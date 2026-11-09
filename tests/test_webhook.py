import json

from hermes_call_me import store
from hermes_call_me.assistant import build_assistant, build_call_payload
from hermes_call_me.config import load_settings
from hermes_call_me.webhook import handle_body
from tests.conftest import configure


def _settings(monkeypatch):
    configure(monkeypatch)
    return load_settings()


def test_web_payload_has_no_phone_fields(monkeypatch):
    settings = _settings(monkeypatch)
    assistant = build_assistant(settings, purpose="approval", call_id="call_1", facts={"action": "deploy", "risk": "high", "summary": "ship it"})
    payload = build_call_payload(settings, channel="web", assistant=assistant, name="demo")
    assert payload["transport"]["provider"] == "daily"
    assert "phoneNumberId" not in payload
    assert "customer" not in payload
    assert assistant["analysisPlan"]["structuredDataPlan"]["enabled"] is True
    assert "decision" in assistant["analysisPlan"]["structuredDataPlan"]["schema"]["properties"]
    url = assistant["server"]["url"]
    assert url.startswith("https://demo.example.com/vapi/webhook?hermes_call_id=call_1")
    assert assistant["server"]["headers"]["Authorization"] == "Bearer test-webhook-secret"
    assert assistant["server"]["headers"]["X-Vapi-Secret"] == "test-webhook-secret"
    names = [tool.get("function", {}).get("name") for tool in assistant["model"]["tools"]]
    assert "verify_pin" in names
    assert "record_decision" in names
    assert settings.owner_pin not in json.dumps(assistant)


def test_phone_payload_dials_only_the_owner(monkeypatch):
    settings = _settings(monkeypatch)
    assistant = build_assistant(settings, purpose="help", call_id="call_2", facts={"issue": "down", "what_i_tried": "restart"})
    payload = build_call_payload(settings, channel="phone", assistant=assistant, name="phone")
    assert payload["phoneNumberId"] == "phone_test"
    assert payload["customer"] == {"number": "+233200000000"}
    assert "transport" not in payload


def test_webhook_rejects_bad_secret_and_accepts_bearer(monkeypatch):
    from hermes_call_me.server import Handler, _token_ok

    settings = _settings(monkeypatch)
    assert _token_ok("test-webhook-secret", settings.webhook_secret)
    assert _token_ok("nope", settings.webhook_secret) is False
    assert _token_ok("", settings.webhook_secret) is False

    class Dummy(Handler):
        def __init__(self):
            self.headers = {"Authorization": "Bearer test-webhook-secret", "X-Vapi-Secret": ""}
            self._status = None
            self._payload = None

        def _json(self, status, payload):
            self._status = status
            self._payload = payload

    ok = Dummy()
    ok._webhook(b'{"message": {"type": "status-update", "status": "ringing"}}', {})
    assert ok._status == 200

    class Bad(Dummy):
        def __init__(self):
            super().__init__()
            self.headers = {"Authorization": "Bearer wrong", "X-Vapi-Secret": ""}

    bad = Bad()
    bad._webhook(b"{}", {})
    assert bad._status == 401


def test_end_of_call_cannot_approve_from_structured_data(monkeypatch):
    settings = _settings(monkeypatch)
    row = store.create_call(direction="outbound", channel="web", purpose="approval", status="in_progress")
    body = {
        "message": {
            "type": "end-of-call-report",
            "endedReason": "customer-ended-call",
            "call": {"id": "vapi_x"},
            "analysis": {"structuredData": {"decision": "approved", "instructions": "ship it"}},
            "artifact": {"transcript": "AI: do you approve? User: yes I think so."},
            "cost": 0.11,
        }
    }
    status, payload = handle_body(body, settings=settings, query_call_id=row["id"])
    assert status == 200
    assert payload["ok"] is True
    saved = store.get_call(row["id"])
    assert saved["reason"] == "no_pin"
    assert saved["status"] == "no_answer"
    assert saved["pin_verified"] == 0
    assert "ship it" not in (saved["tool_instructions"] or "")
    assert saved["cost_usd"] == 0.11
    assert "yes I think so" in saved["transcript"]
    assert store.has_approval(row["id"]) is False


def test_pin_then_decision_approves_and_stores_grant(monkeypatch):
    settings = _settings(monkeypatch)
    row = store.create_call(direction="outbound", channel="web", purpose="approval", status="in_progress")
    store.update_call(row["id"], guard_action="deploy_prod", guard_summary="ship checkout", guard_risk="high")
    pin_body = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {"id": "t1", "function": {"name": "verify_pin", "arguments": {"pin": "24-68"}}}
            ],
        }
    }
    _status, result = handle_body(pin_body, settings=settings, query_call_id=row["id"])
    parsed = json.loads(result["results"][0]["result"])
    assert parsed["ok"] is True
    assert "2468" not in result["results"][0]["result"]
    decision = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {"id": "t2", "function": {"name": "record_decision", "arguments": {"decision": "approved"}}}
            ],
        }
    }
    handle_body(decision, settings=settings, query_call_id=row["id"])
    handle_body(
        {
            "message": {
                "type": "end-of-call-report",
                "endedReason": "assistant-ended-call",
                "artifact": {"transcript": "PIN ok. Owner said approve."},
                "cost": {"total": 0.09},
                "durationSeconds": 42,
            }
        },
        settings=settings,
        query_call_id=row["id"],
    )
    saved = store.get_call(row["id"])
    assert saved["reason"] == "approved"
    assert saved["duration_seconds"] == 42
    assert saved["cost_usd"] == 0.09
    grant = store.claim_approval("deploy_prod")
    assert grant is not None
    assert store.claim_approval("deploy_prod") is None


def test_wrong_pin_blocks_a_later_decision(monkeypatch):
    settings = _settings(monkeypatch)
    row = store.create_call(direction="outbound", channel="web", purpose="approval", status="in_progress")
    for _ in range(2):
        handle_body(
            {
                "message": {
                    "type": "tool-calls",
                    "toolCallList": [
                        {"id": "t", "function": {"name": "verify_pin", "arguments": "{\"pin\": \"0000\"}"}}
                    ],
                }
            },
            settings=settings,
            query_call_id=row["id"],
        )
    _status, result = handle_body(
        {
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {"id": "t3", "function": {"name": "record_decision", "arguments": {"decision": "approved"}}}
                ],
            }
        },
        settings=settings,
        query_call_id=row["id"],
    )
    parsed = json.loads(result["results"][0]["result"])
    assert parsed["ok"] is False
    saved = store.get_call(row["id"])
    assert saved["tool_decision"] in (None, "")


def test_inbound_rejects_other_numbers_and_accepts_owner(monkeypatch):
    settings = _settings(monkeypatch)
    status, payload = handle_body(
        {"message": {"type": "assistant-request", "call": {"id": "in_1", "customer": {"number": "+14155550100"}}}},
        settings=settings,
    )
    assert status == 200
    assert "error" in payload
    assert "assistant" not in payload

    status, payload = handle_body(
        {"message": {"type": "assistant-request", "call": {"id": "in_2", "customer": {"number": "+233200000000"}}}},
        settings=settings,
    )
    assert "assistant" in payload
    assert payload["assistant"]["server"]["url"].startswith("https://demo.example.com/vapi/webhook")
    row = store.get_by_vapi("in_2")
    assert row["direction"] == "inbound"
    assert row["purpose"] == "inbound"
