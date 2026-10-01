"""Formal headed P7.1C Transform transparency evidence with real mpv."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p71c" / "transform-headed"
SOURCE_PROJECT = ROOT / "tmp" / "p66-runtime" / "formal" / "p66-real-hour.2byteproj"
PROJECT_COPY = OUTPUT / "p71c-transform-real-hour.2byteproj"
OUTPUT.mkdir(parents=True, exist_ok=True)
shutil.copy2(SOURCE_PROJECT, PROJECT_COPY)
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(OUTPUT / f"localappdata-{os.getpid()}")
os.environ["TWOBYTEASR_CHILD_PROCESS_LOG"] = str(OUTPUT / "child-processes.jsonl")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    pass

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import moss_firered_pipeline
import subtitle_core
from twobyteasr import ui
from twobyteasr.p64_runtime_audit import _print_window, _window_bounds
from twobyteasr.window_audit import qt_top_level_widgets, win32_top_level_windows


def progress(message: str) -> None:
    print(f"[p71c-transform] {message}", flush=True)


def pump(app: QApplication, milliseconds: int = 0) -> None:
    deadline = time.perf_counter() + max(0, milliseconds) / 1000.0
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        QTest.qWait(5)


def wait_until(app: QApplication, predicate, timeout: float, label: str) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        app.processEvents()
        if predicate():
            return round((time.perf_counter() - started) * 1000.0, 1)
        QTest.qWait(10)
    raise TimeoutError(f"{label} was not ready within {timeout:.1f}s")


def descendants() -> set[int]:
    import psutil

    result = {os.getpid()}
    try:
        result.update(item.pid for item in psutil.Process().children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return result


def qimage_to_pil(image: QImage) -> Image.Image:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(converted.bits()[: converted.sizeInBytes()])
    return Image.frombuffer(
        "RGBA",
        (converted.width(), converted.height()),
        raw,
        "raw",
        "RGBA",
        converted.bytesPerLine(),
        1,
    ).copy()


def save_mpv_screenshot(app: QApplication, page, name: str) -> Path:
    target = OUTPUT / name
    if target.exists():
        target.unlink()
    page.video.controller.screenshot_to_file(target, mode="window")
    wait_until(app, target.is_file, 8.0, f"mpv screenshot {name}")
    if target.stat().st_size <= 0:
        raise RuntimeError(f"empty mpv screenshot: {target}")
    return target


def transform_alpha_image(overlay) -> tuple[Path, dict[str, object]]:
    image = QImage(overlay.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    overlay._draw_transform_visual(painter)
    painter.end()
    target = OUTPUT / "transform-alpha-layer.png"
    image.save(str(target), "PNG")

    rect = overlay._subtitle_rect().toAlignedRect()
    interior = rect.adjusted(12, 12, -12, -12).intersected(image.rect())
    anchor = overlay._screen_point()
    nontransparent = 0
    max_alpha = 0
    for y in range(interior.top(), interior.bottom() + 1):
        for x in range(interior.left(), interior.right() + 1):
            if abs(x - anchor.x()) <= 10 and abs(y - anchor.y()) <= 10:
                continue
            alpha = image.pixelColor(x, y).alpha()
            max_alpha = max(max_alpha, alpha)
            nontransparent += alpha > 0
    edge_alpha = max(
        image.pixelColor(
            max(0, min(image.width() - 1, rect.left() + offset)),
            max(0, min(image.height() - 1, rect.center().y())),
        ).alpha()
        for offset in range(-4, 5)
    )
    return target, {
        "subtitle_rect": list(rect.getRect()),
        "interior_rect": list(interior.getRect()),
        "interior_nontransparent_pixels_excluding_controls": nontransparent,
        "interior_max_alpha_excluding_controls": max_alpha,
        "edge_max_alpha": edge_alpha,
        "handle_count": len(overlay._handle_centers(overlay._subtitle_rect())),
    }


def printwindow_qt_composite(window, overlay) -> tuple[Path, dict[str, object]]:
    hwnd = int(window.winId())
    bounds = _window_bounds(hwnd)
    base = _print_window(hwnd).convert("RGBA")
    layer = qimage_to_pil(overlay.grab().toImage())
    alpha_bounds = layer.getchannel("A").getbbox()
    dpr = float(overlay.devicePixelRatioF() or 1.0)
    global_origin = overlay.mapToGlobal(QPoint(0, 0))
    offset = (
        round(global_origin.x() * dpr - bounds[0]),
        round(global_origin.y() * dpr - bounds[1]),
    )
    base.alpha_composite(layer, dest=offset)
    target = OUTPUT / "transform-printwindow-qt-composite.png"
    base.convert("RGB").save(target)
    return target, {
        "method": "PrintWindow+Qt-overlay",
        "hwnd": hwnd,
        "window_bounds": list(bounds),
        "overlay_offset": list(offset),
        "overlay_pixels": list(layer.size),
        "overlay_alpha_bounds": list(alpha_bounds or ()),
    }


def contact_sheet(printwindow_path: Path, mpv_path: Path) -> Path:
    panels = []
    for label, path in (
        ("PrintWindow + Qt interaction layer", printwindow_path),
        ("Real mpv compositor (subtitle + Transform)", mpv_path),
    ):
        image = Image.open(path).convert("RGB")
        image.thumbnail((900, 520), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (920, 570), (25, 28, 31))
        panel.paste(image, ((920 - image.width) // 2, 36))
        ImageDraw.Draw(panel).text((14, 12), label, fill=(238, 241, 244))
        panels.append(panel)
    sheet = Image.new("RGB", (1840, 570), (18, 20, 22))
    sheet.paste(panels[0], (0, 0))
    sheet.paste(panels[1], (920, 0))
    target = OUTPUT / "transform-headed-contact-sheet.png"
    sheet.save(target)
    return target


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR P7.1C Transform Formal Headed Acceptance")
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    ui.apply_application_theme(app)
    result: dict[str, object] = {
        "schema": "2byteasr.p71c-transform-headed.v1",
        "evidence_class": "FORMAL HEADED VERIFIED",
        "real_user_click": False,
        "project": str(PROJECT_COPY),
        "pid": os.getpid(),
    }
    window = None
    try:
        progress("constructing production MainWindow")
        window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, None)
        window.setWindowTitle("2ByteASR P7.1C Transform Formal Headed Acceptance")
        window.resize(1800, 1050)
        window.show()
        window.activateWindow()
        pump(app, 700)
        window.open_studio_project(PROJECT_COPY, source="p71c-transform-headed")
        page = window.studio_page
        wait_until(
            app,
            lambda: page.video.controller is not None and page.video.controller.running,
            25.0,
            "real mpv",
        )
        cue = page.project.cues[0]
        page.select_cue(cue.id)
        page.timeline.set_playhead(cue.start_ms + min(500, cue.end_ms - cue.start_ms - 1))
        page._seek((cue.start_ms + min(500, cue.end_ms - cue.start_ms - 1)) / 1000.0)
        page.video.set_paused(True)
        wait_until(
            app,
            lambda: bool(page.video.controller.get_property("pause", False)),
            6.0,
            "mpv pause",
        )
        page.ensure_active_subtitle_renderer(reason="p71c_transform_selected")
        if not page.position_edit_button.isChecked():
            QTest.mouseClick(page.position_edit_button, Qt.MouseButton.LeftButton)
        page.ensure_active_subtitle_renderer(reason="p71c_transform_enabled")
        wait_until(app, page.position_overlay.isVisible, 5.0, "Transform visibility")
        wait_until(
            app,
            lambda: page.video.TRANSFORM_OVERLAY_ID
            in page.video.active_compositor_overlay_ids(),
            5.0,
            "Transform mpv compositor overlay",
        )
        pump(app, 350)

        alpha_path, alpha_metrics = transform_alpha_image(page.position_overlay)
        printwindow_path, printwindow_metrics = printwindow_qt_composite(
            window, page.position_overlay,
        )
        mpv_path = save_mpv_screenshot(app, page, "transform-mpv-composite.png")
        sheet_path = contact_sheet(printwindow_path, mpv_path)
        mpv_image = Image.open(mpv_path).convert("RGB")
        extrema = mpv_image.getextrema()
        nonblank_mpv = any(low != high for low, high in extrema)

        pids = descendants()
        final_win32 = win32_top_level_windows(pids=pids)
        final_qt = qt_top_level_widgets(app)
        result.update({
            "cue": {
                "id": cue.id,
                "text": cue.text,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
            },
            "transform": {
                "visible": page.position_overlay.isVisible(),
                "is_window": page.position_overlay.isWindow(),
                "native_window": page.position_overlay.testAttribute(
                    Qt.WidgetAttribute.WA_NativeWindow
                ),
                **alpha_metrics,
            },
            "mpv": {
                "running": page.video.controller.running,
                "sid": page.video.controller.get_property("sid", None),
                "pause": page.video.controller.get_property("pause", None),
                "time_pos": page.video.controller.get_property("time-pos", None),
                "active_compositor_overlay_ids": page.video.active_compositor_overlay_ids(),
                "composite_nonblank": nonblank_mpv,
            },
            "screenshots": {
                "transform_alpha_layer": str(alpha_path),
                "printwindow_qt_composite": str(printwindow_path),
                "printwindow_metrics": printwindow_metrics,
                "mpv_composite": str(mpv_path),
                "contact_sheet": str(sheet_path),
            },
            "window_audit": {
                "visible_win32": [item for item in final_win32 if item.get("visible")],
                "visible_qt": [item for item in final_qt if item.get("visible")],
            },
        })
        result["pass"] = bool(
            result["transform"]["visible"]
            and not result["transform"]["is_window"]
            and not result["transform"]["native_window"]
            and result["transform"]["interior_nontransparent_pixels_excluding_controls"] == 0
            and result["transform"]["edge_max_alpha"] > 0
            and result["transform"]["handle_count"] >= 8
            and page.video.TRANSFORM_OVERLAY_ID
            in result["mpv"]["active_compositor_overlay_ids"]
            and result["mpv"]["composite_nonblank"]
        )
    except Exception as exc:
        result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            pump(app, 250)
    target = OUTPUT / "result.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
