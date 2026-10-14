"""Acceptance: an English subtitle job on local models (2026-10-14).

Builds a short English game-stream clip with two built-in Windows voices
(Microsoft Zira Desktop, and the Huihui OneCore voice reading English as a
second speaker), runs the real recognition queue (``service.run_media_queue``)
with isolated user data and local models only (MOSS, Qwen3-ASR, Qwen3-
ForcedAligner; AI segmentation, AI proofreading and translation are off, so
nothing is uploaded), then checks the saved project against the English rules:

* the task ran as English and the timeline used Qwen3-ForcedAligner (English);
* words are separated by spaces, no subtitle is cut inside a word, every
  subtitle is at most 42 characters and none ends with an article/preposition
  in mid-sentence;
* the recognized words match the script (word accuracy) and start times are
  close to the utterance starts.

usage: python scripts/verify_english_local_flow.py --out tmp/<new dir> [--language en|auto]
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = (
    ("A", "Alright everyone, welcome back to the stream."),
    ("B", "Today we are finally going to beat the final boss, and I have been practicing all week for this."),
    ("A", "Okay so the plan is that we go around the left side of the map, grab the shield and then we push into the boss room."),
    ("B", "Wait, did you see that? He just teleported behind me and I was not ready for it at all."),
    ("A", "Thank you so much for the twenty gifted subs, that is absolutely insane."),
    ("B", "We need to get to the castle in about ten minutes or the dragon will escape again."),
    ("A", "Nice shot! That was amazing."),
    ("B", "Don't worry, I'll heal you after this fight."),
)
SAPI = r"""
param([string]$Text, [string]$OutWav)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Zira Desktop')
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($OutWav, $fmt)
$s.Speak($Text)
$s.Dispose()
"""


def _read_pcm(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as stream:
        rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2" if width == 2 else "<i4")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype("<i2")
    if rate != 16000:
        positions = np.linspace(0, len(data) - 1, int(len(data) * 16000 / rate))
        data = np.interp(positions, np.arange(len(data)), data).astype("<i2")
    return data


def build_speech(directory: Path) -> dict:
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    sapi = directory / "zira.ps1"
    sapi.write_text(SAPI, encoding="utf-8")
    onecore = ROOT / "scripts" / "synth_timing_reference.ps1"
    gap = np.zeros(int(0.7 * 16000), dtype="<i2")
    pieces, utterances, cursor = [gap], [], len(gap)
    for index, (speaker, text) in enumerate(SCRIPT):
        part = directory / f"part{index}.wav"
        if speaker == "A":
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(sapi),
                       "-Text", text, "-OutWav", str(part)]
        else:
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(onecore),
                       "-Text", text, "-Voice", "Huihui", "-OutWav", str(part), "-OutJson", str(part.with_suffix(".json"))]
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        samples = _read_pcm(part)
        utterances.append({"speaker": speaker, "text": text, "start_s": cursor / 16000,
                           "end_s": (cursor + len(samples)) / 16000})
        pieces += [samples, gap]
        cursor += len(samples) + len(gap)
    audio = directory / "english-speech.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(np.concatenate(pieces).tobytes())
    reference = {"audio": str(audio), "utterances": utterances, "origin": "Windows voices on this machine"}
    (directory / "reference.json").write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding="utf-8")
    return reference


def words(text: str) -> list[str]:
    from twobyteasr.english_text import word_core
    return [core for core in (word_core(token) for token in str(text).split()) if core]


def check_project(project_path: Path, reference: dict) -> dict:
    from twobyteasr import english_segmentation as seg
    from twobyteasr.english_text import RULES, display_length, word_core
    from twobyteasr.language_rules import project_language
    from twobyteasr.studio_project import load_project
    project = load_project(project_path)
    cues = sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms))
    texts = [cue.text for cue in cues]
    expected = [w for u in reference["utterances"] for w in words(u["text"])]
    got = [w for text in texts for w in words(text)]
    matcher = difflib.SequenceMatcher(a=expected, b=got, autojunk=False)
    accuracy = sum(block.size for block in matcher.get_matching_blocks()) / max(1, len(expected))
    vocabulary = set(expected)
    hanging = []
    for text in texts:
        tokens = text.split()
        if len(tokens) > 1 and not seg.SENTENCE_END.search(tokens[-1]) and not seg.CLAUSE_END.search(tokens[-1]):
            if word_core(tokens[-1]) in seg.DETERMINERS:
                hanging.append(text)
    glued = [text for text in texts if any(len(token) > 18 and token.isalpha() for token in text.split())]
    broken = [w for text in texts for w in words(text) if w not in vocabulary and len(w) <= 3
              and any(v.startswith(w) and v != w for v in vocabulary)]
    starts = [cue.start_ms / 1000 for cue in cues]
    start_errors = []
    for utterance in reference["utterances"]:
        nearest = min(starts, key=lambda value: abs(value - utterance["start_s"])) if starts else None
        if nearest is not None:
            start_errors.append(round(abs(nearest - utterance["start_s"]) * 1000))
    return {
        "language": project_language(project), "cues": len(cues), "texts": texts,
        "word_accuracy": round(accuracy, 3),
        "max_chars": max((display_length(text) for text in texts), default=0),
        "over_limit": [text for text in texts if display_length(text) > RULES.max_chars and len(text.split()) > 1],
        "hanging_determiner": hanging, "glued_words": glued, "possible_cut_words": broken,
        "spaces_between_words": all(" " in text for text in texts if len(words(text)) > 1),
        "utterance_start_error_ms": start_errors,
        "speakers": sorted({cue.speaker_id for cue in cues}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--language", choices=["en", "auto"], default="en")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if "tmp" not in {part.lower() for part in out.parts}:
        raise SystemExit("--out must be under a tmp directory")
    out.mkdir(parents=True, exist_ok=True)
    user_data = out / "user-data"
    user_data.mkdir(exist_ok=True)
    os.environ["2BYTEASR_USER_DATA_ROOT"] = str(user_data)
    os.environ["LOCALAPPDATA"] = str(user_data)
    os.environ["QT_QPA_PLATFORM"] = os.environ.get("QT_QPA_PLATFORM", "offscreen")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.path.insert(0, str(ROOT))
    reference = build_speech(out / "speech")
    video = out / "english-test.mp4"
    ffmpeg = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    subprocess.run([str(ffmpeg), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x33445a:s=640x360:r=30",
                    "-i", reference["audio"], "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", str(video)], check=True)
    import subtitle_core as legacy
    models = legacy.RUNTIME_SETTINGS.setdefault("models", {})
    switches = legacy.RUNTIME_SETTINGS.setdefault("switches", {})
    models.update(primary_asr_backend="moss", qwen_asr_backend="local", firered_asr_backend="local")
    switches.update(enable_ai_polish=False, use_ai_grouping=False, unified_glm_processing=False,
                    enable_qwen_asr_reference=True)
    legacy.RUNTIME_SETTINGS.setdefault("subtitle_language", {}).update(recognition_language=args.language,
                                                                        output="original")
    legacy.configure_runtime_asr(models)
    from twobyteasr.service import RunOptions, run_media_queue
    from twobyteasr.speaker_strategy import resolve
    options = RunOptions(settings_snapshot_json=json.dumps(legacy.RUNTIME_SETTINGS, ensure_ascii=False),
                         speaker_source=resolve(legacy.RUNTIME_SETTINGS), recognition_language=args.language,
                         subtitle_output="original")
    started = time.perf_counter()
    result = run_media_queue([str(video)], options, event_sink=lambda event: None)
    media = result.results[0]
    receipt = {"language_requested": args.language, "elapsed_s": round(time.perf_counter() - started, 1),
               "exit_code": result.exit_code, "status": media.status, "error": media.error,
               "project": str(getattr(media, "project_path", "") or "")}
    report_path = Path(str(getattr(media, "report_json_path", "") or ""))
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        events = report.get("events") or report.get("run_events") or []
        receipt["task_language_events"] = [e for e in events if (e.get("kind") or e.get("event")) == "TASK_LANGUAGE"][:1]
        receipt["timeline_rerouted"] = [e for e in events if (e.get("kind") or e.get("event")) == "timeline_backend_rerouted"][:1]
        receipt["english_finalized"] = [e for e in events if (e.get("kind") or e.get("event")) == "english_cues_finalized"][:1]
        summary = [e for e in events if (e.get("kind") or e.get("event")) == "japanese_word_timing_summary"]
        receipt["cues_with_measured_words"] = summary[0].get("measured") if summary else None
    if receipt["project"] and Path(receipt["project"]).is_file():
        receipt["check"] = check_project(Path(receipt["project"]), reference)
    check = receipt.get("check") or {}
    receipt["passed"] = bool(result.exit_code == 0 and check.get("language") == "en" and check.get("cues")
                             and not check.get("over_limit") and not check.get("hanging_determiner")
                             and not check.get("glued_words") and check.get("spaces_between_words")
                             and check.get("word_accuracy", 0) >= 0.8
                             and (receipt.get("cues_with_measured_words") or 0) >= 0.8 * check.get("cues", 0))
    (out / "result.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
