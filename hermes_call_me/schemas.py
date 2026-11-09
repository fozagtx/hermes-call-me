"""Tool schemas the model reads."""

_TRUST = (
    "The owner says their PIN first, and this plugin compares the digits; the "
    "CALL-E agent never knows the PIN. A wrong PIN, no answer, busy, silence, "
    "a timeout, or an unclear reply never counts as a yes."
)

CALL_FOR_APPROVAL = {
    "name": "call_for_approval",
    "description": (
        "Phone the owner through CALL-E and ask for a yes or no before a risky action. "
        "CALL-E reads the change aloud and a one-time code; the owner says their PIN, "
        "repeats the code, then says approve or deny. This plugin checks the PIN and the code. "
        + _TRUST
        + " Returns result approved, denied, or no_answer. Treat it as approval only when "
        "approved is true. Do not call again to get a different answer."
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
                "description": "What the owner will hear: what changes if they approve.",
            },
        },
        "required": ["action", "risk", "summary"],
    },
}

CALL_FOR_HELP = {
    "name": "call_for_help",
    "description": (
        "Phone the owner through CALL-E when you are stuck on a production problem and need "
        "their knowledge. "
        + _TRUST
        + " Returns instructions only when the PIN matched and the owner actually gave "
        "instructions. If instructions is null, stop and show the reason. Do not invent a "
        "next step from the transcript."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "issue": {"type": "string", "description": "What is broken, in one or two sentences."},
            "what_i_tried": {"type": "string", "description": "What you already tried, so the owner does not repeat it."},
        },
        "required": ["issue", "what_i_tried"],
    },
}

CALL_REPORT = {
    "name": "call_report",
    "description": (
        "Phone the owner through CALL-E to report finished work: what you did, what is left, "
        "and progress. This is not a request for approval. "
        + _TRUST
        + " delivered is true only after the PIN matched and the owner acknowledged the report. "
        "reply holds a short answer if they gave one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "done": {"type": "string", "description": "What you finished."},
            "left": {"type": "string", "description": "What is still open. Say none if nothing is left."},
            "progress": {"type": "string", "description": "Where things stand now."},
        },
        "required": ["done", "left", "progress"],
    },
}

TOOLS = {
    "call_for_approval": CALL_FOR_APPROVAL,
    "call_for_help": CALL_FOR_HELP,
    "call_report": CALL_REPORT,
}
