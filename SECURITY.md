# Security

## Reporting a problem

Please report security issues privately through GitHub's **Report a vulnerability** button on the [Security tab](https://github.com/fozagtx/hermes-call-me/security/advisories/new), not in a public issue. Include the version, what you did, and what happened. You should get a reply within a week.

## What this plugin protects

Hermes Call Me turns "the owner said yes on the phone" into a value Hermes can act on. The thing to protect is that `approved: true` only ever means **the owner, knowing the PIN, heard this change and approved it**.

## Threat model

| Threat | Defence |
| --- | --- |
| **The model claims approval it didn't get** | `approved` comes from the plugin's own checks of CALL-E's structured result, never from model text. The skill and tool descriptions tell the model to trust only that field. |
| **CALL-E's voice agent reports a yes that wasn't given** | The agent never knows the PIN. The plugin compares the digits the owner said with the stored PIN, using a constant-time compare. An approval also needs a fresh six-digit one-time code read on the call and repeated back. |
| **Someone else answers the phone** | Without the PIN they can't produce an approval, instructions or a delivered report. They may still hear the summary; see [Known limits](#known-limits). |
| **Model text tries to steer the call** (prompt injection in `summary`, `issue`, and so on) | That text is capped at 1,000 characters, quoted inside `<<<` `>>>` markers it can't close, and the task tells CALL-E's agent it is information, not instructions. The PIN check holds regardless, because the PIN is never in the task. |
| **The PIN or code leaks to the model or the logs** | Neither is in the task sent to CALL-E. Tool results never include the transcript. Stored transcripts have runs of three or more spoken digits or number words replaced with `[number]`. The one-time code is wiped from the database when the call ends. Provider errors are scrubbed of the API key, the PIN and the code. |
| **Two calls race each other** | "One call at a time" and the daily cap are checked and the call row inserted in a single SQLite `BEGIN IMMEDIATE` transaction, so parallel tool calls, or two processes sharing the database, can't both pass. |
| **A retry places a second call** | Creates replay the same body and `Idempotency-Key` when acceptance is uncertain, which CALL-E guarantees does not redial. A poll timeout returns `no_answer` and never creates a new call. |
| **A risky tool runs without approval** | With the guard on, `pre_tool_call` blocks matching tools until an unexpired, unused approval for that exact tool name exists. Approvals are consumed atomically, once. A guard setting that can't be read as true or false turns the guard **on**. Only the plugin's own three tools are exempt. |
| **Another Hermes profile's settings or keys are used** | Secrets are read only through `agent.secret_scope.get_secret`. Inside Hermes, every other setting comes from the active profile's plugin config; the shared process environment is ignored. |
| **The plugin dials someone else** | It only dials `owner_number`, which must be a single E.164 number. The model can't pass a number. |
| **Cost runaway** | At most `daily_call_cap` accepted calls (default 8) in a rolling 24 hours, plus optional quiet hours. |

## Known limits

- **The PIN is the identity check.** Anyone who knows it and answers your phone can approve. Use a PIN you don't use anywhere else, and change it if you think it was overheard.
- **The summary is read before the PIN is verified.** CALL-E's agent can't check the PIN during the call (it never sees it), so whoever answers hears the action and summary after saying any digits. Don't put secrets in what you ask Hermes to tell you.
- **An approval is bound to a tool name, not its arguments.** An approval for `deploy_prod` lets one `deploy_prod` call run within the approval lifetime (default 10 minutes), whatever its arguments are. The summary you heard is written by the model.
- **A forwarding number is a real number.** If you use the README's US-number workaround, anyone who has that number can ring your phone. They can't reach Hermes or approve anything, but keep the number dedicated to Hermes and unpublished.
- **The guard is opt-in and pattern-based.** It only blocks tools whose names match the patterns. Review the built-in list against your tools.
- **CALL-E sees the call.** CALL-E processes the audio and the text Hermes sends. Its handling of that data is covered by CALL-E's own terms, not this plugin.
- **Spoken-number redaction is a heuristic.** It catches digit and number-word runs of three or more. Unusual phrasing may slip through, which is one more reason transcripts are never returned to the model.

## Dependencies

The plugin has no runtime Python dependencies. It uses the standard library (`urllib`, `sqlite3`, `hmac`, `secrets`) and Hermes's own APIs. CI installs only `pytest` (pinned below the next major version) to run the tests.
