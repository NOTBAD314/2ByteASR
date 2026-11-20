"""Time video exports per route on synthetic 1080p sources (2026-11-19).

Usage (repository root):
  python -X utf8 scripts/benchmark_export_routes.py [--seconds 20] [--fps 60]
      [--encoder h264_nvenc|libx264] [--scenario pip,pip-raster,chroma] [--repeat 1]

Writes one JSON line per run (wall seconds, real-time factor, route and the
raster pass's own timing counters) to stdout and tmp/bench-export/results.jsonl.
Sources are cached under tmp/bench-export; nothing touches user data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FFMPEG = ROOT / "tools/ffmpeg/bin/ffmpeg.exe"
WORK = ROOT / "tmp/bench-export"
TIMELINE = False


def source(name, pattern, seconds, fps, size="1920x1080"):
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"{name}-{size}-{fps}-{seconds}.mp4"
    if not path.is_file():
        from twobyteasr.system.processes import run_hidden_subprocess
        run_hidden_subprocess([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i",
                               f"{pattern}=s={size}:r={fps}:d={seconds}", "-f", "lavfi", "-i",
                               f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-preset", "veryfast",
                               "-g", str(fps*2), "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                              purpose="export benchmark source", check=True, timeout=600)
    return path


def build(scenario, seconds, fps):
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, VideoTransform
    from twobyteasr.timeline.studio_media_pool import add_media_asset, add_video_clip, create_video_track
    base = source("base", "testsrc2", seconds, fps)
    project = SubtitleProject(media=StudioMedia(path=str(base), duration_ms=seconds*1000, width=1920, height=1080))
    project.validate()
    layer = source("layer", "smptehdbars", seconds, fps)
    asset = add_media_asset(project, layer, duration_ms=seconds*1000,
                            video_metadata={"width": 1920, "height": 1080, "has_video": True, "fps": fps},
                            audio_metadata={"has_audio": False})
    track = create_video_track(project, "V2")
    clip = add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=0)
    clip.transform = VideoTransform(scale_x=.35, scale_y=.35, position_x=.78, position_y=.76)
    if scenario == "chroma":
        clip.effects = {"chromaKey": {"enabled": True, "color": "#00FF00", "similarity": .2,
                                      "smoothness": .1, "spillSuppression": True}}
    return project


def run(scenario, seconds, fps, encoder):
    from twobyteasr.exports import export_filtergraph, export_run_log
    from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.rendering.ass_compiler import compile_ass
    project = build(scenario, seconds, fps)
    ass = WORK / "empty.ass"
    ass.write_text(compile_ass(project), encoding="utf-8-sig")
    output = WORK / f"out-{scenario}.mp4"
    output.unlink(missing_ok=True)
    job = RenderJob(str(project.media.path), str(ass), str(output),
                    RenderSettings(container="mp4", encoder=encoder, preset="p4" if "nvenc" in encoder else "veryfast",
                                   audio_codec="aac", fps=fps),
                    video_graph=capture_video_graph(project), overwrite_existing=True)
    notes = {}
    timeline = []
    original_note = export_run_log.note_export
    def note(key, value):
        notes.setdefault(key, value)
        timeline.append((round(time.perf_counter() - started, 2), key,
                         value.get('name') or value.get('route') or value.get('path') or ''
                         if isinstance(value, dict) else ''))
        return original_note(key, value)
    export_run_log.note_export = note
    original_gate = export_filtergraph.simple_video_clips
    if scenario.endswith("-raster"):
        export_filtergraph.simple_video_clips = lambda graph: None
    started = time.perf_counter()
    try:
        run_render_job(FFMPEG, job)
        wall = time.perf_counter() - started
    finally:
        export_run_log.note_export = original_note
        export_filtergraph.simple_video_clips = original_gate
    return dict(scenario=scenario, encoder=encoder, seconds=seconds, fps=fps, wall_seconds=round(wall, 2),
                realtime_factor=round(seconds / wall, 2), route=(notes.get("export_route") or {}).get("route"),
                raster=notes.get("video_composition_timings"),
                timeline=[row for row in timeline if row[1] not in {'progress'}] if TIMELINE else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--encoder", default="h264_nvenc")
    parser.add_argument("--scenario", default="pip,pip-raster,chroma")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--label", default="")
    parser.add_argument("--source", default="", help="import twobyteasr from another checkout (A/B timing)")
    parser.add_argument("--timeline", action="store_true", help="include every run-log note with its time offset")
    args = parser.parse_args()
    global TIMELINE
    TIMELINE = args.timeline
    if args.source:
        sys.path.insert(0, str(Path(args.source).resolve()))
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    for _ in range(args.repeat):
        for scenario in args.scenario.split(","):
            row = dict(run(scenario, args.seconds, args.fps, args.encoder), label=args.label)
            line = json.dumps(row, ensure_ascii=False, default=str)
            print(line, flush=True)
            with (WORK / "results.jsonl").open("a", encoding="utf8") as handle:
                handle.write(line + "\n")
    del app


if __name__ == "__main__":
    main()
