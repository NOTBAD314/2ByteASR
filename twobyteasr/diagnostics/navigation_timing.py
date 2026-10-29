"""Opt-in bounded navigation phase timings; no Qt or per-frame disk writes.

Set TWOBYTEASR_NAVIGATION_TRACE=1 before starting. The acceptance driver or
support code can call snapshot(); flush(path) writes one explicit receipt.
Durations describe the named call, never readiness or physical presentation.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
import threading
import time

ENABLED = os.environ.get("TWOBYTEASR_NAVIGATION_TRACE") == "1"
_rows = deque(maxlen=8192)
_lock = threading.Lock()
_installed = False


@contextmanager
def phase(name):
    if not ENABLED:
        yield
        return
    start = time.perf_counter()
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        end = time.perf_counter()
        row = dict(phase=name, start=start, end=end,
                   ms=round((end-start)*1000, 3), failed=failed,
                   thread=threading.current_thread().name)
        with _lock:
            _rows.append(row)


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            if not ENABLED:
                return fn(*args, **kwargs)
            with phase(name):
                return fn(*args, **kwargs)
        return call
    return decorate


def snapshot(since=0.0):
    with _lock:
        return [dict(row) for row in _rows if row['start'] >= since]


def flush(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=2), 'utf8')


def install_shutdown_flush(app):
    """One bounded write on normal application exit, only when opted in."""
    global _installed
    if not ENABLED or _installed:
        return
    _installed = True
    def save():
        from ..runtime_paths import user_data_root
        target = os.environ.get('TWOBYTEASR_NAVIGATION_TRACE_FILE') or (
            user_data_root()/'logs'/f'navigation-{os.getpid()}.json')
        try:
            flush(target)
        except OSError:
            pass  # Diagnostics must never prevent application shutdown.
    app.aboutToQuit.connect(save)
