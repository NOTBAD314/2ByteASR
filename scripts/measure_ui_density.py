"""UI 密度验收测量（开发工具，不参与应用发布逻辑）。

用法（在项目根目录）：
    .venv-main\\Scripts\\python.exe scripts\\measure_ui_density.py

输出：1366x768 与 1920x1080 下工坊侧栏/详情/列表宽度、每张模型卡的
可见高度与一屏完整卡数、主设置页横向溢出检查。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QScrollArea,
)

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402


def main() -> int:
    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())
    win = ui.MainWindow([], subtitle_core, moss_firered_pipeline, {"id": "measure", "checks": 0})
    win.show()
    app.processEvents()
    win._open_model_workshop()

    for width, height in ((1366, 768), (1920, 1080)):
        win.resize(width, height)
        app.processEvents()
        page = win.workshop_page
        sidebar = page.findChild(QFrame, "workshopSidebar")
        detail = page.findChild(QFrame, "workshopDetail")
        content = page.findChild(QFrame, "workshopContent")
        scroll = page.findChild(QScrollArea, "workshopScroll")
        viewport = scroll.viewport()
        print(
            f"== {width}x{height}: sidebar={sidebar.width()} "
            f"detail={detail.width()} content={content.width()} "
            f"list_viewport={viewport.width()}x{viewport.height()}"
        )
        full = partial = 0
        for key, card in page._cards.items():
            if not card.isVisible():
                continue
            top = card.mapTo(viewport, card.rect().topLeft()).y()
            bottom = card.mapTo(viewport, card.rect().bottomRight()).y()
            if top >= 0 and bottom <= viewport.height():
                full += 1
                state = "FULL"
            elif top < viewport.height() and bottom > 0:
                partial += 1
                state = "PART"
            else:
                state = "below"
            print(f"   {key:16s} y={top:4d} h={card.height():3d} {state}")
        print(f"   -> fully visible={full} partial={partial}")

        win.pages.setCurrentIndex(0)
        app.processEvents()
        areas = win.pages.currentWidget().findChildren(QScrollArea)
        hmax = max((area.horizontalScrollBar().maximum() for area in areas), default=0)
        print(f"   settings page horizontal overflow max={hmax}")
        win._open_model_workshop()

    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
