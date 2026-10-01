from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from twobyteasr.advanced_renderer import AdvancedRendererBackend
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio_render import RenderJob, RenderSettings


def main() -> int:
    source = Path(sys.argv[1]).resolve()
    output = ROOT / "tmp" / f"p25-advanced-cyberpunk-{os.getpid()}.mp4"
    trace_path = ROOT / "tmp" / f"p25-advanced-cyberpunk-{os.getpid()}.jsonl"
    recipe = style_recipe_for_prompt("赛博朋克 Cyberpunk HUD 多层描边 glow glitch")
    project = SubtitleProject(
        media=StudioMedia(path=str(source), duration_ms=10_000, width=1920, height=1080),
        cues=[
            StudioCue(id="advanced-1", start_ms=0, end_ms=4_700, text="ADVANCED RENDER", style_id="cyberpunk"),
            StudioCue(id="advanced-2", start_ms=5_000, end_ms=10_000, text="赛博朋克字幕系统", style_id="cyberpunk"),
        ],
    )
    project.style_recipes["cyberpunk"] = recipe.to_dict()
    settings = RenderSettings(
        container="mp4", codec="h264", encoder="libx264", quality_mode="crf",
        quality=18, width=1920, height=1080, fps=30, audio_codec="none", preset="medium",
    )
    job = RenderJob(str(source), "", str(output), settings, start_seconds=0.0, duration_seconds=10.0)

    def trace(event: str, value: object = None, **fields: object) -> None:
        record = {"event": event, "value": value, **fields}
        with trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    result = AdvancedRendererBackend().render(
        project, ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe", job, trace=trace,
    )
    (ROOT / "tmp" / "p25-advanced-output.txt").write_text(str(result), encoding="utf-8")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
