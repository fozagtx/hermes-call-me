import sys
import types

from hermes_call_me.config import load_settings


def test_hermes_secret_scope_wins_over_process_env(monkeypatch):
    monkeypatch.setenv("VAPI_API_KEY", "other-profile-key")
    scope = types.ModuleType("agent.secret_scope")
    scope.get_secret = lambda name: {"VAPI_API_KEY": "active-profile-key"}.get(name)
    agent = types.ModuleType("agent")
    agent.secret_scope = scope
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.secret_scope", scope)
    assert load_settings().vapi_api_key == "active-profile-key"


def test_standalone_reads_process_env(monkeypatch):
    monkeypatch.setitem(sys.modules, "agent.secret_scope", None)
    monkeypatch.setenv("VAPI_API_KEY", "standalone-key")
    assert load_settings().vapi_api_key == "standalone-key"
