> **SUPERSEDED (2026-10-12).** Kept as history of Round 3 only. The WhatsApp/Twilio code is removed in Round 4 and replaced by a Telegram bot (PLAN_ROUND4.md). Do not follow the tasks below.

# KAMI add-on: WhatsApp alert push (Level A only)

Do this ONLY after Round 2 (PLAN_ROUND2.md, task R8) is finished and committed. Same rules as CLAUDE.md, with the one exception below.

## Scope (decided by the user)
Outbound alerts only. No inbound messages, no webhook, no commands, no voice, no photos, no LLM, no Bhashini, no RAG. Anything else goes under "Proposed" in docs/decisions.md.

## Exception to the "no accounts, no keys" rule
The user has their own Twilio account (WhatsApp sandbox). Credentials live ONLY in `.env` in the repo root (git-ignored; verify `.env` is in .gitignore before anything else). Never create accounts, never print, log, commit or copy credential values, never put them in test fixtures or docs. Provide `.env.example` with placeholder names only:
```
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
KAMI_WHATSAPP_ENABLE=0
```

## Resume note (2026-10-11)
This round was started on 2026-10-10 and stopped before any commit. First review the existing files listed in PROGRESS.md (Round 3), keep what is correct, fix what is not, then continue with the first unfinished task. Work single-agent and token-efficiently (CLAUDE.md *Working mode*).

## Tasks
W-1. Live demo on the frozen Round 2 rule (do this first, it is a deployment change, not a method change). Make the streaming processor use the fusion design and parameters from `results/fusion/frozen_config.json` (read-only). Do not modify anything under `results/fusion/`, `results/round2/` or the held-out data, and do not run the final evaluation again. Add a test that, on a fixed validation sample, the live path gives the same category as the batch frozen rule. Show the method version (for example "Fusion F-B, frozen Round 2") on the About page. Re-run `scripts/check_step_6.py`; if its 60-second combined-event check now fails because the frozen rule is stricter, report it honestly in PROGRESS.md and adjust only the demo injection size if that is justified and documented.
W0. First task: scripts/check_whatsapp.py (exits 0 only if all criteria below hold, reading real artefacts).
W1. `src/kami/notify/` with a `Notifier` interface and two implementations: `DryRunNotifier` (default; writes each message to `results/notifications/dryrun_log.jsonl`) and `TwilioWhatsAppNotifier` (plain HTTPS POST to the Twilio Messages REST API using `requests` or `httpx`; no extra SDK). The Twilio notifier is used only when `KAMI_WHATSAPP_ENABLE=1` AND all four credentials are present; otherwise fall back to dry run and log which setting was missing (names only, never values).
W2. Trigger rule (documented in docs/notifications.md, unit-tested): send when an alert episode OPENS with priority High or Critical, or when an open episode ESCALATES to High or Critical. At most one message per node per 10 minutes (cooldown), at most 30 messages per hour overall (hard cap), never repeat for an unchanged state. Wire it into the existing alert lifecycle without changing fusion or evidence code.
W3. Message text (plain, under 600 characters): prefix `[KAMI DEMO - simulated data]`, then node name, category, priority, confidence, the explanation string from the fusion output (real values), and time. No emojis required; if used, keep text readable without them.
W4. Failure handling: network errors or non-2xx responses are logged (status code only, never the request body with credentials), retried at most twice with backoff, and never crash or block the processing loop (send in a background thread or queue). Twilio sandbox errors (for example the number has not joined the sandbox) are logged as a clear one-line message.
W5. API: `GET /notifications/status` returning mode (dry_run or twilio), counts sent/suppressed/failed, last send time. No credentials in the response. Add a small status line in the dashboard footer or About page showing "Alerts: dry run" or "Alerts: WhatsApp on".
W6. Tests (mock HTTP; tests must never send a real message and must fail if a real request is attempted): trigger rule, cooldown, hourly cap, escalation, dry-run fallback when credentials are missing, secrets never appear in logs or responses (grep test), failures do not crash the loop.
W7. docs: `docs/notifications.md` with a setup guide for the user (Twilio sandbox join, filling `.env`, enabling, how to test with `python scripts/send_test_alert.py`, which sends one clearly labelled test message only when enabled) and the sandbox limits (recipients must join the sandbox first and the join lapses after a few days; a citizen-facing bot would need a verified business number and template approval; inbound bot and voice are future work).
W8. Close out (W-1 included): check_whatsapp.py, all earlier check scripts, `pytest -q`, `npm run build`. Update README (one short section), PROGRESS.md and docs/decisions.md. Commit `whatsapp: alert push (dry run default)`. STOP.

## check_whatsapp.py exits 0 only if
- `.env` is git-ignored and no tracked file contains a string matching Twilio SID/token patterns
- with no credentials, an injected combined event produces a dry-run log entry containing real values from the assessment
- cooldown and cap tests pass; `GET /notifications/status` works and exposes no secrets
- all earlier checks and tests still pass

## Added constraints (verified against Twilio docs on 2026-10-10)
- Sandbox messages are billed at standard Twilio WhatsApp pricing (about $0.005 per message Twilio fee; trial accounts include 100 WhatsApp messages in free units). The 30/hour cap must therefore also have a lifetime budget: add `WHATSAPP_MAX_TOTAL` (default 80) and stop sending when reached; report it in /notifications/status.
- Free-form messages are allowed only within 24 hours after the recipient last messaged the sandbox number (sending `join <code>` also opens a window). Outside the window Twilio rejects free-form text. Handle that error as "window closed: reply to the sandbox number to reopen" (one clear log line, count as suppressed, no retries), and document it in docs/notifications.md.
- The sandbox join expires after 3 days.
