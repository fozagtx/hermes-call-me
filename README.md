# Hermes Call Me

You leave Hermes running on its own. It should be able to phone you, and you should be able to phone it.

Hermes calls you in three situations. It calls before it does something risky, and it waits for you to say yes or no. It calls when it is stuck on a production problem and needs something only you know. It calls when it finishes, to tell you what it did, what is left, and how far it got. The other direction works too: you call Hermes's number, say what you want, and it takes that as a task or a status question.

A real phone call goes through CALL-E to one allowlisted number. The default region is the US, where CALL-E uses a local line. Canada is the other local-line country. A browser call stays on Vapi: same three tools, no phone line, useful for a recording.

Requires Hermes Agent **0.21.6** or newer.

## Before you install: what this plugin does on your machine

- **Network calls to third parties.** `https://api.vapi.ai` (browser calls, the optional Vapi phone path, inbound) and `https://api.heycall-e.com` (real phone calls). The summary you pass to a tool, the owner number, and the call task are sent to that provider. Call audio is processed by the provider; this plugin gets back the transcript, the structured result, cost, and duration.
- **Paid calls.** Phone calls cost money on your own CALL-E or Vapi account. They are off until you set `HERMES_CALL_ME_PHONE_CALLS=1`, they only dial the single number in `HERMES_CALL_ME_OWNER_NUMBER`, and a daily cap (default 8) applies.
- **A local HTTP server.** The first browser call starts a webhook and demo page in a background thread on `127.0.0.1:8787` (or `hermes call-me serve` runs it in the foreground). It binds to localhost only. Vapi has to reach it, so you expose it yourself with a tunnel such as `cloudflared`; every webhook request must carry your `HERMES_CALL_ME_WEBHOOK_SECRET`.
- **Stored data.** Every call is kept in `<HERMES_HOME>/plugin-data/hermes-call-me/data.db`: transcript, decision, cost, duration, and owner phone requests.
- **Credentials.** `VAPI_API_KEY`, `CALLE_API_KEY`, `HERMES_CALL_ME_PIN` and `HERMES_CALL_ME_WEBHOOK_SECRET` are declared secrets, read through Hermes's secret store for the active profile. The plugin does not read `.env` files or any other credential store.
- **Waiting for a person.** A tool call waits for the owner for at most `call_timeout_seconds` (default 180, max 600) and then returns `no_answer`. It does not hang unattended runs, and it never approves on its own.
- **Inbound.** With a Vapi number pointed at the webhook, a PIN-verified call from the allowlisted number is queued as a task and offered to the live session through `ctx.inject_message`, or the next turn through `pre_llm_call`.
- No shell commands, no telemetry, no self-update.

## Demo first (browser, near $0)

This is the path for a short recording. Two or three browser calls. They do not dial a phone.

1. Create a Vapi account. The pricing page includes **$5 of free credits** on the usage-only plan (`https://vapi.ai/pricing`, checked 8 Nov 2026). You do not need a Vapi phone number for browser calls. A free Vapi number cannot place outbound calls anyway.
2. In the Vapi dashboard, create a **private** API key. The demo page never sees this key.
3. Pick a PIN of 4 to 12 digits, and a long random webhook secret.
4. From this directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

Fill `.env` with `VAPI_API_KEY`, `HERMES_CALL_ME_PIN`, `HERMES_CALL_ME_WEBHOOK_SECRET`. Leave `HERMES_CALL_ME_PHONE_CALLS=0`. The plugin never reads this file itself; your shell loads it.

5. Start the local server:

```bash
set -a; . ./.env; set +a
.venv/bin/python -m hermes_call_me serve
```

It listens on `http://127.0.0.1:8787`. The demo page is `http://127.0.0.1:8787/demo`. The webhook is `http://127.0.0.1:8787/vapi/webhook`.

6. In another terminal, expose that port. Vapi's cloud has to reach the PIN check during the call. Localhost alone is refused on purpose, because a missed PIN check would fail closed and you would burn a call for nothing.

```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

Put the `https://….trycloudflare.com` origin in `HERMES_CALL_ME_WEBHOOK_URL` with no path, then restart the server.

7. Open the demo page **on localhost**, not on the tunnel URL. The page will not start a call from the public hostname. Allow the microphone. Click **Call for approval**, say the PIN when asked, then say approve or deny. The page shows the webhook result: decision, transcript, duration, cost.

Wrong PIN, no answer, silence, a vague answer, or the timeout (default 3 minutes) is **not** approval.

If Hermes itself starts a browser call (`call_for_approval` with the default channel `web`), leave this page open. It offers a Join button while the tool waits for the same webhook.

## What the three tools do

| Tool | You hear | Hermes gets back |
| --- | --- | --- |
| `call_for_approval(action, risk, summary)` | The action, then “approve” or “deny” | `approved`, `denied`, or `no_answer` |
| `call_for_help(issue, what_i_tried)` | The problem, then your instructions | `instructions`, or null if the PIN failed or you were unclear |
| `call_report(done, left, progress)` | The report. A short reply is optional | `delivered` true or false, and `reply` if you left one |

