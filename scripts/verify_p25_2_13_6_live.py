"""Visible Windows acceptance host for Studio Polish + Export Reliability."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.ui import APP_QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("2ByteASR Studio Live Acceptance")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = QMainWindow()
    window.setWindowTitle("2ByteASR Studio Live Acceptance")
    studio = SubtitleStudioPage(window)
    window.setCentralWidget(studio)
    window.resize(1600, 960)
    window.showMaximized()

    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    render_mode = "--render" in sys.argv[2:] or "--render-run" in sys.argv[2:]
    render_run = "--render-run" in sys.argv[2:]
    full_range = "--full" in sys.argv[2:]
    custom_quality = "--custom" in sys.argv[2:]
    if target and target.is_file():
        QTimer.singleShot(300, lambda: studio.open_project(target))
        # The production transform visual is a non-focusable top-level window.
        # Disable only that visual in the acceptance host so Windows automation
        # can address the main HWND; Studio geometry and mpv remain untouched.
        QTimer.singleShot(1500, studio.position_overlay_visual.close_overlay)
        if render_mode:
            QTimer.singleShot(2300, studio._open_render_dialog)
        if render_run:
            if custom_quality:
                QTimer.singleShot(
                    2700,
                    lambda: studio.export_workspace.quality.setCurrentIndex(
                        studio.export_workspace.quality.findData("custom")
                    ),
                )
            def start_short_export() -> None:
                workspace = studio.export_workspace
                workspace.directory.setText(str(ROOT / "tmp"))
                workspace.filename.setText(f"p25-live-{os.getpid()}")
                workspace.audio.setCurrentIndex(workspace.audio.findData("none"))
                resolution_index = workspace.resolution.findData((1280, 720))
                if resolution_index >= 0:
                    workspace.resolution.setCurrentIndex(resolution_index)
                if not full_range:
                    workspace.in_ms, workspace.out_ms = 0, 12_000
                    workspace.export_range.setCurrentIndex(workspace.export_range.findData("in_out"))
                workspace._update_range()
                (ROOT / "tmp" / "p25-live-output.txt").write_text(
                    str(workspace.export_target().full_path), encoding="utf-8"
                )
                workspace._start()

            QTimer.singleShot(3000, start_short_export)

    screenshot = ROOT / "screenshots" / "p25.2.13.6" / (
        "live-export.png" if render_mode else ("live-project.png" if target else "live-hub.png")
    )

    def capture() -> None:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(screenshot))

    capture_delay = 4800 if render_run else (3600 if render_mode else 1800)
    QTimer.singleShot(capture_delay, capture)
    if render_run:
        QTimer.singleShot(
            2850,
            lambda: window.grab().save(str(screenshot.parent / "live-export-settings-custom.png")),
        )
        def capture_modal_and_success() -> None:
            modal = QApplication.activeModalWidget()
            if modal is None:
                QTimer.singleShot(250, capture_modal_and_success)
                return
            modal.grab().save(str(screenshot.parent / "live-export-success-dialog.png"))
            modal.accept()
            QTimer.singleShot(
                300,
                lambda: window.grab().save(str(screenshot.parent / "live-export-success-page.png")),
            )
            QTimer.singleShot(900, app.quit)

        QTimer.singleShot(3600, capture_modal_and_success)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
