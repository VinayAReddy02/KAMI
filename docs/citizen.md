# Citizen interface on the Telegram bot (Round 6)

A citizen can talk to the same bot that sends the alerts (t.me/KAMI67_BOT): ask when the water tanker comes to a ward,
ask a general question from the notices, or report a damaged pipe with a photo and a location. Questions can be typed
or spoken, in Hindi or English. Everything runs on the user's laptop: speech recognition, translation, the language
model and speech output are local models. No cloud service is called except Telegram itself.

**This is a demo.** The wards, the tanker schedule, the notices and the helpline number are fictional
(`demo_fictional` in every file name). Replies carry a short demo marker. The system does not look at what is in a
photo: there is no image recognition, and no reply names a cause.

**Off by default.** Inbound handling runs only with `KAMI_CITIZEN_ENABLE=1`, and only from `scripts/run_demo.py`
(normal start) and `scripts/run_citizen_bot.py`. Tests and check scripts never poll Telegram, never call Ollama and
never load the speech models.

## How a message flows

```
Telegram  --getUpdates (long polling, offset)-->  telegram_in.Poller  (background thread)
                                                      |
                                                  bot.CitizenBot     allowlist -> rate limit -> commands -> route
                                                      |
        +---------------------+-----------------------+----------------------------+
        | text                | voice note            | photo / photo file         | location
        |                     | getFile + download    | getFile + download         |
        |                     | OGG -> WAV 16 kHz     | size and type check        |
        |                     | speech.ASR (+ hint    |                            |
        |                     |   words: ward names)  |                            |
        v                     v                       v                            v
   language of the message (Devanagari / Hindi words / ASR language / the chat's /language setting)
        |                                             tickets.TicketService: location from the message or from the
        v                                             photo file's EXIF; otherwise ask and keep the photo 10 minutes;
   answer.understand()  rules: intent, ward, day      nearest node (haversine), store, reply with ticket number and
        |               (works on Hindi and English)  the node's current KAMI status in plain words
        v
   retrieval: schedule lookup (CSV + replay clock + live alerts)  or  notices (Hindi keywords of each notice first;
        |                                                             else TF-IDF on the English text, a Hindi question
        |                                                             being translated first: translate.Translator)
        v
   writer: TemplateWriter (fixed sentences, Hindi and English)  or  OllamaWriter (local LLM, English only)
        |
        v
   grounding guard: every time, date, ward, tanker id and number in an LLM answer must be in the retrieved records,
        |           and no cause word may appear; otherwise the template answer is used ("guard fallback")
        v
   Hindi reply: LLM answers and notices are translated en -> hi; the numbers must survive the translation,
        |       otherwise the Hindi template is used
        v
   sendMessage (text, with the demo marker)   and, for a voice question, tts.TTS -> WAV -> OGG/Opus -> sendVoice
```

The citizen module only reads the live KAMI state (`LiveProcessor.latest`, `list_alerts`). It does not change the
anomaly models, the fusion rule or any frozen result.

## Modules (`src/kami/citizen/`)

| File | Role |
|---|---|
| `settings.py` | reads the settings below from `.env` or the environment; values are never printed |
| `data.py` | loads wards, schedule and notices; `ScheduleService` resolves the schedule against the replay clock and the live alerts |
| `telegram_in.py` | Bot API client (getUpdates, getFile, file download, sendMessage, sendVoice) and the polling thread |
| `bot.py` | allowlist, rate limit, commands, language choice, routing, replies |
| `speech.py`, `translate.py`, `tts.py` | one interface per stage (ASR, NMT, TTS) with the local implementations and small fakes for tests |
| `audio.py` | OGG/Opus <-> WAV 16 kHz mono through the ffmpeg binary bundled with `imageio-ffmpeg` |
| `answer.py` | understanding (intent and slots), retrieval, the two writers, the grounding guard |
| `tickets.py` | pipe-damage tickets: EXIF location, pending photos, nearest node, storage |

## Settings (`.env`, see `.env.example`)

| Setting | Meaning |
|---|---|
| `KAMI_CITIZEN_ENABLE` | `1` to answer citizens; anything else: inbound handling is off |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | as for the alert push; the chat id is always allowed |
| `CITIZEN_ALLOWED_CHAT_IDS` | optional, comma-separated numeric chat ids that may also use the bot |
| `CITIZEN_ASR`, `CITIZEN_TTS` | choice of the speech models (empty = the defaults chosen in this round) |
| `CITIZEN_DEVICE` | `cuda` or `cpu` (falls back to `cpu` if no GPU is usable) |
| `OLLAMA_MODEL`, `OLLAMA_URL` | local LLM for the answer writer; if Ollama is not reachable the template writer is used |

