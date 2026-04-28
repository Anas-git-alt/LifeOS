#!/usr/bin/env python3
"""Compare baseline Capture V2 splitting against a Hermes sidecar model."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.capture_v2 import (  # noqa: E402
    _extract_json,
    _normalise_capture_item,
    _residue_from_coverage,
    split_capture_message,
)
from app.services.provider_router import chat_completion  # noqa: E402

HERMES_MODEL = "nousresearch/hermes-3-llama-3.1-405b:free"
TRANSCRIPTS = [
    {
        "name": "promise_memory_habit",
        "message": (
            "I promised to send the client invoice tomorrow at 9am, "
            "remember that I prefer client calls after Asr, and I want a nightly sleep routine again"
        ),
        "expected_types": ["reminder", "memory", "habit"],
        "expected_count": 3,
        "require_followup": False,
    },
    {
        "name": "reminder_wording",
        "message": "remind me to submit the tax return request from hr on Monday before 4:30pm",
        "expected_types": ["reminder"],
        "expected_count": 1,
        "require_followup": False,
    },
    {
        "name": "remember_that",
        "message": "remember that morning sunlight helps reset my energy",
        "expected_types": ["memory"],
        "expected_count": 1,
        "require_followup": False,
    },
    {
        "name": "daily_log_mix",
        "message": "slept 7h bedtime 23:40 wake 07:10, meal done, training done, prayed Asr on time",
        "expected_types": ["daily_log", "daily_log", "daily_log", "daily_log"],
        "expected_count": 4,
        "require_followup": False,
    },
    {
        "name": "ambiguous_hr",
        "message": "sort out the admin thing with HR maybe sometime next week",
        "expected_types": ["idea"],
        "expected_count": 1,
        "require_followup": True,
    },
]


def build_prompt(message: str, *, timezone_name: str = "UTC", route_hint: str = "auto") -> str:
    return (
        "You are LifeOS Capture V2. Extract every important item from one messy capture message.\n"
        "Return JSON only with this exact shape:\n"
        "{"
        "\"captured_items\":[{"
        "\"type\":\"commitment|reminder|task|goal|habit|routine|memory|meeting_note|daily_log|question|idea\","
        "\"domain\":\"deen|family|work|health|planning\","
        "\"title\":\"...\","
        "\"summary\":\"...\","
        "\"source_span\":\"exact copied text from the original message\","
        "\"confidence\":0.0,"
        "\"due_at\":\"ISO-8601 datetime or null\","
        "\"recurrence\":\"string or null\","
        "\"needs_follow_up\":false,"
        "\"follow_up_questions\":[],"
        "\"suggested_destination\":\"life_item|memory_review|meeting_context|daily_log|needs_answer\""
        "}],"
        "\"uncaptured_residue\":[\"...\"]"
        "}\n"
        "Rules:\n"
        "- Capture every meaningful promise, reminder, task, goal, habit, routine, memory, meeting note, daily log, question, or idea.\n"
        "- Do not merge unrelated items.\n"
        "- Copy source_span verbatim from the message.\n"
        "- If a fragment is meaningful but ambiguous, still capture it and set needs_follow_up=true.\n"
        "- Put leftover meaningful text in uncaptured_residue.\n"
        "- If there is no residue, return an empty array.\n"
        f"- Local timezone: {timezone_name}.\n"
        f"- Route hint: {route_hint}.\n"
        f"Message:\n{message}"
    )


def parse_sidecar_response(raw: str, message: str):
    parsed = _extract_json(str(raw or "")) or {}
    raw_items = parsed.get("captured_items") or parsed.get("items") or []
    items = [_normalise_capture_item(item, message) for item in raw_items if isinstance(item, dict)]
    residue = _residue_from_coverage(
        message,
        [item.source_span for item in items],
        [str(item) for item in (parsed.get("uncaptured_residue") or []) if isinstance(item, str)],
    )
    return items, residue


def evaluate(items, residue, transcript: dict) -> dict:
    types = [item.type for item in items]
    count_ok = len(items) == transcript["expected_count"]
    types_ok = types == transcript["expected_types"]
    followup_ok = True
    if transcript["require_followup"]:
        followup_ok = any(item.needs_follow_up for item in items)
    residue_ok = not residue if transcript["expected_count"] > 1 else True
    return {
        "count_ok": count_ok,
        "types_ok": types_ok,
        "followup_ok": followup_ok,
        "residue_ok": residue_ok,
        "score": sum([count_ok, types_ok, followup_ok, residue_ok]),
        "types": types,
        "residue": residue,
    }


async def main() -> None:
    results = []
    for transcript in TRANSCRIPTS:
        baseline_items, baseline_residue = await split_capture_message(
            message=transcript["message"],
            timezone_name="UTC",
            route_hint="auto",
        )
        hermes_raw = await chat_completion(
            messages=[
                {"role": "system", "content": "You return strict JSON only."},
                {"role": "user", "content": build_prompt(transcript["message"])},
            ],
            provider="openrouter",
            model=HERMES_MODEL,
            temperature=0.1,
            max_tokens=1800,
        )
        hermes_items, hermes_residue = parse_sidecar_response(hermes_raw, transcript["message"])
        results.append(
            {
                "name": transcript["name"],
                "baseline": evaluate(baseline_items, baseline_residue, transcript),
                "hermes": evaluate(hermes_items, hermes_residue, transcript),
            }
        )
    print(json.dumps({"model": HERMES_MODEL, "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
