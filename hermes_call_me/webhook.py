"""Vapi server-url events: tool calls during the call, and the end-of-call report.

The HTTP server is a thin wrapper around ``handle_body``. Tests call ``handle_body``.
"""

from __future__ import annotations

import json
from typing import Any

from . import store
from .assistant import build_assistant
from .config import Settings, scrub
from .inbound import deliver
from .outcomes import classify
from .policy import MAX_PIN_ATTEMPTS, caller_allowed, pin_matches
from .vapi import as_cost, as_duration

TERMINAL = {
    "approved",
    "denied",
    "no_answer",
    "timeout",
    "completed",
    "unclear",
    "failed",
}


def parse_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def unwrap(body: Any) -> dict:
    if not isinstance(body, dict):
        return {}
    message = body.get("message")
    if isinstance(message, dict):
        return message
    return body


def _call_object(message: dict) -> dict:
    call = message.get("call")
    return call if isinstance(call, dict) else {}


def _caller_number(message: dict) -> str:
    call = _call_object(message)
    customer = call.get("customer") if isinstance(call.get("customer"), dict) else {}
    if not customer and isinstance(message.get("customer"), dict):
        customer = message["customer"]
    number = customer.get("number") or ""
    return str(number)


def _local_call(message: dict, query_call_id: str) -> dict | None:
    if query_call_id:
        row = store.get_call(query_call_id)
        if row is not None:
            return row
    vapi_id = str(_call_object(message).get("id") or "")
    if vapi_id:
        return store.get_by_vapi(vapi_id)
    return None


def _tool_items(message: dict) -> list[dict]:
    raw = message.get("toolCallList") or message.get("toolCalls") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _structured(message: dict) -> dict:
    analysis = message.get("analysis") if isinstance(message.get("analysis"), dict) else {}
    data = analysis.get("structuredData")
    if isinstance(data, dict) and data:
        return data
    artifact = message.get("artifact") if isinstance(message.get("artifact"), dict) else {}
    outputs = artifact.get("structuredOutputs")
    if isinstance(outputs, dict):
        for item in outputs.values():
            if not isinstance(item, dict):
                continue
            result = item.get("result")
            if isinstance(result, dict) and "decision" in result:
                return result
    return {}


def _transcript(message: dict) -> str:
    artifact = message.get("artifact") if isinstance(message.get("artifact"), dict) else {}
    text = artifact.get("transcript") or message.get("transcript") or ""
    if not isinstance(text, str):
        text = store.dumps(text)
    return text[:100_000]


def handle_body(body: dict, *, settings: Settings, query_call_id: str = "") -> tuple[int, dict]:
    message = unwrap(body)
    kind = str(message.get("type") or "")
    if kind == "tool-calls":
        return 200, {"results": _tool_calls(message, settings, query_call_id)}
    if kind == "end-of-call-report":
        _end_of_call(message, query_call_id, timed_out=False)
        return 200, {"ok": True}
    if kind == "status-update":
        _status(message, query_call_id)
        return 200, {"ok": True}
    if kind == "assistant-request":
        return _assistant_request(message, settings)
    return 200, {"ok": True, "ignored": kind or "empty"}


def _status(message: dict, query_call_id: str) -> None:
    row = _local_call(message, query_call_id)
    if row is None or row["status"] in TERMINAL:
        return
    status = str(message.get("status") or "")
    mapped = {"ringing": "ringing", "in-progress": "in_progress", "queued": "starting"}.get(status)
    if mapped:
        store.update_call(row["id"], status=mapped)


def _assistant_request(message: dict, settings: Settings) -> tuple[int, dict]:
    caller = _caller_number(message)
    if not caller_allowed(settings, caller):
        return 200, {"error": "This phone is not the owner line. Goodbye."}
    vapi_id = str(_call_object(message).get("id") or "") or None
    row = store.create_call(
        direction="inbound",
        channel="phone",
        purpose="inbound",
        customer_number=caller,
        vapi_call_id=vapi_id,
        status="in_progress",
    )
    try:
        assistant = build_assistant(settings, purpose="inbound", call_id=row["id"], facts={})
    except Exception as exc:
        store.update_call(row["id"], status="failed", reason="error", error=scrub(str(exc), settings)[:500])
        return 200, {"error": "Hermes could not start the assistant. Goodbye."}
    return 200, {"assistant": assistant}


def _tool_calls(message: dict, settings: Settings, query_call_id: str) -> list[dict]:
    row = _local_call(message, query_call_id)
    results = []
    for item in _tool_items(message):
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function.get("name") or item.get("name") or "")
        raw_args = function.get("arguments")
        if raw_args is None:
            raw_args = item.get("arguments")
        args = parse_arguments(raw_args)
        tool_id = str(item.get("id") or item.get("toolCallId") or "")
        if row is None:
            payload = {"ok": False, "error": "This call is not one Hermes Call Me started. Ending the gate."}
        else:
            payload = _dispatch_tool(name, args, row, settings)
            row = store.get_call(row["id"]) or row
        results.append(
            {
                "name": name,
                "toolCallId": tool_id,
                "result": json.dumps(payload, ensure_ascii=False),
            }
        )
    return results


def _dispatch_tool(name: str, args: dict, row: dict, settings: Settings) -> dict:
    if name == "verify_pin":
        return _verify_pin(args, row, settings)
    if name == "record_decision":
        return _require_pin(row) or _record_decision(args, row)
    if name == "record_instructions":
        return _require_pin(row) or _record_text(row, "tool_instructions", str(args.get("instructions") or ""))
    if name == "record_reply":
        return _require_pin(row) or _record_text(row, "tool_reply", str(args.get("reply") or ""))
    if name == "get_status":
        blocked = _require_pin(row)
        if blocked:
            return blocked
        return {"ok": True, "recent": [_public_summary(item) for item in store.recent_calls(5)]}
    if name == "submit_owner_request":
        blocked = _require_pin(row)
        if blocked:
            return blocked
        return _submit(args, row, settings)
    return {"ok": False, "error": f"Unknown tool {name}."}


