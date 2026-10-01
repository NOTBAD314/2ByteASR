"""Verify the frozen GUI image name, single-instance contract, and relaunches.

This drives the packaged Windows executable and posts WM_CLOSE to the real Qt
main window. It is automated process evidence, not user acceptance.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


WM_CLOSE = 0x0010


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def _window_for_pid(pid: int) -> tuple[int, str]:
    found: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _lparam):
        owner = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != int(pid) or not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = int(ctypes.windll.user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        found.append((int(hwnd), buffer.value))
        return True

    ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
    return found[0] if found else (0, "")


def _wait_for_window(process: subprocess.Popen, timeout: float) -> tuple[int, str, float]:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if process.poll() is not None:
            raise RuntimeError(f"2ByteASR exited before showing a window: {process.returncode}")
        hwnd, title = _window_for_pid(process.pid)
        if hwnd:
            return hwnd, title, (time.perf_counter() - started) * 1000.0
        time.sleep(0.025)
    raise TimeoutError(f"2ByteASR did not show a window within {timeout:.1f}s")


def _base_environment(output: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "LOCALAPPDATA": str(output / "localappdata"),
        "TWOBYTEASR_SKIP_FIRST_RUN_WIZARD": "1",
        "TWOBYTEASR_CHILD_PROCESS_LOG": str(output / "children.jsonl"),
    })
    env.pop("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", None)
    return env


def _launch(exe: Path, output: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=_base_environment(output),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _descendants(pid: int) -> list[dict[str, object]]:
    try:
        return [
            {"pid": child.pid, "name": child.name(), "command": child.cmdline()}
            for child in psutil.Process(pid).children(recursive=True)
        ]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def _alive(pids: set[int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pid in sorted(pids):
        try:
            process = psutil.Process(pid)
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                rows.append({"pid": pid, "name": process.name(), "command": process.cmdline()})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


def _close_cycle(exe: Path, output: Path, timeout: float, index: int) -> dict[str, object]:
    started = time.perf_counter()
    process = _launch(exe, output)
    seen_children: set[int] = set()
    try:
        hwnd, title, window_ms = _wait_for_window(process, timeout)
        image_name = psutil.Process(process.pid).name()
        seen_children.update(row["pid"] for row in _descendants(process.pid))
        close_started = time.perf_counter()
        if not ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
            raise ctypes.WinError()
        process.wait(timeout=timeout)
        close_ms = (time.perf_counter() - close_started) * 1000.0
        deadline = time.perf_counter() + 3.0
        residual = _alive(seen_children)
        while residual and time.perf_counter() < deadline:
            time.sleep(0.05)
            residual = _alive(seen_children)
        return {
            "cycle": index,
            "pid": process.pid,
            "image_name": image_name,
            "window_title": title,
            "window_ms": round(window_ms, 3),
            "close_ms": round(close_ms, 3),
            "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "exit_code": process.returncode,
            "residual_children": residual,
            "pass": image_name.casefold() == "2byteasr.exe" and process.returncode == 0 and not residual,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)


def _live_owner_case(exe: Path, output: Path, timeout: float) -> dict[str, object]:
    owner = _launch(exe, output)
    contender: subprocess.Popen | None = None
    try:
        hwnd, title, window_ms = _wait_for_window(owner, timeout)
        contender = _launch(exe, output)
        contender_deadline = time.perf_counter() + 8.0
        contender_dialog = ""
        while contender.poll() is None and time.perf_counter() < contender_deadline:
            dialog_hwnd, dialog_title = _window_for_pid(contender.pid)
            if dialog_hwnd:
                contender_dialog = dialog_title
                ctypes.windll.user32.PostMessageW(dialog_hwnd, WM_CLOSE, 0, 0)
            time.sleep(0.025)
        contender.wait(timeout=2.0)
        contender_code = contender.returncode
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        owner.wait(timeout=timeout)
        return {
            "owner_pid": owner.pid,
            "owner_title": title,
            "owner_window_ms": round(window_ms, 3),
            "contender_pid": contender.pid,
            "contender_dialog": contender_dialog,
            "contender_exit_code": contender_code,
            "owner_exit_code": owner.returncode,
            "pass": contender_code == 2 and owner.returncode == 0,
        }
    finally:
        for process in (contender, owner):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5.0)


def _crash_recovery_case(exe: Path, output: Path, timeout: float) -> dict[str, object]:
    crashed = _launch(exe, output)
    hwnd, title, window_ms = _wait_for_window(crashed, timeout)
    del hwnd
    crashed_pid = crashed.pid
    descendants = {row["pid"] for row in _descendants(crashed.pid)}
    crashed.kill()
    crashed.wait(timeout=5.0)
    recovery = _close_cycle(exe, output, timeout, 0)
    return {
        "crashed_pid": crashed_pid,
        "crashed_title": title,
        "crashed_window_ms": round(window_ms, 3),
        "crash_exit_code": crashed.returncode,
        "crash_residual_children": _alive(descendants),
        "recovery": recovery,
        "pass": not _alive(descendants) and recovery["pass"] is True,
    }


def main() -> int:
    args = _arguments()
    exe = args.exe.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not exe.is_file() or exe.name.casefold() != "2byteasr.exe":
        raise FileNotFoundError(exe)

    result: dict[str, object] = {
        "evidence": "PACKAGED WINDOWS GUI PROCESS",
        "real_user_click": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "exe": str(exe),
        "cycles": [],
    }
    target = output / "runtime-result.json"
    rows = result["cycles"]
    assert isinstance(rows, list)
    for index in range(1, max(1, args.cycles) + 1):
        rows.append(_close_cycle(exe, output, args.timeout, index))
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    result["live_owner"] = _live_owner_case(exe, output, args.timeout)
    result["crash_recovery"] = _crash_recovery_case(exe, output, args.timeout)
    result["summary"] = {
        "cycle_count": len(rows),
        "passed_cycles": sum(row["pass"] is True for row in rows),
        "max_window_ms": max(float(row["window_ms"]) for row in rows),
        "max_close_ms": max(float(row["close_ms"]) for row in rows),
        "image_names": sorted({str(row["image_name"]) for row in rows}),
        "failed_cycles": [row["cycle"] for row in rows if row["pass"] is not True],
    }
    result["accepted"] = bool(
        all(row["pass"] is True for row in rows)
        and result["live_owner"]["pass"] is True
        and result["crash_recovery"]["pass"] is True
    )
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "accepted": result["accepted"],
        "summary": result["summary"],
        "live_owner": result["live_owner"],
        "crash_recovery_pass": result["crash_recovery"]["pass"],
        "output": str(target),
    }, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
