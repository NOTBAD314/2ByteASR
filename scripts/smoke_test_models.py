"""Installed-model smoke test for release verification.

Default mode validates locked files and imports. ``--infer`` additionally loads
the selected weights and executes a real forward/transcription pass against a
short WAV. Results explicitly say whether inference was executed, so a cheap
file check cannot be mistaken for a model test.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def installed_keys() -> set[str]:
    from twobyteasr.model_workshop import installed_model_keys

    return installed_model_keys(ROOT)


def verify_files(keys: list[str]) -> list[dict]:
    from twobyteasr.model_integrity import verify_model_files

    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    results = []
    for key in keys:
        spec = lock.get("models", {}).get(key)
        if not spec:
            results.append({"model": key, "ok": False, "phase": "files", "error": "not in lock"})
            continue
        started = time.perf_counter()
        try:
            verify_model_files(key, ROOT / spec["path"])
            results.append(
                {
                    "model": key,
                    "ok": True,
                    "phase": "files",
                    "inference_executed": False,
                    "seconds": round(time.perf_counter() - started, 3),
                }
            )
        except Exception as exc:  # noqa: BLE001 - CLI report must include all models
            results.append(
                {
                    "model": key,
                    "ok": False,
                    "phase": "files",
                    "inference_executed": False,
                    "error": " ".join(str(exc).split()),
                }
            )
    return results


def infer_model(key: str, audio_path: Path) -> dict:
    import moss_firered_pipeline as pipeline
    import subtitle_core as legacy

    audio = legacy.decode_audio_to_array(str(audio_path))
    seconds = len(audio) / legacy.AUDIO_SAMPLE_RATE
    speech_regions = [{"start": 0.0, "end": seconds}]
    started = time.perf_counter()
    if key == "firered_vad":
        try:
            output = pipeline.detect_firered_vad(audio, legacy)
            count = len(output)
        except RuntimeError as exc:
            if "没有检测到语音" not in str(exc):
                raise
            count = 0
    elif key == "firered_aed":
        output = legacy.transcribe_firered_reference(audio, seconds, force=True)
        count = len(output)
    elif key == "qwen_asr":
        output = legacy.transcribe_qwen_reference(
            str(audio_path), speech_regions, audio, backend_override="local"
        )
        count = len(output)
    elif key == "moss":
        with tempfile.TemporaryDirectory(prefix="2byteasr_moss_smoke_") as cache_dir:
            cache_context = {
                "cache_dir": cache_dir,
                "identity": {
                    "path": str(audio_path.resolve()).casefold(),
                    "size": audio_path.stat().st_size,
                    "mtime_ns": audio_path.stat().st_mtime_ns,
                },
            }
            try:
                output = pipeline.transcribe_moss_global(
                    str(audio_path), audio, legacy, cache_context
                )
                count = len(output.get("segments", []))
            except RuntimeError as exc:
                if "无法解析为说话人时间段" not in str(exc):
                    raise
                count = 0
    else:
        raise RuntimeError(f"尚未为 {key} 定义真实推理冒烟适配器。")
    return {
        "model": key,
        "ok": True,
        "phase": "inference",
        "inference_executed": True,
        "output_items": count,
        "seconds": round(time.perf_counter() - started, 3),
        "note": "短测试音频可能产生 0 条文字；此项只验证权重加载与真实推理链路不崩溃。",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--infer", action="store_true")
    parser.add_argument("--model", action="append", dest="models")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    keys = args.models or sorted(installed_keys())
    results = verify_files(keys)
    if args.infer:
        if not args.audio or not args.audio.is_file():
            parser.error("--infer requires an existing --audio WAV/media file")
        for key in keys:
            if key not in {"moss", "firered_vad", "firered_aed", "qwen_asr"}:
                continue
            try:
                results.append(infer_model(key, args.audio.resolve()))
            except Exception as exc:  # noqa: BLE001 - continue and report all selected models
                results.append(
                    {
                        "model": key,
                        "ok": False,
                        "phase": "inference",
                        "inference_executed": True,
                        "error": " ".join(str(exc).split()),
                    }
                )
    report = {
        "schema": 1,
        "audio": str(args.audio.resolve()) if args.audio else "",
        "results": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return 1 if any(not item["ok"] for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
