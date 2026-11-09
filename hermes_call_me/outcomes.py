"""Turn a finished call into a fail-closed result.

The voice model does not get to declare victory. ``approved`` is true only
when this process recorded ``record_decision(approved)`` after ``verify_pin``
succeeded. Structured analysis from Vapi is stored for the owner and is not
an approval.
"""

from __future__ import annotations

NO_ANSWER_REASONS = {"no_answer", "timeout", "no_pin", "failed", "error"}
DENIED_REASONS = {"denied", "unclear", "wrong_pin"}

_NO_ANSWER_MARKERS = (
    "did-not-answer",
    "no-answer",
    "customer-busy",
    "voicemail",
    "silence-timed-out",
    "failed-to-connect",
    "did-not-give-microphone",
)


def is_no_answer_reason(ended_reason: str) -> bool:
    text = (ended_reason or "").lower()
    return any(marker in text for marker in _NO_ANSWER_MARKERS)


def classify(row: dict, *, ended_reason: str, timed_out: bool) -> dict:
    """Return the columns to store. ``structured`` data is intentionally unused."""
    pin_ok = bool(row.get("pin_verified"))
    attempts = int(row.get("pin_attempts") or 0)
    purpose = row.get("purpose") or ""
    tool_decision = (row.get("tool_decision") or "").strip().lower()
    instructions = (row.get("tool_instructions") or "").strip()
    reply = (row.get("tool_reply") or "").strip()

    if not pin_ok:
        if attempts > 0:
            reason = "wrong_pin"
            status = "denied"
        elif timed_out:
            reason = "timeout"
            status = "timeout"
        elif is_no_answer_reason(ended_reason):
            reason = "no_answer"
            status = "no_answer"
        else:
            reason = "no_pin"
            status = "no_answer"
        return {
            "status": status,
            "reason": reason,
            "decision": "denied" if reason == "wrong_pin" else "no_answer",
            "instructions": None,
            "reply": None,
        }

    if purpose == "approval":
        if tool_decision == "approved":
            return {
                "status": "approved",
                "reason": "approved",
                "decision": "approved",
                "instructions": None,
                "reply": None,
            }
        if tool_decision == "denied":
            return {
                "status": "denied",
                "reason": "denied",
                "decision": "denied",
                "instructions": None,
                "reply": None,
            }
        if timed_out:
            return {
                "status": "timeout",
                "reason": "timeout",
                "decision": "no_answer",
                "instructions": None,
                "reply": None,
            }
        if is_no_answer_reason(ended_reason):
            return {
                "status": "no_answer",
                "reason": "no_answer",
                "decision": "no_answer",
                "instructions": None,
                "reply": None,
            }
        return {
            "status": "denied",
            "reason": "unclear",
            "decision": "unclear",
            "instructions": None,
            "reply": None,
        }

    if purpose == "help":
        if instructions:
            return {
                "status": "completed",
                "reason": "instructions",
                "decision": "none",
                "instructions": instructions,
                "reply": None,
            }
        if timed_out:
            status, reason, decision = "timeout", "timeout", "no_answer"
        elif is_no_answer_reason(ended_reason):
            status, reason, decision = "no_answer", "no_answer", "no_answer"
        else:
            status, reason, decision = "unclear", "unclear", "unclear"
        return {
            "status": status,
            "reason": reason,
            "decision": decision,
            "instructions": None,
            "reply": None,
        }

    if purpose == "report":
        if timed_out and not reply and tool_decision != "delivered":
            return {
                "status": "timeout",
                "reason": "timeout",
                "decision": "no_answer",
                "instructions": None,
                "reply": None,
            }
        if is_no_answer_reason(ended_reason) and not reply:
            return {
                "status": "no_answer",
                "reason": "no_answer",
                "decision": "no_answer",
                "instructions": None,
                "reply": None,
            }
        return {
            "status": "completed",
            "reason": "delivered" if reply else "delivered_no_reply",
            "decision": "none",
            "instructions": None,
            "reply": reply or None,
        }

    # Inbound calls are finished by their own tools. A hang-up still closes the row.
    if timed_out:
        reason, status = "timeout", "timeout"
    elif is_no_answer_reason(ended_reason):
        reason, status = "no_answer", "no_answer"
    else:
        reason, status = "completed", "completed"
    return {
        "status": status,
        "reason": reason,
        "decision": "none",
        "instructions": instructions or None,
        "reply": reply or None,
    }


def approval_result_label(reason: str) -> str:
    if reason == "approved":
        return "approved"
    if reason in NO_ANSWER_REASONS:
        return "no_answer"
    return "denied"
