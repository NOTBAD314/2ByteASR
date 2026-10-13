"""Low-overhead GUI-thread stall watchdog for real sessions.

A 50 ms Qt heartbeat marks the GUI thread alive; a daemon thread checks the
heartbeat age every 50 ms. When the GUI thread has not run its heartbeat for
``STALL_MS`` the daemon samples the GUI thread's Python stack (function names
and line numbers only: no locals, subtitle text or paths beyond file names)
until the heartbeat returns, then one ``GUI_STALL`` record goes to the Studio
trace. A stall that lasts longer than ``ONGOING_MS`` is also written while it
is still happening, so a freeze that ends with the process being killed still
leaves evidence. Steady state writes nothing: no per-frame logging.

The sampler is a Python thread, so it cannot sample while another thread
holds the GIL inside a long C call. Two additions cover that case: the GUI
heartbeat itself reports a stall the sampler never saw (``samples: 0``), and
``faulthandler.dump_traceback_later`` (a C thread that needs no GIL) is
re-armed from the heartbeat; when the GUI thread misses it for
``HANG_DUMP_S`` the stacks of every thread go to
``logs/gui-hang-<pid>.txt``, which becomes a ``GUI_HANG_DUMP`` record once
the GUI thread runs again (the file stays if the process is killed first).

Set ``TWOBYTEASR_STALL_WATCHDOG=0`` to disable it, ``TWOBYTEASR_HANG_DUMP=0``
to keep only the Python sampler.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer


BEAT_MS = 50
STALL_MS = 250.0
ONGOING_MS = 2000.0
STACK_DEPTH = 18
MAX_RECORDS = 400
HANG_DUMP_S = 2.0
HANG_REARM_S = 0.5
HANG_DUMP_CHARS = 24000


def _frame_chain(frame) -> tuple[str, ...]:
    chain = []
    while frame is not None and len(chain) < STACK_DEPTH:
        code = frame.f_code
        chain.append(f"{Path(code.co_filename).name}:{frame.f_lineno}:{code.co_name}")
        frame = frame.f_back
    return tuple(chain)


class GuiStallWatchdog(QObject):
    """One per process; see :func:`install`."""

    def __init__(self, parent=None, *, sink: Callable[[str, dict], None] | None = None) -> None:
        super().__init__(parent)
        self._sink = sink
        self._main_ident = threading.main_thread().ident
        now = time.perf_counter()
        self._last_beat = now
        self._previous_beat = now
        self._lags: deque[tuple[float, float]] = deque(maxlen=4096)
        self._stall_started = 0.0
        self._stall_samples: Counter[tuple[str, ...]] = Counter()
        self._stall_ongoing_written = False
        self._pending: list[dict] = []
        self._records = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._context: dict[str, Callable[[], dict]] = {}
        self._native_probes: dict[str, Callable[[], dict]] = {}
        self._stall_native: dict | None = None
        self.stall_count = 0
        self.longest_stall_ms = 0.0
        self.recent: deque[dict] = deque(maxlen=64)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(BEAT_MS)
        self._timer.timeout.connect(self._beat)
        self._thread = threading.Thread(target=self._watch, name="gui-stall-watchdog", daemon=True)
        self._dump_file = None
        self._dump_path: Path | None = None
        self._dump_armed_at = 0.0

    def start(self, *, hang_dump_path: Path | None = None) -> None:
        self._last_beat = self._previous_beat = time.perf_counter()
        if hang_dump_path is not None:
            try:
                hang_dump_path.parent.mkdir(parents=True, exist_ok=True)
                self._dump_file = open(hang_dump_path, "w+b", buffering=0)
                self._dump_path = hang_dump_path
                self._arm_hang_dump(self._last_beat)
            except (OSError, ValueError, RuntimeError):
                self._close_dump(remove=True)
        self._timer.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()
        self._close_dump(remove=True)

    # ------------------------------------------------- native hang dump
    def _arm_hang_dump(self, now: float) -> None:
        if self._dump_file is None:
            return
        self._dump_armed_at = now
        try:
            faulthandler.dump_traceback_later(HANG_DUMP_S, repeat=False, file=self._dump_file)
        except (OSError, ValueError, RuntimeError):
            self._close_dump(remove=True)

    def _collect_hang_dump(self) -> None:
        handle = self._dump_file
        if handle is None:
            return
        try:
            fd = handle.fileno()
            size = os.fstat(fd).st_size
            if size <= 0:
                return
            os.lseek(fd, 0, os.SEEK_SET)
            text = os.read(fd, min(size, HANG_DUMP_CHARS * 4)).decode("utf-8", "replace")
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
        except OSError:
            return
        self._emit({"kind": "GUI_HANG_DUMP", "after_s": HANG_DUMP_S,
                    "text": text[:HANG_DUMP_CHARS], "truncated": len(text) > HANG_DUMP_CHARS})

    def _close_dump(self, *, remove: bool) -> None:
        handle, path = self._dump_file, self._dump_path
        self._dump_file = None
        if handle is None:
            return
        try:
            faulthandler.cancel_dump_traceback_later()
        except Exception:
            pass
        try:
            empty = os.fstat(handle.fileno()).st_size == 0
            handle.close()
            if remove and empty and path is not None:
                path.unlink()
        except OSError:
            pass

    def add_context(self, name: str, provider: Callable[[], dict]) -> None:
        """Provider runs on the GUI thread right after a stall ends."""
        self._context[str(name)] = provider

    def remove_context(self, name: str) -> None:
        self._context.pop(str(name), None)

    def add_native_probe(self, name: str, probe: Callable[[], dict]) -> None:
        """Probe run ON THE WATCHDOG THREAD once per stall (after 500 ms).

        It must not touch Qt or Python objects owned by the GUI thread; use
        plain values captured earlier (e.g. an HWND int) and OS calls.
        """
        self._native_probes[str(name)] = probe

    def _run_native_probes(self) -> dict:
        results = {}
        for name, probe in list(self._native_probes.items()):
            try:
                results[name] = probe()
            except Exception as exc:
                results[name] = {"error": f"{type(exc).__name__}: {exc}"}
        return results

    # ------------------------------------------------------------ GUI thread
    def _beat(self) -> None:
        now = time.perf_counter()
        previous = self._previous_beat
        lag = max(0.0, (now - previous) * 1000.0 - BEAT_MS)
        self._previous_beat = now
        self._last_beat = now
        self._lags.append((now, lag))
        if lag >= STALL_MS and self._stall_started != previous:
            # The sampler thread never ran during this gap (GIL held by a C
            # call elsewhere, or the whole process was descheduled).
            self.stall_count += 1
            self.longest_stall_ms = max(self.longest_stall_ms, lag + BEAT_MS)
            with self._lock:
                self._pending.append({"kind": "GUI_STALL", "duration_ms": round(lag + BEAT_MS, 1),
                                      "samples": 0, "stacks": [], "unsampled": True})
        if self._dump_file is not None:
            if lag >= 1000.0:
                self._collect_hang_dump()
            if now - self._dump_armed_at >= HANG_REARM_S:
                self._arm_hang_dump(now)
        with self._lock:
            pending, self._pending = self._pending, []
        for record in pending:
            context = {}
            for name, provider in list(self._context.items()):
                try:
                    context[name] = provider()
                except Exception as exc:  # diagnostics never break the app
                    context[name] = {"error": f"{type(exc).__name__}: {exc}"}
            record["context_after"] = context
            self._emit(record)

    def lag_stats(self, window_s: float = 1.0) -> dict:
        """Event-loop lag over the last ``window_s`` seconds (GUI thread)."""
        cutoff = time.perf_counter() - float(window_s)
        values = [lag for at, lag in self._lags if at >= cutoff]
        return {
            "window_s": float(window_s),
            "beats": len(values),
            "max_lag_ms": round(max(values), 1) if values else None,
            "over_50ms": sum(1 for v in values if v >= 50),
            "over_100ms": sum(1 for v in values if v >= 100),
            "over_250ms": sum(1 for v in values if v >= 250),
            "stalls_total": self.stall_count,
            "longest_stall_ms": round(self.longest_stall_ms, 1),
        }

    # ------------------------------------------------------- watchdog thread
    def _watch(self) -> None:
        while not self._stop.wait(BEAT_MS / 1000.0):
            now = time.perf_counter()
            last = self._last_beat
            age = (now - last) * 1000.0
            if age >= STALL_MS:
                if not self._stall_started or self._stall_started != last:
                    self._stall_started = last
                    self._stall_samples = Counter()
                    self._stall_ongoing_written = False
                    self._stall_native = None
                frame = sys._current_frames().get(self._main_ident)
                if frame is not None:
                    self._stall_samples[_frame_chain(frame)] += 1
                del frame
                if age >= 500.0 and self._stall_native is None and self._native_probes:
                    self._stall_native = self._run_native_probes()
                if age >= ONGOING_MS and not self._stall_ongoing_written:
                    self._stall_ongoing_written = True
                    self._emit(self._record("GUI_STALL_ONGOING", age))
            elif self._stall_started:
                duration = (self._last_beat - self._stall_started) * 1000.0
                record = self._record("GUI_STALL", duration)
                self._stall_started = 0.0
                self.stall_count += 1
                self.longest_stall_ms = max(self.longest_stall_ms, duration)
                with self._lock:
                    self._pending.append(record)

    def _record(self, kind: str, duration_ms: float) -> dict:
        total = sum(self._stall_samples.values())
        stacks = [
            {"samples": count, "frames": list(chain)}
            for chain, count in self._stall_samples.most_common(4)
        ]
        record = {"kind": kind, "duration_ms": round(duration_ms, 1),
                  "samples": total, "stacks": stacks}
        if self._stall_native is not None:
            record["native"] = self._stall_native
        return record

    def _emit(self, record: dict) -> None:
        if self._records >= MAX_RECORDS:
            return
        self._records += 1
        self.recent.append(dict(record))
        try:
            kind = str(record.pop("kind", "GUI_STALL"))
            if self._sink is not None:
                self._sink(kind, record)
                return
            from .runtime_trace import GLOBAL_STUDIO_TRACE
            GLOBAL_STUDIO_TRACE.emit(kind, record)
        except Exception:
            pass


def probe_embedded_windows(parent_hwnd: int, *, timeout_ms: int = 200) -> dict:
    """Is the cross-process child window (mpv --wid) answering messages?

    Windows attaches the input queues of a parent window's thread and a
    child window's thread in another process; a busy or hung child thread
    can then stall the parent's GUI thread. Runs on the watchdog thread.
    """
    if os.name != "nt" or not parent_hwnd:
        return {"parent": int(parent_hwnd or 0), "children": []}
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    children: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd, _lparam):
        if len(children) < 8:
            children.append(int(hwnd))
        return True
    user32.EnumChildWindows(wintypes.HWND(parent_hwnd), callback_type(collect), 0)
    own_pid = os.getpid()
    rows = []
    for hwnd in children:
        pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if int(pid.value) == own_pid:
            continue
        result = ctypes.c_size_t()
        started = time.perf_counter()
        answered = user32.SendMessageTimeoutW(wintypes.HWND(hwnd), 0, 0, 0, 0x0002 | 0x0001,
                                              int(timeout_ms), ctypes.byref(result))
        rows.append({"hwnd": hwnd, "pid": int(pid.value), "tid": int(tid),
                     "answered": bool(answered),
                     "answer_ms": round((time.perf_counter() - started) * 1000, 1),
                     "hung": bool(user32.IsHungAppWindow(wintypes.HWND(hwnd)))})
    return {"parent": int(parent_hwnd), "foreign_children": rows}


_INSTANCE: GuiStallWatchdog | None = None


def install(parent=None) -> GuiStallWatchdog | None:
    """Start the process-wide watchdog once (GUI thread)."""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    if os.environ.get("TWOBYTEASR_STALL_WATCHDOG", "1").strip() in {"0", "false", "off"}:
        return None
    _INSTANCE = GuiStallWatchdog(parent)
    _INSTANCE.start(hang_dump_path=_hang_dump_path())
    return _INSTANCE


def _hang_dump_path() -> Path | None:
    """``logs/gui-hang-<pid>.txt`` unless disabled or owned by an audit.

    Only one ``dump_traceback_later`` timer exists per process; acceptance
    scenarios that arm their own periodic dumps keep theirs.
    """
    if os.environ.get("TWOBYTEASR_HANG_DUMP", "1").strip() in {"0", "false", "off"}:
        return None
    scenario = os.environ.get("TWOBYTEASR_ACCEPTANCE_SCENARIO", "").strip()
    if scenario and scenario != "perf-regression":
        return None
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("TWOBYTEASR_HANG_DUMP") != "1":
        return None  # pytest may own the faulthandler timer (faulthandler_timeout)
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "2ByteASR" / "logs" / f"gui-hang-{os.getpid()}.txt"


def instance() -> GuiStallWatchdog | None:
    return _INSTANCE
