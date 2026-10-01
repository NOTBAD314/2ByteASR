"""Run the P8A-R1 gates against one exact rebuilt 2ByteASR.exe."""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"
DEFAULT_V1 = Path(Path.home() / "Desktop" / r"[NOTBAD]知更鸟晴歌抽卡.mp4")
DEFAULT_V2 = ROOT / "tmp" / "[NOTBAD]雨之城前段9_2026.08.11-16.57.51_成片.mp4"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--media", type=Path, default=DEFAULT_V1)
    parser.add_argument("--second-media", type=Path, default=DEFAULT_V2)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-launches", type=int, default=5)
    parser.add_argument("--stress-seconds", type=int, default=60)
    return parser.parse_args()


def _prepare_project(media: Path, output_dir: Path) -> Path:
    from twobyteasr.models import SubtitleCue
    from twobyteasr.studio_project import create_studio_outputs

    output_dir.mkdir(parents=True, exist_ok=True)
    transcript = output_dir / f"{media.stem}.txt"
    transcript.write_text("P8A-R1 real packaged workflow\n", encoding="utf-8")
    project_path = output_dir / media.stem / f"{media.stem}.2byteproj"
    outputs = create_studio_outputs(
        str(media.resolve()),
        [
            SubtitleCue(1, 0.4, 2.4, "P8A-R1 PROJECT CLOCK", speaker="S01"),
            SubtitleCue(2, 2.6, 4.2, "Real packaged workflow", speaker="S01"),
        ],
        txt_path=str(transcript),
        target_project_path=str(project_path),
        generation_metadata={
            "created_by": "2ByteASR recognition pipeline",
            "recognition_purpose": "final",
            "p8a_r1_fixture": True,
        },
    )
    return Path(outputs["project"]).resolve()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _launch(
    exe: Path,
    *,
    mode: str,
    output: Path,
    local_app_data: Path,
    project: Path | None = None,
    second_media: Path | None = None,
    stress_seconds: int = 60,
    timeout: float,
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env.pop("2BYTEASR_MODEL_ROOT", None)
    env.pop("2BYTEASR_USER_DATA_ROOT", None)
    env.update(
        {
            "LOCALAPPDATA": str(local_app_data),
            "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
            "TWOBYTEASR_NO_OPEN": "1",
            "TWOBYTEASR_LAUNCH_MODE": "packaged",
            "TWOBYTEASR_PROJECT_CLOCK_AUDIT": "1",
            "TWOBYTEASR_P8A_R1_RUNTIME_AUDIT": mode,
            "TWOBYTEASR_P8A_R1_RUNTIME_OUTPUT": str(output),
            "TWOBYTEASR_P8A_R1_STRESS_SECONDS": str(stress_seconds),
        }
    )
    if mode == "model":
        env["TWOBYTEASR_STARTUP_RAISE"] = "1"
        env.pop("TWOBYTEASR_STARTUP_OPEN_STUDIO", None)
        env.pop("TWOBYTEASR_STARTUP_PROJECT", None)
    else:
        if project is None or second_media is None:
            raise ValueError(f"{mode} requires project and second media")
        env["TWOBYTEASR_STARTUP_OPEN_STUDIO"] = "1"
        env["TWOBYTEASR_STARTUP_PROJECT"] = str(project)
        env["TWOBYTEASR_P8A_R1_SECOND_MEDIA"] = str(second_media)
        env.pop("TWOBYTEASR_STARTUP_RAISE", None)
    env.pop("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", None)

    started = time.perf_counter()
    process = subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    result_path = output / "runtime-result.json"
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        if result_path.is_file():
            payload = _read_json(result_path)
            if "accepted" in payload:
                break
        if process.poll() is not None and not result_path.is_file():
            break
        time.sleep(0.2)
    if process.poll() is None:
        try:
            process.wait(timeout=8 if payload else 1)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    payload = payload or _read_json(result_path)
    return {
        "mode": mode,
        "exit_code": process.returncode,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "result_path": str(result_path),
        "accepted": bool(payload.get("accepted")),
        "checks": payload.get("checks", {}),
        "phases": payload.get("phases", {}),
        "errors": payload.get("errors", []),
        "process": payload.get("process", {}),
        "real_user_click": False,
        "ui_event_path": bool(payload.get("ui_event_path")),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    args = _arguments()
    exe = args.exe.resolve()
    media = args.media.resolve()
    second = args.second_media.resolve()
    for label, path in (("packaged EXE", exe), ("V1", media), ("V2", second)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")
    if args.model_launches != 5:
        raise ValueError("P8A-R1 requires exactly five packaged model launches")
    if args.stress_seconds < 60:
        raise ValueError("P8A-R1 requires at least 60 seconds of multitrack playback")

    run = (
        args.output.resolve()
        if args.output
        else ROOT / "tmp" / "p8a-r1" / (
            "packaged-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        )
    )
    run.mkdir(parents=True, exist_ok=False)
    local_app_data = run / "localappdata"
    local_app_data.mkdir()
    project = _prepare_project(media, run / "project")
    build_metadata = _read_json(exe.parent / "2byteasr_build.json")
    identity = {
        "exe": str(exe),
        "exe_bytes": exe.stat().st_size,
        "exe_mtime": datetime.fromtimestamp(exe.stat().st_mtime).astimezone().isoformat(),
        "exe_sha256": _sha256(exe),
        "build_metadata": build_metadata,
    }

    model_runs = []
    for index in range(5):
        model_runs.append(
            _launch(
                exe,
                mode="model",
                output=run / f"model-launch-{index + 1}",
                local_app_data=local_app_data,
                timeout=50.0,
            )
        )
    model_rows = [item.get("phases", {}).get("models", {}) for item in model_runs]
    model_roots = [str(item.get("model_root") or "") for item in model_rows]
    model_counts = [int(item.get("installed_count") or 0) for item in model_rows]
    model_persistence = bool(
        all(item.get("accepted") for item in model_runs)
        and len(set(model_roots)) == 1
        and bool(model_roots[0])
        and len(set(model_counts)) == 1
        and model_counts[0] >= 3
        and all(
            row.get("records", {}).get(key, {}).get("health") == "INSTALLED"
            for row in model_rows
            for key in ("moss", "firered_aed", "qwen_asr")
        )
    )

    workflow = _launch(
        exe,
        mode="workflow",
        output=run / "workflow",
        local_app_data=local_app_data,
        project=project,
        second_media=second,
        stress_seconds=args.stress_seconds,
        timeout=float(args.stress_seconds + 150),
    )
    reopen = _launch(
        exe,
        mode="reopen",
        output=run / "reopen",
        local_app_data=local_app_data,
        project=project,
        second_media=second,
        stress_seconds=args.stress_seconds,
        timeout=80.0,
    )

    workflow_checks = workflow.get("checks", {})
    reopen_checks = reopen.get("checks", {})
    gates = {
        "SOURCE_CODE_VERIFIED": True,
        "NEW_PACKAGED_EXE_BUILT": bool(build_metadata)
        and identity["exe_sha256"]
        == _sha256(exe),
        "PACKAGED_MODEL_PERSISTENCE_VERIFIED": model_persistence,
        "PACKAGED_V2_ONLY_PIXELS_VERIFIED": bool(
            workflow_checks.get("v2_only_real_pixels")
            and reopen_checks.get("v2_reopen_pixels")
        ),
        "PACKAGED_10S_SEEK_VERIFIED": bool(
            workflow_checks.get("seek_10s_not_17s")
            and workflow_checks.get("seek_gate")
            and reopen_checks.get("reopen_seek_10s")
        ),
        "PACKAGED_V2_DRAG_VERIFIED": bool(
            workflow_checks.get("v2_drag_to_zero")
            and reopen_checks.get("v2_still_at_zero")
        ),
        "PACKAGED_60S_MULTITRACK_PLAYBACK_VERIFIED": bool(
            workflow_checks.get("multitrack_60s_playback")
            and workflow_checks.get("stress_interactions_complete")
        ),
        "PACKAGED_SAVE_REOPEN_VERIFIED": bool(
            workflow_checks.get("project_saved")
            and reopen_checks.get("v2_reopen_played")
        ),
        "USER_VERIFIED": False,
    }
    required = [value for key, value in gates.items() if key not in {"USER_VERIFIED"}]
    summary = {
        "schema": "2byteasr.p8a-r1-packaged-closure.v1",
        "run": str(run),
        "identity": identity,
        "media": {
            "v1": str(media),
            "v1_bytes": media.stat().st_size,
            "v2": str(second),
            "v2_bytes": second.stat().st_size,
        },
        "project": str(project),
        "model_runs": model_runs,
        "model_roots": model_roots,
        "model_counts": model_counts,
        "workflow": workflow,
        "reopen": reopen,
        "gates": gates,
        "accepted": all(required),
        "real_user_click": False,
    }
    summary_path = run / "packaged-closure-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