## Safety rules built in

- **Allowlist.** Only the chats listed above are answered. Any other chat gets one fixed line ("demo bot, not public"),
  at most once per hour, and its message is not processed, downloaded or stored.
- **Rate limit.** 10 requests per minute per chat; one notice when the limit is hit.
- **Polling, not a webhook.** One background thread long-polls `getUpdates` with an offset. Messages that were waiting
  before the bot started are skipped, not answered late. Handling runs in its own thread: it cannot block or crash the
  sensor loop.
- **Grounding guard** on every LLM answer: nothing that is not in the retrieved records (times, dates, wards, tanker ids, numbers, day and status words, no cause word, no new negation), and nothing essential missing (the ward, every tanker id and time, delivered or delayed, the possible-delay note; for a notice the times or numbers of a full sentence). And a numbers check after every translation into Hindi.
- **No information.** If nothing relevant is found the bot says so, in the citizen's language. It never guesses a time.
- **Privacy.** Voice notes are deleted after the answer; photos are kept only under `data/citizen/uploads/`
  (git-ignored). Limits: voice 60 s, photo 10 MB, JPEG or PNG only. Logs contain no chat id, name, message text,
  audio or coordinates. A ticket stores the reported location, the photo and the time, and no chat id or name.
- **Token.** The Bot API puts the token in every URL, including file downloads. No URL, exception text or Telegram
  error text is logged; only fixed sentences, the HTTP status and the numeric error code.
- **No cause claims.** Replies say what the sensors currently show ("an Infrastructure alert, priority High"), never
  why, and never that the photo was analysed.

## Demo data (`data/citizen/`, all fictional)

| File | Content |
|---|---|
| `wards_demo_fictional.json` | 8 wards, Ward N <-> node-N of `config/nodes.json`, English and Hindi names |
| `tanker_schedule_demo_fictional.csv` | tanker id, ward, day offset from the replay day, slot, planned status; built by `scripts/build_citizen_data.py` (seeded) |
| `notices_demo_fictional.json` | short English notices and FAQ entries (timings, how to report a pipe, alert levels, a fictional helpline) |
| `eval_questions.jsonl` | authored test questions (30 English, 30 Hindi), validation and test split |
| `uploads/` | citizen photos (git-ignored, never committed) |

**Schedule status.** A row says on which day (relative to the replay clock) and in which slot a tanker is planned.
The status a citizen hears is derived from the replay time: `scheduled`, `en route` (from one hour before the slot),
`delivered` (after the slot), `delayed` (rows planned as delayed, with the new expected time). If the ward's sensor
node has an open alert of priority High or Critical, a tanker that has not delivered yet is reported as
"possibly delayed: active network alert in your area". No cause is stated.

## Models chosen and measured

All models run on the laptop (NVIDIA GeForce RTX 4070 Laptop GPU, 8188 MiB; device `cuda`, CPU fallback). The choices were made on the 20
validation questions only (`results/citizen/model_selection.md`); the test questions were then run once
(`results/citizen/eval.md`).

| Stage | Chosen | Why (validation) |
|---|---|---|
| Speech recognition | `faster-whisper:large-v3-turbo` | mean WER over the TTS candidates 0.193 (all: large-v3-turbo 0.193, medium 0.244) |
| Translation hi <-> en | `nllb-200-distilled-600M` | numbers kept in English -> Hindi: nllb-200-distilled-600M 10/10, opus-mt (hi-en, en-hi) 7/10; chrF against the fixed Hindi sentences: nllb-200-distilled-600M 0.572, opus-mt (hi-en, en-hi) 0.376 |
| Speech output | `piper (hi: priyamvada, en: lessac)` | WER through large-v3-turbo 0.152 (all: piper (hi: pratham, en: lessac) 0.175, piper (hi: priyamvada, en: lessac) 0.152, mms-tts (hin, eng) 0.253) |
| Answer writer (LLM) | `llama3.2:3b` through Ollama | llama3.2:3b: 7 guard fallbacks, 2586 MB; qwen2.5:7b: 6 fallbacks, 4682 MB; the larger model is kept only with at least 3 fewer fallbacks and at most 5200 MB |

