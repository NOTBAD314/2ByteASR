"""Capture the P23.1 Style Inspector and run focused real-project checks."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("LOCALAPPDATA", str(ROOT / "tmp" / "p23.1-localappdata"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import load_project
from twobyteasr.studio_timing import recommend_many
from twobyteasr.studio_ui import SubtitleStudioPage


def pump(app, rounds=3):
    for _ in range(rounds):
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.video.load = lambda *_args, **_kwargs: None
    page._generate_waveform = lambda *_args, **_kwargs: None
    project_path = ROOT / "tmp" / "p22.10-acceptance" / "real-242-copy.2byteproj"
    page.resize(1920, 1080)
    page.open_project(project_path)
    page.show()
    page.context_drawer.setCurrentIndex(2)
    pump(app, 6)
    output = ROOT / "screenshots" / "p23.1"
    output.mkdir(parents=True, exist_ok=True)
    full = output / "style-panel-1920x1080.png"
    panel = output / "style-panel-preview.png"
    page.grab().save(str(full))
    page.context_panel.grab().save(str(panel))

    selected_ids = [cue.id for cue in page.project.cues[:4]]
    page._timeline_selection_changed(set(selected_ids))
    page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
    page.style_font_size.setValue(100)
    pump(app, 5)
    mixed = page.style_font_size.lineEdit().text()

    before = page.style_font.showPopup
    started = time.perf_counter()
    before()
    popup_ms = (time.perf_counter() - started) * 1000
    page.style_font.hidePopup()

    report = {
        "project": str(project_path),
        "cue_count": len(page.project.cues),
        "style_panel": {
            "full_screenshot": str(full),
            "preview_screenshot": str(panel),
            "preview_height": page.style_preview.height(),
            "preview_style": {
                "font": getattr(getattr(page.style_preview, "_style", None), "font_family", ""),
                "size": getattr(getattr(page.style_preview, "_style", None), "font_size", None),
                "fill": getattr(getattr(page.style_preview, "_style", None), "primary_color", ""),
            },
            "scope_options": [page.style_scope._buttons[i].text() for i in range(len(page.style_scope._buttons))],
            "font_size_after_selected_edit": mixed,
            "color_controls": all(getattr(page, name, None) is not None for name in ("style_fill_button", "style_outline_button", "style_back_button")),
        },
        "font_popup": {"first_open_ms": round(popup_ms, 3), "lazy_before_full_load": not page.style_font._fonts_loaded},
        "smart_align": {
            "evidence_refs": sum(bool(cue.evidence_refs) for cue in page.project.cues[:10]),
            "recommendations": len(recommend_many(page.project, [cue.id for cue in page.project.cues[:10]]).recommendations),
            "rows": [],
        },
    }
    alignment = recommend_many(page.project, [cue.id for cue in page.project.cues[:10]])
    by_id = {item.cue_id: item for item in alignment.recommendations}
    for cue in page.project.cues[:10]:
        item = by_id.get(cue.id)
        report["smart_align"]["rows"].append({
            "cue": cue.id,
            "before_start": cue.start_ms,
            "before_end": cue.end_ms,
            "recommended_start": item.recommended_start if item else None,
            "recommended_end": item.recommended_end if item else None,
            "applied": False,
            "evidence": list(item.evidence) if item else ["insufficient word/VAD timing"],
            "confidence": item.confidence if item else 0.0,
            "reason": (item.start_reason or item.end_reason) if item else "skip: scalar segment evidence is not enough for boundary repair",
        })
    (output / "acceptance-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    page.close_page()
    app.quit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
