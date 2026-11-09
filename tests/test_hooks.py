from hermes_call_me import store
from hermes_call_me.hooks import guard_tool
from tests.conftest import configure


def test_guard_is_off_by_default():
    assert guard_tool("deploy_prod", {"target": "prod"}) is None


def test_guard_blocks_then_allows_one_use(monkeypatch):
    configure(monkeypatch, HERMES_CALL_ME_GUARD="1")
    blocked = guard_tool("deploy_prod", {"target": "prod"})
    assert blocked["action"] == "block"
    assert "call_for_approval" in blocked["message"]
    assert "deploy_prod" in blocked["message"]
    assert guard_tool("read_file", {"path": "README.md"}) is None
    assert guard_tool("call_for_approval", {"action": "deploy_prod"}) is None

    row = store.create_call(purpose="approval", owner_number="+14155550100", one_time_code="135790")
    store.save_approval(call_id=row["id"], action="deploy_prod", summary="ship", risk="high", ttl_seconds=600)
    assert guard_tool("deploy_prod", {"target": "prod"}) is None
    again = guard_tool("deploy_prod", {"target": "prod"})
    assert again["action"] == "block"


def test_guard_does_not_exempt_other_call_prefixed_tools(monkeypatch):
    configure(monkeypatch, HERMES_CALL_ME_GUARD="1")
    blocked = guard_tool("call_payment_api", {"amount": 100})
    assert blocked is not None
    assert blocked["action"] == "block"