**Not used: the AI4Bharat models named in the plan.** `ai4bharat/indic-conformer-600m-multilingual` (speech
recognition), `ai4bharat/indictrans2-*-dist-200M` (translation) and `ai4bharat/indic-parler-tts` (speech output) are
gated on Hugging Face: downloading them needs an account, a login and a licence click. This project creates no
accounts, so they were not downloaded, and the comparison was made among open models that download without a login.
They are listed under *Needs user* in `PROGRESS.md`: with a Hugging Face login of the user they could be compared
later. Bhashini was dropped earlier for a similar reason (its registration asks for organisation details).

Licences of the models in use: Whisper large-v3-turbo (MIT), NLLB-200 distilled 600M (CC-BY-NC 4.0: non-commercial
use, which fits a college project and would have to be replaced for a commercial service), Piper voices (MIT),
llama3.2 (Llama 3.2 Community Licence). The models are stored outside the repository, in the Hugging Face cache
(`%USERPROFILE%\.cache\huggingface`) and in Ollama's model folder.

### Validation comparison (synthetic speech, 10 Hindi and 10 English questions)

| Speech recognition | Speech output that spoke the questions | WER Hindi | WER English | Recognition median ms |
|---|---|---|---|---|
| large-v3-turbo | piper (hi: pratham, en: lessac) | 30.8% | 4.2% | 416 |
| large-v3-turbo | piper (hi: priyamvada, en: lessac) | 26.2% | 4.2% | 410 |
| large-v3-turbo | mms-tts (hin, eng) | 32.3% | 18.3% | 414 |
| medium | piper (hi: pratham, en: lessac) | 44.6% | 5.6% | 406 |
| medium | piper (hi: priyamvada, en: lessac) | 32.3% | 5.6% | 418 |
| medium | mms-tts (hin, eng) | 40.0% | 18.3% | 411 |

| Translation | Hindi notice question finds its notice | Numbers kept, English -> Hindi | chrF hi -> en | GPU memory MB |
|---|---|---|---|---|
| nllb-200-distilled-600M | 0/2 | 10/10 | 0.553 | 1182 |
| opus-mt (hi-en, en-hi) | 1/2 | 7/10 | 0.525 | 592 |

| LLM (Ollama) | Answers accepted by the guard | Replaced by the guard | Median ms | GPU memory MB |
|---|---|---|---|---|
| llama3.2:3b | 9 of 16 | 7 | 425.4 | 2586 |
| qwen2.5:7b | 10 of 16 | 6 | 856.8 | 4682 |

### Memory and loading

- Speech recognition `faster-whisper:large-v3-turbo`: about 1568 MB of GPU memory, loads in about 2.5 s from the local cache.
- Translation `nllb-200-distilled-600M`: about 1182 MB of GPU memory. Speech output runs on the CPU.
- LLM `llama3.2:3b`: about 2586 MB of GPU memory, kept loaded by Ollama for 30 minutes after a question.
- With everything loaded during the voice evaluation, 6978 MB of the GPU's 8188 MB were in use
  (this includes what the desktop itself uses). All models stay loaded together; nothing is unloaded between questions.
- The speech models are loaded once in a background thread at start-up (warm-up). Until that has finished the bot answers
  typed questions and tells a citizen who sends a voice note to type instead.
- The very first download of the models needs the internet (about 4 GB for speech and translation, 2 GB for the LLM).

### Test results in short (40 authored questions, run once; details in `results/citizen/eval.md`)

| | English | Hindi |
|---|---|---|
| Fixed sentences: answer correct | 100% | 95% |
| Local LLM after the guard: answer correct | 100% | 95% |
| LLM answers that broke a grounding rule and were replaced | 12 of 17 | 11 of 19 |
| Voice (synthetic speech): word error rate | 1.4% | 23.5% |
| Voice: correct from spoken question to spoken answer | 95% | 70% |
| Voice: median time from question to voice answer | 1.0 s | 1.3 s |

## Limits

- Fictional schedule, wards and notices; a real deployment would read the utility's own systems.
- Hindi and English only.
- The speech evaluation uses synthetic speech (questions spoken by the text-to-speech model). Real voice notes are a
  later step.
- A small local language model; its answers are checked against the retrieved records and replaced when they do not
  match.
- Photos are stored and linked to the nearest sensor node. Nothing recognises what a photo shows.
- One laptop, one polling thread: not built for many users at once.
