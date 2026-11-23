"""Idle storage maintenance in a process of its own, outside the GUI's Python lock.

2026-11-23 (user report: everything stuttered, a 40-minute video took 40 s to
open, the editor could not be used): the six-hourly pass ran as a thread of the
window process. On the user's PC it kept one core busy for over eight minutes
from a minute after start, and every paint, animation and caption job of the
window waited behind it for Python's lock. It now runs in this helper, at
below-normal priority, so it costs the window nothing.

The window owns the decision of when the app is busy: it writes ``busy`` /
``idle`` lines whenever that changes (it is the only place that can look at
its pages safely), and ``stop`` or a closed pipe ends the helper. Until the
first line arrives the helper treats the app as busy.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
FIRST_WORD_TIMEOUT_S = 30.0


def helper_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--storage-maintenance-worker']
    return [sys.executable, '-m', 'twobyteasr.storage.maintenance_process']


def start_helper():
    """Start the helper with a private stdin pipe; the caller owns the process."""
    from ..system.processes import hidden_subprocess_kwargs, popen_hidden_subprocess
    flags = int(hidden_subprocess_kwargs().get('creationflags', 0))
    if os.name == 'nt':
        flags |= BELOW_NORMAL_PRIORITY_CLASS
    return popen_hidden_subprocess(
        helper_command(), purpose='idle storage maintenance', cwd=str(Path(__file__).resolve().parents[2]),
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def _stdin_lines():
    """Text lines from the private pipe, also under the windowed bootloader (no sys.stdin)."""
    if sys.stdin is not None:
        return sys.stdin
    if os.name != 'nt':
        return iter(())
    import ctypes
    import io
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    handle = kernel.GetStdHandle(-10 & 0xffffffff)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        return iter(())
    raw = os.fdopen(msvcrt.open_osfhandle(handle, os.O_BINARY | os.O_RDONLY), 'rb', buffering=0)
    return io.TextIOWrapper(raw, encoding='utf8')


def listen(lines, busy, cancel, heard):
    """Apply the window's words; any end of the pipe cancels the pass."""
    try:
        for line in lines:
            word = line.strip()
            if word == 'busy':
                busy.set()
            elif word == 'idle':
                busy.clear()
            elif word == 'stop':
                break
            heard.set()
    except (OSError, ValueError):
        pass
    finally:
        cancel.set()
        heard.set()


def run(lines, *, maintain=None, service_factory=None):
    busy = threading.Event()
    busy.set()
    cancel = threading.Event()
    heard = threading.Event()
    threading.Thread(target=listen, args=(lines, busy, cancel, heard), name='storage-maintenance-pipe',
                     daemon=True).start()
    if not heard.wait(FIRST_WORD_TIMEOUT_S) or cancel.is_set() or busy.is_set():
        return None
    if service_factory is None:
        from .storage_service import StorageService
        service_factory = StorageService
    if maintain is None:
        from .storage_ui import maintain_registered_storage as maintain
    # Only an idle window starts the pass, and an idle window has no project
    # open, so there is no unsaved media graph to protect. Opening one turns the
    # window busy, which every step checks before it deletes anything.
    service = service_factory(busy=lambda: cancel.is_set() or busy.is_set(), media_references=lambda: None)
    return maintain(service, cancel)


def main():
    os.environ['TWOBYTEASR_PROCESS_ROLE'] = 'storage-maintenance'
    try:
        run(_stdin_lines())
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
