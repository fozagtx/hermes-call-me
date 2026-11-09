"""Tool handlers. Each returns a JSON string and does not raise."""

from __future__ import annotations

import json

from .config import ConfigError, scrub
from .service import run_approval, run_help, run_report


def _fail(exc: Exception, *, approval: bool) -> str:
    payload = {
        "ok": False,
        "reason": "error",
        "error": scrub(str(exc)),
    }
    if approval:
        payload["result"] = "no_answer"
        payload["approved"] = False
    return json.dumps(payload)


def _run(name: str, runner, args, *, approval: bool) -> str:
    try:
        if not isinstance(args, dict):
            raise ConfigError(f"{name} expected an object of arguments.")
        return json.dumps(runner(args))
    except Exception as exc:
        return _fail(exc, approval=approval)


def call_for_approval(args, **kwargs) -> str:
    del kwargs
    return _run("call_for_approval", run_approval, args, approval=True)


def call_for_help(args, **kwargs) -> str:
    del kwargs
    return _run("call_for_help", run_help, args, approval=False)


def call_report(args, **kwargs) -> str:
    del kwargs
    return _run("call_report", run_report, args, approval=False)
