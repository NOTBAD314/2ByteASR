"""Headed Recognition → Studio attach and non-black pixel gate.

This launches the real desktop app (source-dev or packaged) with a
Recognition-produced project. It is automated evidence, not user acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V1 = ROOT / "tmp" / "p74b" / "headed-fixture-media" / "v1-blue-grid.mp4"
V2 = ROOT / "tmp" / "p74b" / "headed-fixture-media" / "v2-magenta-motion.mp4"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--media", type=Path, default=V1)
    parser.add_argument("--second-media", type=Path, default=V2)
    parser.add_argument("--project", type=Path)
    return parser.parse_args()


def _prepare_project(media: Path, output_dir: Path) -> Path:
    from twobyteasr.models import SubtitleCue
    from twobyteasr.studio_project import create_studio_outputs, load_project

    output_dir.mkdir(parents=True, exist_ok=True)
    txt = output_dir / f"{media.stem}.txt"
    txt.write_text("P7.4C recognition fixture\n", encoding="utf-8")
    project_path = output_dir / media.stem / f"{media.stem}.2byteproj"
    outputs = create_studio_outputs(
        str(media.resolve()),
        [
            SubtitleCue(1, 0.4, 2.4, "P74C SUBTITLE FOREGROUND", speaker="S01"),
            SubtitleCue(2, 2.6, 4.2, "Recognition to Studio", speaker="S01"),
        ],
        txt_path=str(txt),
        target_project_path=str(project_path),
        generation_metadata={
            "created_by": "2ByteASR recognition pipeline",
            "recognition_purpose": "final",
            "p74c_fixture": True,
        },
    )
    project = load_project(outputs["project"])
    if project.media_pool[0].duration_ms <= 0:
        raise RuntimeError("create_studio_outputs produced MediaAsset duration 0")
    return Path(outputs["project"])


def main() -> int:
    args = _arguments()
    run = args.output or ROOT / "tmp" / "p74c" / (
        "real-media-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    run = run.resolve()
    run.mkdir(parents=True, exist_ok=False)
    local = run / "localappdata"
    local.mkdir()
    os.environ["LOCALAPPDATA"] = str(local)
    project_path = (
        args.project.resolve()
        if args.project
        else _prepare_project(args.media, run / "project")
    )

    env = dict(os.environ)
    env.update({
        "LOCALAPPDATA": str(local),
        "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
        "TWOBYTEASR_STARTUP_PROJECT": str(project_path),
        "TWOBYTEASR_P74C_RUNTIME_AUDIT": "1",
        "TWOBYTEASR_P74C_RUNTIME_OUTPUT": str(run),
        "TWOBYTEASR_P74C_SECOND_MEDIA": str(args.second_media.resolve()) if args.second_media else "",
        "TWOBYTEASR_CHILD_PROCESS_LOG": str(run / "children.jsonl"),
        "TWOBYTEASR_NO_OPEN": "1",
    })
    env.pop("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", None)
    if args.exe:
        command = [str(args.exe.resolve())]
        cwd = str(args.exe.resolve().parent)
        env["TWOBYTEASR_LAUNCH_MODE"] = "packaged"
    else:
        python = ROOT / ".venv-main" / "Scripts" / "python.exe"
        command = [str(python), str(ROOT / "quick_start.py")]
        cwd = str(ROOT)
        env["TWOBYTEASR_LAUNCH_MODE"] = "source-dev"

    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, env=env, timeout=180)
    result_path = run / "runtime-result.json"
    payload = {}
    if result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    summary = {
        "exit_code": completed.returncode,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "command": command,
        "project": str(project_path),
        "accepted": bool(payload.get("accepted")),
        "checks": payload.get("checks", {}),
        "errors": payload.get("errors", []),
        "process": payload.get("process", {}),
        "result_path": str(result_path),
    }
    (run / "harness-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] and completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
