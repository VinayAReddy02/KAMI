"""Choose the local models of the citizen interface on the VALIDATION questions (never the test questions).

    python scripts/citizen_model_select.py                 # all stages -> results/citizen/model_selection.json and .md
    python scripts/citizen_model_select.py --stages asr_tts nmt llm

Candidates are open models that download without a login. The AI4Bharat models named in the plan (IndicConformer,
IndicTrans2, Indic Parler-TTS) are gated on Hugging Face (login and licence click) and are therefore not used; they
are listed in the result as not used, with the reason.

  asr_tts  every TTS candidate speaks the 20 validation questions, every ASR candidate transcribes them:
           word error rate (the speech is synthetic), language detection, latency.
  nmt      translation candidates: does a translated Hindi notice question find the right notice; do the numbers of
           an English answer survive the translation into Hindi; chrF against the parallel English question.
  llm      local LLM candidates through Ollama: answers accepted by the grounding guard, fallbacks, correctness, latency.

Needs the packages of requirements-citizen.txt and a running Ollama. Runs on the GPU if one is usable. Makes no
Telegram request. A candidate that cannot be loaded is recorded with the reason and skipped.
"""
import argparse
import gc
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "results" / "citizen"
GATED = "gated on Hugging Face (needs a login and a licence click); this project creates no accounts, so it was not downloaded"
NOT_USED = [
    {"model": "ai4bharat/indic-conformer-600m-multilingual", "stage": "asr", "reason": GATED},
    {"model": "ai4bharat/indictrans2-indic-en-dist-200M and indictrans2-en-indic-dist-200M", "stage": "nmt", "reason": GATED},
    {"model": "ai4bharat/indic-parler-tts", "stage": "tts", "reason": GATED},
]
ASR_CANDIDATES = ["large-v3-turbo", "medium"]
LLM_CANDIDATES = ["llama3.2:3b", "qwen2.5:7b"]
PARALLEL = [(f"hi-{i:02d}", f"en-{i:02d}") for i in (1, 2, 3, 4, 6, 7, 8, 9)]  # validation questions written as translations of each other


def vram_mb() -> int | None:
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout.split()[0])
    except Exception:
        return None


def free_gpu() -> None:
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception:
        pass


