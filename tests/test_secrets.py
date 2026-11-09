import sys
import types

from hermes_call_me.config import load_settings


def test_hermes_secret_scope_wins_over_process_env(monkeypatch):
    monkeypatch.setenv("CALLE_API_KEY", "other-profile-key")
    scope = types.ModuleType("agent.secret_scope")
    scope.get_secret = lambda name: {"CALLE_API_KEY": "active-profile-key"}.get(name)
    agent = types.ModuleType("agent")
    agent.secret_scope = scope
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", scope)
    assert load_settings().calle_api_key == "active-profile-key"


def test_standalone_reads_process_env(monkeypatch):
    monkeypatch.setitem(sys.modules, "agent.secret_scope", None)
    monkeypatch.setenv("CALLE_API_KEY", "standalone-key")
    assert load_settings().calle_api_key == "standalone-key"


class _Ctx:
    def __init__(self, values):
        self.values = values

    def get_config(self, key, default=None):
        return self.values.get(key, default)


def test_inside_hermes_profile_config_wins_over_process_env(monkeypatch):
    from hermes_call_me.context import set_context

    monkeypatch.setenv("HERMES_CALL_ME_OWNER_NUMBER", "+19990000000")
    set_context(_Ctx({"owner_number": "+14155550100"}))
    try:
        assert load_settings().owner_number == "+14155550100"
    finally:
        set_context(None)


def test_guard_value_that_is_not_a_boolean_turns_the_guard_on(monkeypatch):
    from hermes_call_me.hooks import guard_tool

    monkeypatch.setenv("HERMES_CALL_ME_GUARD", "maybe")
    monkeypatch.setenv("HERMES_CALL_ME_PIN", "2468")
    blocked = guard_tool("deploy_prod", {})
    assert blocked is not None and blocked["action"] == "block"
