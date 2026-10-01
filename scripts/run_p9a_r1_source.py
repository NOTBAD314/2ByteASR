"""Source-mode debug runner for the P9A-R1 packaged audit logic."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "quick_start.py"
PYTHON = ROOT / ".venv-main" / "Scripts" / "python.exe"
SOURCE_PROJECT = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "2ByteASR"
    / "Projects"
    / "8月29日"
    / "8月29日.2byteproj"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=SOURCE_PROJECT)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "p9a-r1" / "runtime")
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)
    work = args.output.parent / "project"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    project_copy = work / args.project.name
    shutil.copy2(args.project, project_copy)

    env = dict(os.environ)
    env.update(
        {
            "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
            "TWOBYTEASR_NO_OPEN": "1",
            "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
            "TWOBYTEASR_STARTUP_PROJECT": str(project_copy),
            "TWOBYTEASR_P9A_R1_AUDIT": "1",
            "TWOBYTEASR_P9A_R1_OUTPUT": str(args.output),
        }
    )
    result_path = args.output / "runtime-result.json"
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(PYTHON), str(ENTRY)],
        cwd=str(ROOT),
        env=env,
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
        "phases": {
            name: {"ok": value.get("ok"), "error": value.get("error")}
            for name, value in payload.get("phases", {}).items()
        },
        "errors": payload.get("errors", []),
        "result": str(result_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
