"""Reusable word-timing benchmark (2026-10-13).

Two kinds of reference data are supported:

* ``build-synthetic``: speech generated on this machine with built-in Windows
  OneCore voices (zh-CN Huihui / Kangkang / Yaoyao). The synthesizer reports
  each word's start; after pauses these starts sit 0-50 ms from the energy
  onset, which is the stated reference uncertainty. Covers plain Chinese,
  Chinese-English mix, game terms, fast/slow speech, pauses, added noise,
  three speakers and one real overlap. Generated audio is a local test input,
  never shipped, and says nothing about real game commentary.
* ``--reference``: any hand-annotated JSON in the same format
  (``{"audio": ..., "words": [{"text", "start_ms", "end_ms"?, "speaker"?}]}``).

``align`` runs a forced-alignment backend on the *reference text* (pure
alignment); ``score`` compares any prediction file (aligner output or an ASR's
own word times) to the reference and reports median / P95 / max absolute
start error and the share within 50 / 100 / 200 ms, per scenario.
Nothing here is a claim that one backend is "the most accurate"; it reports
what was measured on the stated data.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SR = 16000

# (scenario, voice, rate, text). Kept short so each utterance is one aligner window.
UTTERANCES = [
    ("plain", "Kangkang", 1.0, "大家好，今天我们继续打排位，先看一下这把的阵容。"),
    ("plain", "Huihui", 1.0, "我觉得这局可以先拿下中路，然后再去打小龙。"),
    ("game_terms", "Kangkang", 1.0, "这把我用捷风，先买一把Vandal，再给队友扔个烟。"),
    ("game_terms", "Yaoyao", 1.0, "洛克王国的这个Boss有三个阶段，第二阶段要躲技能。"),
    ("mixed_en", "Huihui", 1.0, "刚才那个clutch太帅了，一打三直接翻盘，GG。"),
    ("mixed_en", "Kangkang", 1.0, "我们这回合eco一下，下回合full buy，记得带defuse kit。"),
    ("numbers", "Yaoyao", 1.0, "现在比分是十二比十，第二十三回合，我们还有三千二百块钱。"),
    ("fast", "Kangkang", 1.45, "快快快他们在B点B点赶紧回防不然这把就没了。"),
    ("fast", "Huihui", 1.4, "等一下等一下我还没买枪你们先别冲我马上就来。"),
    ("slow", "Yaoyao", 0.8, "好的，那我们，慢慢来，一个一个，清点位。"),
    ("pauses", "Kangkang", 1.0, "嗯……这个，我想一想。……算了，还是你来吧。"),
    ("noise", "Huihui", 1.0, "背景音乐有点大，你们听得清我说话吗？"),
    ("noise", "Kangkang", 1.0, "听得清，就是有点吵，我把游戏音量调小一点。"),
    ("dialogue", "Yaoyao", 1.0, "你那边几个人？"),
    ("dialogue", "Kangkang", 1.0, "两个，一个在箱子后面，一个在楼梯上。"),
    ("dialogue", "Huihui", 1.0, "我去补你，三秒到。"),
]
OVERLAP = ("overlap", "Yaoyao", 1.0, "小心左边！")  # starts while the previous line is still speaking


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == SR and handle.getsampwidth() == 2, path
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if handle.getnchannels() > 1:
            data = data.reshape(-1, handle.getnchannels()).mean(axis=1)
    return data


def _write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = np.clip(audio, -1, 1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((pcm * 32767).astype("<i2").tobytes())


def _synthesize(text: str, voice: str, rate: float, out_wav: Path, out_json: Path) -> dict:
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(ROOT / "scripts" / "synth_timing_reference.ps1"), "-Text", text, "-Voice", voice,
                    "-OutWav", str(out_wav), "-OutJson", str(out_json), "-Rate", str(rate)],
                   check=True, capture_output=True)
    return json.loads(out_json.read_text(encoding="utf-8-sig"))


def _noise(n: int, seed: int) -> np.ndarray:
    """Pink-ish noise plus a soft chord, as a stand-in for game audio."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spectrum[1:] /= np.sqrt(freqs[1:])
    pink = np.fft.irfft(spectrum, n)
    pink /= np.max(np.abs(pink)) + 1e-9
    t = np.arange(n) / SR
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.18, 329.63)) / 3
    return 0.6 * pink + 0.4 * chord


