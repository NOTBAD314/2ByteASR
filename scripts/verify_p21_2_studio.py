"""Retained P21.2 Studio focus, playback, navigation, and style acceptance."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "screenshots" / "p21.2-studio-focus"
LOCAL_DATA = ROOT / "tmp" / "p21.2-localappdata"
PROJECT = ROOT / "tmp" / "p20-studio-e2e" / "studio.2byteproj"
sys.path.insert(0, str(ROOT))


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * ratio))]


def _wait(app, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(LOCAL_DATA)

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    import moss_firered_pipeline
    import subtitle_core
    import twobyteasr.ui as ui
    from twobyteasr.ui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    cjk_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if cjk_font.is_file():
        QFontDatabase.addApplicationFont(str(cjk_font))
    app.setFont(QFont("Microsoft YaHei UI", 10))

    shell = MainWindow([], subtitle_core, moss_firered_pipeline, None)
    shell.show()
    _wait(app, 0.4)
    shell.showNormal()
    shell.setGeometry(0, 0, 1920, 1080)
    _wait(app, 0.3)
    shell.pages.setCurrentWidget(shell.studio_page)
    _wait(app, 0.2)
    after_height = shell.pages.height()
    header_hidden = not shell.app_header.isVisible()
    shell.app_header.show()
    _wait(app, 0.1)
    before_height = shell.pages.height()
    shell.app_header.hide()
    _wait(app, 0.1)
    after_height = shell.pages.height()

    page = shell.studio_page
    page.open_project(PROJECT)
    page.context_drawer.setCurrentIndex(2)
    page._show_context_panel()
    page.center_splitter.setSizes([600, 145])
    page.workspace_splitter.setSizes([760, 260])
    _wait(app, 2.0)

    full_shot = OUTPUT / "style-inspector-1920x1080.png"
    panel_shot = OUTPUT / "style-inspector-panel.png"
    appearance_shot = OUTPUT / "style-inspector-appearance.png"
    if not shell.grab().save(str(full_shot)):
        raise RuntimeError("could not capture the 1920x1080 Studio screenshot")
    if not page.context_panel.grab().save(str(panel_shot)):
        raise RuntimeError("could not capture the Style Inspector panel")

    style_area = page.context_drawer.widget(2)
    viewport = style_area.viewport()
    style_area.verticalScrollBar().setValue(0)
    _wait(app, 0.1)
    core_controls = {
        "preset": page.style_preset,
        "font": page.style_font,
        "font_size": page.style_font_size,
        "spacing": page.style_spacing,
        "bold": page.style_bold,
        "alignment": page.style_anchor_buttons[2],
        "position_x": page.style_position_x,
        "position_y": page.style_position_y,
        "fill": page.style_fill_swatch,
        "stroke": page.style_outline_width,
    }
    clipping = {}
    for name, control in core_controls.items():
        top_left = control.mapTo(viewport, QPoint(0, 0))
        clipping[name] = {
            "visible": control.isVisibleTo(viewport),
            "top": top_left.y(),
            "bottom": top_left.y() + control.height(),
            "within_viewport": 0 <= top_left.y() and top_left.y() + control.height() <= viewport.height(),
        }
    style_area.ensureWidgetVisible(page.style_outline_width, 12, 40)
    _wait(app, 0.1)
    if not page.context_panel.grab().save(str(appearance_shot)):
        raise RuntimeError("could not capture the Style Inspector appearance section")
    style_area.verticalScrollBar().setValue(0)

    controller = page.video.controller
    playback = {"available": bool(controller and controller.running), "drift": {}}
    if controller and controller.running:
        for speed in (1.0, 2.0, 4.0, 8.0):
            page.video.set_paused(True)
            page.video.seek(1.0, accurate=True)
            page.video.set_speed(speed)
            page.video.set_paused(False)
            samples = []
            signed_samples = []
            deadline = time.perf_counter() + 1.25
            while time.perf_counter() < deadline and not page.video.at_eof:
                app.processEvents()
                try:
                    real = float(controller.get_property("time-pos", 0.0) or 0.0)
                    signed = (page.video.visual_position() - real) * 1000.0
                    signed_samples.append(signed)
                    samples.append(abs(signed))
                except (RuntimeError, TypeError, ValueError):
                    pass
                time.sleep(0.045)
            page.video.set_paused(True)
            playback["drift"][f"{speed:g}x"] = {
                "samples": len(samples),
                "p95_ms": round(_percentile(samples, 0.95), 3),
                "max_ms": round(max(samples, default=0.0), 3),
                "first_abs_ms": round(samples[0], 3) if samples else 0.0,
                "last_abs_ms": round(samples[-1], 3) if samples else 0.0,
                "growth_ms": round(samples[-1] - samples[0], 3) if samples else 0.0,
                "mean_signed_ms": round(sum(signed_samples) / len(signed_samples), 3) if signed_samples else 0.0,
            }

        page.video.seek(16.0, accurate=True)
        page.video.set_speed(4.0)
        page.video.set_paused(False)
        deadline = time.perf_counter() + 4.0
        while time.perf_counter() < deadline and not page.video.at_eof:
            app.processEvents()
            time.sleep(0.02)
        eof_time = page.video.visual_position()
        eof_real = controller.get_property("time-pos", None)
        eof_state = {
            "reached": page.video.at_eof,
            "visual_seconds": round(eof_time, 6),
            "mpv_seconds": round(float(eof_real), 6) if eof_real is not None else None,
            "paused": page.video._paused,
        }
        page._toggle_playback()
        _wait(app, 0.35)
        replay_real = controller.get_property("time-pos", None)
        playback["eof"] = eof_state
        playback["space_replay"] = {
            "started": replay_real is not None and 0.0 <= float(replay_real) < 3.0,
            "mpv_seconds": round(float(replay_real), 6) if replay_real is not None else None,
            "paused": bool(controller.get_property("pause", True)),
        }
        page.video.set_paused(True)

    timeline = page.timeline
    timeline.set_visible_window(4_000, 8_000)
    start = timeline.visible_start_ms
    timeline._pan_drag = (800.0, start)
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, Qt
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(650.0, 12.0),
        QPointF(650.0, 12.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    timeline.mouseMoveEvent(move)
    pan_after = timeline.visible_start_ms
    timeline._pan_drag = None

    report = {
        "window": [shell.width(), shell.height()],
        "studio_focus": {
            "header_hidden": header_hidden,
            "usable_height_before": before_height,
            "usable_height_after": after_height,
            "height_gained": after_height - before_height,
        },
        "playback": playback,
        "timeline_ruler_pan": {
            "before_ms": start,
            "after_ms": pan_after,
            "moved": pan_after != start,
        },
        "style_panel": {
            "viewport": [viewport.width(), viewport.height()],
            "horizontal_scrollbar_visible": style_area.horizontalScrollBar().isVisible(),
            "core_controls": clipping,
            "all_core_controls_in_first_view": all(item["within_viewport"] for item in clipping.values()),
        },
        "screenshots": {
            "full": str(full_shot),
            "panel": str(panel_shot),
            "appearance": str(appearance_shot),
        },
    }
    report_path = OUTPUT / "acceptance-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    page.close_page()
    shell.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
