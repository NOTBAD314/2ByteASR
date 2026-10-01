"""Real Qt/mpv acceptance for P23 selection, batch editing, and loop behavior."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "screenshots" / "p23.1"
os.environ["LOCALAPPDATA"] = str(ROOT / "tmp" / f"p23.1-interactions-{os.getpid()}")
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_commands import AssignSpeakerCommand, set_cues_timing_offset_command
from twobyteasr.studio_project import load_project
from twobyteasr.studio_timing import recommend_many
from twobyteasr.studio_ui import SubtitleStudioPage


def pump(app, ms=0):
    deadline = time.perf_counter() + ms / 1000
    while True:
        app.processEvents()
        if time.perf_counter() >= deadline:
            return
        time.sleep(.005)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    project_path = ROOT / "tmp" / "p22.10-acceptance" / "real-242-copy.2byteproj"
    page = SubtitleStudioPage()
    page.resize(1920, 1080)
    page.show()
    page.open_project(project_path)
    pump(app, 1200)
    if page.video.controller is None:
        raise RuntimeError(page.video.toolTip())

    first = page.project.cues[0]
    page.timeline.set_visible_window(0, 10_000)
    pump(app, 80)
    timeline_selections = []
    page.timeline.selection_changed.connect(lambda ids: timeline_selections.append(set(ids)))
    y = page.timeline.RULER_HEIGHT + 20
    start = QPoint(round(page.timeline._time_to_x(0)), y)
    end = QPoint(round(page.timeline._time_to_x(3_200)), y)
    QTest.mousePress(page.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    page.timeline.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(end), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(page.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    pump(app, 50)
    marquee_ids = sorted(timeline_selections[-1]) if timeline_selections else []
    marquee_list_sync_count = len(page.selected_cue_ids())
    reverse_selections = []
    page.timeline.selection_changed.connect(lambda ids: reverse_selections.append(set(ids)))
    reverse_start = QPoint(round(page.timeline._time_to_x(3_200)), y)
    reverse_end = QPoint(round(page.timeline._time_to_x(0)), y)
    QTest.mousePress(page.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, reverse_start)
    page.timeline.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(reverse_end), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(page.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, reverse_end)
    pump(app, 50)

    selected_ids = [cue.id for cue in page.project.cues[:4]]
    mixed_style = copy.deepcopy(page.project.styles[0])
    mixed_style.id = "mixed-p23"
    mixed_style.font_size = mixed_style.font_size + 7
    page.project.styles.append(mixed_style)
    page.project.cues[1].style_id = mixed_style.id
    page._timeline_selection_changed(set(selected_ids))
    page.style_scope.setCurrentIndex(page.style_scope.findData("selected"))
    page._load_style_inspector()
    mixed_style_before = page.style_font_size.lineEdit().text()
    before_timing = [(page._cue_lookup[item].start_ms, page._cue_lookup[item].end_ms) for item in selected_ids]
    page.undo_stack.push(set_cues_timing_offset_command(page.project, selected_ids, 50, changed=page._changed))
    timing_shifted = all(page._cue_lookup[item].start_ms == before[0] + 50 for item, before in zip(selected_ids, before_timing))
    page.undo_stack.undo()
    timing_undo = all((page._cue_lookup[item].start_ms, page._cue_lookup[item].end_ms) == before for item, before in zip(selected_ids, before_timing))

    speaker_targets = [speaker.id for speaker in page.project.speakers]
    target = next((item for item in speaker_targets if item != page._cue_lookup[selected_ids[0]].speaker_id), speaker_targets[0])
    old_speakers = [page._cue_lookup[item].speaker_id for item in selected_ids]
    page.undo_stack.push(AssignSpeakerCommand(page.project, selected_ids, target, changed=page._changed))
    speaker_batch = all(page._cue_lookup[item].speaker_id == target for item in selected_ids)
    page.undo_stack.undo()
    speaker_undo = [page._cue_lookup[item].speaker_id for item in selected_ids] == old_speakers

    page.select_cue(first.id)
    page._toggle_loop_current()
    initial_region = page._loop_region_ms
    page._position_changed(initial_region[1] / 1000 + .01)
    pump(app, 80)
    loop_time = float(page.video.controller.get_property("time-pos", -1) or -1)
    page._push_timing(first.id, first.start_ms + 30, first.end_ms + 50)
    pump(app, 50)
    updated_region = page._loop_region_ms
    page._toggle_loop_current()

    snap_values = []
    for _ in range(100):
        started = time.perf_counter()
        page.timeline._snap_time(page.project.cues[1].start_ms + 5, page.project.cues[0].id)
        snap_values.append((time.perf_counter() - started) * 1000)
    snap_values.sort()

    alignment = recommend_many(page.project, [cue.id for cue in page.project.cues[:10]])
    report = {
        "cue_count": len(page.project.cues),
        "mpv": {name: page.video.controller.get_property(name) for name in ("width", "height", "video-format", "sid")},
        "marquee": {"left_to_right": marquee_ids, "right_to_left": sorted(reverse_selections[-1]) if reverse_selections else [], "selected_count": len(marquee_ids), "list_sync_count": marquee_list_sync_count},
        "style_selection": {"selected_count": len(selected_ids), "font_size_display_before_edit": mixed_style_before, "scope": page.style_scope.currentData()},
        "batch": {"timing_shifted": timing_shifted, "timing_undo": timing_undo, "speaker_changed": speaker_batch, "speaker_undo": speaker_undo},
        "loop": {"initial_region": initial_region, "looped_time_seconds": loop_time, "updated_region": updated_region, "disabled": not page._loop_enabled},
        "snap": {"source_exercised": "neighbor boundary", "mouse_path_p95_ms": round(snap_values[round((len(snap_values)-1)*.95)], 4)},
        "smart_align": {"checked": 10, "recommended": len(alignment.recommendations), "skipped": len(alignment.skipped)},
    }
    (OUTPUT / "interaction-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    page.close_page()
    page.close()
    app.quit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
