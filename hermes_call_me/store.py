"""SQLite call log.

Inside Hermes this opens ``plugin_db("hermes-call-me")``, which is
``<HERMES_HOME>/plugin-data/hermes-call-me/data.db``. A standalone demo
server falls back to that same path when the Hermes package is not
importable, so the agent and the webhook process share one file when
``HERMES_HOME`` matches.

``HERMES_CALL_ME_DB`` points at a specific file. Tests set it. Production
does not have to.
"""

from __future__ import annotations

import json
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
    "vapi_call_id",
    "direction",
    "channel",
    "purpose",
    "customer_number",
    "status",
    "reason",
    "decision",
    "pin_verified",
    "pin_attempts",
    "tool_decision",
    "tool_instructions",
    "tool_reply",
    "transcript",
    "cost_usd",
    "duration_seconds",
    "ended_reason",
    "join_url",
    "control_url",
    "structured_json",
    "error",
    "inbound_task_id",
    "guard_action",
    "guard_summary",
    "guard_risk",
    "one_time_code",
    "provider",
    "ended_at",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    vapi_call_id TEXT,
    direction TEXT NOT NULL,
    channel TEXT NOT NULL,
    purpose TEXT NOT NULL,
    customer_number TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    decision TEXT,
    pin_verified INTEGER NOT NULL DEFAULT 0,
    pin_attempts INTEGER NOT NULL DEFAULT 0,
    tool_decision TEXT,
    tool_instructions TEXT,
    tool_reply TEXT,
    transcript TEXT,
    cost_usd REAL,
    duration_seconds REAL,
    ended_reason TEXT,
    join_url TEXT,
    control_url TEXT,
    structured_json TEXT,
    error TEXT,
    inbound_task_id TEXT,
    guard_action TEXT,
    guard_summary TEXT,
    guard_risk TEXT,
    one_time_code TEXT,
    provider TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX IF NOT EXISTS calls_vapi_id ON calls (vapi_call_id);
