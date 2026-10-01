"""Launch the rebuilt packaged app and wait for the P9A-R2 headed audit."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from twobyteasr.studio_project import project_from_runtime_cues, save_project


EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"


def _run_fixture_command(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr[-1200:] or "fixture generation failed")


def _synthetic_projects(work: Path, ffmpeg: Path) -> tuple[Path, Path]:
    """Create media/project fixtures containing no user subtitle or media data."""
    audio = work / "synthetic-audio-20m.m4a"
    video = work / "synthetic-video-b.mp4"
    _run_fixture_command([
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=1200,volume=0.01",
        "-c:a", "aac", "-b:a", "64k", str(audio),
    ])
    _run_fixture_command([
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=0x263044:s=1280x720:r=30:d=12",
        "-f", "lavfi", "-i",
        "sine=frequency=660:sample_rate=48000:duration=12,volume=0.01",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "64k", str(video),
    ])

    cue_a = SimpleNamespace(
        cue_id="synthetic-a-1", speaker="SYNTH-A", start=0.0, end=10.0,
        text="SHADOW TEST — SYNTHETIC AUDIO PROJECT A",
    )
    cue_b = SimpleNamespace(
        cue_id="synthetic-b-1", speaker="SYNTH-B", start=0.0, end=10.0,
        text="PROVIDER TEST — SYNTHETIC VIDEO PROJECT B",
    )
    project_a = project_from_runtime_cues(
        audio, [cue_a],
        media_identity={
            "source_path": str(audio), "duration_ms": 1_200_000,
            "has_video": False, "has_audio": True,
            "audio_codec": "aac", "sample_rate": 48_000, "channels": 1,
        },
    )
    project_b = project_from_runtime_cues(
        video, [cue_b],
        media_identity={
            "source_path": str(video), "duration_ms": 12_000,
            "has_video": True, "has_audio": True, "video_codec": "h264",
            "width": 1280, "height": 720, "fps": 30.0,
            "audio_codec": "aac", "sample_rate": 48_000, "channels": 1,
        },
    )
    project_a_path = save_project(project_a, work / "synthetic-A.2byteproj")
    project_b_path = save_project(project_b, work / "synthetic-B.2byteproj")
    return project_a_path, project_b_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=EXE)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "p9a-r2" / "runtime")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--only-providers", action="store_true")
    args = parser.parse_args()
    if not args.exe.is_file():
        raise FileNotFoundError(args.exe)
    ffmpeg = args.exe.parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if not ffmpeg.is_file():
        raise FileNotFoundError(ffmpeg)

    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    work = output.parent / "project"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    project_a, project_b = _synthetic_projects(work, ffmpeg)
    if args.prepare_only:
        print(json.dumps({
            "project_a": str(project_a),
            "project_b": str(project_b),
            "audio_size": (work / "synthetic-audio-20m.m4a").stat().st_size,
            "video_size": (work / "synthetic-video-b.mp4").stat().st_size,
        }, ensure_ascii=False, indent=2))
        return 0

    path_items = [item for item in str(os.environ.get("PATH") or "").split(os.pathsep) if item]
    host_environment = {
        "agy_executable": shutil.which("agy") or shutil.which("agy.exe") or "",
        "cwd": str(Path.cwd()),
        "HOME": str(os.environ.get("HOME") or ""),
        "USERPROFILE": str(os.environ.get("USERPROFILE") or ""),
        "LOCALAPPDATA": str(os.environ.get("LOCALAPPDATA") or ""),
        "PATH_entry_count": len(path_items),
        "PATH_head": path_items[:8],
    }

    env = dict(os.environ)
    env.update({
        "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
        "TWOBYTEASR_STARTUP_PROJECT": str(project_a),
        "TWOBYTEASR_P9A_R2_AUDIT": "1",
        "TWOBYTEASR_P9A_R2_OUTPUT": str(output),
        "TWOBYTEASR_P9A_R2_PROJECT_B": str(project_b),
        "TWOBYTEASR_P9A_R2_HOST_ENV": json.dumps(host_environment, ensure_ascii=False),
    })
    if args.only_providers:
        env["TWOBYTEASR_P9A_R2_ONLY_PROVIDERS"] = "1"
    result_path = output / "runtime-result.json"
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(args.exe)],
        cwd=str(args.exe.parent),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    payload: dict = {}
    deadline = time.time() + max(30.0, float(args.timeout))
    while time.time() < deadline:
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            if "accepted" in payload:
                break
        if process.poll() is not None:
            break
        time.sleep(0.3)
    if process.poll() is None:
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
    summary = {
        "exit_code": process.returncode,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "accepted": payload.get("accepted"),
        "checks": payload.get("checks", {}),
        "phases": {
            name: {"ok": phase.get("ok"), "error": phase.get("error")}
            for name, phase in payload.get("phases", {}).items()
        },
        "errors": payload.get("errors", []),
        "result": str(result_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if payload.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
