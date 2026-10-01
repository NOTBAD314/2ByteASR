"""P7.1B headed end-to-end Studio interaction latency profiler.

The harness opens the production MainWindow on the Windows QPA backend, loads
the checked-in two-hour real-media fixture, and drives the visible widgets via
QTest.  It deliberately reports command return, first timeline paint, visual
state correctness, event-loop settlement, and worker completion separately.

Usage::

    python scripts/profile_studio_interaction_latency.py --label before
    python scripts/profile_studio_interaction_latency.py --label after
"""

from __future__ import annotations

import argparse
import collections
import copy
import gc
import json
import os
import pickle
import shutil
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="profile")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--settle-timeout", type=float, default=6.0)
    parser.add_argument(
        "--viewport",
        choices=("overview", "zoom30"),
        default="overview",
        help="Timeline viewport used by Razor and seek actions.",
    )
    parser.add_argument(
        "--dense-cues",
        type=int,
        default=0,
        help="Scale the existing 10k-cue soak fixture onto the real long media.",
    )
    parser.add_argument(
        "--low-perturbation",
        action="store_true",
        help=(
            "Measure latency without per-method call wrappers and collect prior "
            "profiler allocations between actions."
        ),
    )
    parser.add_argument(
        "--collect-before-action",
        action="store_true",
        help="Run a full Python collection before each timed action.",
    )
    return parser.parse_args()


ARGS = _arguments()
OUTPUT = (ARGS.output or ROOT / "tmp" / "p71b" / ARGS.label).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
PROJECT_COPY = OUTPUT / "p71b-real-hour.2byteproj"
shutil.copy2(SOURCE_PROJECT, PROJECT_COPY)
if ARGS.dense_cues > 0:
    project_payload = json.loads(PROJECT_COPY.read_text(encoding="utf-8"))
    dense_source = (
        ROOT / "tmp" / "p22.9-real-workflow" / "soak-10000.2byteproj"
    )
    dense_payload = json.loads(dense_source.read_text(encoding="utf-8"))
    source_duration = max(1, int(dense_payload["media"]["duration_ms"]))
    target_duration = max(1, int(project_payload["media"]["duration_ms"]))
    scale = target_duration / source_duration
    cues = []
    for item in dense_payload["cues"][: max(0, ARGS.dense_cues)]:
        cue = dict(item)
        cue["start_ms"] = min(target_duration - 2, round(int(cue["start_ms"]) * scale))
        cue["end_ms"] = min(target_duration - 1, max(
            cue["start_ms"] + 1,
            round(int(cue["end_ms"]) * scale),
        ))
        cues.append(cue)
    project_payload["cues"] = cues
    PROJECT_COPY.write_text(
        json.dumps(project_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
RUNTIME_LOCALAPPDATA = OUTPUT / f"localappdata-{os.getpid()}"
WAVEFORM_CACHE_SEED = (
    ROOT
    / "tmp"
    / "p7-audit"
    / "actions"
    / "localappdata-37080"
    / "2ByteASR"
    / "SubtitleStudioPreview"
    / "waveform-cache"
)
if WAVEFORM_CACHE_SEED.is_dir():
    shutil.copytree(
        WAVEFORM_CACHE_SEED,
        RUNTIME_LOCALAPPDATA
        / "2ByteASR"
        / "SubtitleStudioPreview"
        / "waveform-cache",
        dirs_exist_ok=True,
    )
ENCODER_CACHE_SEED = (
    ROOT
    / "tmp"
    / "p7-audit"
    / "actions"
    / "localappdata-37080"
    / "2ByteASR"
    / "SubtitleStudio"
    / "encoder-capabilities.json"
)
if ENCODER_CACHE_SEED.is_file():
    encoder_target = (
        RUNTIME_LOCALAPPDATA
        / "2ByteASR"
        / "SubtitleStudio"
        / "encoder-capabilities.json"
    )
    encoder_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ENCODER_CACHE_SEED, encoder_target)

os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(RUNTIME_LOCALAPPDATA)
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
os.environ["TWOBYTEASR_INTERACTION_LATENCY_PATH"] = str(
    OUTPUT / "command-return-latency.json"
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QApplication

import moss_firered_pipeline
import psutil
import subtitle_core
from twobyteasr import ui
from twobyteasr.processes import child_process_start_count
from twobyteasr.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
from twobyteasr.studio_cue_controller import StudioCueController
from twobyteasr.studio_edit_commands import EditSequenceCommand
from twobyteasr.studio_edit_sequence import runtime_of as sequence_runtime_of, sequence_of
from twobyteasr.studio_mpv import MpvController
from twobyteasr.studio_project import save_autosave
from twobyteasr.studio_runtime_state import StateTransaction, state_for
from twobyteasr.studio_ui import MpvCanvas, SubtitleStudioPage, WaveformTimeline
from twobyteasr.style_recipe import FillSpec
from twobyteasr.teach_hints import TeachHintStore
from twobyteasr.window_audit import qt_top_level_widgets, win32_top_level_windows


MEDIA = Path(json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))["media"]["path"])
CURRENT_ACTION = "startup"
IPC_RECORDS: list[dict[str, Any]] = []
CALL_RECORDS: list[dict[str, Any]] = []
THREAD_RECORDS: list[dict[str, Any]] = []
ACTIVE_CALLS: list[str] = []
LAST_COMPLETED_CALL = ""
COMMAND_START_NS: dict[str, int] = {}
ORIGINALS: list[tuple[type, str, Any]] = []


