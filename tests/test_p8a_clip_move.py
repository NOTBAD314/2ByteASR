"""P8A VideoClip move/trim via production timeline actions."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.studio_media_commands import media_graph_command
from twobyteasr.timeline.studio_media_pool import (
    active_video_clips,
    add_media_asset,
    add_video_clip,
    create_video_track,
    move_video_clip,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import DirtyDomain, state_for
from twobyteasr.studio.studio_ui import SubtitleStudioPage, WaveformTimeline


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> SubtitleProject:
    primary = tmp_path / "v1.mp4"
    second = tmp_path / "v2.mp4"
    primary.write_bytes(b"v1")
    second.write_bytes(b"v2")
    project = SubtitleProject(
        media=StudioMedia(path=str(primary), duration_ms=120_000, width=1920, height=1080),
        cues=[StudioCue("c1", 0, 1_000, "cue")],
    )
    project.validate()
    project.video_tracks[0].locked = False
    asset = add_media_asset(project, second, fingerprint="v2", duration_ms=180_000)
    v2 = create_video_track(project, "V2")
    add_video_clip(project, v2.id, asset.asset_id, timeline_in_ms=9_000)
    project.validate()
    return project


def test_move_video_clip_command_is_not_locked_to_import_playhead(tmp_path):
    _app()
    project = _project(tmp_path)
    v2 = project.video_tracks[1]
    clip = v2.clips[0]
    assert clip.timeline_in_ms == 9_000
    source_in = clip.source_in_ms
    source_out = clip.source_out_ms
    page = SubtitleStudioPage()
    page.project = project
    page._video_clip_move_committed(v2.id, clip.id, 3_000)
    moved = project.video_tracks[1].clips[0]
    assert moved.timeline_in_ms == 3_000
    assert moved.timeline_out_ms == 3_000 + (source_out - source_in)
    assert moved.source_in_ms == source_in
    assert moved.source_out_ms == source_out
    linked = next(
        audio_clip
        for track in project.audio_tracks
        for audio_clip in track.clips
        if audio_clip.linked_video_clip_id == moved.id
    )
    assert linked.timeline_in_ms == 3_000
    page.undo_stack.undo()
    assert project.video_tracks[1].clips[0].timeline_in_ms == 9_000
    page.undo_stack.redo()
    assert project.video_tracks[1].clips[0].timeline_in_ms == 3_000
    page.close_page()
    page.deleteLater()


def test_timeline_drag_emits_move_command(tmp_path):
    app = _app()
    project = _project(tmp_path)
    timeline = WaveformTimeline()
    timeline.set_project(project)
    timeline.resize(1400, 420)
    timeline.set_visible_window(0, 30_000)
    timeline.show()
    app.processEvents()
    v2 = project.video_tracks[1]
    clip = v2.clips[0]
    received: list[tuple[str, str, int]] = []
    timeline.video_clip_move_committed.connect(
        lambda track_id, clip_id, start: received.append((track_id, clip_id, start))
    )
    start_x = int(timeline._time_to_x(clip.timeline_in_ms + 1_000))
    end_x = int(timeline._time_to_x(4_000))
    rects = timeline._video_track_rects()
    assert v2.id in rects
    y = int(rects[v2.id].center().y())

    def mouse(kind: QEvent.Type, x: int, buttons: Qt.MouseButton) -> QMouseEvent:
        local = QPointF(x, y)
        return QMouseEvent(
            kind,
            local,
            local,
            timeline.mapToGlobal(QPoint(x, y)),
            Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    timeline.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, start_x, Qt.MouseButton.LeftButton))
    assert timeline._clip_drag is not None
    timeline.mouseMoveEvent(mouse(QEvent.Type.MouseMove, end_x, Qt.MouseButton.LeftButton))
    assert timeline._clip_drag["moved"] is True
    timeline.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, end_x, Qt.MouseButton.NoButton))
    app.processEvents()
    assert received, f"drag did not commit; drag={timeline._clip_drag} rects={rects}"
    assert received[0][0] == v2.id
    assert received[0][1] == clip.id
    assert received[0][2] != 9_000
    timeline.close()
    timeline.deleteLater()


def test_import_playhead_is_initial_not_permanent_anchor(tmp_path):
    project = _project(tmp_path)
    v2 = project.video_tracks[1]
    clip = v2.clips[0]
    stack = QUndoStack()
    stack.push(
        media_graph_command(
            project,
            "移动视频片段",
            lambda working: move_video_clip(working, v2.id, clip.id, 1_500),
        )
    )
    assert project.video_tracks[1].clips[0].timeline_in_ms == 1_500
    assert project.video_tracks[1].clips[0].source_in_ms == 0


def test_move_then_hide_v1_rebinds_v2_without_followup_seek(tmp_path, monkeypatch):
    _app()
    project = _project(tmp_path)
    page = SubtitleStudioPage()
    page.project = project
    page.timeline.set_playhead(1_000)
    v1 = str(Path(project.media.path).resolve())
    v2 = str(Path(project.media_pool[-1].canonical_source).resolve())
    page.video._media_path = v1
    page._active_video_preview_key = "primary"
    page._active_video_preview_track_id = "V1"
    rebinds: list[tuple[str, float, int]] = []

    def switch(path, _ass, *, source_seconds, project_ms):
        page.video._media_path = str(Path(path).resolve())
        rebinds.append((page.video._media_path, source_seconds, project_ms))
        return True

    monkeypatch.setattr(page.video, "switch_media_at_async", switch)
    monkeypatch.setattr(page.video, "seek", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page.video, "set_paused", lambda *_args, **_kwargs: None)
    deltas = []
    state_for(project).subscribe(deltas.append)

    clip = project.video_tracks[1].clips[0]
    page._video_clip_move_committed("V2", clip.id, 0)
    assert deltas[-1].dirty & DirtyDomain.MEDIA_TIMING
    assert deltas[-1].dirty & DirtyDomain.VIDEO_COMPOSITION
    assert [layer[0].id for layer in active_video_clips(project, 1_000)] == ["V1", "V2"]

    page._video_track_action("V1", "enabled")

    assert page._active_video_preview_track_id == "V2"
    assert page._active_video_preview_clip_id == clip.id
    assert rebinds[-1] == (v2, 1.0, 1_000)
    assert [layer[0].id for layer in active_video_clips(project, 1_000)] == ["V2"]
    page.close_page()
    page.deleteLater()
