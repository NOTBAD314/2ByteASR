"""Collect untranslated Chinese UI strings across main surfaces (offscreen).

Instantiates the real widgets, applies each language, then walks the trees.
A string is a "gap" when it still contains CJK after apply_ui_language and
is not explainable (model names / paths / user data are filtered heuristics).

Usage:
  .venv/Scripts/python.exe scripts/harvest_i18n_gaps.py --out tmp/i18n-gaps.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "tmp" / "i18n-gaps.json"))
    args = parser.parse_args()

    import os

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    tmp = Path(tempfile.mkdtemp())
    os.environ["LOCALAPPDATA"] = str(tmp)
    import twobyteasr.settings as settings_module

    settings_module.stable_settings_root = lambda: tmp

    from PySide6.QtWidgets import (
        QAbstractButton, QApplication, QComboBox, QGroupBox, QLabel,
        QLineEdit, QTabWidget, QTableWidget,
    )
    import subtitle_core as legacy
    import moss_firered_pipeline
    from twobyteasr import i18n
    from twobyteasr.ui import MainWindow
    from twobyteasr.application_settings import read_studio_preferences, project_library_root
    from twobyteasr.application_settings_ui import ApplicationSettingsDialog

    app = QApplication.instance() or QApplication([])

    # 已知翻译键（有词条的），用于判断"仍显示中文=真缺口"
    from twobyteasr.i18n import _KNOWN_KEYS

    window = MainWindow([], legacy, moss_firered_pipeline, {"id": "h", "checks": 0})
    prefs = read_studio_preferences()
    settings_dialog = ApplicationSettingsDialog(
        window, prefs, project_library_root(),
        browse=lambda *a: None, clear_recent=lambda: None, reset_layout=None)

    surfaces = {
        "main_window": window,
        "settings_dialog": settings_dialog,
    }
    # 工坊/术语库/历史等页面已作为 stacked 子页挂在 MainWindow 里，
    # 通过 findChildren 自然覆盖；单独打开的对话框树补充在上面。

    report = {"zh_counts": {}, "gaps": {}}
    for language in ("en", "ja"):
        i18n._CURRENT_LANGUAGE_CACHE = language
        gaps = []
        seen = set()
        for surface_name, root in surfaces.items():
            i18n.apply_ui_language(root, language)
        for surface_name, root in surfaces.items():
            widgets = [root, *root.findChildren(__import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget)]
            for w in widgets:
                texts = []
                if isinstance(w, QLabel):
                    texts.append(w.text())
                if isinstance(w, QAbstractButton):
                    texts.append(w.text())
                if isinstance(w, QGroupBox):
                    texts.append(w.title())
                if isinstance(w, QLineEdit):
                    texts.append(w.placeholderText())
                if isinstance(w, QComboBox):
                    texts.extend(w.itemText(i) for i in range(w.count()))
                if isinstance(w, QTabWidget):
                    texts.extend(w.tabText(i) for i in range(w.count()))
                if isinstance(w, QTableWidget):
                    texts.extend(w.horizontalHeaderItem(c).text() for c in range(w.columnCount())
                                 if w.horizontalHeaderItem(c))
                tip = w.toolTip()
                if tip:
                    texts.append(tip)
                for text in texts:
                    text = str(text).strip()
                    if not text or not CJK.search(text):
                        continue
                    if text in seen:
                        continue
                    seen.add(text)
                    gaps.append({"surface": surface_name, "text": text[:160]})
        report["gaps"][language] = gaps
        report["zh_counts"][language] = len(gaps)

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"en gaps: {report['zh_counts']['en']}, ja gaps: {report['zh_counts']['ja']}")
    print(f"written: {args.out}")
    settings_dialog.close()
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
