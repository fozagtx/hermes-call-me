"""Transient Vapi assistant shared by browser calls, outbound phone calls, and inbound calls.

The PIN is not in this prompt. The model must call ``verify_pin``. This server
accepts or rejects the digits. A later tool that records an approval is
rejected until that check has succeeded for the same call.
"""

from __future__ import annotations

from .config import Settings, webhook_endpoint

STRUCTURED_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["approved", "denied", "unclear", "no_answer", "none"],
            "description": "What the owner actually said. Use unclear if it was not explicit.",
        },
        "instructions": {
            "type": "string",
            "description": "The owner's words telling Hermes what to do. Empty string if none.",
        },
        "reply": {
            "type": "string",
            "description": "A short reply on a report call. Empty string if the owner added nothing.",
        },
        "request_kind": {
            "type": "string",
            "enum": ["task", "status", "none"],
        },
        "owner_request": {
            "type": "string",
            "description": "The task or status question the owner asked for, if this was an inbound call.",
        },
        "callback_requested": {"type": "boolean"},
    },
    "required": ["decision"],
}


def _server(settings: Settings, call_id: str) -> dict:
    url = webhook_endpoint(settings.webhook_public_url)
    if call_id:
        url = f"{url}?hermes_call_id={call_id}"
    return {
        "url": url,
        "timeoutSeconds": 15,
        "headers": {
            "Authorization": f"Bearer {settings.webhook_secret}",
            "X-Vapi-Secret": settings.webhook_secret,
        },
    }


def _function(name: str, description: str, properties: dict, required: list[str], server: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
        "server": server,
    }


def _prompt(purpose: str, facts: dict) -> str:
    common = (
        "You are Hermes, calling the owner of this agent. Speak briefly, in plain language. "
        "Your first job is the PIN. Ask them to say the numeric PIN. "
        "When they say it, call verify_pin with the digits only (convert spoken numbers to digits). "
        "Do not guess the PIN. Do not say the PIN back except to confirm you heard the digits they just said. "
        "If verify_pin returns ok=false, you may ask one more time. "
        "If it returns end_call=true, say you cannot continue and call the endCall tool. "
        "Until verify_pin returns ok=true, do not mention the action, the issue, the report, or any task. "
        "Never claim something was approved unless record_decision returned ok=true. "
        "If you are unsure what they said, record unclear. Do not fill the gap yourself."
    )
    if purpose == "approval":
        return (
            common
            + " After the PIN is accepted, say what you need permission for, then ask them to say "
            "approve or deny. Then call record_decision. "
            f"Action: {facts.get('action', '')}. "
            f"Risk: {facts.get('risk', '')}. "
            f"Summary: {facts.get('summary', '')}. "
            "Then say goodbye and end the call."
        )
    if purpose == "help":
        return (
            common
            + " After the PIN is accepted, explain the problem and what you already tried. "
            "Ask what they want you to do. Call record_instructions with their words, as close "
            "as you can to how they said them. If they do not know, call record_instructions "
            "with an empty string and say so. "
            f"Issue: {facts.get('issue', '')}. "
            f"What you already tried: {facts.get('what_i_tried', '')}. "
            "Then say goodbye and end the call."
        )
    if purpose == "report":
        return (
            common
            + " After the PIN is accepted, give the report in a few sentences. "
            "Ask if they have a short reply. Call record_reply with that reply, or with an "
            "empty string if they have nothing to add. This call is not an approval of future work. "
            f"Done: {facts.get('done', '')}. "
            f"Left: {facts.get('left', '')}. "
            f"Progress: {facts.get('progress', '')}. "
            "Then say goodbye and end the call."
        )
    return (
        common
        + " After the PIN is accepted, ask whether they want to give Hermes a task or hear status. "
        "For status, call get_status and speak the result in one or two sentences. "
        "If they want something the status tool cannot answer, or they have a task, "
        "call submit_owner_request with kind task or status, their words, and callback true "
        "if they want a call back when it is done. Repeat the limit field of the tool result "
        "in one honest sentence if delivered_to_agent is false. "
        "Then say goodbye and end the call."
    )


def _first_message(purpose: str) -> str:
    if purpose == "inbound":
        return "Hello, this is Hermes. Say your PIN, and then tell me the task or ask for status."
    return "Hello, this is Hermes. Before I continue, please say your PIN."


