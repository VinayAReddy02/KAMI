# Alert push to WhatsApp (outbound only)

KAMI can push a short text message when a node goes into a High or Critical alert. This is an add-on to the live demo
(Round 3). It only sends. There is no inbound handling, no webhook, no commands, no voice, no photos and no language model.

**Default: dry run.** Out of the box nothing leaves the machine. Each message is appended to
`results/notifications/dryrun_log.jsonl` (git-ignored). WhatsApp is used only when you switch it on in `.env` with your
own Twilio account, and only by `scripts/run_demo.py` and `scripts/send_test_alert.py`. Every check script and every test
forces a dry run, whatever `.env` says.

All data in the demo are simulated or replayed, so every message starts with `[KAMI DEMO - simulated data]`.

## When a message is sent (trigger rule)

| Rule | Value |
|---|---|
| Trigger | an alert episode **opens** with priority High or Critical, or an open episode **escalates** to High or Critical (to a higher priority than the one already notified for it) |
| No repeat | an episode is never notified twice at the same priority. A change of category alone, a de-escalation and the closing of an episode send nothing |
| Cooldown | at most one message per node per 10 minutes (wall-clock time, not replay time) |
| Hourly cap | at most 30 messages in any 60 minutes, over all nodes |
| Lifetime budget | at most `WHATSAPP_MAX_TOTAL` requests to Twilio in total (default 80), kept across restarts |

A trigger that a limit holds back is counted as *suppressed* and is not marked as notified, so a later change of the same
episode can still be sent once the limit allows it. The processor reports an episode only when its category or priority
changes, so an escalation that falls inside the cooldown is usually not sent at all. At the default replay speed (600x)
ten minutes of wall-clock time are about four days of replayed data, so expect one message per node per demo session.

The rule is in `src/kami/notify/rules.py` and is tested in `tests/whatsapp/test_notify.py`. It listens to the alert events
of the live processor. Fusion and evidence code are not involved.

## Message text

Plain text, always under 600 characters. A real message from a dry run (2026-10-11, injected combined event on node-3):

```
[KAMI DEMO - simulated data]
Node: Sathuvachari Main (node-3)
Category: Infrastructure | Priority: High | Confidence: 0.29
Infrastructure anomaly, priority High (confidence 0.29): infrastructure evidence 1.00, above threshold for 1.8 h, suddenness 1.00, 1 episode(s) in the last 7 days.
Replay time: 2018-01-07 17:50
```

The category, priority, confidence and explanation are the values of the assessment that raised the alert. Two things to
know when reading it:

- The live demo runs the fusion rule frozen in Round 2. It reported this injected *combined* event as Infrastructure
  (see `docs/decisions.md`, Round 3, W-1).
- Confidence is the pignistic probability of the reported category. It can be low while the alert is still High, for
  example when the other stream shows evidence that the rule has not confirmed yet.

"Replay time" is the timestamp of the replayed data, not the time on your clock.

## Setup (your own Twilio WhatsApp sandbox)

You need a Twilio account. KAMI never creates accounts and never asks for your credentials anywhere except `.env`.

1. **Join the sandbox.** In the Twilio console open *Messaging > Try it out > Send a WhatsApp message*. It shows the
   sandbox number (`+1 415 523 8886`) and a join code. From the WhatsApp account that should receive the alerts, send
   `join <your code>` to that number.
2. **Create `.env`.** Copy `.env.example` to `.env` in the repository root and fill it in:

   | Setting | What to put |
   |---|---|
   | `TWILIO_ACCOUNT_SID` | Account SID from the Twilio console |
   | `TWILIO_AUTH_TOKEN` | Auth Token from the Twilio console |
   | `TWILIO_WHATSAPP_FROM` | the sandbox number, written as `whatsapp:+14155238886` |
   | `WHATSAPP_TO` | your number with country code, written as `whatsapp:+91...` |
   | `KAMI_WHATSAPP_ENABLE` | `1` to send, `0` for dry run |
   | `WHATSAPP_MAX_TOTAL` | lifetime budget, default 80 |

   `.env` is git-ignored. Do not put these values anywhere else (not in code, tests, docs or chat).
3. **Send one test message.**

   ```
   python scripts/send_test_alert.py
   ```

   With `KAMI_WHATSAPP_ENABLE=1` and all four values set, this sends exactly one message that says `TEST MESSAGE` and
   prints the result. In every other case it prints "Dry run, nothing was sent" and writes the message to the dry-run log.
   A real test message counts against the budget.
4. **Run the demo.** `python scripts/run_demo.py` prints `Alerts: WhatsApp on` or `Alerts: dry run` with the reason.
   The dashboard footer shows the same line with the counts.
5. **Switch it off.** Set `KAMI_WHATSAPP_ENABLE=0` (or delete the line) and restart.

