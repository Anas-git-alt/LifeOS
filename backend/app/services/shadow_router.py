"""Shadow router — asynchronously tests alternative LLM providers on a sample of traffic.

Design principles (from agency-autonomous-optimization-architect skill):
- NEVER blocks the user's response — all shadow calls are fire-and-forget.
- NEVER auto-promotes a provider — only surfaces a candidate in the ApprovalQueue.
- Grades outputs with a transparent, deterministic scoring heuristic.
- Stores all results in the experiment_runs table for audit and trend analysis.

Usage (called from provider_router.py after a successful primary call)::

    from app.services.shadow_router import maybe_shadow_test
    asyncio.create_task(maybe_shadow_test(messages, primary_result, primary_provider, primary_model))
"""

import asyncio
import logging
import random
import time
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Percentage of successful primary calls that trigger a shadow test (0.0 – 1.0).
SHADOW_SAMPLE_RATE: float = 0.05  # 5%

# Number of consecutive shadow wins required before surfacing a promotion candidate.
PROMOTION_THRESHOLD: int = 10

# Minimum length ratio between shadow and primary output to count as "comparable".
_MIN_LENGTH_RATIO: float = 0.4

# Error phrases that indicate a bad/failed response.
_ERROR_PHRASES = [
    "i'm sorry, i cannot",
    "i apologize, i cannot",
    "as an ai, i don't",
    "error:",
    "traceback",
    "i'm unable to",
]


def _score_output(text: str, reference: str) -> float:
    """Return a score in [0, 1] for *text* relative to *reference*.

    Scoring heuristic:
    - 0.0  if empty or contains error phrases
    - +0.4 base for non-empty
    - +0.3 for length ratio within acceptable range
    - +0.3 for no error phrases detected
    """
    if not text or not text.strip():
        return 0.0

    lowered = text.lower()
    if any(phrase in lowered for phrase in _ERROR_PHRASES):
        return 0.1  # Not zero — the model responded — but poor quality

    score = 0.4  # Base: non-empty
    ref_len = len(reference) or 1
    ratio = len(text) / ref_len
    if _MIN_LENGTH_RATIO <= ratio <= 3.0:
        score += 0.3  # Length comparable to primary
    score += 0.3  # No error phrases
    return round(score, 2)


def _pick_shadow_provider(primary_provider: str) -> Optional[tuple[str, str]]:
    """Return (provider_name, model) for the shadow call, or None if unavailable."""
    from app.services.provider_router import PROVIDERS, free_mode_rejection
    from app.services import telemetry

    candidates = []
    for name, config in PROVIDERS.items():
        if name == primary_provider:
            continue
        api_key = getattr(settings, config["api_key_attr"], "")
        if not api_key:
            continue
        if telemetry.is_circuit_open(name):
            continue
        default_model = getattr(settings, config["default_model_attr"], "")
        if free_mode_rejection(name, default_model):
            continue
        candidates.append((name, default_model))

    if not candidates:
        return None
    return random.choice(candidates)


async def _run_shadow_call(
    messages: list[dict],
    primary_result: str,
    primary_provider: str,
    primary_model: Optional[str],
    shadow_provider: str,
    shadow_model: Optional[str],
) -> None:
    """Execute the shadow call and persist the experiment result."""
    from app.services.provider_router import _call_provider

    t0 = time.monotonic()
    shadow_text = ""
    success = False
    try:
        shadow_text = await asyncio.wait_for(
            _call_provider(shadow_provider, shadow_model, messages, 0.7, 1024, enable_shadow=False),
            timeout=30.0,  # Hard cap — shadow must not run forever
        )
        success = True
    except Exception as exc:
        logger.debug("Shadow call to '%s' failed: %s", shadow_provider, exc)

    latency_ms = (time.monotonic() - t0) * 1000

    primary_score = _score_output(primary_result, primary_result)
    shadow_score = _score_output(shadow_text, primary_result) if success else 0.0

    # Cost estimate: $/1M tokens rough estimates (not authoritative)
    _cost_per_1m = {
        "openrouter": 0.80,
        "nvidia": 0.40,
        "google": 0.35,
        "openai": 2.50,
    }
    est_tokens = len(primary_result.split()) * 1.3  # rough token count
    cost_estimate = (_cost_per_1m.get(shadow_provider, 1.0) / 1_000_000) * est_tokens

    try:
        from app.services.experiment_log import log_run, check_for_promotion_candidate
        await log_run(
            primary_provider=primary_provider,
            primary_model=primary_model or "",
            shadow_provider=shadow_provider,
            shadow_model=shadow_model or "",
            primary_score=primary_score,
            shadow_score=shadow_score,
            shadow_latency_ms=latency_ms,
            cost_estimate=cost_estimate,
        )
        await check_for_promotion_candidate(shadow_provider, threshold=PROMOTION_THRESHOLD)
    except Exception as exc:
        logger.warning("Failed to persist experiment run: %s", exc)


async def maybe_shadow_test(
    messages: list[dict],
    primary_result: str,
    primary_provider: str,
    primary_model: Optional[str] = None,
) -> None:
    """Fire-and-forget shadow test. Call with asyncio.create_task()."""
    if not settings.shadow_router_enabled:
        return
    if random.random() > SHADOW_SAMPLE_RATE:
        return  # Not sampled this call

    candidate = _pick_shadow_provider(primary_provider)
    if not candidate:
        return

    shadow_provider, shadow_model = candidate
    logger.debug(
        "Shadow test: primary=%s shadow=%s (%.0f%% sample rate)",
        primary_provider,
        shadow_provider,
        SHADOW_SAMPLE_RATE * 100,
    )
    await _run_shadow_call(
        messages=messages,
        primary_result=primary_result,
        primary_provider=primary_provider,
        primary_model=primary_model,
        shadow_provider=shadow_provider,
        shadow_model=shadow_model,
    )