def progress(message: str) -> None:
    print(f"[p71b] {message}", flush=True)


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        QTest.qWait(4)


def wait_until(
    app: QApplication,
    predicate: Callable[[], bool],
    timeout: float,
    label: str,
) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return (time.perf_counter() - started) * 1000.0
        QTest.qWait(8)
    raise TimeoutError(f"{label} not ready in {timeout:.1f}s")


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return round(ordered[index], 3)


def summary(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return {
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": round(max(values), 3) if values else 0.0,
    }


class EventMonitor(QObject):
    """Count relevant Qt work and timestamp timeline feedback paints."""

    EVENT_NAMES = {
        QEvent.Type.Paint: "paint",
        QEvent.Type.UpdateRequest: "update_request",
        QEvent.Type.LayoutRequest: "layout_request",
        QEvent.Type.Resize: "resize",
        QEvent.Type.Show: "show",
        QEvent.Type.Hide: "hide",
    }

    def __init__(self) -> None:
        super().__init__()
        self.timeline: WaveformTimeline | None = None
        self.counts: collections.Counter[str] = collections.Counter()
        self.timeline_paints: list[dict[str, Any]] = []

    def eventFilter(self, watched, event) -> bool:
        name = self.EVENT_NAMES.get(event.type())
        if name:
            self.counts[name] += 1
        if watched is self.timeline and event.type() == QEvent.Type.Paint:
            region = event.region().boundingRect() if hasattr(event, "region") else QRect()
            self.timeline_paints.append(
                {
                    "action": CURRENT_ACTION,
                    "time_ns": time.perf_counter_ns(),
                    "x": region.x(),
                    "y": region.y(),
                    "width": region.width(),
                    "height": region.height(),
                }
            )
        return False

    def snapshot(self) -> tuple[dict[str, int], int]:
        return dict(self.counts), len(self.timeline_paints)

    def delta(self, before: tuple[dict[str, int], int]) -> dict[str, Any]:
        counts, paint_index = before
        return {
            "events": {
                name: int(self.counts.get(name, 0)) - int(counts.get(name, 0))
                for name in sorted(set(self.EVENT_NAMES.values()))
            },
            "timeline_paints": copy.deepcopy(self.timeline_paints[paint_index:]),
        }


class EventLoopLag:
    """High precision event-loop heartbeat with threshold buckets."""

    THRESHOLDS = (16, 33, 50, 100, 250, 500, 1000)

    def __init__(self, parent: QObject, interval_ms: int = 8) -> None:
        self.interval_ms = float(interval_ms)
        self.samples: list[dict[str, Any]] = []
        self._last_ns = time.perf_counter_ns()
        self.timer = QTimer(parent)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self) -> None:
        now = time.perf_counter_ns()
        lateness = max(0.0, (now - self._last_ns) / 1_000_000 - self.interval_ms)
        self._last_ns = now
        self.samples.append(
            {
                "action": CURRENT_ACTION,
                "lateness_ms": round(lateness, 3),
                "caller_context": ACTIVE_CALLS[-1] if ACTIVE_CALLS else LAST_COMPLETED_CALL,
                "time_ns": now,
            }
        )

    def reset(self) -> int:
        self._last_ns = time.perf_counter_ns()
        return len(self.samples)

    def report_since(self, index: int) -> dict[str, Any]:
        rows = self.samples[index:]
        values = [float(row["lateness_ms"]) for row in rows]
        return {
            "samples": rows,
            "p95_ms": percentile(values, 0.95),
            "max_ms": round(max(values), 3) if values else 0.0,
            "threshold_counts": {
                str(limit): sum(value > limit for value in values)
                for limit in self.THRESHOLDS
            },
            "stalls": [
                row for row in rows if float(row["lateness_ms"]) > self.THRESHOLDS[0]
            ],
        }


