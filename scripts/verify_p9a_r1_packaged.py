"""Drive the P9A-R1 packaged audit against one exact rebuilt 2ByteASR.exe."""

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

from twobyteasr.media_ingest import probe_media_identity
from twobyteasr.studio_project import project_from_runtime_cues, save_project

EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"
SOURCE_PROJECT = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "2ByteASR"
    / "Projects"
    / "8月29日"
    / "8月29日.2byteproj"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=EXE)
    parser.add_argument("--project", type=Path, default=SOURCE_PROJECT)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "p9a-r1" / "runtime")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--localappdata", type=Path)
    parser.add_argument("--audio-target", type=float)
    parser.add_argument("--config-phase", choices=("save", "reopen"))
    args = parser.parse_args()
    args.exe = args.exe.resolve()
    args.output = args.output.resolve()
    if args.localappdata is not None:
        args.localappdata = args.localappdata.resolve()

    if not args.exe.is_file():
        raise FileNotFoundError(args.exe)
    if args.output.exists():
        shutil.rmtree(args.output)
    project_copy = None
    if not args.config_phase:
        work = args.output.parent / "project"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        if args.media is not None:
            if not args.media.is_file():
                raise FileNotFoundError(args.media)
            identity = probe_media_identity(args.media)
            target = max(0.0, float(args.audio_target or 0.0))
            cue = SimpleNamespace(
                cue_id="p9a-r5-seek-cue",
                speaker="P9A-R5",
                start=max(0.0, target - 5.0),
                end=min(float(identity.get("duration_ms") or 0) / 1000.0, target + 15.0),
                text="P9A-R5 PACKAGED AUDIO SEEK",
            )
            project = project_from_runtime_cues(
                args.media.resolve(), [cue], media_identity=dict(identity)
            )
            project_copy = save_project(project, work / f"{args.media.stem}.2byteproj")
        else:
            if not args.project.is_file():
                raise FileNotFoundError(args.project)
            project_copy = work / args.project.name
            shutil.copy2(args.project, project_copy)

    env = dict(os.environ)
    env.update({
        "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_P9A_R1_AUDIT": "1",
        "TWOBYTEASR_P9A_R1_OUTPUT": str(args.output),
    })
    if project_copy is not None:
        env.update({
            "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
            "TWOBYTEASR_STARTUP_PROJECT": str(project_copy),
        })
    if args.localappdata is not None:
        args.localappdata.mkdir(parents=True, exist_ok=True)
        env["LOCALAPPDATA"] = str(args.localappdata.resolve())
    if args.audio_target is not None:
        env["TWOBYTEASR_P9A_R5_AUDIO_TARGET_SECONDS"] = str(args.audio_target)
    if args.config_phase:
        env["TWOBYTEASR_P9A_R5_CONFIG_PHASE"] = args.config_phase
        # P9A audit hooks are registered by the instrumented startup branch.
        # Config-only runs do not open a Studio project, so explicitly enter
        # that branch without changing the visible page selection.
        env["TWOBYTEASR_STARTUP_RAISE"] = "1"
    extra_skip = os.environ.get("TWOBYTEASR_P9A_R1_SKIP", "")
    if extra_skip:
        env["TWOBYTEASR_P9A_R1_SKIP"] = extra_skip
    result_path = args.output / "runtime-result.json"
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(args.exe)],
        cwd=str(args.exe.parent),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    payload: dict = {}
    deadline = time.time() + args.timeout
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
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
    print(json.dumps({
        "exit_code": process.returncode,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "accepted": payload.get("accepted"),
        "checks": payload.get("checks", {}),
        "errors": payload.get("errors", []),
        "result": str(result_path),
    }, ensure_ascii=False, indent=2))
    return 0 if payload.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
