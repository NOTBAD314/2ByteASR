"""Run P8C source or official-package headed evidence.

Automated evidence only. This script never sets USER VERIFIED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil


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
    parser.add_argument("--skip-header-matrix", action="store_true")
    parser.add_argument("--header-matrix-only", action="store_true")
    parser.add_argument("--carryover-memory-only", action="store_true")
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
    transcript.write_text("P8C production integration runtime\n", encoding="utf-8")
    project = output / media.stem / f"{media.stem}.2byteproj"
    values = create_studio_outputs(
        str(media.resolve()),
        [
            SubtitleCue(1, 0.4, 4.8, "H", speaker="S01"),
            SubtitleCue(2, 5.0, 6.5, "P8C Production Integration", speaker="S01"),
        ],
        txt_path=str(transcript),
        target_project_path=str(project),
        generation_metadata={"created_by": "P8C audit", "p8c_fixture": True},
    )
    return Path(values["project"]).resolve()


def _studio_settings_path_for_profile(profile: Path) -> Path:
    """Return the settings path used by the application for an isolated profile."""

    from twobyteasr.studio_project import studio_settings_path

    return studio_settings_path(profile)


def _process_row(process: psutil.Process, *, role: str = "") -> dict[str, object]:
    try:
        return {
            "pid": process.pid,
            "ppid": process.ppid(),
            "name": process.name(),
            "executable": process.exe(),
            "command_line": process.cmdline(),
            "creation_time": process.create_time(),
            "role": role,
        }
    except (psutil.Error, OSError) as exc:
        return {"pid": process.pid, "error": f"{type(exc).__name__}: {exc}", "role": role}


def _descendants(pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except (psutil.Error, OSError):
        return []


def _remember_owned_processes(
    root: psutil.Process,
    known: dict[tuple[int, float], psutil.Process],
) -> None:
    candidates = [root, *_descendants(root.pid)]
    for process in candidates:
        try:
            known[(process.pid, process.create_time())] = process
        except (psutil.Error, OSError):
            pass


def _running_owned_processes(
    known: dict[tuple[int, float], psutil.Process],
) -> list[psutil.Process]:
    running = []
    for (pid, created), process in known.items():
        try:
            if (
                process.is_running()
                and process.status() != psutil.STATUS_ZOMBIE
                and abs(process.create_time() - created) < 0.001
            ):
                running.append(process)
        except (psutil.Error, OSError):
            pass
    return running


def _bounded_cleanup_owned_processes(
    processes: list[psutil.Process],
) -> dict[str, object]:
    requested = [_process_row(process, role="audit-owned-cleanup") for process in processes]
    for process in reversed(processes):
        try:
            process.terminate()
        except (psutil.Error, OSError):
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    killed = []
    for process in alive:
        try:
            killed.append(process.pid)
            process.kill()
        except (psutil.Error, OSError):
            pass
    _, alive = psutil.wait_procs(alive, timeout=3)
    return {
        "requested": requested,
        "forced_kill_pids": killed,
        "remaining": [_process_row(process) for process in alive],
    }


def _audio_sessions(pids: set[int]) -> dict[str, object]:
    com_initialized = False
    rows = []
    try:
        import comtypes
        comtypes.CoInitialize()
        com_initialized = True
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        try:
            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                process = session.Process
                pid = int(process.pid) if process is not None else 0
                if pid not in pids:
                    continue
                peak = None
                try:
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    peak = float(meter.GetPeakValue())
                except Exception:
                    pass
                rows.append({
                    "pid": pid,
                    "process_name": process.name() if process is not None else "",
                    "display_name": str(session.DisplayName or ""),
                    "state": str(session.State),
                    "peak": peak,
                })
        except Exception as exc:
            result = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "sessions": rows,
            }
        else:
            result = {"available": True, "error": "", "sessions": rows}
    except Exception as exc:
        result = {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "sessions": rows,
        }
    finally:
        if com_initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
    return result


def _audio_sessions_bounded(
    pids: set[int],
    *,
    timeout_s: float = 2.0,
) -> dict[str, object]:
    completed = threading.Event()
    holder: dict[str, object] = {}

    def enumerate_sessions() -> None:
        try:
            holder["result"] = _audio_sessions(pids)
        finally:
            completed.set()

    threading.Thread(
        target=enumerate_sessions,
        name="p8c-audio-session-enumeration",
        daemon=True,
    ).start()
    if not completed.wait(max(0.1, float(timeout_s))):
        return {
            "available": False,
            "error": f"audio session enumeration timeout after {timeout_s:.1f}s",
            "sessions": [],
        }
    value = holder.get("result")
    return value if isinstance(value, dict) else {
        "available": False,
        "error": "audio session enumeration returned no result",
        "sessions": [],
    }


def _sample_audio_sessions(pid: int, duration_s: float = 0.9) -> dict[str, object]:
    samples = []
    deadline = time.time() + duration_s
    while time.time() < deadline:
        pids = {pid, *(child.pid for child in _descendants(pid))}
        samples.append(_audio_sessions_bounded(pids))
        time.sleep(0.1)
    available = any(item.get("available") for item in samples)
    sessions: dict[tuple[int, str], dict[str, object]] = {}
    for sample in samples:
        for row in sample.get("sessions", []):
            key = (int(row["pid"]), str(row["display_name"]))
            current = sessions.setdefault(key, {**row, "peak_max": 0.0, "sample_count": 0})
            current["sample_count"] += 1
            if row.get("peak") is not None:
                current["peak_max"] = max(float(current["peak_max"]), float(row["peak"]))
    return {
        "available": available,
        "samples": len(samples),
        "sessions": list(sessions.values()),
        "errors": sorted({
            str(item.get("error")) for item in samples
            if item.get("error")
        }),
    }


def _source_rms(path: Path, start_s: float = 1.0) -> dict[str, object]:
    ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if not ffmpeg:
        return {"path": str(path), "available": False, "error": "ffmpeg not found"}
    command = [
        ffmpeg, "-v", "error", "-ss", f"{start_s:.3f}", "-i", str(path),
        "-t", "1.0", "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
    ]
    completed = subprocess.run(command, capture_output=True, timeout=30, check=False)
    samples = np.frombuffer(completed.stdout, dtype="<i2").astype(np.float64)
    if completed.returncode or samples.size == 0:
        return {
            "path": str(path), "available": False,
            "error": completed.stderr.decode("utf-8", "replace")[-1000:],
        }
    rms = float(np.sqrt(np.mean(np.square(samples))))
    return {
        "path": str(path), "available": True,
        "sample_count": int(samples.size),
        "rms": round(rms, 3),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-9) / 32768.0), 3),
        "peak": int(np.max(np.abs(samples))),
    }


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
    scale_factor: str = "",
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=False)
    startup_trace = output / "startup-trace.jsonl"
    child_log = output / "child-processes.jsonl"
    env = dict(os.environ)
    env.pop("TWOBYTEASR_SKIP_FIRST_RUN_WIZARD", None)
    env.pop("TWOBYTEASR_P8B_RUNTIME_AUDIT", None)
    env.update({
        "LOCALAPPDATA": str(profile),
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "0" if phase == "header" else "1",
        "TWOBYTEASR_STARTUP_RAISE": "1" if phase == "header" else "0",
        "TWOBYTEASR_STARTUP_PROJECT": str(project),
        "TWOBYTEASR_P8C_RUNTIME_AUDIT": phase,
        "TWOBYTEASR_P8C_RUNTIME_OUTPUT": str(output),
        "TWOBYTEASR_P8B_SECOND_MEDIA": str(second_media),
        "TWOBYTEASR_STARTUP_TRACE": str(startup_trace),
        "TWOBYTEASR_CHILD_PROCESS_LOG": str(child_log),
        "TWOBYTEASR_LAUNCH_MODE": "packaged" if launch_mode == "packaged" else "source-dev",
    })
    if phase == "reopen":
        # The workflow intentionally leaves a newer autosave beside the saved
        # project.  An automated reopen must exercise the official persisted
        # project without blocking on the product's interactive recovery dialog.
        # Keep this aligned with studio_project.studio_settings_path().  The
        # settings file lives under SubtitleStudioPreview; writing to the
        # legacy SubtitleStudio directory leaves recovery_policy at ``ask``
        # and blocks the automated reopen behind a modal dialog.
        settings_path = _studio_settings_path_for_profile(profile)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({
                "studio_preferences": {
                    "recovery_policy": "official",
                },
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if scale_factor:
        env["QT_SCALE_FACTOR"] = scale_factor
    else:
        env.pop("QT_SCALE_FACTOR", None)
    env.pop("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", None)
    if launch_mode == "packaged":
        command = [str(exe.resolve())]
        cwd = exe.resolve().parent
    else:
        command = [
            str(ROOT / ".venv-main" / "Scripts" / "python.exe"),
            "-B", str(ROOT / "quick_start.py"),
        ]
        cwd = ROOT

    started = time.time()
    process = subprocess.Popen(
        command, cwd=str(cwd), env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    root_process = psutil.Process(process.pid)
    owned_processes: dict[tuple[int, float], psutil.Process] = {}
    _remember_owned_processes(root_process, owned_processes)
    result_path = output / "runtime-result.json"
    payload = {}
    timed_out = False
    seen_markers: set[str] = set()
    audio_sessions: dict[str, object] = {}
    peak_process_rss_bytes = 0
    peak_owned_rss_bytes = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        _remember_owned_processes(root_process, owned_processes)
        running_owned = _running_owned_processes(owned_processes)
        rss_values = []
        for owned in running_owned:
            try:
                rss_values.append(int(owned.memory_info().rss))
            except (psutil.Error, OSError):
                pass
        peak_process_rss_bytes = max([peak_process_rss_bytes, *rss_values])
        peak_owned_rss_bytes = max(peak_owned_rss_bytes, sum(rss_values))
        payload = _read_json(result_path) if result_path.is_file() else {}
        marker = str(payload.get("phases", {}).get("audio", {}).get("probe_state") or "")
        if marker and marker not in {"complete"} and marker not in seen_markers:
            seen_markers.add(marker)
            audio_sessions[marker] = _sample_audio_sessions(process.pid)
        if "accepted" in payload and phase != "lifecycle":
            break
        if process.poll() is not None and not payload:
            break
        time.sleep(0.15)
    else:
        timed_out = True
    _remember_owned_processes(root_process, owned_processes)
    process_rows = []
    for index, owned in enumerate(owned_processes.values()):
        process_rows.append(_process_row(owned, role="launcher" if index == 0 else "child"))
    if process.poll() is None:
        try:
            process.wait(timeout=20 if payload else 2)
        except subprocess.TimeoutExpired:
            pass
    payload = payload or _read_json(result_path)
    residual_deadline = time.time() + 5
    while time.time() < residual_deadline:
        residual_processes = _running_owned_processes(owned_processes)
        if not residual_processes:
            break
        time.sleep(0.1)
    residual_processes = _running_owned_processes(owned_processes)
    residual = [_process_row(item) for item in residual_processes]
    cleanup = (
        _bounded_cleanup_owned_processes(residual_processes)
        if residual_processes else {"requested": [], "forced_kill_pids": [], "remaining": []}
    )
    return {
        "phase": phase,
        "scale_factor": scale_factor,
        "command": command,
        "exit_code": process.returncode,
        "elapsed_s": round(time.time() - started, 3),
        "timed_out": timed_out,
        "accepted": bool(payload.get("accepted")),
        "checks": payload.get("checks", {}),
        "phases": payload.get("phases", {}),
        "errors": payload.get("errors", []),
        "processes": process_rows,
        "audio_sessions": audio_sessions,
        "peak_process_rss_bytes": peak_process_rss_bytes,
        "peak_owned_rss_bytes": peak_owned_rss_bytes,
        "result_path": str(result_path),
        "startup_trace": str(startup_trace),
        "child_process_log": str(child_log),
        "residual_processes": residual,
        "cleanup": cleanup,
        "real_user_click": False,
    }


def main() -> int:
    args = _arguments()
    if args.header_matrix_only and args.skip_header_matrix:
        raise ValueError("--header-matrix-only conflicts with --skip-header-matrix")
    if args.header_matrix_only and args.carryover_memory_only:
        raise ValueError("targeted audit modes conflict")
    media = args.media.resolve()
    second = args.second_media.resolve()
    exe = args.exe.resolve()
    required = [media, second, *( [exe] if args.mode == "packaged" else [])]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    run = (
        args.output.resolve()
        if args.output else ROOT / "tmp" / "p8c" /
        f"{args.mode}-runtime-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    run.mkdir(parents=True, exist_ok=False)
    profile = run / "localappdata"
    profile.mkdir()
    os.environ["LOCALAPPDATA"] = str(profile)
    project = _prepare_project(media, run / "project")
    result: dict[str, object] = {
        "schema": "2byteasr.p8c-runtime-closure.v1",
        "mode": args.mode,
        "real_user_click": False,
        "identity": {
            "exe": str(exe) if args.mode == "packaged" else "",
            "exe_sha256": _sha256(exe) if args.mode == "packaged" else "",
            "exe_bytes": exe.stat().st_size if args.mode == "packaged" else 0,
            "exe_mtime": datetime.fromtimestamp(exe.stat().st_mtime).astimezone().isoformat()
            if args.mode == "packaged" else "",
            "build_metadata": _read_json(exe.parent / "2byteasr_build.json")
            if args.mode == "packaged" else {},
        },
        "source_audio": {
            "V1": _source_rms(media),
            "V2": _source_rms(second),
        },
    }
    workflow = {"skipped": True, "checks": {}, "errors": []}
    result["reopen"] = {"skipped": True, "checks": {}, "errors": []}
    if args.carryover_memory_only:
        workflow = _launch(
            args.mode, phase="memory", output=run / "memory",
            profile=profile, project=project, second_media=second, exe=exe, timeout=180,
        )
    elif not args.header_matrix_only:
        workflow = _launch(
            args.mode, phase="workflow", output=run / "workflow",
            profile=profile, project=project, second_media=second, exe=exe, timeout=720,
        )
        result["reopen"] = (
            _launch(
                args.mode, phase="reopen", output=run / "reopen",
                profile=profile, project=project, second_media=second, exe=exe, timeout=300,
            )
            if workflow["accepted"] else {"accepted": False, "errors": ["workflow failed"]}
        )
    result["workflow"] = workflow
    header = []
    if not args.skip_header_matrix and not args.carryover_memory_only:
        for scale in ("1.0", "1.25", "1.5", "1.75", "2.0"):
            scale_profile = run / f"localappdata-header-{scale.replace('.', '_')}"
            scale_profile.mkdir()
            header.append(_launch(
                args.mode, phase="header", output=run / f"header-{scale.replace('.', '_')}",
                profile=scale_profile, project=project, second_media=second,
                exe=exe, timeout=180, scale_factor=scale,
            ))
    result["header_matrix"] = header
    source_audio_ok = all(
        bool(item.get("available")) and float(item.get("rms", 0)) > 0
        for item in result["source_audio"].values()
    )
    header_checks = {
        "header_matrix": bool(
            args.skip_header_matrix
            or (len(header) == 5 and all(item.get("accepted") for item in header))
        ),
        "header_no_residual": all(not item.get("residual_processes") for item in header),
    }
    if args.header_matrix_only:
        result["checks"] = header_checks
    elif args.carryover_memory_only:
        result["checks"] = {
            "memory_workflow": bool(workflow.get("accepted")),
            "memory_no_residual": not workflow.get("residual_processes"),
            "memory_peak_process_rss_under_3gb": (
                0 < int(workflow.get("peak_process_rss_bytes", 0)) < 3 * 1024 ** 3
            ),
        }
    else:
        session_rows = workflow.get("audio_sessions", {})
        sessions_available = bool(session_rows) and all(
            bool(item.get("available")) for item in session_rows.values()
        )
        result["checks"] = {
            "workflow": bool(workflow.get("accepted")),
            "reopen": bool(result["reopen"].get("accepted")),
            "source_audio_rms": source_audio_ok,
            "audio_sessions_enumerated": sessions_available,
            "workflow_no_residual": not workflow.get("residual_processes"),
            "workflow_peak_process_rss_under_3gb": (
                0 < int(workflow.get("peak_process_rss_bytes", 0)) < 3 * 1024 ** 3
            ),
            "reopen_no_residual": not result["reopen"].get("residual_processes"),
            **header_checks,
        }
    result["accepted"] = all(bool(value) for value in result["checks"].values())
    target = run / "runtime-closure-summary.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "accepted": result["accepted"],
        "checks": result["checks"],
        "workflow_checks": workflow.get("checks", {}),
        "workflow_errors": workflow.get("errors", []),
        "output": str(target),
    }, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
