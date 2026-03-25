"""Risk classification engine — extracted from orchestrator.py for testability.

Separating risk logic into its own module keeps ``orchestrator.py`` focused on
pipeline orchestration while making classification rules easy to unit-test and
extend independently.
"""

import re
from typing import Optional

# Pre-compiled word-boundary patterns for risk classification.
# Using word boundaries \\b avoids false positives like "pay" in "payment"
# or "book" in "bookmarked".

_LOW_RISK_PATTERNS = re.compile(
    r"\b(status|summary|explain|advice|check[- ]?in)\b",
    re.IGNORECASE,
)
_MEDIUM_RISK_PATTERNS = re.compile(
    r"\b(remind|commitment|deadline|schedule|plan|promise|follow[- ]up)\b",
    re.IGNORECASE,
)
_HIGH_RISK_PATTERNS = re.compile(
    r"\b(send email|book(?:ing)?|purchase|pay(?:ment)?|external api|execute|delete)\b",
    re.IGNORECASE,
)
_APPROVAL_ELIGIBLE_ACTION_TYPES = {
    "create_agent",
    "create_job",
    "workspace_delete",
    "workspace_mutation",
    "workspace_restore",
}


def classify_risk(text: str) -> str:
    """Return 'high', 'medium', or 'low' based on keyword patterns in *text*."""
    if _HIGH_RISK_PATTERNS.search(text):
        return "high"
    if _MEDIUM_RISK_PATTERNS.search(text):
        return "medium"
    if _LOW_RISK_PATTERNS.search(text):
        return "low"
    return "low"


def infer_action_type(text: str) -> str:
    """Return a coarse action-type label for the given user message."""
    lowered = text.lower()
    if "status" in lowered or "summary" in lowered:
        return "status"
    if "check-in" in lowered or "checkin" in lowered:
        return "check-in"
    if "remind" in lowered:
        return "reminder"
    if "commitment" in lowered or "promise" in lowered:
        return "commitment"
    if "deadline" in lowered:
        return "deadline"
    return "message"


def is_approval_eligible_action_type(action_type: str | None) -> bool:
    """Return True only for executable action types that can be approved."""
    return str(action_type or "").strip().lower() in _APPROVAL_ELIGIBLE_ACTION_TYPES


def should_require_approval(
    user_message: str,
    response_text: str,
    approval_policy: str = "auto",
    require_approval: Optional[bool] = None,
    action_type: Optional[str] = None,
) -> tuple[bool, str, str]:
    """Determine whether a response requires human approval.

    Returns (needs_approval, risk_level, action_type).
    Override flag ``require_approval`` takes precedence over the policy string.
    """
    resolved_action_type = action_type or infer_action_type(user_message)
    if require_approval is True:
        risk_level = classify_risk(f"{user_message}\n{response_text}")
        return True, risk_level, resolved_action_type
    if require_approval is False and approval_policy == "never":
        return False, "low", resolved_action_type

    if approval_policy == "always":
        risk_level = classify_risk(f"{user_message}\n{response_text}")
        return True, risk_level, resolved_action_type
    elif approval_policy == "never":
        return False, "low", resolved_action_type
    elif approval_policy == "auto":
        # Auto approval is based on the user's requested intent, not incidental
        # keywords in the assistant reply or injected search context.
        risk_level = classify_risk(f"{resolved_action_type}\n{user_message}")
        needs_approval = risk_level in {"medium", "high"} and resolved_action_type not in {"status", "check-in"}
        return needs_approval, risk_level, resolved_action_type
    else:
        raise ValueError(f"Unknown approval_policy: {approval_policy!r}")
