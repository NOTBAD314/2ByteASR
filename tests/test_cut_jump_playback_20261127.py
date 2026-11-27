"""2026-11-27: playing across a cut with a deleted range between the pieces.

User report: Studio playback paused at every cut. Razor cuts were fixed by
handing over without a seek (test_contiguous_cut_playback_20261127). A real
jump (AI rough cut, silence cut, ripple delete) still needs an mpv seek, but
it went through the user-seek cover first: a screenshot of the last frame and
caption preparation took ~75 ms before mpv even started seeking, and the jump
began only after the decoder had shown a frame from the deleted range, which
then stayed frozen on screen. Measured in the real window (1080p, 10 s GOP,
jump mid-GOP): ~233 ms before, ~133 ms after.

Also: the first periodic media-availability probe (~15 s after opening) only
adds the stream identity of a file the open-time check had stat'ed. It reset
the active preview binding and re-seeked the player mid-piece.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.media.media_availability import playback_identity_changed
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio import caption_seek_preparation
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.timeline.studio_edit_sequence import (
    delete_timeline_range,
    ensure_edit_sequence,
    replace_runtime_sequence,
    sequence_of,
    split_at_playhead,
)
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence


class _Recorder:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result

    @property
    def flat(self):
        return [args for args, _ in self.calls]


def _project(tmp_path: Path) -> SubtitleProject:
    """Pieces: source [0,20) [20,30) [30,40) [45,55); timeline cut 40 jumps to source 45."""
    media = tmp_path / "recording.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), display_name=media.name, duration_ms=60_000,
                          fingerprint="recording", width=1920, height=1080),
        cues=[StudioCue("cue-1", 0, 1_000, "字幕")],
    )
    project.validate()
    sequence = ensure_edit_sequence(project)
    sequence = delete_timeline_range(sequence, 55_000, 60_000)
    sequence = delete_timeline_range(sequence, 40_000, 45_000)
    sequence = split_at_playhead(sequence, 20_000)
    sequence = split_at_playhead(sequence, 30_000)
    replace_runtime_sequence(project, sequence)
    sync_primary_video_track_from_sequence(project, sequence)
    return project


def _segments(project):
    return sorted(sequence_of(project).segments, key=lambda item: item.timeline_in_ms)


def _playing_page(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    page = SubtitleStudioPage()
    page.project = project
    page.video.controller = SimpleNamespace(running=True, set_raw_overlay=_Recorder(), remove_overlay=_Recorder())
    page._refresh_edit_playback_state()
    page.video._paused = False
    page.video.set_paused = _Recorder()
    page.video.seek = _Recorder()
    cover = _Recorder(result=True)  # an active caption scene would take the seek
    monkeypatch.setattr(caption_seek_preparation, "coordinate_caption_seek", cover)
    return page, cover


def _close(page):
    page.close_page()
    page.deleteLater()


def test_cut_jump_seeks_mpv_directly_without_the_user_seek_cover(tmp_path, monkeypatch):
    page, cover = _playing_page(tmp_path, monkeypatch)
    page._active_video_preview_clip_id = _segments(page.project)[2].id

    page._advance_project_boundary(40_000)

    assert cover.calls == []
    assert page.video.seek.flat and page.video.seek.flat[-1][0] == 45.0
    assert page.video.seek.calls[-1][1].get("project_ms") == 40_000
    _close(page)


def test_a_user_seek_still_uses_the_cover(tmp_path, monkeypatch):
    page, cover = _playing_page(tmp_path, monkeypatch)

    page._seek(41.0)

    assert cover.flat == [(page, 41.0, True)]
    assert page.video.seek.calls == []
    _close(page)


def test_cut_jump_while_paused_or_during_a_user_seek_keeps_the_cover(tmp_path, monkeypatch):
    page, cover = _playing_page(tmp_path, monkeypatch)
    page.video._paused = True
    page._seek(40.0, cut_jump=True)
    assert len(cover.calls) == 1

    page.video._paused = False
    page._caption_seek_preparation = SimpleNamespace(pending={"phase": "seek"})
    page._seek(40.0, cut_jump=True)
    assert len(cover.calls) == 2
    page._caption_seek_preparation = None
    _close(page)


def test_jump_is_armed_before_the_out_point_and_fires_once(tmp_path, monkeypatch):
    page, _cover = _playing_page(tmp_path, monkeypatch)
    third = _segments(page.project)[2]
    page._active_video_preview_clip_id = third.id
    boundary = _Recorder()
    page._advance_project_boundary = boundary

    page._position_changed(39.90, _bypass_throttle=True)   # 100 ms left: not yet
    assert getattr(page, "_predicted_cut_jump", None) is None
    page._position_changed(39.97, _bypass_throttle=True)   # 30 ms left: arm
    token = page._predicted_cut_jump
    assert token is not None and token[2] == third.id
    page._position_changed(39.98, _bypass_throttle=True)   # same piece: not re-armed

    page._fire_predicted_cut_jump(token, third.timeline_out_ms)
    page._fire_predicted_cut_jump(token, third.timeline_out_ms)

    assert boundary.flat == [(40_000,)]
    assert page.video.seek.calls == []
    _close(page)


def test_razor_cut_and_last_piece_are_not_predicted(tmp_path, monkeypatch):
    page, _cover = _playing_page(tmp_path, monkeypatch)
    first, _second, _third, fourth = _segments(page.project)
    page._active_video_preview_clip_id = first.id
    page._position_changed(19.98, _bypass_throttle=True)   # contiguous successor
    assert getattr(page, "_predicted_cut_jump", None) is None

    page._active_video_preview_clip_id = fourth.id
    page._position_changed(54.98, _bypass_throttle=True)   # project end
    assert getattr(page, "_predicted_cut_jump", None) is None
    _close(page)


def test_a_seek_or_pause_cancels_the_predicted_jump(tmp_path, monkeypatch):
    page, _cover = _playing_page(tmp_path, monkeypatch)
    third = _segments(page.project)[2]
    page._active_video_preview_clip_id = third.id
    boundary = _Recorder()
    page._advance_project_boundary = boundary

    page._position_changed(39.97, _bypass_throttle=True)
    token = page._predicted_cut_jump
    page._seek(10.0)                       # user seek retires it
    page._fire_predicted_cut_jump(token, third.timeline_out_ms)

    page._active_video_preview_clip_id = third.id
    page._position_changed(39.97, _bypass_throttle=True)
    token = page._predicted_cut_jump
    page.video._paused = True              # user pause before it fires
    page._fire_predicted_cut_jump(token, third.timeline_out_ms)

    assert boundary.calls == []
    _close(page)


def test_hold_entering_position_does_not_post_a_second_seek(tmp_path, monkeypatch):
    """The jump's own hold pause reports the old position against the new piece."""
    page, _cover = _playing_page(tmp_path, monkeypatch)
    page._active_video_preview_clip_id = _segments(page.project)[3].id   # source [45, 55)
    page.video._paused = True
    page.video._seek_hold_entering = True
    page._position_changed(40.0, _bypass_throttle=True)
    assert page.video.seek.calls == []

    page.video._seek_hold_entering = False
    page._position_changed(40.0, _bypass_throttle=True)   # a real early decoder report
    assert page.video.seek.flat == [(45.0,)]
    _close(page)


