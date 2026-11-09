import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Ctx:
    def __init__(self):
        self.tools = []
        self.hooks = []
        self.skills = []
        self.commands = []
        self.cli = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs["name"])

    def register_hook(self, name, fn):
        assert "kwargs" in fn.__code__.co_varnames
        self.hooks.append(name)

    def register_skill(self, name, path):
        self.skills.append(name)

    def register_cli_command(self, **kwargs):
        self.cli.append(kwargs["name"])

    def register_command(self, name, handler, description=""):
        self.commands.append(name)


def test_declared_tools_match_registered_tools():
    text = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    declared = []
    hooks = []
    bucket = None
    for line in text.splitlines():
        if line.startswith("provides_tools:"):
            bucket = declared
            continue
        if line.startswith("provides_hooks:"):
            bucket = hooks
            continue
        if bucket is not None:
            if line.startswith("  - "):
                bucket.append(line.split("-", 1)[1].strip())
                continue
            if line and not line.startswith(" "):
                bucket = None
    spec = importlib.util.spec_from_file_location("hermes_call_me_plugin", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ctx = Ctx()
    module.register(ctx)
    assert ctx.tools == declared
    assert ctx.hooks == hooks
    assert ctx.skills == ["call-me"]
    assert ctx.cli == ["call-me"]
    assert "mock" not in (ROOT / "hermes_call_me" / "vapi.py").read_text(encoding="utf-8").lower()
