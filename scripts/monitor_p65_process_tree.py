"""External real-Runtime process/window monitor for P6.5 acceptance.

This script never imports or drives the application.  It observes the formal
quick_start process, every descendant, and relevant console/render processes;
the application-side canonical launcher log supplies creation flags and exit
codes for direct children while this monitor fills in grandchildren and HWNDs.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


TARGET_NAMES = {
    "cmd.exe", "conhost.exe", "ffmpeg.exe", "ffprobe.exe", "powershell.exe",
    "pwsh.exe", "node.exe", "agy.exe", "grok.exe", "mpv.exe", "python.exe",
    "pythonw.exe",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _windows_by_pid() -> dict[int, list[dict[str, object]]]:
    rows: dict[int, list[dict[str, object]]] = {}
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _lparam):
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = int(ctypes.windll.user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        rows.setdefault(int(pid.value), []).append({
            "hwnd": int(hwnd),
            "title": buffer.value,
            "visible": bool(ctypes.windll.user32.IsWindowVisible(hwnd)),
        })
        return True

    ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
    return rows


def _purpose(name: str, command: list[str]) -> str:
    lowered = " ".join(command).casefold()
    if name in {"ffmpeg.exe", "ffprobe.exe"}:
        if "project-cover" in lowered or "-frames:v 1" in lowered:
            return "thumbnail/frame extraction"
        return "media probe/render"
    if name == "cmd.exe" and ("remotion.cmd" in lowered or "node_modules\\.bin" in lowered):
        return "Remotion batch launcher"
    if name == "node.exe":
        return "Remotion/Node descendant"
    if name == "conhost.exe":
        return "Windows console host"
    if name in {"agy.exe", "grok.exe"}:
        return "AI provider CLI"
    if name == "mpv.exe":
        return "Studio media preview"
    return "runtime descendant"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--interval-ms", type=int, default=10)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    stop_file = Path(args.stop_file).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    observed: dict[int, dict[str, object]] = {}
    visible_hits: dict[tuple[int, int], dict[str, object]] = {}
    events: list[dict[str, object]] = []
    root_pid = int(args.root_pid)

    def append(event: dict[str, object]) -> None:
        events.append(event)

    while not stop_file.exists():
        try:
            processes = {process.pid: process for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"])}
        except (psutil.Error, OSError):
            processes = {}
        descendants = {root_pid}
        changed = True
        while changed:
            changed = False
            for pid, process in processes.items():
                try:
                    parent = int(process.info.get("ppid") or 0)
                except (TypeError, ValueError):
                    continue
                if parent in descendants and pid not in descendants:
                    descendants.add(pid)
                    changed = True
        windows = _windows_by_pid()
        alive_now: set[int] = set()
        for pid, process in processes.items():
            try:
                name = str(process.info.get("name") or "").casefold()
                # The acceptance scope is the launched quick_start tree.  Do
                # not admit unrelated system/user processes merely because
                # they own hidden IME helper HWNDs with a target-like name.
                if pid not in descendants:
                    continue
                command = [str(item) for item in (process.info.get("cmdline") or [])]
                row_windows = windows.get(pid, [])
                alive_now.add(pid)
                if pid not in observed:
                    row = {
                        "timestamp": _timestamp(),
                        "event": "start",
                        "parent_pid": int(process.info.get("ppid") or 0),
                        "child_pid": pid,
                        "executable": str(process.info.get("exe") or process.info.get("name") or ""),
                        "command": command,
                        "purpose": _purpose(name, command),
                        "creation_flags": None,
                        "window_title": " | ".join(str(item.get("title") or "") for item in row_windows),
                        "visible_hwnd": [item for item in row_windows if item.get("visible")],
                        "exit_code": None,
                    }
                    observed[pid] = row
                    append(row)
                for window in row_windows:
                    if not window.get("visible"):
                        continue
                    key = (pid, int(window["hwnd"]))
                    if key not in visible_hits:
                        hit = {
                            "timestamp": _timestamp(),
                            "event": "visible_window",
                            "parent_pid": int(process.info.get("ppid") or 0),
                            "child_pid": pid,
                            "executable": str(process.info.get("exe") or process.info.get("name") or ""),
                            "purpose": _purpose(name, command),
                            **window,
                        }
                        visible_hits[key] = hit
                        append(hit)
            except (psutil.Error, OSError, ValueError):
                continue
        for pid in set(observed) - alive_now:
            row = observed[pid]
            if row.get("ended"):
                continue
            row["ended"] = True
            append({
                "timestamp": _timestamp(),
                "event": "exit",
                "parent_pid": row["parent_pid"],
                "child_pid": pid,
                "executable": row["executable"],
                "command": row["command"],
                "purpose": row["purpose"],
                "creation_flags": None,
                "window_title": row["window_title"],
                "visible_hwnd": row["visible_hwnd"],
                "exit_code": None,
            })
        time.sleep(max(0.005, args.interval_ms / 1000.0))

    jsonl = output.with_suffix(".jsonl")
    jsonl.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in events), encoding="utf-8")
    relevant_visible = [
        row for row in visible_hits.values()
        if Path(str(row.get("executable") or "")).name.casefold()
        in {"cmd.exe", "conhost.exe", "ffmpeg.exe", "ffprobe.exe", "powershell.exe", "pwsh.exe", "node.exe"}
    ]
    summary = {
        "root_pid": root_pid,
        "sample_interval_ms": args.interval_ms,
        "observed_processes": len(observed),
        "processes": list(observed.values()),
        "visible_console_or_render_windows": relevant_visible,
        "visible_console_or_render_window_count": len(relevant_visible),
        "events_jsonl": str(jsonl),
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
