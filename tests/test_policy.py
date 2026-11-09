from datetime import datetime, timezone

import pytest

from hermes_call_me.config import ConfigError
from hermes_call_me.policy import (
    caller_allowed,
    check_outbound,
    in_quiet_hours,
    numbers_match,
    pin_matches,
)
from tests.conftest import configure


class _Settings:
    def __init__(self, **kwargs):
        defaults = dict(
            owner_number="+233200000000",
            daily_call_cap=8,
            quiet_hours="22:00-07:00",
            quiet_hours_enabled=False,
            owner_timezone="Africa/Accra",
        )
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_pin_matches_digits_only():
    assert pin_matches("24 68", "2468")
    assert pin_matches("two 468", "2468") is False
    assert pin_matches("24680", "2468") is False
    assert pin_matches("", "2468") is False


def test_allowlist_is_one_number():
    assert numbers_match("+233200000000", "+233 200 000 000")
    assert numbers_match("+233200000000", "+233200000001") is False
    assert numbers_match("+233200000000", "233200000000") is False


def test_quiet_hours_cross_midnight():
    zone = "Africa/Accra"
    late = datetime(2026, 11, 8, 22, 30, tzinfo=timezone.utc)
    morning = datetime(2026, 11, 8, 6, 59, tzinfo=timezone.utc)
    day = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(late, "22:00-07:00", zone)
    assert in_quiet_hours(morning, "22:00-07:00", zone)
    assert in_quiet_hours(day, "22:00-07:00", zone) is False


def test_unknown_timezone_fails_loud():
    with pytest.raises(ConfigError):
        in_quiet_hours(datetime.now(timezone.utc), "22:00-07:00", "Not/AZone")


def test_daily_cap_blocks_before_any_call():
    settings = _Settings(daily_call_cap=2)
    with pytest.raises(ConfigError, match="Daily call cap"):
        check_outbound(settings, "web", recent_calls=2)


def test_quiet_hours_block_when_enabled():
    settings = _Settings(quiet_hours_enabled=True)
    late = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
    with pytest.raises(ConfigError, match="Quiet hours"):
        check_outbound(settings, "web", now=late, recent_calls=0)


def test_caller_allowlist_fails_closed():
    settings = _Settings()
    assert caller_allowed(settings, "+233200000000")
    assert caller_allowed(settings, "+233200000001") is False
    assert caller_allowed(settings, "") is False
    settings.owner_number = ""
    assert caller_allowed(settings, "+233200000000") is False


def test_phone_requires_explicit_enable(monkeypatch):
    from hermes_call_me.config import load_settings, require_call_config

    configure(monkeypatch)
    settings = load_settings()
    require_call_config(settings, "web")
    with pytest.raises(ConfigError, match="Phone calls are off"):
        require_call_config(settings, "phone")


def test_missing_key_names_the_variable(monkeypatch):
    from hermes_call_me.config import load_settings, require_call_config

    configure(monkeypatch, VAPI_API_KEY="")
    with pytest.raises(ConfigError, match="VAPI_API_KEY"):
        require_call_config(load_settings(), "web")


def test_localhost_webhook_is_refused(monkeypatch):
    from hermes_call_me.config import load_settings, require_call_config

    configure(monkeypatch, HERMES_CALL_ME_WEBHOOK_URL="http://127.0.0.1:8787")
    with pytest.raises(ConfigError, match="https"):
        require_call_config(load_settings(), "web")
