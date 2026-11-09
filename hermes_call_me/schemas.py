"""Tool schemas the model reads."""

CALL_FOR_APPROVAL = {
    "name": "call_for_approval",
    "description": (
        "Phone or browser-call the owner and ask for a yes or no before a risky action. "
        "The owner must say the PIN first. The server compares the PIN. "
        "Returns result approved, denied, or no_answer. "
        "Treat approved as true only when approved is true. "
        "No answer, a wrong PIN, silence, a timeout, or an unclear reply is not approval. "
        "channel web (the default) is a real Vapi browser call and does not dial a phone. "
        "channel phone places a CALL-E call to the one allowlisted number. "
        "The owner says their PIN, hears the change, and repeats a one-time code. "
        "This server checks both. A wrong PIN, a wrong code, no answer, or an unclear reply is not approval. "
        "On web, the owner joins from the local demo page while this tool waits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Short name of the action. When the risky-tool guard blocked a tool, this must be that tool's exact name.",
            },
            "risk": {
                "type": "string",
                "description": "How bad a wrong yes would be: low, medium, or high, plus a few words.",
            },
            "summary": {
                "type": "string",
                "description": "What the owner will hear: what will change if they approve.",
            },
            "channel": {
                "type": "string",
                "enum": ["web", "phone"],
                "description": "web is the Vapi browser demo. phone is a CALL-E call to the allowlisted number.",
            },
        },
        "required": ["action", "risk", "summary"],
    },
}

CALL_FOR_HELP = {
    "name": "call_for_help",
    "description": (
        "Call the owner when you are stuck on a production problem and need their knowledge. "
        "The owner says the PIN first. Returns instructions only when the server verified the PIN "
        "and the owner actually gave instructions. If instructions is null, stop and show the "
        "reason. Do not invent a next step from the transcript. "
        "channel web is the Vapi browser demo. channel phone is a CALL-E call to the allowlisted number. Instructions are null unless the PIN matched."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "What is broken, in one or two sentences."},
            "what_i_tried": {"type": "string", "description": "What you already tried, so the owner does not repeat it."},
            "channel": {
                "type": "string",
                "enum": ["web", "phone"],
                "description": "web is the Vapi browser demo. phone is a CALL-E call to the allowlisted number.",
            },
        },
        "required": ["issue", "what_i_tried"],
    },
}

CALL_REPORT = {
    "name": "call_report",
    "description": (
        "Call the owner to report finished work: what you did, what is left, and progress. "
        "This is not a request for approval. The owner says the PIN, hears the report, and "
        "may leave a short reply. delivered is true only after the PIN check. "
        "If they phoned in a task and asked for a callback, pass that inbound_task_id. "
        "channel web is the browser demo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "done": {"type": "string", "description": "What you finished."},
            "left": {"type": "string", "description": "What is still open. Say none if nothing is left."},
            "progress": {"type": "string", "description": "Where things stand now."},
            "channel": {
                "type": "string",
                "enum": ["web", "phone"],
                "description": "web is the Vapi browser demo. phone is a CALL-E call to the allowlisted number.",
            },
            "inbound_task_id": {
                "type": "string",
                "description": "Optional id of an owner phone request this report closes.",
            },
        },
        "required": ["done", "left", "progress"],
    },
}

TOOLS = {
    "call_for_approval": CALL_FOR_APPROVAL,
    "call_for_help": CALL_FOR_HELP,
    "call_report": CALL_REPORT,
}
