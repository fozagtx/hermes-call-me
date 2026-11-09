"""SQLite call log and single-use approvals.

Inside Hermes this opens ``plugin_db("hermes-call-me")``, which is
``<HERMES_HOME>/plugin-data/hermes-call-me/data.db``. Outside Hermes it uses
that same path. ``HERMES_CALL_ME_DB`` points at a specific file; tests set it.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_key: str | None = None

_CALL_COLUMNS = {
    "calle_call_id",
    "one_time_code",
    "status",
    "reason",
    "decision",
    "pin_verified",
    "instructions",
    "reply",
    "transcript",
    "ended_reason",
    "error",
    "guard_action",
    "guard_summary",
    "guard_risk",
    "ended_at",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_calls (
    id TEXT PRIMARY KEY,
    calle_call_id TEXT,
    purpose TEXT NOT NULL,
    owner_number TEXT NOT NULL,
    one_time_code TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    decision TEXT,
    pin_verified INTEGER NOT NULL DEFAULT 0,
    instructions TEXT,
    reply TEXT,
    transcript TEXT,
    ended_reason TEXT,
    error TEXT,
    guard_action TEXT,
    guard_summary TEXT,
    guard_risk TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX IF NOT EXISTS phone_calls_created ON phone_calls (created_at);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    risk TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    consumed_tool TEXT
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    current = moment or utcnow()
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def close_db() -> None:
    global _conn, _key
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _key = None


def _sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _connect() -> sqlite3.Connection:
    override = os.environ.get("HERMES_CALL_ME_DB", "").strip()
    if override:
        return _sqlite(Path(override))
    try:
        from plugins.plugin_storage import plugin_db
    except ImportError:
        root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
        return _sqlite(root / "plugin-data" / "hermes-call-me" / "data.db")
    conn = plugin_db("hermes-call-me")
    conn.row_factory = sqlite3.Row
    return conn


def open_db() -> sqlite3.Connection:
    global _conn, _key
    key = os.environ.get("HERMES_CALL_ME_DB", "").strip() or "plugin_db"
    with _lock:
        if _conn is not None and _key == key:
            return _conn
        if _conn is not None:
            _conn.close()
        conn = _connect()
        conn.executescript(_SCHEMA)
        conn.commit()
        _conn = conn
        _key = key
        return conn


def _row(row) -> dict | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _write(fn):
    conn = open_db()
    with _lock:
        result = fn(conn)
        conn.commit()
        return result


class CallRefused(Exception):
    """Another call is active, or the daily cap is reached. Nothing was dialed."""


def reserve_call(
    *,
    purpose: str,
    owner_number: str,
    one_time_code: str,
    daily_cap: int,
    stale_after_seconds: int,
) -> dict:
    """Check "one call at a time" and the daily cap, then insert, in one transaction.

    ``BEGIN IMMEDIATE`` takes SQLite's write lock first, so two tool calls
    (or two processes sharing this file) cannot both pass the checks.
    """
    call_id = "call_" + uuid.uuid4().hex
    now = utcnow()
    conn = open_db()
    with _lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            active = conn.execute(
                "SELECT * FROM phone_calls WHERE status IN ('starting', 'in_progress') "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if active is not None:
                started = datetime.strptime(active["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if (now - started).total_seconds() <= stale_after_seconds:
                    raise CallRefused(
                        f"A call is already in progress ({active['id']}, {active['purpose']}). "
                        "Wait for it to finish before starting another. Nothing new was dialed."
                    )
                conn.execute(
                    "UPDATE phone_calls SET status = 'timeout', reason = 'timeout', one_time_code = '', "
                    "updated_at = ?, ended_at = ? WHERE id = ?",
                    (iso(now), iso(now), active["id"]),
                )
            since = iso(now - timedelta(hours=24))
            used = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM phone_calls WHERE calle_call_id IS NOT NULL AND created_at >= ?",
                    (since,),
                ).fetchone()["n"]
            )
            if daily_cap == 0 or used >= daily_cap:
                raise CallRefused(
                    f"Daily call cap reached ({used} of {daily_cap} in the last 24 hours). "
                    "No call was placed. Raise HERMES_CALL_ME_DAILY_CAP if this is intentional."
                )
            conn.execute(
                """
                INSERT INTO phone_calls (
                    id, purpose, owner_number, one_time_code, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'starting', ?, ?)
                """,
                (call_id, purpose, owner_number, one_time_code, iso(now), iso(now)),
            )
            row = _row(conn.execute("SELECT * FROM phone_calls WHERE id = ?", (call_id,)).fetchone())
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
        return row


def update_call(call_id: str, **fields) -> dict | None:
    unknown = set(fields) - _CALL_COLUMNS
    if unknown:
        raise ValueError(f"unknown call columns: {sorted(unknown)}")
    fields["updated_at"] = iso()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    values = list(fields.values()) + [call_id]

    def run(conn):
        conn.execute(f"UPDATE phone_calls SET {assignments} WHERE id = ?", values)
        return _row(conn.execute("SELECT * FROM phone_calls WHERE id = ?", (call_id,)).fetchone())

    return _write(run)


def get_call(call_id: str) -> dict | None:
    def run(conn):
        return _row(conn.execute("SELECT * FROM phone_calls WHERE id = ?", (call_id,)).fetchone())

    return _write(run)


def count_recent_calls(hours: int = 24) -> int:
    """Calls CALL-E accepted in the window. A refused create does not count."""
    since = iso(utcnow() - timedelta(hours=hours))

    def run(conn):
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM phone_calls WHERE calle_call_id IS NOT NULL AND created_at >= ?",
            (since,),
        ).fetchone()
        return int(row["n"])

    return _write(run)


def recent_calls(limit: int = 8) -> list[dict]:
    def run(conn):
        rows = conn.execute(
            "SELECT * FROM phone_calls ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row(row) for row in rows]

    return _write(run)


def save_approval(*, call_id: str, action: str, summary: str, risk: str, ttl_seconds: int) -> dict:
    approval_id = "apr_" + uuid.uuid4().hex
    created = utcnow()
    expires = created + timedelta(seconds=ttl_seconds)

    def run(conn):
        conn.execute(
            """
            INSERT INTO approvals (id, call_id, action, summary, risk, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (approval_id, call_id, action, summary, risk, iso(created), iso(expires)),
        )
        return _row(conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone())

    return _write(run)


def claim_approval(tool_name: str, *, now: datetime | None = None) -> dict | None:
    moment = iso(now)

    def run(conn):
        row = conn.execute(
            """
            SELECT * FROM approvals
            WHERE consumed_at IS NULL AND expires_at > ? AND lower(action) = lower(?)
            ORDER BY created_at DESC LIMIT 1
            """,
            (moment, tool_name),
        ).fetchone()
        if row is None:
            return None
        updated = conn.execute(
            "UPDATE approvals SET consumed_at = ?, consumed_tool = ? WHERE id = ? AND consumed_at IS NULL",
            (moment, tool_name, row["id"]),
        )
        if updated.rowcount != 1:
            return None
        return _row(conn.execute("SELECT * FROM approvals WHERE id = ?", (row["id"],)).fetchone())

    return _write(run)
