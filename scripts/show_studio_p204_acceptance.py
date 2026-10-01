"""Run the real P20.4 Studio fixture and retain the warm window for desktop QA."""

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
    report_path = fixture_root / "p20-4-acceptance-report.json"
    live_state_path = fixture_root / "p20-4-live-state.json"
    screenshot_path = fixture_root / "p20-4-studio-final.png"

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setApplicationDisplayName("2ByteASR")
    app.setWindowIcon(ui._app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    report: dict[str, object] = {}
    cold = SubtitleStudioPage()
    cold.setWindowTitle("2ByteASR Subtitle Studio P20.4 Cold Profile")
    cold.resize(1920, 1080)
    cold.show()
    cold.open_project(project_path)

    def finish_cold() -> None:
        report["cold_open_seconds"] = cold.last_open_profile
        cold.hide()
        cold.close_page()
        report["cold_close_seconds"] = cold.last_close_profile
        cold.deleteLater()

        warm = SubtitleStudioPage()
        warm.setWindowTitle("2ByteASR Subtitle Studio P20.4 QA")
        warm.resize(1920, 1080)
        warm.show()
        warm.open_project(project_path)
        warm.video.setFocus()
        globals()["_p204_window"] = warm

        def write_live_state() -> None:
            focus = app.focusWidget()
            controller = warm.video.controller
            current = next(
                (cue for cue in warm.project.cues if cue.id == warm.selected_cue_id),
                None,
            ) if warm.project else None
            paused = None
            position = None
            if controller and controller.running:
                try:
                    paused = bool(controller.get_property("pause", True))
                    position = float(controller.get_property("time-pos", 0.0) or 0.0)
                except RuntimeError:
                    pass
            live_state_path.write_text(
                json.dumps(
                    {
                        "window_title": warm.windowTitle(),
                        "focus_class": focus.__class__.__name__ if focus else "",
                        "focus_name": focus.objectName() if focus else "",
                        "paused": paused,
                        "position_seconds": position,
                        "timeline_tool": warm.timeline.tool_mode,
                        "selected_cue": warm.selected_cue_id,
                        "cue_count": len(warm.project.cues) if warm.project else 0,
                        "current_text": warm.cue_text.toPlainText(),
                        "current_start_ms": current.start_ms if current else None,
                        "current_end_ms": current.end_ms if current else None,
                        "undo_available": warm.undo_stack.canUndo(),
                        "redo_available": warm.undo_stack.canRedo(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        live_timer = QTimer(warm)
        live_timer.setInterval(200)
        live_timer.timeout.connect(write_live_state)
        live_timer.start()
        write_live_state()

        def capture() -> None:
            report["warm_open_seconds"] = warm.last_open_profile
            report["fixture"] = {
                "project": str(project_path),
                "cue_count": len(warm.project.cues) if warm.project else 0,
                "speaker_tracks": len(warm.timeline.speaker_ids()),
                "waveform_loaded": warm.timeline.cache is not None,
                "active_context_tab": warm.context_drawer.tabText(warm.context_drawer.currentIndex()),
                "toolbar_has_duplicate_ai": hasattr(warm, "ai_button"),
                "toolbar_has_duplicate_style": hasattr(warm, "style_button"),
            }
            pixmap = warm.grab()
            if pixmap.isNull() or not pixmap.save(str(screenshot_path)):
                raise RuntimeError("Could not save P20.4 screenshot")
            report["screenshot"] = str(screenshot_path)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

        QTimer.singleShot(1800, capture)

    QTimer.singleShot(1600, finish_cold)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