CREATE INDEX IF NOT EXISTS calls_created ON calls (created_at);
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
CREATE TABLE IF NOT EXISTS inbound_tasks (
    id TEXT PRIMARY KEY,
    call_id TEXT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    callback_requested INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    injected INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    done_at TEXT
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
        _migrate(conn)
        conn.commit()
        _conn = conn
        _key = key
        return conn


def _migrate(conn: sqlite3.Connection) -> None:
    have = {row[1] for row in conn.execute("PRAGMA table_info(calls)")}
    for name, declaration in (("one_time_code", "TEXT"), ("provider", "TEXT")):
        if name not in have:
            conn.execute(f"ALTER TABLE calls ADD COLUMN {name} {declaration}")


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


def create_call(
    *,
    direction: str,
    channel: str,
    purpose: str,
    customer_number: str | None = None,
    vapi_call_id: str | None = None,
    status: str = "starting",
) -> dict:
    call_id = "call_" + uuid.uuid4().hex
    now = iso()

    def run(conn):
        conn.execute(
            """
            INSERT INTO calls (
                id, vapi_call_id, direction, channel, purpose, customer_number,
                status, pin_verified, pin_attempts, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (call_id, vapi_call_id, direction, channel, purpose, customer_number, status, now, now),
        )
        return _row(conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone())

    return _write(run)


def update_call(call_id: str, **fields) -> dict | None:
    unknown = set(fields) - _CALL_COLUMNS
    if unknown:
        raise ValueError(f"unknown call columns: {sorted(unknown)}")
    fields["updated_at"] = iso()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    values = list(fields.values()) + [call_id]

    def run(conn):
        conn.execute(f"UPDATE calls SET {assignments} WHERE id = ?", values)
        return _row(conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone())

    return _write(run)


def get_call(call_id: str) -> dict | None:
    def run(conn):
        return _row(conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone())

    return _write(run)


def get_by_vapi(vapi_call_id: str) -> dict | None:
    if not vapi_call_id:
        return None

    def run(conn):
        return _row(
            conn.execute(
                "SELECT * FROM calls WHERE vapi_call_id = ? ORDER BY created_at DESC LIMIT 1",
                (vapi_call_id,),
            ).fetchone()
        )

    return _write(run)


def count_recent_calls(hours: int = 24) -> int:
    since = iso(utcnow() - timedelta(hours=hours))

    def run(conn):
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM calls
            WHERE vapi_call_id IS NOT NULL AND created_at >= ?
            """,
            (since,),
        ).fetchone()
        return int(row["n"])

    return _write(run)


def active_call() -> dict | None:
    def run(conn):
        return _row(
            conn.execute(
                """
                SELECT * FROM calls
                WHERE status IN ('starting', 'ringing', 'in_progress')
                  AND join_url IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
        )

    return _write(run)


def recent_calls(limit: int = 8) -> list[dict]:
    def run(conn):
        rows = conn.execute(
            "SELECT * FROM calls ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row(row) for row in rows]

    return _write(run)


def in_progress() -> dict | None:
    def run(conn):
        return _row(
            conn.execute(
                """
                SELECT * FROM calls
                WHERE status IN ('starting', 'ringing', 'in_progress')
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
        )

    return _write(run)


def record_pin_attempt(call_id: str, *, verified: bool) -> dict | None:
    def run(conn):
        row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if row is None:
            return None
        already = bool(row["pin_verified"])
        attempts = int(row["pin_attempts"])
        if verified:
            conn.execute(
                "UPDATE calls SET pin_verified = 1, updated_at = ? WHERE id = ?",
                (iso(), call_id),
            )
        elif not already:
            conn.execute(
                "UPDATE calls SET pin_attempts = ?, updated_at = ? WHERE id = ?",
                (attempts + 1, iso(), call_id),
            )
        return _row(conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone())

    return _write(run)


def has_approval(call_id: str) -> bool:
    def run(conn):
        row = conn.execute("SELECT id FROM approvals WHERE call_id = ? LIMIT 1", (call_id,)).fetchone()
        return row is not None

    return _write(run)


def save_approval(*, call_id: str, action: str, summary: str, risk: str, ttl_seconds: int) -> dict:
    approval_id = "apr_" + uuid.uuid4().hex
    created = utcnow()
    expires = created + timedelta(seconds=ttl_seconds)

    def run(conn):
        conn.execute(
            """
            INSERT INTO approvals (
                id, call_id, action, summary, risk, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
            """
            UPDATE approvals
            SET consumed_at = ?, consumed_tool = ?
            WHERE id = ? AND consumed_at IS NULL
            """,
            (moment, tool_name, row["id"]),
        )
        if updated.rowcount != 1:
            return None
        return _row(conn.execute("SELECT * FROM approvals WHERE id = ?", (row["id"],)).fetchone())

    return _write(run)


def create_task(*, call_id: str | None, kind: str, text: str, callback: bool) -> dict:
    task_id = "task_" + uuid.uuid4().hex
    now = iso()

    def run(conn):
        conn.execute(
            """
            INSERT INTO inbound_tasks (
                id, call_id, kind, text, callback_requested, status, injected, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?)
            """,
            (task_id, call_id, kind, text, 1 if callback else 0, now),
        )
        return _row(conn.execute("SELECT * FROM inbound_tasks WHERE id = ?", (task_id,)).fetchone())

    return _write(run)


def mark_task_injected(task_id: str) -> None:
    def run(conn):
        conn.execute("UPDATE inbound_tasks SET injected = 1 WHERE id = ?", (task_id,))

    _write(run)


def complete_task(task_id: str) -> None:
    def run(conn):
        conn.execute(
            "UPDATE inbound_tasks SET status = 'done', done_at = ? WHERE id = ?",
            (iso(), task_id),
        )

    _write(run)


def pending_tasks(limit: int = 3) -> list[dict]:
    def run(conn):
        rows = conn.execute(
            """
            SELECT * FROM inbound_tasks
            WHERE status = 'pending'
            ORDER BY created_at ASC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row(row) for row in rows]

    return _write(run)


def get_task(task_id: str) -> dict | None:
    def run(conn):
        return _row(conn.execute("SELECT * FROM inbound_tasks WHERE id = ?", (task_id,)).fetchone())

    return _write(run)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
