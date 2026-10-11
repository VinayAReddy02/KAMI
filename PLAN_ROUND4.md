# KAMI Round 4: replace the WhatsApp alert push with a Telegram bot

Same rules as CLAUDE.md, including *Working mode* (Opus 5.5 high, single agent, token-efficient). Do NOT re-tune, re-freeze or re-evaluate anything: `results/fusion/`, `results/round2/` and the held-out logs are final.

## Decided by the user (2026-10-12)
- **Why:** the Twilio "Try out WhatsApp" trial only sends fixed, pre-approved Twilio templates (error 21654 "ContentSid required"), so an alert could only say that something happened, not which node, category, priority or why. A Telegram bot sends free-form text, is free, has no 24-hour window, no join expiry and no trial quota.
- **Remove all WhatsApp/Twilio code and start the alert-push part fresh for Telegram.** No WhatsApp/Twilio backend is kept, not even as an option. History stays only in `docs/decisions.md` (Round 3 section) and `PLAN_WHATSAPP.md` (marked superseded).
- **This round is code only.** No real Telegram request is made in this round (no `getUpdates`, no `sendMessage`, not even a "quick check"). The user tests the bot together with the planning assistant after this round.
- **Not in this round:** Docker, Playwright, screenshots, accessibility. They moved to Round 5 (`PLAN_ROUND5.md`).
- **Scope:** outbound alerts only, as in Round 3. No inbound commands, no webhook, no polling loop in the running system, no LLM, no voice. Ideas go under "Proposed" in docs/decisions.md.
- **Secret:** the bot token lives only in the git-ignored `.env` as `TELEGRAM_BOT_TOKEN` (the user adds it). The bot is t.me/KAMI67_BOT (username is not secret). Never print, log, commit or copy the token or the chat id, never put them in tests, fixtures, docs or error text. Telegram puts the token in the request URL (`/bot<TOKEN>/...`), so URLs must never be logged: keep httpx/httpcore loggers at WARNING and never include an exception's text or a URL in a log line.
- **Deleting (one-time exception to CLAUDE.md rule 8 for this round):** remove the files listed in T1 with `git rm <file>`, one named file per command. No recursive deletes, no wildcards.

## Tasks (write `scripts/check_telegram.py` first and extend it as you go)

T0. Inventory. `git grep -n -i -E "whatsapp|twilio"` and list every hit in PROGRESS.md (one line per file). Expected: `src/kami/notify/*`, `src/kami/api/app.py`, `src/kami/live/system.py`, `src/kami/live/frozen.py` (docstring), `scripts/run_demo.py`, `scripts/send_test_alert.py`, `scripts/check_whatsapp.py`, `tests/conftest.py`, `tests/whatsapp/*`, `frontend/src/components/AlertPushStatus.tsx` (+ test), `frontend/src/types.ts`, `.env.example`, README, docs.
   Write `scripts/check_telegram.py` (exit 0 only if every criterion at the bottom holds, reading real artefacts).

T1. Remove the WhatsApp code.
   - `git rm`: `src/kami/notify/twilio.py`, `scripts/check_whatsapp.py`, `tests/whatsapp/test_notify.py`, `tests/whatsapp/conftest.py`, `tests/whatsapp/__init__.py`.
   - **Keep the W-1 test** (it is about the frozen live rule, not WhatsApp): `git mv tests/whatsapp/test_live_frozen.py tests/live/test_live_frozen.py` (add `tests/live/__init__.py` if the other test folders have one) and update the reference in `src/kami/live/frozen.py` and docs/decisions.md.
   - Old generated state: `git rm` (or remove the single file if untracked) `results/notifications/state.json` and `results/notifications/dryrun_log.jsonl` if present. They counted Twilio requests.
   - `.env`: remove only the lines whose key is one of `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `WHATSAPP_TO`, `KAMI_WHATSAPP_ENABLE`, `WHATSAPP_MAX_TOTAL`, `TWILIO_CONTENT_SID`, with a small Python read-modify-write that matches on the key name and never prints or logs any value. Keep every other line (including `TELEGRAM_BOT_TOKEN` if the user already added it). If `.env` does not exist, do nothing.
   - Rewrite the rest of `src/kami/notify/` fresh for Telegram (T2). Channel-neutral logic from Round 3 (trigger rule, cooldown, hourly cap, dry run, background sending, never crashing the loop) may be re-implemented or adapted, but no name, comment, string, setting or state key may mention WhatsApp or Twilio afterwards.

T2. Telegram notifier, `src/kami/notify/`.
   - `Notifier` interface with `DryRunNotifier` (default; appends each message to `results/notifications/dryrun_log.jsonl`) and `TelegramNotifier`: one HTTPS POST to `https://api.telegram.org/bot<TOKEN>/sendMessage` with `chat_id` and `text` using `httpx` (already a dependency, no Telegram SDK). Plain text, no `parse_mode` (avoids escaping failures). `disable_web_page_preview=true`.
   - Settings (`settings.py`, `.env.example` with placeholders only): `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`, `KAMI_TELEGRAM_ENABLE=0`. Telegram is used only when `KAMI_TELEGRAM_ENABLE=1` AND both token and chat id are present AND the caller allows real sending (as in Round 3: only `scripts/run_demo.py` normal start and `scripts/send_test_alert.py`; every check, test and `launch` default forces dry run). Otherwise dry run, and log which setting is missing (names only).
   - Trigger rule (unchanged from Round 3, unit-tested): send when an alert episode OPENS at High or Critical, or ESCALATES to High or Critical. One message per node per 10 minutes, 30 per hour overall, never repeat an unchanged state. No lifetime budget (Telegram is free); remove that concept.
   - Message text (plain, under 600 characters): first line `[KAMI DEMO - simulated data]`, then node name, category, priority, confidence, the explanation from the fusion output (real values) and time. Test message (`send_test_alert.py`): category "TEST" and the words "TEST MESSAGE ... not an alert".
   - Failures: never crash or block the processing loop (background queue). Retry at most twice with backoff on network errors and 5xx. HTTP 429: wait `parameters.retry_after` seconds (cap 60) once, then give up. 401 (bad token), 400 "chat not found", 403 (user blocked the bot or never pressed Start): no retry, one clear fixed-sentence log line each (for example "Telegram: bot token rejected, check TELEGRAM_BOT_TOKEN in .env"; "Telegram: chat not found, press Start in the bot and run scripts/telegram_find_chat.py"). Log only fixed sentences, the HTTP status and Telegram's `error_code`; never the URL, the token, the chat id, Telegram's `description` text or an exception text.
   - State file `results/notifications/state.json`: counts sent, suppressed, failed, last send time. No token, no chat id.

