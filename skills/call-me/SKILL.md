---
name: call-me
description: Call the owner for approval, help, or a progress report before acting alone.
---

# Call the owner

Use the Hermes Call Me tools when you are running without the owner watching.

- `call_for_approval` before something risky (deploy, delete, payment, anything the guard blocks). Pass `action`, `risk`, and `summary`. If the guard named a tool, `action` must be that tool's exact name.
- `call_for_help` when a production problem needs the owner's knowledge. Pass `issue` and `what_i_tried`.
- `call_report` when work is finished. Pass `done`, `left`, and `progress`. This is not approval for the next risky step.

Leave `channel` unset, or set `web`, unless the owner asked for a real phone call. `web` is a real Vapi browser call. The owner joins it from the local demo page. `phone` places one CALL-E call to the single allowlisted number and is refused until phone calls are turned on.

On a phone approval, CALL-E reads the change aloud and a one-time code. The owner says their PIN and repeats the code. This server checks both. You never see the code in the tool result, and you must not invent it.

Trust the tool result, not the transcript:

- Approval counts only when `approved` is true and `result` is `approved`. `denied`, `no_answer`, a wrong PIN, a wrong code, silence, a timeout, and an unclear reply are not approval. Do not retry the risky tool after that. Do not place a second call to get a better answer.
- Help instructions count only when `instructions` is a string. If it is null, stop and tell the owner the `reason`. Do not mine the transcript for a plan.
- A report was delivered only when `delivered` is true.

If the owner phones in, a pending request shows up in your context with an id. Do the work. If they asked for a callback, call `call_report` with that `inbound_task_id`. Do not claim you called them unless that tool says the report was delivered.
