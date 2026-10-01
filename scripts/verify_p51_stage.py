"""Capture P5.1 incremental UI for Hero, Fill, Stroke, AI, subtitle editor."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QToolButton

from twobyteasr.studio_ui import FillEditorDialog, SubtitleStudioPage
from twobyteasr.style_recipe import FillSpec
import os


SHOTS = ROOT / "tmp" / "p51-accept"
SHOTS.mkdir(parents=True, exist_ok=True)


def pump(app, ms=120):
    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)


def grab(widget, name: str) -> Path:
    target = SHOTS / name
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(target), "PNG"):
        raise RuntimeError(name)
    return target


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.show()
    pump(app, 160)
    page.show_project_hub()
    pump(app, 160)

    for width, height, name in ((1280, 820, "hero-compact.png"), (1680, 980, "hero-wide.png")):
        page.resize(width, height)
        pump(app, 120)
        origin = page.workspace_splitter.mapTo(page, page.workspace_splitter.rect().topLeft())
        page.studio_empty.setGeometry(origin.x(), origin.y(), page.workspace_splitter.width(), page.workspace_splitter.height())
        page._refresh_studio_empty_state()
        pump(app, 160)
        grab(page, name)
        print(name, "title_pt", page.resume_title.font().pointSize(), "h", page.resume_title.height())

    solid = FillEditorDialog("#FFFF4DA3")
    solid.resize(580, 720)
    solid.show()
    pump(app, 80)
    grab(solid, "fill-solid.png")
    solid.close()

    linear = FillEditorDialog({
        "type": "linear-gradient",
        "angle": 18,
        "stops": [{"color": "#FFFF5E5E", "position": 0.0}, {"color": "#FF5EC8FF", "position": 1.0}],
    })
    linear.resize(580, 720)
    linear.show()
    linear.mode_group.button(1).setChecked(True)
    pump(app, 80)
    grab(linear, "fill-linear.png")
    linear.close()

    radial = FillEditorDialog({
        "type": "radial-gradient",
        "stops": [{"color": "#FFFFFFFF", "position": 0.0}, {"color": "#FF20D6E8", "position": 1.0}],
    })
    radial.resize(580, 720)
    radial.show()
    radial.mode_group.button(2).setChecked(True)
    pump(app, 80)
    grab(radial, "fill-radial.png")
    radial.close()

    project = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "2ByteASR" / r"Projects\尼奈早稻机VLOG\尼奈早稻机VLOG.2byteproj"
    page.open_project(project)
    pump(app, 2500)
    page.select_cue(page.project.cues[0].id)
    pump(app, 200)
    page.context_drawer.setCurrentIndex(2)
    pump(app, 80)
    for button in page.context_panel.findChildren(type(page.ai_style_entry)):
        if button.text() in {"Advanced Style", "外观"}:
            if hasattr(button, "setChecked"):
                button.setChecked(button.text() == "外观")
    rows = page._appearance_rows
    rows["outline"].set_expanded(True)
    rows["fill"].set_expanded(False)
    pump(app, 120)
    grab(page.context_panel, "stroke-panel.png")
    grab(rows["outline"], "stroke-row.png")
    grab(page, "studio-editor.png")
    grab(page.subtitle_edit_card, "subtitle-edit-card.png")

    page.context_drawer.setCurrentIndex(0)
    pump(app, 80)
    grab(page.context_panel, "ai-input.png")
    page.ai_prompt.setPlainText("手工纸片感 字幕背景是皱的被裁剪过的纸 上面是手写字，像纸团展开一样的出现字幕")
    pump(app, 40)
    page._request_ai_suggestion()
    deadline = time.perf_counter() + 25
    while time.perf_counter() < deadline and getattr(page, "_pending_suggestion", None) is None:
        pump(app, 200)
    grab(page.context_panel, "ai-generated.png")
    if getattr(page, "_pending_suggestion", None) is not None:
        page._apply_ai_preview()
        pump(app, 400)
        grab(page.context_panel, "ai-applied-panel.png")
        page.context_drawer.setCurrentIndex(2)
        pump(app, 80)
        grab(page.context_panel, "advanced-after-ai.png")
        grab(page, "studio-after-ai.png")
        print("ai_name", page._pending_suggestion.recipe.name if page._pending_suggestion else page.ai_suggestion_title.text())
        print("saved_buttons", page.advanced_saved_layout.count())
    else:
        print("AI generate did not return a pending suggestion in time")
        print(page.ai_preview.toPlainText()[:400])

    print("edit_visible", page.subtitle_edit_card.isVisible(), "h", page.subtitle_edit_card.height())
    page.close_page()
    page.deleteLater()
    pump(app, 60)
    print("shots", SHOTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
