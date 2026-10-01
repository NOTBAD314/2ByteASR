"""Formal headed P7.3C seek-to-playable and continuous-playback evidence."""

from __future__ import annotations

import collections
import copy
import ctypes
import json
import math
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "TWOBYTEASR_P73C_SEEK_OUTPUT",
    str(ROOT / "tmp" / "p73c" / "seek-to-playable"),
)).resolve()
SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"
PROJECT = OUTPUT / "p73c-seek-real-hour.2byteproj"
CONTINUOUS_SECONDS = max(1, int(os.environ.get("TWOBYTEASR_P73C_CONTINUOUS_SECONDS", "120")))
SEEK_COUNT = max(1, int(os.environ.get("TWOBYTEASR_P73C_SEEK_COUNT", "30")))
RAPID_COUNT = max(1, int(os.environ.get("TWOBYTEASR_P73C_RAPID_COUNT", "30")))
OUTPUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SOURCE_PROJECT, PROJECT)
os.environ["QT_QPA_PLATFORM"] = "windows"
if os.environ.get("TWOBYTEASR_P73C_ISOLATED_LOCALAPPDATA") == "1":
    os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "children.jsonl")
os.environ["TWOBYTEASR_NO_OPEN"] = "1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

import psutil
from PIL import Image, ImageStat
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QObject,
    QPoint,
    QTimer,
    Qt,
)
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.p64_runtime_audit import _print_window, _window_bounds
from twobyteasr.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
from twobyteasr.runtime_trace import GLOBAL_STUDIO_TRACE
from twobyteasr.studio_ai import style_recipe_for_prompt
from twobyteasr.visual_runtime import VisualOwner


CURRENT_ACTION = "startup"


class RuntimeEvidenceError(RuntimeError):
    def __init__(self, message: str, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.evidence = evidence


def progress(message: str) -> None:
    print(f"[p73c-seek] {message}", flush=True)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else None,
    }


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        # A busy headed Studio can continuously enqueue timer, mpv, and paint
        # events. Bound each drain so an acceptance timeout remains meaningful.
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 4)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if time.perf_counter() >= deadline:
            return
        time.sleep(0.004)


