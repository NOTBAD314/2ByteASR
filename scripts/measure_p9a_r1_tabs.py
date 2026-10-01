"""Measure context-drawer tab widths at 440 px to size the medium tier correctly."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_theme import build_studio_qss
from twobyteasr.studio_ui import SubtitleStudioPage
from twobyteasr.theme_manager import apply_application_theme


def main() -> int:
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, "plum")
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.show()
    app.processEvents()
    drawer = getattr(page, "context_drawer", None)
    if drawer is None:
        print("no drawer")
        return 1
    bar = drawer.tabBar()
    for width in (360, 400, 440, 465, 500, 530, 560):
        page.context_panel.resize(width, page.context_panel.height())
        app.processEvents()
        page._update_context_tab_labels()
        app.processEvents()
        labels = [drawer.tabText(i) for i in range(drawer.count())]
        need = bar.sizeHint().width()
        visible = sum(1 for i in range(drawer.count()) if bar.tabRect(i).width() > 0)
        print(
            f"panel={width:3} drawer={drawer.width():3} bar_need={need:3} "
            f"labels={labels} tabs_with_rect={visible}/{drawer.count()}"
        )
    page.close_page()
    page.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
