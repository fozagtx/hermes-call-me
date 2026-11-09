"""``register(ctx)``: wires tools, hooks, the skill and commands. Opens no sockets."""

from __future__ import annotations

from pathlib import Path

from . import schemas, tools
from .cli import cli_main, setup_cli, slash_status
from .context import set_context
from .hooks import guard_tool

TOOLSET = "hermes_call_me"
SKILL = Path(__file__).resolve().parent.parent / "skills" / "call-me" / "SKILL.md"

_TOOLS = (
    ("call_for_approval", schemas.CALL_FOR_APPROVAL, tools.call_for_approval),
    ("call_for_help", schemas.CALL_FOR_HELP, tools.call_for_help),
    ("call_report", schemas.CALL_REPORT, tools.call_report),
)


def register(ctx) -> None:
    set_context(ctx)
    for name, schema, handler in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            description=schema["description"],
        )
    ctx.register_hook("pre_tool_call", guard_tool)

    register_skill = getattr(ctx, "register_skill", None)
    if register_skill is not None and SKILL.is_file():
        register_skill("call-me", SKILL)

    register_cli = getattr(ctx, "register_cli_command", None)
    if register_cli is not None:
        register_cli(
            name="call-me",
            help="Recent CALL-E calls to the owner",
            setup_fn=setup_cli,
            handler_fn=cli_main,
        )

    register_command = getattr(ctx, "register_command", None)
    if register_command is not None:
        try:
            register_command(
                "call-me",
                handler=slash_status,
                description="Show recent Hermes Call Me calls",
            )
        except TypeError:
            register_command("call-me", slash_status, "Show recent Hermes Call Me calls")
