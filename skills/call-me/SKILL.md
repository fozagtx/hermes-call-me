---
name: call-me
description: Phone the owner through CALL-E for approval, help, or a progress report before acting alone.
---

# Call the owner

Use the Hermes Call Me tools when you are running without the owner watching. Each tool places one real CALL-E phone call to the owner's single allowlisted number.

- `call_for_approval` before something risky (deploy, delete, payment, anything the guard blocks). Pass `action`, `risk`, and `summary`. If the guard named a tool, `action` must be that tool's exact name.
- `call_for_help` when a production problem needs the owner's knowledge. Pass `issue` and `what_i_tried`.
- `call_report` when work is finished. Pass `done`, `left`, and `progress`. This is not approval for the next risky step.

On an approval call, CALL-E reads the change aloud and a one-time code. The owner says their PIN and repeats the code. The plugin checks both. You never see the code in the tool result, and you must not invent it.

Trust the tool result, not the transcript:

- Approval counts only when `approved` is true and `result` is `approved`. `denied`, `no_answer`, a wrong PIN, a wrong code, silence, a timeout, and an unclear reply are not approval. Do not retry the risky tool after that. Do not place a second call to get a better answer.
- Help instructions count only when `instructions` is a string. If it is null, stop and tell the owner the `reason`. Do not mine the transcript for a plan.
- A report was delivered only when `delivered` is true.

Calls cost money and there is a daily cap. Call only when it matters.
