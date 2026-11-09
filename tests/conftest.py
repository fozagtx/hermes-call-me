"""Isolated env and database for every test. No test should see a real API key."""

from __future__ import annotations

import pytest

_NAMES = (
    "CALLE_API_KEY",
    "CALLE_BASE_URL",
    "HERMES_CALL_ME_PIN",
    "HERMES_CALL_ME_OWNER_NUMBER",
    "HERMES_CALL_ME_REGION",
    "HERMES_CALL_ME_LOCALE",
    "HERMES_CALL_ME_GUARD",
    "HERMES_CALL_ME_RISKY_TOOLS",
    "HERMES_CALL_ME_TIMEOUT_SECONDS",
    "HERMES_CALL_ME_DAILY_CAP",
    "HERMES_CALL_ME_QUIET_HOURS",
    "HERMES_CALL_ME_QUIET_HOURS_ENABLED",
    "HERMES_CALL_ME_TIMEZONE",
    "HERMES_CALL_ME_APPROVAL_TTL_SECONDS",
    "HERMES_HOME",
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_CALL_ME_DB", str(tmp_path / "calls.db"))
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)
    from hermes_call_me import store

    store.close_db()
    yield
    store.close_db()


def configure(monkeypatch, **extra):
    values = {
        "CALLE_API_KEY": "calle-test-key",
        "HERMES_CALL_ME_PIN": "2468",
        "HERMES_CALL_ME_OWNER_NUMBER": "+14155550100",
        "HERMES_CALL_ME_TIMEOUT_SECONDS": "30",
    }
    values.update(extra)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
