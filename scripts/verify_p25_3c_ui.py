"""Windows Qt smoke: open Studio, invoke the edit card, and capture evidence."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"
WORKSPACE = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = str(WORKSPACE / "tmp" / "p25.3c" / "local")
sys.path.insert(0, str(WORKSPACE))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitleStudioPage


PROJECT = WORKSPACE / "tmp" / "p25.3c" / "mixed-authoritative-visuals.2byteproj"
SCREENSHOT_DIR = WORKSPACE / "screenshots" / "p25.3c"


def main() -> None:
    app = QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    page.video.load = lambda *_args, **_kwargs: None
    page._generate_waveform = lambda *_args, **_kwargs: None
    page.resize(1500, 930)
    page.open_project(PROJECT)
    page.show(); page.activateWindow(); page.raise_(); page.setFocus()
    app.processEvents()
    selected = page.selected_cue_id
    QTest.keyClick(page, Qt.Key.Key_E)
    app.processEvents()
    editor = page._canvas_editor
    opened = editor is page.subtitle_edit_input and page.subtitle_edit_card.isVisible()
    if editor is not None:
        editor.setPlainText("Windows IME 编辑卡\nShift+Enter 多行")
    app.processEvents()
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot = SCREENSHOT_DIR / "studio-edit-card-windows.png"
    page.grab().save(str(screenshot), "PNG")
    if editor is not None:
        QTest.keyClick(editor, Qt.Key.Key_Return)
    app.processEvents()
    committed = page._cue_lookup[selected].text == "Windows IME 编辑卡\nShift+Enter 多行"
    report = {
        "qtPlatform": app.platformName(), "selectedCue": selected,
        "editCardOpened": opened, "enterCommitted": committed,
        "screenshot": str(screenshot),
    }
    (WORKSPACE / "tmp" / "p25.3c" / "ui-acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    page.close_page(); page.close(); app.processEvents()
    if not (opened and committed and app.platformName().casefold() == "windows"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
