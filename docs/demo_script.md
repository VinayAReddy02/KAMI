# Live demo script (5 to 7 minutes)

A script for presenting KAMI live: what to type, what to click, what to say, and what to do if the network fails.
Commands are for PowerShell in the project folder. Times are a guide.

**Say these two caveats at the start and once more at the end:**
- The infrastructure data are a simulation (BattLeDIM) replayed by a virtual sensor node; the quality data are real river records. There is no physical hardware.
- The tanker schedule, the wards and the notices of the citizen bot are fictional demo data.

## Before the audience arrives (10 minutes)

1. Laptop on mains power and on Wi-Fi. Phone with Telegram open on the bot (t.me/KAMI67_BOT), same account whose chat id is in `.env`.
2. `.env` has `KAMI_TELEGRAM_ENABLE=1` and `KAMI_CITIZEN_ENABLE=1`. Ollama is running (`ollama list` shows the model in `OLLAMA_MODEL`).
3. Start the demo. Port 8000 is reserved by Windows on this laptop, so use 8200:

   ```powershell
   .\.venv\Scripts\python scripts\run_demo.py --port 8200
   ```

   This is the fallback mode (one process), which is the safest for a presentation. Wait for these lines: `Alerts: Telegram on` and `Citizen bot: on`. The speech models load in the background (up to a minute). To show the real stack instead (MQTT broker, TimescaleDB, three processes), start Docker Desktop first and add `--mode docker`; everything else in this script is the same.
4. Open http://127.0.0.1:8200 in the browser, full screen, dark theme.
5. Warm up the voice path once, so the first real question is fast: on the phone send a voice note "test" and wait for the reply.
6. Check that the replay speed shows ×600 (0.5 s per 5-minute step, the default). An injected burst lasts 12 to 48 simulated hours, which is only 1 to 5 minutes at this speed: that is why the script pauses the replay once the alert is on screen.

If step 3 prints `Alerts: dry run (...)` or `Citizen bot: off (...)`, the text in brackets names the setting that is missing. The demo still works in that state with the fallback plan below.

## The demo

| Time | Do | Say |
|---|---|---|
| 0:00 | Show the Overview page. | "KAMI watches flow, pressure, turbidity and TDS at 8 points of a water network and tells apart infrastructure problems from water-quality problems. This network has a fictional layout; the data are replayed public data, the infrastructure part is a simulation." |
| 0:40 | Point at the status strip: 8 nodes, all Normal. Point at the footer: `Alerts: Telegram on`. | "With nothing injected the network stays quiet. In a replay of 14 simulated days on all 8 nodes it opened no alert at all (`results/demo_quiet/quiet_demo.md`). That is a property of this replayed demo data, not a false-alarm rate." |
| 1:10 | In the control bar choose Event **Burst (sudden)**, Node **Gandhi Nagar Tank**, click **Inject event**. | "I now inject a sudden burst at one node. The injected event comes from the same scenario generator that was used for the evaluation." |
| 1:30 | Wait a few seconds: the marker of Gandhi Nagar Tank changes to Infrastructure with a priority, and an entry appears in the live alert feed. | "The marker changes shape, colour and text. The system reports a category, a priority and a confidence." |
| 1:50 | Click the marker. On the node page point at the "Why" box, the two evidence bars and the pressure and flow charts. | "This is the explanation with the numbers behind it: the model score of each stream, how long it has been high, how suddenly it rose. The method was frozen before the final test; on the fresh test set it did not beat simple threshold voting on event F1 by a detectable margin, and it named the category correctly more often." |
| 2:20 | Go back to the Overview and click **Pause** in the control bar. | "I pause the replay here, so the alert stays open while we look at the other side of the system." |
| 2:30 | Show the phone: the Telegram alert has arrived. Read it out. | "The same alert goes to the control room as a message, in plain words, with one generic action line. It never names a cause." |
| 3:10 | On the phone, record a Hindi voice note to the bot: **"वार्ड 2 में टैंकर कब आएगा?"** (Ward 2 is Gandhi Nagar). | "Now the citizen side. A resident asks in Hindi when the tanker comes to Ward 2. Speech recognition, translation, the language model and the voice all run on this laptop." |
| 3:40 | The bot replies with text and a voice note. Play the voice note. Point at "मैंने सुना:" (what was understood) and at the note about a possible delay. | "The time comes from the schedule data, never from the language model. Because Ward 2's sensor point has an open High alert, the bot adds that the tanker may be delayed. It does not say why." |
| 4:20 | Type in English: **Is there any problem in Ward 2?** | "It answers in the language of the question and says only what the sensors show." |
| 4:40 | On the phone send a photo to the bot (any photo of a pipe or a tap), then share a location near the map area (attach > Location). | "A resident reports a damaged pipe: a photo and a location." |
| 5:10 | The bot replies with a ticket number and the nearest sensor point. In the browser open **Complaints**; then the Overview map shows a dashed "Report" marker. | "The report becomes a ticket linked to the nearest sensor point. The software does not look at what is in the photo; staff do." |
| 5:50 | Open the **Method** page. | "To close: the infrastructure data are simulated, the schedule is fictional, there is no hardware, and the photo is not analysed. What is real is the pipeline from sensor reading to alert to citizen answer, and an evaluation that reports where the method does not win." |