T3. Chat id helper `scripts/telegram_find_chat.py` (written now, NOT run in this round). Reads the token from `.env`, calls `getUpdates` once, takes the newest private chat, and writes or replaces only the `TELEGRAM_CHAT_ID=` line in `.env`. Prints only "Chat id saved for <first name>" or a clear instruction ("Open t.me/KAMI67_BOT, press Start, send any message, then run this again"). Never prints the token or the id. Unit-test it with mocked HTTP and a temporary `.env`.

T4. Wiring, API and dashboard.
   - `src/kami/live/system.py`, `scripts/run_demo.py`: same behaviour as Round 3 with Telegram. `run_demo.py` prints "Alerts: Telegram on" or "Alerts: dry run (<reason>)".
   - `GET /notifications/status`: `mode` is `dry_run` or `telegram`, counts, last send time, limits. No token or chat id.
   - Frontend: `types.ts` mode `"dry_run" | "telegram"`; `AlertPushStatus.tsx` shows "Alerts: dry run" or "Alerts: Telegram on" (colour + icon + text, as the design brief requires); update its Vitest test.

T5. Tests `tests/telegram/` (mocked HTTP only). A fixture must make any real network request fail the test. Cover: trigger rule, escalation, cooldown, hourly cap, unchanged state not repeated, dry-run fallback for each missing setting, 401/400/403/429/5xx handling, retries, loop never crashes, message under 600 characters, token and chat id never appear in logs, state file, API response or dry-run log (grep test with a fake token such as `123456:TEST-TOKEN`), the chat-id helper. Update `tests/conftest.py` to clear the new `.env` keys instead of the old ones.

T6. Docs.
   - Rewrite `docs/notifications.md` for Telegram: creating the bot (@BotFather `/newbot`), adding `TELEGRAM_BOT_TOKEN` to `.env`, pressing Start, running `scripts/telegram_find_chat.py`, setting `KAMI_TELEGRAM_ENABLE=1`, `scripts/send_test_alert.py`, what the message looks like, limits, failures and what they mean, how to turn it off.
   - README: replace the WhatsApp section with a Telegram section; update the scripts/tests listing and the plan file list (`PLAN_ROUND4.md`, `PLAN_ROUND5.md`; `PLAN_WHATSAPP.md` superseded).
   - docs/decisions.md, new section "Round 4 (WhatsApp replaced by Telegram)": why (template-only trial, error 21654), what was removed, the new trigger/limits, no lifetime budget, plain text instead of HTML/Markdown, the redaction rules. Limitation for the paper: Telegram is less common than WhatsApp among citizens in India; a citizen-facing WhatsApp channel would need a verified WhatsApp Business sender and approved templates (paid). Move the Round 3 "Inbound WhatsApp bot" Proposed item to "Inbound Telegram commands (status, acknowledge)".
   - `scripts/make_summary.py` / `results/SUMMARY.md`: only if they mention WhatsApp; regenerate with the script, never by hand.

T7. Close out. Run `scripts/check_telegram.py`, `scripts/check_round2.py --quick`, every `scripts/check_step_N.py`, `pytest -q`, `npm run build`, `npm run test`. Update PROGRESS.md and CLAUDE.md round history (Round 4 done). Commit `round 4: whatsapp alert push replaced by telegram bot (dry run default)`. STOP. Do not send a real message; the user tests the bot next.

## check_telegram.py exits 0 only if
- `git grep -i -E "whatsapp|twilio"` finds nothing outside `docs/decisions.md`, `PLAN_WHATSAPP.md`, `PLAN_ROUND4.md`, `PLAN_ROUND5.md`, `PROGRESS.md`, `CLAUDE.md` and `docs/reference/` (history and the teacher's notes only)
- `tests/telegram` passes with no network access and at least one test proves a real request would fail
- `.env` is git-ignored and is not tracked; no tracked file contains a string matching a Telegram token pattern (`\d{8,10}:[A-Za-z0-9_-]{35}`)
- `GET /notifications/status` (in-process test client) returns `dry_run` by default and contains no token or chat id
- `tests/live/test_live_frozen.py` passes
- all earlier checks still pass and no file under `results/fusion/` or `results/round2/` changed in this round (compare with git)