def chrf(ref: str, hyp: str, n_max: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-score (chrF), 0 to 1."""
    from collections import Counter

    ref, hyp = "".join(ref.split()), "".join(hyp.split())
    ps, rs = [], []
    for n in range(1, n_max + 1):
        r, h = Counter(ref[i:i + n] for i in range(len(ref) - n + 1)), Counter(hyp[i:i + n] for i in range(len(hyp) - n + 1))
        if not r or not h:
            continue
        match = sum((r & h).values())
        ps.append(match / sum(h.values()))
        rs.append(match / sum(r.values()))
    if not ps:
        return 0.0
    p, r = sum(ps) / len(ps), sum(rs) / len(rs)
    return (1 + beta ** 2) * p * r / (beta ** 2 * p + r) if p + r else 0.0


def tts_candidates(device: str) -> dict:
    from kami.citizen.tts import MmsTTS, PiperTTS

    return {"piper (hi: pratham, en: lessac)": lambda: PiperTTS({"hi": "hi_IN-pratham-medium", "en": "en_US-lessac-medium"}),
            "piper (hi: priyamvada, en: lessac)": lambda: PiperTTS({"hi": "hi_IN-priyamvada-medium", "en": "en_US-lessac-medium"}),
            "mms-tts (hin, eng)": lambda: MmsTTS(device=device)}


def stage_asr_tts(device: str, val: list[dict]) -> dict:
    from kami.citizen.audio import resample
    from kami.citizen.evaluate import corpus_wer, pct, words
    from kami.citizen.speech import FasterWhisperASR

    audio, tts_info = {}, {}
    for name, make in tts_candidates(device).items():
        try:
            tts = make()
            t = time.perf_counter()
            tts.load()
            load_s = time.perf_counter() - t
            clips, ms = [], []
            for q in val:
                t = time.perf_counter()
                pcm, rate = tts.synthesize(q.get("speech_text", q["text"]), q["lang"])
                ms.append((time.perf_counter() - t) * 1000)
                clips.append(resample(pcm, rate))
            audio[name] = clips
            tts_info[name] = {"load_s": round(load_s, 1), "synth_ms_median": pct(ms, 50), "audio_s_mean": round(sum(len(c) for c in clips) / 16000 / len(clips), 2)}
            del tts
        except Exception as e:
            tts_info[name] = {"error": type(e).__name__ + ": " + str(e)[:160]}
        free_gpu()
    out = {"tts": tts_info, "asr": {}, "wer": {}}
    for model in ASR_CANDIDATES:
        try:
            before = vram_mb()
            asr = FasterWhisperASR(model, device)
            asr.load()
            out["asr"][model] = {"load_s": round(asr.load_seconds, 1), "device": asr.device, "vram_mb": (vram_mb() or 0) - (before or 0)}
            for name, clips in audio.items():
                pairs, ms, lang_ok = {"hi": [], "en": []}, [], 0
                for q, clip in zip(val, clips):
                    t = time.perf_counter()
                    tr = asr.transcribe(clip, None)
                    ms.append((time.perf_counter() - t) * 1000)
                    lang_ok += tr.language == q["lang"]
                    pairs[q["lang"]].append((words(q.get("speech_text", q["text"]), q["lang"]), words(tr.text, q["lang"])))
                out["wer"][f"{model} | {name}"] = {"wer_hi": round(corpus_wer(pairs["hi"]), 3), "wer_en": round(corpus_wer(pairs["en"]), 3),
                                                   "wer_mean": round((corpus_wer(pairs["hi"]) + corpus_wer(pairs["en"])) / 2, 3),
                                                   "language_detected": f"{lang_ok}/{len(val)}", "asr_ms_median": pct(ms, 50), "asr_ms_p90": pct(ms, 90)}
            del asr
        except Exception as e:
            out["asr"][model] = {"error": type(e).__name__ + ": " + str(e)[:160]}
        free_gpu()
    return out


def stage_nmt(device: str, val: list[dict]) -> dict:
    from kami.citizen.answer import Answerer, NoticeIndex, numbers_survive
    from kami.citizen.evaluate import eval_world, pct
    from kami.citizen.translate import MarianTranslator, NllbTranslator

    by_id = {q["id"]: q for q in val}
    sch, ns = eval_world()
    templates = Answerer(sch, node_state=ns)
    idx = NoticeIndex()
    en_answers = [templates.answer(q["text"]) for q in val if q["lang"] == "en"]
    refs_hi = {q["id"]: templates.answer(q["text"]) for q in val if q["lang"] == "hi" and q["intent"] in ("schedule", "ward_status")}
    out = {}
    for name, make in (("nllb-200-distilled-600M", lambda: NllbTranslator(device=device)), ("opus-mt (hi-en, en-hi)", lambda: MarianTranslator(device))):
        try:
            before = vram_mb()
            tr = make()
            tr.load()
            info = {"load_s": round(tr.load_seconds, 1), "device": tr.device, "vram_mb": (vram_mb() or 0) - (before or 0)}
            ms, hits, n_faq, scores = [], 0, 0, []
            for q in val:
                if q["lang"] != "hi":
                    continue
                t = time.perf_counter()
                en = tr.translate(q.get("speech_text", q["text"]) if q.get("script") == "latin" else q["text"], "hi", "en")
                ms.append((time.perf_counter() - t) * 1000)
                if q["intent"] == "faq":
                    n_faq += 1
                    found = idx.search(en)  # the English channel alone: this measures the translation, not the Hindi keywords
                    hits += bool(found) and found[0][0]["id"] == q["expect"]["notice"]
            for hi_id, en_id in PARALLEL:
                if hi_id in by_id and en_id in by_id:
                    scores.append(chrf(by_id[en_id]["text"], tr.translate(by_id[hi_id]["text"], "hi", "en")))
            keep, ms_out, scores_hi = 0, [], []
            for r in en_answers:
                t = time.perf_counter()
                hi = tr.translate(r.text_en, "en", "hi")
                ms_out.append((time.perf_counter() - t) * 1000)
                keep += numbers_survive(r.text_en, hi)
            for qid, ref in refs_hi.items():  # the fixed Hindi sentences as references for English -> Hindi
                scores_hi.append(chrf(ref.text, tr.translate(ref.text_en, "en", "hi")))
            info.update({"hi_en_notice_found": f"{hits}/{n_faq}", "hi_en_chrf": round(sum(scores) / len(scores), 3) if scores else None,
                         "en_hi_numbers_survive": f"{keep}/{len(en_answers)}", "en_hi_chrf_vs_fixed_hindi": round(sum(scores_hi) / len(scores_hi), 3) if scores_hi else None,
                         "hi_en_ms_median": pct(ms, 50), "en_hi_ms_median": pct(ms_out, 50)})
            out[name] = info
            del tr
        except Exception as e:
            out[name] = {"error": type(e).__name__ + ": " + str(e)[:160]}
        free_gpu()
    return out


def stage_llm(val: list[dict], translator) -> dict:
    import httpx

    from kami.citizen.answer import Answerer, OllamaWriter
    from kami.citizen.evaluate import eval_world, judge, pct, truth
    from kami.citizen.service import ollama_ready

    sch, ns = eval_world()
    out = {}
    for model in LLM_CANDIDATES:
        if not ollama_ready("http://127.0.0.1:11434", model):
            out[model] = {"error": "not available in the local Ollama (not pulled, or Ollama not running)"}
            continue
        for m in LLM_CANDIDATES:  # unload whatever Ollama still holds, so the memory of this candidate is measured from a free state
            try:
                httpx.post("http://127.0.0.1:11434/api/generate", json={"model": m, "keep_alive": 0}, timeout=30)
            except Exception:
                pass
        time.sleep(4)
        before = vram_mb()
        a = Answerer(sch, translator=translator, llm=OllamaWriter(model, timeout=180.0), node_state=ns)
        a.answer("When will the water tanker reach Ward 4?")  # load the model before timing
        used = (vram_mb() or 0) - (before or 0)
        rows = []
        for q in val:
            r = a.answer(q["text"])
            j = judge(q, r, truth(q, sch, ns))
            rows.append({"id": q["id"], "asked_llm": "llm" in r.ms, "by_llm": r.writer == "ollama", "fallback": r.guard_fallback,
                         "answer_ok": j["answer_ok"], "final_ok": j["final_ok"], "llm_ms": r.ms.get("llm")})
        asked = [x for x in rows if x["asked_llm"]]
        out[model] = {"vram_mb": used, "questions": len(rows), "asked_llm": len(asked), "accepted_by_guard": sum(x["by_llm"] for x in rows),
                      "guard_fallbacks": sum(x["fallback"] for x in rows), "answer_correct_after_guard": sum(x["answer_ok"] for x in rows),
                      "final_correct_after_guard": sum(x["final_ok"] for x in rows), "llm_ms_median": pct([x["llm_ms"] for x in asked], 50),
                      "llm_ms_p90": pct([x["llm_ms"] for x in asked], 90), "rows": rows}
        try:  # unload, so the next candidate is measured on a free GPU
            httpx.post("http://127.0.0.1:11434/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
            time.sleep(3)
        except Exception:
            pass
    return out


def choose(result: dict) -> dict:
    """Simple, fixed rules. ASR and TTS: lowest mean word error rate (ties within 0.02 go to the faster one). NMT: more
    numbers kept in the Hindi reply, then chrF of the Hindi reply, then chrF Hindi -> English (the reply a citizen reads
    comes first; the first version of this rule ranked by notices found, on two questions, and was changed after the
    validation outputs showed that one candidate loses numbers). LLM: the small default unless the larger one has at least 3
    fewer guard fallbacks on the validation questions AND fits beside the speech models in 8 GB."""
    chosen, why = {}, {}
    wer = {k: v for k, v in result.get("asr_tts", {}).get("wer", {}).items()}
    if wer:
        asr_mean = {}
        for k, v in wer.items():
            asr_mean.setdefault(k.split(" | ")[0], []).append(v["wer_mean"])
        asr_mean = {k: sum(v) / len(v) for k, v in asr_mean.items()}
        best = min(asr_mean.values())
        close = [k for k, v in asr_mean.items() if v <= best + 0.02]
        asr = min(close, key=lambda k: min(v["asr_ms_median"] for kk, v in wer.items() if kk.startswith(k + " | ")))
        chosen["asr"], why["asr"] = f"faster-whisper:{asr}", f"mean WER over the TTS candidates {asr_mean[asr]:.3f} (all: " + ", ".join(f"{k} {v:.3f}" for k, v in asr_mean.items()) + ")"
        tts_wer = {k.split(" | ")[1]: v["wer_mean"] for k, v in wer.items() if k.startswith(asr + " | ")}
        best = min(tts_wer.values())
        close = [k for k, v in tts_wer.items() if v <= best + 0.02]
        tts = min(close, key=lambda k: result["asr_tts"]["tts"][k].get("synth_ms_median") or 1e9)
        chosen["tts"], why["tts"] = tts, f"WER through {asr} {tts_wer[tts]:.3f} (all: " + ", ".join(f"{k} {v:.3f}" for k, v in tts_wer.items()) + ")"
    nmt = {k: v for k, v in result.get("nmt", {}).items() if "error" not in v}
    if nmt:
        def key(k):
            v = nmt[k]
            return (int(v["en_hi_numbers_survive"].split("/")[0]), v["en_hi_chrf_vs_fixed_hindi"] or 0, v["hi_en_chrf"] or 0)

        pick = max(nmt, key=key)
        chosen["nmt"], why["nmt"] = pick, ("numbers kept in English -> Hindi: " + ", ".join(f"{k} {v['en_hi_numbers_survive']}" for k, v in nmt.items())
                                           + "; chrF against the fixed Hindi sentences: " + ", ".join(f"{k} {v['en_hi_chrf_vs_fixed_hindi']}" for k, v in nmt.items()))
    llm = {k: v for k, v in result.get("llm", {}).items() if "error" not in v}
    if llm:
        small, big = LLM_CANDIDATES[0], LLM_CANDIDATES[1]
        pick = small if small in llm else next(iter(llm))
        if small in llm and big in llm:
            gain = llm[small]["guard_fallbacks"] - llm[big]["guard_fallbacks"]
            fits = (llm[big]["vram_mb"] or 9999) <= 5200  # leaves room for speech recognition and translation in 8 GB
            pick = big if gain >= 3 and fits else small
            why["llm"] = (f"{small}: {llm[small]['guard_fallbacks']} guard fallbacks, {llm[small]['vram_mb']} MB; {big}: {llm[big]['guard_fallbacks']} fallbacks, "
                          f"{llm[big]['vram_mb']} MB; the larger model is kept only with at least 3 fewer fallbacks and at most 5200 MB")
        chosen["llm"] = pick
    return {"chosen": chosen, "why": why}


def to_markdown(r: dict) -> str:
    L = ["# Citizen interface: model choices (validation questions only)", "",
         f"Generated by `scripts/citizen_model_select.py` on {r['run_utc']} (commit `{r['git_commit']}`), device `{r['device']}`, GPU: {r['gpu']}. "
         "20 authored validation questions (10 Hindi, 10 English); the test questions were not used. Speech is synthetic.", "",
         "## Chosen", "", "| Stage | Model | Why |", "|---|---|---|"]
    L += [f"| {k} | {v} | {r['why'].get(k, '')} |" for k, v in r["chosen"].items()]
    L += ["", "## Not used", ""] + [f"- `{x['model']}` ({x['stage']}): {x['reason']}." for x in r["not_used"]]
    a = r.get("asr_tts")
    if a:
        L += ["", "## Speech recognition x speech output (word error rate on synthetic speech)", "",
              "Measured without the domain hint words (ward names, \"ward\", \"tanker\") that the deployed recogniser gets; with them the Hindi error rate of the "
              "chosen pair is lower (see `eval.md`). The comparison between candidates is like for like.", "", "| ASR | TTS | WER Hindi | WER English | Mean | Language detected | ASR median ms | p90 ms |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {k.split(' | ')[0]} | {k.split(' | ')[1]} | {v['wer_hi']} | {v['wer_en']} | {v['wer_mean']} | {v['language_detected']} | {v['asr_ms_median']} | {v['asr_ms_p90']} |" for k, v in a["wer"].items()]
        L += ["", "| Model | Load s | Detail |", "|---|---|---|"]
        L += [f"| ASR {k} | {v.get('load_s', '')} | {v.get('error') or str(v.get('vram_mb')) + ' MB GPU memory, ' + v.get('device', '')} |" for k, v in a["asr"].items()]
        L += [f"| TTS {k} | {v.get('load_s', '')} | {v.get('error') or 'synthesis median ' + str(v.get('synth_ms_median')) + ' ms for ' + str(v.get('audio_s_mean')) + ' s of audio'} |" for k, v in a["tts"].items()]
    n = r.get("nmt")
    if n:
        L += ["", "## Translation", "", "| Model | hi->en: notice found | hi->en chrF | en->hi: numbers kept | en->hi chrF vs fixed Hindi | hi->en ms | en->hi ms | GPU MB | Load s |", "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {k} | {v.get('error') or v['hi_en_notice_found']} | {v.get('hi_en_chrf', '')} | {v.get('en_hi_numbers_survive', '')} | {v.get('en_hi_chrf_vs_fixed_hindi', '')} | {v.get('hi_en_ms_median', '')} | {v.get('en_hi_ms_median', '')} | {v.get('vram_mb', '')} | {v.get('load_s', '')} |" for k, v in n.items()]
    m = r.get("llm")
    if m:
        L += ["", "## Local LLM (Ollama)", "", "| Model | Asked | Accepted by the guard | Guard fallbacks | Correct after guard | Median ms | p90 ms | GPU MB |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {k} | {v.get('error') or v['asked_llm']} | {v.get('accepted_by_guard', '')} | {v.get('guard_fallbacks', '')} | {v.get('answer_correct_after_guard', '')}/{v.get('questions', '')} | {v.get('llm_ms_median', '')} | {v.get('llm_ms_p90', '')} | {v.get('vram_mb', '')} |" for k, v in m.items()]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", nargs="*", default=["asr_tts", "nmt", "llm"])
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()
    from kami.citizen.evaluate import load_questions
    from kami.notify.lock import forget_bot_settings

    forget_bot_settings()  # no Telegram client can be built here; model downloads and the local Ollama stay reachable
    val = load_questions("val")
    path = OUT / "model_selection.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if "asr_tts" in a.stages:
        result["asr_tts"] = stage_asr_tts(a.device, val)
    if "nmt" in a.stages:
        result["nmt"] = stage_nmt(a.device, val)
    result.update(choose(result))
    if "llm" in a.stages:
        from kami.citizen.translate import MarianTranslator, NllbTranslator

        tr = (MarianTranslator(a.device) if "opus" in result["chosen"].get("nmt", "nllb") else NllbTranslator(device=a.device))
        tr.load()
        result["llm"] = stage_llm(val, tr)
        del tr
        free_gpu()
    result.update(choose(result))
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    result.update({"made_by": "scripts/citizen_model_select.py", "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "split": "val",
                   "git_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                   "device": a.device, "gpu": gpu or "none", "not_used": NOT_USED, "questions": len(val)})
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    (OUT / "model_selection.md").write_text(to_markdown(result), encoding="utf-8", newline="\n")
    print(json.dumps(result["chosen"], ensure_ascii=False), "|", json.dumps(result["why"], ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
