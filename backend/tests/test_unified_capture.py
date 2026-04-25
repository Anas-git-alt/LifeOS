from __future__ import annotations

import pytest

from app.models import CommitmentCaptureResponse, IntakeCaptureResponse, UnifiedCaptureRequest
from app.routers.life import _select_capture_route, capture_life


def test_unified_capture_route_selector_sorts_common_inputs():
    assert _select_capture_route(UnifiedCaptureRequest(message="Send invoice tomorrow at 9am")) == "commitment"
    assert _select_capture_route(UnifiedCaptureRequest(message="Meeting notes: decided to keep one capture inbox")) == "memory"
    assert _select_capture_route(UnifiedCaptureRequest(message="I want to build better sleep habits")) == "intake"


@pytest.mark.asyncio
async def test_unified_capture_commitment_facade(monkeypatch):
    async def _fake_capture_commitment(data):
        assert data.message == "Send invoice tomorrow at 9am"
        assert data.source == "webui_today_capture"
        return CommitmentCaptureResponse(
            response="Tracked.",
            auto_promoted=True,
            needs_follow_up=False,
        )

    monkeypatch.setattr("app.routers.life.capture_commitment", _fake_capture_commitment)

    result = await capture_life(
        UnifiedCaptureRequest(
            message="Send invoice tomorrow at 9am",
            source="webui_today_capture",
        )
    )

    assert result.route == "commitment"
    assert result.response == "Tracked."
    assert result.auto_promoted_count == 1


@pytest.mark.asyncio
async def test_unified_capture_intake_facade(monkeypatch):
    async def _fake_capture_inbox(data):
        assert data.message == "I want to build better sleep habits"
        assert data.source == "webui_today_capture"
        return IntakeCaptureResponse(
            response="Captured.",
            entries=[],
            life_items=[],
            wiki_proposals=[],
            auto_promoted_count=0,
        )

    monkeypatch.setattr("app.routers.life.capture_inbox", _fake_capture_inbox)

    result = await capture_life(
        UnifiedCaptureRequest(
            message="I want to build better sleep habits",
            source="webui_today_capture",
        )
    )

    assert result.route == "intake"
    assert result.response == "Captured."