`channel` defaults to `web`. `phone` is the real call to your mobile. It stays off until `HERMES_CALL_ME_PHONE_CALLS=1`.

The voice model does not know the PIN and cannot approve by saying so. It calls `verify_pin`. This server compares the digits. Only after that can it record a decision. Vapi's end-of-call structured data is stored so you can read it. It cannot flip a call to approved.

## Install into Hermes

```bash
hermes plugins install https://github.com/fozagtx/hermes-call-me
hermes plugins enable hermes-call-me
```

Set the secrets (`VAPI_API_KEY`, `HERMES_CALL_ME_PIN`, `HERMES_CALL_ME_WEBHOOK_SECRET`, and `CALLE_API_KEY` for phone calls) through Hermes's plugin settings, not in `config.yaml`. They are `secret` fields in `plugin.yaml`.

On a machine where the standalone server is already running, the tools reuse it. Both processes must share `HERMES_HOME` so they read one call database.

`hermes call-me serve`, `hermes call-me recent`, `/call-me`, and the `call-me` skill are registered with the plugin. Manifest version 2, `api_version` 1.

## Optional guard

Leave this off for the demo. Set `HERMES_CALL_ME_GUARD=1` when Hermes is unattended.

The `pre_tool_call` hook then blocks tools whose names match deploy, delete, drop, payment, transfer, and the other built-in patterns (or your own list in `HERMES_CALL_ME_RISKY_TOOLS`). The model has to call `call_for_approval` with `action` set to that tool's exact name. A yes is single-use and expires (default 10 minutes).

The hook does not place the call itself. Hermes gives a hook about 30 seconds, and a call is allowed to run for about 3 minutes. The hook only checks that an approval is already on file.

## A real phone call (CALL-E)

The browser demo does not need this.

