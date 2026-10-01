"""Create an isolated real-media project for the P7.4 quick-start audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)


PRIMARY_MEDIA = ROOT / "tmp" / "p72" / "media" / "p72-av-8s.mp4"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not PRIMARY_MEDIA.is_file():
        raise FileNotFoundError(PRIMARY_MEDIA)
    output.parent.mkdir(parents=True, exist_ok=True)
    (output.parent / "autosave").mkdir(exist_ok=True)
    project = SubtitleProject(
        media=StudioMedia(
            path=str(PRIMARY_MEDIA.resolve()),
            display_name=PRIMARY_MEDIA.name,
            duration_ms=8_000,
            fingerprint="p74-primary-real-av",
            width=1280,
            height=720,
        ),
        speakers=[
            StudioSpeaker("S00", "Host"),
            StudioSpeaker("S01", "Guest"),
        ],
        cues=[
            StudioCue("p74-1", 0, 2_000, "AIR PUNCH", speaker_id="S00"),
            StudioCue("p74-2", 2_000, 4_000, "P7.4 RUNTIME", speaker_id="S01"),
            StudioCue("p74-3", 4_000, 6_000, "VISUAL MOTION", speaker_id="S00"),
            StudioCue("p74-4", 6_000, 7_900, "RECOVERY READY", speaker_id="S01"),
        ],
    )
    project.validate()
    save_project(project, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
