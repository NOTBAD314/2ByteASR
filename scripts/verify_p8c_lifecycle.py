"""Exercise P8C launch, V1+V2 playback, external WM_CLOSE, and relaunch.

The application-side P8C lifecycle audit prepares a real Studio playback state.
This process remains outside the application, records exact process/window
identity, posts WM_CLOSE, and proves bounded cleanup. Automated evidence only.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import psutil


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_EXE = ROOT / "dist" / "2ByteASR" / "2ByteASR.exe"
DEFAULT_V1 = Path(Path.home() / "Desktop" / r"[NOTBAD]知更鸟晴歌抽卡.mp4")
DEFAULT_V2 = ROOT / "tmp" / "[NOTBAD]雨之城前段9_2026.08.11-16.57.51_成片.mp4"
WM_CLOSE = 0x0010


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("source", "packaged"), default="source")
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--media", type=Path, default=DEFAULT_V1)
    parser.add_argument("--second-media", type=Path, default=DEFAULT_V2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--startup-timeout", type=float, default=75.0)
    parser.add_argument("--close-timeout", type=float, default=30.0)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _windows_for_pids(pids: set[int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _lparam):
        owner = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) not in pids:
            return True
        length = int(ctypes.windll.user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        rows.append({
            "hwnd": int(hwnd),
            "pid": int(owner.value),
            "title": buffer.value,
            "visible": bool(ctypes.windll.user32.IsWindowVisible(hwnd)),
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "area": max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top),
        })
        return True

    ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
    return rows


def _role(process: psutil.Process, root_pid: int, packaged_exe: Path | None) -> str:
    try:
        name = process.name().casefold()
        command = " ".join(process.cmdline()).casefold()
        executable = Path(process.exe()).resolve()
    except (psutil.Error, OSError):
        return "unknown"
    if process.pid == root_pid:
        return "launcher"
    if name == "mpv.exe" or "mpv" in executable.stem.casefold():
        return "mpv"
    if "renderer" in command or "remotion" in command:
        return "renderer"
    if "provider" in command or "antigravity" in command:
        return "provider"
    if "--multiprocessing-fork" in command or "spawn_main" in command:
        return "multiprocessing-worker"
    if packaged_exe is not None and executable == packaged_exe:
        return "frozen-helper"
    return "child"


def _process_row(
    process: psutil.Process,
    *,
    root_pid: int,
    packaged_exe: Path | None,
    windows: Iterable[dict[str, object]] = (),
) -> dict[str, object]:
    try:
        created = process.create_time()
        process_windows = [row for row in windows if int(row["pid"]) == process.pid]
        role = _role(process, root_pid, packaged_exe)
        if any(
            row["visible"]
            and int(row["area"]) > 0
            and "2byteasr" in str(row["title"]).casefold()
            for row in process_windows
        ):
            role = "main-gui"
        return {
            "pid": process.pid,
            "ppid": process.ppid(),
            "name": process.name(),
            "executable": process.exe(),
            "command_line": process.cmdline(),
            "creation_time": created,
            "creation_time_iso": datetime.fromtimestamp(created).astimezone().isoformat(),
            "role": role,
            "children": [child.pid for child in process.children(recursive=False)],
            "windows": process_windows,
        }
    except (psutil.Error, OSError) as exc:
        return {"pid": process.pid, "error": f"{type(exc).__name__}: {exc}"}


def _remember(root: psutil.Process, known: dict[tuple[int, float], psutil.Process]) -> None:
    try:
        candidates = [root, *root.children(recursive=True)]
    except (psutil.Error, OSError):
        candidates = [root]
    for process in candidates:
        try:
            known[(process.pid, process.create_time())] = process
        except (psutil.Error, OSError):
            pass


def _running(known: dict[tuple[int, float], psutil.Process]) -> list[psutil.Process]:
    rows = []
    for (pid, created), process in known.items():
        try:
            if (
                process.is_running()
                and process.status() != psutil.STATUS_ZOMBIE
                and process.pid == pid
                and abs(process.create_time() - created) < 0.001
            ):
                rows.append(process)
        except (psutil.Error, OSError):
            pass
    return rows


def _matching_existing(mode: str, exe: Path) -> list[dict[str, object]]:
    rows = []
    target_exe = exe.resolve() if mode == "packaged" else None
    for process in psutil.process_iter(["pid", "name"]):
        try:
            executable = Path(process.exe()).resolve()
            command = " ".join(process.cmdline())
            matches = (
                executable == target_exe
                if target_exe is not None
                else str((ROOT / "quick_start.py").resolve()).casefold() in command.casefold()
            )
            if matches:
                rows.append(_process_row(
                    process,
                    root_pid=process.pid,
                    packaged_exe=target_exe,
                ))
        except (psutil.Error, OSError):
            pass
    return rows


def _cleanup_owned(processes: list[psutil.Process]) -> dict[str, object]:
    requested = []
    for process in reversed(processes):
        try:
            requested.append({"pid": process.pid, "creation_time": process.create_time()})
            process.terminate()
        except (psutil.Error, OSError):
            pass
    _, alive = psutil.wait_procs(processes, timeout=5.0)
    forced = []
    for process in alive:
        try:
            forced.append(process.pid)
            process.kill()
        except (psutil.Error, OSError):
            pass
    _, alive = psutil.wait_procs(alive, timeout=3.0)
    return {
        "requested": requested,
        "forced_kill_pids": forced,
        "remaining_pids": [process.pid for process in alive],
    }


def _launch(
    mode: str,
    *,
    exe: Path,
    project: Path,
    second_media: Path,
    profile: Path,
    cycle_dir: Path,
) -> tuple[subprocess.Popen, list[str]]:
    environment = dict(os.environ)
    environment.update({
        "LOCALAPPDATA": str(profile),
        "TWOBYTEASR_NO_OPEN": "1",
        "TWOBYTEASR_STARTUP_OPEN_STUDIO": "1",
        "TWOBYTEASR_STARTUP_RAISE": "0",
        "TWOBYTEASR_STARTUP_PROJECT": str(project),
        "TWOBYTEASR_P8C_RUNTIME_AUDIT": "lifecycle",
        "TWOBYTEASR_P8C_RUNTIME_OUTPUT": str(cycle_dir),
        "TWOBYTEASR_P8B_SECOND_MEDIA": str(second_media),
        "TWOBYTEASR_STARTUP_TRACE": str(cycle_dir / "startup-trace.jsonl"),
        "TWOBYTEASR_CHILD_PROCESS_LOG": str(cycle_dir / "child-processes.jsonl"),
        "TWOBYTEASR_LAUNCH_MODE": "packaged" if mode == "packaged" else "source-dev",
    })
    environment.pop("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", None)
    environment.pop("TWOBYTEASR_P8B_RUNTIME_AUDIT", None)
    if mode == "packaged":
        command = [str(exe)]
        cwd = exe.parent
    else:
        command = [
            str(ROOT / ".venv-main" / "Scripts" / "python.exe"),
            "-B",
            str(ROOT / "quick_start.py"),
        ]
        cwd = ROOT
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ), command


def _cycle(
    mode: str,
    *,
    exe: Path,
    project: Path,
    second_media: Path,
    profile: Path,
    cycle_dir: Path,
    startup_timeout: float,
    close_timeout: float,
    index: int,
) -> dict[str, object]:
    cycle_dir.mkdir(parents=True, exist_ok=False)
    process, command = _launch(
        mode,
        exe=exe,
        project=project,
        second_media=second_media,
        profile=profile,
        cycle_dir=cycle_dir,
    )
    root = psutil.Process(process.pid)
    packaged_exe = exe if mode == "packaged" else None
    known: dict[tuple[int, float], psutil.Process] = {}
    result_path = cycle_dir / "runtime-result.json"
    ready_payload: dict[str, object] = {}
    failure = ""
    started = time.perf_counter()
    deadline = time.perf_counter() + startup_timeout
    while time.perf_counter() < deadline:
        _remember(root, known)
        ready_payload = _read_json(result_path)
        if ready_payload.get("ready_for_external_close"):
            break
        if process.poll() is not None:
            failure = f"application exited before lifecycle readiness: {process.returncode}"
            break
        time.sleep(0.05)
    else:
        failure = f"lifecycle readiness timed out after {startup_timeout:.1f}s"

    _remember(root, known)
    running = _running(known)
    windows = _windows_for_pids({item.pid for item in running})
    visible = [row for row in windows if row["visible"] and int(row["area"]) > 0]
    main_window = max(visible, key=lambda row: int(row["area"]), default={})
    process_rows = [
        _process_row(
            item,
            root_pid=process.pid,
            packaged_exe=packaged_exe,
            windows=windows,
        )
        for item in running
    ]
    close_posted = False
    close_elapsed_ms = None
    if not failure and not main_window:
        failure = "no visible application window owned by the process tree"
    if not failure and not bool(ready_payload.get("accepted")):
        failure = "application lifecycle audit was not accepted"
    if not failure:
        close_started = time.perf_counter()
        close_posted = bool(ctypes.windll.user32.PostMessageW(
            int(main_window["hwnd"]), WM_CLOSE, 0, 0
        ))
        if not close_posted:
            failure = f"PostMessageW(WM_CLOSE) failed: {ctypes.WinError()}"
        else:
            try:
                process.wait(timeout=close_timeout)
            except subprocess.TimeoutExpired:
                failure = f"application close timed out after {close_timeout:.1f}s"
            close_elapsed_ms = round((time.perf_counter() - close_started) * 1000.0, 3)

    residual_deadline = time.perf_counter() + 5.0
    residual = _running(known)
    while residual and time.perf_counter() < residual_deadline:
        time.sleep(0.05)
        residual = _running(known)
    residual_windows = _windows_for_pids({item.pid for item in residual})
    residual_rows = [
        _process_row(
            item,
            root_pid=process.pid,
            packaged_exe=packaged_exe,
            windows=residual_windows,
        )
        for item in residual
    ]
    if residual and not failure:
        failure = "tracked application processes remained after bounded close"
    cleanup = (
        _cleanup_owned(residual)
        if residual
        else {"requested": [], "forced_kill_pids": [], "remaining_pids": []}
    )
    false_single_instance = bool(
        process.returncode == 2
        or any("关闭2ByteASR" in str(row.get("title", "")) for row in windows)
    )
    if false_single_instance and not failure:
        failure = "false single-instance rejection"
    return {
        "cycle": index,
        "command": command,
        "root_pid": process.pid,
        "ready_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "runtime_result": str(result_path),
        "runtime_accepted": bool(ready_payload.get("accepted")),
        "runtime_checks": ready_payload.get("checks", {}),
        "runtime_phases": ready_payload.get("phases", {}),
        "child_process_events": _read_jsonl(cycle_dir / "child-processes.jsonl"),
        "processes_before_close": process_rows,
        "windows_before_close": windows,
        "main_window": main_window,
        "wm_close_posted": close_posted,
        "close_elapsed_ms": close_elapsed_ms,
        "exit_code": process.returncode,
        "false_single_instance": false_single_instance,
        "residual_processes": residual_rows,
        "cleanup": cleanup,
        "failure": failure,
        "pass": not failure and close_posted and process.returncode == 0 and not residual_rows,
    }


def main() -> int:
    args = _arguments()
    exe = args.exe.resolve()
    media = args.media.resolve()
    second_media = args.second_media.resolve()
    output = args.output.resolve()
    required = [media, second_media, *([exe] if args.mode == "packaged" else [])]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)

    before = _matching_existing(args.mode, exe)
    result: dict[str, object] = {
        "schema": "2byteasr.p8c-external-lifecycle.v1",
        "evidence_class": "PACKAGED EXTERNAL WM_CLOSE" if args.mode == "packaged" else "SOURCE EXTERNAL WM_CLOSE",
        "real_user_click": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "identity": {
            "exe": str(exe) if args.mode == "packaged" else "",
            "exe_sha256": _sha256(exe) if args.mode == "packaged" else "",
            "exe_bytes": exe.stat().st_size if args.mode == "packaged" else 0,
            "build_metadata": _read_json(exe.parent / "2byteasr_build.json") if args.mode == "packaged" else {},
        },
        "existing_processes_before_run": before,
        "cycles": [],
    }
    target = output / "runtime-result.json"
    if before:
        result["accepted"] = False
        result["blocker"] = "existing matching application process; no process was terminated"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"accepted": False, "blocker": result["blocker"], "output": str(target)}, ensure_ascii=False, indent=2))
        return 3

    profile = output / "localappdata"
    profile.mkdir()
    os.environ["LOCALAPPDATA"] = str(profile)
    from scripts.verify_p8c_runtime import _prepare_project

    project = _prepare_project(media, output / "project")
    cycles = result["cycles"]
    assert isinstance(cycles, list)
    for index in range(1, max(1, args.cycles) + 1):
        row = _cycle(
            args.mode,
            exe=exe,
            project=project,
            second_media=second_media,
            profile=profile,
            cycle_dir=output / f"cycle-{index:02d}",
            startup_timeout=args.startup_timeout,
            close_timeout=args.close_timeout,
            index=index,
        )
        cycles.append(row)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if row["pass"] is not True:
            break

    matching_after = _matching_existing(args.mode, exe)
    result["matching_processes_after_run"] = matching_after
    result["summary"] = {
        "requested_cycles": max(1, args.cycles),
        "completed_cycles": len(cycles),
        "passed_cycles": sum(row["pass"] is True for row in cycles),
        "failed_cycles": [row["cycle"] for row in cycles if row["pass"] is not True],
        "false_single_instance_cycles": [row["cycle"] for row in cycles if row["false_single_instance"]],
        "residual_cycles": [row["cycle"] for row in cycles if row["residual_processes"]],
        "max_close_ms": max((float(row["close_elapsed_ms"] or 0.0) for row in cycles), default=0.0),
    }
    result["accepted"] = bool(
        len(cycles) == max(1, args.cycles)
        and all(row["pass"] is True for row in cycles)
        and not matching_after
    )
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "accepted": result["accepted"],
        "summary": result["summary"],
        "matching_processes_after_run": matching_after,
        "output": str(target),
    }, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
