"""Headed Windows acceptance for P25.2.10 Review Mode UX."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "p25.2.10-review"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(OUTPUT / "local-app-data")
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from twobyteasr.studio_ui import SubtitlePositionOverlay, SubtitleStudioPage


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_p25_2_10_review.py PROJECT.2byteproj")
    project_path = Path(sys.argv[1]).resolve()
    if not project_path.is_file():
        raise FileNotFoundError(project_path)

    app = QApplication.instance() or QApplication(sys.argv)
    page = SubtitleStudioPage()
    page.resize(1600, 900)
    page.move(40, 40)
    page.show()
    page.open_project(project_path)
    pump(app, 1.5)

    cue = page.project.cues[0]
    cue.text = "太赖了"
    cue.evidence_refs = ["p25.2.10-review"]
    page.project.asr_evidence["p25.2.10-review"] = {
        "moss_text": "太赖了",
        "firered_text": "太赖了",
        "qwen_asr_text": "太烂了",
    }
    page._refresh_review_risks()
    page.select_cue(cue.id)
    page._set_review_mode(True)
    pump(app, 0.25)

    dock = page.review_summary_strip.grab()
    screenshot = OUTPUT / "review-dock.png"
    dock.save(str(screenshot))
    review_card_type = __import__(
        "twobyteasr.studio_ui", fromlist=["ReviewCandidateCard"]
    ).ReviewCandidateCard
    # QObject children may include cards waiting for deleteLater(); inspect
    # only widgets currently present and visible in the live candidate grid.
    candidate_cards = []
    for index in range(page.review_dock_candidate_layout.count()):
        item = page.review_dock_candidate_layout.itemAt(index)
        widget = item.widget() if item is not None else None
        if isinstance(widget, review_card_type) and widget.isVisible():
            candidate_cards.append(widget)

    before = cue.text
    page._dispatch_shortcut_sequence("2")
    adopted = cue.text
    page.undo_stack.undo()
    undone = cue.text
    page._dispatch_shortcut_sequence("Space")
    pump(app, 0.08)

    controller = page.video.controller
    mpv = {}
    if controller is not None:
        for name in ("idle-active", "pause", "time-pos", "video-format", "aid", "sid"):
            try:
                mpv[name] = controller.get_property(name)
            except RuntimeError as exc:
                mpv[name] = {"unavailable": str(exc)}

    report = {
        "project": str(project_path),
        "review_mode": page._review_mode,
        "summary": page.review_summary_text.text(),
        "reason": page.review_reason_label.text(),
        "queue": page.review_queue_label.text(),
        "legend": page.review_legend.text(),
        "candidate_card_count": len(candidate_cards),
        "candidate_card_text": [card.text_label.text() for card in candidate_cards],
        "candidate_card_sizes": [[card.width(), card.height()] for card in candidate_cards],
        "adoption": {"before": before, "after": adopted, "undo": undone},
        "interaction_overlay_count": len(page.findChildren(SubtitlePositionOverlay)),
        "visual_overlay_visible": page.position_overlay_visual.isVisible(),
        "mpv": mpv,
        "screenshot": str(screenshot),
    }
    report_path = OUTPUT / "acceptance-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    page.close_page()
    page.close()
    app.quit()

    passed = (
        report["review_mode"]
        and report["candidate_card_count"] == 2
        and "多模型" in report["summary"]
        and report["reason"]
        and "需要检查" in report["queue"]
        and report["adoption"]["after"] == "太烂了"
        and report["adoption"]["undo"] == "太赖了"
        and report["interaction_overlay_count"] == 1
        and report["visual_overlay_visible"]
        and mpv.get("video-format")
        and mpv.get("sid") not in {None, False, "no"}
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