def test_first_decode_probe_of_an_open_file_is_not_a_playback_change():
    stat = {"status": "available", "signature": [10, 20]}
    decoded = dict(stat, identity={"has_video": True, "has_audio": True})
    assert not playback_identity_changed(stat, decoded)
    assert not playback_identity_changed(decoded, dict(decoded))
    assert playback_identity_changed(stat, dict(decoded, signature=[11, 20]))
    assert playback_identity_changed(decoded, dict(decoded, identity={"has_video": False, "has_audio": True}))
    assert playback_identity_changed({}, decoded)
    assert playback_identity_changed({"status": "offline"}, decoded)
    assert playback_identity_changed(stat, {"status": "decode_failed", "signature": [10, 20]})


def test_availability_apply_keeps_the_preview_binding_on_first_decode(tmp_path, monkeypatch):
    page, _cover = _playing_page(tmp_path, monkeypatch)
    source = page.project.media_pool[0].canonical_source
    page.project._media_availability = {source: {"status": "available", "signature": [10, 20]}}
    page._active_video_preview_key = "primary-key"
    rebind = _Recorder()
    page._sync_multitrack_preview_at = rebind

    page.media_availability.apply(page.project, (source,), {
        source: {"status": "available", "signature": [10, 20], "identity": {"has_video": True}}})

    assert page._active_video_preview_key == "primary-key"
    assert rebind.calls == []
    _close(page)
