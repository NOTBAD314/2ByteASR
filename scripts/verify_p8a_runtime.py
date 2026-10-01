"""P8A headed + path-parity verification.

Source mode is the debug path. Packaged EXE is the product path when the
current tree has been rebuilt into dist\\2ByteASR\\2ByteASR.exe.
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
V2_REAL = ROOT / "tmp" / "[NOTBAD]雨之城前段9_2026.08.11-16.57.51_成片.mp4"
V2_FALLBACK = ROOT / "tmp" / "p53-accept" / "clips" / "native-30s.mp4"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--media", type=Path, default=V1)
    parser.add_argument("--second-media", type=Path)
    parser.add_argument("--project", type=Path)
    return parser.parse_args()


def _second_media(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    if V2_REAL.is_file():
        return V2_REAL
    return V2_FALLBACK


def _prepare_project(media: Path, output_dir: Path) -> Path:
    from twobyteasr.models import SubtitleCue
    from twobyteasr.studio_project import create_studio_outputs, load_project

    output_dir.mkdir(parents=True, exist_ok=True)
    txt = output_dir / f"{media.stem}.txt"
    txt.write_text("P8A true multi-track fixture\n", encoding="utf-8")
    project_path = output_dir / media.stem / f"{media.stem}.2byteproj"
    outputs = create_studio_outputs(
        str(media.resolve()),
        [
            SubtitleCue(1, 0.4, 2.4, "P8A PROJECT CLOCK", speaker="S01"),
            SubtitleCue(2, 2.6, 4.2, "Mapped source time", speaker="S01"),
        ],
        txt_path=str(txt),
        target_project_path=str(project_path),
        generation_metadata={
            "created_by": "2ByteASR recognition pipeline",
            "recognition_purpose": "final",
            "p8a_fixture": True,
        },
    )
    project = load_project(outputs["project"])
    if project.media_pool[0].duration_ms <= 0:
        raise RuntimeError("create_studio_outputs produced MediaAsset duration 0")
    return Path(outputs["project"])


def _path_parity() -> dict:
    from twobyteasr.model_registry import scan_model_registry
    from twobyteasr.runtime_paths import (
        build_runtime_paths,
        reset_runtime_paths,
    )

    reset_runtime_paths()
    source = build_runtime_paths(install_root=ROOT, persist=False)
    reset_runtime_paths()
    packaged_root = ROOT / "dist" / "2ByteASR"
    packaged = build_runtime_paths(
        install_root=packaged_root if packaged_root.exists() else ROOT,
        persist=False,
    )
    source_reg = scan_model_registry(install_root=ROOT, model_root=source.model_root)
    packaged_reg = scan_model_registry(
        install_root=packaged_root if packaged_root.exists() else ROOT,
        model_root=packaged.model_root,
    )
    return {
        "source_model_root": str(source.model_root),
        "packaged_model_root": str(packaged.model_root),
        "same_model_root": source.model_root.resolve() == packaged.model_root.resolve(),
        "source_installed": source_reg.installed_count(),
        "packaged_installed": packaged_reg.installed_count(),
        "same_installed_count": source_reg.installed_count() == packaged_reg.installed_count(),
        "source_project_root": str(source.project_root),
        "packaged_project_root": str(packaged.project_root),
        "same_project_root": source.project_root.resolve() == packaged.project_root.resolve(),
    }


def main() -> int:
    args = _arguments()
    run = args.output or ROOT / "tmp" / "p8a" / (
        "runtime-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    run = run.resolve()
    run.mkdir(parents=True, exist_ok=False)
    local = run / "localappdata"
    local.mkdir()
    second = _second_media(args.second_media)
    project_path = (
        args.project.resolve()
        if args.project
        else _prepare_project(args.media, run / "project")
    )
    parity = _path_parity()
    (run / "path-parity.json").write_text(
        json.dumps(parity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env.update({
        "LOCALAPPDATA": str(local),
        "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
        "TWOBYTEASR_STARTUP_PROJECT": str(project_path),
        "TWOBYTEASR_P8A_RUNTIME_AUDIT": "1",
        "TWOBYTEASR_P8A_RUNTIME_OUTPUT": str(run),
        "TWOBYTEASR_P8A_SECOND_MEDIA": str(second.resolve()) if second.is_file() else "",
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_MODEL_ROOT": parity["source_model_root"],
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
    exit_code = 1
    proc = subprocess.Popen(command, cwd=cwd, env=env)
    result_path = run / "runtime-result.json"
    deadline = time.time() + (70.0 if args.exe else 45.0)
    payload: dict = {}
    while time.time() < deadline:
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            if payload.get("checks") or payload.get("errors") or "accepted" in payload:
                try:
                    exit_code = int(proc.wait(timeout=4))
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    exit_code = 0 if payload.get("accepted") else 1
                break
        time.sleep(0.2)
    else:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        exit_code = 124
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
    summary = {
        "exit_code": exit_code,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "command": command,
        "project": str(project_path),
        "second_media": str(second),
        "second_media_bytes": second.stat().st_size if second.is_file() else 0,
        "path_parity": parity,
        "accepted": bool(payload.get("accepted")) and bool(parity.get("same_model_root")),
        "checks": payload.get("checks", {}),
        "errors": payload.get("errors", []),
        "phases": payload.get("phases", {}),
        "benchmarks": payload.get("benchmarks", {}),
        "result_path": str(result_path),
        "real_user_click": False,
    }
    (run / "harness-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] and exit_code in {0, 124} else 1


if __name__ == "__main__":
    raise SystemExit(main())
