import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.studio_commands import BatchTimingCommand, set_cues_timing_offset_command
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.timeline.studio_timing import CueSelectionModel, loop_region, recommend_many, snap_candidates
from twobyteasr.studio.studio_ui import WaveformTimeline
from twobyteasr.studio.studio_helpers import format_timeline_timecode, parse_timeline_timecode


def _project():
    return SubtitleProject(
        media=StudioMedia("video.mp4", duration_ms=10_000),
        cues=[
            StudioCue("a", 1_000, 2_000, "你好", speaker_id="S01", evidence_refs=["e1"]),
            StudioCue("b", 2_200, 3_000, "世界", speaker_id="S01"),
        ],
        asr_evidence={"e1": {"word_timestamps": [{"start": 1.05, "end": 1.3}, {"start": 1.4, "end": 1.85}], "speech_regions": [{"start": 1.02, "end": 1.9}]}},
    )


def test_smart_alignment_uses_words_and_vad_with_guardrails():
    report = recommend_many(_project(), ["a"])
    item = report.recommendations[0]
    assert item.recommended_start == 1050
    assert item.recommended_end == 1850
    assert item.confidence > 0.8


def test_alignment_skips_missing_evidence_and_loop_clamps_media():
    project = _project()
    assert recommend_many(project, ["b"]).skipped == ["b"]
    assert loop_region(project.cues[0], pre_roll_ms=500, post_roll_ms=500, duration_ms=2_100) == (500, 2100)


def test_batch_timing_offset_is_one_undo_step_and_respects_bounds():
    project = _project()
    stack = QUndoStack()
    stack.push(set_cues_timing_offset_command(project, ["a", "b"], 100))
    assert [(cue.start_ms, cue.end_ms) for cue in project.cues] == [(1100, 2100), (2300, 3100)]
    assert stack.count() == 1
    stack.undo()
    assert project.cues[0].start_ms == 1000


def test_selection_model_distinguishes_active_and_multi_selected():
    model = CueSelectionModel()
    assert model.click("a", ordered_ids=["a", "b", "c"]) == ["a"]
    assert set(model.click("c", ctrl=True, ordered_ids=["a", "b", "c"])) == {"a", "c"}
    assert model.click("b", shift=True, ordered_ids=["a", "b", "c"]) == ["b", "c"]


def test_snap_candidates_report_semantic_source():
    project = _project()
    candidates = snap_candidates(project, project.cues[0], 1055, edge="start", threshold_ms=20)
    assert candidates and candidates[0][1] == "首字/末字时间"


def test_transport_timecode_round_trip_supports_hours_and_minutes_only():
    assert format_timeline_timecode(3_723_004) == "01:02:03.004"
    assert parse_timeline_timecode("01:02:03.004") == 3_723_004
    assert parse_timeline_timecode("02:03.004") == 123_004
    assert parse_timeline_timecode("01:60.000") is None


def test_timeline_scrub_emits_seek_and_snap_can_be_disabled():
    app = QApplication.instance() or QApplication([])
    timeline = WaveformTimeline()
    timeline.resize(900, 300)
    timeline.set_project(_project())
    timeline.show()
    app.processEvents()
    seeks = []
    timeline.seek_requested.connect(seeks.append)
    x = round(timeline._time_to_x(5_000))
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, 10))
    QTest.mouseMove(timeline, QPoint(x + 20, 10), 10)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x + 20, 10))
    assert seeks and seeks[-1] > 5.0
    assert timeline._snap_time(1_990, "b") == 2_000
    timeline.set_snap_enabled(False)
    assert timeline._snap_time(1_990, "b") == 1_990
    timeline.deleteLater()


def test_timeline_marquee_selects_visible_cues_in_both_directions():
    app = QApplication.instance() or QApplication([])
    project = _project()
    timeline = WaveformTimeline()
    timeline.resize(900, 300)
    timeline.set_project(project)
    timeline.show()
    app.processEvents()
    selected = []
    timeline.selection_changed.connect(lambda ids: selected.append(set(ids)))
    left = timeline._time_to_x(900)
    right = timeline._time_to_x(3100)
    y = timeline.RULER_HEIGHT + 20
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(left), y))
    timeline.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(right, y), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(right), y))
    assert selected and selected[-1] == {"a", "b"}
    selected.clear()
    far_right = timeline._time_to_x(3400)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(far_right), y))
    timeline.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(left, y), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(left), y))
    assert selected and selected[-1] == {"a", "b"}
    timeline.deleteLater()
