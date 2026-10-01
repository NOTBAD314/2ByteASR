"""Formal headed Gradient residency evidence for P7.2.

This drives the production MainWindow/mpv/Advanced preview path. It is an
automated headed harness, not a real-user click session.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p72" / "gradient-residency"
MEDIA = ROOT / "tmp" / "p72" / "media" / "p72-av-8s.mp4"
PROJECT = OUTPUT / "p72-gradient-residency.2byteproj"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"]).unlink(missing_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

import psutil
from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.advanced_preview import AdvancedPreviewResidency
from twobyteasr.p64_runtime_audit import _print_window, _window_bounds
from twobyteasr.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    SubtitleStyle,
    save_project,
)
from twobyteasr.style_recipe import FillSpec
from twobyteasr.visual_runtime import VisualOwner
from twobyteasr.window_audit import qt_top_level_widgets, win32_top_level_windows


GRADIENT_ID = "gradient"
NORMAL_ID = "normal"
GRADIENT_MS = 1_000
NORMAL_MS = 5_000
AWAY_SECONDS = tuple(
    int(value)
    for value in os.environ.get(
        "TWOBYTEASR_P72_GRADIENT_AWAY_SECONDS", "1,10,60,300",
    ).split(",")
    if value.strip()
)
REPEAT_ROUNDS = max(
    1, int(os.environ.get("TWOBYTEASR_P72_GRADIENT_REPEAT_ROUNDS", "20")),
)


def progress(message: str) -> None:
    print(f"[p72-gradient] {message}", flush=True)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return round(ordered[index], 3)


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        QTest.qWait(min(10, max(1, round((deadline - time.perf_counter()) * 1000))))


def wait_until(app: QApplication, predicate, timeout: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return (time.perf_counter() - started) * 1000.0
        QTest.qWait(5)
    raise TimeoutError(f"{label} was not ready within {timeout:.1f}s")


def descendants() -> set[int]:
    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


def fixture_project() -> Path:
    if not MEDIA.is_file():
        raise FileNotFoundError(MEDIA)
    project = SubtitleProject(
        media=StudioMedia(
            path=str(MEDIA), display_name=MEDIA.name, duration_ms=8_000,
            width=640, height=360,
        ),
        cues=[
            StudioCue(GRADIENT_ID, 500, 3_500, "BLUE YELLOW", style_id=GRADIENT_ID),
            StudioCue(NORMAL_ID, 4_500, 7_500, "NORMAL", style_id="default"),
        ],
        speakers=[StudioSpeaker("S00", "Speaker")],
        styles=[
            SubtitleStyle("default", "Default", font_family="Arial", font_size=84),
            SubtitleStyle(
                GRADIENT_ID, "Gradient", font_family="Arial", font_size=112,
                bold=True, outline_width=0, shadow=0,
                position_x=960, position_y=540,
            ),
        ],
        style_recipes={
            GRADIENT_ID: {
                "name": "P7.2 Blue Yellow Gradient",
                "engine": "remotion",
                "typography": {},
                "colors": {
                    "fill": FillSpec.linear([
                        {"color": "#FF168BFF", "position": 0.0},
                        {"color": "#FFFFD84A", "position": 1.0},
                    ]).to_dict(),
                },
                "outline": {"width": 0, "shadow": 0},
                "background": {},
                "effects": {},
                "layout": {},
                "motion": {"mode": "none"},
                "ass": {},
            },
        },
        render_settings={"play_res_x": 1920, "play_res_y": 1080},
    )
    project.validate()
    return save_project(project, PROJECT)


def qimage_to_pil(image: QImage) -> Image.Image:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(converted.bits()[: converted.sizeInBytes()])
    return Image.frombuffer(
        "RGBA", (converted.width(), converted.height()), raw, "raw", "RGBA",
        converted.bytesPerLine(), 1,
    ).copy()


def pixmap_metrics(pixmap: QPixmap) -> dict[str, object]:
    if pixmap.isNull():
        return {
            "correct_gradient": False,
            "blue_pixels": 0,
            "yellow_pixels": 0,
            "opaque_pixels": 0,
        }
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    blue = yellow = opaque = 0
    # Sparse sampling keeps the acceptance probe below the interaction budget.
    # The glyph spans hundreds of pixels at the production 1280x720 tier, so
    # an 8px grid still samples both gradient ends without perturbing latency.
    for y in range(0, image.height(), 8):
        for x in range(0, image.width(), 8):
            color = image.pixelColor(x, y)
            if color.alpha() < 160:
                continue
            opaque += 1
            blue += color.blue() > color.red() + 20 and color.blue() > 140
            yellow += color.red() > 175 and color.green() > 130 and color.blue() < 155
    return {
        "correct_gradient": bool(blue > 2 and yellow > 2),
        "blue_pixels": int(blue),
        "yellow_pixels": int(yellow),
        "opaque_pixels": int(opaque),
        "size": [pixmap.width(), pixmap.height()],
    }


def applied_overlay_sequence(page) -> int:
    controller = page.video.controller
    if controller is None:
        return 0
    applied = controller.applied_visual_state()
    overlay = applied.get("overlays", {}).get(page.video.ADVANCED_OVERLAY_ID, {})
    return int(overlay.get("sequence", 0))


def visual_ready(page, *, after_overlay_sequence: int) -> bool:
    canvas = page.advanced_cue_overlay
    snapshot = getattr(canvas, "_snapshot", None)
    source = getattr(canvas, "_source", QPixmap())
    controller = page.video.controller
    applied = controller.applied_visual_state() if controller is not None else {}
    subtitle = applied.get("subtitle", {})
    overlay = applied.get("overlays", {}).get(page.video.ADVANCED_OVERLAY_ID, {})
    ownership = page._visual_ownership.current
    return bool(
        snapshot is not None
        and snapshot.cue_id == GRADIENT_ID
        and canvas.isVisible()
        and not source.isNull()
        and page._advanced_preview_state.residency in {
            AdvancedPreviewResidency.LIVE,
            AdvancedPreviewResidency.FIDELITY,
            AdvancedPreviewResidency.CACHED_FIDELITY,
        }
        and ownership.cue_id == GRADIENT_ID
        and ownership.owner in {
            VisualOwner.ADVANCED_LIVE, VisualOwner.ADVANCED_FIDELITY,
        }
        and ownership.foreground_owner_count == 1
        and subtitle.get("visible") is False
        and overlay.get("visible") is True
        and int(overlay.get("sequence", 0)) > max(
            int(subtitle.get("sequence", 0)), int(after_overlay_sequence)
        )
    )


def capture_composite(window, page, name: str, elapsed_ms: float) -> dict[str, object]:
    hwnd = int(window.winId())
    bounds = _window_bounds(hwnd)
    base = _print_window(hwnd).convert("RGBA")
    canvas = page.advanced_cue_overlay
    layer = qimage_to_pil(canvas.grab().toImage())
    dpr = float(canvas.devicePixelRatioF() or 1.0)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    offset = (
        round(origin.x() * dpr - bounds[0]),
        round(origin.y() * dpr - bounds[1]),
    )
    if canvas.isVisible():
        base.alpha_composite(layer, dest=offset)
    target = OUTPUT / f"{name}.png"
    base.convert("RGB").save(target)
    source = getattr(canvas, "_source", QPixmap())
    return {
        "path": str(target),
        "elapsed_ms": round(float(elapsed_ms), 3),
        "method": "PrintWindow+Qt-overlay",
        "canvas_visible": canvas.isVisible(),
        "canvas_offset": list(offset),
        "canvas_geometry": list(canvas.geometry().getRect()),
        "pixels": pixmap_metrics(source),
    }


def seek_and_wait(app: QApplication, page, cue_id: str, milliseconds: int) -> dict[str, object]:
    started = time.perf_counter()
    started_monotonic = time.perf_counter()
    before_overlay_sequence = applied_overlay_sequence(page)
    page._seek(milliseconds / 1000.0)
    seek_return_ms = (time.perf_counter() - started) * 1000.0
    correct_ms = 0.0
    detected_correct_ms = 0.0
    if cue_id == GRADIENT_ID:
        wait_until(
            app,
            lambda: visual_ready(
                page, after_overlay_sequence=before_overlay_sequence,
            ),
            2.0,
            "correct Gradient visual",
        )
        detected_correct_ms = (time.perf_counter() - started) * 1000.0
        controller = page.video.controller
        applied = controller.applied_visual_state() if controller is not None else {}
        overlay = applied.get("overlays", {}).get(page.video.ADVANCED_OVERLAY_ID, {})
        correct_ms = max(
            0.0,
            (
                float(
                    overlay.get(
                        "perf_counter",
                        overlay.get("monotonic", started_monotonic),
                    )
                )
                - started_monotonic
            )
            * 1000.0,
        )
    wait_until(
        app,
        lambda: (
            page.selected_cue_id == cue_id
            and abs(int(page.timeline.playhead_ms) - milliseconds) < 350
        ),
        5.0,
        f"cue {cue_id} active",
    )
    active_ms = (time.perf_counter() - started) * 1000.0
    return {
        "seek_return_ms": round(seek_return_ms, 3),
        "active_ms": round(active_ms, 3),
        "correct_ms": round(correct_ms, 3),
        "detected_correct_ms": round(detected_correct_ms, 3),
        "timing_source": "mpv_overlay_ack" if cue_id == GRADIENT_ID else "none",
        "previous_overlay_sequence": before_overlay_sequence,
    }


def first_activation(app: QApplication, window, page, traces: list[dict[str, object]]) -> dict[str, object]:
    trace_start = len(traces)
    started = time.perf_counter()
    started_monotonic = time.perf_counter()
    before_overlay_sequence = applied_overlay_sequence(page)
    page._seek(GRADIENT_MS / 1000.0)
    wait_until(
        app,
        lambda: visual_ready(
            page, after_overlay_sequence=before_overlay_sequence,
        ),
        2.0,
        "cold correct Gradient",
    )
    detected_live_ms = (time.perf_counter() - started) * 1000.0
    controller = page.video.controller
    applied = controller.applied_visual_state() if controller is not None else {}
    overlay = applied.get("overlays", {}).get(page.video.ADVANCED_OVERLAY_ID, {})
    live_ms = max(
        0.0,
        (
            float(
                overlay.get(
                    "perf_counter", overlay.get("monotonic", started_monotonic),
                )
            )
            - started_monotonic
        )
        * 1000.0,
    )
    wait_until(
        app,
        lambda: (
            page.selected_cue_id == GRADIENT_ID
            and abs(int(page.timeline.playhead_ms) - GRADIENT_MS) < 350
        ),
        5.0,
        "cold Gradient active",
    )
    active_at = time.perf_counter()
    samples = [capture_composite(window, page, "cold-active", live_ms)]
    for label, offset_ms in (("50ms", 50), ("100ms", 100), ("500ms", 500)):
        remaining = offset_ms - (time.perf_counter() - active_at) * 1000.0
        if remaining > 0:
            pump(app, round(remaining))
        samples.append(capture_composite(
            window, page, f"cold-{label}", (time.perf_counter() - started) * 1000.0,
        ))
    wait_until(
        app,
        lambda: page._advanced_preview_state.residency in {
            AdvancedPreviewResidency.FIDELITY,
            AdvancedPreviewResidency.CACHED_FIDELITY,
        },
        120.0,
        "Gradient fidelity",
    )
    fidelity_ms = (time.perf_counter() - started) * 1000.0
    relevant = traces[trace_start:]
    event_ms = {
        str(row["event"]): round(float(row["monotonic_ms"]) - started * 1000.0, 3)
        for row in relevant
        if row.get("event") in {
            "ADVANCED_SELECT", "SNAPSHOT_CREATED", "LIVE_READY", "WORKER_START",
            "WORKER_FINISH", "WORKER_PUBLISH", "CANVAS_FRAME_SET", "ADVANCED_READY",
        }
    }
    return {
        "active_ms": round((active_at - started) * 1000.0, 3),
        "correct_live_ms": round(live_ms, 3),
        "detected_correct_live_ms": round(detected_live_ms, 3),
        "timing_source": "mpv_overlay_ack",
        "previous_overlay_sequence": before_overlay_sequence,
        "fidelity_visible_ms": round(fidelity_ms, 3),
        "event_timeline_ms": event_ms,
        "samples": samples,
        "residency": page._advanced_preview_state.residency.value,
    }


def reentry(app: QApplication, page, away_seconds: int) -> dict[str, object]:
    seek_and_wait(app, page, NORMAL_ID, NORMAL_MS)
    away_started = time.perf_counter()
    while time.perf_counter() - away_started < away_seconds:
        pump(app, min(250, round((away_seconds - (time.perf_counter() - away_started)) * 1000.0)))
    measurement = seek_and_wait(app, page, GRADIENT_ID, GRADIENT_MS)
    source = getattr(page.advanced_cue_overlay, "_source", QPixmap())
    measurement.update({
        "away_seconds": away_seconds,
        "residency": page._advanced_preview_state.residency.value,
        "pixels": pixmap_metrics(source),
        "worker_running": bool(page._advanced_preview_worker_running),
        "pending_job": page._advanced_preview_pending_job is not None,
    })
    return measurement


def repeated_seek(app: QApplication, page) -> dict[str, object]:
    rows: list[float] = []
    for index in range(REPEAT_ROUNDS):
        seek_and_wait(app, page, NORMAL_ID, NORMAL_MS)
        measurement = seek_and_wait(app, page, GRADIENT_ID, GRADIENT_MS)
        rows.append(measurement["correct_ms"])
        progress(
            f"repeat {index + 1:02d}/{REPEAT_ROUNDS} "
            f"correct={measurement['correct_ms']:.3f} ms"
        )
    return {
        "rounds": len(rows),
        "samples_ms": rows,
        "p50_ms": percentile(rows, 0.50),
        "p95_ms": percentile(rows, 0.95),
        "max_ms": round(max(rows), 3),
        "mean_ms": round(statistics.fmean(rows), 3),
    }


def child_records() -> list[dict[str, object]]:
    path = Path(os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"])
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("root_pid") == os.getpid():
            rows.append(row)
    return rows


def main() -> int:
    project_path = fixture_project()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR P7.2 Gradient Residency")
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    ui.apply_application_theme(app)
    result: dict[str, object] = {
        "schema": "2byteasr.p72-gradient-residency.v1",
        "evidence_class": "FORMAL HEADED PRODUCTION MAINWINDOW",
        "real_user_click": False,
        "project": str(project_path),
        "media": str(MEDIA),
        "pid": os.getpid(),
    }
    window = None
    before_pids = descendants()
    traces: list[dict[str, object]] = []
    method_spans: list[dict[str, object]] = []
    try:
        progress("constructing production MainWindow")
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        window.setWindowTitle("2ByteASR P7.2 Gradient Residency")
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 500)
        window.open_studio_project(project_path, source="p72-gradient-residency")
        page = window.studio_page
        wait_until(
            app,
            lambda: page.video.controller is not None and page.video.controller.running,
            25.0,
            "real mpv",
        )
        original_trace = page._studio_trace

        def capture_trace(event: str, **fields: object) -> None:
            traces.append({
                "event": str(event),
                "monotonic_ms": time.perf_counter() * 1000.0,
                **fields,
            })
            original_trace(event, **fields)

        page._studio_trace = capture_trace

        def profile_method(owner, name: str) -> None:
            original = getattr(owner, name)

            def measured(*args, **kwargs):
                started = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    method_spans.append({
                        "method": name,
                        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    })

            setattr(owner, name, measured)

        for owner, names in (
            (page, (
                "_seek", "_position_changed", "_finish_deferred_seek_feedback",
                "_follow_playhead_selection", "_schedule_advanced_preview",
                "_publish_advanced_frame", "ensure_active_subtitle_renderer",
                "_load_style_inspector",
            )),
        ):
            for name in names:
                profile_method(owner, name)
        page.follow_playhead_toggle.setChecked(True)
        page.video.set_paused(True)
        seek_and_wait(app, page, NORMAL_ID, NORMAL_MS)

        progress("cold first activation")
        result["cold_first_activation"] = first_activation(app, window, page, traces)
        result["cold_first_activation"]["renderer_processes_after_fidelity"] = [
            item.pid
            for item in psutil.Process().children(recursive=True)
            if (item.name() or "").casefold() in {"node.exe", "chrome.exe", "chromium.exe"}
        ]

        reentries = []
        for away_seconds in AWAY_SECONDS:
            progress(f"waiting away for {away_seconds}s")
            row = reentry(app, page, away_seconds)
            reentries.append(row)
            progress(f"re-entry {away_seconds}s correct={row['correct_ms']:.3f} ms")
        result["reentries"] = reentries

        progress(f"running {REPEAT_ROUNDS} A/B rounds")
        result["repeat_seek"] = repeated_seek(app, page)
        result["trace"] = traces
        result["method_spans"] = method_spans
        result["cache_telemetry"] = page._runtime_cache.snapshot()
        result["resource_governor"] = asdict(page._resource_governor.snapshot())
        pids = descendants()
        result["window_audit"] = {
            "visible_win32": [item for item in win32_top_level_windows(pids=pids) if item.get("visible")],
            "visible_qt": [item for item in qt_top_level_widgets(app) if item.get("visible")],
            "active_compositor_overlay_ids": page.video.active_compositor_overlay_ids(),
        }
        result["child_process_records"] = child_records()
        cold = result["cold_first_activation"]
        result["checks"] = {
            "cold_correct_lt_100": cold["correct_live_ms"] < 100.0,
            "cold_samples_are_gradient": all(
                sample["pixels"]["correct_gradient"] for sample in cold["samples"]
            ),
            "reentry_all_lt_50": all(row["correct_ms"] < 50.0 for row in reentries),
            "reentry_all_gradient": all(row["pixels"]["correct_gradient"] for row in reentries),
            "repeat_p95_lt_50": result["repeat_seek"]["p95_ms"] < 50.0,
            "no_renderer_process_after_fidelity": not cold["renderer_processes_after_fidelity"],
        }
        result["pass"] = all(result["checks"].values())
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump(app, 800)
        remaining = descendants() - before_pids - {os.getpid()}
        result["remaining_child_pids"] = sorted(remaining)
        result["no_remaining_children"] = not remaining
        result["pass"] = bool(result.get("pass") and result["no_remaining_children"])
    target = OUTPUT / "runtime-result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target, flush=True)
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
