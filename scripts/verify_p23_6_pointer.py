"""Headed Windows acceptance for the Qt-owned canvas overlay.

This intentionally uses OS mouse input. QTest/offscreen checks cannot prove
that the overlay is above the external mpv child window in a real desktop.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_SCALE_FACTOR", "1")
ROOT = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = str(ROOT / "tmp" / f"p23.7-canvas-{os.getpid()}")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage


USER32 = ctypes.windll.user32 if os.name == "nt" else None


def pump(app: QApplication, seconds: float = 0.1) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


def move_to(point: QPoint) -> None:
    USER32.SetCursorPos(int(point.x()), int(point.y()))


def left_button(down: bool) -> None:
    USER32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)


def click(point: QPoint, app: QApplication, *, double: bool = False) -> None:
    move_to(point)
    pump(app, 0.05)
    for _ in range(2 if double else 1):
        left_button(True)
        pump(app, 0.04)
        left_button(False)
        pump(app, 0.05)


def drag(origin: QPoint, target: QPoint, app: QApplication) -> None:
    move_to(origin)
    pump(app, 0.08)
    left_button(True)
    pump(app, 0.08)
    move_to(target)
    pump(app, 0.18)
    left_button(False)
    pump(app, 0.15)


def main() -> int:
    if USER32 is None:
        raise RuntimeError("P23.7 headed acceptance requires Windows user32 mouse input")
    source = Path(os.environ.get("P23_PROJECT", str(ROOT / "tmp" / "p20-studio-e2e" / "studio.2byteproj")))
    if not source.is_file():
        raise FileNotFoundError(f"Studio fixture not found: {source}")

    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.resize(1920, 1080)
    page.move(0, 0)
    page.show()
    page.open_project(source)
    pump(app, 1.5)
    page.select_cue(page.project.cues[0].id)
    page.activateWindow()
    page.raise_()
    page.position_overlay.sync_to_video(page.video)
    page.position_overlay.show()
    page.position_overlay.raise_()
    pump(app, 0.25)

    video_origin = page.video.mapToGlobal(QPoint(0, 0))
    rect = page.position_overlay._subtitle_rect().toRect()
    center = page.position_overlay.mapToGlobal(rect.center())
    print("overlay_geometry", page.position_overlay.geometry().getRect(), "center", center.x(), center.y(), "widget_at", type(app.widgetAt(center)).__name__ if app.widgetAt(center) else None, flush=True)
    before_position = (page.position_overlay.position_x, page.position_overlay.position_y)
    drag(center, center + QPoint(-100, -60), app)
    after_position = (page.position_overlay.position_x, page.position_overlay.position_y)
    page.undo_stack.undo()
    pump(app, 0.12)
    undo_position = (page.position_overlay.position_x, page.position_overlay.position_y)

    page.position_overlay.set_video_position(
        *before_position,
        page.position_overlay.play_res_x,
        page.position_overlay.play_res_y,
    )
    page.position_overlay.set_font_size(52)
    rect = page.position_overlay._subtitle_rect().toRect()
    handle = page.position_overlay.mapToGlobal(rect.bottomRight())
    before_font_size = page.position_overlay.font_size
    drag(handle, handle + QPoint(24, 24), app)
    after_font_size = page.position_overlay.font_size
    page.undo_stack.undo()
    pump(app, 0.12)
    undo_font_size = page.position_overlay.font_size

    rect = page.position_overlay._subtitle_rect().toRect()
    click(page.position_overlay.mapToGlobal(rect.center()), app, double=True)
    double_click_editor = getattr(page, "_canvas_editor", None) is not None

    report = {
        "fixture": str(source),
        "backend": {
            "class": type(page.video.controller).__name__ if page.video.controller else None,
            "is_in_process": False,
            "supports_canvas_events": False,
        },
        "video_global_origin": [video_origin.x(), video_origin.y()],
        "drag": {
            "before": before_position,
            "after": after_position,
            "changed": after_position != before_position,
            "undo": undo_position,
            "undo_restored": undo_position == before_position,
        },
        "resize": {
            "before": before_font_size,
            "after": after_font_size,
            "changed": after_font_size != before_font_size,
            "undo": undo_font_size,
            "undo_restored": undo_font_size == before_font_size,
        },
        "double_click_editor": double_click_editor,
        "overlay_visible": page.position_overlay.isVisible(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    page.close_page()
    page.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
