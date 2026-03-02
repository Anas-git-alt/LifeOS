"""Orchestrator policy tests."""

from app.services.orchestrator import classify_risk, should_require_approval


def test_classify_risk_low():
    assert classify_risk("status update please") == "low"


def test_classify_risk_high():
    assert classify_risk("please send email and execute purchase") == "high"


def test_approval_auto_medium_high():
    needs, risk, action_type = should_require_approval(
        user_message="remind me about my deadline tomorrow",
        response_text="I will set reminder",
        approval_policy="auto",
    )
    assert risk in {"medium", "high"}
    assert action_type in {"reminder", "deadline", "message"}
    assert needs is True


def test_approval_never_forced_off():
    needs, risk, _ = should_require_approval(
        user_message="deadline",
        response_text="will do",
        approval_policy="never",
    )
    assert needs is False
    assert risk == "low"
