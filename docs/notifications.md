# Alert push through a Telegram bot (outbound only)

KAMI can push a short text message to a Telegram chat when a node goes into a High or Critical alert. It only sends.
There are no inbound commands, no webhook, no polling loop in the running system, no voice and no language model.

**Default: dry run.** Out of the box nothing leaves the machine. Each message is appended to
`results/notifications/dryrun_log.jsonl` (git-ignored). The bot is used only when you switch it on in `.env`, and only
by `scripts/run_demo.py` and `scripts/send_test_alert.py`. Every check script and every test forces a dry run, whatever
`.env` says.

All data in the demo are simulated or replayed, so every message starts with `[KAMI DEMO - simulated data]`.

## Setup

The bot for this project is [t.me/KAMI67_BOT](https://t.me/KAMI67_BOT). KAMI never creates accounts or bots.

1. **Bot token.** A bot is created once in Telegram by writing to `@BotFather` and sending `/newbot`; BotFather answers
   with the token. Copy `.env.example` to `.env` in the repository root (if you have no `.env` yet) and put the token in:

   ```
   TELEGRAM_BOT_TOKEN=<the token from BotFather>
   ```

   `.env` is git-ignored. The token is a password for the bot: do not put it anywhere else (not in code, tests, docs
   or chat). If it leaks, send `/revoke` to `@BotFather` and use the new one.
2. **Press Start.** Open the bot in Telegram, press **Start** and send any message. A bot cannot write to you first.
3. **Find your chat.**

   ```
   python scripts/telegram_find_chat.py
   ```

   It asks Telegram once for the latest messages sent to the bot, takes the newest private chat and writes the
   `TELEGRAM_CHAT_ID=` line in `.env`. It prints `Chat id saved for <first name>` and never the token or the id.
4. **Switch it on.** In `.env` set `KAMI_TELEGRAM_ENABLE=1`.
5. **Send one test message.**

   ```
   python scripts/send_test_alert.py
   ```

   With the three settings in place this sends exactly one message with category `TEST` and the words
   `TEST MESSAGE ... This is not an alert`, and prints the result. In every other case it prints
   "Dry run, nothing was sent" with the reason and writes the message to the dry-run log.
6. **Run the demo.** `python scripts/run_demo.py` prints `Alerts: Telegram on` or `Alerts: dry run (<reason>)`.
   The dashboard footer shows the same with the counts.

| Setting | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the bot token, as `<digits>:<letters, digits, _ and ->` |
| `TELEGRAM_CHAT_ID` | numeric id of the chat that receives the alerts (written by the helper script) |
| `KAMI_TELEGRAM_ENABLE` | `1` to send, anything else for dry run |

The bot is used only if `KAMI_TELEGRAM_ENABLE=1` **and** the token and the chat id are present and well formed.
Otherwise KAMI falls back to dry run and logs which setting is missing, by name only. Variables set in the process
environment take precedence over `.env`.

**To turn it off:** set `KAMI_TELEGRAM_ENABLE=0` (or delete the line) and restart. To stop the bot from writing to you
for good, block it in Telegram.

## When a message is sent (trigger rule)

| Rule | Value |
|---|---|
| Trigger | an alert episode **opens** with priority High or Critical, or an open episode **escalates** to High or Critical (to a higher priority than the one already notified for it) |
| No repeat | an episode is never notified twice at the same priority. A change of category alone, a de-escalation and the closing of an episode send nothing |
| Cooldown | at most one message per node per 10 minutes (wall-clock time, not replay time) |
| Hourly cap | at most 30 messages in any 60 minutes, over all nodes |

There is no total limit: Telegram bots are free to use. A trigger that a limit holds back is counted as *suppressed*
and is not marked as notified, so a later change of the same episode can still be sent once the limit allows it. The
processor reports an episode only when its category or priority changes, so an escalation that falls inside the
cooldown is usually not sent at all. At the default replay speed (600x) ten minutes of wall-clock time are about four
days of replayed data, so expect roughly one message per node per demo session.

The rule is in `src/kami/notify/rules.py` and is tested in `tests/telegram/test_notify.py`. It listens to the alert
events of the live processor. Fusion and evidence code are not involved.

## What the message looks like

Plain text (no Markdown or HTML, so nothing in the text can break the formatting), always under 600 characters, link
previews off. The values of a dry run on 2026-10-12 (injected sudden infrastructure event on node-2), in the Round 7 format that adds the
node number and the ward to the Node line (text produced by `format_message`):

```
[KAMI DEMO - simulated data]
Node: Gandhi Nagar Tank (node-2 · Ward 2)
Category: Infrastructure | Priority: High
Confidence: 0.69 (final fused value, not the model score)
Flow/pressure: unusual for 2 h, started suddenly, 1st episode in 7 days (model score 0.99, suddenness 0.91)
Action: Check pressure and flow at Gandhi Nagar Tank.
Replay time: 2018-01-07 18:30
```

Every word comes from the values of the assessment that raised the alert; nothing is invented.

| In the message | Where it comes from |
|---|---|
| `Confidence: 0.69` | the final fused value for the reported category. It combines both evidence streams and how long they have lasted, so it is usually lower than a single model score |
| `model score 0.99` | the calibrated output of one evidence model (flow/pressure or turbidity/TDS) at that moment. It is an input to the fusion, not the final answer |
| `unusual for 2 h` | how long that model score has stayed at or above 0.5 without a break (5-minute steps) |
| `started suddenly` / `built up gradually` | the suddenness value: `started suddenly` if the score rose by at least 0.5 within 15 minutes at some point in the last 2 hours (suddenness 0.5 or more), otherwise `built up gradually` |
| `1st episode in 7 days` | how many separate episodes of that stream started in the last 7 days |
| `Action: Check ...` | a generic line for the category: Infrastructure names pressure and flow, Quality names turbidity and TDS, Combined names both. It never names a cause |

A Combined alert has one reason line for each stream. If the text would get too long, the bracketed numbers are left
out first and a very long node name is shortened last; the prefix, the action line and the time always stay. The
dashboard still shows all numbers on the node page. The labelled test message from `send_test_alert.py` has no
assessment behind it, so it shows its fixed sentence instead of reasons and has no action line.

The live demo runs the fusion rule frozen in Round 2. It reports an injected *combined* event as Infrastructure (see
`docs/decisions.md`, Round 3, W-1). "Replay time" is the timestamp of the replayed data, not the time on your clock.

## Failures and what they mean

Sending happens in a background thread with a bounded queue. The processing loop never waits for Telegram and cannot
be stopped by an error in this module.

| What happens | Log line | What KAMI does |
|---|---|---|
| Network error or timeout | `Telegram: network error (<error type>)` | retry at most twice (after 2 s and 6 s), then count as failed |
| HTTP 5xx | `Telegram: service unavailable` | same |
| HTTP 429 (too many requests) | `Telegram: too many requests, the message was not sent` | wait the time Telegram asks for (at most 60 s) once, try once more, then give up |
| HTTP 401 or 404 | `Telegram: bot token rejected, check TELEGRAM_BOT_TOKEN in .env` | no retry |
| HTTP 400 "chat not found" | `Telegram: chat not found, press Start in the bot and run scripts/telegram_find_chat.py` | no retry |
| HTTP 403 | `Telegram: the bot may not write to this chat (it was blocked or Start was never pressed), press Start in the bot` | no retry |
| Any other rejection | `Telegram: the message was not accepted` | no retry |

Each failed message gives one line, `Alert message not sent: <sentence> (HTTP <status>, error_code <code>)`.
After a token, chat or blocked error, sending is paused for 10 minutes (triggers are counted as suppressed,
"on_hold"), because the next requests would fail the same way.

**Nothing secret is logged.** Telegram puts the bot token in the request URL, so log lines contain only a fixed
sentence, the HTTP status and Telegram's numeric `error_code`. They never contain the URL, the token, the chat id,
Telegram's own error text or an exception text, and the request logging of the HTTP library is switched off.

## Status and state

`GET /notifications/status` returns the mode, the counts and the limits, and never the token or the chat id. From a
dry run on 2026-10-12 local time (the time stamp is UTC and shortened here):

```json
{"mode": "dry_run", "sent": 1, "suppressed": 1, "failed": 0, "suppressed_by": {"cooldown": 1},
 "last_send_utc": "2026-10-11T...", "last_problem": null, "detail": "forced for this run (checks and tests never send)",
 "queued": 0, "messages_last_hour": 1, "limits": {"min_priority": "High", "cooldown_seconds_per_node": 600.0, "max_per_hour": 30}}
```

`mode` is `dry_run` or `telegram`. In dry run, "sent" means written to the dry-run log. The same counts and the last
send time are kept in `results/notifications/state.json` for the current run.

## What this is not

- **Not a citizen-facing service.** One bot writes to one chat that was set up by hand. Reaching residents would need
  a channel they already use and a way to subscribe; see the limitation noted in `docs/decisions.md` (Round 4).
- **No inbound commands and no voice.** Messages sent to the bot are not read by the running system (the helper script
  reads them once, during setup). Commands such as status or acknowledge are listed under "Proposed" in
  `docs/decisions.md`.

## Where the code is

| File | Role |
|---|---|
| `src/kami/notify/settings.py` | reads `.env` and the environment; values are never printed |
| `src/kami/notify/rules.py` | trigger rule, cooldown, hourly cap |
| `src/kami/notify/message.py` | message text: plain words from the real values, action line, length limit |
| `src/kami/notify/dryrun.py`, `telegram.py` | the two notifiers (one HTTPS POST to `sendMessage` with `httpx`, no SDK) |
| `src/kami/notify/manager.py` | queue, background thread, retries, status, state file |
| `scripts/telegram_find_chat.py` | one-time setup: saves the chat id in `.env` |
| `scripts/send_test_alert.py` | one labelled test message |
| `scripts/check_telegram.py` | exit 0 only if the Round 4 criteria hold; cannot reach Telegram |
| `tests/telegram/` | tests with mocked HTTP; a real request makes the test fail |
