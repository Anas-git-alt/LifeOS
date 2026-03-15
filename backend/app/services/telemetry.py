"""In-memory telemetry store for LLM provider performance tracking.

This module provides lightweight, zero-dependency tracking of per-provider
metrics (latency, token usage, success/failure counts). Data is held in-process
and resets on restart — it is intentionally not persisted so it has no DB
migration cost. The ``ExperimentRun`` table (created separately) handles
persistent experiment records.

Usage::

    from app.services.telemetry import record_call, get_provider_stats

    # After each LLM call:
    record_call("openrouter", "meta/llama-3", latency_ms=342, tokens=812, success=True)

    # From the /api/telemetry endpoint:
    stats = get_provider_stats()
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

# Maximum number of recent calls to retain per provider for rolling averages.
_WINDOW_SIZE = 200

_lock = Lock()


@dataclass
class _ProviderWindow:
    latencies: deque = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))
    token_counts: deque = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))
    failures: int = 0
    successes: int = 0
    last_called_at: Optional[float] = None
    last_model: Optional[str] = None

    # Circuit-breaker state: track recent failures in a rolling 60-second window.
    recent_failure_times: deque = field(default_factory=lambda: deque())

    @property
    def circuit_open(self) -> bool:
        """Return True if this provider has tripped its circuit breaker.

        The breaker trips when >= 3 failures occur within a 60-second window.
        """
        now = time.monotonic()
        # Prune stale failure timestamps
        while self.recent_failure_times and now - self.recent_failure_times[0] > 60:
            self.recent_failure_times.popleft()
        return len(self.recent_failure_times) >= 3

    def record_failure(self) -> None:
        self.failures += 1
        self.recent_failure_times.append(time.monotonic())

    def reset_circuit(self) -> None:
        """Manually reset circuit breaker (e.g., after a successful call)."""
        self.recent_failure_times.clear()


_windows: dict[str, _ProviderWindow] = defaultdict(_ProviderWindow)


def record_call(
    provider: str,
    model: Optional[str],
    latency_ms: float,
    tokens: int,
    success: bool,
) -> None:
    """Record a single LLM call for in-memory telemetry.

    Thread-safe — uses a module-level lock so async + sync callers are safe.
    """
    with _lock:
        w = _windows[provider]
        w.last_called_at = time.time()
        w.last_model = model
        if success:
            w.latencies.append(latency_ms)
            w.token_counts.append(tokens)
            w.successes += 1
            w.reset_circuit()
        else:
            w.record_failure()


def is_circuit_open(provider: str) -> bool:
    """Return True if the given provider's circuit breaker is currently tripped."""
    with _lock:
        return _windows[provider].circuit_open


def get_provider_stats() -> list[dict]:
    """Return a list of per-provider telemetry snapshots.

    Each dict contains:
    - ``provider``: provider name
    - ``avg_latency_ms``: rolling average latency (None if no data)
    - ``avg_tokens``: rolling average token count
    - ``successes``: total successful calls
    - ``failures``: total failed calls
    - ``circuit_open``: whether circuit breaker is tripped
    - ``last_called_at``: Unix timestamp of last call (None if never called)
    - ``last_model``: most recently used model name
    """
    with _lock:
        result = []
        for provider, w in _windows.items():
            lats = list(w.latencies)
            toks = list(w.token_counts)
            result.append(
                {
                    "provider": provider,
                    "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else None,
                    "avg_tokens": round(sum(toks) / len(toks)) if toks else None,
                    "successes": w.successes,
                    "failures": w.failures,
                    "circuit_open": w.circuit_open,
                    "last_called_at": w.last_called_at,
                    "last_model": w.last_model,
                }
            )
        return result


def reset_all() -> None:
    """Clear all telemetry state — intended for tests only."""
    with _lock:
        _windows.clear()
