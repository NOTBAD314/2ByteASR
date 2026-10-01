"""Focused P23.1 timing measurements on the retained 10k Studio fixture."""
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

from PySide6.QtWidgets import QApplication
from twobyteasr.studio_commands import set_cues_timing_offset_command
from twobyteasr.studio_project import load_project
from twobyteasr.studio_timing import recommend_many
from twobyteasr.studio_ui import CueTableModel, WaveformTimeline


def measure(action, count=7):
    values = []
    for _ in range(count):
        started = time.perf_counter()
        action()
        values.append((time.perf_counter() - started) * 1000)
    ordered = sorted(values)
    return {"mean_ms": round(statistics.fmean(values), 3), "p95_ms": round(ordered[min(len(ordered) - 1, round((len(ordered) - 1) * .95))], 3)}


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    source = ROOT / "tmp" / "p22.9-real-workflow" / "combined-10000.2byteproj"
    started = time.perf_counter()
    project = load_project(source)
    load_ms = (time.perf_counter() - started) * 1000
    timeline = WaveformTimeline()
    timeline.resize(1400, 360)
    started = time.perf_counter()
    timeline.set_project(project)
    app.processEvents()
    initial_ms = (time.perf_counter() - started) * 1000
    model = CueTableModel(project)
    thousand = [cue.id for cue in project.cues[4000:5000]]
    report = {
        "fixture": str(source),
        "cue_count": len(project.cues),
        "project_load_ms": round(load_ms, 3),
        "timeline_initial_ms": round(initial_ms, 3),
        "visible_query": measure(lambda: timeline.visible_cues(), 25),
        "zoom": measure(lambda: timeline.set_visible_window(8_000_000, 30_000), 12),
        "select_row": measure(lambda: model.row_for_cue_id("cue-7500"), 100),
        "range_1000": measure(lambda: set(thousand), 20),
        "marquee_1000_candidate_query": measure(lambda: timeline._cues_intersecting(project.cues[4000].start_ms - 1, project.cues[4999].end_ms + 1), 20),
        "batch_timing_1000": measure(lambda: set_cues_timing_offset_command(project, thousand, 50), 5),
        "smart_align_100": measure(lambda: recommend_many(project, [cue.id for cue in project.cues[:100]]), 5),
    }
    output = ROOT / "screenshots" / "p23.1" / "performance-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    timeline.deleteLater()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