def build_synthetic(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for index, (scenario, voice, rate, text) in enumerate(UTTERANCES + [OVERLAP]):
        wav, meta = out_dir / f"u{index:02d}.wav", out_dir / f"u{index:02d}.json"
        info = _synthesize(text, voice, rate, wav, meta)
        parts.append((scenario, voice, rate, text, _read_wav(wav), info))
    timeline, words, utterances = [], [], []
    cursor = 0.5
    gap = 0.6
    overlap_start = None
    for index, (scenario, voice, rate, text, audio, info) in enumerate(parts):
        if scenario == "overlap":
            # Starts 0.7 s before the previous utterance ends (true overlap).
            start = utterances[-1]["end_s"] - 0.7
            overlap_start = start
        else:
            start = cursor
        if scenario == "noise":
            audio = audio + _noise(len(audio), index) * (np.sqrt(np.mean(audio ** 2)) / 3.2)  # about 10 dB SNR
        timeline.append((start, audio))
        end = start + len(audio) / SR
        speaker = {"Kangkang": "M1", "Huihui": "F1", "Yaoyao": "F2"}[voice]
        utterances.append({"index": index, "scenario": scenario, "speaker": speaker, "voice": info.get("voice"),
                           "rate": rate, "text": text, "start_s": round(start, 4), "end_s": round(end, 4)})
        for word in info.get("words") or []:
            words.append({"utterance": index, "scenario": scenario, "speaker": speaker, "text": word["text"],
                          "start_ms": round(start * 1000 + float(word["start_ms"]), 1),
                          "char_offset": int(word["start_position"])})
        if scenario != "overlap":
            cursor = end + gap
    total = max(start + len(audio) / SR for start, audio in timeline) + 0.5
    mix = np.zeros(int(total * SR), dtype=np.float32)
    for start, audio in timeline:
        offset = int(round(start * SR))
        mix[offset:offset + len(audio)] += audio
    mix /= max(1.0, float(np.max(np.abs(mix))) / 0.95)
    audio_path = out_dir / "benchmark.wav"
    _write_wav(audio_path, mix)
    reference = {"kind": "synthetic-windows-onecore", "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "audio": str(audio_path), "sample_rate": SR, "duration_s": round(len(mix) / SR, 3),
                 "reference_uncertainty_ms": "word starts from the synthesizer; 0-50 ms from energy onset after pauses",
                 "overlap_start_s": overlap_start, "utterances": utterances, "words": words,
                 "note": "Synthetic speech for comparing timing backends on identical input. Not real game audio."}
    path = out_dir / "reference.json"
    path.write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _content(text: str) -> str:
    sys.path.insert(0, str(ROOT))
    from twobyteasr.text_rules import content_only
    return content_only(text)


def align(reference_path: Path, out: Path, *, device: str, language: str = "Chinese") -> dict:
    """Pure alignment: the aligner receives each utterance's reference text and window."""
    sys.path.insert(0, str(ROOT))
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    audio = _read_wav(Path(reference["audio"]))
    jobs = [{"id": f"u{u['index']:02d}", "window_start_ms": max(0, int(u["start_s"] * 1000) - 300),
             "window_end_ms": int(u["end_s"] * 1000) + 300, "text": u["text"], "language": language}
            for u in reference["utterances"]]
    os.environ["TWOBYTEASR_ALIGNER_DEVICE"] = device
    from twobyteasr.asr import run_qwen_aligner_worker
    peak = _PeakChildMemory()
    started = time.perf_counter()
    with peak:
        payload = run_qwen_aligner_worker(audio, jobs)
    wall = time.perf_counter() - started
    predictions = []
    for row in payload["results"]:
        for unit in row.get("char_units") or row.get("word_units") or []:
            predictions.append(_unit_prediction(row, unit))
    result = {"backend": f"qwen3-forced-aligner/{payload.get('backend') or device}", "device": payload.get("device"),
              "dtype": payload.get("dtype"), "wall_s": round(wall, 3), "load_ms": payload.get("load_ms"),
              "inference_ms": payload.get("inference_ms"), "audio_s": reference["duration_s"],
              "peak_worker_rss_mb": peak.peak_mb,
              "mode": "pure_alignment_reference_text", "predictions": predictions}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


class _PeakChildMemory:
    """Peak resident memory of this process's children (the model worker)."""

    def __init__(self, interval: float = 0.2):
        self.interval = interval
        self.peak_mb = None
        self._stop = None

    def __enter__(self):
        import threading
        import psutil
        self._stop = threading.Event()
        me = psutil.Process()

        def sample():
            peak = 0
            while not self._stop.is_set():
                try:
                    total = sum(child.memory_info().rss for child in me.children(recursive=True))
                except Exception:
                    total = 0
                peak = max(peak, total)
                self.peak_mb = round(peak / 1048576, 1)
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        return False


def _unit_prediction(row: dict, unit) -> dict:
    if isinstance(unit, dict):
        data = unit
    else:  # compact rows follow forced_alignment.UNIT_FIELDS
        from twobyteasr.forced_alignment import UNIT_FIELDS
        data = dict(zip(UNIT_FIELDS, unit))
    text = str(row.get("text") or "")
    return {"utterance": int(str(row["id"]).lstrip("u")), "text": text[int(data["char_start"]):int(data["char_end"])],
            "char_start": int(data["char_start"]), "start_ms": float(data["start_ms"]), "end_ms": float(data["end_ms"]),
            "start_basis": data.get("start_basis"), "end_basis": data.get("end_basis")}


def score(reference_path: Path, prediction_path: Path) -> dict:
    """Match reference words to predicted units by utterance + character offset
    (pure alignment) or by in-order content matching (end-to-end ASR words)."""
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
    by_utterance = {}
    for item in prediction["predictions"]:
        by_utterance.setdefault(item.get("utterance"), []).append(item)
    errors = {}
    unmatched = 0
    measured_only = []
    for word in reference["words"]:
        candidates = by_utterance.get(word["utterance"]) or []
        match = next((c for c in candidates if c.get("char_start") == word["char_offset"]), None)
        if match is None:
            unmatched += 1
            continue
        error = float(match["start_ms"]) - float(word["start_ms"])
        errors.setdefault(word["scenario"], []).append(error)
        errors.setdefault("all", []).append(error)
        if match.get("start_basis") in (None, "model"):
            measured_only.append(error)
    report = {"backend": prediction.get("backend"), "mode": prediction.get("mode"),
              "reference": reference.get("kind"), "reference_uncertainty_ms": reference.get("reference_uncertainty_ms"),
              "unmatched_reference_words": unmatched, "wall_s": prediction.get("wall_s"),
              "audio_s": prediction.get("audio_s"), "scenarios": {}}
    for name, values in sorted(errors.items()):
        report["scenarios"][name] = _stats(values)
    if measured_only:
        report["scenarios"]["all_model_measured_starts"] = _stats(measured_only)
    return report


def score_project(reference_path: Path, project_path: Path) -> dict:
    """End-to-end: word times saved in a recognized project vs the reference.

    Each reference word is matched by its position in the utterance's content
    characters to the project word that starts at the same character (cues
    of the same speaker inside the utterance's time range, in order). Words
    whose text was rewritten later (e.g. numbers) stay unmatched.
    """
    sys.path.insert(0, str(ROOT))
    from twobyteasr.text_rules import content_only
    from twobyteasr.studio_project import load_project
    from twobyteasr.cue_word_alignment import cue_words
    reference = json.loads(reference_path.read_text(encoding='utf-8'))
    project = load_project(project_path)
    cues = sorted(project.cues, key=lambda cue: cue.start_ms)
    words_by_cue = {}
    for cue in cues:
        try:
            words, _reason = cue_words(project, cue)
        except Exception:
            words = ()
        words_by_cue[cue.id] = list(words)
    errors, unmatched, matched_utterances = {}, 0, 0
    for utterance in reference['utterances']:
        start_ms, end_ms = utterance['start_s'] * 1000, utterance['end_s'] * 1000
        inside = [c for c in cues if c.start_ms < end_ms - 50 and c.end_ms > start_ms + 50]
        predicted, cursor = {}, 0
        stream = ''.join(content_only(c.text) for c in inside)
        target = content_only(utterance['text'])
        offset = stream.find(target) if target else -1
        if offset < 0:
            unmatched += sum(1 for w in reference['words'] if w['utterance'] == utterance['index'])
            continue
        matched_utterances += 1
        for cue in inside:
            for word in words_by_cue.get(cue.id, ()):
                text = content_only(getattr(word, 'text', ''))
                predicted.setdefault(cursor - offset, float(word.start_ms))
                cursor += len(text)
            if not words_by_cue.get(cue.id):
                cursor += len(content_only(cue.text))
        for word in (w for w in reference['words'] if w['utterance'] == utterance['index']):
            index = len(content_only(utterance['text'][:word['char_offset']]))
            if index not in predicted:
                unmatched += 1
                continue
            error = predicted[index] - float(word['start_ms'])
            errors.setdefault(word['scenario'], []).append(error)
            errors.setdefault('all', []).append(error)
    return {'mode': 'end_to_end_project', 'project': str(project_path), 'matched_utterances': matched_utterances,
            'unmatched_reference_words': unmatched,
            'scenarios': {name: _stats(values) for name, values in sorted(errors.items())}}


def _stats(values) -> dict:
    data = np.abs(np.asarray(values, dtype=float))
    signed = np.asarray(values, dtype=float)
    return {"n": int(data.size), "median_abs_ms": round(float(np.median(data)), 1),
            "p95_abs_ms": round(float(np.percentile(data, 95)), 1), "max_abs_ms": round(float(np.max(data)), 1),
            "median_signed_ms": round(float(np.median(signed)), 1),
            "within_50ms": round(float(np.mean(data <= 50)), 3), "within_100ms": round(float(np.mean(data <= 100)), 3),
            "within_200ms": round(float(np.mean(data <= 200)), 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-synthetic")
    build.add_argument("--out", required=True)
    run = sub.add_parser("align")
    run.add_argument("--reference", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    grade = sub.add_parser("score")
    grade.add_argument("--reference", required=True)
    grade.add_argument("--prediction", required=True)
    project = sub.add_parser("score-project")
    project.add_argument("--reference", required=True)
    project.add_argument("--project", required=True)
    args = parser.parse_args()
    if args.command == "build-synthetic":
        print(build_synthetic(Path(args.out)))
    elif args.command == "align":
        result = align(Path(args.reference), Path(args.out), device=args.device)
        print(json.dumps({k: v for k, v in result.items() if k != "predictions"}, ensure_ascii=False))
    elif args.command == "score-project":
        print(json.dumps(score_project(Path(args.reference), Path(args.project)), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(score(Path(args.reference), Path(args.prediction)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
