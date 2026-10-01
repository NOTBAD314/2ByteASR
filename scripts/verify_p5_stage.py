"""Offscreen + on-screen captures for P5 library / fill / export UI."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import FillEditorDialog, MotionBrowserDialog, SubtitleStudioPage
from twobyteasr.studio_project import SubtitleStyle


SHOTS = ROOT / "tmp" / "p5-accept"
SHOTS.mkdir(parents=True, exist_ok=True)


def pump(app: QApplication, ms: int = 80) -> None:
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def grab(widget, name: str) -> Path:
    target = SHOTS / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"could not save {target}")
    return target


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.show()
    pump(app, 200)
    page.show_project_hub()
    pump(app, 200)

    for width, height, name in ((1100, 760, "library-compact.png"), (1600, 960, "library-wide.png")):
        page.resize(width, height)
        pump(app, 160)
        if hasattr(page, "workspace_splitter"):
            origin = page.workspace_splitter.mapTo(page, page.workspace_splitter.rect().topLeft())
            page.studio_empty.setGeometry(
                origin.x(), origin.y(), page.workspace_splitter.width(), page.workspace_splitter.height()
            )
        page._refresh_studio_empty_state()
        pump(app, 160)
        grab(page, name)
        print(
            name,
            "new_btn", page.project_new_button.width(), page.project_new_button.height(),
            "hero", page.resume_preview.width(), page.resume_preview.height(),
            "mascot", page.project_library_mascot.width(), page.project_library_mascot.height(),
        )

    dialog = FillEditorDialog({
        "type": "linear-gradient",
        "stops": [
            {"color": "#FF20D6E8", "position": 0.0},
            {"color": "#DAD2FF20", "position": 1.0},
        ],
        "angle": 0,
    })
    dialog.resize(560, 720)
    dialog.show()
    dialog.mode_group.button(1).setChecked(True)
    dialog._select_gradient_stop(1)
    pump(app, 120)
    grab(dialog, "fill-editor.png")
    print("fill picker", dialog.picker.color().alpha(), "stop", dialog.gradient.opacity_spin.value())
    dialog.close()

    style = SubtitleStyle("demo", "Demo")
    motion = MotionBrowserDialog(style)
    motion.resize(980, 680)
    motion.show()
    pump(app, 120)
    grab(motion, "motion-library.png")
    cards = motion.findChildren(type(motion.host), "")
    motion.close()

    from twobyteasr.studio_export_ui import StudioExportWorkspace
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject

    project = SubtitleProject(
        media=StudioMedia(path="source.mp4", duration_ms=10_000, width=1920, height=1080),
        cues=[StudioCue("c1", 0, 1000, "hello")],
    )
    export = StudioExportWorkspace(project, str(ROOT / "tmp" / "preview.ass"))
    export.resize(1100, 720)
    export.show()
    export.success_name.setText("demo_export.mp4")
    export.success_meta.setText("源分辨率 · H.264 · 12.0 MB\n耗时 00:12")
    export.pages.setCurrentWidget(export.success_page)
    pump(app, 120)
    grab(export, "export-success.png")
    export.close()

    page.close_page()
    page.deleteLater()
    pump(app, 80)
    print("shots", SHOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
