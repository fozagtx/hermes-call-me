"""The risky-tool guard. It never places a call or opens a socket."""

from __future__ import annotations

import json
import re

from .config import ConfigError, _bool, _first, load_settings
from .policy import DEFAULT_RISKY_PATTERNS
from . import store

_OURS = {"call_for_approval", "call_for_help", "call_report"}


def _guard_requested() -> bool:
    """A value that cannot be read as true or false turns the guard on."""
    try:
        return _bool(_first("HERMES_CALL_ME_GUARD", "guard_enabled", False), False, "HERMES_CALL_ME_GUARD")
    except ConfigError:
        return True


def guard_tool(tool_name, args=None, **kwargs):
    """Block risky tools until ``call_for_approval`` has a fresh, unused approval.

    The hook itself cannot place the phone call. Hermes stops a hook after
    about 30 seconds, and a call is allowed to run for about three minutes.
    The hook tells the model to call ``call_for_approval`` and then retry.
    """
    del kwargs
    name = str(tool_name or "")
    if name in _OURS:
        return None
    if not _guard_requested():
        return None
    try:
        settings = load_settings()
    except ConfigError as exc:
        return {"action": "block", "message": str(exc)}
    patterns = settings.risky_tool_patterns or DEFAULT_RISKY_PATTERNS
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            return {
                "action": "block",
                "message": (
                    f"HERMES_CALL_ME_RISKY_TOOLS has an invalid pattern {pattern!r}: {exc}. "
                    "No risky tool will run until that pattern is fixed."
                ),
            }
    if not any(pattern.search(name) for pattern in compiled):
        return None
    try:
        granted = store.claim_approval(name)
    except Exception as exc:
        return {
            "action": "block",
            "message": f"Could not read approval records ({exc}). {name} was not run.",
        }
    if granted is not None:
        return None
    preview = json.dumps(args, default=str, ensure_ascii=False)[:500] if args else "{}"
    return {
        "action": "block",
        "message": (
            f"Blocked {name}. This tool matches the risky-tool guard. "
            f"Call call_for_approval with action exactly {name!r}, "
            "risk set to high, medium, or low, and a summary that describes "
            f"these arguments: {preview}. "
            "The owner must say the PIN and then approve. "
            "If the result is not approved, do not retry. "
            "An approval is single-use and expires."
        ),
    }
