"""Create a Recognition-produced Studio project from a real MP4.

This goes through ``create_studio_outputs`` — the same function the ASR
pipeline uses — and never constructs a ``MediaAsset`` in the caller.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.models import SubtitleCue
from twobyteasr.studio_project import create_studio_outputs, load_project


V1 = ROOT / "tmp" / "p74b" / "headed-fixture-media" / "v1-blue-grid.mp4"
V2 = ROOT / "tmp" / "p74b" / "headed-fixture-media" / "v2-magenta-motion.mp4"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path, default=V1)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    media = args.media.resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    txt = output_dir / f"{media.stem}.txt"
    txt.write_text("P7.4C recognition fixture\n", encoding="utf-8")
    cues = [
        SubtitleCue(1, 0.4, 2.4, "P74C SUBTITLE FOREGROUND", speaker="S01"),
        SubtitleCue(2, 2.6, 4.2, "Recognition to Studio", speaker="S01"),
    ]
    project_path = output_dir / media.stem / f"{media.stem}.2byteproj"
    outputs = create_studio_outputs(
        str(media),
        cues,
        txt_path=str(txt),
        target_project_path=str(project_path),
        generation_metadata={
            "created_by": "2ByteASR recognition pipeline",
            "recognition_purpose": "final",
            "p74c_fixture": True,
        },
    )
    project = load_project(outputs["project"])
    asset = project.media_pool[0]
    clip = project.video_tracks[0].clips[0]
    print(outputs["project"])
    print(f"duration_ms={asset.duration_ms}")
    print(f"clip_out_ms={clip.timeline_out_ms}")
    print(f"source={asset.canonical_source}")
    if asset.duration_ms <= 0 or clip.timeline_out_ms <= 0:
        raise SystemExit("recognition fixture produced a zero-duration MediaAsset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
