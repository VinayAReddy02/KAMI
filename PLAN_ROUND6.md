# KAMI Round 6: citizen interface on the Telegram bot + Docker stack (Hindi + English voice with local open speech models, schedule answers, pipe-damage reports)

Same rules as CLAUDE.md, including *Working mode* (Opus 5.5 high, single agent, token-efficient). Do NOT re-tune, re-freeze or re-evaluate anything: `results/fusion/`, `results/round2/` and the held-out logs are final. This round adds a separate module; it must not change the anomaly models, the fusion rule or any frozen result.

> **Merged on 2026-10-12 by the user:** the Docker stack (formerly Round 7, `PLAN_ROUND7.md`) is now Part B of this round. Part A = citizen interface (C0 to C8), Part B = Docker (D1 to D5). There is no Round 7.

## Decided by the user (2026-10-12)
- **What:** the teacher's Phase 3, Step 2 "citizen interface". A citizen talks to the existing bot (t.me/KAMI67_BOT):
  1. sends a **voice note or text** in **Hindi or English**, e.g. "Ward 4 mein tanker kab aayega?" / "When will the water tanker reach Ward 4?";
  2. a **local speech model** turns Hindi or English speech into text (ASR) and Hindi text is translated to English (NMT), all on the user's laptop;
  3. the system **retrieves** the live tanker schedule and ward notices and writes the answer with a **local LLM (Ollama)**, grounded in what was retrieved;
  4. the answer is translated back to Hindi and spoken by a **local text-to-speech model**; the bot replies with **text + a voice note** in the citizen's language.
  5. A citizen sends a **photo of a broken pipe with a location**; it becomes a **complaint ticket** on the dashboard map, linked to the nearest sensor node, and the reply states that node's current KAMI status.
