"""Run P8B continuous workflow/reopen gates in source or exact packaged mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import psutil
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
    parser.add_argument("--mode", choices=("source", "packaged"), default="source")
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--media", type=Path, default=DEFAULT_V1)
    parser.add_argument("--second-media", type=Path, default=DEFAULT_V2)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _prepare_project(media: Path, output: Path) -> Path:
    from twobyteasr.models import SubtitleCue
    from twobyteasr.studio_project import create_studio_outputs

    output.mkdir(parents=True, exist_ok=True)
    transcript = output / f"{media.stem}.txt"
    transcript.write_text("P8B continuous creative runtime\n", encoding="utf-8")
    project = output / media.stem / f"{media.stem}.2byteproj"
    values = create_studio_outputs(
        str(media.resolve()),
        [
            SubtitleCue(1, 0.4, 4.8, "H", speaker="S01"),
            SubtitleCue(2, 5.0, 6.5, "P8B Applied Motion", speaker="S01"),
        ],
        txt_path=str(transcript),
        target_project_path=str(project),
        generation_metadata={
            "created_by": "2ByteASR recognition pipeline",
            "recognition_purpose": "final",
            "p8b_fixture": True,
        },
    )
    return Path(values["project"]).resolve()


def _launch(
    launch_mode: str,
    *,
    phase: str,
    output: Path,
    profile: Path,
    project: Path,
    second_media: Path,
    exe: Path,
    timeout: float,
) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    startup_trace = output / "startup-trace.jsonl"
    child_log = output / "child-processes.jsonl"
    env = dict(os.environ)
    # This omission is intentional: the gate must exercise the real first-run
    # decision and prove a healthy registry never opens the install prompt.
    env.pop("TWOBYTEASR_SKIP_FIRST_RUN_WIZARD", None)
    env.update({
        "LOCALAPPDATA": str(profile),
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
        "TWOBYTEASR_STARTUP_PROJECT": str(project),
        "TWOBYTEASR_P8B_RUNTIME_AUDIT": phase,
        "TWOBYTEASR_P8B_RUNTIME_OUTPUT": str(output),
        "TWOBYTEASR_P8B_SECOND_MEDIA": str(second_media),
        "TWOBYTEASR_STARTUP_TRACE": str(startup_trace),
        "TWOBYTEASR_CHILD_PROCESS_LOG": str(child_log),
        "TWOBYTEASR_LAUNCH_MODE": "packaged" if launch_mode == "packaged" else "source-dev",
    })
    env.pop("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", None)
    if launch_mode == "packaged":
        command = [str(exe.resolve())]
        cwd = exe.resolve().parent
    else:
        command = [str(ROOT / ".venv-main" / "Scripts" / "python.exe"), "-B", str(ROOT / "quick_start.py")]
        cwd = ROOT

    started = time.time()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    result_path = output / "runtime-result.json"
    deadline = time.time() + timeout
    payload = {}
    timed_out = False
    while time.time() < deadline:
        if result_path.is_file():
            payload = _read_json(result_path)
            if "accepted" in payload:
                break
        if process.poll() is not None and not result_path.is_file():
            break
        time.sleep(0.2)
    else:
        timed_out = True
    if process.poll() is None:
        try:
            process.wait(timeout=15 if payload else 1)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    payload = payload or _read_json(result_path)
    child_rows = []
    if child_log.is_file():
        child_rows = [
            json.loads(line) for line in child_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    starts = {int(item["child_pid"]) for item in child_rows if item.get("phase") == "start" and item.get("child_pid")}
    exits = {int(item["child_pid"]) for item in child_rows if item.get("phase") == "exit" and item.get("child_pid")}
    start_rows = {
        int(item["child_pid"]): item
        for item in child_rows
        if item.get("phase") == "start" and item.get("child_pid")
    }
    residual_children: list[dict[str, object]] = []
    residual_deadline = time.time() + 5.0
    while time.time() < residual_deadline:
        residual_children = []
        for pid in sorted(starts - exits):
            try:
                child = psutil.Process(pid)
                actual_exe = child.exe()
                expected_exe = str(start_rows[pid].get("executable") or "")
                same_image = bool(
                    not expected_exe
                    or Path(actual_exe).resolve() == Path(expected_exe).resolve()
                )
                if child.is_running() and same_image:
                    residual_children.append({
                        "pid": pid,
                        "name": child.name(),
                        "executable": actual_exe,
                    })
            except (OSError, psutil.Error):
                continue
        if not residual_children:
            break
        time.sleep(0.1)
    return {
        "phase": phase,
        "command": command,
        "exit_code": process.returncode,
        "elapsed_s": round(time.time() - started, 3),
        "timed_out": timed_out,
        "accepted": bool(payload.get("accepted")),
        "checks": payload.get("checks", {}),
        "phases": payload.get("phases", {}),
        "errors": payload.get("errors", []),
        "process": payload.get("process", {}),
        "result_path": str(result_path),
        "startup_trace": str(startup_trace),
        "child_process_log": str(child_log),
        "child_starts": sorted(starts),
        "child_exits": sorted(exits),
        "all_logged_children_exited": not residual_children,
        "residual_children": residual_children,
        "real_user_click": False,
    }


def main() -> int:
    args = _arguments()
    media = args.media.resolve()
    second_media = args.second_media.resolve()
    exe = args.exe.resolve()
    required = [("V1", media), ("V2", second_media)]
    if args.mode == "packaged":
        required.append(("EXE", exe))
    for label, path in required:
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")
    run = (
        args.output.resolve()
        if args.output
        else ROOT / "tmp" / "p8b" / f"{args.mode}-runtime-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    run.mkdir(parents=True, exist_ok=False)
    profile = run / "localappdata"
    profile.mkdir()
    # Fixture creation also registers the recent project, so isolate the
    # parent runner before importing Studio project modules.
    os.environ["LOCALAPPDATA"] = str(profile)
    project = _prepare_project(media, run / "project")
    identity = {
        "mode": args.mode,
        "exe": str(exe) if args.mode == "packaged" else "",
        "exe_sha256": _sha256(exe) if args.mode == "packaged" else "",
        "exe_bytes": exe.stat().st_size if args.mode == "packaged" else 0,
        "exe_mtime": datetime.fromtimestamp(exe.stat().st_mtime).astimezone().isoformat() if args.mode == "packaged" else "",
        "build_metadata": _read_json(exe.parent / "2byteasr_build.json") if args.mode == "packaged" else {},
    }
    workflow = _launch(
        args.mode, phase="workflow", output=run / "workflow", profile=profile,
        project=project, second_media=second_media, exe=exe, timeout=420,
    )
    reopen = (
        _launch(
            args.mode, phase="reopen", output=run / "reopen", profile=profile,
            project=project, second_media=second_media, exe=exe, timeout=240,
        )
        if workflow.get("accepted")
        else {
            "phase": "reopen",
            "accepted": False,
            "checks": {},
            "phases": {},
            "errors": ["skipped because workflow did not pass"],
            "all_logged_children_exited": True,
            "real_user_click": False,
        }
    )
    workflow_ai = workflow.get("phases", {}).get("ai_motion", {})
    reopen_state = reopen.get("phases", {}).get("reopen", {})
    persisted_visual_matches = bool(
        workflow_ai.get("applied_graph_hash")
        and workflow_ai.get("applied_graph_hash") == reopen_state.get("graph_hash")
        and float(workflow_ai.get("applied_stroke_width", -1))
        == float(reopen_state.get("stroke_width", -2))
        and int(workflow_ai.get("applied_motion_duration_ms", -1))
        == int(reopen_state.get("motion_duration_ms", -2))
    )
    gates = {
        "NO_FALSE_MODEL_PROMPT": bool(workflow.get("checks", {}).get("startup_prompt_absent") and reopen.get("checks", {}).get("startup_prompt_absent")),
        "MODEL_REGISTRY_HEALTH": bool(workflow.get("checks", {}).get("registry_models_healthy")),
        "V2_MOVE_HIDE_CONTINUOUS": bool(workflow.get("checks", {}).get("v2_only_after_move_without_seek") and workflow.get("checks", {}).get("v2_first_frame_and_pixels")),
        "STROKE_CONTROL_PARITY": all(bool(workflow.get("checks", {}).get(key)) for key in (
            "stroke_control_canonical_levels", "stroke_live_strict_order", "stroke_fidelity_strict_order",
            "stroke20_not_thin", "stroke_no_50ms_thinning", "paused_fidelity_current_time",
        )),
        "ART_DIRECTION_CARDS": bool(workflow.get("checks", {}).get("three_distinct_art_direction_cards") and workflow.get("checks", {}).get("card_live_first_frame_budget")),
        "APPLIED_MOTION": all(bool(workflow.get("checks", {}).get(key)) for key in (
            "play_motion_restarts", "card_applied_same_graph", "applied_motion_visible_through_hold",
            "applied_playback_live_owner", "applied_paused_fidelity", "applied_live_p95_budget",
        )),
        "SAVE_REOPEN": bool(
            workflow.get("checks", {}).get("project_saved")
            and reopen.get("accepted")
            and persisted_visual_matches
        ),
        "CHILD_PROCESS_CLEANUP": bool(workflow.get("all_logged_children_exited") and reopen.get("all_logged_children_exited")),
        "EXACT_PACKAGED_IDENTITY": bool(args.mode != "packaged" or (
            workflow.get("process", {}).get("frozen")
            and reopen.get("process", {}).get("frozen")
            and identity["build_metadata"]
        )),
        "USER_VERIFIED": False,
    }
    summary = {
        "schema": "2byteasr.p8b-runtime-closure.v1",
        "run": str(run),
        "identity": identity,
        "media": {"v1": str(media), "v2": str(second_media)},
        "project": str(project),
        "workflow": workflow,
        "reopen": reopen,
        "gates": gates,
        "accepted": all(value for key, value in gates.items() if key != "USER_VERIFIED"),
        "real_user_click": False,
    }
    summary_path = run / "runtime-closure-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
