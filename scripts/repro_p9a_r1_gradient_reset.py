"""Minimal repro: does an inspector reload between fill-apply and stroke-commit drop the gradient?"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import load_project
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.style_recipe import FillSpec


def main() -> int:
    src = Path(os.environ["LOCALAPPDATA"]) / "2ByteASR" / "Projects" / "8月29日" / "8月29日.2byteproj"
    work = ROOT / "tmp" / "p9a-r1" / "repro"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    copy = work / src.name
    shutil.copy2(src, copy)

    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.resize(1920, 1080)
    page.show()
    app.processEvents()
    # Mirror the audit's tabs phase: maximize -> normal(860) -> maximize.
    page.showMaximized()
    for _ in range(30):
        app.processEvents()
    page.showNormal()
    page.resize(860, 700)
    for _ in range(30):
        app.processEvents()
    page.showMaximized()
    for _ in range(30):
        app.processEvents()
    page.context_drawer.setCurrentIndex(2)
    for _ in range(20):
        app.processEvents()
    page.open_project(copy)
    for _ in range(60):
        app.processEvents()
    page.select_cue(page.project.cues[0].id)
    for _ in range(20):
        app.processEvents()

    gradient = FillSpec.linear(
        [{"color": "#FFFFAA00", "position": 0.0}, {"color": "#FF00FF88", "position": 1.0}],
        angle=90,
    )
    page._apply_fill_spec(gradient)
    app.processEvents()
    print("after apply_fill_spec:", page._fill_spec.kind)

    page._load_style_inspector()  # what a resize/selection reload does
    app.processEvents()
    print("after inspector reload:", page._fill_spec.kind)

    page.style_outline_width.setValue(10.0)
    print("before commit: cue.style_id =", page._cue_lookup[page.selected_cue_id].style_id)
    print("before commit: recipes =", list(page.project.style_recipes))
    original_apply = page._apply_style

    def traced_apply(**kwargs):
        cue = page._cue_lookup.get(page.selected_cue_id)
        recipes_before = list(page.project.style_recipes)
        original_apply(**kwargs)
        cue_after = page._cue_lookup.get(page.selected_cue_id)
        print(
            "apply_style:", kwargs.get("replace_preset"),
            "| style", cue.style_id if cue else None, "->", cue_after.style_id if cue_after else None,
            "| recipes", recipes_before, "->", list(page.project.style_recipes),
        )

    page._apply_style = traced_apply
    page._apply_style()
    import time as _t
    deadline = _t.perf_counter() + 0.5
    while _t.perf_counter() < deadline:
        app.processEvents()
    app.processEvents()
    cue = page._cue_lookup[page.selected_cue_id]
    fill = page.project.style_recipes.get(cue.style_id, {}).get("colors", {}).get("fill")
    print("style_id:", cue.style_id)
    print("fill after stroke commit:", fill)

    page.close_page()
    page.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
