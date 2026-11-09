"""Isolated env and database for every test. No test should see a real API key."""

from __future__ import annotations

import pytest

_SECRETS = (
    "VAPI_API_KEY",
    "HERMES_CALL_ME_PIN",
    "HERMES_CALL_ME_WEBHOOK_SECRET",
    "HERMES_CALL_ME_WEBHOOK_URL",
    "HERMES_CALL_ME_OWNER_NUMBER",
    "VAPI_PHONE_NUMBER_ID",
    "HERMES_CALL_ME_PHONE_CALLS",
    "HERMES_CALL_ME_GUARD",
    "HERMES_CALL_ME_CHANNEL",
    "HERMES_CALL_ME_TIMEOUT_SECONDS",
    "HERMES_CALL_ME_DAILY_CAP",
    "HERMES_CALL_ME_QUIET_HOURS",
    "HERMES_CALL_ME_QUIET_HOURS_ENABLED",
    "HERMES_CALL_ME_TIMEZONE",
    "HERMES_CALL_ME_PORT",
    "HERMES_CALL_ME_RISKY_TOOLS",
    "HERMES_CALL_ME_GATEWAY_SESSION_KEY",
    "HERMES_CALL_ME_PROVIDER",
    "HERMES_CALL_ME_REGION",
    "HERMES_CALL_ME_LOCALE",
    "CALLE_API_KEY",
    "CALLE_BASE_URL",
    "HERMES_HOME",
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_CALL_ME_DB", str(tmp_path / "calls.db"))
    for name in _SECRETS:
        monkeypatch.delenv(name, raising=False)
    from hermes_call_me import store

    store.close_db()
    yield
    store.close_db()


def configure(monkeypatch, **extra):
    values = {
        "VAPI_API_KEY": "test-vapi-key",
        "HERMES_CALL_ME_PIN": "2468",
        "HERMES_CALL_ME_WEBHOOK_SECRET": "test-webhook-secret",
        "HERMES_CALL_ME_WEBHOOK_URL": "https://demo.example.com",
        "HERMES_CALL_ME_OWNER_NUMBER": "+233200000000",
        "VAPI_PHONE_NUMBER_ID": "phone_test",
        "HERMES_CALL_ME_TIMEOUT_SECONDS": "30",
        "HERMES_CALL_ME_PORT": "8799",
    }
    values.update(extra)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
