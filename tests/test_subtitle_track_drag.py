# -*- coding: utf-8 -*-
"""Subtitle tracks dragged to another place, and selected lines moved between tracks together
(2026-11-20)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.timeline.subtitle_track_drag import reordered, shifted_speakers
from twobyteasr.timeline.timeline_cue_gesture import CueInterval, preview_intervals


def _app():
    return QApplication.instance() or QApplication([])


def test_a_track_takes_the_place_it_is_dropped_on():
    order = ['A', 'B', 'C', 'D']
    assert reordered(order, 'A', 'C') == ['B', 'C', 'A', 'D']
    assert reordered(order, 'D', 'B') == ['A', 'D', 'B', 'C']
    assert reordered(order, 'B', 'B') == order and reordered(order, 'X', 'B') == order


def test_selected_lines_move_by_the_same_rows_or_not_at_all():
    rows = ['A', 'B', 'C']
    assert shifted_speakers({'1': 'A', '2': 'A'}, rows, 'A', 'C') == {'1': 'C', '2': 'C'}
    # Lines on two tracks keep their distance.
    assert shifted_speakers({'1': 'A', '2': 'B'}, rows, 'A', 'B') == {'1': 'B', '2': 'C'}
    # One of them would leave the rows, or land on a locked track: nothing moves.
    assert shifted_speakers({'1': 'B', '2': 'C'}, rows, 'B', 'C') == {}
    assert shifted_speakers({'1': 'A'}, rows, 'A', 'B', locked={'B'}) == {}
    # A line on a row that is not its own (collapsed group) blocks the move.
    assert shifted_speakers({'1': 'G1'}, rows, 'A', 'B') == {}


def test_a_dragged_multi_selection_changes_tracks_together():
    originals = {'1': CueInterval(0, 1000, 'A'), '2': CueInterval(2000, 3000, 'B')}
    moved = preview_intervals(originals, '1', 'move', 500, target_speaker='B', speaker_rows=['A', 'B', 'C'])
    assert moved == {'1': CueInterval(500, 1500, 'B'), '2': CueInterval(2500, 3500, 'C')}
    # Without the rows (old callers) several lines keep their tracks, as before.
    kept = preview_intervals(originals, '1', 'move', 500, target_speaker='B')
    assert kept['1'].speaker_id == 'A' and kept['2'].speaker_id == 'B'


def _timeline():
    from twobyteasr.studio.studio_ui import WaveformTimeline
    timeline = WaveformTimeline()
    timeline.resize(1200, 620)
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=8000),
        cues=[StudioCue("a1", 0, 1200, "一", speaker_id="SA"), StudioCue("a2", 2000, 3000, "二", speaker_id="SA"),
              StudioCue("b1", 3500, 4500, "三", speaker_id="SB"), StudioCue("c1", 5000, 6000, "四", speaker_id="SC")],
        speakers=[StudioSpeaker(id="SA", name="甲"), StudioSpeaker(id="SB", name="乙"), StudioSpeaker(id="SC", name="丙")],
    )
    project.studio_state['speaker_track_order'] = ['SA', 'SB', 'SC']
    timeline.set_project(project)
    timeline.set_visible_window(0, 8000)
    timeline.show()
    _app().processEvents()
    return timeline, project


def test_dragging_a_subtitle_track_header_asks_for_its_new_place():
    app = _app()
    timeline, _project = _timeline()
    try:
        rows = timeline._track_layout()[0]
        top, bottom = timeline._speaker_rows()[0], timeline._speaker_rows()[-1]
        start = QPoint(30, round(rows[top].center().y()))
        end = QPoint(30, round(rows[bottom].center().y()))
        asked = []
        timeline.speaker_track_reorder_requested.connect(lambda s, t: asked.append((s, t)))
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(timeline, QPoint(30, start.y() + 12))
        QTest.mouseMove(timeline, end)
        assert timeline._speaker_reorder_drag['target_speaker_id'] == bottom
        timeline.grab()                                   # the drop feedback paints
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, end)
        assert asked == [(top, bottom)] and timeline._speaker_reorder_drag is None
        # A click without moving only selects the header.
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, start)
        assert len(asked) == 1 and timeline.selected_track_header == ('subtitle', top)
    finally:
        timeline.close()
        timeline.deleteLater()
        app.processEvents()


def test_selected_lines_dragged_down_land_on_the_track_below_in_one_edit():
    from twobyteasr.timeline.studio_selection import ClipSelection
    app = _app()
    timeline, project = _timeline()
    try:
        rows = timeline._track_layout()[0]
        order = timeline._speaker_rows()
        source = timeline._timeline_cue_by_id['a1'].speaker_id
        below = order[order.index(source) + 1] if order.index(source) + 1 < len(order) else order[order.index(source) - 1]
        timeline._publish_clip_selection(ClipSelection(cue_ids={'a1', 'a2'}))
        app.processEvents()
        start = QPoint(round(timeline._time_to_x(600)), round(rows[source].center().y()))
        end = QPoint(start.x() + 40, round(rows[below].center().y()))
        committed, moved_groups = [], []
        timeline.timing_edit_committed.connect(committed.append)
        timeline.group_move_committed.connect(lambda *a: moved_groups.append(a))
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(timeline, QPoint(start.x() + 10, start.y() + 10))
        QTest.mouseMove(timeline, end)
        assert timeline._group_drag['speakers'] == {'a1': below, 'a2': below}
        timeline.grab()                                   # lines drawn on the rows they will land on
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, end)
        assert not moved_groups and len(committed) == 1
        values = committed[0]
        assert set(values) == {'a1', 'a2'} and {v.speaker_id for v in values.values()} == {below}
        assert values['a2'].start_ms - values['a1'].start_ms == 2000          # spacing kept
    finally:
        timeline.close()
        timeline.deleteLater()
        app.processEvents()


def test_the_reorder_command_is_one_undo_step(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtGui import QUndoStack
    from twobyteasr.timeline.subtitle_track_drag import reorder_subtitle_track
    app = _app()
    timeline, project = _timeline()
    try:
        page = SimpleNamespace(project=project, timeline=timeline, undo_stack=QUndoStack())
        assert reorder_subtitle_track(page, 'SA', 'SC')
        assert project.studio_state['speaker_track_order'] == ['SB', 'SC', 'SA']
        assert timeline.speaker_ids() == ['SB', 'SC', 'SA']
        page.undo_stack.undo()
        assert project.studio_state['speaker_track_order'] == ['SA', 'SB', 'SC']
        assert timeline.speaker_ids() == ['SA', 'SB', 'SC']
        assert not reorder_subtitle_track(page, 'SA', 'SA')
    finally:
        timeline.close()
        timeline.deleteLater()
        app.processEvents()
