"""Measure a real launch from outside the process (Windows).

Timing starts in this script immediately before CreateProcess of the entry
(normally the root ``2ByteASR.exe`` launcher, the target of the user's
shortcuts), so launcher, bootloader and import time are included. For each run:

- ``window_visible_ms``: first visible top-level window of the GUI process;
- the app's own startup marks (``FIRST_PAINT``, ``INTERACTIVE``,
  ``BACKGROUND_READY``...) re-based on the same clock;
- ``responsive_ms``: first time the GUI thread answers ``WM_NULL`` within
  50 ms after the window appeared, and ``max_unresponsive_ms`` for the rest of
  the observation window (``SendMessageTimeout`` every ~25 ms), so a window
  that shows and then freezes is not counted as usable.

The app runs on a private desktop with ``TWOBYTEASR_TEST_ROOT`` pointing at a
profile made by ``prepare_startup_profile.py``; the user's own data is only
read by that preparation step. The window is closed with ``WM_CLOSE``.

Usage:
  python scripts/measure_startup_entry.py --entry 2ByteASR.exe \
      --profile tmp/startup-perf/profile-b --runs 5 --output tmp/startup-perf/base
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
user = ctypes.WinDLL("user32", use_last_error=True)
kernel = ctypes.WinDLL("kernel32", use_last_error=True)


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_byte)), ("hStdInput", W.HANDLE),
                ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class PROCESSINFO(ctypes.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


user.CreateDesktopW.argtypes = [W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, W.DWORD, W.DWORD, ctypes.c_void_p]
user.CreateDesktopW.restype = W.HANDLE
user.CloseDesktop.argtypes = [W.HANDLE]
user.IsWindowVisible.argtypes = [W.HWND]
user.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
user.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT, ctypes.POINTER(ctypes.c_size_t)]
user.SendMessageTimeoutW.restype = W.LPARAM
user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
ENUM_PROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
user.EnumDesktopWindows.argtypes = [W.HANDLE, ENUM_PROC, W.LPARAM]
kernel.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD,
                                  ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESSINFO)]
kernel.CloseHandle.argtypes = [W.HANDLE]
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]

WM_NULL, WM_CLOSE, SMTO_ABORTIFHUNG = 0x0000, 0x0010, 0x0002


def _gui_windows(desktop, pid):
    found = []

    def callback(hwnd, _):
        owner = W.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd):
            rect = W.RECT()
            user.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left >= 400 and rect.bottom - rect.top >= 300:
                found.append(hwnd)
        return True

    user.EnumDesktopWindows(desktop, ENUM_PROC(callback), 0)
    return found


def _read_trace(path):
    events = []
    try:
        for line in Path(path).read_text("utf8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return events


def _launch(command, env, desktop_name, cwd):
    startup = STARTUPINFO()
    startup.cb = ctypes.sizeof(startup)
    startup.lpDesktop = desktop_name
    info = PROCESSINFO()
    block = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(env.items())) + "\0\0")
    cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(x) for x in command]))
    started = time.time()
    ok = kernel.CreateProcessW(None, cmd, None, None, False, 0x400, block, str(cwd),
                               ctypes.byref(startup), ctypes.byref(info))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(info.hThread)
    kernel.CloseHandle(info.hProcess)
    return started, info.dwProcessId


def measure_once(args, run_index, out):
    trace = out / f"run{run_index}-startup.jsonl"
    env = os.environ.copy()
    for key in ("TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE", "TWOBYTEASR_ACCEPTANCE_DIR"):
        env.pop(key, None)
    env.update(TWOBYTEASR_TEST_ROOT=str(Path(args.profile).resolve()), TWOBYTEASR_STARTUP_TRACE=str(trace),
               QT_QPA_PLATFORM="windows", PYTHONUTF8="1")
    if args.entry.endswith(".py"):
        command = [str(ROOT / ".venv-main/Scripts/pythonw.exe"), str(ROOT / args.entry)]
    else:
        command = [str(Path(args.entry).resolve())]
    desktop_name = "2ByteASR-startup-" + uuid.uuid4().hex
    desktop = user.CreateDesktopW(desktop_name, None, None, 0, 0x01FF, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    record = {"run": run_index, "entry": command}
    try:
        t0, entry_pid = _launch(command, env, desktop_name, ROOT)
        t0_ms = t0 * 1000
        record["entry_pid"] = entry_pid
        gui_pid = None
        hwnd = None
        visible_at = None
        responsive_at = None
        probes = []
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            if gui_pid is None:
                for event in _read_trace(trace):
                    if event.get("stage") == "EARLY_INSTANCE_OWNER":
                        gui_pid = int(event["pid"])
                        break
                if gui_pid is None and args.entry.endswith(".py"):
                    gui_pid = None
            if gui_pid is not None and hwnd is None:
                windows = _gui_windows(desktop, gui_pid)
                if windows:
                    hwnd = windows[0]
                    visible_at = time.time() * 1000 - t0_ms
            if hwnd is not None:
                result = ctypes.c_size_t()
                sent = time.perf_counter()
                answered = user.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))
                latency = (time.perf_counter() - sent) * 1000
                now_ms = time.time() * 1000 - t0_ms
                probes.append((round(now_ms, 1), round(latency, 1) if answered else None))
                if responsive_at is None and answered and latency < 50:
                    responsive_at = now_ms
                if now_ms - visible_at >= args.observe * 1000:
                    break
            time.sleep(0.025)
        record.update(gui_pid=gui_pid, window_visible_ms=round(visible_at, 1) if visible_at else None,
                      responsive_ms=round(responsive_at, 1) if responsive_at else None)
        if probes and responsive_at is not None:
            after = [lat for at, lat in probes if at >= responsive_at]
            record["max_unresponsive_ms_after_responsive"] = max((lat or 2000) for lat in after) if after else None
            record["probes"] = len(probes)
        marks, durations = {}, {}
        for event in _read_trace(trace):
            if event.get("pid") == gui_pid and event.get("stage") not in marks:
                marks[event["stage"]] = round(float(event["utc_ms"]) - t0_ms, 1)
                if "duration_ms" in event:
                    durations[event["stage"]] = event["duration_ms"]
        record["marks"] = marks
        record["durations"] = durations
        if gui_pid:
            try:
                import psutil
                process = psutil.Process(gui_pid)
                io = process.io_counters()
                record["gui_read_mb"] = round(io.read_bytes / 1e6, 1)
                record["gui_rss_mb"] = round(process.memory_info().rss / 1e6, 1)
                record["children"] = [child.name() for child in process.children(recursive=True)]
            except Exception as exc:  # psutil missing or the process already gone
                record["io_error"] = repr(exc)
        record["probe_series"] = probes
        if hwnd is not None:
            user.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if gui_pid:
            handle = kernel.OpenProcess(0x00100000, False, gui_pid)
            if handle:
                record["closed_cleanly"] = kernel.WaitForSingleObject(handle, 30000) == 0
                kernel.CloseHandle(handle)
            if not record.get("closed_cleanly"):
                subprocess.run(["taskkill", "/PID", str(gui_pid), "/T", "/F"], capture_output=True)
    finally:
        user.CloseDesktop(desktop)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", default="2ByteASR.exe")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--observe", type=float, default=8.0, help="seconds to probe after the window appears")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--pause", type=float, default=3.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if not out.is_relative_to(ROOT / "tmp"):
        raise SystemExit("output must be under tmp/")
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(args.runs):
        record = measure_once(args, index, out)
        records.append(record)
        short = {k: record.get(k) for k in ("window_visible_ms", "responsive_ms", "max_unresponsive_ms_after_responsive")}
        short.update({k: record["marks"].get(k) for k in ("PYTHON_ENTRY", "IMPORTS_DONE", "MAIN_WINDOW_CREATED",
                                                          "FIRST_PAINT", "INTERACTIVE", "BACKGROUND_READY")})
        short["font_db_ms"] = record["durations"].get("FONT_FALLBACK_READY")
        short["read_mb"] = record.get("gui_read_mb")
        print(json.dumps(short, ensure_ascii=False), flush=True)
        time.sleep(args.pause)
    keys = ("window_visible_ms", "responsive_ms")
    summary = {}
    for key in keys:
        values = [r[key] for r in records if r.get(key) is not None]
        if values:
            summary[key] = {"min": min(values), "median": statistics.median(values), "max": max(values)}
    for stage in ("PYTHON_ENTRY", "IMPORTS_DONE", "MAIN_WINDOW_CREATED", "FIRST_SHOW", "FIRST_PAINT",
                  "INTERACTIVE", "BACKGROUND_READY"):
        values = [r["marks"][stage] for r in records if stage in r["marks"]]
        if values:
            summary[stage] = {"min": min(values), "median": statistics.median(values), "max": max(values)}
    (out / "records.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), "utf8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
