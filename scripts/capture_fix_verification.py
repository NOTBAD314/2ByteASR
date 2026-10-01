"""Capture screenshots proving UI/UX fixes for this round.
- ModalHost dim (main UI header+cards visibly darker, Card bright ivory, no black gaps)
- Model Picker no black gaps between cards + ★ recommended visible
- Term Library classic two-pane layout + full category labels
- Workshop detail width stable
- Technical first screen order + no per-line yellows + wrap + benchmark table

Run:
  .venv-main\Scripts\python.exe scripts\capture_fix_verification.py

Outputs go to screenshots/ui_fixes/*.png
"""

from __future__ import annotations
import os
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Do NOT force offscreen for this verification so we get real desktop raster (actual window compositing for dim proof).
# If the session is headless, caller can set QT_QPA_PLATFORM=offscreen externally.

from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout  # noqa: E402
from PySide6.QtCore import QTimer, Qt  # noqa: E402

import moss_firered_pipeline  # noqa: E402
import subtitle_core  # noqa: E402
import twobyteasr.ui as ui  # noqa: E402
from twobyteasr.model_workshop import ModelPickerPanel, ModelWorkshopPage  # noqa: E402

OUT_DIR = ROOT / "screenshots" / "ui_fixes"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZES = [(1366, 768), (1600, 900)]


def _temp_media() -> str:
    folder = Path(tempfile.mkdtemp(prefix="2b_fixcap_"))
    path = folder / "cap_media.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 8000)
    return str(path)


def _grab(widget, name: str) -> str:
    for w, h in SIZES:
        widget.resize(w, h)
        QApplication.processEvents()
    p = OUT_DIR / f"{name}.png"
    ok = widget.grab().save(str(p), "PNG")
    print(f"CAPTURE {p.name}: {'OK' if ok else 'FAIL'}")
    return str(p)


def _grab_at(widget, name: str, width: int, height: int) -> str:
    widget.resize(width, height)
    QApplication.processEvents()
    p = OUT_DIR / f"{name}.png"
    ok = widget.grab().save(str(p), "PNG")
    print(f"CAPTURE {p.name}: {'OK' if ok else 'FAIL'}")
    return str(p)


def main() -> int:
    ui._configure_windows_app_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("2ByteASR")
    app.setWindowIcon(ui._app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(ui.APP_QSS)
    ui._register_bundled_fonts()
    app.setFont(ui._app_font())

    media = _temp_media()
    window = ui.MainWindow([media], subtitle_core, moss_firered_pipeline, {"id": "fixcap", "checks": 0})
    window.game_box.setCurrentText("我的世界")
    window.show()
    QApplication.processEvents()

    # 1) Baseline main (no modal)
    _grab(window, "01_main_baseline")
    _grab_at(window, "01_main_compact_1366x768", 1366, 768)
    _grab_at(window, "01_main_large_1920x1080", 1920, 1080)

    # 2) Term Library via ModalHost (classic layout + sidebar + right card + full cats)
    try:
        host = window._modal_host
        dlg = ui.TermLibraryDialog(window, host.body)
        if dlg.parent() is not host.body:
            dlg.setParent(host.body)
        host.show_content(dlg, title="术语库", size=(980, 640), min_size=(820, 520))
        QApplication.processEvents()
        # Let any deferred refresh settle
        QTimer.singleShot(50, lambda: None)
        QApplication.processEvents()
        _grab(window, "02_term_library")
        # Close via host (tests correct lifecycle)
        host._request_close()
        QApplication.processEvents()
    except Exception as e:
        print("TERM LIB CAPTURE ERR:", e)

    # 3) Model Picker via ModalHost (no black gaps; ★ rec visible)
    try:
        host = window._modal_host
        panel = ModelPickerPanel(window.workshop_page, "primary", host.body)
        panel.close_requested.connect(host._request_close)
        if panel.parent() is not host.body:
            panel.setParent(host.body)
        host.show_content(panel, title="选择模型 · 主力转写", size=(920, 620), min_size=(780, 520))
        QApplication.processEvents()
        _grab(window, "03_model_picker")
        host._request_close()
        QApplication.processEvents()
    except Exception as e:
        print("PICKER CAPTURE ERR:", e)

    # 4) Workshop page itself (detail width stability visible in layout)
    try:
        # Navigate to workshop page if possible
        if hasattr(window, "pages"):
            # Find workshop index
            for i in range(window.pages.count()):
                w = window.pages.widget(i)
                if isinstance(w, ModelWorkshopPage):
                    window.pages.setCurrentIndex(i)
                    break
        QApplication.processEvents()
        _grab(window, "04_workshop_page")
    except Exception as e:
        print("WORKSHOP CAPTURE ERR:", e)

    # 5) Technical Info via ModalHost (first screen order + no yellow lines + benchmark + wrap)
    try:
        host = window._modal_host
        from twobyteasr.model_workshop import ModelTechnicalDialog
        cards = getattr(window.workshop_page, "_cards", {})
        for index, key in enumerate(("moss", "firered", "qwen_local"), start=1):
            model = cards[key].model
            content = ModelTechnicalDialog(model, host.body)
            host.show_content(content, title=f"{model.name} · 技术说明", size=(720, 620), min_size=(600, 480))
            QApplication.processEvents()
            _grab(window, f"05_{index}_technical_{key}")
            scroll = content.findChild(QScrollArea, "technicalDetailsScroll")
            if scroll is not None:
                bar = scroll.verticalScrollBar()
                bar.setValue(max(1, int(bar.maximum() * 0.38)))
                QApplication.processEvents()
                _grab(window, f"05_{index}_technical_{key}_benchmark")
            host._request_close()
            QApplication.processEvents()
    except Exception as e:
        print("TECH CAPTURE ERR:", e)

    # 6) Modal dim proof: open Term again and grab while backdrop is up (main should look dimmer)
    try:
        host = window._modal_host
        dlg = ui.TermLibraryDialog(window, host.body)
        if dlg.parent() is not host.body:
            dlg.setParent(host.body)
        host.show_content(dlg, title="术语库（验证暗化）", size=(980, 640), min_size=(820, 520))
        # Allow backdrop fade to target
        for _ in range(6):
            QApplication.processEvents()
            # small sleep not available; process more
        _grab(window, "06_modal_dim_proof")
        host._request_close()
        QApplication.processEvents()
    except Exception as e:
        print("DIM PROOF CAPTURE ERR:", e)

    print("All captures attempted. See:", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
