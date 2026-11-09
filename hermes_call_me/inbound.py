"""Hand a PIN-verified owner request to the running Hermes, as far as the plugin API allows."""

from __future__ import annotations

from .config import Settings
from .context import get_context


def task_prompt(task: dict) -> str:
    callback = "yes" if task.get("callback_requested") else "no"
    return (
        "The owner phoned Hermes Call Me and passed the PIN on this server. "
        f"Request id: {task['id']}. Kind: {task['kind']}. "
        f"Call back when done: {callback}. "
        f"Their words: {task['text']}\n"
        "Treat this as the owner's request. "
        "If they asked for a callback, do the work and then call call_report "
        f"with inbound_task_id={task['id']!r} and channel web unless they asked for a phone call. "
        "Do not say you called them unless call_report says the report was delivered. "
        "If instructions on a help call are null, do not invent them from a transcript."
    )


def deliver(task: dict, settings: Settings) -> dict:
    """Try to wake the live session. A false result is not a dropped task.

    Hermes exposes ``ctx.inject_message`` for a live CLI session, and for a
    gateway session only when that call accepts ``session_key`` and the
    operator turned on gateway injection. It does not give a plugin a way to
    start a brand-new unattended run. When injection is refused, the task
    stays pending and ``pre_llm_call`` shows it on the next turn, which does
    not by itself wake a sleeping agent.
    """
    ctx = get_context()
    prompt = task_prompt(task)
    if ctx is None or not hasattr(ctx, "inject_message"):
        return {
            "delivered": False,
            "limit": (
                "No live Hermes session is attached to this process. "
                "The request is saved. It will be added to the next turn "
                "(pre_llm_call). That hook does not start a new run by itself, "
                "so Hermes has to be in a session already, or you open one."
            ),
        }
    try:
        if settings.gateway_session_key:
            ok = ctx.inject_message(prompt, role="user", session_key=settings.gateway_session_key)
        else:
            ok = ctx.inject_message(prompt, role="user")
    except TypeError:
        try:
            ok = bool(ctx.inject_message(prompt))
        except Exception as exc:
            return {
                "delivered": False,
                "limit": f"inject_message failed ({exc}). The request is saved for the next turn.",
            }
    except Exception as exc:
        return {
            "delivered": False,
            "limit": f"inject_message failed ({exc}). The request is saved for the next turn.",
        }
    if not ok:
        return {
            "delivered": False,
            "limit": (
                "inject_message returned false. On the gateway this needs a live "
                "session and plugins.entries.hermes-call-me.allow_gateway_injection, "
                "plus HERMES_CALL_ME_GATEWAY_SESSION_KEY when the session is not the "
                "CLI. The request is saved and will show up on the next turn. "
                "That does not start a run on its own."
            ),
        }
    return {"delivered": True, "limit": ""}
