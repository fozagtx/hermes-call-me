"""``hermes call-me recent``, ``/call-me``, and ``python -m hermes_call_me``."""

from __future__ import annotations

import argparse


def _lines(limit: int) -> list[str]:
    from . import store

    rows = store.recent_calls(limit)
    if not rows:
        return ["No calls yet."]
    return [
        f"{row['created_at']}  {row['purpose']:8}  {row['status']:11}  "
        f"{row.get('reason') or '-':18}  {row['id']}"
        for row in rows
    ]


def recent() -> int:
    for line in _lines(10):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-call-me")
    subs = parser.add_subparsers(dest="command")
    subs.add_parser("recent", help="Print recent calls")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "recent":
        return recent()
    build_parser().print_help()
    return 2


def setup_cli(subparser) -> None:
    subs = subparser.add_subparsers(dest="call_me_command")
    subs.add_parser("recent", help="Print recent calls")
    subparser.set_defaults(func=cli_main)


def cli_main(args) -> None:
    if getattr(args, "call_me_command", None) == "recent":
        raise SystemExit(recent())
    print("Usage: hermes call-me recent")


def slash_status(raw_args: str, **kwargs) -> str:
    del raw_args, kwargs
    try:
        lines = _lines(5)
    except Exception as exc:
        return f"hermes-call-me could not read its database: {exc}"
    return "\n".join(["Hermes Call Me: recent calls"] + lines)
