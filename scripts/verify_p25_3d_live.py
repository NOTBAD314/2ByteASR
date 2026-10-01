"""Visible Windows acceptance host for P25.3D live canvas and design workflow."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCALAPPDATA"] = str(ROOT / "tmp" / "p25.3d" / "local")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMainWindow

from twobyteasr.advanced_preview import AdvancedPreviewCache
from twobyteasr.studio_project import load_project
from twobyteasr.studio_ui import FillEditorDialog, FontPickerDialog, SubtitleStudioPage
from twobyteasr.ui import APP_QSS

PROJECT = ROOT / "tmp" / "p25.3c" / "mixed-authoritative-visuals.2byteproj"
EVIDENCE = ROOT / "screenshots" / "p25.3d"
REPORT = ROOT / "tmp" / "p25.3d" / "windows-acceptance.json"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("2ByteASR P25.3D Windows Acceptance")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    window = QMainWindow()
    window.setWindowTitle("2ByteASR P25.3D Live Advanced Canvas")
    studio = SubtitleStudioPage(window)
    studio._advanced_preview_cache = AdvancedPreviewCache(ROOT / "tmp" / "p25.3d" / f"cache-{os.getpid()}")
    window.setCentralWidget(studio)
    window.resize(1720, 980)
    window.showMaximized()
    studio.open_project(PROJECT)
    checks = {"fallbackPresentDuringLoad": False}

    def select_advanced() -> None:
        studio.select_cue("cyber")
        studio._seek(5.2)
        studio.video.set_paused(True)
        window.activateWindow(); window.raise_()
        QTimer.singleShot(80, lambda: checks.update(
            fallbackPresentDuringLoad=any(c.id == "cyber" for c in studio._ass_preview_snapshot(studio.project).cues)
        ))

    def prepare_capture() -> None:
        window.activateWindow(); QApplication.setActiveWindow(window); window.raise_()
        studio._sync_advanced_cue_overlay()

    def capture() -> None:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        screen = app.primaryScreen()
        screen.grabWindow(0).save(str(EVIDENCE / "windows-live-advanced.png"), "PNG")
        snapshot = getattr(studio.advanced_cue_overlay, "_snapshot", None)
        payload = {
            "qtPlatform": app.platformName(),
            "cueListVisible": studio.cue_list_panel.isVisible(),
            "toolPanelVisible": studio.context_panel.isVisible(),
            "splitterSizes": studio.upper_splitter.sizes(),
            "selectedCue": studio.selected_cue_id,
            "liveCanvasVisible": studio.advanced_cue_overlay.isVisible(),
            "liveUsesSnapshot": snapshot is not None and snapshot.cue_id == "cyber",
            "fallbackPresentDuringLoad": checks["fallbackPresentDuringLoad"],
            "systemFontCount": len(QFontDatabase.families()),
            "screenshot": str(EVIDENCE / "windows-live-advanced.png"),
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def show_font_picker() -> None:
        dialog = FontPickerDialog("Microsoft YaHei UI", 700, window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show(); dialog.raise_(); dialog.activateWindow()
        QTimer.singleShot(500, lambda: app.primaryScreen().grabWindow(0).save(str(EVIDENCE / "windows-font-picker.png"), "PNG"))
        QTimer.singleShot(900, dialog.close)

    def show_fill_editor() -> None:
        dialog = FillEditorDialog({"type": "linear-gradient", "stops": [
            {"color": "#FFFFD84A", "position": 0.0},
            {"color": "#FFFF4FA3", "position": 0.5},
            {"color": "#FF20D9FF", "position": 1.0},
        ], "angle": 25}, window)
        dialog.mode_group.button(1).setChecked(True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show(); dialog.raise_(); dialog.activateWindow()
        QTimer.singleShot(500, lambda: app.primaryScreen().grabWindow(0).save(str(EVIDENCE / "windows-fill-editor.png"), "PNG"))
        QTimer.singleShot(1000, dialog.close)

    QTimer.singleShot(900, select_advanced)
    QTimer.singleShot(19_500, prepare_capture)
    QTimer.singleShot(20_000, capture)
    QTimer.singleShot(21_000, show_font_picker)
    QTimer.singleShot(23_000, show_fill_editor)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