1. Sign up at [heycall-e.com](https://www.heycall-e.com). The CALL-E integrations README and the product FAQ say new accounts get **100 free credits (US$1)**. Create an API key in the dashboard.
2. Export `CALLE_API_KEY`. Leave `CALLE_BASE_URL` at `https://api.heycall-e.com` and `HERMES_CALL_ME_PROVIDER` at `calle`.
3. Set `HERMES_CALL_ME_OWNER_NUMBER` to one number you are allowed to call, in E.164 (`+` and country code). Set `HERMES_CALL_ME_REGION` to the matching country. **US** and **CA** use local lines. Other countries on [the region list](https://docs.heycall-e.com/regions) use international lines and may cost more. A region that does not match the number is rejected before dialing.
4. Set `HERMES_CALL_ME_PHONE_CALLS=1`.
5. From the demo page, tick the phone checkbox, or ask Hermes for `channel` `phone`. The page sends an extra confirmation so a mis-click cannot dial. Turn phone calls off again when you are done.

Phone calls use CALL-E one-shot: `POST /v2/calls` with the task, that one number, a result schema, and an `Idempotency-Key`, then `GET /v2/calls/{id}` until `result_status` is no longer `pending`. This is the Calls API in SDK 1.0 / the current docs. Goal runs are half the price, but a Goal has to be published in CALL-E first and only accepts variables, not a new task and schema per call. Approval, help, and report each need their own wording, so this plugin uses one-shot.

On an approval call, CALL-E reads the change aloud, then a one-time code, and asks the owner to say their PIN and repeat the code. This server compares both. Wrong PIN, wrong code, no answer, busy, an unclear answer, or a timeout is not approval. A timeout does not place a second call. Help instructions and a report acknowledgement are returned only after the PIN matches.

`HERMES_CALL_ME_PROVIDER=vapi` still places a phone call through Vapi if `VAPI_PHONE_NUMBER_ID` is set. That path is optional and unused by default. This repo does not set up Telnyx, and it does not call Twilio.

## When you call Hermes

CALL-E's Developer API does not place or receive inbound calls. Their docs say to buy a number and configure an Inbound Goal in the dashboard. This plugin cannot attach that from the API.

Inbound in this plugin is still the Vapi `assistant-request` webhook. It needs a Vapi phone number and the public webhook (`python3 -m hermes_call_me configure-number`). The server checks the caller against the one allowlisted number. If you only configure CALL-E, calling Hermes back is not wired.

What Hermes can do with that task is limited by the plugin API:

- If this process is inside a live Hermes session, it tries `ctx.inject_message`. On the CLI that queues or interrupts the current turn. On the gateway it returns false unless the session is live, you set `plugins.entries.hermes-call-me.allow_gateway_injection`, and (when needed) `HERMES_CALL_ME_GATEWAY_SESSION_KEY`.
- If injection does not land, the task stays in the database. The next model turn's `pre_llm_call` hook adds it to the prompt. That hook does **not** wake a sleeping agent and does not start a new run.
- There is no supported plugin call that creates a fresh unattended run by itself. Hermes's own webhook adapter can do that, with its own HMAC secret. This plugin does not pretend to speak that protocol.
- A callback is another real call: after the work, Hermes calls `call_report` with `inbound_task_id`. It should not say it called you unless that tool says the report was delivered.

## Rules that always apply

- One allowlisted number. The phone path only dials `HERMES_CALL_ME_OWNER_NUMBER`.
- Daily cap, default 8 calls in 24 hours, browser and phone together. A call counts once the provider has accepted it.
- Quiet hours default to 22:00–07:00 in `America/New_York` and are **off** so a demo is not blocked. Set `HERMES_CALL_ME_QUIET_HOURS_ENABLED=1` for unattended use.
- One call at a time. A second start is refused until the first finishes or is abandoned past the timeout.
- Every call is stored: transcript, decision, cost, duration. Inside Hermes that is `plugin_db("hermes-call-me")` (`<HERMES_HOME>/plugin-data/hermes-call-me/data.db`). If that API is not importable, the server uses the same file path. `HERMES_CALL_ME_DB` overrides the file. Tests set it. You do not have to.
- Missing keys fail with the variable name. Nothing in the runtime invents a call result.

## Test cost

Checked 8 November 2026. Prices move. The browser demo is the one to budget for.

**Vapi, per the pricing page** (`https://vapi.ai/pricing`):

- Hosting is **$0.05 per minute**, prepaid.
- New usage-only accounts list **$5 free credits**.
- The page's calculator, for Deepgram + OpenAI + ElevenLabs, shows about **$0.0095–$0.0099** (transcriber) + **$0.0077–$0.0452** (model) + **$0.0146–$0.0238** (voice) per minute. Added to hosting, that published example is about **$0.08–$0.13 per minute**.
- This demo defaults to `gpt-4o-mini` and Vapi's Elliot voice, not ElevenLabs. The hosting rate is explicit. A separate per-minute price for Elliot was **not** on the pages above, so treat $0.08–$0.13 as the upper reference, not a quote for this exact stack.

**Two or three browser calls of about one minute:** about **$0.16–$0.39** if the stack sits in that published band. That comes out of the $5 credit. Out of pocket: **$0**, if the credit is still there. Three calls that run all the way to the 3-minute cap are still on the order of **$1–$1.20** at the high end of that band, still inside $5. Hang up when you have the yes or the no. Silence ends the call from Vapi's side as well, and our wait hangs up at the timeout so a forgotten tab does not run for half an hour.

**Vapi minimum top-up:** the billing guide says “a minimum purchase applies” and does not print the amount (`https://docs.vapi.ai/billing/manage-billing-and-credits`). **Unverifiable** from the public docs. You do not need to buy credits for this demo if the $5 is unused. If the credit is already gone, read the minimum off the Buy credits screen before paying. Do not guess it.

**CALL-E phone calls, from their billing page and the 2026-09-24 changelog** (`https://docs.heycall-e.com/billing`):

- One-shot domestic (US/CA): model fee **$0.0296 per 10 seconds**, carrier **$0.0400 per minute**, rounded up to a whole minute.
- Their worked example for a 60-second one-shot call is **$0.2176** (model $0.1776 + carrier $0.04). A 30-second call is **$0.1288**.
- Goal mode is half of that ($0.1088 at 60 seconds). This plugin does not use it, because a Goal cannot take a new task and schema on each call.
- International carrier rates are not published. They follow the carrier. Model fees stay the same.
- Preparation can cost model fees even when nobody answers. The pages do not publish a separate preparation amount.
- Signup credit: the integrations README and the product FAQ say **100 free credits = US$1**. That sentence is not on the billing page.

**Three US one-shot calls of about 60 seconds:** 3 × $0.2176 = **$0.65**, inside the $1 signup credit. A call that runs past 60 seconds adds another $0.04 carrier minute plus another $0.0296 per 10 seconds of model time. Three 90-second calls are about **$1.04**, just over that credit. Keep each call short. A no-answer can still cost preparation; the amount is not published.

**Recommended top-up for a 3-call phone demo:** **$0** if the 100 credits are unused and each call stays near a minute. Vapi browser calls stay on the separate **$5** Vapi credit. Vapi's paid minimum is still unpublished.

## Layout

```
plugin.yaml                manifest v2, three tools, two hooks, secret config
__init__.py                Hermes entry point, re-exports register
hermes_call_me/
  plugin.py                register(ctx): tools, hooks, skill, commands. No network
  schemas.py               what the model sees
  tools.py                 handlers, JSON strings, errors instead of raises
  service.py               approval / help / report flows
  policy.py                daily cap, quiet hours, one call at a time
  hooks.py                 pre_tool_call guard, pre_llm_call inbound tasks
  config.py                settings and secrets
  store.py                 SQLite call log
  vapi.py, assistant.py    Vapi browser client and voice agent
  calle.py, calle_call.py  CALL-E phone client
  server.py, webhook.py    local webhook and demo page
  inbound.py               owner phone requests into the session
  cli.py                   hermes call-me / python -m hermes_call_me
skills/call-me/            when to call, and what not to trust
tests/                     HTTP is stubbed here only
```

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

## License

MIT. See `LICENSE`.

The tests stub `perform_http` / `create_call`. The server code path is urllib to `https://api.vapi.ai`. A missing key raises before that request.
