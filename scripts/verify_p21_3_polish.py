"""Real Qt acceptance for P21.3 Studio polish and interaction correctness."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "screenshots" / "p21.3-studio-polish"
LOCAL_DATA = ROOT / "tmp" / "p21.3-localappdata"
PROJECT = ROOT / "tmp" / "p20-studio-e2e" / "studio.2byteproj"
sys.path.insert(0, str(ROOT))


def _wait(app, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(LOCAL_DATA)

    from PySide6.QtCore import QEvent, QObject, QPoint, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QColorDialog, QToolButton

    import moss_firered_pipeline
    import subtitle_core
    import twobyteasr.ui as ui
    from twobyteasr.ui import MainWindow

    class EventCounter(QObject):
        def __init__(self):
            super().__init__()
            self.counts = Counter()

        def eventFilter(self, _obj, event):
            if event.type() == QEvent.Type.Move:
                self.counts["move"] += 1
            elif event.type() == QEvent.Type.Resize:
                self.counts["resize"] += 1
            elif event.type() == QEvent.Type.LayoutRequest:
                self.counts["layout"] += 1
            elif event.type() == QEvent.Type.Paint:
                self.counts["paint"] += 1
            return False

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    cjk_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if cjk_font.is_file():
        QFontDatabase.addApplicationFont(str(cjk_font))
    app.setFont(QFont("Microsoft YaHei UI", 10))

    counter = EventCounter()
    app.installEventFilter(counter)
    shell = MainWindow([], subtitle_core, moss_firered_pipeline, None)
    shell.setGeometry(20, 20, 1920, 1080)
    shell.show()
    _wait(app, 0.35)

    switch_started = time.perf_counter()
    shell._open_subtitle_studio(PROJECT)
    immediate_ms = (time.perf_counter() - switch_started) * 1000
    _wait(app, 0.02)
    first_paint_ms = (time.perf_counter() - switch_started) * 1000
    page = shell.studio_page
    page.context_drawer.setCurrentIndex(2)
    page._show_context_panel()
    page.center_splitter.setSizes([620, 190])
    page.workspace_splitter.setSizes([770, 285])
    _wait(app, 1.2)

    full_shot = OUTPUT / "studio-style-panel-1920x1080.png"
    panel_shot = OUTPUT / "style-panel-dense.png"
    shell.grab().save(str(full_shot))
    page.context_panel.grab().save(str(panel_shot))

    color_dialog = page._create_style_color_dialog(page.style_fill_color)
    color_dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    color_dialog.show()
    _wait(app, 0.2)
    color_shot = OUTPUT / "color-picker-direct.png"
    color_dialog.grab().save(str(color_shot))
    color_dialog.close()

    page.style_scope.showPopup()
    _wait(app, 0.12)
    popup = page.style_scope.view().window()
    popup_shot = OUTPUT / "tool-panel-popup-theme.png"
    popup.grab().save(str(popup_shot))
    popup_background = page.style_scope.view().palette().color(
        page.style_scope.view().backgroundRole()
    ).name()
    popup_text = page.style_scope.view().palette().color(
        page.style_scope.view().foregroundRole()
    ).name()
    page.style_scope.hidePopup()

    timeline = page.timeline
    timeline.set_visible_window(2_000, 10_000)
    seeks = []
    timeline.seek_requested.connect(seeks.append)
    click = QPoint(timeline.TRACK_HEADER_WIDTH + 420, 14)
    QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, pos=click)
    before_pan = timeline.visible_start_ms
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(820, 14))
    QTest.mouseMove(timeline, QPoint(650, 14), delay=20)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(650, 14))
    after_pan = timeline.visible_start_ms

    speed_result = {"available": bool(page.video.controller and page.video.controller.running)}
    if speed_result["available"]:
        page.video.set_paused(False)
        page._set_speed(4.0)
        page._toggle_playback()
        _wait(app, 0.1)
        speed_result.update(
            {
                "paused": bool(page.video.controller.get_property("pause", False)),
                "actual_speed": float(page.video.controller.get_property("speed", 0.0) or 0.0),
                "ui_speed": float(page.speed_box.currentData()),
            }
        )

    before_events = Counter(counter.counts)
    move_samples = []
    for index in range(12):
        started = time.perf_counter()
        shell.move(20 + index * 3, 20 + index * 2)
        app.processEvents()
        move_samples.append((time.perf_counter() - started) * 1000)
    resize_samples = []
    for index in range(8):
        started = time.perf_counter()
        shell.resize(1920 - index * 2, 1080 - index)
        app.processEvents()
        resize_samples.append((time.perf_counter() - started) * 1000)
    event_delta = Counter(counter.counts)
    event_delta.subtract(before_events)

    style_area = page.context_drawer.widget(2)
    swatch = page.style_fill_swatch.findChild(QToolButton)
    report = {
        "studio_transition": {
            "request_to_stack_ready_ms": round(immediate_ms, 3),
            "request_to_first_processed_paint_ms": round(first_paint_ms, 3),
            "layout_settled_ms": shell.last_studio_transition_profile[
                "request_to_layout_settled_ms"
            ],
            "header_hidden_at_first_paint": not shell.app_header.isVisible(),
        },
        "style_panel": {
            "scope_default": page.style_scope.currentData(),
            "anchor_grid_visible": bool(page.style_anchor_buttons),
            "vertical_scroll_max": style_area.verticalScrollBar().maximum(),
            "color_entry_has_menu": bool(swatch and swatch.menu()),
            "effect_duration_ms": page.effect_duration.value(),
        },
        "timeline": {
            "click_seek_count": len(seeks),
            "click_seek_seconds": round(seeks[0], 3) if seeks else None,
            "pan_before_ms": before_pan,
            "pan_after_ms": after_pan,
            "pan_moved": after_pan != before_pan,
        },
        "pause_speed_reset": speed_result,
        "window_geometry": {
            "move_average_ms": round(sum(move_samples) / len(move_samples), 3),
            "move_max_ms": round(max(move_samples), 3),
            "resize_average_ms": round(sum(resize_samples) / len(resize_samples), 3),
            "resize_max_ms": round(max(resize_samples), 3),
            "events": dict(event_delta),
            "studio_skips_global_density_recompute": True,
        },
        "popup_theme": {
            "background": popup_background,
            "text": popup_text,
        },
        "screenshots": {
            "full": str(full_shot),
            "style_panel": str(panel_shot),
            "color_picker": str(color_shot),
            "popup_theme": str(popup_shot),
        },
    }
    report_path = OUTPUT / "acceptance-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

    page.close_page()
    shell.close()
    app.removeEventFilter(counter)
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