def _install_probes(*, detailed_calls: bool = True) -> None:
    original_send = MpvController._send

    def audited_send(self, command, timeout=2.0):
        values = list(command)
        started = time.perf_counter_ns()
        try:
            return original_send(self, values, timeout=timeout)
        finally:
            IPC_RECORDS.append(
                {
                    "action": CURRENT_ACTION,
                    "command": str(values[0] if values else ""),
                    "detail": str(values[1] if len(values) > 1 else ""),
                    "elapsed_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
                    "thread": threading.current_thread().name,
                    "ui_blocking": threading.current_thread() is threading.main_thread(),
                }
            )

    ORIGINALS.append((MpvController, "_send", original_send))
    MpvController._send = audited_send

    original_thread_start = threading.Thread.start

    def audited_thread_start(self, *args, **kwargs):
        THREAD_RECORDS.append(
            {
                "action": CURRENT_ACTION,
                "name": self.name,
                "daemon": self.daemon,
                "time_ns": time.perf_counter_ns(),
            }
        )
        return original_thread_start(self, *args, **kwargs)

    ORIGINALS.append((threading.Thread, "start", original_thread_start))
    threading.Thread.start = audited_thread_start

    if not detailed_calls:
        return

    targets = {
        SubtitleStudioPage: (
            "_set_timeline_tool",
            "_show_teach_hint",
            "_razor_video_at",
            "_undo_interactive",
            "_redo_interactive",
            "_sequence_changed",
            "_refresh_edit_playback_state",
            "_schedule_render_refresh",
            "_refresh_ass_preview",
            "_start_ass_worker",
            "_ass_ready",
            "_schedule_autosave",
            "_autosave",
            "_start_autosave_worker",
            "_autosave_ready",
            "_flush_deferred_updates",
            "_refresh_checks",
            "_position_changed",
            "_seek",
        ),
        StudioCueController: ("consume_state_delta", "select_cue", "set_timing"),
        EditSequenceCommand: ("__init__", "_apply", "redo", "undo"),
        StateTransaction: ("_capture_domains", "_validate_and_commit"),
        TeachHintStore: ("should_show", "mark_shown", "load", "_save"),
        WaveformTimeline: ("reindex_project", "paintEvent", "set_playhead"),
        MpvCanvas: ("_reconcile_position", "reload_subtitle", "seek"),
    }
    command_entries = {
        "SubtitleStudioPage._razor_video_at",
        "SubtitleStudioPage._undo_interactive",
        "SubtitleStudioPage._redo_interactive",
        "StudioCueController.select_cue",
        "StudioCueController.set_timing",
        "MpvCanvas.seek",
    }
    for owner, names in targets.items():
        for name in names:
            original = getattr(owner, name, None)
            if original is None:
                continue
            key = f"{owner.__name__}.{name}"

            def make_wrapper(function, method_key):
                def wrapper(*args, **kwargs):
                    global LAST_COMPLETED_CALL
                    if method_key in command_entries:
                        COMMAND_START_NS.setdefault(CURRENT_ACTION, time.perf_counter_ns())
                    started = time.perf_counter_ns()
                    ACTIVE_CALLS.append(method_key)
                    try:
                        return function(*args, **kwargs)
                    finally:
                        elapsed = (time.perf_counter_ns() - started) / 1_000_000
                        if ACTIVE_CALLS:
                            ACTIVE_CALLS.pop()
                        LAST_COMPLETED_CALL = method_key
                        CALL_RECORDS.append(
                            {
                                "action": CURRENT_ACTION,
                                "method": method_key,
                                "elapsed_ms": round(elapsed, 3),
                                "thread": threading.current_thread().name,
                                "ui_blocking": threading.current_thread() is threading.main_thread(),
                            }
                        )

                return wrapper

            ORIGINALS.append((owner, name, original))
            setattr(owner, name, make_wrapper(original, key))


def _restore_probes() -> None:
    while ORIGINALS:
        owner, name, original = ORIGINALS.pop()
        setattr(owner, name, original)


def _thread_alive(page: SubtitleStudioPage, attr: str) -> bool:
    thread = getattr(page, attr, None)
    return bool(thread is not None and thread.is_alive())


def _settlement_fingerprint(page: SubtitleStudioPage) -> tuple[Any, ...]:
    runtime = state_for(page.project)
    sequence_runtime = sequence_runtime_of(page.project)
    sequence = sequence_runtime.sequence
    advanced = getattr(page, "_advanced_preview_state", None)
    revision_store = getattr(page.project, "_studio_revision_store", None)
    render_revision = getattr(revision_store, "render", None)
    return (
        runtime.revision,
        sequence_runtime.revision,
        len(sequence.segments),
        len(page.project.cues),
        getattr(render_revision, "compile_key", None),
        str(page.selected_cue_id),
        int(page.timeline.playhead_ms),
        int(page.undo_stack.index()),
        int(getattr(page, "_ass_generation", 0)),
        str(getattr(page, "_preview_path", "")),
        int(getattr(advanced, "generation", 0)),
    )


