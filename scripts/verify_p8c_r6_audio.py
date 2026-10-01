"""Run the R6 audio-only clock/subtitle trace against the current project.

This is automated real-widget evidence. It never represents a person's
acceptance and never changes the source project.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = Path(
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\8月29日\8月29日.2byteproj"
)
DEFAULT_EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("source", "packaged"), default="source")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=170.0)
    parser.add_argument("--trace-seconds", type=int, default=60)
    return parser.parse_args()


def _owned_rows(root: psutil.Process) -> list[dict[str, object]]:
    rows = []
    for process in (root, *root.children(recursive=True)):
        try:
            rows.append({
                "pid": process.pid,
                "ppid": process.ppid(),
                "name": process.name(),
                "executable": process.exe(),
                "command_line": process.cmdline(),
                "creation_time": process.create_time(),
            })
        except (psutil.Error, OSError):
            pass
    return rows


def main() -> int:
    args = _args()
    project = args.project.resolve()
    exe = args.exe.resolve()
    if not project.is_file():
        raise FileNotFoundError(project)
    if args.mode == "packaged" and not exe.is_file():
        raise FileNotFoundError(exe)
    output = (args.output or ROOT / "tmp" / "p8c-r6-audio" / time.strftime("%Y%m%d-%H%M%S")).resolve()
    output.mkdir(parents=True, exist_ok=False)
    profile = output / "localappdata"
    profile.mkdir()
    result_path = output / "runtime-result.json"
    env = dict(os.environ)
    env.update({
        "LOCALAPPDATA": str(profile),
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
        "TWOBYTEASR_STARTUP_PROJECT": str(project),
        "TWOBYTEASR_P8C_RUNTIME_AUDIT": "r6_audio",
        "TWOBYTEASR_P8C_RUNTIME_OUTPUT": str(output),
        "TWOBYTEASR_LAUNCH_MODE": args.mode,
        "P8C_R6_AUDIO_TRACE_SECONDS": str(max(1, int(args.trace_seconds))),
    })
    if args.mode == "packaged":
        command = [str(exe)]
        cwd = exe.parent
    else:
        command = [str(ROOT / ".venv-main" / "Scripts" / "python.exe"), "-B", str(ROOT / "quick_start.py")]
        cwd = ROOT
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    root_process = psutil.Process(process.pid)
    deadline = time.time() + max(10.0, float(args.timeout))
    payload: dict[str, object] = {}
    while time.time() < deadline:
        if result_path.is_file():
            try:
                value = json.loads(result_path.read_text(encoding="utf-8"))
                payload = value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                payload = {}
        if payload.get("accepted") is not None:
            break
        if process.poll() is not None:
            break
        time.sleep(0.25)
    rows = _owned_rows(root_process)
    if process.poll() is None:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
    residual = []
    for row in rows:
        try:
            child = psutil.Process(int(row["pid"]))
            if child.is_running() and abs(child.create_time() - float(row["creation_time"])) < 0.01:
                residual.append(row)
        except (psutil.Error, OSError, KeyError, TypeError, ValueError):
            pass
    # Only terminate descendants proven to belong to this launch.
    for row in reversed(residual):
        try:
            child = psutil.Process(int(row["pid"]))
            child.terminate()
        except (psutil.Error, OSError):
            pass
    payload.update({
        "launch": {
            "mode": args.mode,
            "command": command,
            "project": str(project),
            "exe": str(exe) if args.mode == "packaged" else "",
            "exit_code": process.returncode,
            "result_path": str(result_path),
            "processes": rows,
            "residual_processes": residual,
            "real_user_click": False,
        },
    })
    summary_path = output / "r6-audio-summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "accepted": bool(payload.get("accepted")),
        "checks": payload.get("checks", {}),
        "audio_r6": payload.get("phases", {}).get("audio_r6", {}),
        "summary": str(summary_path),
    }, ensure_ascii=False, indent=2))
    return 0 if payload.get("accepted") else 2


if __name__ == "__main__":
    raise SystemExit(main())
