import json
from urllib.parse import parse_qs, urlparse

from hermes_call_me import service, store
from hermes_call_me.webhook import handle_body
from tests.conftest import configure


def _created(payload):
    query = parse_qs(urlparse(payload["assistant"]["server"]["url"]).query)
    return query["hermes_call_id"][0], {
        "id": "vapi_test",
        "status": "queued",
        "transport": {"provider": "daily", "callUrl": "https://vapi.daily.co/room-demo"},
        "monitor": {"controlUrl": "https://api.vapi.ai/control/demo"},
    }


def test_web_approval_uses_real_client_shape_and_webhook_result(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr("hermes_call_me.server.ensure_server", lambda settings: None)
    seen = {}

    def fake_create(payload, settings, **kwargs):
        seen["payload"] = payload
        call_id, created = _created(payload)
        from hermes_call_me.config import load_settings

        current = load_settings()
        handle_body(
            {"message": {"type": "tool-calls", "toolCallList": [
                {"id": "p", "function": {"name": "verify_pin", "arguments": {"pin": "2468"}}}
            ]}},
            settings=current,
            query_call_id=call_id,
        )
        handle_body(
            {"message": {"type": "tool-calls", "toolCallList": [
                {"id": "d", "function": {"name": "record_decision", "arguments": {"decision": "approved"}}}
            ]}},
            settings=current,
            query_call_id=call_id,
        )
        handle_body(
            {"message": {"type": "end-of-call-report", "endedReason": "assistant-ended-call",
                         "artifact": {"transcript": "Owner approved."}, "cost": 0.08, "durationSeconds": 30}},
            settings=current,
            query_call_id=call_id,
        )
        return created

    monkeypatch.setattr(service, "create_call", fake_create)
    result = service.run_approval(
        {"action": "deploy_prod", "risk": "high", "summary": "Ship checkout.", "channel": "web"}
    )
    assert seen["payload"]["transport"]["provider"] == "daily"
    assert "phoneNumberId" not in seen["payload"]
    assert result["result"] == "approved"
    assert result["approved"] is True
    assert result["pin_verified"] is True
    assert result["join_url"] == "https://vapi.daily.co/room-demo"
    assert result["cost_usd"] == 0.08
    assert "Owner approved." in result["transcript"]
    assert store.claim_approval("deploy_prod")["summary"] == "Ship checkout."


def test_help_without_tool_text_does_not_invent_instructions(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr("hermes_call_me.server.ensure_server", lambda settings: None)

    def fake_create(payload, settings, **kwargs):
        call_id, created = _created(payload)
        from hermes_call_me.config import load_settings

        current = load_settings()
        handle_body(
            {"message": {"type": "tool-calls", "toolCallList": [
                {"id": "p", "function": {"name": "verify_pin", "arguments": {"pin": "2468"}}}
            ]}},
            settings=current,
            query_call_id=call_id,
        )
        handle_body(
            {"message": {"type": "end-of-call-report", "endedReason": "customer-ended-call",
                         "analysis": {"structuredData": {"instructions": "restart it", "decision": "none"}},
                         "artifact": {"transcript": "User: restart the worker"}}},
            settings=current,
            query_call_id=call_id,
        )
        return created

    monkeypatch.setattr(service, "create_call", fake_create)
    result = service.run_help({"issue": "500s", "what_i_tried": "rollback", "channel": "web"})
    assert result["instructions"] is None
    assert result["reason"] == "unclear"


def test_missing_api_key_does_not_call_vapi(monkeypatch):
    configure(monkeypatch, VAPI_API_KEY="")
    called = {"n": 0}

    def boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("Vapi was called without a key")

    monkeypatch.setattr(service, "create_call", boom)
    from hermes_call_me import tools

    result = json.loads(tools.call_for_approval({"action": "deploy", "risk": "high", "summary": "ship"}))
    assert called["n"] == 0
    assert result["ok"] is False
    assert result["approved"] is False
    assert result["result"] == "no_answer"
    assert "VAPI_API_KEY" in result["error"]


def test_phone_payload_and_flag(monkeypatch):
    configure(monkeypatch, HERMES_CALL_ME_PHONE_CALLS="1", HERMES_CALL_ME_PROVIDER="vapi")
    monkeypatch.setattr("hermes_call_me.server.ensure_server", lambda settings: None)
    seen = {}

    def fake_create(payload, settings, **kwargs):
        seen["payload"] = payload
        return {"id": "vapi_phone", "status": "queued"}

    monkeypatch.setattr(service, "create_call", fake_create)
    monkeypatch.setattr(service.time, "sleep", lambda _s: None)
    state = {"n": 0}

    def mono():
        state["n"] += 1
        return 0 if state["n"] < 4 else 10_000

    monkeypatch.setattr(service.time, "monotonic", mono)
    monkeypatch.setattr(service, "get_call", lambda *a, **k: {"id": "vapi_phone", "status": "queued"})
    monkeypatch.setattr(service, "end_call", lambda *a, **k: None)
    result = service.run_approval(
        {"action": "deploy_prod", "risk": "high", "summary": "Ship.", "channel": "phone"}
    )
    assert seen["payload"]["phoneNumberId"] == "phone_test"
    assert seen["payload"]["customer"]["number"] == "+233200000000"
    assert "transport" not in seen["payload"]
    assert result["result"] == "no_answer"
    assert result["approved"] is False
    assert result["channel"] == "phone"


def test_vapi_error_is_scrubbed(monkeypatch):
    import pytest

    from hermes_call_me.vapi import VapiError

    configure(monkeypatch)
    monkeypatch.setattr("hermes_call_me.server.ensure_server", lambda settings: None)

    def fake_create(payload, settings, **kwargs):
        raise VapiError("Vapi POST failed (401): bad test-vapi-key and pin 2468")

    monkeypatch.setattr(service, "create_call", fake_create)
    with pytest.raises(VapiError) as caught:
        service.run_approval({"action": "deploy", "risk": "high", "summary": "ship", "channel": "web"})
    assert "test-vapi-key" not in str(caught.value)
    assert "2468" not in str(caught.value)