def _critical_work_pending(page: SubtitleStudioPage) -> bool:
    timers = (
        "_preview_timer",
        "_edit_preview_timer",
        "_transform_preview_timer",
        "_visual_update_timer",
        "_advanced_preview_timer",
    )
    if any(bool(getattr(page, name, None) and getattr(page, name).isActive()) for name in timers):
        return True
    return bool(
        getattr(page, "_ass_worker_running", False)
        or _thread_alive(page, "_ass_thread")
    )


def _background_pending(page: SubtitleStudioPage) -> bool:
    return bool(
        _critical_work_pending(page)
        or getattr(page, "_autosave_worker_running", False)
        or _thread_alive(page, "_autosave_thread")
        or getattr(page, "_advanced_preview_worker_running", False)
        or getattr(page, "_advanced_preview_pending_job", None) is not None
    )


def _child_records() -> list[dict[str, Any]]:
    target = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    rows: list[dict[str, Any]] = []
    if target.is_file():
        for line in target.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _screenshot(widget, name: str) -> str:
    target = OUTPUT / name
    screen = QGuiApplication.primaryScreen()
    pixmap = screen.grabWindow(int(widget.window().winId())) if screen else widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"screenshot failed: {target}")
    return str(target)


def main() -> int:
    global CURRENT_ACTION
    child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    child_log.unlink(missing_ok=True)
    _install_probes(detailed_calls=not ARGS.low_perturbation)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(f"2ByteASR P7.1C {ARGS.label}")
    monitor = EventMonitor()
    app.installEventFilter(monitor)
    heartbeat = EventLoopLag(app)
    window = None
    rows: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "schema": "2byteasr.p71c-interaction-latency.v1",
        "label": ARGS.label,
        "viewport": ARGS.viewport,
        "probe_mode": "low_perturbation" if ARGS.low_perturbation else "detailed_trace",
        "evidence_class": "PROFILED / FORMAL HEADED VERIFIED",
        "real_user_click": False,
        "source_project": str(SOURCE_PROJECT),
        "project_copy": str(PROJECT_COPY),
        "cue_count": ARGS.dense_cues or len(
            json.loads(PROJECT_COPY.read_text(encoding="utf-8"))["cues"]
        ),
        "media": {
            "path": str(MEDIA),
            "exists": MEDIA.is_file(),
            "bytes": MEDIA.stat().st_size if MEDIA.is_file() else 0,
        },
        "waveform_cache_seed": str(WAVEFORM_CACHE_SEED),
        "waveform_cache_seed_exists": WAVEFORM_CACHE_SEED.is_dir(),
        "encoder_cache_seed": str(ENCODER_CACHE_SEED),
        "encoder_cache_seed_exists": ENCODER_CACHE_SEED.is_file(),
        "actions": rows,
    }

    def measure(
        group: str,
        name: str,
        callback: Callable[[], Any],
        visual_correct: Callable[[], bool],
        *,
        require_paint: bool = True,
    ) -> dict[str, Any]:
        global CURRENT_ACTION
        action = f"{group}:{name}"
        CURRENT_ACTION = "pre_settle"
        pump(app, 40)
        if ARGS.low_perturbation or ARGS.collect_before_action:
            gc.collect()
            pump(app, 20)
        CURRENT_ACTION = action
        COMMAND_START_NS.pop(action, None)
        event_before = monitor.snapshot()
        heartbeat_before = heartbeat.reset()
        ipc_before = len(IPC_RECORDS)
        calls_before = len(CALL_RECORDS)
        threads_before = len(THREAD_RECORDS)
        child_before = child_process_start_count()
        gc_before = gc.get_count()
        t0 = time.perf_counter_ns()
        error = ""
        callback_result = None
        try:
            callback_result = callback()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        t2 = time.perf_counter_ns()
        t1 = COMMAND_START_NS.get(action, t0)
        first_paint_ns: int | None = None
        visual_ns: int | None = None
        settled_ns: int | None = None
        background_ns: int | None = None
        stable_frames = 0
        previous = None
        deadline = time.perf_counter() + ARGS.settle_timeout
        while time.perf_counter() < deadline:
            app.processEvents()
            now = time.perf_counter_ns()
            paints = monitor.timeline_paints[event_before[1]:]
            if first_paint_ns is None:
                match = next((item for item in paints if item["time_ns"] >= t0), None)
                if match is not None:
                    first_paint_ns = int(match["time_ns"])
            correct = False
            try:
                correct = bool(visual_correct())
            except Exception as exc:
                error = error or f"visual predicate: {type(exc).__name__}: {exc}"
            if correct and (first_paint_ns is not None or not require_paint) and visual_ns is None:
                visual_ns = now
            fingerprint = _settlement_fingerprint(page)
            if correct and not _critical_work_pending(page) and fingerprint == previous:
                stable_frames += 1
            else:
                stable_frames = 0
            previous = fingerprint
            if stable_frames >= 3 and settled_ns is None:
                settled_ns = now
            if settled_ns is not None and not _background_pending(page):
                background_ns = now
                break
            QTest.qWait(16)
        end_ns = time.perf_counter_ns()
        if visual_ns is None:
            error = error or "visual state did not become correct"
        if settled_ns is None:
            error = error or "event loop did not settle"
        if background_ns is None:
            error = error or "background work did not complete"
        events = monitor.delta(event_before)
        ipc = copy.deepcopy(IPC_RECORDS[ipc_before:])
        calls = copy.deepcopy(CALL_RECORDS[calls_before:])
        lag = heartbeat.report_since(heartbeat_before)
        row = {
            "group": group,
            "name": name,
            "t0_input_ns": t0,
            "t1_command_start_ns": t1,
            "t2_command_return_ns": t2,
            "t3_first_timeline_paint_ns": first_paint_ns,
            "t4_visual_correct_ns": visual_ns,
            "t5_event_loop_settled_ns": settled_ns,
            "t6_background_complete_ns": background_ns,
            "command_ms": round((t2 - t1) / 1_000_000, 3),
            "first_feedback_ms": round((first_paint_ns - t0) / 1_000_000, 3) if first_paint_ns else None,
            "visual_settled_ms": round((visual_ns - t0) / 1_000_000, 3) if visual_ns else None,
            "event_loop_settled_ms": round((settled_ns - t0) / 1_000_000, 3) if settled_ns else None,
            "background_ms": round((background_ns - t0) / 1_000_000, 3) if background_ns else None,
            "observation_ms": round((end_ns - t0) / 1_000_000, 3),
            "callback_result": callback_result,
            "error": error,
            "qt": events,
            "event_loop_lag": lag,
            "mpv_ipc": {
                "count": len(ipc),
                "total_ms": round(sum(float(item["elapsed_ms"]) for item in ipc), 3),
                "synchronous_over_10ms": [item for item in ipc if item["ui_blocking"] and item["elapsed_ms"] > 10],
                "records": ipc,
            },
            "calls": calls,
            "threads_started": copy.deepcopy(THREAD_RECORDS[threads_before:]),
            "child_process_starts": child_process_start_count() - child_before,
            "gc_count_before": list(gc_before),
            "gc_count_after": list(gc.get_count()),
        }
        rows.append(row)
        progress(
            f"{action} command={row['command_ms']} first={row['first_feedback_ms']} "
            f"settled={row['event_loop_settled_ms']} background={row['background_ms']} "
            f"lag_max={lag['max_ms']} error={error or '-'}"
        )
        return row

    try:
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        window.setWindowTitle(f"2ByteASR P7.1B {ARGS.label}")
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 500)
        page = window.studio_page
        monitor.timeline = page.timeline
        window.open_studio_project(PROJECT_COPY, source=f"p71b-{ARGS.label}")
        wait_until(
            app,
            lambda: page.video.controller is not None and page.video.controller.running,
            25.0,
            "mpv process",
        )
        wait_until(
            app,
            lambda: page.timeline.waveform_state in {"READY", "ERROR"},
            20.0,
            "waveform",
        )
        page.video.set_paused(True)
        pump(app, 900)
        result["startup_screenshot"] = _screenshot(window, "00-startup.png")
        baseline_win32 = win32_top_level_windows(pids=descendants())
        baseline_qt = qt_top_level_widgets(app)
        result["window_baseline"] = {
            "win32": baseline_win32,
            "qt": baseline_qt,
        }
        sequence_of(page.project).video_track_locked = False

        # Razor x20: every sample follows toolbar button -> V1 timeline click.
        duration = max(1, sequence_of(page.project).timeline_duration_ms)
        viewport_duration = duration if ARGS.viewport == "overview" else min(duration, 30_000)
        page.timeline.set_visible_window(0, viewport_duration)
        pump(app, 80)
        for index in range(20):
            before_segments = len(sequence_of(page.project).segments)
            fraction = (index + 1) / 21.0
            point = QPoint(
                round(page.timeline.TRACK_HEADER_WIDTH + fraction * (page.timeline._content_right() - page.timeline.TRACK_HEADER_WIDTH)),
                round(page.timeline._video_track_rect().center().y()),
            )

            def razor_click(target=point):
                started_ns = time.perf_counter_ns()
                QTest.mouseClick(page.razor_tool_button, Qt.MouseButton.LeftButton)
                tool_ready_ns = time.perf_counter_ns()
                QTest.mouseClick(page.timeline, Qt.MouseButton.LeftButton, pos=target)
                command_ready_ns = time.perf_counter_ns()
                return {
                    "point": [target.x(), target.y()],
                    "tool_click_ms": round((tool_ready_ns - started_ns) / 1_000_000, 3),
                    "timeline_click_ms": round((command_ready_ns - tool_ready_ns) / 1_000_000, 3),
                }

            measure(
                "razor_x20",
                f"{index + 1:02d}",
                razor_click,
                lambda wanted=before_segments + 1: len(sequence_of(page.project).segments) == wanted,
            )

        # Undo/Redo the exact 20 Razor commands.
        for index in range(20):
            before_index = page.undo_stack.index()
            measure(
                "undo_x20",
                f"{index + 1:02d}",
                lambda: QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier),
                lambda wanted=before_index - 1: page.undo_stack.index() == wanted,
            )
        for index in range(20):
            before_index = page.undo_stack.index()
            measure(
                "redo_x20",
                f"{index + 1:02d}",
                lambda: QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier),
                lambda wanted=before_index + 1: page.undo_stack.index() == wanted,
            )

        # Mixed sequence exercises backpressure while retaining human input paths.
        mixed = ("razor", "razor", "razor", "undo", "undo", "redo", "razor")
        for index, kind in enumerate(mixed):
            before_index = page.undo_stack.index()
            if kind == "razor":
                before_segments = len(sequence_of(page.project).segments)
                visible_start = int(page.timeline.visible_start_ms)
                visible_end = visible_start + int(page.timeline.visible_duration_ms)
                spans = [
                    (
                        max(visible_start, int(segment.timeline_in_ms)),
                        min(visible_end, int(segment.timeline_out_ms)),
                    )
                    for segment in sequence_of(page.project).segments
                    if int(segment.timeline_out_ms) > visible_start
                    and int(segment.timeline_in_ms) < visible_end
                ]
                left, right = max(spans, key=lambda span: span[1] - span[0])
                cut_ms = left + max(1, (right - left) // 2)
                x = round(page.timeline._time_to_x(cut_ms))
                target = QPoint(x, round(page.timeline._video_track_rect().center().y()))
                callback = lambda target=target: (
                    QTest.mouseClick(page.razor_tool_button, Qt.MouseButton.LeftButton),
                    QTest.mouseClick(page.timeline, Qt.MouseButton.LeftButton, pos=target),
                )
                predicate = lambda wanted=before_segments + 1: len(sequence_of(page.project).segments) == wanted
            elif kind == "undo":
                callback = lambda: QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                predicate = lambda wanted=before_index - 1: page.undo_stack.index() == wanted
            else:
                callback = lambda: QTest.keyClick(page.timeline, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                predicate = lambda wanted=before_index + 1: page.undo_stack.index() == wanted
            measure("mixed", f"{index + 1:02d}_{kind}", callback, predicate)

        # Cue drag x20.
        QTest.mouseClick(page.selection_tool_button, Qt.MouseButton.LeftButton)
        drag_speaker = page.project.cues[0].speaker_id
        drag_cues = [cue for cue in page.project.cues if cue.speaker_id == drag_speaker]
        for index in range(20):
            cue = drag_cues[index % len(drag_cues)]
            page.timeline.set_visible_window(max(0, cue.start_ms - 3_000), 10_000)
            page.select_cue(cue.id)
            pump(app, 32)
            speaker_rect = page.timeline._track_layout()[0][cue.speaker_id]
            left = round(page.timeline._time_to_x(cue.start_ms))
            right = round(page.timeline._time_to_x(cue.end_ms))
            y = round(speaker_rect.center().y())
            start = None
            for x in range(left + 14, right - 13):
                hit, mode = page.timeline._cue_at(QPoint(x, y))
                if hit is not None and hit.id == cue.id and mode == "move":
                    start = QPoint(x, y)
                    break
            if start is None:
                raise RuntimeError(f"no move hit target for {cue.id}: {left}..{right}")
            delta = 32 if index % 2 == 0 else -32
            end = start + QPoint(delta, 0)
            before_start = cue.start_ms

            def drag(source=start, target=end):
                QTest.mousePress(page.timeline, Qt.MouseButton.LeftButton, pos=source)
                QTest.mouseMove(page.timeline, target, 30)
                QTest.mouseRelease(page.timeline, Qt.MouseButton.LeftButton, pos=target, delay=30)

            measure(
                "drag_x20",
                f"{index + 1:02d}",
                drag,
                lambda cue_id=cue.id, old=before_start: page._cue_lookup[cue_id].start_ms != old,
            )

        # Visible V1 click seek x30.
        seek_duration = max(1, sequence_of(page.project).timeline_duration_ms)
        seek_viewport = seek_duration if ARGS.viewport == "overview" else min(seek_duration, 30_000)
        page.timeline.set_visible_window(0, seek_viewport)
        for index in range(30):
            fraction = ((index * 7) % 29 + 1) / 30.0
            target_ms = round(page.timeline.visible_start_ms + page.timeline.visible_duration_ms * fraction)
            point = QPoint(
                round(page.timeline.TRACK_HEADER_WIDTH + fraction * (page.timeline._content_right() - page.timeline.TRACK_HEADER_WIDTH)),
                round(page.timeline._video_track_rect().center().y()),
            )
            measure(
                "seek_x30",
                f"{index + 1:02d}",
                lambda target=point: QTest.mouseClick(page.timeline, Qt.MouseButton.LeftButton, pos=target),
                lambda wanted=target_ms: abs(page.timeline.playhead_ms - wanted) < 20_000,
            )

        # Preset/fill edits use their production handlers; they still traverse the
        # same transaction, preview, ASS, mpv, paint and autosave consumers.
        style_cue = page.project.cues[0]
        if ARGS.viewport == "zoom30":
            page.timeline.set_visible_window(max(0, style_cue.start_ms - 3_000), 30_000)
        page.select_cue(style_cue.id)
        pump(app, 40)
        for index in range(10):
            preset_index = page.style_preset.findData("game" if index % 2 == 0 else "clean-white")

            def preset(value=preset_index):
                page.style_preset.setCurrentIndex(value)
                page._preset_activated(value)

            before_revision = state_for(page.project).revision
            measure(
                "preset_x10",
                f"{index + 1:02d}",
                preset,
                lambda wanted=before_revision + 1: state_for(page.project).revision >= wanted,
            )
        fills = (FillSpec.solid("#FFFFE45E"), FillSpec.solid("#FF20D9FF"))
        for index in range(10):
            before_revision = state_for(page.project).revision
            measure(
                "fill_x10",
                f"{index + 1:02d}",
                lambda value=fills[index % 2]: page._apply_fill_spec(value),
                lambda wanted=before_revision + 1: state_for(page.project).revision >= wanted,
            )

        def apply_numeric_style(control, value: float) -> None:
            blocked = control.blockSignals(True)
            try:
                control.setValue(value)
            finally:
                control.blockSignals(blocked)
            page._apply_style()

        for index in range(10):
            before_revision = state_for(page.project).revision
            width = 2.0 if index % 2 == 0 else 6.0
            measure(
                "stroke_x10",
                f"{index + 1:02d}",
                lambda value=width: apply_numeric_style(page.style_outline_width, value),
                lambda wanted=before_revision + 1: state_for(page.project).revision >= wanted,
            )

        gradients = (
            FillSpec.linear([
                {"color": "#FFFFE45E", "position": 0.0},
                {"color": "#FF20D9FF", "position": 1.0},
            ], angle=18.0),
            FillSpec.linear([
                {"color": "#FFFF6B8A", "position": 0.0},
                {"color": "#FFFFFFFF", "position": 1.0},
            ], angle=92.0),
        )
        for index in range(10):
            before_revision = state_for(page.project).revision
            measure(
                "gradient_x10",
                f"{index + 1:02d}",
                lambda value=gradients[index % 2]: page._apply_fill_spec(value),
                lambda wanted=before_revision + 1: state_for(page.project).revision >= wanted,
            )

        shadow_values = (0.1, 0.5, 1.0, 0.5)
        for index in range(10):
            before_revision = state_for(page.project).revision
            strength = shadow_values[index % len(shadow_values)]
            measure(
                "shadow_x10",
                f"{index + 1:02d}",
                lambda value=strength: apply_numeric_style(page.style_shadow, value),
                lambda wanted=before_revision + 1: state_for(page.project).revision >= wanted,
            )

        # Cue selection x30 through the visible cue table rows. This avoids a
        # moved/overlapped timeline block changing the hit target under test.
        for index in range(30):
            cue = page.project.cues[(index + 1) % len(page.project.cues)]
            row_index = page.cue_model.row_for_cue_id(cue.id)
            model_index = page.cue_model.index(row_index, 3)

            def click_table_row(target=model_index, target_row=row_index):
                # Follow-playhead may scroll the table during measure()'s
                # pre-settle window, so resolve the click point at dispatch.
                page.cue_table.scrollTo(
                    target,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                target_rect = page.cue_table.visualRect(target)
                if not page.cue_table.viewport().rect().intersects(target_rect):
                    raise RuntimeError(f"cue table row is not visible: {target_row}")
                QTest.mouseClick(
                    page.cue_table.viewport(),
                    Qt.MouseButton.LeftButton,
                    pos=target_rect.center(),
                )

            measure(
                "select_x30",
                f"{index + 1:02d}",
                click_table_row,
                lambda wanted=cue.id: page.selected_cue_id == wanted,
            )

        # Force one dirty autosave so snapshot time and background persistence are
        # measured independently of the ordinary 5-60 second debounce interval.
        before_profile_count = len(page._autosave_profile)

        def force_dirty_autosave():
            page._schedule_autosave()
            deadline = page._autosave_deadline
            now = time.monotonic()
            deadline.dirty_since = now - deadline.interval_seconds
            deadline.last_edit_at = now - deadline.idle_seconds
            page._autosave()

        measure(
            "autosave",
            "forced_dirty_snapshot_and_persist",
            force_dirty_autosave,
            lambda wanted=before_profile_count + 1: len(page._autosave_profile) >= wanted,
            require_paint=False,
        )
        result["ass_phase_profile"] = list(page._ass_profile)
        result["autosave_phase_profile"] = list(page._autosave_profile)
        observed = getattr(page.video.controller, "observed_properties", None)
        result["mpv_observed_properties"] = observed() if callable(observed) else {}
        command_payloads = []
        for index in range(page.undo_stack.count()):
            command = page.undo_stack.command(index)
            if not isinstance(command, EditSequenceCommand):
                continue
            payload = (
                command.before_sequence,
                command.after_sequence,
                command.before_cues,
                command.after_cues,
            )
            command_payloads.append({
                "index": index,
                "text": command.text(),
                "pickle_payload_bytes": len(pickle.dumps(payload, protocol=5)),
                "before_segments": len(command.before_sequence.segments),
                "after_segments": len(command.after_sequence.segments),
                "before_cues": len(command.before_cues or ()),
                "after_cues": len(command.after_cues or ()),
                "shares_project_cues": command.before_cues is None,
            })
        result["undo_command_payloads"] = command_payloads
        final_win32 = win32_top_level_windows(pids=descendants())
        final_qt = qt_top_level_widgets(app)
        baseline_hwnds = {int(item["hwnd"]) for item in baseline_win32}
        baseline_qt_ids = {int(item["winId"]) for item in baseline_qt if item["winId"]}
        result["window_final"] = {"win32": final_win32, "qt": final_qt}
        result["new_visible_windows"] = {
            "win32": [
                item for item in final_win32
                if item["visible"] and int(item["hwnd"]) not in baseline_hwnds
            ],
            "qt": [
                item for item in final_qt
                if item["visible"] and int(item["winId"] or 0) not in baseline_qt_ids
            ],
        }
        result["final_screenshot"] = _screenshot(window, "01-final.png")

        metric_fields = (
            "command_ms",
            "first_feedback_ms",
            "visual_settled_ms",
            "event_loop_settled_ms",
            "background_ms",
        )
        result["summaries"] = {
            group: {
                field: summary([row for row in rows if row["group"] == group], field)
                for field in metric_fields
            }
            for group in sorted({row["group"] for row in rows})
        }
        result["worst_traces"] = {
            group: max(
                (row for row in rows if row["group"] == group),
                key=lambda row: float(row.get("event_loop_settled_ms") or row["observation_ms"]),
            )
            for group in sorted({row["group"] for row in rows})
        }
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
    finally:
        CURRENT_ACTION = "shutdown"
        try:
            if window is not None:
                original_dirty_prompt = ProjectDirtyGuard._prompt
                ProjectDirtyGuard._prompt = (
                    lambda _guard, _action: DirtyGuardChoice.DISCARD
                )
                try:
                    window.close()
                finally:
                    ProjectDirtyGuard._prompt = original_dirty_prompt
                window.deleteLater()
                pump(app, 200)
        except Exception:
            pass
        app.removeEventFilter(monitor)
        heartbeat.timer.stop()
        _restore_probes()

    result["all_event_loop_samples"] = heartbeat.samples
    result["all_mpv_ipc_records"] = IPC_RECORDS
    result["all_call_records"] = CALL_RECORDS
    result["all_thread_records"] = THREAD_RECORDS
    result["child_process_records"] = _child_records()
    target = OUTPUT / "profile-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 1 if result.get("fatal_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