- **Languages:** Hindi and English only.
- **Answer writing:** option (b): retrieval + a free local LLM through Ollama. The LLM works in English only (the local translation model does the Hindi in and out).
- **Speech and translation: local open models, no Bhashini (user decision 2026-10-12).** Bhashini registration asks for incubator/organisation details that do not fit a student project, and nothing may be invented on that form. Use AI4Bharat-style open models run locally instead; the paper says "open Indian-language models run locally", and a Bhashini adapter is listed only as future work for a real deployment.
- **Photos:** ticket + nearest node only. **No image recognition / computer vision**; never claim the system recognises damage.
- **Order:** Round 5 is done. This is Round 6 and the last building round: Part A citizen interface (C0 to C8), Part C project documents (E1 to E3), Part B Docker stack (D1 to D5, merged in from the former Round 7). Order of work: A, then C, then B. After D5 the paper is written with the user (not in this round).
- **How to work (user instruction 2026-10-12):** take as much time as needed; quality over speed. Single agent only: never spawn subagents, parallel agents, background workflows or multi-reviewer runs. Work as a chain: one task at a time, finish it, run its tests, write one or two lines in PROGRESS.md (and update *Current step*), then start the next task in the same session. Commit at the end of each Part. If the session is interrupted (for example a usage limit), the next session resumes from PROGRESS.md at the first unfinished task without redoing finished ones.
- **Honesty:** the tanker schedule, wards and notices are **fictional demo data** (label `demo_fictional` in file names, docs and the bot's `/help`), like the fictional map. Replies keep a short demo marker.

## Hardware, models and installs (the user installs Ollama; never create accounts)
- **User's laptop (use it):** Intel i7 (14th gen), 16 GB RAM, 1 TB disk, NVIDIA RTX 4070 laptop GPU (8 GB VRAM). Check with `nvidia-smi` first. Use the GPU (CUDA) for speech, translation and TTS where it helps, with a CPU fallback. Budget the 8 GB VRAM: speech + translation + TTS + LLM must fit together, or models are loaded on demand and unloaded (document which). Keep total model downloads under about 15 GB.
- **Local speech stack (downloads approved; pip packages and Hugging Face models only; no system installs except the NVIDIA driver that is already there):**
  - ASR: compare `faster-whisper` (`large-v3-turbo` or `medium`, CUDA float16; it can also translate Hindi speech straight to English) with AI4Bharat **IndicConformer** (Hindi) on the validation questions; pick by word error rate and latency; record the choice.
  - Translation hi<->en: AI4Bharat **IndicTrans2** distilled (~200M) models (`ai4bharat/indictrans2-indic-en-dist-200M`, `ai4bharat/indictrans2-en-indic-dist-200M`) via transformers; if a model needs a Hugging Face login/licence click, stop that model, log it under Needs user and use the other option (Whisper translate for hi->en; the LLM is NOT used to translate into Hindi).
  - TTS: compare AI4Bharat **Indic Parler-TTS** (GPU) with a **Piper** Hindi voice (fast, CPU); pick by naturalness (listen-free checks: it must round-trip through the chosen ASR with low WER) and latency; English TTS with Piper or Parler.
  - PyTorch with CUDA from the official PyTorch index (pick the CUDA wheel that matches the driver). Pin every version in `requirements-citizen.txt` (separate from the frozen `requirements.txt`).
- **Ollama:** the user has installed Ollama for Windows (version 0.40.3 confirmed 2026-10-12; local use only: never run `ollama signin`, never use `:cloud` models). Claude Code may then run `ollama pull <model>` (download approved). With 8 GB VRAM, default `qwen2.5:3b` or `llama3.2:3b` (about 2-3 GB); also try one 7-8B model (`qwen2.5:7b` or `llama3.1:8b`, Q4) on the validation questions and keep it only if it fits alongside the speech models and is clearly better. Record the choice and why. If Ollama is not installed or not running, the answer writer falls back to the template writer (C4) and logs it; the round still completes, and the LLM evaluation is marked pending.
- **ffmpeg:** use the `imageio-ffmpeg` pip package (bundled binary, no system install) to convert Telegram OGG/Opus <-> WAV 16 kHz mono.
- Retrieval: BM25 or TF-IDF over the English documents (scikit-learn, no model download). Embeddings are optional and only if clearly better on the validation questions.

## Safety rules for this round
- **Allowlist:** the bot only answers chats in `TELEGRAM_CHAT_ID` plus an optional `CITIZEN_ALLOWED_CHAT_IDS` list; everything else gets one fixed "demo bot, not public" reply (rate-limited) and is not processed.
- **Off by default:** inbound handling runs only with `KAMI_CITIZEN_ENABLE=1` and only from `scripts/run_demo.py` (normal start) and `scripts/run_citizen_bot.py`. Tests and checks never poll Telegram and never call Ollama or load the real speech models (fixtures refuse network). The outbound alert push from Round 4 keeps working unchanged.
- **Polling, not webhook:** a background thread long-polls `getUpdates` with an offset (no public URL needed on a laptop). Never crash or block the sensor loop. Per-chat rate limit (e.g. 10 requests per minute).
- **Grounding guard:** every time, date, ward, tanker id and number in an LLM answer must appear in the retrieved records; otherwise the answer is replaced by the template answer and the event is counted as a "guard fallback". If nothing relevant is retrieved, the bot says it does not have that information (in the citizen's language). The LLM never invents schedule data.
- **Privacy:** voice files and photos are stored only under `data/citizen/` (git-ignored), with size limits (voice 60 s, photo 10 MB, JPEG/PNG only). Logs contain no chat ids, names, phone numbers, coordinates of the citizen beyond the ticket record, or message text beyond what the evaluation needs.
- **No cause claims** in any reply ("leak", "contamination" are not stated as facts).

## Tasks (write `scripts/check_round6.py` first and extend it as you go)

C0. Design note + check script. `docs/citizen.md`: architecture (Telegram polling -> router -> ASR/NMT -> retrieval -> answer writer (LLM or template) -> guard -> NMT/TTS -> reply), data, limits, failure modes. `scripts/check_round6.py`.

C1. Demo data (`data/citizen/`, tracked except uploads; all `demo_fictional`):
   - `wards.json`: 8 wards, each mapped to one sensor node from `config/nodes.json` (Ward N <-> node-N, using the node's locality name), with Hindi and English names.
   - `tanker_schedule.csv`: tanker id, ward, scheduled date/slot, status (scheduled, en route, delivered, delayed), relative to the replay clock, generated by a seeded script `scripts/build_citizen_data.py`.
   - **Live status:** the schedule service reads the live KAMI state: if a node has an open High/Critical alert, tankers for its ward are marked "possibly delayed: active network alert in your area" (no cause stated). Deterministic and unit-tested.
   - `notices/`: 10-20 short English notices and FAQ entries (water timings, how to report a pipe, what the alert levels mean, whom to call: a fictional number clearly marked).

C2. Telegram inbound (`src/kami/citizen/telegram_in.py`): getUpdates polling with offset, allowlist, rate limit, `/start`, `/help`, `/language hi|en` (per-chat language, default Hindi; Devanagari text auto-detects Hindi), text, voice (getFile -> download OGG), photo (largest size) and photo sent as file (keep EXIF), location messages. Replies: sendMessage and sendVoice (OGG/Opus). Same token redaction rules as `notify/telegram.py` (the URL contains the token).

C3. Language layer (`src/kami/citizen/speech.py`, `translate.py`, `tts.py`): one interface per stage (ASR, NMT, TTS) with the local implementations from "Local speech stack" above, models loaded once and reused, GPU if available with CPU fallback, timeouts, clear one-line errors (no audio or text in logs). English input skips NMT. A warm-up at start-up so the first citizen does not wait for model loading. Record model names, versions, VRAM use and load times in docs/citizen.md.

C4. Retrieval + answer writer (`src/kami/citizen/answer.py`):
   - Intent + slot extraction (ward number/name, date words like today/tomorrow/kal) with rules first; the LLM may help only if rules fail.
   - Structured lookup for schedule questions (the time always comes from `tanker_schedule.csv` + live status), BM25/TF-IDF retrieval for notices/FAQ.
   - Two writers behind one interface: `TemplateWriter` (fixed sentences) and `OllamaWriter` (local LLM, English, prompt = retrieved records only, temperature 0, short answers). Grounding guard (see rules) on every LLM answer.

C5. Pipe-damage tickets (`src/kami/citizen/tickets.py`): location from a Telegram location message or EXIF GPS (photo sent as file); if the photo has no location, ask for one and keep the photo pending for 10 minutes. Nearest node by haversine (report the distance; "outside the demo area" if > 3 km). Store tickets through the existing storage interface (new table). Reply: ticket id, nearest node, and that node's current KAMI category/priority in plain words ("our sensors there currently show no anomaly" / "...show an Infrastructure alert, priority High"). API `GET /complaints`; dashboard: ticket markers on the map (distinct icon + text, colour-blind safe) and a Complaints list with photo thumbnail, time, nearest node, status. Playwright test for the new UI.

C6. Evaluation (separate from the frozen anomaly results; `results/citizen/`):
   - Question set `data/citizen/eval_questions.jsonl`: at least 60 questions (30 English, 30 Hindi, written in this round and labelled as authored test questions), covering schedule questions for every ward, notices/FAQ, unanswerable questions (must say "no information"), and tricky slots (ward names in Hindi, "kal"). Expected answer = the structured truth. Split 20 validation / 40 test; tune prompts and retrieval on validation only, run test once per writer.
   - Metrics per writer (Template vs Ollama) and per language: slot accuracy, answer correctness (time/status match), grounding violations before the guard, guard fallbacks, "no information" correctness, median and p90 latency per stage. Table in `results/citizen/eval.md` + JSON.
   - Voice path (local, no API limits): synthesise the Hindi and English test questions with the chosen TTS, run them back through the chosen ASR, report word error rate and end-to-end correctness, and the per-stage latency on the user's GPU. Label this as synthetic speech. Real voice notes recorded by the user are a later, separate step (add to Needs user).
   - No real Telegram message in C6.

C7. Wiring + docs: `scripts/run_citizen_bot.py` (bot only) and the `run_demo.py` integration (Alerts + citizen bot in one process), `.env.example` placeholders (`KAMI_CITIZEN_ENABLE=0`, `CITIZEN_ASR=`, `CITIZEN_TTS=`, `CITIZEN_DEVICE=cuda`, `CITIZEN_ALLOWED_CHAT_IDS=`, `OLLAMA_MODEL=llama3.2:3b`, `OLLAMA_URL=http://127.0.0.1:11434`), README section (setup, commands, what a citizen can ask, limits, "demo data, fictional"), docs/citizen.md, docs/decisions.md (Round 6: choices, model, limits; limitations for the paper: fictional schedule, synthetic speech evaluation, no CV, small local LLM, local open speech models instead of Bhashini, Hindi/English only).

C8. Close out. `scripts/check_round6.py`, all earlier check scripts (including `check_round5.py`, `check_telegram.py`, `check_round2.py --quick`), `pytest -q`, `npm run build`, `npm run test`, the Playwright tests. Restore the three Round 1 access logs if they show as modified (see PLAN_ROUND5.md). Update PROGRESS.md (including what the user must do for the live test), CLAUDE.md round history (Round 6 Part A done). Commit `round 6a: citizen interface (hindi/english voice, schedule answers, pipe tickets)`. Do NOT stop: continue with Part C, then Part B. The live end-to-end test (the user sends a Hindi voice note and a photo from the phone) is done with the user and the planning assistant after this round.

## Part C: project documents (no code changes; everything from real artefacts)
E1. Teacher-feedback scope table `docs/teacher_scope.md`: go through `docs/reference/faculty/Faculty_feedback.txt` item by item. For each item: what the teacher asked, what KAMI built (file/round), what changed and why (for example WhatsApp -> Telegram in Round 4 because the Twilio trial only sends templates; Bhashini -> local open models in Round 6 because registration needs organisation details; no physical hardware, virtual sensor node instead; no image recognition), and what is not done (with the reason). Neutral, factual, no claims beyond the evidence.
E2. Presentation demo script `docs/demo_script.md`: a 5-7 minute live demo with exact commands and clicks: start the demo, show the quiet network (Round 5 Q1: no alerts without injection), inject a burst, show the dashboard alert and the Telegram alert (real send only when the user runs it live), ask the citizen bot a Hindi voice question about a ward tanker, send a pipe photo with location and show the ticket. Include a fallback plan if Wi-Fi/Telegram fails (dry-run log and dashboard only), and the honest one-line caveats (simulated infrastructure data, fictional schedule).
E3. Real labelled data search (report only, at most about 30 minutes of searching): look again for public labelled real-world leak/burst or water-quality incident datasets with sensor time series (including the Babela et al. 2026 dataset noted in PROGRESS.md). Write `docs/real_data_search.md` with each candidate (link, licence, what it contains, why it fits or not). Do NOT download or integrate anything in this round; add the best candidate to Needs user.
Commit `round 6c: teacher scope table, demo script, real-data search`.

## Part B: Docker stack (formerly Round 7)
Needs Docker Desktop installed and running (the user installs it; never install or uninstall Docker). Before D1 stop Ollama models and free GPU memory if RAM is tight (16 GB laptop). No real Telegram message in Part B; tests use the forced dry run.

D1. Docker check (Docker Desktop 29.8.2 with Compose v5.5.1 was installed and verified by the user on 2026-10-12 and is left running). Run `docker info`. If Docker is not running, log it in PROGRESS.md, skip D2 to D4, and go straight to D5 (Part B stays pending; Part A is already committed). Record Docker and compose versions in docs/decisions.md.

D2. Real stack. `docker compose up -d` (Mosquitto and TimescaleDB). Run the MQTT and TimescaleDB tests that were skipped in fallback mode; fix real bugs they expose (small edits, tests first). Run `scripts/check_step_1.py` and `python scripts/run_demo.py --check` with `KAMI_MODE=docker`.

D3. Separate processes. Make it possible to run the virtual nodes, the ingest worker and the API as separate processes talking through MQTT and TimescaleDB (the architecture in the teacher's notes). Add `python scripts/run_demo.py --mode docker` for it, keep the fallback mode unchanged, and document both in README (ports, start and stop, `docker compose down`). Leave containers stopped at the end of the round.

D4. Browser tests on the Docker stack. Run the Round 5 and Round 6 Playwright tests once against the docker-mode demo (D3) as well as the fallback mode. Do not regenerate the paper screenshots unless the user asks.

D5. Close out (whole round). `scripts/check_round6.py` (extended with the Part B criteria below), all earlier check scripts (`check_round5.py`, `check_telegram.py`, `check_round2.py --quick`, every `check_step_N.py`), `pytest -q` (with Docker up, the MQTT/TimescaleDB tests must run, not skip), `npm run build`, `npm run test`, the Playwright tests. Restore the three Round 1 access logs if needed. Update README (fallback and docker modes, ports, start/stop, `docker compose down`, citizen bot), PROGRESS.md, CLAUDE.md round history (Round 6 done; next: live phone test with the user, then the paper), docs/decisions.md, and the limitations in `results/SUMMARY.md` via `scripts/make_summary.py` (Docker path now exercised, if D2 passed). Leave containers stopped. Commit `round 6b: docker stack (mqtt + timescaledb, separate processes)` (or, if Docker was not running, commit the docs with Part B marked pending). STOP.

## check_round6.py exits 0 only if
- the citizen tests pass with no network access (Telegram and Ollama mocked; speech/translation/TTS replaced by small fakes so tests need no GPU or model download; a test proves a real request would fail)
- the allowlist, rate limit and off-by-default behaviour are tested; no tracked file contains a token, key, chat id or user audio/photo
- `data/citizen/` demo files exist and are labelled `demo_fictional`; uploads are git-ignored
- the grounding guard is tested with planted wrong times/wards (it must replace them)
- `results/citizen/eval.md` and its JSON exist and were produced by code in this round (Ollama parts may be marked pending with a logged reason; the local speech evaluation must run)
- `GET /complaints` works and the dashboard ticket test passes
- all earlier checks still pass and no file under results/fusion/ or results/round2/ changed in this round
- (Part B, only if Docker ran) `docker info` works; the MQTT/TimescaleDB tests passed, not skipped; `check_step_1.py` and `run_demo.py --check` pass with `KAMI_MODE=docker`; the separate-process docker demo starts, ingests from all 8 nodes and stops cleanly; the Playwright tests pass in docker mode; fallback mode is unchanged
- (Part C) `docs/teacher_scope.md`, `docs/demo_script.md` and `docs/real_data_search.md` exist; every item of `docs/reference/faculty/Faculty_feedback.txt` appears in the scope table
