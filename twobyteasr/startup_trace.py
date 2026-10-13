"""Lightweight real-process startup milestones.

This module deliberately imports no Qt or application modules so it can be
used before the expensive desktop import graph begins.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path


_RUN_ID = os.environ.get("TWOBYTEASR_STARTUP_RUN_ID") or uuid.uuid4().hex
_PROCESS_CREATED_MS: float | None = None
_SEEN: set[str] = set()


def _process_created_ms() -> float:
    global _PROCESS_CREATED_MS
    if _PROCESS_CREATED_MS is not None:
        return _PROCESS_CREATED_MS
    launched = os.environ.get("TWOBYTEASR_PROCESS_START_MS", "").strip()
    if launched:
        try:
            _PROCESS_CREATED_MS = float(launched)
            return _PROCESS_CREATED_MS
        except ValueError:
            pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
                _PROCESS_CREATED_MS = ticks / 10_000 - 11_644_473_600_000
                return _PROCESS_CREATED_MS
        except Exception:
            pass
    _PROCESS_CREATED_MS = time.time() * 1000
    return _PROCESS_CREATED_MS


def _trace_path() -> Path:
    configured = os.environ.get("TWOBYTEASR_STARTUP_TRACE", "").strip()
    if configured:
        return Path(configured)
    # External model workers run a real Python, but load this module from the
    # same installed bundle. Both processes must treat its directory as read-only.
    # Isolated audits must not append to the repository's reports/ folder.
    if (getattr(sys, "frozen", False) or os.environ.get("TWOBYTEASR_TEST_ROOT")
            or (Path(__file__).resolve().parents[1] / "python310.dll").is_file()):
        from .runtime_paths import user_data_root
        return user_data_root() / "logs" / "startup-trace.jsonl"
    return Path(__file__).resolve().parents[1] / "reports" / "startup-trace.jsonl"


def mark(stage: str, **details: object) -> None:
    """Append one milestone once per process; tracing must never block launch."""
    stage = str(stage).strip().upper()
    if not stage or stage in _SEEN:
        return
    _SEEN.add(stage)
    now_ms = time.time() * 1000
    payload = {
        "run_id": _RUN_ID,
        "pid": os.getpid(),
        "stage": stage,
        "utc_ms": round(now_ms, 3),
        "elapsed_ms": round(max(0.0, now_ms - _process_created_ms()), 3),
        **details,
    }
    try:
        target = _trace_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


mark("PROCESS_START")
