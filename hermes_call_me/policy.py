"""Call policy: one allowlisted number, a daily cap, quiet hours, and the PIN.

The PIN comparison is this plugin's job. The CALL-E agent never learns the
PIN and cannot approve a call by claiming the PIN matched.
"""

from __future__ import annotations

import hmac
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import ConfigError, Settings

# Used when the operator does not override risky_tool_patterns.
DEFAULT_RISKY_PATTERNS: tuple[str, ...] = (
    r"deploy",
    r"destroy",
    r"delete",
    r"drop",
    r"purge",
    r"wipe",
    r"payment",
    r"payout",
    r"refund",
    r"charge",
    r"transfer",
    r"terraform",
    r"kubectl",
    r"migrate",
)


def pin_digits(pin: str) -> str:
    return "".join(ch for ch in (pin or "") if ch.isdigit())


def pin_matches(spoken: str, expected: str) -> bool:
    got = pin_digits(spoken)
    want = pin_digits(expected)
    if not got or len(got) != len(want):
        return False
    return hmac.compare_digest(got, want)


def _minutes(hhmm: str) -> int:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm.strip())
    if match is None:
        raise ConfigError(
            "HERMES_CALL_ME_QUIET_HOURS must look like 22:00-07:00. "
            f"Could not read {hhmm!r}."
        )
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ConfigError(f"HERMES_CALL_ME_QUIET_HOURS has an impossible time: {hhmm!r}.")
    return hour * 60 + minute


def in_quiet_hours(now: datetime, window: str, zone_name: str) -> bool:
    if "-" not in window:
        raise ConfigError(
            "HERMES_CALL_ME_QUIET_HOURS must look like 22:00-07:00, "
            f"got {window!r}."
        )
    start_text, end_text = window.split("-", 1)
    start = _minutes(start_text)
    end = _minutes(end_text)
    if start == end:
        return False
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(
            f"HERMES_CALL_ME_TIMEZONE {zone_name!r} is not a known timezone. "
            "America/New_York is the default."
        ) from exc
    local = now.astimezone(zone)
    current = local.hour * 60 + local.minute
    if start < end:
        return start <= current < end
    return current >= start or current < end


def check_outbound(settings: Settings, *, now: datetime | None = None, recent_calls: int) -> None:
    """Refuse the call before CALL-E is contacted."""
    if settings.daily_call_cap == 0 or recent_calls >= settings.daily_call_cap:
        raise ConfigError(
            f"Daily call cap reached ({recent_calls} of {settings.daily_call_cap} "
            "in the last 24 hours). No call was placed. Raise "
            "HERMES_CALL_ME_DAILY_CAP if this is intentional."
        )
    if settings.quiet_hours_enabled:
        moment = now or datetime.now(timezone.utc)
        if in_quiet_hours(moment, settings.quiet_hours, settings.owner_timezone):
            raise ConfigError(
                f"Quiet hours are {settings.quiet_hours} ({settings.owner_timezone}). "
                "No call was placed. Set HERMES_CALL_ME_QUIET_HOURS_ENABLED=0 to "
                "allow calls during that window."
            )
