"""Capture Subtitle Studio inside the real 2ByteASR desktop shell."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402


def main() -> int:
    project = ROOT / "tmp" / "p20-studio-e2e" / "studio.2byteproj"
    if not project.is_file():
        raise FileNotFoundError(project)

    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setApplicationDisplayName("2ByteASR")
    app.setWindowIcon(ui._app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    window = ui.MainWindow([], subtitle_core, moss_firered_pipeline, {"id": "p20.2", "checks": 0})
    window.resize(1920, 1080)
    window.move(0, 0)
    window.show()

    def capture_home() -> None:
        app.processEvents()
        target = ROOT / "tmp" / "p20-studio-e2e" / "p20-5-main-toolbar-logo.png"
        pixmap = window.grab()
        if pixmap.isNull() or not pixmap.save(str(target)):
            raise RuntimeError("could not capture the main toolbar logo")
        print(f"captured main toolbar: {target}", flush=True)
        window._open_subtitle_studio(project)
        QTimer.singleShot(2200, capture_studio)

    def capture_studio() -> None:
        app.processEvents()
        pixmap = window.grab()
        if pixmap.width() != 1920 or pixmap.height() != 1080:
            pixmap = pixmap.scaled(
                1920,
                1080,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        target = ROOT / "tmp" / "p20-studio-e2e" / "p20-5-final-main-shell.png"
        if pixmap.isNull() or not pixmap.save(str(target)):
            raise RuntimeError("could not capture the main shell")
        print(f"captured main shell: {target}", flush=True)
        window.close()
        app.quit()

    QTimer.singleShot(1800, capture_home)
    result = app.exec()
    window.studio_page.close_page()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
