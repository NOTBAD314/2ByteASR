"""Dump the settings-page widget texts for verification (offscreen).

Usage: .venv-main\\Scripts\\python.exe scripts\\dump_ui_texts.py
Prints every QLabel / button / combo text found under the main window,
so label rendering can be verified without vision.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "2byteasr_settings.json"

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(ROOT))


def main() -> int:
    import moss_firered_pipeline
    import subtitle_core
    from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QLabel, QLineEdit
    from twobyteasr.ui import MainWindow

    payload = json.loads(SETTINGS.read_text(encoding="utf-8"))
    backup = json.loads(SETTINGS.read_text(encoding="utf-8"))
    for language in ("zh", "en"):
        payload.setdefault("ui", {})["language"] = language
        SETTINGS.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow([], subtitle_core, moss_firered_pipeline, {"id": "dump", "checks": 0})
        print(f"===== language={language} =====")
        for widget in window.findChildren(QLabel):
            text = widget.text()
            if text:
                print(f"  L: {text}")
        for widget in window.findChildren(QAbstractButton):
            text = widget.text()
            if text:
                print(f"  B: {text}")
        for widget in window.findChildren(QComboBox):
            items = [widget.itemText(i) for i in range(widget.count())]
            print(f"  C: {items[:6]}")
        window.close()
        app.processEvents()
    SETTINGS.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print("settings restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
