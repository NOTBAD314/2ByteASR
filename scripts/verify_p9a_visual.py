"""Headed P9A screenshots of current sources. Does not rebuild the packaged EXE."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots" / "p9a" / "after"
OUTPUT = ROOT / "tmp" / "p9a-visual"
SOURCE = Path(
    Path(__file__).resolve().parents[1] / r"tmp\p22.10-acceptance\real-242-copy.2byteproj"
)
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from PySide6.QtWidgets import QScrollArea  # noqa: E402

from twobyteasr.color_picker import SimpleColorDialog  # noqa: E402
from twobyteasr.studio_export_ui import SubtitleExportDialog  # noqa: E402
from twobyteasr.studio_highlight_ui import HighlightAssistantPanel  # noqa: E402
from twobyteasr.studio_ui import SubtitleStudioPage  # noqa: E402
from twobyteasr.theme_manager import apply_application_theme  # noqa: E402
from twobyteasr.ui_recognition import RecognitionPlanWidget  # noqa: E402


def pump(app: QApplication, milliseconds: int = 80) -> None:
    deadline = time.perf_counter() + milliseconds / 1000
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        time.sleep(0.01)


def capture(widget, name: str) -> Path:
    SHOTS.mkdir(parents=True, exist_ok=True)
    target = SHOTS / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(f"could not capture {target}")
    return target


def main() -> int:
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    copy_dir = OUTPUT / SOURCE.stem
    copy_dir.mkdir(parents=True, exist_ok=True)
    project_copy = copy_dir / SOURCE.name
    shutil.copy2(SOURCE, project_copy)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_application_theme(app, "plum")
    page = SubtitleStudioPage()
    page.resize(1920, 1080)
    page.show()
    pump(app, 160)
    page.open_project(project_copy)
    pump(app, 900)
    if page.project and page.project.cues:
        page.select_cue(page.project.cues[0].id)
    page._show_context_panel()

    drawer = page.context_drawer
    drawer.setCurrentIndex(2)
    pump(app, 160)
    rows = getattr(page, "_appearance_rows", None) or {}
    shadow_row = rows.get("shadow")
    if shadow_row is not None:
        shadow_row.set_expanded(True)
        pump(app, 80)
        for area in page.context_panel.findChildren(QScrollArea):
            area.ensureWidgetVisible(shadow_row)
        pump(app, 80)
        capture(shadow_row, "style-shadow-angle.png")
        fill_row = rows.get("fill")
        outline_row = rows.get("outline")
        if fill_row is not None:
            capture(fill_row, "style-fill-summary.png")
        if outline_row is not None:
            capture(outline_row, "style-stroke-summary.png")
        parent = shadow_row.parentWidget()
        if parent is not None:
            capture(parent, "style-appearance-rows.png")
    capture(page, "studio-style-1920x1080.png")
    capture(page.context_panel, "style-inspector-panel.png")
    capture(page.studio_toolbar, "studio-topbar.png")
    capture(drawer.tabBar(), "tool-panel-tabs.png")
    page.style_font.showPopup()
    pump(app, 80)
    popup = page.style_font.view().window() if page.style_font.view() is not None else None
    if popup is not None:
        capture(popup, "combo-popup.png")
    page.style_font.hidePopup()
    pump(app, 40)

    drawer.setCurrentIndex(1)
    pump(app, 120)
    capture(page, "studio-check-1920x1080.png")
    capture(page.context_panel, "review-inspector-panel.png")

    drawer.setCurrentIndex(0)
    pump(app, 120)
    capture(page, "studio-ai-1920x1080.png")

    drawer.setCurrentIndex(3)
    pump(app, 120)
    capture(page.context_panel, "video-inspector-panel.png")

    drawer.setCurrentIndex(4)
    pump(app, 120)
    capture(page.highlight_panel, "clip-assistant-loaded.png")
    empty_panel = HighlightAssistantPanel()
    empty_panel.resize(380, 420)
    empty_panel.empty_setup.show()
    empty_panel.config_body.hide()
    empty_panel.config_toggle.hide()
    empty_panel.analyze_button.hide()
    empty_panel.config_summary.hide()
    empty_panel.status.hide()
    empty_panel.show()
    pump(app, 80)
    capture(empty_panel.empty_setup, "clip-assistant-empty.png")
    empty_panel.close()

    drawer.setCurrentIndex(5)
    pump(app, 120)
    capture(page.context_panel, "media-pool-panel.png")

    export = SubtitleExportDialog(page.project, project_copy, page)
    export.show()
    pump(app, 120)
    capture(export, "export-subtitle-dialog.png")
    export.close()

    picker = SimpleColorDialog(QColor("#f47c68"), page)
    picker.show()
    pump(app, 120)
    capture(picker, "color-picker.png")
    picker.close()

    plan = RecognitionPlanWidget()
    plan.resize(1200, 420)
    plan.cards["primary"].set_state("MOSS", "本地", "已就绪", "good")
    plan.cards["timeline"].set_state("FireRedASR2-AED", "本地", "已就绪", "good")
    plan.cards["review"].set_state("Qwen3-ASR", "本地", "已就绪", "good")
    plan.show()
    pump(app, 120)
    capture(plan, "recognition-model-cards.png")
    plan.close()

    try:
        import moss_firered_pipeline
        import subtitle_core
        from twobyteasr.ui import MainWindow

        home = MainWindow(
            [],
            subtitle_core,
            moss_firered_pipeline,
            {"id": "p9a", "checks": 0},
        )
        apply_application_theme(app, "plum")
        home.resize(1600, 1000)
        home.show()
        pump(app, 500)
        capture(home, "recognition-home.png")
        home.close()
    except Exception as exc:
        print(f"recognition-home skipped: {exc}")

    page.resize(2560, 1440)
    pump(app, 200)
    capture(page, "studio-max-2560x1440.png")

    page.close_page()
    page.close()
    print(f"wrote {SHOTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
