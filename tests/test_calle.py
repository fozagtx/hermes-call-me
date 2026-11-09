"""Contract tests for the CALL-E one-shot adapter. HTTP is scripted here only."""

import json

from hermes_call_me import calle, service
from hermes_call_me.calle_call import build_request, interpret
from hermes_call_me.config import load_settings
from tests.conftest import configure


def _settings(monkeypatch, **extra):
    configure(
        monkeypatch,
        HERMES_CALL_ME_PHONE_CALLS="1",
        HERMES_CALL_ME_OWNER_NUMBER="+14155550100",
        CALLE_API_KEY="calle-test-key",
        HERMES_CALL_ME_REGION="US",
        **extra,
    )
    return load_settings()


def test_request_matches_v2_contract(monkeypatch):
    settings = _settings(monkeypatch)
    body = build_request(
        "approval",
        {"action": "deploy_prod", "risk": "high", "summary": "Ship checkout."},
        settings,
        local_id="call_local",
        one_time="135790",
    )
    assert body["phone"] == "+14155550100"
    assert body["region"] == "US"
    assert body["locale"] == "en-US"
    schema = body["result_schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["decision"]["enum"] == ["approved", "denied", "unclear"]
    assert "2468" not in body["task"]
    assert "1 3 5 7 9 0" in body["task"]
    assert "Ship checkout." in body["task"]


def test_busy_shape_from_docs_is_not_approval():
    call = {
        "status": "completed",
        "call_outcome": "busy",
        "result_status": "unavailable",
        "transcript": [],
        "result": None,
        "error": None,
    }
    outcome = interpret(call, purpose="approval", pin="2468", one_time="135790")
    assert outcome["reason"] == "no_answer"
    assert outcome["pin_verified"] == 0
    assert outcome["tool_decision"] is None


def test_available_yes_requires_pin_and_code_readback():
    ready = {
        "status": "completed",
        "call_outcome": "completed",
        "result_status": "available",
        "result": {"pin_said": "2468", "code_readback": "135790", "decision": "approved"},
        "transcript": [{"speaker": "user", "text": "approve", "offset_seconds": 4}],
    }
    ok = interpret(ready, purpose="approval", pin="2468", one_time="135790")
    assert ok["reason"] == "approved"
    assert ok["pin_verified"] == 1

    wrong = dict(ready)
    wrong["result"] = {"pin_said": "2468", "code_readback": "000000", "decision": "approved"}
    denied = interpret(wrong, purpose="approval", pin="2468", one_time="135790")
    assert denied["reason"] == "wrong_code"
    assert denied["pin_verified"] == 0

    unclear = dict(ready)
    unclear["result_status"] = "unavailable"
    unclear["result"] = None
    missed = interpret(unclear, purpose="approval", pin="2468", one_time="135790")
    assert missed["reason"] == "unclear"
    assert missed["pin_verified"] == 0


def test_help_drops_instructions_when_pin_is_wrong():
    call = {
        "status": "completed",
        "call_outcome": "completed",
        "result_status": "available",
        "result": {"pin_said": "0000", "instructions": "restart the worker"},
    }
    outcome = interpret(call, purpose="help", pin="2468", one_time="135790")
    assert outcome["tool_instructions"] is None
    assert outcome["pin_verified"] == 0


def test_service_posts_real_path_and_reads_result(monkeypatch):
    settings = _settings(monkeypatch)
    monkeypatch.setattr("hermes_call_me.calle_call.one_time_code", lambda: "135790")
    monkeypatch.setattr("hermes_call_me.server.ensure_server", lambda _settings: None)
    seen = {}

    def http(method, url, api_key, body, extra_headers, timeout):
        assert api_key == "calle-test-key"
        if method == "POST":
            assert url == "https://api.heycall-e.com/v2/calls"
            assert extra_headers["Idempotency-Key"].startswith("hermes-call_")
            seen["body"] = body
            return 202, {
                "id": "call_example",
                "object": "call",
                "status": "queued",
                "result_status": "pending",
                "result": None,
                "error": None,
                "transcript": [],
                "call_id": None,
            }
        assert method == "GET"
        assert url == "https://api.heycall-e.com/v2/calls/call_example"
        return 200, {
            "id": "call_example",
            "call_id": "0123456789abcdef0123456789abcdef",
            "status": "completed",
            "call_outcome": "completed",
            "result_status": "available",
            "result": {"pin_said": "2 4 6 8", "code_readback": "135790", "decision": "approved"},
            "transcript": [
                {"speaker": "bot", "offset_seconds": 0, "text": "Please say your PIN."},
                {"speaker": "user", "offset_seconds": 3, "text": "approve"},
            ],
            "error": None,
        }

    monkeypatch.setattr(calle, "perform_http", http)
    result = service.run_approval(
        {"action": "deploy_prod", "risk": "high", "summary": "Ship checkout.", "channel": "phone"}
    )
    assert seen["body"]["region"] == "US"
    assert result["approved"] is True
    assert result["result"] == "approved"
    assert result["provider"] == "calle"
    assert result["pin_verified"] is True
    assert "approve" in result["transcript"]
    assert "135790" not in json.dumps(result)
    assert settings.owner_pin not in json.dumps(result)


def test_missing_calle_key_does_not_dial(monkeypatch):
    configure(
        monkeypatch,
        HERMES_CALL_ME_PHONE_CALLS="1",
        HERMES_CALL_ME_OWNER_NUMBER="+14155550100",
    )
    called = {"n": 0}

    def boom(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("CALL-E was contacted without a key")

    monkeypatch.setattr(calle, "perform_http", boom)
    from hermes_call_me import tools

    result = json.loads(
        tools.call_for_approval(
            {"action": "deploy", "risk": "high", "summary": "ship", "channel": "phone"}
        )
    )
    assert called["n"] == 0
    assert result["approved"] is False
    assert result["result"] == "no_answer"
    assert "CALLE_API_KEY" in result["error"]
