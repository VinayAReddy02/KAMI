"""Evaluation of the citizen interface (Round 6, C6). Separate from the frozen anomaly evaluation.

    python scripts/citizen_eval.py                      # test questions: text (template and Ollama writer) and voice
    python scripts/citizen_eval.py --split val          # the validation questions (for tuning; never written to eval.json)
    python scripts/citizen_eval.py --parts text         # only the text part (or: voice)

What it measures, on authored questions about a fictional schedule:
  text   per writer (fixed sentences / local LLM) and per language: were intent, ward and day understood, is the
         answer correct, is "no information" said exactly when it should be, how often the LLM answer broke the grounding
         rules before the guard, how often the guard replaced it, and the latency of each stage.
  voice  every question is spoken by the chosen text-to-speech model (synthetic speech, not a person), recognised by the
         chosen speech model, answered, and the answer is spoken: word error rate, end-to-end correctness and the
         latency of each stage on this machine.

Each part runs ONCE on the test questions: the raw outputs are stored in results/citizen/test_outputs.json and a later
run only recomputes the tables from them (results/citizen/test_access_log.json says when each part ran).
Models: the choices recorded in results/citizen/model_selection.json. Makes no Telegram request.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "results" / "citizen"
STAGES = ("understand", "translate_in", "retrieve", "llm", "translate_out", "total")
VOICE_STAGES = ("asr", "answer", "tts", "ogg", "end_to_end")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def vram_mb():
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.split()[0])
    except Exception:
        return None


def chosen_models() -> dict:
    from kami.citizen.service import DEFAULT_ASR, DEFAULT_NMT, DEFAULT_TTS
    from kami.citizen.settings import DEFAULT_OLLAMA_MODEL

    p = OUT / "model_selection.json"
    c = json.loads(p.read_text(encoding="utf-8")).get("chosen", {}) if p.is_file() else {}
    return {"asr": c.get("asr", DEFAULT_ASR), "nmt": c.get("nmt", DEFAULT_NMT), "tts": c.get("tts", DEFAULT_TTS), "llm": c.get("llm", DEFAULT_OLLAMA_MODEL)}


def build(models: dict, device: str, need_speech: bool, no_hints: bool = False):
    from kami.citizen.audio import FfmpegAudio
    from kami.citizen.speech import FasterWhisperASR
    from kami.citizen.translate import MarianTranslator, NllbTranslator
    from kami.citizen.tts import MmsTTS, PiperTTS

    tr = MarianTranslator(device) if "opus" in models["nmt"] else NllbTranslator(device=device)
    tr.load()
    if not need_speech:
        return tr, None, None, None
    from kami.citizen.data import speech_vocabulary

    asr = FasterWhisperASR(models["asr"].split(":", 1)[-1], device, hotwords=None if no_hints else speech_vocabulary())
    asr.load()
    if models["tts"].startswith("mms"):
        tts = MmsTTS(device=device)
    else:
        tts = PiperTTS({"hi": "hi_IN-priyamvada-medium" if "priyamvada" in models["tts"] else "hi_IN-pratham-medium", "en": "en_US-lessac-medium"})
    tts.load()
    return tr, asr, tts, FfmpegAudio()


def reply_row(q: dict, r, j: dict) -> dict:
    return {"id": q["id"], "lang": q["lang"], "intent": q["intent"], "question": q["text"], "answer_en": r.text_en, "answer": r.text, "kind": r.kind,
            "ward": r.ward, "day": r.day, "writer": r.writer, "asked_llm": "llm" in r.ms, "guard_violations": r.guard_violations, "guard_fallback": r.guard_fallback,
            "llm_unavailable": r.llm_unavailable, "translation_fallback": r.translation_fallback, "no_info": r.no_info, "ms": r.ms, **j}


def run_text(questions: list[dict], translator, llm) -> list[dict]:
    from kami.citizen.answer import Answerer
    from kami.citizen.evaluate import eval_world, judge, truth

    sch, ns = eval_world()
    a = Answerer(sch, translator=translator, llm=llm, node_state=ns)
    a.answer("When will the water tanker reach Ward 4?")  # warm-up: models loaded before any timing
    a.answer("वार्ड 4 में टैंकर कब आएगा?")
    return [reply_row(q, r, judge(q, r, truth(q, sch, ns))) for q in questions for r in [a.answer(q["text"])]]


def run_voice(questions: list[dict], translator, llm, asr, tts, audio) -> list[dict]:
    from kami.citizen.answer import Answerer
    from kami.citizen.audio import resample
    from kami.citizen.evaluate import eval_world, judge, truth, words

    sch, ns = eval_world()
    a = Answerer(sch, translator=translator, llm=llm, node_state=ns)
    rows = []
    for i, q in enumerate([questions[0], *questions]):  # the first question once more in front, as a warm-up that is not counted
        spoken = q.get("speech_text", q["text"])
        pcm, rate = tts.synthesize(spoken, q["lang"])
        clip = resample(pcm, rate)
        t0 = time.perf_counter()
        heard = asr.transcribe(clip, None)
        t1 = time.perf_counter()
        r = a.answer(heard.text, heard.language) if heard.text.strip() else None
        t2 = time.perf_counter()
        if r is None:
            continue
        out_pcm, out_rate = tts.synthesize(r.text, r.lang)
        t3 = time.perf_counter()
        ogg = audio.pcm_to_ogg(out_pcm, out_rate)
        t4 = time.perf_counter()
        if i == 0:
            continue
        row = reply_row(q, r, judge(q, r, truth(q, sch, ns)))
        row.update({"spoken": spoken, "heard": heard.text, "heard_language": heard.language, "question_audio_s": round(len(clip) / 16000, 2),
                    "answer_audio_s": round(len(out_pcm) / out_rate, 2), "answer_ogg_bytes": len(ogg),
                    "ref_words": words(spoken, q["lang"]), "hyp_words": words(heard.text, q["lang"]),
                    "ref_words_raw": words(spoken, q["lang"], normalise=False), "hyp_words_raw": words(heard.text, q["lang"], normalise=False),
                    "voice_ms": {"asr": round((t1 - t0) * 1000, 1), "answer": round((t2 - t1) * 1000, 1), "tts": round((t3 - t2) * 1000, 1),
                                 "ogg": round((t4 - t3) * 1000, 1), "end_to_end": round((t4 - t0) * 1000, 1)}})
        rows.append(row)
    return rows


def text_metrics(rows: list[dict], with_llm: bool) -> dict:
    from kami.citizen.evaluate import pct

    def one(rs):
        if not rs:
            return {"n": 0}
        m = {"n": len(rs), "slot_accuracy": round(sum(r["slot_ok"] for r in rs) / len(rs), 3), "answer_correct": round(sum(r["answer_ok"] for r in rs) / len(rs), 3),
             "final_text_correct": round(sum(r["final_ok"] for r in rs) / len(rs), 3), "no_information_correct": round(sum(r["no_info_ok"] for r in rs) / len(rs), 3),
             "unanswerable_n": sum(r["intent"] == "none" for r in rs), "unanswerable_said_no_information": sum(r["intent"] == "none" and r["no_info"] for r in rs),
             "translation_fallbacks": sum(r["translation_fallback"] for r in rs)}
        if with_llm:
            asked = [r for r in rs if r["asked_llm"]]
            m.update({"asked_llm": len(asked), "grounding_violations_before_guard": sum(bool(r["guard_violations"]) for r in asked),
                      "guard_fallbacks": sum(r["guard_fallback"] for r in rs), "answers_by_llm": sum(r["writer"] == "ollama" for r in rs),
                      "llm_unavailable": sum(r["llm_unavailable"] for r in rs)})
        for st in STAGES:
            xs = [r["ms"][st] for r in rs if st in r["ms"]]
            m[f"latency_ms_{st}_median" if st != "total" else "latency_ms_median"] = pct(xs, 50)
            m[f"latency_ms_{st}_p90" if st != "total" else "latency_ms_p90"] = pct(xs, 90)
        m["failed_ids"] = [r["id"] for r in rs if not r["answer_ok"]]
        return m

    return {lang: one([r for r in rows if r["lang"] == lang]) for lang in ("en", "hi")} | {"all": one(rows)}


def voice_metrics(rows: list[dict]) -> dict:
    from kami.citizen.evaluate import corpus_wer, pct

    def one(rs):
        if not rs:
            return {"n": 0}
        return {"n": len(rs), "wer": round(corpus_wer([(r["ref_words"], r["hyp_words"]) for r in rs]), 3),
                "wer_raw": round(corpus_wer([(r["ref_words_raw"], r["hyp_words_raw"]) for r in rs]), 3),
                "language_detected": round(sum(r["heard_language"] == r["lang"] for r in rs) / len(rs), 3),
                "slot_accuracy": round(sum(r["slot_ok"] for r in rs) / len(rs), 3), "end_to_end_correct": round(sum(r["final_ok"] for r in rs) / len(rs), 3),
                "answers_by_llm": sum(r["writer"] == "ollama" for r in rs), "guard_fallbacks": sum(r["guard_fallback"] for r in rs),
                "latency_ms": {st: {"median": pct([r["voice_ms"][st] for r in rs], 50), "p90": pct([r["voice_ms"][st] for r in rs], 90)} for st in VOICE_STAGES},
                "failed_ids": [r["id"] for r in rs if not r["final_ok"]]}

    return {lang: one([r for r in rows if r["lang"] == lang]) for lang in ("en", "hi")} | {"all": one(rows)}


def to_markdown(ev: dict) -> str:
    t, v, m = ev["text"]["writers"], ev.get("voice", {}), ev["models"]
    L = ["# Citizen interface: evaluation", "",
         f"Generated by `scripts/citizen_eval.py` on {ev['run_utc']} (commit `{ev['git_commit']}`). Numbers come from `eval.json`; the raw answers are in `test_outputs.json`.", "",
         "**What this is.** " + ev["what"], "",
         f"**Questions.** {ev['questions']['n']} authored test questions ({ev['questions']['en']} English, {ev['questions']['hi']} Hindi, "
         f"{ev['questions']['hi_latin']} of the Hindi ones in Latin letters), written by the developer of the system: {ev['questions']['by_intent']}. "
         "Each part was run once on them; prompts, rules and thresholds were set on the 20 validation questions only. "
         "The correct answer is the structured lookup with the question's gold ward and day at the replay time " + ev["world"]["time"]
         + f", with one planted open alert ({ev['world']['planted_alert']}).", "",
         "**Limits.** The questions are authored by one person who knows the rules of the system, so this measures the system on the intended kind of "
         "question, not on free citizen language. The schedule, wards and notices are fictional. The speech is synthetic speech from the text-to-speech "
         "model, which is cleaner than a real voice note. The numbers below are for 20 questions per language.", "",
         f"**Models (local).** Speech recognition `{m['asr']}`, translation `{m['nmt']}`, speech output `{m['tts']}`, LLM `{m['llm']}` through Ollama; device `{ev['device']}`.", "",
         "## Text questions", "",
         "| Writer | Language | n | Intent, ward and day understood | Answer correct | Reply in the citizen's language correct | No information said exactly when due | Median ms | p90 ms |",
         "|---|---|---|---|---|---|---|---|---|"]
    for w in ("template", "ollama"):
        if t.get(w, {}).get("status") == "pending":
            L.append(f"| {w} | | | pending: {t[w]['reason']} | | | | | |")
            continue
        for lang in ("en", "hi", "all"):
            x = t[w][lang]
            L.append(f"| {w} | {lang} | {x['n']} | {x['slot_accuracy']:.0%} | {x['answer_correct']:.0%} | {x['final_text_correct']:.0%} | {x['no_information_correct']:.0%} "
                     f"| {x['latency_ms_median']} | {x['latency_ms_p90']} |")
    if "all" in t.get("ollama", {}):
        L += ["", "### Local LLM and the grounding guard", "",
              "| Language | Questions given to the LLM | LLM answers that broke a grounding rule (before the guard) | Replaced by the guard | Answers finally written by the LLM | "
              "Hindi translations replaced (numbers lost) | LLM median ms | LLM p90 ms |", "|---|---|---|---|---|---|---|---|"]
        for lang in ("en", "hi", "all"):
            x = t["ollama"][lang]
            L.append(f"| {lang} | {x['asked_llm']} | {x['grounding_violations_before_guard']} | {x['guard_fallbacks']} | {x['answers_by_llm']} | {x['translation_fallbacks']} "
                     f"| {x['latency_ms_llm_median']} | {x['latency_ms_llm_p90']} |")
        L += ["", "Questions without anything to retrieve (no information, ward missing) are answered with a fixed sentence and never go to the LLM. "
              "\"Answer correct\" for the Ollama writer is measured after the guard, which is what a citizen receives."]
    L += ["", "### Latency per stage, text (milliseconds, median / p90)", "", "| Writer | Language | Understand | Translate in | Retrieve | LLM | Translate out | Total |", "|---|---|---|---|---|---|---|---|"]
    for w in ("template", "ollama"):
        if "all" not in t.get(w, {}):
            continue
        for lang in ("en", "hi"):
            x = t[w][lang]
            cells = [f"{x.get(f'latency_ms_{s}_median')} / {x.get(f'latency_ms_{s}_p90')}" for s in STAGES[:-1]] + [f"{x['latency_ms_median']} / {x['latency_ms_p90']}"]
            L.append(f"| {w} | {lang} | " + " | ".join(c.replace("None / None", "not used") for c in cells) + " |")
    for w in ("template", "ollama"):
        if "all" in t.get(w, {}) and t[w]["all"]["failed_ids"]:
            L += ["", f"Questions answered wrongly by the {w} writer: " + ", ".join(f"`{i}`" for i in t[w]["all"]["failed_ids"]) + ". See `eval.json` (`failures`) for each one."]
    if v.get("status") == "pending":
        L += ["", "## Voice questions", "", f"Pending: {v['reason']}"]
    elif v:
        L += ["", "## Voice questions (synthetic speech)", "",
              f"Each test question was spoken by `{m['tts']}`, recognised by `{m['asr']}` with the language detected between Hindi and English, answered by the "
              f"{v['writer']} writer, and the answer was spoken and encoded as a Telegram voice note. This is synthetic speech, not recordings of people.", "",
              "| Language | n | Word error rate | WER without number/spelling normalisation | Language detected | Intent, ward, day | End-to-end correct | Answers by the LLM | Guard fallbacks |",
              "|---|---|---|---|---|---|---|---|---|"]
        for lang in ("en", "hi", "all"):
            x = v[lang]
            L.append(f"| {lang} | {x['n']} | {x['wer']:.1%} | {x['wer_raw']:.1%} | {x['language_detected']:.0%} | {x['slot_accuracy']:.0%} | {x['end_to_end_correct']:.0%} "
                     f"| {x['answers_by_llm']} | {x['guard_fallbacks']} |")
        L += ["", "### Latency per stage, voice (milliseconds, median / p90)", "", "| Language | Speech recognition | Answer | Speech output | OGG encoding | End to end |", "|---|---|---|---|---|---|"]
        for lang in ("en", "hi"):
            x = v[lang]["latency_ms"]
            L.append(f"| {lang} | " + " | ".join(f"{x[s]['median']} / {x[s]['p90']}" for s in VOICE_STAGES) + " |")
        L += ["", f"End to end = from the recorded question to the encoded voice answer, on this machine ({ev['gpu']}); Telegram upload and download times are not included. "
              f"GPU memory in use with all models loaded: {v.get('vram_mb_all_models')} MB of {ev.get('vram_total_mb')} MB."]
        if v["all"]["failed_ids"]:
            L += ["", "Voice questions not answered correctly: " + ", ".join(f"`{i}`" for i in v["all"]["failed_ids"]) + "."]
    L += ["", "## Reading the numbers", "",
          "- \"Answer correct\": a schedule answer states every true time and no other time, no wrong tanker, the status of delivered and delayed tankers, and the "
          "possible-delay note when the ward has an open alert; a notice answer contains the key facts of the right notice; a status answer states what the sensors show.",
          "- \"No information\": questions about an unknown ward or another topic must get the no-information reply, and answerable questions must not.",
          "- Word error rate: word-level edit distance over the reference words, summed over the questions. The normalised form writes digits as words and ignores "
          "spelling variants that sound the same.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "val"])
    ap.add_argument("--parts", nargs="*", default=["text", "voice"])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--no-hints", action="store_true", help="validation only: recognise speech without the domain hint words")
    a = ap.parse_args()
    assert not (a.no_hints and a.split == "test"), "--no-hints is for the validation questions"
    from kami.citizen.answer import OllamaWriter
    from kami.citizen.evaluate import EVAL_ALERTS, EVAL_NOW, load_questions
    from kami.citizen.service import ollama_ready
    from kami.notify.lock import forget_bot_settings

    forget_bot_settings()  # no Telegram client can be built here
    models = chosen_models()
    qs = load_questions(a.split)
    test = a.split == "test"
    OUT.mkdir(parents=True, exist_ok=True)
    out_path, log_path = OUT / ("test_outputs.json" if test else "val_outputs.json"), OUT / "test_access_log.json"
    outputs = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}
    llm_ok = ollama_ready("http://127.0.0.1:11434", models["llm"])
    todo = [k for k in (["text:template", "text:ollama"] if "text" in a.parts else []) + (["voice"] if "voice" in a.parts else [])
            if not (test and k in outputs) and not (k == "text:ollama" and not llm_ok)]
    device = a.device
    if todo:
        tr, asr, tts, audio = build(models, a.device, "voice" in todo, a.no_hints)
        device = tr.device
        llm = OllamaWriter(models["llm"], timeout=180.0) if llm_ok else None
        for k in todo:
            t0 = time.time()
            if k == "text:template":
                rows = run_text(qs, tr, None)
            elif k == "text:ollama":
                rows = run_text(qs, tr, llm)
            else:
                rows = run_voice(qs, tr, llm, asr, tts, audio)
                outputs["voice_meta"] = {"writer": f"Ollama ({models['llm']})" if llm else "template", "vram_mb_all_models": vram_mb()}
            outputs[k] = rows
            if test:
                log[k] = {"utc": now(), "git_commit": commit(), "questions": len(qs), "seconds": round(time.time() - t0, 1), "models": models}
            print(f"{k}: {len(rows)} questions in {time.time() - t0:.0f} s")
        outputs["device"] = device
        out_path.write_text(json.dumps(outputs, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if test:
            log_path.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8", newline="\n")
    writers = {}
    if "text:template" in outputs:
        writers["template"] = text_metrics(outputs["text:template"], False)
    writers["ollama"] = (text_metrics(outputs["text:ollama"], True) if "text:ollama" in outputs
                         else {"status": "pending", "reason": f"the model {models['llm']} was not available in a local Ollama when the evaluation ran"})
    if "voice" in outputs:
        voice = {"speech": "synthetic", "device": outputs.get("device", device), **outputs.get("voice_meta", {}), **voice_metrics(outputs["voice"])}
    else:
        voice = {"status": "pending", "reason": "the voice part has not been run"}
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.strip()
    from collections import Counter

    ev = {"made_by": "scripts/citizen_eval.py", "run_utc": now(), "git_commit": commit(), "split": a.split, "device": outputs.get("device", device), "gpu": gpu or "none",
          "vram_total_mb": int(gpu.split(",")[1]) if "," in gpu else None, "models": models,
          "what": "The citizen interface on authored questions about a fictional tanker schedule and fictional notices. It is separate from the anomaly-detection "
                  "evaluation in results/SUMMARY.md and changes none of those results.",
          "questions": {"n": len(qs), "en": sum(q["lang"] == "en" for q in qs), "hi": sum(q["lang"] == "hi" for q in qs),
                        "hi_latin": sum(q.get("script") == "latin" for q in qs), "by_intent": dict(Counter(q["intent"] for q in qs)), "label": "authored test questions"},
          "world": {"time": EVAL_NOW.isoformat(sep=" ", timespec="minutes"), "planted_alert": "node-3 (Ward 3): " + EVAL_ALERTS["node-3"]["category"] + ", " + EVAL_ALERTS["node-3"]["priority"]},
          "ran_once_log": log if test else None, "text": {"writers": writers}, "voice": voice,
          "failures": {k: [{kk: r[kk] for kk in ("id", "question", "answer_en", "answer", "kind", "ward", "day", "writer", "guard_violations",
                                                 *(["heard"] if "heard" in r else []))} for r in outputs[k] if not r["final_ok"]]
                       for k in ("text:template", "text:ollama", "voice") if k in outputs}}
    if test:
        (OUT / "eval.json").write_text(json.dumps(ev, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        (OUT / "eval.md").write_text(to_markdown(ev), encoding="utf-8", newline="\n")
    for w, m in writers.items():
        if "all" in m:
            print(f"text {w}: slots {m['all']['slot_accuracy']:.0%}, correct {m['all']['answer_correct']:.0%} (en {m['en']['answer_correct']:.0%}, hi {m['hi']['answer_correct']:.0%}), "
                  f"failed {m['all']['failed_ids']}" + (f", guard fallbacks {m['all']['guard_fallbacks']}/{m['all']['asked_llm']}" if "guard_fallbacks" in m["all"] else ""))
    if "all" in voice:
        print(f"voice: WER en {voice['en']['wer']:.1%}, hi {voice['hi']['wer']:.1%}; end-to-end correct {voice['all']['end_to_end_correct']:.0%}; failed {voice['all']['failed_ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