WhatsApp is used only if `KAMI_WHATSAPP_ENABLE=1` **and** all four credentials are present and well formed (both numbers
must look like `whatsapp:+<digits>`). Otherwise KAMI falls back to dry run and logs which setting is missing, by name
only. Variables set in the process environment take precedence over `.env`.

## Sandbox limits you will meet

- **The join expires after 3 days.** Then Twilio answers with error 63015 and KAMI logs
  `recipient has not joined the sandbox or the join expired: send the join code to the sandbox number again`.
- **24-hour window.** Free-form text is allowed only within 24 hours after the recipient last wrote to the sandbox
  number (sending the join code also opens the window). Outside it Twilio rejects the message with error 63016. KAMI
  logs one line, `window closed: reply to the sandbox number to reopen`, counts the message as suppressed and does not
  retry. Send any message (for example "hi") to the sandbox number and try again.
- **Cost.** Sandbox messages are billed at Twilio's normal WhatsApp rates (about 0.005 USD per message in Twilio fees
  when this was checked on 2026-10-10; trial accounts included 100 free WhatsApp messages). Check the current prices in
  your Twilio console. This is why there is a lifetime budget.
- **Only numbers that joined** your sandbox can receive messages.

## Budget

`WHATSAPP_MAX_TOTAL` (default 80) is a lifetime limit on requests to Twilio. Every request counts, including retries
and requests that Twilio rejects. The count is kept in `results/notifications/state.json`, so it survives restarts.
When it is used up, sending stops and further triggers are counted as suppressed ("budget").

To start a new budget, delete that single file by hand. This is deliberately not automatic. If the file is damaged,
KAMI does not guess: it stops sending and says so in the status.

In dry run the same limits are applied, so the dry-run log shows what would have been sent, but the count starts at
zero on every run and nothing is stored.

## Failures

Sending happens in a background thread with a bounded queue. The processing loop never waits for Twilio and cannot be
stopped by an error in this module.

| What happens | What KAMI does |
|---|---|
| Network error, timeout, HTTP 429 or 5xx | retry at most twice (after 2 s and 6 s), then count as failed |
| Error 63016 (window closed) | one log line, counted as suppressed, no retry |
| Error 63015 (not joined / join expired) | one log line, counted as failed, no retry |
| HTTP 401/403 or error 20003 | `Twilio rejected the credentials: check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env`, no retry |
| Any other rejection | `Twilio did not accept the message (HTTP <status>, Twilio error <code>)`, no retry |
| Accepted, but reported as failed afterwards | one status check about 20 s after sending; the message is then moved from sent to suppressed or failed |

After a window, sandbox or credentials error, sending is paused for 10 minutes (triggers are counted as suppressed,
"on_hold"), because the next requests would fail the same way and would only use up the budget.

Log lines contain a fixed sentence, the HTTP status and Twilio's numeric error code. They never contain the request,
the URL (it includes the Account SID), the recipient number, Twilio's error text or an exception text.

## Status

`GET /notifications/status` returns the mode, the counts and the limits, and no credential or number. Response of a
dry run started by a check on 2026-10-11 (one message logged, the escalation to Critical held back by the cooldown; the
time is shortened here):

```json
{"mode": "dry_run", "detail": "dry run: forced for this run (checks and tests never send)", "sent": 1, "suppressed": 1, "failed": 0,
 "suppressed_by": {"cooldown": 1}, "last_send_utc": "2026-10-11T...", "last_problem": null, "queued": 0,
 "messages_last_hour": 1,
 "limits": {"min_priority": "High", "cooldown_seconds_per_node": 600.0, "max_per_hour": 30, "max_total": 80},
 "budget_used": 1, "budget_remaining": 79, "budget_scope": "this run only (dry run)"}
```

`mode` is `dry_run` or `twilio`. In dry run, "sent" means written to the dry-run log.

## What this is not

- **Not a citizen-facing service.** The sandbox is for testing with numbers that joined it. A real service needs a
  WhatsApp Business sender with a verified business, and messages sent outside the 24-hour window must use templates
  approved by WhatsApp.
- **No inbound bot and no voice.** Replies to the sandbox number are not read by KAMI. Both are future work and are
  listed under "Proposed" in `docs/decisions.md`.

## Where the code is

| File | Role |
|---|---|
| `src/kami/notify/settings.py` | reads `.env` and the environment; values are never printed |
| `src/kami/notify/rules.py` | trigger rule, cooldown, hourly cap, budget |
| `src/kami/notify/message.py` | message text |
| `src/kami/notify/dryrun.py`, `twilio.py` | the two notifiers (plain HTTPS POST with `httpx`, no Twilio SDK) |
| `src/kami/notify/manager.py` | queue, background thread, retries, status |
| `scripts/send_test_alert.py` | one labelled test message |
| `scripts/check_whatsapp.py` | exit 0 only if the add-on criteria hold; cannot send |
| `tests/whatsapp/` | tests with mocked HTTP; a real request makes the test fail |
