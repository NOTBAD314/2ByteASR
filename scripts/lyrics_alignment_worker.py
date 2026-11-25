"""Run the optional local singing aligner without importing Torch into the GUI."""
import argparse
import json
import os
from pathlib import Path
import sys
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _whisper_draft(audio, model_dir, language):
    from twobyteasr.recognition.asr import transcribe_whisper_reference
    from twobyteasr.subtitle_rules.language_rules import language_scope

    if float(np.max(np.abs(audio))) < .001:
        raise ValueError("选区没有可辨识的声音")
    os.environ["2BYTEASR_WHISPER_DIR"] = str(model_dir)
    with language_scope(language or "auto"):
        rows = transcribe_whisper_reference("", [{"start": 0., "end": len(audio) / 16000}],
                                            shared_audio=audio)
    value = "\n".join(row["text"] for row in rows).strip()
    if not value:
        raise ValueError("没有得到可编辑的歌词草稿")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--draft", action="store_true")
    modes.add_argument("--scene", action="store_true")
    parser.add_argument("--scene-runtime", type=Path)
    parser.add_argument("--language", default="", choices=("", "en", "zh", "ja", "es", "fr", "de"))
    args = parser.parse_args()
    from twobyteasr.recognition.lyrics_ctc import SAMPLE_RATE, MAX_SECONDS, run_alignment

    try:
        if args.request.stat().st_size > 32768:
            raise ValueError("歌词超出局部音频可对齐范围")
        lines = json.loads(args.request.read_bytes())
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise ValueError("歌词需要逐行输入")
        with wave.open(str(args.audio), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ValueError("歌词音频格式错误")
            frames = source.getnframes()
            if not 0 < frames <= SAMPLE_RATE * MAX_SECONDS:
                raise ValueError("局部歌词对齐最多 30 秒")
            raw = source.readframes(frames)
        if len(raw) != frames * 2:
            raise ValueError("歌词音频文件未完整写入")
        audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
        if args.scene:
            from twobyteasr.recognition.lyric_scene import detect_selected_song

            receipt = {"scene": detect_selected_song(audio, args.model_dir / "yamnet.tflite", args.scene_runtime)}
        elif args.draft:
            receipt = {"draft": _whisper_draft(audio, args.model_dir, args.language)}
        else:
            receipt = {"lines": run_alignment(audio, args.model_dir, lines)}
    except ValueError as exc:
        receipt = {"error": str(exc)[:240]}
    except Exception as exc:
        receipt = {"error": f"本机歌词模型未完成（{type(exc).__name__}）"}
    args.output.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
