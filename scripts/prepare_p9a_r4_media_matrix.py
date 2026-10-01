"""Create comparable MP4/FLV legacy-project fixtures for P9A-R4 audits."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project


def _run(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr[-2000:] or "fixture generation failed")


def _project(media: Path, *, duration_ms: int, output: Path) -> Path:
    project = SubtitleProject(
        media=StudioMedia(
            path=str(media.resolve()),
            display_name=media.name,
            duration_ms=duration_ms,
            width=640,
            height=360,
        ),
        cues=[StudioCue("p9a-r4-cue", 500, 4_500, "P9A-R4 HOLD PIXEL TEST")],
    )
    project.validate()
    return save_project(project, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tmp" / "p9a-r4" / "media-matrix",
    )
    parser.add_argument(
        "--ffmpeg",
        type=Path,
        default=ROOT / "dist" / "2ByteASR" / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
    )
    parser.add_argument("--duration", type=int, default=90)
    args = parser.parse_args()
    if not args.ffmpeg.is_file():
        raise FileNotFoundError(args.ffmpeg)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    duration = max(30, int(args.duration))
    mp4 = output / "p9a-r4-legacy.mp4"
    flv = output / "p9a-r4-legacy.flv"
    common = [
        str(args.ffmpeg.resolve()), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=0x263044:s=640x360:r=25:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=523:sample_rate=48000:duration={duration},volume=0.01",
        "-shortest",
    ]
    _run(common + [
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", str(mp4),
    ])
    _run(common + [
        "-c:v", "flv1", "-c:a", "aac", "-b:a", "64k", "-f", "flv", str(flv),
    ])
    duration_ms = duration * 1000
    mp4_project = _project(
        mp4, duration_ms=duration_ms,
        output=output / "p9a-r4-legacy-mp4.2byteproj",
    )
    flv_project = _project(
        flv, duration_ms=duration_ms,
        output=output / "p9a-r4-legacy-flv.2byteproj",
    )
    payload = {
        "duration_seconds": duration,
        "mp4": str(mp4),
        "flv": str(flv),
        "mp4_project": str(mp4_project),
        "flv_project": str(flv_project),
        "mp4_bytes": mp4.stat().st_size,
        "flv_bytes": flv.stat().st_size,
    }
    (output / "fixtures.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
