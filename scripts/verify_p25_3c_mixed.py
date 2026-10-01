"""Render the 20-second Native/Cyber/Gaming/Neon P25.3C acceptance clip."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from twobyteasr.advanced_renderer import AdvancedRendererBackend, compile_composition_data, split_renderer_cues
from twobyteasr.ass_compiler import compile_ass
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.studio_project import StudioCue, load_project, save_project
from twobyteasr.studio_render import RenderJob, RenderSettings, windows_subprocess_kwargs
from twobyteasr.visual_snapshot import build_visual_cue_snapshot
import os


PROJECT = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\[NOTBAD]雨之城前段9_2026.08.11-16.57.51\[NOTBAD]雨之城前段9_2026.08.11-16.57.51.2byteproj"
FFMPEG = WORKSPACE / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
OUTPUT_DIR = WORKSPACE / "tmp" / "p25.3c"
SCREENSHOT_DIR = WORKSPACE / "screenshots" / "p25.3c"


def main() -> None:
    project = load_project(PROJECT)
    project.media.duration_ms = 20_000
    project.media.width, project.media.height = 1920, 1080
    project.render_settings.update({"play_res_x": 1920, "play_res_y": 1080})
    native_style = project.styles[0].id
    advanced_specs = (
        ("p25-3c-cyber", "Cyberpunk HUD", 760, 875, 105),
        ("p25-3c-gaming", "Gaming Impact", 960, 780, 118),
        ("p25-3c-neon", "Soft Neon", 1120, 900, 92),
    )
    for style_id, prompt, x, y, scale in advanced_specs:
        style = copy.deepcopy(project.styles[0])
        recipe = style_recipe_for_prompt(prompt)
        style.id, style.name = style_id, recipe.name
        style.font_family = str(recipe.typography.get("fontFamily") or style.font_family)
        style.font_size = float(recipe.typography.get("fontSize") or style.font_size)
        style.position_x, style.position_y = x, y
        style.scale_x = style.scale_y = scale
        project.styles = [item for item in project.styles if item.id != style_id] + [style]
        project.style_recipes[style_id] = recipe.to_dict()
    project.cues = [
        StudioCue("native-before", 0, 4_000, "NATIVE · 原生字幕", style_id=native_style),
        StudioCue("cyber", 4_000, 8_000, "CYBERPUNK · 数据接入", style_id="p25-3c-cyber"),
        StudioCue("gaming", 8_000, 12_000, "GAMING IMPACT!", style_id="p25-3c-gaming"),
        StudioCue("neon", 12_000, 16_000, "Soft Neon · 柔光时刻", style_id="p25-3c-neon"),
        StudioCue("native-after", 16_000, 20_000, "NATIVE · 安全返回", style_id=native_style),
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    project_path = save_project(project, OUTPUT_DIR / "mixed-authoritative-visuals.2byteproj")
    native_ass = OUTPUT_DIR / "mixed-authoritative-visuals.ass"
    native_ass.write_text(compile_ass(project), encoding="utf-8-sig")
    output = OUTPUT_DIR / "mixed-authoritative-visuals.mp4"
    output.unlink(missing_ok=True)
    settings = RenderSettings(width=1280, height=720, fps=30.0, encoder="libx264", audio_codec="aac", quality=18)
    job = RenderJob(project.media.path, str(native_ass), str(output), settings, start_seconds=0, duration_seconds=20)
    events, progress_events = [], []
    AdvancedRendererBackend().render(
        project, FFMPEG, job,
        trace=lambda event, value: events.append({"event": event, "value": value}),
        progress=lambda payload: progress_events.append(dict(payload)),
    )
    native, advanced = split_renderer_cues(project)
    props = compile_composition_data(project, width=1280, height=720, fps=30, start_seconds=0, duration_seconds=20)
    frames = []
    for label, second in (("native-before", 2), ("cyber", 6), ("gaming", 10), ("neon", 14), ("native-after", 18)):
        frame = SCREENSHOT_DIR / f"mixed-{label}.png"
        subprocess.run(
            [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(second),
             "-i", str(output), "-frames:v", "1", str(frame)],
            check=True, **windows_subprocess_kwargs(),
        )
        frames.append(str(frame))
    snapshots = {
        cue.id: {
            "hash": (snapshot := build_visual_cue_snapshot(project, cue.id, width=1280, height=720)).stable_hash(),
            "text": snapshot.text,
            "position": [snapshot.position_x, snapshot.position_y],
            "scale": [snapshot.scale_x, snapshot.scale_y],
            "motion": snapshot.motion_recipe,
        }
        for cue in advanced
    }
    report = {
        "project": str(project_path), "output": str(output), "size": output.stat().st_size,
        "nativeCueIds": [cue.id for cue in native], "advancedCueIds": [cue.id for cue in advanced],
        "overlayCueIds": [cue["id"] for cue in props["cues"]], "frames": frames,
        "snapshots": snapshots, "progressEventCount": len(progress_events), "events": events,
    }
    report_path = OUTPUT_DIR / "acceptance.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