def wait_until(app: QApplication, predicate, timeout: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        pump(app, 5)
        if predicate():
            return round((time.perf_counter() - started) * 1000.0, 3)
    if not predicate():
        raise TimeoutError(f"{label} was not ready within {timeout:.1f}s")
    return round((time.perf_counter() - started) * 1000.0, 3)


def frame_summary(frame) -> list[str]:
    if frame is None:
        return []
    return [
        f"{Path(item.filename).name}:{item.lineno}:{item.name}"
        for item in traceback.extract_stack(frame, limit=12)
    ]


class PythonSampler:
    """Sampling evidence; a sampling gap is recorded, never assigned to a caller."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.main_ident = threading.main_thread().ident
        self.lock = threading.Lock()
        self.latest: dict[str, object] = {}
        self.gaps: list[dict[str, object]] = []
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="p73c-python-sampler",
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return copy.deepcopy(self.latest)

    def _run(self) -> None:
        previous = time.perf_counter()
        while not self.stop_event.wait(0.008):
            now = time.perf_counter()
            gap_ms = max(0.0, (now - previous) * 1000.0 - 8.0)
            previous = now
            frames = sys._current_frames()
            rows = {
                thread.name: frame_summary(frames.get(thread.ident))
                for thread in threading.enumerate()
                if thread.ident is not None
            }
            sample = {
                "perf_counter": now,
                "action": CURRENT_ACTION,
                "main_stack": rows.get(threading.main_thread().name, []),
                "thread_stacks": rows,
                "sampler_gap_ms": round(gap_ms, 3),
            }
            with self.lock:
                self.latest = sample
                if gap_ms > 50.0:
                    self.gaps.append({
                        "action": CURRENT_ACTION,
                        "sampler_gap_ms": round(gap_ms, 3),
                        "at_perf_counter": now,
                        "attribution": "unknown; sampler could not run during this interval",
                    })


class QtEventProbe(QObject):
    """Retain the most recently dispatched Qt receiver/event without timing it."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.last_event: dict[str, object] = {}
        self.counts: collections.Counter[str] = collections.Counter()
        app.installEventFilter(self)

    def eventFilter(self, receiver, event) -> bool:
        name = event.type().name
        self.counts[name] += 1
        self.last_event = {
            "action": CURRENT_ACTION,
            "receiver": type(receiver).__name__,
            "event_type": int(event.type()),
            "event_name": name,
            "observed_at": time.perf_counter(),
        }
        return False


class EventLoopProbe:
    THRESHOLDS = (50, 100, 250, 500, 1000)

    def __init__(
        self,
        app: QApplication,
        qt_events: QtEventProbe,
    ) -> None:
        self.app = app
        self.qt_events = qt_events
        self.page = None
        self.samples: list[dict[str, object]] = []
        self.stalls: list[dict[str, object]] = []
        self.last = time.perf_counter()
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def reset(self) -> int:
        self.last = time.perf_counter()
        return len(self.samples)

    def _runtime_state(self) -> dict[str, object]:
        page = self.page
        if page is None:
            return {}
        governor = page._resource_governor.snapshot()
        controller = page.video.controller
        renderer = page._advanced_preview_cache.renderer_service
        return {
            "mpv": {
                "running": bool(controller and controller.running),
                "pid": getattr(getattr(controller, "_process", None), "pid", None),
                "observed": controller.observed_properties() if controller else {},
            },
            "renderer": {
                "pid": renderer.process_id,
                "worker_running": bool(page._advanced_preview_worker_running),
                "pending": bool(page._advanced_preview_pending_job),
            },
            "provider": {
                "threads": sum(
                    thread.name.startswith("provider-service-")
                    for thread in threading.enumerate()
                ),
            },
            "autosave": {
                "worker_running": bool(page._autosave_worker_running),
                "thread_alive": bool(
                    page._autosave_thread and page._autosave_thread.is_alive()
                ),
            },
            "resource_governor": {
                "playback": governor.playback,
                "dragging": governor.dragging,
                "active": dict(governor.active),
                "foreground_active": dict(governor.foreground_active),
                "yield_counts": dict(governor.yield_counts),
            },
        }

    def _tick(self) -> None:
        now = time.perf_counter()
        lateness_ms = max(0.0, (now - self.last) * 1000.0 - 8.0)
        self.last = now
        row = {
            "action": CURRENT_ACTION,
            "lateness_ms": round(lateness_ms, 3),
            "perf_counter": now,
        }
        self.samples.append(row)
        if lateness_ms > 50.0:
            self.stalls.append({
                **row,
                "last_qt_event_after_gap": copy.deepcopy(self.qt_events.last_event),
                "post_gap_python_sample": {
                    "action": CURRENT_ACTION,
                    "main_stack": frame_summary(sys._getframe()),
                    "thread_names": [
                        thread.name for thread in threading.enumerate()
                    ],
                    "sampling_gap_attribution": "unknown",
                },
                "runtime_state_after_gap": self._runtime_state(),
                "attribution_note": (
                    "The Python sample and service state are post-gap evidence; "
                    "they are not attributed as the cause without a matching timed call."
                ),
            })

    def report_since(self, index: int) -> dict[str, object]:
        rows = self.samples[index:]
        values = [float(row["lateness_ms"]) for row in rows]
        return {
            "sample_count": len(rows),
            "p95_ms": percentile(values, 0.95),
            "max_ms": round(max(values), 3) if values else 0.0,
            "threshold_counts": {
                str(limit): sum(value > limit for value in values)
                for limit in self.THRESHOLDS
            },
            "stalls": [row for row in self.stalls if row in rows or (
                rows and float(row["perf_counter"]) >= float(rows[0]["perf_counter"])
            )],
        }


def wait_pause(app: QApplication, page, paused: bool) -> None:
    page.video.set_paused(paused)
    wait_until(
        app,
        lambda: bool(page.video.controller.observed_property("pause", not paused)) == paused,
        3.0,
        f"mpv pause={paused}",
    )
    pump(app, 30)


def perform_seek(
    app: QApplication,
    page,
    probe: EventLoopProbe,
    *,
    label: str,
    index: int,
    target: float,
    paused: bool,
) -> dict[str, object]:
    global CURRENT_ACTION
    CURRENT_ACTION = f"{label}:{index:02d}"
    wait_pause(app, page, paused)
    before_history = len(page.video.seek_latency_traces())
    lag_index = probe.reset()
    started = time.perf_counter()
    page._seek(target)
    callback_ms = (time.perf_counter() - started) * 1000.0
    wait_until(
        app,
        lambda: getattr(page.video, "_active_seek_trace", None) is None,
        3.0,
        f"{label} seek {index}",
    )
    traces = page.video.seek_latency_traces()
    trace = copy.deepcopy(traces[-1]) if len(traces) > before_history else {}
    return {
        "index": index,
        "target_seconds": target,
        "paused": paused,
        "callback_ms": round(callback_ms, 3),
        "trace": trace,
        "event_loop": probe.report_since(lag_index),
    }


def continuous_playback(
    app: QApplication,
    page,
    probe: EventLoopProbe,
    *,
    seconds: int = CONTINUOUS_SECONDS,
) -> dict[str, object]:
    global CURRENT_ACTION
    CURRENT_ACTION = "continuous_playback_120s"
    page._seek(3600.0)
    wait_until(app, lambda: page.video._active_seek_trace is None, 3.0, "continuous pre-seek")
    wait_pause(app, page, False)
    lag_index = probe.reset()
    started = time.monotonic()
    samples: list[dict[str, object]] = []
    next_sample = 0
    while time.monotonic() - started < seconds:
        pump(app, 20)
        elapsed = time.monotonic() - started
        if elapsed >= next_sample:
            samples.append({
                "elapsed_seconds": round(elapsed, 3),
                "visual_position": round(page.video.visual_position(), 3),
                "observed_position": page.video.controller.observed_property("time-pos", None),
                "paused": bool(page.video.controller.observed_property("pause", True)),
            })
            next_sample += 1
        if int(elapsed) > 0 and int(elapsed) % 10 == 0:
            marker = int(elapsed)
            if not samples or samples[-1].get("progress_marker") != marker:
                samples.append({"progress_marker": marker})
                progress(f"continuous playback {marker}/{seconds}s")
    wait_pause(app, page, True)
    positions = [
        float(row["visual_position"])
        for row in samples
        if "visual_position" in row
    ]
    backsteps = [
        round(previous - current, 3)
        for previous, current in zip(positions, positions[1:])
        if current + 0.05 < previous
    ]
    checkpoints = {}
    timed = [row for row in samples if "elapsed_seconds" in row]
    for checkpoint in (30, 120):
        nearest = min(
            timed,
            key=lambda row: abs(float(row["elapsed_seconds"]) - checkpoint),
        )
        checkpoints[str(checkpoint)] = nearest
    return {
        "duration_seconds": seconds,
        "sample_count": len(timed),
        "checkpoints": checkpoints,
        "backsteps_over_50ms": backsteps,
        "position_delta_seconds": round(positions[-1] - positions[0], 3),
        "event_loop": probe.report_since(lag_index),
    }


def qimage_to_pil(image: QImage) -> Image.Image:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(converted.bits()[: converted.sizeInBytes()])
    return Image.frombuffer(
        "RGBA", (converted.width(), converted.height()), raw, "raw", "RGBA",
        converted.bytesPerLine(), 1,
    ).copy()


def capture_formal_visual(app: QApplication, window, page) -> dict[str, object]:
    global CURRENT_ACTION
    CURRENT_ACTION = "formal_visual_capture"
    cue = page.project.cues[0]
    recipe = style_recipe_for_prompt("赛博游戏冲击，黄蓝渐变，多层描边")
    recipe.name = f"P73C Seek Visual {time.time_ns()}"
    if not page._apply_style_recipe(cue.id, recipe):
        raise RuntimeError("advanced recipe did not apply")
    page.select_cue(cue.id)
    wait_until(
        app,
        lambda: not str(getattr(page, "_pending_motion_replay_cue_id", "") or ""),
        3.0,
        "automatic motion replay dispatch",
    )
    wait_until(
        app,
        lambda: (
            page._visual_ownership.current.owner in {
                VisualOwner.ADVANCED_LIVE, VisualOwner.ADVANCED_FIDELITY,
            }
            and page._visual_ownership.current.cue_id == cue.id
            and page.advanced_cue_overlay.isVisible()
            and not page.advanced_cue_overlay._source.isNull()
        ),
        8.0,
        "advanced visual owner warmup",
    )
    wait_until(
        app,
        lambda: page.video._active_seek_trace is None,
        3.0,
        "automatic motion replay seek",
    )
    wait_pause(app, page, True)
    page._seek((cue.start_ms + 700) / 1000.0)
    try:
        wait_until(app, lambda: page.video._active_seek_trace is None, 4.0, "visual seek")
    except TimeoutError as exc:
        controller = page.video.controller
        observed = (
            controller.observed_properties()
            if controller is not None and hasattr(controller, "observed_properties")
            else {}
        )
        applied_seek = (
            controller.applied_seek_state()
            if controller is not None and hasattr(controller, "applied_seek_state")
            else {}
        )
        preview_state = getattr(page, "_advanced_preview_state", None)
        evidence = {
            "active_seek_trace": copy.deepcopy(page.video._active_seek_trace),
            "recent_seek_traces": page.video.seek_latency_traces()[-5:],
            "mpv_observed": observed,
            "mpv_applied_seek": applied_seek,
            "visibility": page.subtitle_visibility_trace(reason="visual_seek_timeout"),
            "selected_cue_id": str(page.selected_cue_id or ""),
            "advanced_expected_key": str(
                getattr(page, "_advanced_preview_expected_key", "") or ""
            ),
            "advanced_phase": str(getattr(preview_state, "phase", "")),
            "advanced_generation": int(
                getattr(preview_state, "generation", 0) or 0
            ),
            "advanced_worker_running": bool(
                getattr(page, "_advanced_preview_worker_running", False)
            ),
            "advanced_pending": bool(
                getattr(page, "_advanced_preview_pending_job", None) is not None
            ),
            "recent_runtime_events": list(GLOBAL_STUDIO_TRACE.recent())[-80:],
        }
        evidence = json.loads(json.dumps(evidence, ensure_ascii=False, default=str))
        diagnostic_path = OUTPUT / "visual-seek-timeout.json"
        diagnostic_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        evidence["path"] = str(diagnostic_path)
        raise RuntimeEvidenceError(str(exc), evidence) from exc
    wait_until(
        app,
        lambda: (
            page._visual_ownership.current.owner in {
                VisualOwner.ADVANCED_LIVE, VisualOwner.ADVANCED_FIDELITY,
            }
            and page._visual_ownership.current.cue_id == cue.id
            and page.advanced_cue_overlay.isVisible()
            and not page.advanced_cue_overlay._source.isNull()
        ),
        8.0,
        "advanced visual owner",
    )
    pump(app, 100)
    hwnd = int(window.winId())
    bounds = _window_bounds(hwnd)
    base = _print_window(hwnd).convert("RGBA")
    canvas = page.advanced_cue_overlay
    layer = qimage_to_pil(canvas.grab().toImage())
    origin = canvas.mapToGlobal(QPoint(0, 0))
    dpr = float(canvas.devicePixelRatioF() or 1.0)
    offset = (
        round(origin.x() * dpr - bounds[0]),
        round(origin.y() * dpr - bounds[1]),
    )
    base.alpha_composite(layer, dest=offset)
    target = OUTPUT / "formal-printwindow-qt-overlay.png"
    base.convert("RGB").save(target)
    video_origin = page.video.mapToGlobal(QPoint(0, 0))
    left = max(0, round(video_origin.x() * dpr - bounds[0]))
    top = max(0, round(video_origin.y() * dpr - bounds[1]))
    right = min(base.width, left + round(page.video.width() * dpr))
    bottom = min(base.height, top + round(page.video.height() * dpr))
    video_crop = base.crop((left, top, right, bottom)).convert("RGB")
    video_stat = ImageStat.Stat(video_crop)
    extrema = video_crop.getextrema()
    visibility = page.subtitle_visibility_trace(reason="p73c_formal_capture")
    controller = page.video.controller
    mpv_process = getattr(controller, "_process", None)
    return {
        "path": str(target),
        "method": "PrintWindow+Qt-overlay",
        "window_hwnd": hwnd,
        "window_bounds": list(bounds),
        "pixels": list(base.size),
        "overlay_offset": list(offset),
        "overlay_pixels": list(layer.size),
        "overlay_nonblank": bool(layer.getchannel("A").getbbox()),
        "video_crop": [left, top, right, bottom],
        "video_crop_mean_rgb": [round(value, 3) for value in video_stat.mean[:3]],
        "video_crop_extrema": [list(item) for item in extrema],
        "video_pixels_nonblank": any(high > low for low, high in extrema),
        "visibility": visibility,
        "process_identity": {
            "app_pid": os.getpid(),
            "mpv_pid": getattr(mpv_process, "pid", None),
            "mpv_running": bool(controller and controller.running),
            "renderer_pid": page._advanced_preview_cache.renderer_service.process_id,
        },
    }


def summarize_seek_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    traces = [row.get("trace", {}) for row in rows]
    settled = [trace for trace in traces if trace.get("settled") is True]
    def values(stage: str) -> list[float]:
        return [
            float(trace["elapsed_ms"][stage])
            for trace in settled
            if stage in trace.get("elapsed_ms", {})
        ]
    return {
        "count": len(rows),
        "settled_count": len(settled),
        "t8_pass_count": sum(trace.get("T8_passed") is True for trace in traces),
        "callback": stats([float(row["callback_ms"]) for row in rows]),
        "T0_T2": stats(values("T2_optimistic_playhead_visible")),
        "T0_T5": stats(values("T5_first_target_frame")),
        "T0_T7": stats(values("T7_sustained_progression")),
        "T0_T9": stats(values("T9_event_loop_settled")),
        "event_loop_max_ms": round(max(
            (float(row["event_loop"].get("max_ms") or 0.0) for row in rows),
            default=0.0,
        ), 3),
    }


def main() -> int:
    global CURRENT_ACTION
    child_log = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    child_log.unlink(missing_ok=True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    probe = None
    qt_events = None
    process = psutil.Process()
    result: dict[str, object] = {
        "schema": "2byteasr.p73c-seek-to-playable.v1",
        "evidence_class": "FORMAL HEADED PRODUCTION MAINWINDOW",
        "real_user_click": False,
        "source_project": str(SOURCE_PROJECT),
        "project": str(PROJECT),
        "media": json.loads(PROJECT.read_text(encoding="utf-8"))["media"],
        "pid": os.getpid(),
    }
    window = None
    try:
        progress("constructing production MainWindow")
        constructor_started = time.perf_counter()
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        result["constructor_ms"] = round(
            (time.perf_counter() - constructor_started) * 1000.0, 3,
        )
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 300)
        open_started = time.perf_counter()
        window.open_studio_project(PROJECT, source="p73c-seek-matrix")
        page = window.studio_page
        wait_until(
            app,
            lambda: page.video.controller is not None and page.video.controller.running,
            15.0,
            "real mpv",
        )
        qt_events = QtEventProbe(app)
        probe = EventLoopProbe(app, qt_events)
        probe.page = page
        result["first_project_usable_ms"] = round(
            (time.perf_counter() - open_started) * 1000.0, 3,
        )
        page.follow_playhead_toggle.setChecked(True)

        progress("starting 120-second continuous playback")
        result["continuous_playback"] = continuous_playback(
            app, page, probe, seconds=CONTINUOUS_SECONDS,
        )

        nearby = [414.1, 415.0, 416.0, 414.5, 421.2, 422.0, 423.0, 421.5]
        long_targets = [10.0, 600.0, 1800.0, 3600.0, 5400.0, 7200.0, 414.5]
        matrix_targets = [
            nearby[index % len(nearby)] if index % 2 == 0
            else long_targets[index % len(long_targets)]
            for index in range(SEEK_COUNT)
        ]
        paused_rows = []
        playing_rows = []
        progress(f"starting paused seek x{SEEK_COUNT}")
        for index, target in enumerate(matrix_targets, 1):
            paused_rows.append(perform_seek(
                app, page, probe, label="paused_seek", index=index,
                target=target, paused=True,
            ))
            if index % 10 == 0 or index == SEEK_COUNT:
                progress(f"paused seek {index}/{SEEK_COUNT}")
        progress(f"starting playing seek x{SEEK_COUNT}")
        for index, target in enumerate(matrix_targets, 1):
            playing_rows.append(perform_seek(
                app, page, probe, label="playing_seek", index=index,
                target=target, paused=False,
            ))
            if index % 10 == 0 or index == SEEK_COUNT:
                progress(f"playing seek {index}/{SEEK_COUNT}")

        progress(f"starting rapid A/B seek burst x{RAPID_COUNT}")
        CURRENT_ACTION = f"rapid_seek_burst_x{RAPID_COUNT}"
        wait_pause(app, page, False)
        lag_index = probe.reset()
        rapid_feedback = []
        history_before = len(page.video.seek_latency_traces())
        for index in range(RAPID_COUNT):
            started = time.perf_counter()
            page._seek(414.5 if index % 2 == 0 else 428.0)
            rapid_feedback.append(round((time.perf_counter() - started) * 1000.0, 3))
            pump(app, 20)
        wait_until(app, lambda: page.video._active_seek_trace is None, 4.0, "rapid final seek")
        rapid_traces = page.video.seek_latency_traces()[history_before:]
        rapid = {
            "command_count": RAPID_COUNT,
            "feedback": stats(rapid_feedback),
            "terminal_trace_count": len(rapid_traces),
            "terminal_trace": copy.deepcopy(rapid_traces[-1]) if rapid_traces else {},
            "event_loop": probe.report_since(lag_index),
        }
        result["seek_rows"] = {
            "paused": paused_rows,
            "playing": playing_rows,
            "rapid": rapid,
        }
        result["seek_summary"] = {
            "paused": summarize_seek_rows(paused_rows),
            "playing": summarize_seek_rows(playing_rows),
            "rapid": {
                "command_count": RAPID_COUNT,
                "feedback": rapid["feedback"],
                "settled": rapid["terminal_trace"].get("settled") is True,
                "t8_passed": rapid["terminal_trace"].get("T8_passed") is True,
            },
        }

        progress("capturing formal PrintWindow+Qt-overlay evidence")
        result["formal_visual"] = capture_formal_visual(app, window, page)
        result["resource_snapshot"] = {
            "rss_mb": round(process.memory_info().rss / 1024 / 1024, 3),
            "threads": process.num_threads(),
            "children": [
                {"pid": child.pid, "name": child.name()}
                for child in process.children(recursive=True)
                if child.is_running()
            ],
        }
        result["event_loop"] = {
            "sample_count": len(probe.samples),
            "max_ms": round(max(
                (float(row["lateness_ms"]) for row in probe.samples),
                default=0.0,
            ), 3),
            "threshold_counts": {
                str(limit): sum(
                    float(row["lateness_ms"]) > limit for row in probe.samples
                )
                for limit in probe.THRESHOLDS
            },
            "stalls": probe.stalls,
            "qt_event_counts": dict(qt_events.counts),
            "python_sampler_gaps": [],
            "gil_holder_sampling": "unavailable without perturbing the Windows headed runtime",
        }
        paused_summary = result["seek_summary"]["paused"]
        playing_summary = result["seek_summary"]["playing"]
        continuous = result["continuous_playback"]
        visual = result["formal_visual"]
        result["checks"] = {
            "continuous_120s_no_backstep": not continuous["backsteps_over_50ms"],
            "paused_30_settled": paused_summary["settled_count"] == SEEK_COUNT,
            "playing_30_settled": playing_summary["settled_count"] == SEEK_COUNT,
            "playing_30_have_t7": playing_summary["T0_T7"]["count"] == SEEK_COUNT,
            "all_t8_semantic_pass": (
                paused_summary["t8_pass_count"] == SEEK_COUNT
                and playing_summary["t8_pass_count"] == SEEK_COUNT
                and result["seek_summary"]["rapid"]["t8_passed"]
            ),
            "feedback_p95_lt_50": max(
                float(paused_summary["T0_T2"]["p95_ms"] or 9999),
                float(playing_summary["T0_T2"]["p95_ms"] or 9999),
                float(rapid["feedback"]["p95_ms"] or 9999),
            ) < 50.0,
            "typical_first_frame_p95_lt_200": max(
                float(paused_summary["T0_T5"]["p95_ms"] or 9999),
                float(playing_summary["T0_T5"]["p95_ms"] or 9999),
            ) < 200.0,
            "typical_playing_t7_p95_lt_300": float(
                playing_summary["T0_T7"]["p95_ms"] or 9999
            ) < 300.0,
            "no_event_loop_freeze_over_500": result["event_loop"]["threshold_counts"]["500"] == 0,
            "no_unexplained_freeze_over_1000": result["event_loop"]["threshold_counts"]["1000"] == 0,
            "formal_visual_nonblank": (
                visual["overlay_nonblank"] and visual["video_pixels_nonblank"]
            ),
            "formal_visual_single_owner": (
                visual["visibility"]["foreground_owner_count"] == 1
                and visual["visibility"]["foreground_owner"] in {
                    "advanced_live", "advanced_fidelity",
                }
            ),
        }
        result["pass"] = all(result["checks"].values())
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        evidence = getattr(exc, "evidence", None)
        if isinstance(evidence, dict):
            result["failure_evidence"] = evidence
        result["pass"] = False
    finally:
        CURRENT_ACTION = "close"
        if window is not None:
            try:
                page = window.studio_page
                if page.project_controller is not None:
                    active_guard = page.project_controller.dirty_guard
                    active_guard._prompt = (
                        lambda _action: DirtyGuardChoice.DISCARD
                    )
                    active_guard.confirm = lambda _action, **_kwargs: True
                original_guard_confirm = ProjectDirtyGuard.confirm
                ProjectDirtyGuard.confirm = (
                    lambda _self, _action, **_kwargs: True
                )
                try:
                    window.close()
                finally:
                    ProjectDirtyGuard.confirm = original_guard_confirm
                pump(app, 20)
                wait_until(app, lambda: bool(page._close_complete), 10.0, "close cleanup")
                result["close_profile"] = dict(page.last_close_profile)
            except Exception as exc:
                result["close_error"] = f"{type(exc).__name__}: {exc}"
    target = OUTPUT / "runtime-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target, flush=True)
    print(json.dumps({
        "pass": result.get("pass"),
        "constructor_ms": result.get("constructor_ms"),
        "first_project_usable_ms": result.get("first_project_usable_ms"),
        "seek_summary": result.get("seek_summary"),
        "checks": result.get("checks"),
        "fatal_error": result.get("fatal_error"),
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
