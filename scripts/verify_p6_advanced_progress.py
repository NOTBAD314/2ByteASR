"""P6-P0: live Advanced Remotion export with real stage progress."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.advanced_renderer import AdvancedRendererBackend
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_render import (
    STAGE_ADVANCED_RENDER,
    STAGE_ENCODE,
    STAGE_MUX,
    STAGE_PREPARE_PROJECT,
    STAGE_PREPARE_SUBTITLES,
    RenderJob,
    RenderSettings,
)

FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = FFMPEG.with_name("ffprobe.exe")
SOURCE_30S = ROOT / "tmp" / "p53-accept" / "clips" / "native-30s.mp4"
VLOG = Path(Path.home() / "Desktop" / r"尼奈早稻机VLOG.mp4")
OUT = ROOT / "tmp" / "p6-accept"
OUT.mkdir(parents=True, exist_ok=True)


def ffprobe_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return float(completed.stdout.strip() or 0)
    except ValueError:
        return 0.0


def cut_clip(source: Path, dest: Path, start: float, duration: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 50_000:
        return dest
    subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", str(dest),
        ],
        check=True,
    )
    return dest


def main() -> int:
    source = SOURCE_30S if SOURCE_30S.is_file() else VLOG
    if not source.is_file():
        raise SystemExit(f"missing source: {source}")
    clip = cut_clip(source, OUT / "advanced-6s.mp4", 2.0, 6.0)
    duration = ffprobe_duration(clip)
    recipe = style_recipe_for_prompt("赛博朋克 Cyberpunk HUD 多层描边 glow glitch")
    project = SubtitleProject(
        media=StudioMedia(
            path=str(clip),
            display_name=clip.name,
            duration_ms=round(duration * 1000),
            width=1280,
            height=720,
        ),
        speakers=[StudioSpeaker(id="S01", name="主播")],
        cues=[
            StudioCue(
                id="adv-1",
                start_ms=200,
                end_ms=max(1200, round(duration * 1000) - 400),
                text="P6 Advanced Remotion",
                speaker_id="S01",
                style_id="cyber",
            )
        ],
    )
    project.style_recipes["cyber"] = recipe.to_dict()
    output = OUT / "advanced-live.mp4"
    if output.exists():
        output.unlink()
    events: list[dict] = []
    traces: list[dict] = []
    started = time.perf_counter()

    def progress(payload: dict) -> None:
        item = {"t": round(time.perf_counter() - started, 3), **dict(payload)}
        events.append(item)
        print("PROGRESS", json.dumps(item, ensure_ascii=False), flush=True)

    def trace(name: str, payload=None) -> None:
        item = {"t": round(time.perf_counter() - started, 3), "trace": name, "payload": payload}
        traces.append(item)
        preview = payload
        if isinstance(payload, list) and len(payload) > 8:
            preview = payload[:8] + ["…"]
        print("TRACE", name, preview, flush=True)

    job = RenderJob(
        media_path=str(clip),
        ass_path=str(OUT / "advanced-placeholder.ass"),
        output_path=str(output),
        settings=RenderSettings(
            codec="h264",
            encoder="h264_nvenc",
            container="mp4",
            quality_mode="cq",
            quality=23,
            width=1280,
            height=720,
            fps=30,
            audio_codec="aac",
        ),
        start_seconds=0.0,
        duration_seconds=duration,
        overwrite_existing=True,
    )
    (OUT / "advanced-placeholder.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,24,24,32,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n",
        encoding="utf-8",
    )
    backend = AdvancedRendererBackend()
    status = backend.status()
    print("renderer", status.available, status.reason, flush=True)
    result = backend.render(project, FFMPEG, job, progress=progress, trace=trace)
    wall = time.perf_counter() - started
    stages = [str(item.get("stage") or "") for item in events if item.get("stage")]
    remotion_events = [item for item in events if item.get("stage") == STAGE_ADVANCED_RENDER]
    encode_events = [item for item in events if item.get("stage") == STAGE_ENCODE]
    remotion_percents = []
    encode_percents = []
    for item in remotion_events:
        try:
            remotion_percents.append(float(item.get("percent")))
        except (TypeError, ValueError):
            pass
    for item in encode_events:
        try:
            encode_percents.append(float(item.get("percent")))
        except (TypeError, ValueError):
            pass
    # Fake mapping was Remotion occupying 0–65 of the whole job, or a cache
    # hit jumping the encode bar to 65%. Real Remotion passing through 65%
    # of its own stage is expected.
    remotion_hit_65 = any(
        abs(float(item.get("percent") or 0) - 65.0) < 0.05
        for item in remotion_events
        if item.get("percent") not in {None, ""}
    )
    encode_started_near_65 = bool(encode_percents) and encode_percents[0] >= 60.0
    fake_jump = encode_started_near_65 and not remotion_percents
    if remotion_hit_65 and remotion_percents and remotion_percents[0] < 50:
        # Passed through 65% after earlier remotion percents — real, not fake.
        fake_jump = False
    timings = {}
    for item in traces:
        if item.get("trace") == "advanced_timings" and isinstance(item.get("payload"), dict):
            timings = item["payload"]
    report = {
        "source": str(clip),
        "output": str(result),
        "output_size": result.stat().st_size if result.is_file() else 0,
        "output_duration": ffprobe_duration(result),
        "expected_duration": duration,
        "wall": wall,
        "stages_seen": stages,
        "unique_stages": list(dict.fromkeys(stages)),
        "required_stages": [
            STAGE_PREPARE_PROJECT, STAGE_PREPARE_SUBTITLES,
            STAGE_ADVANCED_RENDER, STAGE_ENCODE, STAGE_MUX,
        ],
        "remotion_event_count": len(remotion_events),
        "remotion_percent_min": min(remotion_percents) if remotion_percents else None,
        "remotion_percent_max": max(remotion_percents) if remotion_percents else None,
        "encode_percent_min": min(encode_percents) if encode_percents else None,
        "encode_percent_max": max(encode_percents) if encode_percents else None,
        "fake_65_jump": fake_jump,
        "cache": timings.get("overlay_cache"),
        "timings": timings,
        "event_count": len(events),
    }
    (OUT / "advanced-live-progress.json").write_text(
        json.dumps({"report": report, "events": events, "traces": traces}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("REPORT", json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    missing = [stage for stage in report["required_stages"] if stage not in report["unique_stages"]]
    if missing:
        raise SystemExit(f"missing stages: {missing}")
    if report["remotion_event_count"] <= 0:
        raise SystemExit("Remotion stage produced no progress events")
    if report["remotion_percent_max"] in {None, 0, 0.0}:
        raise SystemExit("Remotion stage stayed at 0%")
    if fake_jump:
        raise SystemExit("fake 65% mapping still present")
    if report["output_duration"] < duration * 0.85:
        raise SystemExit(f"output too short: {report['output_duration']}")
    print("P0-A OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
