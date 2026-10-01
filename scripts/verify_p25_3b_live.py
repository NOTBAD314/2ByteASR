"""Visible Windows acceptance host for P25.3B Studio/export UX."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.ui import APP_QSS


SHOT_DIR = ROOT / "screenshots" / "p25.3b" / "live"


def save(widget, name: str) -> None:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(SHOT_DIR / name))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("2ByteASR P25.3B Live Acceptance")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = QMainWindow()
    window.setWindowTitle("2ByteASR P25.3B Live Acceptance")
    studio = SubtitleStudioPage(window)
    window.setCentralWidget(studio)
    window.resize(1600, 960)
    window.showMaximized()
    mode = next((arg[2:] for arg in sys.argv[1:] if arg.startswith("--")), "hub")
    target = next((Path(arg).resolve() for arg in sys.argv[1:] if not arg.startswith("--")), None)

    if target and target.is_file():
        QTimer.singleShot(250, lambda: studio.open_project(target))
        QTimer.singleShot(1300, studio.position_overlay_visual.close_overlay)

    if mode == "hub":
        QTimer.singleShot(1800, lambda: save(window, "hub-8-projects.png"))
        QTimer.singleShot(2100, app.quit)

    elif mode == "inline":
        def exercise_inline() -> None:
            window.activateWindow()
            QApplication.setActiveWindow(window)
            studio.timeline.setFocus()
            QTest.keyClick(studio, Qt.Key.Key_E)
            QTimer.singleShot(120, compose_inline)

        def compose_inline() -> None:
            editor = studio._canvas_editor
            if editor is None:
                raise RuntimeError("E did not create the canvas editor")
            preedit = QInputMethodEvent("第一行中文", [])
            QApplication.sendEvent(editor, preedit)
            commit = QInputMethodEvent()
            commit.setCommitString("第一行中文")
            QApplication.sendEvent(editor, commit)
            QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
            second = QInputMethodEvent()
            second.setCommitString("第二行中文")
            QApplication.sendEvent(editor, second)
            save(window, "inline-ime-two-lines.png")
            QTimer.singleShot(120, commit_inline)

        def commit_inline() -> None:
            editor = studio._canvas_editor
            if editor is None:
                raise RuntimeError("editor disappeared before Enter")
            QTest.keyClick(editor, Qt.Key.Key_Return)
            QTimer.singleShot(250, lambda: save(window, "inline-committed.png"))
            QTimer.singleShot(500, app.quit)
        QTimer.singleShot(1900, exercise_inline)

    elif mode == "export":
        def open_export() -> None:
            studio.project.media.duration_ms = max(40_000, int(studio.project.media.duration_ms or 0))
            studio._open_render_dialog()
        QTimer.singleShot(1800, open_export)

        def configure_and_start() -> None:
            workspace = studio.export_workspace
            save(window, "export-settings.png")
            workspace.quality.setCurrentIndex(workspace.quality.findData("custom"))
            save(window, "export-settings-custom.png")
            workspace.directory.setText(str(ROOT / "tmp" / "p25.3b"))
            workspace.filename.setText(f"live-export-{os.getpid()}")
            workspace.audio.setCurrentIndex(workspace.audio.findData("none"))
            resolution = workspace.resolution.findData((1280, 720))
            if resolution >= 0:
                workspace.resolution.setCurrentIndex(resolution)
            workspace.in_ms, workspace.out_ms = 0, 40_000
            workspace.export_range.setCurrentIndex(workspace.export_range.findData("in_out"))
            workspace._update_range()
            captured: set[int] = set()
            def progress(value: int, _payload: dict) -> None:
                for threshold in (10, 40, 80):
                    if value >= threshold and threshold not in captured:
                        captured.add(threshold)
                        save(window, f"export-running-{threshold}.png")
            workspace.progress_updated.connect(progress)
            workspace.render_succeeded.connect(lambda _path: QTimer.singleShot(300, capture_success))
            workspace._start()

        def capture_success() -> None:
            modal = QApplication.activeModalWidget()
            if modal is not None:
                save(modal, "export-success-dialog.png")
                modal.accept()
            save(window, "export-success-page.png")
            QTimer.singleShot(500, app.quit)

        QTimer.singleShot(2700, configure_and_start)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
