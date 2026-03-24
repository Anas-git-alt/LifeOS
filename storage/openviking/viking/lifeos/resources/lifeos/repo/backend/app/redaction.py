"""Basic sensitive value redaction utilities."""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"(sk-[A-Za-z0-9]{12,})"),
    re.compile(r"([A-Za-z0-9_\-]*api[_\-]?key[\"'\s:=]+)([A-Za-z0-9._\-]{8,})", re.IGNORECASE),
]


def redact_sensitive(value: str) -> str:
    text = value or ""
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text
