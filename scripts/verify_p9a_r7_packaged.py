"""Launch the exact frozen executable for the P9A-R7 long-media audit."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"
PROJECT = ROOT / "tmp" / "p9a-r6" / "real-flv" / "real-flv.2byteproj"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=EXE)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--localappdata", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()
    exe = args.exe.resolve()
    project = args.project.resolve()
    output = args.output.resolve()
    localappdata = args.localappdata.resolve()
    for label, path in (("packaged executable", exe), ("project", project)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} missing: {path}")
    if output.exists():
        raise FileExistsError(f"audit output already exists: {output}")
    output.mkdir(parents=True)
    localappdata.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.update(
        {
            "LOCALAPPDATA": str(localappdata),
            "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
            "TWOBYTEASR_NO_OPEN": "1",
            "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
            "TWOBYTEASR_STARTUP_PROJECT": str(project),
            "TWOBYTEASR_P9A_R7_AUDIT": "1",
            "TWOBYTEASR_P9A_R7_OUTPUT": str(output),
            "TWOBYTEASR_DEBUG_STUDIO": "1",
        }
    )
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    result_path = output / "runtime-result.json"
    payload: dict = {}
    deadline = time.time() + float(args.timeout)
    while time.time() < deadline:
        if result_path.is_file():
            try:
                value = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                value = {}
            if isinstance(value, dict):
                payload = value
            if "accepted" in payload:
                break
        if process.poll() is not None:
            break
        time.sleep(0.25)
    if process.poll() is None:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
    if not payload and result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    summary = {
        "exe": str(exe),
        "project": str(project),
        "output": str(result_path),
        "localappdata": str(localappdata),
        "exit_code": process.returncode,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "accepted": bool(payload.get("accepted")),
        "checks": payload.get("checks", {}),
        "startup": payload.get("startup", {}),
        "seek_targets": [
            row.get("target_seconds")
            for row in payload.get("phases", {}).get("real_flv", {}).get("seeks", [])
        ],
        "system_sample_count": len(payload.get("system_samples", [])),
        "errors": payload.get("errors", []),
        "build_identity": payload.get("build_identity", {}),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
