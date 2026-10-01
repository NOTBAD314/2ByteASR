"""Create the real two-video fixture used by the P7.4B headed audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    create_video_track,
    set_audio_master_track,
    update_video_clip_transform,
)
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)
from twobyteasr.style_presets import StylePresetStore


V1 = ROOT / "tmp" / "p74b" / "headed-fixture-media" / "v1-blue-grid.mp4"
V2 = ROOT / "tmp" / "p74b" / "headed-fixture-media" / "v2-magenta-motion.mp4"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for path in (V1, V2):
        if not path.is_file():
            raise FileNotFoundError(path)

    polar_bear = SubtitleStyle(
        "polar-bear", "北极熊",
        font_family="Microsoft YaHei UI", font_size=72,
        primary_color="#FFFFFF", outline_color="#000000",
        outline_width=15, shadow=0, bold=True,
        alignment=2, position_x=960, position_y=900,
    )
    StylePresetStore().upsert(polar_bear)
    project = SubtitleProject(
        media=StudioMedia(
            path=str(V1.resolve()), display_name=V1.name,
            duration_ms=8_000, fingerprint="p74b-v1-blue-grid",
            width=1280, height=720,
        ),
        speakers=[
            StudioSpeaker("S01", "Host"),
            StudioSpeaker("S02", "Guest"),
        ],
        styles=[polar_bear],
        cues=[
            StudioCue(
                "p74b-cue", 0, 7_900, "P7.4B SUBTITLE FOREGROUND",
                speaker_id="S01", style_id="polar-bear",
                base_preset_id="polar-bear",
            ),
            StudioCue(
                "p74b-cue-s02", 7_900, 8_000, "S02 LANE SENTINEL",
                speaker_id="S02", style_id="polar-bear",
                base_preset_id="polar-bear",
            ),
        ],
        render_settings={"play_res_x": 1920, "play_res_y": 1080},
    )
    project.validate()
    project.video_tracks[0].locked = False
    asset = add_media_asset(
        project, V2.resolve(), fingerprint="p74b-v2-magenta-motion",
        duration_ms=8_000,
        video_metadata={"width": 640, "height": 360, "fps": 30.0},
        audio_metadata={"has_audio": True},
    )
    track = create_video_track(project, "Picture in picture")
    clip = add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=0)
    update_video_clip_transform(project, track.id, clip.id, {
        "position_x": 0.76,
        "position_y": 0.24,
        "scale_x": 0.44,
        "scale_y": 0.44,
        "rotation": 0.0,
        "opacity": 1.0,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
        "fit_mode": "contain",
    })
    set_audio_master_track(project, "V1")
    project.validate()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    save_project(project, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
