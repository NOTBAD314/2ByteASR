"""P5.3 native encoder benchmarks and stage-aware progress logs. No GUI import."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.studio_render import (
    STAGE_ENCODE,
    STAGE_MUX,
    STAGE_PREPARE_PROJECT,
    STAGE_PREPARE_SUBTITLES,
    RenderJob,
    RenderSettings,
    run_render_job,
)

SHOTS = ROOT / "tmp" / "p53-accept"
SHOTS.mkdir(parents=True, exist_ok=True)
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
SOURCE = Path(Path.home() / "Desktop" / r"尼奈早稻机VLOG.mp4")


def gpu_stats() -> dict:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.encoder,utilization.decoder,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
        )
        parts = [item.strip() for item in completed.stdout.split(",")]
        if len(parts) >= 4:
            return {
                "gpu": float(parts[0]), "nvenc": float(parts[1]),
                "nvdec": float(parts[2]), "vram_mb": float(parts[3]),
            }
    except Exception:
        pass
    return {}


def write_ass(path: Path, text: str = "P53") -> Path:
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,32,32,48,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:12.00,Default,,0,0,0,,{text}\n",
        encoding="utf-8",
    )
    return path


def cut_range(source: Path, dest: Path, start: float, duration: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        print("reuse clip", dest)
        return dest
    print("cutting", dest.name, start, duration, flush=True)
    subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ac", "2", str(dest)],
        check=True,
    )
    return dest


def log_progress(media: Path, duration: float, name: str) -> dict:
    ass = write_ass(SHOTS / f"{name}.ass", name)
    output = SHOTS / "bench" / f"{name}-progress.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    events = []
    started = time.perf_counter()

    def progress(payload: dict) -> None:
        events.append({"t": round(time.perf_counter() - started, 3), **dict(payload)})

    job = RenderJob(
        str(media), str(ass), str(output),
        RenderSettings(encoder="h264_nvenc", quality_mode="cq", quality=23, preset="p4"),
        0.0, duration, True,
    )
    try:
        run_render_job(FFMPEG, job, progress=progress)
        error = ""
    except Exception as exc:
        error = str(exc)
    wall = time.perf_counter() - started
    percents = []
    for event in events:
        raw = event.get("percent")
        if raw:
            try:
                percents.append(float(raw))
            except ValueError:
                pass
    jump = max((b - a for a, b in zip(percents, percents[1:])), default=0.0)
    payload = {
        "name": name, "duration": duration, "wall": round(wall, 3),
        "ok": output.is_file() and not error, "error": error[:500],
        "size": output.stat().st_size if output.is_file() else 0,
        "stages": [event.get("stage") for event in events if event.get("stage")],
        "first_events": events[:12],
        "max_percent_jump": round(jump, 2),
        "had_prepare": any(event.get("stage") == STAGE_PREPARE_PROJECT for event in events),
        "had_subtitles": any(event.get("stage") == STAGE_PREPARE_SUBTITLES for event in events),
        "had_encode": any(event.get("stage") == STAGE_ENCODE for event in events),
        "had_mux": any(event.get("stage") == STAGE_MUX for event in events),
        "indeterminate_before_encode": any(
            event.get("stage") in {STAGE_PREPARE_PROJECT, STAGE_PREPARE_SUBTITLES}
            and event.get("indeterminate") == "1" for event in events
        ),
    }
    (SHOTS / f"{name}-progress.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("progress", name, payload["wall"], "jump", payload["max_percent_jump"], payload["stages"][:8], flush=True)
    return payload


def bench_one(media: Path, duration: float, label: str, encoder: str) -> dict:
    ass = write_ass(SHOTS / f"bench-{label}.ass", label)
    output = SHOTS / "bench" / f"{label}-{encoder}.mp4"
    if output.exists():
        output.unlink()
    codec = "hevc" if "hevc" in encoder else "av1" if "av1" in encoder else "h264"
    settings = RenderSettings(
        encoder=encoder, codec=codec,
        quality_mode="cq" if encoder.endswith("nvenc") else "crf",
        quality=23 if encoder.endswith("nvenc") else 20,
        preset="p4" if encoder.endswith("nvenc") else "veryfast",
    )
    job = RenderJob(str(media), str(ass), str(output), settings, 0.0, duration, True)
    samples = []
    stop = {"done": False}

    def sampler() -> None:
        while not stop["done"]:
            samples.append({"t": round(time.perf_counter() - started, 2), **gpu_stats()})
            time.sleep(0.8)

    import threading
    print("bench start", label, encoder, flush=True)
    started = time.perf_counter()
    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()
    error = ""
    try:
        run_render_job(FFMPEG, job)
    except Exception as exc:
        error = str(exc)
    stop["done"] = True
    thread.join(timeout=2)
    wall = time.perf_counter() - started
    enc = [row.get("nvenc") or 0 for row in samples if row]
    gpu = [row.get("gpu") or 0 for row in samples if row]
    row = {
        "label": label, "encoder": encoder, "duration": duration,
        "wall": round(wall, 3),
        "realtime": round(duration / wall, 3) if wall else 0,
        "approx_fps": round((duration * 30) / wall, 2) if wall else 0,
        "size": output.stat().st_size if output.is_file() else 0,
        "error": error[:400],
        "nvenc_peak": max(enc) if enc else None,
        "gpu_peak": max(gpu) if gpu else None,
        "nvenc_avg": round(sum(enc) / len(enc), 1) if enc else None,
        "gpu_avg": round(sum(gpu) / len(gpu), 1) if gpu else None,
        "samples": len(samples),
    }
    print("bench done", label, encoder, f"{wall:.2f}s", f"{row['realtime']:.2f}x", error[:80], flush=True)
    return row


def main() -> int:
    print("bench script start", flush=True)
    if not SOURCE.is_file():
        raise SystemExit(f"missing source {SOURCE}")
    clips = {
        "native-30s": (8.0, 30.0),
        "native-2min": (40.0, 120.0),
        "native-range-3min": (180.0, 180.0),
    }
    progress_rows = []
    bench_rows = []
    encoders = ["libx264", "h264_nvenc", "hevc_nvenc", "av1_nvenc"]
    for name, (start, duration) in clips.items():
        clip = cut_range(SOURCE, SHOTS / "clips" / f"{name}.mp4", start, duration)
        progress_rows.append(log_progress(clip, duration, name))
        for encoder in encoders:
            bench_rows.append(bench_one(clip, duration, name, encoder))
    (SHOTS / "progress-log.json").write_text(json.dumps(progress_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (SHOTS / "benchmark.json").write_text(json.dumps(bench_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", SHOTS / "benchmark.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
