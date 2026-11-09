"""Place a call and wait until the webhook (or a real GET /call) finishes it."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from . import store
from .assistant import build_assistant, build_call_payload
from .config import ConfigError, Settings, load_settings, require_call_config, scrub
from .outcomes import approval_result_label
from .policy import check_outbound
from .vapi import VapiError, control_url, create_call, end_call, get_call, join_url
from .webhook import TERMINAL, finalize_row, handle_body

logger = logging.getLogger("hermes_call_me")


def run_approval(args: dict) -> dict:
    return _run(
        "approval",
        args,
        facts={
            "action": _need(args, "action"),
            "risk": _need(args, "risk"),
            "summary": _need(args, "summary"),
        },
    )


def run_help(args: dict) -> dict:
    return _run(
        "help",
        args,
        facts={"issue": _need(args, "issue"), "what_i_tried": _need(args, "what_i_tried")},
    )


def run_report(args: dict) -> dict:
    return _run(
        "report",
        args,
        facts={
            "done": _need(args, "done"),
            "left": _need(args, "left"),
            "progress": _need(args, "progress"),
        },
        inbound_task_id=str(args.get("inbound_task_id") or "").strip() or None,
    )


def start_from_demo(payload: dict) -> dict:
    """Browser (or the one phone call) started by the local demo page. Does not block."""
    purpose = str(payload.get("purpose") or "")
    if purpose not in {"approval", "help", "report"}:
        raise ConfigError("purpose must be approval, help, or report.")
    channel = str(payload.get("channel") or "web").strip().lower()
    if channel == "phone" and payload.get("confirm") != "PHONE":
        raise ConfigError(
            "Refusing the phone call. The demo page must send confirm=PHONE "
            "so a mis-click cannot dial the owner."
        )
    facts = {
        "action": payload.get("action") or "Deploy the demo change",
        "risk": payload.get("risk") or "high",
        "summary": payload.get("summary") or "This is the browser demo of an approval call.",
        "issue": payload.get("issue") or "The demo service is failing and Hermes is stuck.",
        "what_i_tried": payload.get("what_i_tried") or "Retried the last step and read the error.",
        "done": payload.get("done") or "Finished the demo task.",
        "left": payload.get("left") or "Nothing else for this demo.",
        "progress": payload.get("progress") or "Done.",
    }
    return _run(purpose, {"channel": channel}, facts=facts, wait=False)


def hangup(call_id: str) -> dict:
    settings = load_settings()
    row = store.get_call(call_id)
    if row is None:
        raise ConfigError(f"No call {call_id}.")
    hangup_error = ""
    if row.get("vapi_call_id") and settings.vapi_api_key:
        try:
            end_call(row["vapi_call_id"], row.get("control_url"), settings)
        except VapiError as exc:
            hangup_error = scrub(str(exc), settings)
    if row["status"] not in TERMINAL:
        finalize_row(
            row,
            ended_reason="manual-hangup",
            structured=None,
            transcript=row.get("transcript"),
            cost=row.get("cost_usd"),
            duration=row.get("duration_seconds"),
            timed_out=False,
        )
    payload = tool_payload(store.get_call(call_id))
    if hangup_error:
        payload["hangup_error"] = hangup_error
    return payload


def _need(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing {key}. No call was placed.")
    return value.strip()


def _channel(args: dict, settings: Settings) -> str:
    raw = args.get("channel") or settings.default_channel
    channel = str(raw).strip().lower()
    if channel not in {"web", "phone"}:
        raise ConfigError(f"channel must be web or phone, got {channel!r}.")
    return channel


def _abandon_stale(settings: Settings) -> None:
    active = store.in_progress()
    if active is None:
        return
    try:
        started = datetime.strptime(active["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return
    age = (store.utcnow() - started.replace(tzinfo=timezone.utc)).total_seconds()
    if age > settings.call_timeout_seconds + 90:
        store.update_call(active["id"], status="timeout", reason="timeout", decision="no_answer", ended_at=store.iso())
        return
    raise ConfigError(
        f"A call is already in progress ({active['id']}, {active['purpose']}, {active['channel']}). "
        "Wait for it to finish before starting another. Nothing new was dialed."
    )


def _run(purpose: str, args: dict, *, facts: dict, wait: bool = True, inbound_task_id: str | None = None) -> dict:
    settings = load_settings()
    channel = _channel(args, settings)
    require_call_config(settings, channel)
    _abandon_stale(settings)
    check_outbound(settings, channel, recent_calls=store.count_recent_calls())
    from .server import ensure_server

    ensure_server(settings)
    row = store.create_call(
        direction="outbound",
        channel=channel,
        purpose=purpose,
        customer_number=settings.owner_number if channel == "phone" else None,
        status="starting",
    )
    if inbound_task_id:
        store.update_call(row["id"], inbound_task_id=inbound_task_id)
    if purpose == "approval":
        store.update_call(
            row["id"],
            guard_action=facts.get("action") or "",
            guard_summary=facts.get("summary") or "",
            guard_risk=facts.get("risk") or "",
        )
    if channel == "phone" and settings.phone_provider == "calle":
        return _run_calle(
            row,
            settings,
            purpose,
            facts,
            wait=wait,
            inbound_task_id=inbound_task_id,
        )
    store.update_call(row["id"], provider="vapi")
    assistant = build_assistant(settings, purpose=purpose, call_id=row["id"], facts=facts)
    payload = build_call_payload(
        settings,
        channel=channel,
        assistant=assistant,
        name=f"hermes-call-me {purpose}",
    )
    try:
        created = create_call(payload, settings)
    except VapiError as exc:
        message = scrub(str(exc), settings)
        store.update_call(row["id"], status="failed", reason="error", error=message[:800])
        raise VapiError(message) from exc
    vapi_id = created.get("id")
    if not isinstance(vapi_id, str) or not vapi_id:
        store.update_call(row["id"], status="failed", reason="error", error="Vapi response had no call id.")
        raise VapiError(
            "Vapi POST /call did not return a call id. Keys in the response: "
            + ", ".join(sorted(str(key) for key in created))
        )
    url = join_url(created)
    if channel == "web" and not url:
        store.update_call(
            row["id"],
            vapi_call_id=vapi_id,
            status="failed",
            reason="error",
            error="Vapi did not return a browser join URL.",
        )
        raise VapiError(
            "Vapi created the call but did not return webCallUrl or transport.callUrl. "
            "Keys: " + ", ".join(sorted(str(key) for key in created))
        )
    current = store.get_call(row["id"]) or row
    fields = {
        "vapi_call_id": vapi_id,
        "join_url": url,
        "control_url": control_url(created),
    }
    if current.get("status") not in TERMINAL:
        fields["status"] = "in_progress"
    store.update_call(row["id"], **fields)
    if channel == "web" and url:
        logger.info("Browser call %s ready. Open the demo page or join %s", row["id"], url)
    if not wait:
        fresh = store.get_call(row["id"])
        return {
            "ok": True,
            "call_id": fresh["id"],
            "vapi_call_id": vapi_id,
            "join_url": url,
            "channel": channel,
            "purpose": purpose,
            "status": fresh["status"],
        }
    finished = _wait(row["id"], settings)
    if inbound_task_id and finished.get("reason") in {"delivered", "delivered_no_reply"}:
        store.complete_task(inbound_task_id)
    return tool_payload(finished)


def _run_calle(row, settings, purpose, facts, *, wait: bool, inbound_task_id: str | None) -> dict:
    from . import calle
    from .calle_call import build_request, interpret, one_time_code, transcript_text

    code = one_time_code()
    store.update_call(row["id"], one_time_code=code, provider="calle")
    body = build_request(purpose, facts, settings, local_id=row["id"], one_time=code)
    idempotency_key = f"hermes-{row['id']}"

    def fail(exc: calle.CalleError) -> None:
        message = scrub(str(exc), settings).replace(code, "[redacted]")
        store.update_call(row["id"], status="failed", reason="error", error=message[:800], provider="calle")
        raise calle.CalleError(message) from exc

    try:
        created = calle.create_call(body, settings, idempotency_key=idempotency_key)
    except calle.CalleError as exc:
        fail(exc)
    calle_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(calle_id, str) or not calle_id:
        message = (
            "CALL-E POST /v2/calls did not return an id. No second call was placed. "
            "Keys: " + ", ".join(sorted(str(key) for key in (created or {})))
        )
        store.update_call(row["id"], status="failed", reason="error", error=message[:800], provider="calle")
        raise calle.CalleError(message)
    store.update_call(row["id"], vapi_call_id=calle_id, status="in_progress", provider="calle")

    def finish() -> dict:
        try:
            ready = calle.wait_for_result(
                calle_id, settings, timeout_seconds=settings.call_timeout_seconds
            )
        except calle.CalleError as exc:
            cancel_note = ""
            try:
                calle.cancel_call(calle_id, settings)
            except calle.CalleError as cancel_exc:
                cancel_note = " " + scrub(str(cancel_exc), settings)
            message = (scrub(str(exc), settings) + cancel_note).replace(code, "[redacted]")
            store.update_call(
                row["id"],
                status="timeout",
                reason="timeout",
                decision="no_answer",
                pin_verified=0,
                error=message[:800],
                ended_reason="client-timeout",
                ended_at=store.iso(),
                provider="calle",
            )
            return store.get_call(row["id"]) or row
        outcome = interpret(ready, purpose=purpose, pin=settings.owner_pin, one_time=code)
        store.update_call(
            row["id"],
            status=outcome["status"],
            reason=outcome["reason"],
            decision=outcome["decision"],
            pin_verified=outcome["pin_verified"],
            tool_decision=outcome["tool_decision"],
            tool_instructions=outcome["tool_instructions"],
            tool_reply=outcome["tool_reply"],
            transcript=transcript_text(ready),
            ended_reason=str(ready.get("call_outcome") or ready.get("status") or "")[:300],
            ended_at=store.iso(),
            provider="calle",
        )
        fresh = store.get_call(row["id"]) or row
        if purpose == "approval" and fresh.get("reason") == "approved" and not store.has_approval(fresh["id"]):
            store.save_approval(
                call_id=fresh["id"],
                action=facts.get("action") or "",
                summary=facts.get("summary") or "",
                risk=facts.get("risk") or "",
                ttl_seconds=settings.approval_ttl_seconds,
            )
        if inbound_task_id and fresh.get("reason") in {"delivered", "delivered_no_reply"}:
            store.complete_task(inbound_task_id)
        return fresh

    if not wait:
        threading.Thread(target=finish, name=f"calle-{row['id']}", daemon=True).start()
        return {
            "ok": True,
            "call_id": row["id"],
            "calle_call_id": calle_id,
            "channel": "phone",
            "provider": "calle",
            "purpose": purpose,
            "status": "in_progress",
        }
    return tool_payload(finish())


def _wait(call_id: str, settings: Settings) -> dict:
    deadline = time.monotonic() + settings.call_timeout_seconds + 25
    while time.monotonic() < deadline:
        row = store.get_call(call_id)
        if row and row["status"] in TERMINAL:
            return row
        time.sleep(0.25)
    row = store.get_call(call_id) or {}
    remote = None
    fetch_error = ""
    if row.get("vapi_call_id"):
        try:
            remote = get_call(row["vapi_call_id"], settings)
        except VapiError as exc:
            fetch_error = scrub(str(exc), settings)
        if isinstance(remote, dict) and remote.get("status") == "ended":
            handle_body(
                {
                    "message": {
                        "type": "end-of-call-report",
                        "endedReason": remote.get("endedReason"),
                        "call": remote,
                        "analysis": remote.get("analysis") or {},
                        "artifact": remote.get("artifact") or {},
                        "cost": remote.get("cost"),
                    }
                },
                settings=settings,
                query_call_id=call_id,
            )
            fresh = store.get_call(call_id)
            if fresh and fresh["status"] in TERMINAL:
                return fresh
        try:
            end_call(row["vapi_call_id"], row.get("control_url"), settings)
        except VapiError as exc:
            fetch_error = (fetch_error + " " + scrub(str(exc), settings)).strip()
    finished = finalize_row(
        row,
        ended_reason="client-timeout" + (f" {fetch_error}" if fetch_error else ""),
        structured=None,
        transcript=row.get("transcript"),
        cost=row.get("cost_usd"),
        duration=row.get("duration_seconds"),
        timed_out=True,
    )
    return finished or row


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
        "vapi_call_id": row.get("vapi_call_id"),
        "channel": row.get("channel"),
        "provider": row.get("provider"),
        "purpose": row.get("purpose"),
        "pin_verified": pin_ok,
        "reason": reason,
        "status": row.get("status"),
        "duration_seconds": row.get("duration_seconds"),
        "cost_usd": row.get("cost_usd"),
        "ended_reason": row.get("ended_reason"),
        "join_url": row.get("join_url"),
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
        payload["instructions"] = row.get("tool_instructions") if pin_ok else None
    elif purpose == "report":
        payload["delivered"] = reason in {"delivered", "delivered_no_reply"} and pin_ok
        payload["reply"] = row.get("tool_reply") if pin_ok else None
    if pin_ok and row.get("transcript"):
        payload["transcript"] = row["transcript"]
    return payload