def build_assistant(settings: Settings, *, purpose: str, call_id: str, facts: dict) -> dict:
    server = _server(settings, call_id)
    tools = [
        _function(
            "verify_pin",
            "Check the PIN the owner just said. Call this before any other tool. Pass digits only.",
            {"pin": {"type": "string", "description": "Digits the owner said, with no spaces."}},
            ["pin"],
            server,
        ),
        {"type": "endCall"},
    ]
    if purpose == "approval":
        tools.append(
            _function(
                "record_decision",
                "Record the owner's decision after the PIN was accepted. Use unclear when it was not a clear approve or deny.",
                {
                    "decision": {
                        "type": "string",
                        "enum": ["approved", "denied", "unclear"],
                    }
                },
                ["decision"],
                server,
            )
        )
    elif purpose == "help":
        tools.append(
            _function(
                "record_instructions",
                "Store the owner's instructions after the PIN was accepted.",
                {
                    "instructions": {
                        "type": "string",
                        "description": "What the owner told Hermes to do. Empty if they had no instruction.",
                    }
                },
                ["instructions"],
                server,
            )
        )
    elif purpose == "report":
        tools.append(
            _function(
                "record_reply",
                "Store an optional short reply after the report was delivered and the PIN was accepted.",
                {"reply": {"type": "string", "description": "The owner's reply. Empty if they had nothing to add."}},
                ["reply"],
                server,
            )
        )
    else:
        tools.append(
            _function(
                "get_status",
                "Read the latest stored call results so you can answer a status question. PIN required.",
                {},
                [],
                server,
            )
        )
        tools.append(
            _function(
                "submit_owner_request",
                "Save a task or a status question for the Hermes agent. PIN required.",
                {
                    "kind": {"type": "string", "enum": ["task", "status"]},
                    "text": {"type": "string", "description": "The owner's words."},
                    "callback": {
                        "type": "boolean",
                        "description": "True if they want Hermes to call back when the work is done.",
                    },
                },
                ["kind", "text"],
                server,
            )
        )

    return {
        "name": f"Hermes Call Me ({purpose})",
        "firstMessage": _first_message(purpose),
        "firstMessageMode": "assistant-speaks-first",
        "endCallMessage": "Goodbye.",
        "maxDurationSeconds": settings.call_timeout_seconds,
        "backgroundSound": "off",
        "server": server,
        "serverMessages": ["end-of-call-report", "tool-calls", "status-update"],
        "monitorPlan": {"controlEnabled": True, "listenEnabled": False},
        "analysisPlan": {
            "minMessagesThreshold": 1,
            "summaryPlan": {
                "enabled": True,
                "timeoutSeconds": 15,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Summarize this call in two sentences. "
                            "Do not invent an approval. If the owner did not clearly approve, say so."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Transcript:\n\n{{transcript}}\n\nEnded reason:\n\n{{endedReason}}\n",
                    },
                ],
            },
            "structuredDataPlan": {
                "enabled": True,
                "timeoutSeconds": 20,
                "schema": STRUCTURED_SCHEMA,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract only what the human owner said. "
                            "The assistant's words are not a decision. "
                            "If the owner did not clearly approve, decision is unclear. "
                            "If the call never connected, decision is no_answer. "
                            "Reply with JSON only.\n\nJson Schema:\n{{schema}}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Transcript:\n\n{{transcript}}\n\nEnded reason:\n\n{{endedReason}}\n",
                    },
                ],
            },
        },
        "voice": {"provider": settings.voice_provider, "voiceId": settings.voice_id},
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en"},
        "model": {
            "provider": "openai",
            "model": settings.vapi_model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": _prompt(purpose, facts)}],
            "tools": tools,
        },
    }


def build_call_payload(settings: Settings, *, channel: str, assistant: dict, name: str) -> dict:
    payload: dict = {"name": name, "assistant": assistant}
    if channel == "web":
        payload["transport"] = {"provider": "daily", "conversationType": "voice"}
        return payload
    payload["phoneNumberId"] = settings.vapi_phone_number_id
    payload["customer"] = {"number": settings.owner_number}
    return payload
