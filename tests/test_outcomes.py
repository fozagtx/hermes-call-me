from hermes_call_me.outcomes import classify


def _row(**extra):
    base = {
        "pin_verified": 0,
        "pin_attempts": 0,
        "purpose": "approval",
        "tool_decision": "",
        "tool_instructions": "",
        "tool_reply": "",
    }
    base.update(extra)
    return base


def test_structured_approval_without_pin_is_not_approval():
    # classify ignores analysis on purpose. The caller may have a structured
    # "approved" and it must not matter.
    outcome = classify(_row(), ended_reason="customer-ended-call", timed_out=False)
    assert outcome["reason"] == "no_pin"
    assert outcome["status"] == "no_answer"
    assert outcome["decision"] != "approved"


def test_wrong_pin_is_denied():
    outcome = classify(_row(pin_attempts=2), ended_reason="customer-ended-call", timed_out=False)
    assert outcome["reason"] == "wrong_pin"
    assert outcome["status"] == "denied"
    assert outcome["instructions"] is None


def test_pin_ok_but_no_tool_decision_is_unclear():
    outcome = classify(
        _row(pin_verified=1),
        ended_reason="customer-ended-call",
        timed_out=False,
    )
    assert outcome["reason"] == "unclear"
    assert outcome["status"] == "denied"


def test_tool_approval_after_pin_is_the_only_yes():
    outcome = classify(
        _row(pin_verified=1, tool_decision="approved"),
        ended_reason="customer-ended-call",
        timed_out=False,
    )
    assert outcome["reason"] == "approved"
    assert outcome["status"] == "approved"


def test_no_answer_and_timeout():
    missed = classify(_row(), ended_reason="customer-did-not-answer", timed_out=False)
    assert missed["reason"] == "no_answer"
    timed = classify(_row(), ended_reason="", timed_out=True)
    assert timed["reason"] == "timeout"


def test_help_ignores_instructions_until_pin_and_tool():
    blocked = classify(
        _row(purpose="help", tool_instructions="restart the worker"),
        ended_reason="customer-ended-call",
        timed_out=False,
    )
    assert blocked["instructions"] is None
    kept = classify(
        _row(purpose="help", pin_verified=1, tool_instructions="restart the worker"),
        ended_reason="customer-ended-call",
        timed_out=False,
    )
    assert kept["instructions"] == "restart the worker"
    assert kept["status"] == "completed"


def test_report_without_pin_is_not_delivered():
    outcome = classify(
        _row(purpose="report", tool_reply="sounds good"),
        ended_reason="customer-ended-call",
        timed_out=False,
    )
    assert outcome["reply"] is None
    assert outcome["status"] == "no_answer"


def test_report_with_pin_and_no_reply_still_counts_as_delivered():
    outcome = classify(
        _row(purpose="report", pin_verified=1),
        ended_reason="customer-ended-call",
        timed_out=False,
    )
    assert outcome["reason"] == "delivered_no_reply"
    assert outcome["status"] == "completed"
