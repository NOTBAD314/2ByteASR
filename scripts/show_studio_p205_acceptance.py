"""Capture real P20.5 workspace and Style Inspector states at 1920x1080."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.studio_ui import SubtitleStudioPage  # noqa: E402


def main() -> int:
    fixture_root = ROOT / "tmp" / "p20-studio-e2e"
    project_path = fixture_root / "studio.2byteproj"
    report_path = fixture_root / "p20-5-phase-a-report.json"
    screenshots = {
        "expanded": fixture_root / "p20-5-phase-a-expanded.png",
        "timeline_first": fixture_root / "p20-5-phase-a-timeline-first.png",
        "restored": fixture_root / "p20-5-phase-a-restored.png",
        "style": fixture_root / "p20-5-phase-b-style.png",
        "mpv_subtitles": fixture_root / "p20-5-mpv-subtitles.png",
    }

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setApplicationDisplayName("2ByteASR")
    app.setWindowIcon(ui._app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    page = SubtitleStudioPage()
    page.setWindowTitle("2ByteASR Subtitle Studio P20.5 Phase A")
    page.resize(1920, 1080)
    page.show()
    page.open_project(project_path)
    globals()["_p205_window"] = page
    report: dict[str, object] = {}

    def capture(name: str) -> None:
        page.updateGeometry()
        page.repaint()
        app.processEvents()
        # QWidget capture reflects hidden splitter children reliably. The
        # native mpv child is validated separately with screenshot-to-file.
        pixmap = page.grab()
        if pixmap.isNull() or not pixmap.save(str(screenshots[name])):
            raise RuntimeError(f"could not save {name} screenshot")

    def expanded() -> None:
        duration = page.timeline._duration_ms()
        page.timeline.set_visible_window(0, min(20_000, max(1_000, duration // 3)))
        page.timeline.reveal_playhead(min(duration, 12_600), force=True)
        page.context_drawer.setCurrentIndex(0)
        page._show_context_panel()
        controller = page.video.controller
        if controller and controller.running:
            controller.set_speed(1.0)
            controller.set_paused(True)
            controller.seek(12.6, accurate=True)
        QTimer.singleShot(650, capture_expanded)

    def capture_expanded() -> None:
        controller = page.video.controller
        mpv_state = {}
        if controller and controller.running:
            for name in ("sid", "sub-text", "sub-visibility", "track-list", "time-pos"):
                try:
                    mpv_state[name] = controller.get_property(name)
                except RuntimeError as exc:
                    mpv_state[name] = str(exc)
            try:
                controller._send(
                    ["screenshot-to-file", str(screenshots["mpv_subtitles"]), "subtitles"],
                    timeout=5.0,
                )
            except RuntimeError as exc:
                mpv_state["screenshot_error"] = str(exc)
        capture("expanded")
        report["expanded"] = {
            "window": [page.width(), page.height()],
            "horizontal_scroll_visible": page.timeline.horizontal_scrollbar.isVisible(),
            "horizontal_range": [
                page.timeline.horizontal_scrollbar.minimum(),
                page.timeline.horizontal_scrollbar.maximum(),
            ],
            "page_step": page.timeline.horizontal_scrollbar.pageStep(),
            "visible_start_ms": page.timeline.visible_start_ms,
            "waveform_visible": page.timeline.waveform_visible,
            "waveform_loaded": page.timeline.cache is not None,
            "context_tabs": [
                page.context_drawer.tabText(index)
                for index in range(page.context_drawer.count())
            ],
            "mpv": mpv_state,
            "mpv_subtitle_screenshot": screenshots["mpv_subtitles"].is_file(),
        }
        QTimer.singleShot(350, timeline_first)

    def timeline_first() -> None:
        page._set_major_panel_visible("cue_list", False)
        page._set_major_panel_visible("editor", False)
        page._set_major_panel_visible("context", False)
        page.workspace_splitter.setSizes([560, 440])
        QTimer.singleShot(500, capture_timeline_first)

    def capture_timeline_first() -> None:
        capture("timeline_first")
        report["timeline_first"] = {
            "cue_list_visible": page.cue_list_panel.isVisible(),
            "editor_visible": page.cue_editor.isVisible(),
            "context_visible": page.context_panel.isVisible(),
            "workspace_sizes": page.workspace_splitter.sizes(),
        }
        QTimer.singleShot(350, restored)

    def restored() -> None:
        page._set_major_panel_visible("cue_list", True)
        page._set_major_panel_visible("editor", True)
        page._set_major_panel_visible("context", True)
        page._set_editor_field_visible("start", False)
        page.context_drawer.setCurrentIndex(2)
        page.center_splitter.setSizes([480, 190])

        cue = page.project.cues[0]
        original = cue.text
        page._timeline_text_edited(cue.id, False, original + "（验收）")
        inline_applied = cue.text.endswith("（验收）")
        page.undo_stack.undo()
        inline_undone = cue.text == original

        speeds: list[float] = []
        controller = page.video.controller
        if controller and controller.running:
            original_set_speed = controller.set_speed

            def record_speed(value: float) -> None:
                speeds.append(float(value))
                original_set_speed(value)

            controller.set_speed = record_speed
            page._shuttle(0)
            for _ in range(4):
                page._shuttle(1)
            page._shuttle(0)
            controller.set_speed = original_set_speed

        QTimer.singleShot(500, lambda: capture_restored(inline_applied, inline_undone, speeds))

    def capture_restored(inline_applied: bool, inline_undone: bool, speeds: list[float]) -> None:
        capture("restored")
        report["restored"] = {
            "cue_list_visible": page.cue_list_panel.isVisible(),
            "editor_visible": page.cue_editor.isVisible(),
            "context_visible": page.context_panel.isVisible(),
            "active_tab": page.context_drawer.tabText(page.context_drawer.currentIndex()),
            "start_field_visible": page.start_ms.isVisible(),
            "inline_applied": inline_applied,
            "inline_undo": inline_undone,
            "l_shuttle_speeds": speeds,
            "speaker_tracks": len(page.timeline.speaker_ids()),
        }
        QTimer.singleShot(300, capture_style)

    def capture_style() -> None:
        page.context_drawer.setCurrentIndex(2)
        page._show_context_panel()
        page.style_font.setEditText("Microsoft YaHei UI")
        page.style_font_size.setValue(58.0)
        page.style_spacing.setValue(1.0)
        page.style_bold.setChecked(True)
        page.style_italic.setChecked(True)
        page.style_fill_color.setText("#F4F1E8")
        page.style_outline_color.setText("#25332A")
        page.style_outline_width.setValue(3.5)
        page.style_shadow.setValue(1.5)
        page._apply_style()
        app.processEvents()
        capture("style")
        applied = next(item for item in page.project.styles if item.id == "default")
        report["style"] = {
            "font_family": applied.font_family,
            "font_size": applied.font_size,
            "spacing": applied.spacing,
            "bold": applied.bold,
            "italic": applied.italic,
            "outline_width": applied.outline_width,
            "shadow": applied.shadow,
            "active_tab": page.context_drawer.tabText(page.context_drawer.currentIndex()),
        }
        report["screenshots"] = {key: str(value) for key, value in screenshots.items()}
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        page.close_page()
        page.close()
        app.quit()

    QTimer.singleShot(2500, expanded)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
