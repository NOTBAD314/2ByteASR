"""Render the 10-second Native → Advanced → Native P25.3B acceptance clip."""

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
import os


PROJECT = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\[NOTBAD]雨之城前段9_2026.08.11-16.57.51\[NOTBAD]雨之城前段9_2026.08.11-16.57.51.2byteproj"
FFMPEG = WORKSPACE / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
OUTPUT_DIR = WORKSPACE / "tmp" / "p25.3b"
SCREENSHOT_DIR = WORKSPACE / "screenshots" / "p25.3b"


def main() -> None:
    project = load_project(PROJECT)
    project.media.duration_ms = 10_000
    project.media.width = 1920
    project.media.height = 1080
    native_style = project.styles[0].id
    advanced_id = "p25-3b-cyberpunk"
    approximation = copy.deepcopy(project.styles[0])
    approximation.id = advanced_id
    approximation.name = "Cyberpunk HUD · Advanced"
    approximation.primary_color = "#20D6E8"
    approximation.outline_color = "#090D12"
    approximation.outline_width = 6
    project.styles = [style for style in project.styles if style.id != advanced_id] + [approximation]
    recipe = style_recipe_for_prompt("赛博朋克 Cyberpunk HUD 多层描边 glow glitch")
    project.style_recipes[advanced_id] = recipe.to_dict()
    project.cues = [
        StudioCue("native-before", 0, 3_000, "NATIVE · 原生字幕开始", style_id=native_style),
        StudioCue("advanced", 3_000, 7_000, "ADVANCED · CYBERPUNK HUD", style_id=advanced_id),
        StudioCue("native-after", 7_000, 10_000, "NATIVE · 原生字幕结束", style_id=native_style),
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    project_path = save_project(project, OUTPUT_DIR / "mixed-native-advanced.2byteproj")
    native_ass = OUTPUT_DIR / "mixed-native-advanced.ass"
    native_ass.write_text(compile_ass(project), encoding="utf-8-sig")
    output = OUTPUT_DIR / "mixed-native-advanced.mp4"
    if output.exists():
        output.unlink()
    settings = RenderSettings(width=1280, height=720, fps=30.0, encoder="libx264", audio_codec="aac", quality=18)
    job = RenderJob(project.media.path, str(native_ass), str(output), settings, start_seconds=0.0, duration_seconds=10.0)
    events, progress_events = [], []
    AdvancedRendererBackend().render(
        project, FFMPEG, job,
        trace=lambda event, value: events.append({"event": event, "value": value}),
        progress=lambda payload: progress_events.append(dict(payload)),
    )
    native, advanced = split_renderer_cues(project)
    props = compile_composition_data(project, width=1280, height=720, fps=30, start_seconds=0, duration_seconds=10)
    frames = []
    for label, second in (("native-before", 1.5), ("advanced", 4.5), ("native-after", 8.5)):
        frame = SCREENSHOT_DIR / f"mixed-{label}.png"
        command = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(second), "-i", str(output), "-frames:v", "1", str(frame)]
        subprocess.run(command, check=True, **windows_subprocess_kwargs())
        frames.append(str(frame))
    report = {
        "project": str(project_path), "output": str(output), "size": output.stat().st_size,
        "nativeCueIds": [cue.id for cue in native], "advancedCueIds": [cue.id for cue in advanced],
        "overlayCueIds": [cue["id"] for cue in props["cues"]], "frames": frames,
        "progressPercents": sorted({round(float(item.get("out_time_ms", 0)) / 100_000) for item in progress_events}),
        "events": events,
    }
    (OUTPUT_DIR / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
