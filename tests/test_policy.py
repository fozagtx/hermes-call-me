from datetime import datetime, timezone

import pytest

from hermes_call_me.config import ConfigError
from hermes_call_me.policy import check_outbound, in_quiet_hours, pin_matches
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
        check_outbound(settings, recent_calls=2)


def test_quiet_hours_block_when_enabled():
    settings = _Settings(quiet_hours_enabled=True)
    late = datetime(2026, 11, 8, 23, 0, tzinfo=timezone.utc)
    with pytest.raises(ConfigError, match="Quiet hours"):
        check_outbound(settings, now=late, recent_calls=0)


def test_every_required_value_is_checked_before_dialing(monkeypatch):
    from hermes_call_me.config import load_settings, require_call_config

    configure(monkeypatch)
    require_call_config(load_settings())
    for name, value, message in (
        ("HERMES_CALL_ME_PIN", "", "HERMES_CALL_ME_PIN"),
        ("HERMES_CALL_ME_PIN", "12a4", "4 to 12 digits"),
        ("HERMES_CALL_ME_OWNER_NUMBER", "4155550100", "E.164"),
        ("CALLE_API_KEY", "", "CALLE_API_KEY"),
    ):
        configure(monkeypatch, **{name: value})
        with pytest.raises(ConfigError, match=message):
            require_call_config(load_settings())


def test_region_is_inferred_by_default_and_must_be_two_letters_when_set(monkeypatch):
    from hermes_call_me.config import load_settings

    configure(monkeypatch)
    assert load_settings().calle_region == ""
    assert load_settings().calle_locale == ""
    configure(monkeypatch, HERMES_CALL_ME_REGION="USA")
    with pytest.raises(ConfigError, match="two-letter"):
        load_settings()


def test_listed_countries_pass_and_unlisted_ones_are_refused_before_dialing(monkeypatch):
    from hermes_call_me.config import load_settings, require_call_config

    for number in ("+14155550100", "+447700900123", "+919812345678", "+358401234567", "+8801712345678"):
        configure(monkeypatch, HERMES_CALL_ME_OWNER_NUMBER=number)
        require_call_config(load_settings())
    configure(monkeypatch, HERMES_CALL_ME_OWNER_NUMBER="+233201234567")
    with pytest.raises(ConfigError, match="isn't listed"):
        require_call_config(load_settings())
    configure(monkeypatch, HERMES_CALL_ME_OWNER_NUMBER="+233201234567", HERMES_CALL_ME_REGION="GH")
    require_call_config(load_settings())
