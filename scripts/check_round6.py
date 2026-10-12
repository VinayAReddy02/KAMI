"""Exit 0 only if the Round 6 criteria hold (PLAN_ROUND6.md), reading real artefacts.

    python scripts/check_round6.py            # everything, including scripts/check_round5.py (slow: all earlier checks)
    python scripts/check_round6.py --quick    # Round 6 checks only
    python scripts/check_round6.py --part a   # only Part A (citizen interface), c (documents) or b (Docker); default: all that apply

Nothing here can reach Telegram or Ollama or load a speech model: this process is locked to dry run
(kami.notify.lock, which also refuses every HTTP request that leaves the machine), child processes get an environment
without the bot settings and with a settings file that does not exist, and the citizen tests use mocked HTTP and fakes.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ok = True
ROUND_BASE = "ae67102"  # last commit before Round 6
ROUND_START = "2026-10-12"
SETTING_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "KAMI_TELEGRAM_ENABLE", "KAMI_CITIZEN_ENABLE", "CITIZEN_ALLOWED_CHAT_IDS",
                 "CITIZEN_ASR", "CITIZEN_TTS", "CITIZEN_DEVICE", "OLLAMA_MODEL", "OLLAMA_URL")
TOKEN_RX = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}")
BINARY = {".parquet", ".png", ".npz", ".joblib", ".pdf", ".docx", ".ico", ".jpg", ".jpeg", ".sqlite", ".ogg", ".oga", ".wav", ".onnx"}
MEDIA = {".ogg", ".oga", ".opus", ".wav", ".mp3", ".m4a", ".jpg", ".jpeg", ".png", ".webp", ".heic"}
MEDIA_OK = ("results/", "results_round1/", "frontend/", "docs/")  # screenshots, figures and app icons; never citizen uploads
REQUIRED_TESTS = {
    "a real request is refused": "test_a_real_request_is_refused_and_would_fail_the_test",
    "allowlist": "test_allowlist_other_chats_get_one_fixed_reply_and_are_not_processed",
    "rate limit": "test_rate_limit_per_chat",
    "off by default": "test_off_by_default_nothing_polls_without_the_enable_setting",
    "guard, planted wrong time": "test_guard_replaces_an_answer_with_a_planted_wrong_time",
    "guard, planted wrong ward": "test_guard_replaces_an_answer_with_a_planted_wrong_ward",
    "guard, cause word": "test_guard_replaces_an_answer_that_names_a_cause",
    "no information": "test_unanswerable_questions_get_the_no_information_reply",
    "live status": "test_open_high_alert_marks_the_ward_tankers_as_possibly_delayed",
    "token never logged": "test_token_and_chat_ids_never_appear_in_logs_or_replies",
}


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a, code=False):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.returncode if code else r.stdout.rstrip("\n")


def load(rel):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def text_of(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
ap.add_argument("--part", choices=["a", "b", "c"], action="append")
args = ap.parse_args()
parts = set(args.part or ["a", "b", "c"])

# ---------------------------------------------------------------- the real secrets, read only to prove they are nowhere in git
from kami.notify.settings import read_env_file  # noqa: E402

real = read_env_file(ROOT / ".env")
secret_values = [v for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if (v := real.get(k, "").strip())]
secret_values += [v.strip() for v in real.get("CITIZEN_ALLOWED_CHAT_IDS", "").split(",") if len(v.strip()) >= 6]
del real

# ---------------------------------------------------------------- make sending and polling impossible, here and in every child
from kami.notify.lock import lock_to_dry_run, refused  # noqa: E402

lock_to_dry_run()
tmp = Path(tempfile.mkdtemp(prefix="kami_round6_check_"))
child_env = {k: v for k, v in os.environ.items() if k not in SETTING_NAMES}
child_env["KAMI_NOTIFY_DIR"] = str(tmp / "child_notifications")
child_env["KAMI_E2E_OUT"] = str(tmp / "e2e")
child_env["KAMI_CITIZEN_DIR"] = str(tmp / "citizen")
child_env.setdefault("KAMI_MODE", "fallback")  # Docker Desktop may be running without the stack: the Part A and C checks use the fallback mode
decisions = text_of("docs/decisions.md")
tracked = git("ls-files").splitlines()

if "a" in parts:
    # ------------------------------------------------------------ tests: no network, no GPU, no model download
    t = subprocess.run([sys.executable, "-m", "pytest", "tests/citizen", "-vv", "-p", "no:warnings", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    print("   ", t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
    check("A pytest tests/citizen passes (Telegram and Ollama mocked, speech/translation/TTS replaced by fakes)", t.returncode == 0)
    missing = [k for k, name in REQUIRED_TESTS.items() if not re.search(rf"{name}\S* PASSED", t.stdout)]
    check(f"A the required tests ran and passed: real request refused, allowlist, rate limit, off by default, guard with planted "
          f"wrong time/ward/cause, no information, live status, token redaction {missing or ''}", not missing)
    heavy = subprocess.run([sys.executable, "-c",
                            "import sys; import kami.citizen.bot, kami.citizen.answer, kami.citizen.tickets, kami.citizen.speech, "
                            "kami.citizen.translate, kami.citizen.tts, kami.api.app; "
                            "bad=[m for m in ('torch','transformers','faster_whisper','ctranslate2','piper','onnxruntime') if m in sys.modules]; "
                            "print(bad); sys.exit(1 if bad else 0)"], cwd=ROOT, capture_output=True, text=True, env=child_env)
    check(f"A importing the citizen modules and the API loads no speech or deep-learning package {heavy.stdout.strip()}", heavy.returncode == 0)

    try:  # optional speech packages: where they are installed, the voice-note conversion must work (no network, no GPU, no model)
        import numpy as np

        from kami.citizen.audio import RATE, AudioError, FfmpegAudio

        audio = FfmpegAudio()
        tone = (np.sin(np.arange(3 * 22050) * 0.06) * 12000).astype(np.int16)  # three seconds
        ogg = audio.pcm_to_ogg(tone, 22050)
        back = audio.ogg_to_pcm(ogg)
        try:
            audio.ogg_to_pcm(b"this is not audio")
            junk_refused = False
        except AudioError:
            junk_refused = True
        check("A OGG/Opus round trip through the bundled ffmpeg works (3 s tone -> voice note -> 16 kHz samples; non-audio is refused)",
              ogg[:4] == b"OggS" and 2000 < len(ogg) < 60000 and abs(len(back) / RATE - 3.0) < 0.15 and float(np.abs(back).max()) > 0.1 and junk_refused)
    except Exception as e:
        print(f"    INFO the optional speech packages are not installed here ({type(e).__name__}); the ffmpeg conversion was not checked")

    # ------------------------------------------------------------ secrets, uploads, demo data
    leaks, media = [], []
    for rel in tracked:
        p = ROOT / rel
        if not p.is_file():
            continue
        if p.suffix.lower() in MEDIA and not rel.startswith(MEDIA_OK):
            media.append(rel)
        if p.suffix.lower() in BINARY or p.stat().st_size > 8_000_000:
            continue
        body = p.read_text(encoding="utf-8", errors="ignore")
        if TOKEN_RX.search(body) or any(v in body for v in secret_values):
            leaks.append(rel)
    check(f"A no tracked file contains a bot token, the chat id or an allowed chat id ({len(secret_values)} real values searched, none shown) {leaks[:5] or ''}",
          not leaks)
    check(f"A no tracked audio or photo outside results/, frontend/ and docs/ (no citizen upload in git) {media[:5] or ''}",
          not media and not any(f.startswith("data/citizen/uploads/") for f in tracked))
    check("A .env and data/citizen/uploads/ are git-ignored", git("check-ignore", "-q", ".env", code=True) == 0
          and git("check-ignore", "-q", "data/citizen/uploads/x.jpg", code=True) == 0)
    demo = ["data/citizen/wards_demo_fictional.json", "data/citizen/tanker_schedule_demo_fictional.csv", "data/citizen/notices_demo_fictional.json"]
    wards = load(demo[0]) or {}
    notices = load(demo[2]) or {}
    nodes = {n["id"] for n in load("config/nodes.json")["nodes"]}
    check("A data/citizen/ demo files exist, are tracked and labelled demo_fictional (file names and a label inside)",
          all(f in tracked for f in demo) and wards.get("label") == "demo_fictional" and notices.get("label") == "demo_fictional"
          and "demo_fictional" in text_of(demo[1]).splitlines()[0])
    check("A 8 wards, Ward N <-> node-N, each with an English and a Hindi name; 10 to 20 notices; schedule rows for every ward",
          [w["node_id"] for w in wards.get("wards", [])] == [f"node-{i}" for i in range(1, 9)] and {w["node_id"] for w in wards["wards"]} == nodes
          and all(w.get("name_en") and re.search(r"[ऀ-ॿ]", w.get("name_hi", "")) for w in wards["wards"])
          and 10 <= len(notices.get("notices", [])) <= 20
          and {ln.split(",")[1] for ln in text_of(demo[1]).splitlines()[2:] if ln.strip()} == {str(i) for i in range(1, 9)})
    b = subprocess.run([sys.executable, "scripts/build_citizen_data.py", "--check"], cwd=ROOT, capture_output=True, text=True, env=child_env)
    check("A the schedule file is reproduced exactly by the seeded script (scripts/build_citizen_data.py --check)", b.returncode == 0)

    # ------------------------------------------------------------ evaluation artefacts
    ev = load("results/citizen/eval.json") or {}
    qs = [json.loads(ln) for ln in text_of("data/citizen/eval_questions.jsonl").splitlines() if ln.strip()]
    check("A question set: at least 60 authored questions, 30 English and 30 Hindi or more, 20 validation / 40 test or more, with unanswerable ones",
          len(qs) >= 60 and sum(q["lang"] == "en" for q in qs) >= 30 and sum(q["lang"] == "hi" for q in qs) >= 30
          and sum(q["split"] == "val" for q in qs) >= 20 and sum(q["split"] == "test" for q in qs) >= 40
          and sum(q["intent"] == "none" for q in qs) >= 6 and {q["expect"].get("ward") for q in qs if q["intent"] == "schedule"} >= set(range(1, 9)))
    check("A results/citizen/eval.json and eval.md exist and were produced by scripts/citizen_eval.py in this round",
          ev.get("made_by") == "scripts/citizen_eval.py" and ev.get("run_utc", "")[:10] >= ROUND_START and (ROOT / "results/citizen/eval.md").is_file()
          and git("merge-base", "--is-ancestor", ROUND_BASE, ev.get("git_commit", "none"), code=True) == 0)
    tw = ev.get("text", {}).get("writers", {})
    check("A text evaluation: the template writer was scored on the test split per language (slots, correctness, no-information, latency)",
          all(k in tw.get("template", {}).get(lang, {}) for lang in ("en", "hi")
              for k in ("n", "slot_accuracy", "answer_correct", "no_information_correct", "latency_ms_median", "latency_ms_p90")))
    ol = tw.get("ollama", {})
    check("A text evaluation: the Ollama writer was scored (grounding violations before the guard, guard fallbacks), or is marked pending with a reason",
          (all(k in ol.get(lang, {}) for lang in ("en", "hi") for k in ("grounding_violations_before_guard", "guard_fallbacks", "answer_correct"))
           or (ol.get("status") == "pending" and len(ol.get("reason", "")) > 10)))
    vp = ev.get("voice", {})
    check("A voice evaluation ran on the local models with synthetic speech: word error rate, end-to-end correctness and per-stage latency, per language",
          vp.get("speech") == "synthetic" and all(k in vp.get(lang, {}) for lang in ("en", "hi") for k in ("n", "wer", "end_to_end_correct", "latency_ms"))
          and vp.get("device") in ("cuda", "cpu"))
    md = text_of("results/citizen/eval.md")
    check("A eval.md states that the questions are authored, the speech is synthetic and the schedule is fictional",
          "authored" in md and "synthetic speech" in md and "fictional" in md)
    sel = load("results/citizen/model_selection.json") or {}
    check("A the model choices (ASR, translation, TTS, LLM) were made on the validation questions and are recorded with the gated models that were not used",
          all(k in sel.get("chosen", {}) for k in ("asr", "nmt", "tts", "llm")) and sel.get("split") == "val" and len(sel.get("not_used", [])) >= 1
          and "gated" in json.dumps(sel).lower())

    # ------------------------------------------------------------ API and dashboard
    from fastapi.testclient import TestClient  # noqa: E402

    from kami.api.app import create_app  # noqa: E402
    from kami.ingest.bus import InProcessBus  # noqa: E402
    from kami.live.system import build_live  # noqa: E402
    from kami.runtime import Stack  # noqa: E402
    from kami.store import SqliteStore  # noqa: E402

    os.environ["KAMI_CITIZEN_DIR"] = str(tmp / "citizen_api")
    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    app = create_app(stack)
    build_live(stack, speed=0)
    with TestClient(app) as c:
        r0 = c.get("/complaints")
        st = c.get("/citizen/status")
    check("A GET /complaints works (empty list on a fresh store) and GET /citizen/status says the citizen bot is off by default",
          r0.status_code == 200 and r0.json() == [] and st.status_code == 200 and st.json().get("enabled") is False
          and not any(v in st.text for v in secret_values))
    stack.extras["notifications"].stop()
    npm, npx = shutil.which("npm"), shutil.which("npx")
    fe = ROOT / "frontend"
    built = subprocess.run([npm, "run", "build"], cwd=fe, capture_output=True, env=child_env).returncode == 0
    pw = subprocess.run([npx, "playwright", "test", "complaints"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    print("    playwright:", ([ln for ln in pw.stdout.splitlines() if ln.strip()][-1:] or [pw.stderr[-200:]])[0].strip())
    check("A the dashboard ticket test passes in the browser (ticket marker on the map, Complaints list with thumbnail, time, nearest node, status)",
          built and pw.returncode == 0 and len(re.findall(r"^\s+ok\s+\d+ .*complaints\.spec\.ts", pw.stdout, flags=re.M)) >= 2)
    check("A docs/citizen.md, the README section and docs/decisions.md (Round 6) describe the citizen interface and its limits",
          "Models chosen and measured" in text_of("docs/citizen.md") and "citizen" in text_of("README.md").lower()
          and "## Round 6" in decisions and "Bhashini" in decisions and "gated" in decisions)
    env_example = text_of(".env.example")
    check(".env.example has the citizen placeholders with the bot off and no value that is a secret",
          all(f"{k}=" in env_example for k in ("KAMI_CITIZEN_ENABLE", "CITIZEN_ASR", "CITIZEN_TTS", "CITIZEN_DEVICE", "CITIZEN_ALLOWED_CHAT_IDS", "OLLAMA_MODEL", "OLLAMA_URL"))
          and "KAMI_CITIZEN_ENABLE=0" in env_example and "TELEGRAM_BOT_TOKEN=\n" in env_example)

if "c" in parts:
    scope = text_of("docs/teacher_scope.md")
    items = load("docs/teacher_scope_items.json") or []
    feedback = text_of("docs/reference/faculty/Faculty_feedback.txt")
    check("C docs/teacher_scope.md, docs/demo_script.md and docs/real_data_search.md exist",
          all((ROOT / f).is_file() for f in ("docs/teacher_scope.md", "docs/demo_script.md", "docs/real_data_search.md")))
    lost = [it["id"] for it in items if it["quote"] not in feedback or f"| {it['id']} |" not in scope]
    lines = [ln.strip() for ln in feedback.splitlines() if len(ln.strip()) > 25]
    uncovered = [ln[:60] for ln in lines if not any(ln in it["source_text"] for it in items)]
    check(f"C every item of the faculty feedback appears in the scope table (items quote the feedback text; rows exist) {lost[:3] or ''}",
          len(items) >= 5 and not lost)
    check(f"C every substantive line of the faculty feedback belongs to an item of the scope table {uncovered[:3] or ''}", bool(lines) and not uncovered)

if "b" in parts:
    d = load("results/docker/part_b.json")
    if d is None or d.get("docker_ran") is False:
        check("B Docker part: not run; PROGRESS.md records it as pending with the reason",
              "Part B" in text_of("PROGRESS.md") and re.search(r"Part B[^\n]*(pending|not run)", text_of("PROGRESS.md")) is not None)
    else:
        check("B results/docker/part_b.json was produced by scripts/docker_checks.py in this round",
              d.get("made_by") == "scripts/docker_checks.py" and d.get("run_utc", "")[:10] >= ROUND_START)
        for key, label in (("docker_info", "docker info works"), ("mqtt_timescale_tests", "the MQTT and TimescaleDB tests passed, none skipped"),
                           ("pytest_all_with_stack_up", "pytest -q passes with the stack up, no test skipped"),
                           ("check_step_1_docker", "check_step_1.py passes with KAMI_MODE=docker"),
                           ("run_demo_check_docker", "run_demo.py --check passes with KAMI_MODE=docker"),
                           ("separate_processes", "the separate-process docker demo starts, ingests from all 8 nodes and stops cleanly"),
                           ("playwright_docker", "the Playwright tests pass in docker mode"),
                           ("fallback_unchanged", "fallback mode still passes its checks"),
                           ("containers_stopped", "the containers are stopped at the end")):
            check(f"B {label}", d.get(key, {}).get("ok") is True)

IN_A, IN_B = "citizen=" + '"auto"', "allow_inbound=" + "True"  # in pieces so that this file does not match itself
inbound = sorted(p.name for p in (ROOT / "scripts").glob("*.py") if IN_A in p.read_text(encoding="utf-8") or IN_B in p.read_text(encoding="utf-8"))
check(f"only scripts/run_demo.py and scripts/run_citizen_bot.py can start inbound handling {inbound}", inbound == ["run_citizen_bot.py", "run_demo.py"])
check(f"no request left this machine during this check {sorted(set(refused)) or ''}", not refused)
if not args.quick:
    r = subprocess.run([sys.executable, "scripts/check_round5.py"], cwd=ROOT, capture_output=True, text=True, env=child_env)
    for ln in r.stdout.splitlines():
        if ln.strip().startswith("FAIL"):
            print("     ", ln.strip())
    check("scripts/check_round5.py still passes (Round 5, check_telegram, check_round2, every check_step_N.py, pytest -q, npm build and test, Playwright)",
          r.returncode == 0)

R1_LOG = "results/fusion/test_eval_log.json"  # Round 1 access log of the exposed test_v1; check_step_5.py rewrites its time stamps


def without_time(o):
    if isinstance(o, dict):
        return {k: without_time(v) for k, v in o.items() if k != "utc"}
    return [without_time(x) for x in o] if isinstance(o, list) else o


FINAL = ("results/fusion", "results/round2")
changed = set(git("diff", "--name-only", ROUND_BASE, "--", *FINAL).split()) | {ln[3:] for ln in git("status", "--porcelain", "--", *FINAL).splitlines()}
log_same = True
if R1_LOG in changed:
    log_same = without_time(json.loads(git("show", f"{ROUND_BASE}:{R1_LOG}"))) == without_time(json.loads((ROOT / R1_LOG).read_text(encoding="utf-8")))
    print("    INFO the Round 1 access log has new time stamps from the Round 1 checks; its content is " + ("unchanged" if log_same else "DIFFERENT"))
check(f"no file under results/fusion/ or results/round2/ changed in this round (git, against {ROUND_BASE}) {sorted(changed - {R1_LOG}) or ''}",
      not (changed - {R1_LOG}) and log_same)
sys.exit(0 if ok else 1)