Optional, if there is time: type "Who won the cricket match?" to show the "I do not have that information" reply, or `/help`.

## If Wi-Fi or Telegram fails (fallback plan)

Nothing on the dashboard needs the internet except the map background. Continue with the dashboard only:

1. The injected event, the alert in the feed, the node page and the explanation work offline. If the map tiles do not load, the markers and labels still do.
2. Show the alert message without Telegram. The message of every alert is also kept when sending is off. Stop the demo (Ctrl+C), then:

   ```powershell
   $env:KAMI_TELEGRAM_ENABLE="0"; $env:KAMI_CITIZEN_ENABLE="0"
   .\.venv\Scripts\python scripts\run_demo.py --port 8200
   ```

   Inject the burst again and show the last message that was written to the dry-run log:

   ```powershell
   Get-Content results\notifications\dryrun_log.jsonl -Tail 1 | ConvertFrom-Json | Select-Object -ExpandProperty text
   ```
3. Citizen bot without Telegram: show the evaluation tables in `results/citizen/eval.md` and the stored answers in `results/citizen/test_outputs.json` (question, what was heard, answer), and the Complaints page (it is empty until a report arrives).
4. If Ollama is not running, the bot answers with its fixed sentences automatically; nothing has to be changed. If the GPU is busy and voice is slow, type the question instead of speaking it.

## What can go wrong

| Symptom | Cause | What to do |
|---|---|---|
| `error while attempting to bind on address ... 8000` | Windows reserves ports 7981 to 8080 on this laptop | start with `--port 8200` |
| `Alerts: dry run (...)` | a Telegram setting is missing or sending is off | the text in brackets names it; see `docs/notifications.md` |
| `Citizen bot: off (...)` | `KAMI_CITIZEN_ENABLE` is not 1, or a setting is missing | see `docs/citizen.md` |
| The bot says voice notes cannot be processed right now | the speech models are still loading, or the speech packages are not installed | wait a minute, or type the question |
| No Telegram alert after an injection | one message per node per 10 minutes; only High and Critical | inject at another node |
| The bot does not answer at all | another program is polling the same bot, or the chat is not on the allowlist | stop the other program; check `TELEGRAM_CHAT_ID` |
| The injected event shows as Infrastructure, not Combined | known behaviour of the frozen rule (`docs/decisions.md`, Round 3) | say so; use a burst for the demo |

## After the demo

Ctrl+C in the terminal stops everything. Tickets of this run are kept only until the next start of `run_demo.py`; the photos stay in `data/citizen/uploads/` (git-ignored) until you delete them.
