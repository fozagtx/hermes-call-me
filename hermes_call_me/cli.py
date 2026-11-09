"""``hermes call-me`` and ``python -m hermes_call_me``."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_settings, scrub
from .vapi import VapiError


def serve() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load_settings()
    from .server import serve_forever

    port = settings.webhook_port
    print(f"Demo page:  http://127.0.0.1:{port}/demo")
    print(f"Webhook:    http://127.0.0.1:{port}/vapi/webhook")
    print("Point cloudflared (or similar) at this port.")
    print("Set HERMES_CALL_ME_WEBHOOK_URL to the https origin, with no path.")
    if not settings.vapi_api_key or not settings.owner_pin or not settings.webhook_secret:
        print("The page will load. Starting a call still needs VAPI_API_KEY,")
        print("HERMES_CALL_ME_PIN, HERMES_CALL_ME_WEBHOOK_SECRET, and the public URL.")
    try:
        serve_forever(settings)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def configure_number() -> int:
    settings = load_settings()
    from .config import require_call_config
    from .vapi import configure_phone_number

    try:
        require_call_config(settings, "phone" if settings.phone_calls_enabled else "web")
        if not settings.vapi_phone_number_id:
            raise ConfigError("VAPI_PHONE_NUMBER_ID is not set. Nothing was changed.")
        result = configure_phone_number(settings)
    except (ConfigError, VapiError) as exc:
        print(scrub(str(exc), settings), file=sys.stderr)
        return 1
    number = result.get("number") or result.get("id") or settings.vapi_phone_number_id
    print(f"Inbound assistant requests for {number} now come to the webhook.")
    return 0


def recent() -> int:
    from . import store

    rows = store.recent_calls(10)
    tasks = store.pending_tasks(10)
    if not rows and not tasks:
        print("No calls yet.")
        return 0
    for row in rows:
        cost = row.get("cost_usd")
        cost_text = "" if cost is None else f" ${cost:.4f}"
        print(
            f"{row['created_at']}  {row['channel']:5}  {row['purpose']:10}  "
            f"{row['status']:12}  {row.get('reason') or '-'}{cost_text}  {row['id']}"
        )
    for task in tasks:
        print(f"pending {task['kind']:6}  callback={bool(task['callback_requested'])}  {task['id']}  {task['text'][:80]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-call-me")
    subs = parser.add_subparsers(dest="command")
    subs.add_parser("serve", help="Run the webhook and the local demo page")
    subs.add_parser("configure-number", help="Point the Vapi phone number at this webhook")
    subs.add_parser("recent", help="Print recent calls and pending owner requests")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve()
    if args.command == "configure-number":
        return configure_number()
    if args.command == "recent":
        return recent()
    parser.print_help()
    return 2


def setup_cli(subparser) -> None:
    subs = subparser.add_subparsers(dest="call_me_command")
    subs.add_parser("serve", help="Run the webhook and the local demo page")
    subs.add_parser("configure-number", help="Point the Vapi phone number at this webhook")
    subs.add_parser("recent", help="Print recent calls")
    subparser.set_defaults(func=cli_main)


def cli_main(args) -> None:
    command = getattr(args, "call_me_command", None)
    if command == "serve":
        raise SystemExit(serve())
    if command == "configure-number":
        raise SystemExit(configure_number())
    if command == "recent":
        raise SystemExit(recent())
    print("Usage: hermes call-me <serve|configure-number|recent>")


def slash_status(raw_args: str, **kwargs) -> str:
    del raw_args, kwargs
    from . import store

    try:
        rows = store.recent_calls(5)
        tasks = store.pending_tasks(5)
    except Exception as exc:
        return f"hermes-call-me could not read its database: {exc}"
    lines = ["Hermes Call Me"]
    if not rows:
        lines.append("No calls yet.")
    for row in rows:
        lines.append(
            f"- {row['created_at']} {row['channel']} {row['purpose']} "
            f"{row['status']} ({row.get('reason') or '-'})"
        )
    if tasks:
        lines.append("Pending owner requests:")
        for task in tasks:
            lines.append(f"- {task['id']} {task['kind']}: {task['text'][:120]}")
    return "\n".join(lines)
