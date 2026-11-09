"""Place one CALL-E call and read its result. Fails closed."""

from __future__ import annotations

from . import calle, store
from .calle_call import build_request, interpret, one_time_code, transcript_text
from .config import ConfigError, load_settings, require_call_config, scrub
from .policy import check_outbound

NO_ANSWER_REASONS = {"no_answer", "timeout", "error"}


def run_approval(args: dict) -> dict:
    return _run(
        "approval",
        {
            "action": _need(args, "action"),
            "risk": _need(args, "risk"),
            "summary": _need(args, "summary"),
        },
    )


def run_help(args: dict) -> dict:
    return _run("help", {"issue": _need(args, "issue"), "what_i_tried": _need(args, "what_i_tried")})


def run_report(args: dict) -> dict:
    return _run(
        "report",
        {"done": _need(args, "done"), "left": _need(args, "left"), "progress": _need(args, "progress")},
    )


MAX_FACT_CHARS = 1000


def _need(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing {key}. No call was placed.")
    text = " ".join(value.split())
    if len(text) > MAX_FACT_CHARS:
        raise ConfigError(
            f"{key} is {len(text)} characters; the limit is {MAX_FACT_CHARS} so the call stays short. "
            "No call was placed."
        )
    return text


def _run(purpose: str, facts: dict) -> dict:
    settings = load_settings()
    require_call_config(settings)
    check_outbound(settings, recent_calls=store.count_recent_calls())

    code = one_time_code()
    try:
        row = store.reserve_call(
            purpose=purpose,
            owner_number=settings.owner_number,
            one_time_code=code,
            daily_cap=settings.daily_call_cap,
            stale_after_seconds=settings.call_timeout_seconds + 300,
        )
    except store.CallRefused as exc:
        raise ConfigError(str(exc)) from exc
    if purpose == "approval":
        store.update_call(
            row["id"],
            guard_action=facts["action"],
            guard_summary=facts["summary"],
            guard_risk=facts["risk"],
        )
    body = build_request(purpose, facts, settings, local_id=row["id"], one_time=code)

    def redact(exc: Exception) -> str:
        return scrub(str(exc), settings).replace(code, "[redacted]")[:800]

    try:
        created = calle.create_call(body, settings, idempotency_key=f"hermes-{row['id']}")
    except calle.CalleError as exc:
        message = redact(exc)
        store.update_call(
            row["id"], status="failed", reason="error", error=message, one_time_code="", ended_at=store.iso()
        )
        raise calle.CalleError(message) from exc
    calle_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(calle_id, str) or not calle_id:
        message = (
            "CALL-E POST /v2/calls did not return an id. No second call was placed. Keys: "
            + ", ".join(sorted(str(key) for key in (created or {})))
        )
        store.update_call(
            row["id"], status="failed", reason="error", error=message, one_time_code="", ended_at=store.iso()
        )
        raise calle.CalleError(message)
    store.update_call(row["id"], calle_call_id=calle_id, status="in_progress")

    try:
        ready = calle.wait_for_result(calle_id, settings, timeout_seconds=settings.call_timeout_seconds)
    except calle.CalleError as exc:
        note = ""
        try:
            calle.cancel_call(calle_id, settings)
        except calle.CalleError as cancel_exc:
            note = " " + redact(cancel_exc)
        store.update_call(
            row["id"],
            status="timeout",
            reason="timeout",
            pin_verified=0,
            error=(redact(exc) + note)[:800],
            ended_reason="client-timeout",
            one_time_code="",
            ended_at=store.iso(),
        )
        return tool_payload(store.get_call(row["id"]))

    outcome = interpret(ready, purpose=purpose, pin=settings.owner_pin, one_time=code)
    store.update_call(
        row["id"],
        status=outcome["status"],
        reason=outcome["reason"],
        decision=outcome["decision"],
        pin_verified=outcome["pin_verified"],
        instructions=outcome["tool_instructions"],
        reply=outcome["tool_reply"],
        transcript=transcript_text(ready),
        ended_reason=str(ready.get("call_outcome") or ready.get("status") or "")[:300],
        one_time_code="",
        ended_at=store.iso(),
    )
    fresh = store.get_call(row["id"]) or row
    if purpose == "approval" and fresh.get("reason") == "approved":
        store.save_approval(
            call_id=fresh["id"],
            action=facts["action"],
            summary=facts["summary"],
            risk=facts["risk"],
            ttl_seconds=settings.approval_ttl_seconds,
        )
    return tool_payload(fresh)


def approval_result_label(reason: str) -> str:
    if reason == "approved":
        return "approved"
    if reason in NO_ANSWER_REASONS:
        return "no_answer"
    return "denied"


def tool_payload(row: dict | None) -> dict:
    if not row:
        return {
            "ok": False,
            "result": "no_answer",
            "approved": False,
            "reason": "error",
            "error": "The call record disappeared before it could be read.",
        }
    pin_ok = bool(row.get("pin_verified"))
    reason = row.get("reason") or "error"
    payload = {
        "ok": reason != "error" and row.get("status") != "failed",
        "call_id": row.get("id"),
        "calle_call_id": row.get("calle_call_id"),
        "purpose": row.get("purpose"),
        "pin_verified": pin_ok,
        "reason": reason,
        "status": row.get("status"),
        "ended_reason": row.get("ended_reason"),
    }
    if row.get("error"):
        payload["ok"] = False
        payload["error"] = row["error"]
    purpose = row.get("purpose")
    if purpose == "approval":
        approved = reason == "approved" and pin_ok
        payload["approved"] = approved
        payload["result"] = "approved" if approved else approval_result_label(reason)
    elif purpose == "help":
        payload["instructions"] = row.get("instructions") if pin_ok else None
    elif purpose == "report":
        payload["delivered"] = reason in {"delivered", "delivered_no_reply"} and pin_ok
        payload["reply"] = row.get("reply") if pin_ok else None
    # The transcript stays in the call log only. The model gets the checked
    # fields above, never the raw conversation.
    return payload
