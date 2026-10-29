# -*- coding: utf-8 -*-
"""Razor / merge tool interaction, ripple-merge shortcuts, and the responsive
edit pipeline (splice commands + incremental QC) introduced 2026-09-03."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    save_project,
)
from twobyteasr.timeline.studio_commands import (
    add_cue_command,
    delete_cues_command,
    merge_cues_command,
    split_cue_command,
)
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.studio_ui import SubtitleStudioPage, WaveformTimeline
from twobyteasr.studio.studio_shortcuts import STUDIO_COMMANDS
from twobyteasr.timeline.studio_timing import resolve_split


def _app():
    return QApplication.instance() or QApplication([])


def _mouse(widget, kind, x, y, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        kind,
        QPointF(x, y),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    if kind == QMouseEvent.Type.MouseButtonPress:
        widget.mousePressEvent(event)
    elif kind == QMouseEvent.Type.MouseButtonRelease:
        widget.mouseReleaseEvent(event)
    else:
        widget.mouseMoveEvent(event)


def _timeline_with_project():
    timeline = WaveformTimeline()
    timeline.resize(1200, 560)
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=6000),
        cues=[
            StudioCue("a", 0, 1200, "我今天好想要吃肯", speaker_id="S01"),
            StudioCue("b", 1500, 3000, "德基麦当劳", speaker_id="S01"),
            StudioCue("c", 3200, 4600, "再来一句", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    timeline.set_project(project)
    timeline.set_visible_window(0, 6000)
    return timeline, project


def _cue_point(timeline, cue, fraction=0.5):
    track = timeline._track_layout()[0][cue.speaker_id]
    x = timeline._time_to_x(cue.start_ms + (cue.end_ms - cue.start_ms) * fraction)
    return x, track.center().y()


# ---------------------------------------------------------------------------
# resolve_split parity
# ---------------------------------------------------------------------------

def test_resolve_split_clamps_and_splits_by_ratio():
    cue = StudioCue("x", 1000, 3000, "九字字幕内容一二三")
    preview = resolve_split(cue, 2000)
    assert preview is not None
    assert preview.left_text + preview.right_text == cue.text
    assert preview.split_ms == 2000
    # Old controller math: ratio 0.5 over 9 chars rounds to position 4/5.
    ratio = (2000 - 1000) / 2000
    position = min(len(cue.text) - 1, max(1, round(len(cue.text) * ratio)))
    assert preview.left_text == cue.text[:position]

    clamped = resolve_split(cue, 2999)
    assert clamped.split_ms == 3000 - 50
    assert resolve_split(cue, 0).split_ms == 1000 + 50
    assert resolve_split(StudioCue("y", 0, 1000, "短"), 500) is None


def test_controller_split_uses_same_resolution_as_preview(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=6000),
        cues=[
            StudioCue("a", 0, 2400, "九字字幕一二三四五六七", speaker_id="S01"),
            StudioCue("b", 2600, 4000, "第二句", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio.2byteproj"))
    app.processEvents()

    cue = page.project.cues[0]
    raw_ms = cue.start_ms + int((cue.end_ms - cue.start_ms) * 0.55)
    preview = resolve_split(cue, raw_ms)
    assert preview is not None
    page.cue_controller.split_at(cue.id, raw_ms)
    app.processEvents()
    by_text = {item.text: item for item in page.project.cues}
    assert preview.left_text in by_text
    assert preview.right_text in by_text
    assert by_text[preview.left_text].end_ms == preview.split_ms
    assert by_text[preview.right_text].start_ms == preview.split_ms
    page.close_page()
    page.deleteLater()


# ---------------------------------------------------------------------------
# Razor drag interaction
# ---------------------------------------------------------------------------

def test_razor_press_slide_release_commits_split_at_release_position():
    app = _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))

    cue = project.cues[0]
    x, y = _cue_point(timeline, cue, 0.3)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    assert emitted == []  # press alone must not cut yet

    x2, _ = _cue_point(timeline, cue, 0.7)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x2, y)
    assert timeline._razor_drag is not None
    assert int(timeline._razor_drag["split_ms"]) == timeline._x_to_time(x2)

    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x2, y)
    assert timeline._razor_drag is None
    assert len(emitted) == 1
    cue_id, ms = emitted[0]
    assert cue_id == cue.id
    assert abs(ms - timeline._x_to_time(x2)) <= 30  # snapping tolerance


def test_razor_click_without_drag_splits_at_press_position():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    cue = project.cues[1]
    x, y = _cue_point(timeline, cue, 0.4)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x, y)
    assert len(emitted) == 1
    assert abs(emitted[0][1] - timeline._x_to_time(x)) <= 30


def test_razor_release_commits_exactly_the_previewed_split():
    """The preview is the single commit source: emitted ms must equal the
    split the preview card last showed, including after snapping."""
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    timeline.set_playhead(1905)  # a snap candidate right next to the drag
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    cue = project.cues[0]
    x, y = _cue_point(timeline, cue, 0.475)  # ≈1900ms, inside snap threshold
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x, y)
    preview_state = timeline._razor_preview()
    assert preview_state is not None
    expected = int(preview_state[0].split_ms)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x, y)
    assert emitted == [(cue.id, expected)]


def test_razor_subdrag_move_still_commits_previewed_position():
    """Regression: sub-threshold wiggles moved the preview but the release
    used to commit the press position — off by one character vs the card."""
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    cue = project.cues[0]
    x, y = _cue_point(timeline, cue, 0.3)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x + 5, y)  # below startDragDistance
    assert timeline._razor_preview() is not None
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x + 5, y)
    assert len(emitted) == 1
    assert abs(emitted[0][1] - timeline._x_to_time(x + 5)) <= 30


def test_razor_hover_previews_without_touching_the_project():
    """Hover shows the cut (2026-10-10 redesign); it never edits or cuts."""
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    before = [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues]
    x, y = _cue_point(timeline, project.cues[0], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x, y)
    assert timeline._razor_drag is None
    preview, cue = timeline._razor_preview()
    assert cue.id == "a" and preview.left_text + preview.right_text == cue.text
    assert not preview.measured  # synthetic cue: no evidence, labelled estimate
    timeline.leaveEvent(None)
    assert timeline._razor_preview() is None
    assert emitted == []
    assert [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues] == before


def test_razor_click_commits_exactly_the_hover_preview():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    x, y = _cue_point(timeline, project.cues[1], 0.37)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x, y)
    hovered, _cue = timeline._razor_preview()
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x, y)
    assert emitted == [("b", hovered.split_ms)]


def test_razor_escape_cancels_the_pending_cut():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    x, y = _cue_point(timeline, project.cues[0], 0.4)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    from PySide6.QtGui import QKeyEvent
    timeline.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert timeline._razor_drag is None and timeline._razor_preview() is None
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x, y)
    assert emitted == []


def test_razor_never_cuts_another_speakers_overlapping_caption():
    _app()
    timeline = WaveformTimeline()
    timeline.resize(1200, 560)
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=6000),
        cues=[
            StudioCue("host", 0, 3000, "主播这一句很长", speaker_id="S01"),
            StudioCue("guest", 1000, 2500, "嘉宾插话", speaker_id="S02"),
            StudioCue("host2", 3200, 4600, "主播下一句", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播"), StudioSpeaker(id="S02", name="嘉宾")],
    )
    timeline.set_project(project)
    timeline.set_visible_window(0, 6000)
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    host_track = timeline._track_layout()[0]["S01"]
    y = host_track.center().y()
    _mouse(timeline, QMouseEvent.Type.MouseMove, timeline._time_to_x(1800), y)
    assert timeline._razor_preview()[1].id == "host"
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, timeline._time_to_x(500), y)
    # Slide through the guest's overlapping caption, then onto host2.
    _mouse(timeline, QMouseEvent.Type.MouseMove, timeline._time_to_x(1800), y, Qt.MouseButton.LeftButton)
    assert str(timeline._razor_drag["cue_id"]) == "host"
    _mouse(timeline, QMouseEvent.Type.MouseMove, timeline._time_to_x(3900), y, Qt.MouseButton.LeftButton)
    assert str(timeline._razor_drag["cue_id"]) == "host2"
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, timeline._time_to_x(3900), y)
    assert [cue_id for cue_id, _ms in emitted] == ["host2"]


def test_razor_locked_track_shows_state_and_does_not_cut():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    timeline.locked_speakers.add("S01")
    emitted, blocked = [], []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    timeline.edit_blocked.connect(blocked.append)
    x, y = _cue_point(timeline, project.cues[0], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x, y)
    assert timeline._razor_resolution().locked and timeline._razor_preview() is None
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x, y)
    assert emitted == [] and blocked


def test_razor_press_on_empty_space_anchors_nearest_and_release_anywhere_cuts():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("razor")
    emitted = []
    timeline.razor_split_requested.connect(lambda cue_id, ms: emitted.append((cue_id, ms)))
    track = timeline._track_layout()[0]["S01"]
    y = track.center().y()
    # Gap between a (0-1200) and b (1500-3000); 1300 is nearest to a.
    gap_x = timeline._time_to_x(1300)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, gap_x, y)
    assert timeline._razor_drag is not None
    assert str(timeline._razor_drag["cue_id"]) == "a"
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, gap_x, y)
    assert emitted and emitted[0][0] == "a"

    # Slide from cue a across the gap onto cue b: retarget and cut b.
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, timeline._time_to_x(600), y)
    _mouse(timeline, QMouseEvent.Type.MouseMove, timeline._time_to_x(2000), y)
    assert str(timeline._razor_drag["cue_id"]) == "b"
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, timeline._time_to_x(2000), y)
    assert emitted[-1][0] == "b"


def test_shortcut_dialog_opens_and_merge_tool_defaults_to_b(tmp_path, monkeypatch):
    app = _app()
    from twobyteasr.studio.studio_shortcuts import ShortcutSettingsDialog, STUDIO_COMMANDS

    assert STUDIO_COMMANDS["merge_tool"][1] == "B"
    dialog = ShortcutSettingsDialog({"merge_tool": "B"}, None)
    assert len(dialog.rows) == len(STUDIO_COMMANDS)
    assert dialog._editors["merge_tool"].keySequence().toString().upper() == "B"
    dialog.deleteLater()
    app.processEvents()

    # Legacy stored value "M" (old default, dialog was unopenable) migrates to B.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.projects.studio_project import studio_settings_path

    settings_file = studio_settings_path()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"shortcuts": {"merge_tool": "M"}}', encoding="utf-8")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    assert page._shortcut_values["merge_tool"] == "B"
    page.deleteLater()
    app.processEvents()


def test_razor_preview_matches_committed_split_end_to_end(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=6000),
        cues=[
            StudioCue("a", 0, 2400, "我今天好想要吃肯德基麦当劳", speaker_id="S01"),
            StudioCue("b", 2600, 4000, "第二句", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio.2byteproj"))
    app.processEvents()
    timeline = page.timeline
    timeline.set_tool_mode("razor")

    cue = project.cues[0]
    x, y = _cue_point(timeline, cue, 0.55)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x, y)
    preview = timeline._razor_preview()
    assert preview is not None
    resolved, _cue = preview
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x, y)
    app.processEvents()

    texts = [item.text for item in page.project.cues]
    assert resolved.left_text in texts
    assert resolved.right_text in texts
    assert len(page.project.cues) == 3
    page.close_page()
    page.deleteLater()


# ---------------------------------------------------------------------------
# Merge drag interaction
# ---------------------------------------------------------------------------

def test_merge_drag_right_and_left_pick_direction_neighbour():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("merge")
    emitted = []
    timeline.merge_pair_requested.connect(lambda first, second: emitted.append((first, second)))

    anchor = project.cues[1]  # b: neighbours a (prev) and c (next)
    x, y = _cue_point(timeline, anchor, 0.5)

    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    assert emitted == []  # anchor selection must never merge immediately
    assert timeline._merge_anchor_id == anchor.id

    _mouse(timeline, QMouseEvent.Type.MouseMove, x + 120, y)
    assert timeline._merge_drag["direction"] == 1
    assert timeline._merge_drag["neighbor_id"] == "c"
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x + 120, y)
    assert emitted == [(anchor.id, "c")]

    # Drag left merges with the previous cue in time order.
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, x, y)
    _mouse(timeline, QMouseEvent.Type.MouseMove, x - 120, y)
    assert timeline._merge_drag["neighbor_id"] == "a"
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, x - 120, y)
    assert emitted[-1] == (anchor.id, "a")
    timeline.deleteLater()


def test_merge_click_click_pairs_anchor_with_second_cue_only():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("merge")
    emitted = []
    timeline.merge_pair_requested.connect(lambda first, second: emitted.append((first, second)))

    # First click anchors a; second click on b pairs them.
    xa, ya = _cue_point(timeline, project.cues[0], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xa, ya)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xa, ya)
    assert emitted == []
    assert timeline._merge_anchor_id == "a"

    xb, yb = _cue_point(timeline, project.cues[1], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xb, yb)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xb, yb)
    assert emitted == [("a", "b")]
    assert timeline._merge_anchor_id == ""

    # Clicking the same cue twice clears the anchor instead of merging.
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xb, yb)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xb, yb)
    assert timeline._merge_anchor_id == "b"
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xb, yb)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xb, yb)
    assert emitted == [("a", "b")]
    assert timeline._merge_anchor_id == ""
    timeline.deleteLater()


def test_merge_never_absorbs_preexisting_selection(tmp_path, monkeypatch):
    """Regression: merge tool used the pre-click selection as merge partner."""
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=6000),
        cues=[
            StudioCue("a", 0, 1200, "第一句", speaker_id="S01"),
            StudioCue("b", 1500, 3000, "第二句", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio.2byteproj"))
    app.processEvents()
    page.select_cue("a")  # old selection lives far from the click target
    timeline = page.timeline
    timeline.set_tool_mode("merge")

    emitted = []
    timeline.merge_pair_requested.connect(lambda first, second: emitted.append((first, second)))
    track = timeline._track_layout()[0]["S01"]
    xb = timeline._time_to_x(2200)
    yb = track.center().y()
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xb, yb)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xb, yb)
    app.processEvents()

    assert emitted == []  # single click only anchors; no accidental merge with "a"
    assert len(page.project.cues) == 2
    page.close_page()
    page.deleteLater()


# ---------------------------------------------------------------------------
# Ripple merge shortcuts
# ---------------------------------------------------------------------------

def test_ripple_merge_shortcuts_registered_and_ripple_through_controller(tmp_path, monkeypatch):
    app = _app()
    assert STUDIO_COMMANDS["merge_previous"][1] == "Shift+Q"
    assert STUDIO_COMMANDS["merge_next"][1] == "Shift+W"

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=8000),
        cues=[
            StudioCue("a", 0, 1000, "一二", speaker_id="S01"),
            StudioCue("b", 1200, 2200, "三四", speaker_id="S01"),
            StudioCue("c", 2400, 3400, "五六", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio.2byteproj"))
    app.processEvents()
    assert page._shortcut_values["merge_previous"] == "Shift+Q"
    assert page._shortcut_values["merge_next"] == "Shift+W"

    page.select_cue("b")
    page.cue_controller.merge_with_neighbor(-1)
    app.processEvents()
    texts = [cue.text for cue in page.project.cues]
    assert texts == ["一二三四", "五六"]
    # Selection must land on the merged cue so repeated presses ripple.
    assert page.selected_cue_id == "a"
    page.cue_controller.merge_with_neighbor(1)
    app.processEvents()
    assert [cue.text for cue in page.project.cues] == ["一二三四五六"]

    page.undo_stack.undo()
    app.processEvents()
    assert [cue.text for cue in page.project.cues] == ["一二三四", "五六"]
    page.close_page()
    page.deleteLater()


# ---------------------------------------------------------------------------
# Splice command semantics
# ---------------------------------------------------------------------------

def _project(n=6):
    return SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=n * 2000),
        cues=[
            StudioCue(f"c{i}", i * 2000, i * 2000 + 1500, f"句{i}", speaker_id="S01")
            for i in range(n)
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )


def test_splice_split_undo_redo_roundtrip():
    _app()
    project = _project()
    state_for(project)
    from PySide6.QtGui import QUndoStack

    stack = QUndoStack()
    stack.push(split_cue_command(project, "c2", 4700, "左", "右"))
    assert len(project.cues) == 7
    assert [cue.id for cue in project.cues][:3] == ["c0", "c1", "c2"]
    assert project.cues[3].id.startswith("c2-split-")
    assert project.cues[2].end_ms == 4700
    assert project.cues[3].start_ms == 4700
    stack.undo()
    assert len(project.cues) == 6
    assert [cue.text for cue in project.cues] == [f"句{i}" for i in range(6)]
    stack.redo()
    assert len(project.cues) == 7


def test_splice_isolation_survives_subsequent_field_edits():
    _app()
    project = _project()
    state_for(project)
    from PySide6.QtGui import QUndoStack
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand

    stack = QUndoStack()
    stack.push(split_cue_command(project, "c1", 2500, "甲", "乙"))
    new_id = project.cues[2].id
    stack.push(SetCueFieldsCommand(project, new_id, {"text": "乙改"}, "edit"))
    assert project.cues[2].text == "乙改"
    stack.undo()  # field edit
    stack.undo()  # split
    assert [cue.text for cue in project.cues] == [f"句{i}" for i in range(6)]


def test_merge_non_adjacent_and_scattered_delete_fall_back_safely():
    _app()
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=10000),
        cues=[
            StudioCue("a", 0, 1000, "一", speaker_id="S01"),
            StudioCue("b", 2000, 3000, "二", speaker_id="S02"),
            StudioCue("c", 4000, 5000, "三", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="甲"), StudioSpeaker(id="S02", name="乙")],
    )
    state_for(project)
    from PySide6.QtGui import QUndoStack

    stack = QUndoStack()
    stack.push(merge_cues_command(project, ["a", "c"]))  # non-adjacent in list
    assert [cue.text for cue in project.cues] == ["一三", "二"]

    merged_id = project.cues[0].id
    other_id = project.cues[1].id
    stack.push(delete_cues_command(project, [merged_id, other_id]))
    assert project.cues == []
    stack.undo()
    stack.undo()
    assert [cue.text for cue in project.cues] == ["一", "二", "三"]


def test_add_cue_command_splices_sorted_and_undo_restores():
    _app()
    project = _project()
    state_for(project)
    from PySide6.QtGui import QUndoStack

    stack = QUndoStack()
    stack.push(add_cue_command(project, StudioCue("new", 1100, 1600, "新", speaker_id="S01")))
    assert [cue.start_ms for cue in project.cues] == [0, 1100, 2000, 4000, 6000, 8000, 10000]
    stack.undo()
    assert len(project.cues) == 6


# ---------------------------------------------------------------------------
# Incremental QC routing
# ---------------------------------------------------------------------------

def test_small_structural_edits_route_to_incremental_qc(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=6000),
        cues=[
            StudioCue("a", 0, 2400, "我今天好想要吃肯德基麦当劳", speaker_id="S01"),
            StudioCue("b", 2600, 4000, "第二句内容", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播")],
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *a, **k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *a, **k: None)
    page.open_project(save_project(project, tmp_path / "studio.2byteproj"))
    app.processEvents()
    page._refresh_review_risks(sync=True)  # seed _qc_result with a full scan
    assert hasattr(page.project, "_qc_result")
    original_analyze = page._qc_engine.analyze
    unscoped_full_scans = []

    def counting_analyze(*args, **kwargs):
        # analyze_incremental() internally calls analyze(cue_ids=window);
        # only cue_ids=None counts as a real full rescan.
        if kwargs.get("cue_ids") is None:
            unscoped_full_scans.append(1)
        return original_analyze(*args, **kwargs)

    page._qc_engine.analyze = counting_analyze

    page.cue_controller.split_at("a", 1200)
    app.processEvents()
    assert page._qc_full_scan_pending is False
    assert page._pending_qc_cue_ids  # routed incrementally

    page._flush_deferred_updates()
    assert not page._pending_qc_cue_ids
    assert unscoped_full_scans == []  # small structural edit must not rescan all cues
    new_right_id = next(cue.id for cue in page.project.cues if cue.text == "吃肯德基麦当劳")
    cache = page.project._review_risks_cache
    assert new_right_id in cache
    page.close_page()
    page.deleteLater()


# ---------------------------------------------------------------------------
# Merge preview (2026-10-10: in-track ghost instead of the card)
# ---------------------------------------------------------------------------

def test_merge_preview_states_follow_the_gesture_without_editing():
    _app()
    timeline, project = _timeline_with_project()
    timeline.set_tool_mode("merge")
    before = [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues]
    xb, yb = _cue_point(timeline, project.cues[1], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xb, yb)
    state = timeline._merge_preview_state()
    assert (state.kind, state.anchor.id, state.other) == ("anchor", "b", None)
    _mouse(timeline, QMouseEvent.Type.MouseMove, xb + 120, yb)
    state = timeline._merge_preview_state()
    assert (state.kind, state.other.id, state.direction) == ("drag", "c", 1)
    assert state.span == (1500, 4600)
    from twobyteasr.studio import timeline_merge
    line, left, right = timeline_merge.status_lines(state)
    assert (left, right) == ("德基麦当劳", "再来一句")
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xb + 120, yb)
    # Anchor, then hover another cue: the click-to-pair result is previewed.
    xa, ya = _cue_point(timeline, project.cues[0], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseButtonPress, xa, ya)
    _mouse(timeline, QMouseEvent.Type.MouseButtonRelease, xa, ya)
    xc, yc = _cue_point(timeline, project.cues[2], 0.5)
    _mouse(timeline, QMouseEvent.Type.MouseMove, xc, yc, Qt.MouseButton.NoButton)
    state = timeline._merge_preview_state()
    assert (state.kind, state.anchor.id, state.other.id) == ("pair", "a", "c")
    assert timeline.cancel_selection_gesture() is True  # Esc drops the anchor
    assert timeline._merge_preview_state() is None
    assert [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues] == before


def test_merge_neighbour_skips_another_speakers_simultaneous_caption():
    _app()
    timeline = WaveformTimeline()
    timeline.resize(1200, 560)
    project = SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=6000),
        cues=[
            StudioCue("host", 0, 1500, "主播第一句", speaker_id="S01"),
            StudioCue("guest", 1000, 2000, "嘉宾插话", speaker_id="S02"),
            StudioCue("host2", 2600, 4000, "主播第二句", speaker_id="S01"),
        ],
        speakers=[StudioSpeaker(id="S01", name="主播"), StudioSpeaker(id="S02", name="嘉宾")],
    )
    timeline.set_project(project)
    timeline.set_visible_window(0, 6000)
    timeline.set_tool_mode("merge")
    assert timeline._merge_neighbor("host", 1).id == "host2"  # overlapping guest skipped
    assert timeline._merge_neighbor("guest", -1) is None      # host overlaps it
    assert timeline._merge_neighbor("host2", -1).id == "guest"  # sequential: allowed


def test_split_text_layout_keeps_the_boundary_characters_centred():
    _app()
    from PySide6.QtGui import QFont, QFontMetrics
    from twobyteasr.studio.timeline_razor import split_text_layout, MARKER_GAP
    metrics = QFontMetrics(QFont())
    left, right, total = split_text_layout(metrics, "主播投的是对面的", "没挡眼睛的哥哥", 2000)
    assert (left, right) == ("主播投的是对面的", "没挡眼睛的哥哥")
    narrow = metrics.horizontalAdvance("对面的没挡") + MARKER_GAP + 10
    left, right, total = split_text_layout(metrics, "主播投的是对面的", "没挡眼睛的哥哥", narrow)
    assert left.endswith("的") and right.startswith("没") and total <= narrow + 2