def _verify_pin(args: dict, row: dict, settings: Settings) -> dict:
    if row.get("pin_verified"):
        return {"ok": True, "attempts_remaining": MAX_PIN_ATTEMPTS}
    if int(row.get("pin_attempts") or 0) >= MAX_PIN_ATTEMPTS:
        return {"ok": False, "attempts_remaining": 0, "end_call": True}
    # The spoken PIN is compared and then dropped. It is not stored.
    matched = pin_matches(str(args.get("pin") or ""), settings.owner_pin)
    updated = store.record_pin_attempt(row["id"], verified=matched)
    attempts = int((updated or row).get("pin_attempts") or 0)
    if matched:
        return {"ok": True, "attempts_remaining": max(0, MAX_PIN_ATTEMPTS - attempts)}
    remaining = max(0, MAX_PIN_ATTEMPTS - attempts)
    return {"ok": False, "attempts_remaining": remaining, "end_call": remaining == 0}


def _require_pin(row: dict) -> dict | None:
    if row.get("pin_verified"):
        return None
    return {
        "ok": False,
        "error": "PIN not verified. Ask for the PIN and call verify_pin. Do not continue.",
    }


def _record_decision(args: dict, row: dict) -> dict:
    decision = str(args.get("decision") or "").strip().lower()
    if decision not in {"approved", "denied", "unclear"}:
        return {"ok": False, "error": "decision must be approved, denied, or unclear."}
    store.update_call(row["id"], tool_decision=decision)
    return {"ok": True, "decision": decision}


def _record_text(row: dict, column: str, text: str) -> dict:
    store.update_call(row["id"], **{column: text.strip()[:4000]})
    return {"ok": True}


def _submit(args: dict, row: dict, settings: Settings) -> dict:
    kind = str(args.get("kind") or "").strip().lower()
    text = str(args.get("text") or "").strip()
    if kind not in {"task", "status"}:
        return {"ok": False, "error": "kind must be task or status."}
    if not text:
        return {"ok": False, "error": "text is empty."}
    callback = bool(args.get("callback"))
    task = store.create_task(call_id=row["id"], kind=kind, text=text[:4000], callback=callback)
    delivery = deliver(task, settings)
    if delivery["delivered"]:
        store.mark_task_injected(task["id"])
    return {
        "ok": True,
        "task_id": task["id"],
        "delivered_to_agent": delivery["delivered"],
        "limit": delivery["limit"],
    }


def _end_of_call(message: dict, query_call_id: str, *, timed_out: bool) -> dict | None:
    row = _local_call(message, query_call_id)
    if row is None:
        return None
    if row["status"] in TERMINAL and not timed_out:
        return row
    call = _call_object(message)
    ended = str(message.get("endedReason") or call.get("endedReason") or row.get("ended_reason") or "")
    structured = _structured(message)
    transcript = _transcript(message) or row.get("transcript") or ""
    cost = as_cost(message.get("cost"))
    if cost is None:
        cost = as_cost(call.get("cost"))
    if cost is None:
        cost = row.get("cost_usd")
    duration = as_duration(message, call)
    if duration is None:
        duration = row.get("duration_seconds")
    return finalize_row(
        row,
        ended_reason=ended,
        structured=structured,
        transcript=transcript,
        cost=cost,
        duration=duration,
        timed_out=timed_out,
    )


def finalize_row(
    row: dict,
    *,
    ended_reason: str,
    structured: dict | None,
    transcript: str | None,
    cost: float | None,
    duration: float | None,
    timed_out: bool,
) -> dict | None:
    fresh = store.get_call(row["id"]) or row
    if fresh["status"] in TERMINAL:
        return fresh
    outcome = classify(fresh, ended_reason=ended_reason, timed_out=timed_out)
    fields = {
        "status": outcome["status"],
        "reason": outcome["reason"],
        "decision": outcome["decision"],
        "ended_reason": (ended_reason or "")[:300],
        "ended_at": store.iso(),
    }
    # Tool-captured instructions win. classify already copied them only when the PIN matched.
    if outcome["instructions"] is not None:
        fields["tool_instructions"] = outcome["instructions"]
    elif not fresh.get("pin_verified"):
        fields["tool_instructions"] = None
    if outcome["reply"] is not None:
        fields["tool_reply"] = outcome["reply"]
    elif not fresh.get("pin_verified"):
        fields["tool_reply"] = None
    if transcript:
        fields["transcript"] = transcript
    if cost is not None:
        fields["cost_usd"] = cost
    if duration is not None:
        fields["duration_seconds"] = duration
    if structured:
        fields["structured_json"] = store.dumps(structured)[:20000]
    updated = store.update_call(fresh["id"], **fields)
    if (
        updated
        and updated.get("reason") == "approved"
        and updated.get("purpose") == "approval"
        and updated.get("guard_action")
        and not store.has_approval(updated["id"])
    ):
        try:
            from .config import load_settings

            ttl = load_settings().approval_ttl_seconds
        except Exception:
            ttl = 600
        store.save_approval(
            call_id=updated["id"],
            action=updated["guard_action"],
            summary=updated.get("guard_summary") or "",
            risk=updated.get("guard_risk") or "",
            ttl_seconds=ttl,
        )
    return updated


def _public_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "purpose": row["purpose"],
        "channel": row["channel"],
        "status": row["status"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "duration_seconds": row["duration_seconds"],
        "cost_usd": row["cost_usd"],
    }
