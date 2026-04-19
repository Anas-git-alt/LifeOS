"""Natural-language parsing helpers for Discord automation commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

DAY_MAP = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
DEFAULT_TIMEZONE = "Africa/Casablanca"
_ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")

_TIME_PATTERN = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
_TIMEZONE_PATTERN = re.compile(r"\b([A-Z][A-Za-z_]+/[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)?)\b")
_AGENT_PATTERN = re.compile(r"(?:\busing\b|\bagent\b)\s+([a-z0-9\-_]+)\b", re.IGNORECASE)
_CHANNEL_ID_PATTERN = re.compile(r"<#(\d+)>")
_CHANNEL_NAME_PATTERN = re.compile(r"#\s*([a-z0-9\-_]+)")
_EXPLICIT_NOTIFY_PATTERN = re.compile(
    r"\b(?:notify|post)\s+(?:in|to)\s+(<#\d+>|#\s*[a-z0-9\-_]+)",
    re.IGNORECASE,
)
_INCOMPLETE_NOTIFY_PATTERN = re.compile(r"\b(?:notify|post)\s+(?:in|to)\b", re.IGNORECASE)
_SILENT_PATTERN = re.compile(
    r"\b(?:silently|silent|background|no discord post|no notification)\b",
    re.IGNORECASE,
)
_RECURRING_PATTERNS = [
    (re.compile(rf"\bevery\s+weekday\s+at\s+{_TIME_PATTERN}\b", re.IGNORECASE), "mon-fri"),
    (re.compile(rf"\bweekdays\s+at\s+{_TIME_PATTERN}\b", re.IGNORECASE), "mon-fri"),
    (re.compile(rf"\bevery\s+day\s+at\s+{_TIME_PATTERN}\b", re.IGNORECASE), "*"),
    (re.compile(rf"\bdaily\s+at\s+{_TIME_PATTERN}\b", re.IGNORECASE), "*"),
    (re.compile(rf"\bweekend\s+at\s+{_TIME_PATTERN}\b", re.IGNORECASE), "sat,sun"),
    (
        re.compile(
            rf"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+{_TIME_PATTERN}\b",
            re.IGNORECASE,
        ),
        None,
    ),
]
_RELATIVE_PATTERN = re.compile(
    r"\bin\s+(\d+)\s*(minutes?|minute|mins?|hours?|hour|hrs?|hr|min)\b",
    re.IGNORECASE,
)
_TODAY_TOMORROW_PATTERN = re.compile(
    rf"\b(today|tomorrow)\s+at\s+{_TIME_PATTERN}\b",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    rf"\bon\s+(\d{{4}}-\d{{2}}-\d{{2}})\s+at\s+{_TIME_PATTERN}\b",
    re.IGNORECASE,
)
_SCHEDULE_KEYWORD_PATTERN = re.compile(
    r"\b(every|daily|weekday|weekdays|weekend|today|tomorrow|on\s+\d{4}-\d{2}-\d{2}|in\s+\d+)\b",
    re.IGNORECASE,
)


def _ensure_utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time_parts(hour_text: str, minute_text: str | None, meridian_text: str | None) -> tuple[int, int] | None:
    hour = int(hour_text)
    minute = int(minute_text or 0)
    meridian = (meridian_text or "").lower().strip()
    if meridian == "pm" and hour < 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour, minute


def _normalize_whitespace(text: str) -> str:
    cleaned = _ZERO_WIDTH_PATTERN.sub("", str(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def _subtract_span(text: str, span: tuple[int, int], *, include_preposition: bool = False) -> tuple[int, int]:
    start, end = span
    if include_preposition:
        prefix = text[:start]
        for token in (" in ", " to "):
            if prefix.endswith(token):
                start -= len(token)
                break
    return start, end


def _strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    cleaned = text
    for start, end in sorted(spans, key=lambda item: item[0], reverse=True):
        cleaned = f"{cleaned[:start]} {cleaned[end:]}"
    cleaned = _normalize_whitespace(cleaned)
    cleaned = re.sub(r"^\bremind me(?:\s+to)?\b\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:in|to)\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.-")


def _format_schedule_error() -> str:
    return (
        "I couldn't parse that schedule. Try `every weekday at 7:30`, "
        "`tomorrow at 9am`, or `in 10 min`."
    )


def _validate_timezone_name(timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
        return True
    except Exception:
        return False


def _parse_notification(text: str) -> dict:
    data: dict[str, str] = {}
    spans: list[tuple[int, int]] = []
    missing: list[str] = []
    errors: list[str] = []
    explicit_notify = _EXPLICIT_NOTIFY_PATTERN.search(text)
    if explicit_notify:
        token = explicit_notify.group(1)
        channel_id_match = _CHANNEL_ID_PATTERN.fullmatch(token)
        channel_name_match = _CHANNEL_NAME_PATTERN.fullmatch(token)
        data["notification_mode"] = "channel"
        if channel_id_match:
            data["target_channel_id"] = channel_id_match.group(1)
        elif channel_name_match:
            data["target_channel"] = channel_name_match.group(1)
        spans.append(explicit_notify.span())
        return {"data": data, "spans": spans, "missing": missing, "errors": errors}

    if _INCOMPLETE_NOTIFY_PATTERN.search(text):
        data["notification_mode"] = "channel"
        missing.append("target_channel")
        return {"data": data, "spans": spans, "missing": missing, "errors": errors}

    silent_match = _SILENT_PATTERN.search(text)
    if silent_match:
        data["notification_mode"] = "silent"
        spans.append(silent_match.span())
        return {"data": data, "spans": spans, "missing": missing, "errors": errors}

    channel_id_match = _CHANNEL_ID_PATTERN.search(text)
    if channel_id_match:
        data["notification_mode"] = "channel"
        data["target_channel_id"] = channel_id_match.group(1)
        spans.append(_subtract_span(text, channel_id_match.span(), include_preposition=True))
        return {"data": data, "spans": spans, "missing": missing, "errors": errors}

    channel_name_match = _CHANNEL_NAME_PATTERN.search(text)
    if channel_name_match:
        data["notification_mode"] = "channel"
        data["target_channel"] = channel_name_match.group(1)
        spans.append(_subtract_span(text, channel_name_match.span(), include_preposition=True))
        return {"data": data, "spans": spans, "missing": missing, "errors": errors}

    data["notification_mode"] = "silent"
    return {"data": data, "spans": spans, "missing": missing, "errors": errors}


def parse_schedule_value(
    text: str,
    *,
    now: datetime | None = None,
    default_timezone: str = DEFAULT_TIMEZONE,
) -> dict:
    normalized_text = _normalize_whitespace(text)
    timezone_name = default_timezone if _validate_timezone_name(default_timezone) else DEFAULT_TIMEZONE
    now_utc = _ensure_utc_now(now)
    local_now = now_utc.astimezone(ZoneInfo(timezone_name))

    relative_match = _RELATIVE_PATTERN.search(normalized_text)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2).lower()
        delta = timedelta(hours=amount) if unit.startswith(("h", "hour")) else timedelta(minutes=amount)
        run_local = local_now + delta
        return {
            "data": {
                "schedule_type": "once",
                "cron_expression": None,
                "run_at": run_local.astimezone(timezone.utc).replace(tzinfo=None),
            },
            "spans": [relative_match.span()],
            "errors": [],
        }

    day_match = _TODAY_TOMORROW_PATTERN.search(normalized_text)
    if day_match:
        parsed_time = _parse_time_parts(day_match.group(2), day_match.group(3), day_match.group(4))
        if parsed_time is None:
            return {"data": {}, "spans": [], "errors": [_format_schedule_error()]}
        hour, minute = parsed_time
        offset_days = 1 if day_match.group(1).lower() == "tomorrow" else 0
        run_local = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=offset_days)
        if run_local <= local_now:
            return {
                "data": {},
                "spans": [],
                "errors": ["That one-time schedule is in the past. Try `tomorrow at 9am` or `in 10 min`."],
            }
        return {
            "data": {
                "schedule_type": "once",
                "cron_expression": None,
                "run_at": run_local.astimezone(timezone.utc).replace(tzinfo=None),
            },
            "spans": [day_match.span()],
            "errors": [],
        }

    date_match = _DATE_PATTERN.search(normalized_text)
    if date_match:
        parsed_time = _parse_time_parts(date_match.group(2), date_match.group(3), date_match.group(4))
        if parsed_time is None:
            return {"data": {}, "spans": [], "errors": [_format_schedule_error()]}
        hour, minute = parsed_time
        try:
            date_value = datetime.strptime(date_match.group(1), "%Y-%m-%d")
        except ValueError:
            return {"data": {}, "spans": [], "errors": [_format_schedule_error()]}
        run_local = datetime(
            year=date_value.year,
            month=date_value.month,
            day=date_value.day,
            hour=hour,
            minute=minute,
            tzinfo=ZoneInfo(timezone_name),
        )
        if run_local <= local_now:
            return {
                "data": {},
                "spans": [],
                "errors": ["That one-time schedule is in the past. Try a future date or `in 10 min`."],
            }
        return {
            "data": {
                "schedule_type": "once",
                "cron_expression": None,
                "run_at": run_local.astimezone(timezone.utc).replace(tzinfo=None),
            },
            "spans": [date_match.span()],
            "errors": [],
        }

    for pattern, day_of_week in _RECURRING_PATTERNS:
        match = pattern.search(normalized_text)
        if not match:
            continue
        if day_of_week is None:
            day_of_week = DAY_MAP[match.group(1).lower()]
            hour_text = match.group(2)
            minute_text = match.group(3)
            meridian_text = match.group(4)
        else:
            hour_text = match.group(1)
            minute_text = match.group(2)
            meridian_text = match.group(3)
        parsed_time = _parse_time_parts(hour_text, minute_text, meridian_text)
        if parsed_time is None:
            return {"data": {}, "spans": [], "errors": [_format_schedule_error()]}
        hour, minute = parsed_time
        return {
            "data": {
                "schedule_type": "cron",
                "cron_expression": f"{minute} {hour} {day_of_week}",
                "run_at": None,
            },
            "spans": [match.span()],
            "errors": [],
        }

    if _SCHEDULE_KEYWORD_PATTERN.search(normalized_text):
        return {"data": {}, "spans": [], "errors": [_format_schedule_error()]}
    return {"data": {}, "spans": [], "errors": []}


def parse_schedule_prompt(
    text: str,
    *,
    now: datetime | None = None,
    default_timezone: str = DEFAULT_TIMEZONE,
) -> dict:
    normalized_text = _normalize_whitespace(text)
    data: dict = {}
    missing: list[str] = []
    errors: list[str] = []
    remove_spans: list[tuple[int, int]] = []

    timezone_match = _TIMEZONE_PATTERN.search(normalized_text)
    timezone_name = timezone_match.group(1) if timezone_match else default_timezone
    if not _validate_timezone_name(timezone_name):
        timezone_name = default_timezone
        errors.append(f"Invalid timezone. Try something like `{DEFAULT_TIMEZONE}`.")
    else:
        data["timezone"] = timezone_name
    if timezone_match:
        remove_spans.append(timezone_match.span())

    notification = _parse_notification(normalized_text)
    data.update(notification["data"])
    missing.extend(notification["missing"])
    errors.extend(notification["errors"])
    remove_spans.extend(notification["spans"])

    agent_match = _AGENT_PATTERN.search(normalized_text)
    if agent_match:
        data["agent_name"] = agent_match.group(1).lower()
        remove_spans.append(agent_match.span())
    else:
        missing.append("agent_name")

    schedule = parse_schedule_value(normalized_text, now=now, default_timezone=data.get("timezone", DEFAULT_TIMEZONE))
    data.update(schedule["data"])
    errors.extend(schedule["errors"])
    remove_spans.extend(schedule["spans"])
    if "schedule_type" not in data:
        missing.append("schedule")

    prompt_template = _strip_spans(normalized_text, remove_spans)
    prompt_template = prompt_template or normalized_text
    data["prompt_template"] = prompt_template
    data["name"] = f"NL: {prompt_template[:80]}"
    data["description"] = f"Natural-language reminder job: {prompt_template}"
    data["job_type"] = "agent_nudge"
    data["source"] = "discord_nl"
    data["created_by"] = "discord"
    data["approval_required"] = True
    data.setdefault("notification_mode", "silent")
    data.setdefault("timezone", DEFAULT_TIMEZONE)
    data.setdefault("target_channel", None)
    data.setdefault("target_channel_id", None)

    return {"data": data, "missing": list(dict.fromkeys(missing)), "errors": list(dict.fromkeys(errors))}


def parse_commitment_prompt(
    text: str,
    *,
    now: datetime | None = None,
    default_timezone: str = DEFAULT_TIMEZONE,
) -> dict:
    normalized_text = _normalize_whitespace(text)
    data: dict = {"timezone": default_timezone}
    errors: list[str] = []
    remove_spans: list[tuple[int, int]] = []

    timezone_match = _TIMEZONE_PATTERN.search(normalized_text)
    timezone_name = timezone_match.group(1) if timezone_match else default_timezone
    if _validate_timezone_name(timezone_name):
        data["timezone"] = timezone_name
    elif timezone_match:
        errors.append(f"Invalid timezone. Try something like `{DEFAULT_TIMEZONE}`.")
    if timezone_match:
        remove_spans.append(timezone_match.span())

    schedule = parse_schedule_value(normalized_text, now=now, default_timezone=data["timezone"])
    errors.extend(schedule["errors"])
    remove_spans.extend(schedule["spans"])
    schedule_type = schedule["data"].get("schedule_type")
    if schedule_type == "once":
        data["due_at"] = schedule["data"].get("run_at")
    elif schedule_type == "cron":
        errors.append("Commitments need a one-time deadline like `tomorrow at 9am` or `in 2 hours`.")

    cleaned_message = _strip_spans(normalized_text, remove_spans)
    data["message"] = cleaned_message or normalized_text
    return {"data": data, "errors": list(dict.fromkeys(errors))}


def parse_agent_prompt(text: str) -> dict:
    lowered = _normalize_whitespace(text).lower()
    data: dict = {}
    missing: list[str] = []

    name_match = re.search(r"(?:named|name)\s+([a-z0-9\-_]+)", lowered)
    if name_match:
        data["name"] = name_match.group(1)
    else:
        missing.append("name")

    purpose_match = re.search(r"(?:for|to)\s+(.+?)(?:\sin\s#|$)", text, re.IGNORECASE)
    if purpose_match:
        purpose = purpose_match.group(1).strip()
        data["description"] = purpose
        data["system_prompt"] = f"You are {data.get('name', 'a LifeOS agent')}. Purpose: {purpose}"
    else:
        missing.append("purpose")

    channel_match = _CHANNEL_NAME_PATTERN.search(lowered)
    if channel_match:
        data["discord_channel"] = channel_match.group(1)
    else:
        missing.append("discord_channel")

    schedule = parse_schedule_value(text, default_timezone=DEFAULT_TIMEZONE)
    if schedule["data"].get("schedule_type") == "cron":
        data["cadence"] = schedule["data"]["cron_expression"]
    else:
        missing.append("cadence")

    if "approval always" in lowered:
        data["config_json"] = {"approval_policy": "always"}
    elif "approval never" in lowered:
        data["config_json"] = {"approval_policy": "never"}
    elif "approval auto" in lowered:
        data["config_json"] = {"approval_policy": "auto"}
    else:
        missing.append("approval_policy")

    data.setdefault("provider", "openrouter")
    data.setdefault("model", "openrouter/auto")
    data.setdefault("enabled", True)

    return {"data": data, "missing": missing}
