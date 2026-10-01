"""Interactive headed target for P25.2.11.1 native window-drag acceptance."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.setWindowTitle("P25.2.11.1 Window Drag Acceptance")
    page.resize(1400, 860)
    page.show()
    page.raise_()
    page.activateWindow()
    output = ROOT / "tmp" / "p25.2.11.1-usability" / "window-drag-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, object]] = []

    def record_state() -> None:
        geometry = page.geometry()
        state = {
            "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
            "maximized": page.isMaximized(),
        }
        if not history or history[-1] != state:
            history.append(state)
            output.write_text(
                json.dumps({"history": history}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    timer = QTimer(page)
    timer.setInterval(100)
    timer.timeout.connect(record_state)
    timer.start()
    record_state()
    result = app.exec()
    page.close_page()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
