from __future__ import annotations

import argparse
import collections
import copy
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("TWOBYTEASR_NO_OPEN", "1")

import psutil
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.runtime_cache import GLOBAL_RUNTIME_CACHE


SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.monotonic() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if time.monotonic() >= deadline:
            return
        time.sleep(0.005)


def wait_until(app: QApplication, predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pump(app, 10)
        if predicate():
            return True
    return bool(predicate())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/p73c/lifecycle-loop")
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    project_copy = output / "p73c-real-hour.2byteproj"
    shutil.copy2(SOURCE_PROJECT, project_copy)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    process = psutil.Process()
    lag_samples: list[float] = []
    expected = time.perf_counter() + 0.016
    lag_timer = QTimer()
    lag_timer.setTimerType(Qt.TimerType.PreciseTimer)
    lag_timer.setInterval(16)

    def lag_tick() -> None:
        nonlocal expected
        now = time.perf_counter()
        lag_samples.append(max(0.0, (now - expected) * 1000.0))
        expected = now + 0.016

    lag_timer.timeout.connect(lag_tick)
    lag_timer.start()
    result: dict[str, object] = {
        "evidence": "lifecycle-loop+seek-to-playable+close-under-load",
        "project": str(project_copy),
        "source_project": str(SOURCE_PROJECT),
        "real_user_click": False,
        "iterations": [],
        "errors": [],
    }

    constructor_started = time.perf_counter()
    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
    result["constructor_ms"] = round((time.perf_counter() - constructor_started) * 1000.0, 3)
    window.resize(1600, 950)
    window.show()
    window.activateWindow()
    pump(app, 300)
    page = window.studio_page
    targets = (21.0, 22.0, 23.0, 21.5, 600.0, 1800.0, 3600.0, 45.0, 120.0, 2400.0)

    for index in range(max(1, args.iterations)):
        window._return_to_settings()
        pump(app, 50)
        started = time.perf_counter()
        window.open_studio_project(project_copy, source=f"p73c-lifecycle-{index + 1}")
        call_ms = (time.perf_counter() - started) * 1000.0
        usable = wait_until(
            app,
            lambda: page.project is not None
            and page.video.controller is not None
            and page.video.controller.running,
            5.0,
        )
        usable_ms = (time.perf_counter() - started) * 1000.0
        page.video.set_paused(index % 2 == 0)
        pump(app, 80)
        seek_started = time.perf_counter()
        page._seek(targets[index % len(targets)])
        feedback_ms = (time.perf_counter() - seek_started) * 1000.0
        wait_until(app, lambda: getattr(page.video, "_active_seek_trace", None) is None, 2.5)
        traces = page.video.seek_latency_traces()
        seek_trace = copy.deepcopy(traces[-1]) if traces else {}
        children = process.children(recursive=True)
        renderer_process = getattr(page._advanced_preview_cache.renderer_service, "_process", None)
        snapshot = page._resource_governor.snapshot()
        row = {
            "iteration": index + 1,
            "entry_call_ms": round(call_ms, 3),
            "usable_ms": round(usable_ms, 3),
            "usable": usable,
            "first_seek_callback_ms": round(feedback_ms, 3),
            "seek_trace": seek_trace,
            "open_profile_ms": {
                key: round(float(value) * 1000.0, 3)
                for key, value in page.last_open_profile.items()
                if isinstance(value, (int, float))
            },
            "rss_mb": round(process.memory_info().rss / 1024 / 1024, 3),
            "thread_count": process.num_threads(),
            "python_threads": len(threading.enumerate()),
            "child_count": len(children),
            "child_processes": [
                {"pid": child.pid, "name": child.name()} for child in children
                if child.is_running()
            ],
            "qt_widget_count": len(app.allWidgets()),
            "qt_widget_types": dict(collections.Counter(
                type(widget).__name__ for widget in app.allWidgets()
            )),
            "qt_timer_count": len(window.findChildren(QTimer)),
            "qt_active_timer_count": sum(
                timer.isActive() for timer in window.findChildren(QTimer)
            ),
            "studio_page_count": sum(1 for widget in app.allWidgets() if type(widget).__name__ == "SubtitleStudioPage"),
            "studio_session_count": 1 if getattr(page, "session", None) is not None else 0,
            "mpv_actor_threads": sum(
                thread.name == "studio-mpv-actor" for thread in threading.enumerate()
            ),
            "mpv_pid": getattr(getattr(page.video.controller, "_process", None), "pid", None),
            "renderer_pid": getattr(renderer_process, "pid", None),
            "provider_threads": sum(1 for thread in threading.enumerate() if thread.name.startswith("provider-service-")),
            "waveform_threads": sum(
                thread.name == "studio-waveform" for thread in threading.enumerate()
            ),
            "autosave_threads": sum(
                thread.name == "studio-autosave" for thread in threading.enumerate()
            ),
            "advanced_preview_worker_running": bool(
                getattr(page, "_advanced_preview_worker_running", False)
            ),
            "resource_governor": {
                "playback": snapshot.playback,
                "dragging": snapshot.dragging,
                "active": dict(snapshot.active),
                "foreground_active": dict(snapshot.foreground_active),
                "yield_counts": dict(snapshot.yield_counts),
                "background_limit": snapshot.background_limit,
            },
            "cache": GLOBAL_RUNTIME_CACHE.snapshot(),
        }
        result["iterations"].append(row)
        if index == 0:
            result["startup_event_loop_lag"] = {
                "max_ms": round(max(lag_samples, default=0.0), 3),
                "over_250": sum(value > 250 for value in lag_samples),
                "over_1000": sum(value > 1000 for value in lag_samples),
            }
            lag_samples.clear()

    page.video.set_paused(False)
    page._seek(900.0)
    pump(app, 10)
    close_started = time.perf_counter()
    window.close()
    pump(app, 1)
    visible_response_ms = (time.perf_counter() - close_started) * 1000.0
    cleanup_complete = wait_until(app, lambda: bool(getattr(page, "_close_complete", False)), 10.0)
    close_total_ms = (time.perf_counter() - close_started) * 1000.0
    pump(app, 100)
    remaining_children = [
        {"pid": child.pid, "name": child.name()}
        for child in process.children(recursive=True)
        if child.is_running()
    ]
    result["close_under_load"] = {
        "visible_response_ms": round(visible_response_ms, 3),
        "window_visible_after_response": window.isVisible(),
        "cleanup_complete": cleanup_complete,
        "cleanup_total_ms": round(close_total_ms, 3),
        "profile": dict(getattr(page, "last_close_profile", {})),
        "remaining_children": remaining_children,
    }
    result["event_loop_lag_warm_iterations_and_close"] = {
        "max_ms": round(max(lag_samples, default=0.0), 3),
        "over_50": sum(value > 50 for value in lag_samples),
        "over_100": sum(value > 100 for value in lag_samples),
        "over_250": sum(value > 250 for value in lag_samples),
        "over_500": sum(value > 500 for value in lag_samples),
        "over_1000": sum(value > 1000 for value in lag_samples),
    }
    rows = result["iterations"]
    if rows:
        first = float(rows[0]["usable_ms"])
        last = float(rows[-1]["usable_ms"])
        result["iteration_10_vs_1_percent"] = round((last - first) * 100.0 / max(0.001, first), 3)
        warm_first = float(rows[1]["usable_ms"]) if len(rows) > 1 else first
        result["warm_last_vs_first_percent"] = round(
            (last - warm_first) * 100.0 / max(0.001, warm_first), 3
        )
        second_half = rows[len(rows) // 2:]
        rss_values = [float(row["rss_mb"]) for row in second_half]
        result["rss_plateau"] = {
            "iteration_start": int(second_half[0]["iteration"]),
            "iteration_end": int(second_half[-1]["iteration"]),
            "min_mb": round(min(rss_values), 3),
            "max_mb": round(max(rss_values), 3),
            "span_mb": round(max(rss_values) - min(rss_values), 3),
            "slope_mb_per_iteration": round(
                (rss_values[-1] - rss_values[0]) / max(1, len(rss_values) - 1), 3
            ),
        }
        result["lifecycle_stability"] = {
            "studio_page_counts": sorted({int(row["studio_page_count"]) for row in rows}),
            "studio_session_counts": sorted({int(row["studio_session_count"]) for row in rows}),
            "mpv_actor_thread_counts": sorted({int(row["mpv_actor_threads"]) for row in rows}),
            "mpv_pids": sorted({int(row["mpv_pid"]) for row in rows if row["mpv_pid"] is not None}),
            "thread_counts": sorted({int(row["thread_count"]) for row in rows}),
            "child_counts": sorted({int(row["child_count"]) for row in rows}),
            "timer_counts": sorted({int(row["qt_timer_count"]) for row in rows}),
            "active_timer_counts": sorted({int(row["qt_active_timer_count"]) for row in rows}),
        }
    stability = result.get("lifecycle_stability", {})
    rss_plateau = result.get("rss_plateau", {})
    result["pass"] = bool(
        rows
        and all(row["usable"] for row in rows)
        and float(result.get("warm_last_vs_first_percent", 100.0)) <= 20.0
        and float(rss_plateau.get("span_mb", 999.0)) <= 12.0
        and float(rss_plateau.get("slope_mb_per_iteration", 999.0)) <= 1.5
        and stability.get("studio_page_counts") == [1]
        and stability.get("studio_session_counts") == [1]
        and stability.get("mpv_actor_thread_counts") == [1]
        and len(stability.get("mpv_pids", [])) == 1
        and visible_response_ms < 100.0
        and cleanup_complete
        and not remaining_children
    )
    target = output / "runtime-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)
    print(json.dumps({
        "pass": result["pass"],
        "constructor_ms": result["constructor_ms"],
        "iteration_10_vs_1_percent": result.get("iteration_10_vs_1_percent"),
        "warm_last_vs_first_percent": result.get("warm_last_vs_first_percent"),
        "rss_plateau": result.get("rss_plateau"),
        "lifecycle_stability": result.get("lifecycle_stability"),
        "close_under_load": result["close_under_load"],
        "startup_event_loop_lag": result.get("startup_event_loop_lag"),
        "event_loop_lag_warm_iterations_and_close": result["event_loop_lag_warm_iterations_and_close"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
