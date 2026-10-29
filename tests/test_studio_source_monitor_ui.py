"""2026-10-25 (user): preview a media-pool source in the cue-list slot, then drag its
picture or sound (or both) into the tracks like Premiere; 「分离音频」 on a clip."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMenu

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio import studio_video_canvas
from twobyteasr.studio.studio_source_monitor import MEDIA_PART_MIME, media_part_mime
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, linked_audio_clip


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(tmp_path, monkeypatch):
    for name in ("main.mp4", "clip.mp4", "song.wav"):
        (tmp_path / name).write_bytes(b"x")
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "main.mp4"), display_name="main.mp4",
                                                duration_ms=30_000, fingerprint="main", width=1920, height=1080),
                              cues=[StudioCue("cue", 0, 1_000, "你好")])
    project.validate()
    project.media_pool[0].audio_metadata["has_audio"] = True
    add_media_asset(project, tmp_path / "clip.mp4", fingerprint="clip", duration_ms=4_000,
                    video_metadata={"has_video": True}, audio_metadata={"has_audio": True})
    add_media_asset(project, tmp_path / "song.wav", fingerprint="song", duration_ms=6_000,
                    video_metadata={"has_video": False}, audio_metadata={"has_audio": True})
    create_video_track(project)
    project.validate()
    path = save_project(project, tmp_path / "av.2byteproj")
    loads = []
    monkeypatch.setattr(studio_video_canvas.MpvCanvas, "load",
                        lambda self, media_path, *_a, **_k: loads.append(media_path))
    studio = SubtitleStudioPage()
    monkeypatch.setattr(studio, "_generate_waveform", lambda *_args, **_kwargs: None)
    studio.resize(1600, 1000)
    studio.show()
    studio.open_project(path)
    QApplication.processEvents()
    studio.loads = loads
    yield studio
    studio.close_page()
    studio.deleteLater()


def _row(page, name):
    tree = page.media_pool_panel.assets
    return next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0) == name)


def _asset(page, name):
    return next(a.asset_id for a in page.project.media_pool if a.display_name == name)


def _lane_point(page, kind, track_id, ms):
    timeline = page.timeline
    rects = timeline._video_track_rects() if kind == "video" else timeline._audio_track_rects()
    row = rects[track_id]
    local = QPoint(round(timeline._time_to_x(ms)) + 2, round(row.center().y()))
    return timeline.mapTo(page, local)


def _drag(page, mime, point, *, drop):
    args = (QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    move = QDragMoveEvent(QPoint(point.x(), point.y()), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dragMoveEvent(move)
    preview = page.timeline._media_drop_preview
    if drop:
        page.dropEvent(QDropEvent(*args))
    return move.isAccepted(), preview


def _double_click(widget, pos):
    """The events Windows sends; QTest.mouseDClick never reaches itemDoubleClicked."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
                          (QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton),
                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        QApplication.sendEvent(widget, QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                                                   Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
        QApplication.processEvents()


def test_double_click_previews_in_the_cue_list_slot(page):
    tree = page.media_pool_panel.assets
    item = _row(page, "clip.mp4")
    _double_click(tree.viewport(), tree.visualItemRect(item).center())
    monitor = page.source_monitor
    assert page.cue_list_stack.currentWidget() is monitor and monitor.isVisible()
    assert monitor.title.text() == "clip.mp4"
    assert all(chip.isEnabled() for chip in monitor.chips.values())
    assert page.loads and page.loads[-1].endswith("clip.mp4")
    assert page.undo_stack.count() == 0  # previewing never edits the project
    item = _row(page, "song.wav")
    tree.setCurrentItem(item)
    tree.itemDoubleClicked.emit(item, 0)
    QApplication.processEvents()
    assert monitor.title.text() == "song.wav" and "没有画面" in monitor.note.text()
    assert [part for part, chip in monitor.chips.items() if chip.isEnabled()] == ["both", "audio"]
    monitor.back_button.click()
    assert page.cue_list_stack.currentIndex() == 0


def test_pool_rows_drag_the_whole_source(page):
    tree = page.media_pool_panel.assets
    mime = tree.mimeData([_row(page, "clip.mp4")])
    payload = json.loads(bytes(mime.data(MEDIA_PART_MIME)).decode("utf-8"))
    assert payload == {"asset_id": _asset(page, "clip.mp4"), "part": "both"}


def test_drag_picture_only_onto_v2_shows_where_it_lands(page):
    point = _lane_point(page, "video", "V2", 2_000)
    accepted, preview = _drag(page, media_part_mime(_asset(page, "clip.mp4"), "video"), point, drop=False)
    assert accepted and preview["video_track_id"] == "V2" and preview["part"] == "video"
    assert abs(preview["timeline_in_ms"] - 2_000) < 400
    before = page.undo_stack.count()
    _drag(page, media_part_mime(_asset(page, "clip.mp4"), "video"), point, drop=True)
    assert page.undo_stack.count() == before + 1 and page.timeline._media_drop_preview is None
    clip = page.project.video_tracks[1].clips[0]
    assert clip.audio_enabled is False and linked_audio_clip(page.project, "V2", clip.id) is None
    page.undo_stack.undo()
    assert page.project.video_tracks[1].clips == []


def test_drag_sound_only_onto_a_busy_lane_makes_a_new_audio_track(page):
    a1 = next(g.audio_track_id for g in page.project.av_track_groups if g.video_track_id == "V1")
    point = _lane_point(page, "audio", a1, 1_000)
    tracks = len(page.project.audio_tracks)
    accepted, preview = _drag(page, media_part_mime(_asset(page, "song.wav"), "audio"), point, drop=True)
    assert accepted and preview["new_audio_track"]
    assert len(page.project.audio_tracks) == tracks + 1
    lane = page.project.audio_tracks[-1]
    assert [(c.linked_video_clip_id, c.timeline_out_ms - c.timeline_in_ms) for c in lane.clips] == [("", 6_000)]
    assert lane.id in page.timeline._audio_track_rects()


def test_drop_outside_the_lanes_is_refused(page):
    point = page.timeline.mapTo(page, QPoint(10, 10))  # the track header / ruler
    accepted, preview = _drag(page, media_part_mime(_asset(page, "clip.mp4"), "both"), point, drop=False)
    assert not accepted and preview is None


def test_chip_click_adds_at_the_playhead(page):
    page.media_pool_panel.assets.setCurrentItem(_row(page, "clip.mp4"))
    page.media_pool_panel._preview_selected()
    page.timeline.playhead_ms = 5_000
    page.source_monitor.chips["both"].click()
    clip = page.project.video_tracks[1].clips[0]
    assert clip.timeline_in_ms == 5_000 and clip.audio_enabled
    assert linked_audio_clip(page.project, "V2", clip.id) is not None


def test_clip_menu_detaches_audio(page, monkeypatch):
    page.media_pool_panel.assets.setCurrentItem(_row(page, "clip.mp4"))
    page.media_pool_panel._preview_selected()
    page.source_monitor.chips["both"].click()
    clip = page.project.video_tracks[1].clips[0]
    menus = []

    class Menu(QMenu):
        def exec(self, *_args):  # never block the test
            menus.append(self)

    from twobyteasr.studio import studio_video_flow
    monkeypatch.setattr(studio_video_flow, "create_studio_menu", lambda parent=None, **_k: Menu(parent))
    page._show_video_track_menu("V2", clip.id, QPoint(0, 0))
    detach = next(a for a in menus[-1].actions() if a.text() == "分离音频")
    assert detach.isEnabled()
    detach.trigger()
    clip = page.project.video_tracks[1].clips[0]
    assert clip.audio_enabled is False and linked_audio_clip(page.project, "V2", clip.id) is None
    lane = next(g.audio_track_id for g in page.project.av_track_groups if g.video_track_id == "V2")
    assert [c.linked_video_clip_id for c in next(t for t in page.project.audio_tracks if t.id == lane).clips] == [""]
    page.undo_stack.undo()
    assert linked_audio_clip(page.project, "V2", page.project.video_tracks[1].clips[0].id) is not None
