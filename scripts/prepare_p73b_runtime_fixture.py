"""Create deterministic dense and normal projects for P7.3B headed acceptance."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)


OUTPUT = ROOT / "tmp" / "p73b" / "runtime-fixture"
REAL_FLV = Path(r"H:\record\Bilibili\Bilibili\企鹅带带北极熊\2026-08-23 19-50-33 狗熊：世界任务最后一部分.flv")
MEDIA = REAL_FLV if REAL_FLV.is_file() else ROOT / "tmp" / "p72" / "media" / "p72-6h.mp4"
MEDIA_DURATION_MS = 7_298_261 if MEDIA == REAL_FLV else 21_600_000


def project(count: int, name: str) -> Path:
    target_dir = OUTPUT / name
    target_dir.mkdir(parents=True, exist_ok=True)
    cues = [
        StudioCue(
            f"cue-{index:05d}",
            index * 500,
            index * 500 + 500,
            f"P7.3B subtitle {index:05d}",
            speaker_id="S00",
            style_id="default",
        )
        for index in range(count)
    ]
    payload = SubtitleProject(
        media=StudioMedia(
            str(MEDIA), display_name=MEDIA.name, duration_ms=MEDIA_DURATION_MS,
            width=2560 if MEDIA == REAL_FLV else 640,
            height=1440 if MEDIA == REAL_FLV else 360,
        ),
        cues=cues,
        speakers=[StudioSpeaker("S00", "Speaker", style_id="default", color="#47B8B2")],
        styles=[SubtitleStyle(
            "default", "P7.3B Default", font_family="Microsoft YaHei UI",
            font_size=58, outline_width=3, shadow=1, bold=True,
        )],
        render_settings={"play_res_x": 1920, "play_res_y": 1080},
        studio_state={"p73b_fixture": name},
    )
    payload.validate()
    return save_project(payload, target_dir / f"p73b-{name}.2byteproj")


def main() -> None:
    if not MEDIA.is_file():
        raise FileNotFoundError(MEDIA)
    dense = project(10_000, "dense")
    normal = project(200, "normal")
    manifest = {"dense": str(dense), "normal": str(normal), "media": str(MEDIA)}
    target = OUTPUT / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
