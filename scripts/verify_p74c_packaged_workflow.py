"""Packaged 2ByteASR.exe Recognition → Studio workflow plus process identity."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exe",
        type=Path,
        default=ROOT / "dist" / "2ByteASR" / "2ByteASR.exe",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    exe = args.exe.resolve()
    if not exe.is_file():
        raise FileNotFoundError(exe)
    run = (args.output or ROOT / "tmp" / "p74c" / (
        "packaged-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )).resolve()
    python = ROOT / ".venv-main" / "Scripts" / "python.exe"
    completed = subprocess.run(
        [
            str(python if python.is_file() else sys.executable),
            str(ROOT / "scripts" / "verify_p74c_real_media.py"),
            "--exe",
            str(exe),
            "--output",
            str(run),
        ],
        cwd=str(ROOT),
    )
    summary_path = run / "harness-summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    process = payload.get("process") or {}
    image = str(process.get("image_name") or "")
    identity = {
        "exe": str(exe),
        "image_name": image,
        "frozen": process.get("frozen"),
        "image_is_2byteasr": image.lower() == "2byteasr.exe",
        "not_python": "python" not in image.lower(),
        "headed_exit": completed.returncode,
        "accepted": bool(payload.get("accepted")),
    }
    run.mkdir(parents=True, exist_ok=True)
    (run / "process-identity.json").write_text(
        json.dumps(identity, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(identity, indent=2))
    return 0 if completed.returncode == 0 and identity["image_is_2byteasr"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
