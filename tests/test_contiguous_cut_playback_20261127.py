"""2026-11-27: playing across a razor cut must not seek mpv.

User report: in 字幕工作台 playback froze about a second at every cut point.
Once the sequence was non-linear (any delete or trim), reaching the end of a
piece always called the boundary seek, even when the next piece starts at the
very source frame the decoder is already presenting. An exact seek to that
frame stalled the picture at every split. A real jump (deleted range, another
file, another speed) still seeks.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.timeline.studio_edit_sequence import (
    VideoSegment,
    delete_timeline_range,
    ensure_edit_sequence,
    replace_runtime_sequence,
    sequence_of,
    split_at_playhead,
)
from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
from twobyteasr.timeline.studio_sequence_mapper import contiguous_successor


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    @property
    def flat(self):
        return [args for args, _ in self.calls]


def _project(tmp_path: Path) -> SubtitleProject:
    """60 s source: split at 20 s and 30 s, 40-45 s deleted, 55-60 s deleted.

    Pieces: source [0,20) [20,30) [30,40) [45,55); cuts at 20 and 30 continue
    the source, the cut at timeline 40 jumps to source 45.
    """
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


def _page(project):
    page = SubtitleStudioPage()
    page.project = project
    page.video.controller = SimpleNamespace(running=True, set_raw_overlay=_Recorder(), remove_overlay=_Recorder())
    page._refresh_edit_playback_state()
    return page


def _segments(project):
    return sorted(sequence_of(project).segments, key=lambda item: item.timeline_in_ms)


def _close(page):
    page.close_page()
    page.deleteLater()


def test_fixture_is_mapped_with_contiguous_and_jump_cuts(tmp_path):
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    rows = [(s.source_in_ms, s.source_out_ms, s.timeline_in_ms, s.timeline_out_ms) for s in _segments(project)]
    assert rows == [(0, 20_000, 0, 20_000), (20_000, 30_000, 20_000, 30_000),
                    (30_000, 40_000, 30_000, 40_000), (45_000, 55_000, 40_000, 50_000)]
    page = _page(project)
    assert page._playback_mode == "mapped"
    _close(page)


def test_contiguous_successor_only_for_same_file_frame_and_speed(tmp_path):
    project = _project(tmp_path)
    sequence = sequence_of(project)
    first, second, third, fourth = _segments(project)
    assert contiguous_successor(sequence, first) is second
    assert contiguous_successor(sequence, second) is third
    assert contiguous_successor(sequence, third) is None   # source jumps 40 -> 45
    assert contiguous_successor(sequence, fourth) is None  # last piece
    other_file = VideoSegment("x", "other.mp4", 20_000, 30_000, 20_000, 30_000)
    faster = VideoSegment("y", first.source_path, 20_000, 40_000, 20_000, 30_000)
    for following in (other_file, faster):
        sequence.segments = [first, following]
        assert contiguous_successor(sequence, first) is None


def test_playing_across_a_razor_cut_posts_no_seek(tmp_path):
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    page = _page(project)
    first, second, _third, _fourth = _segments(project)
    page._active_video_preview_clip_id = first.id
    page.video._paused = False
    page.video.set_paused = _Recorder()
    seek = _Recorder()
    boundary = _Recorder()
    page.video.seek = seek
    page._advance_project_boundary = boundary

    page._position_changed(20.04, _bypass_throttle=True)

    assert seek.flat == []
    assert boundary.flat == []
    assert page._active_video_preview_clip_id == second.id
    assert page.timeline.playhead_ms == 20_040
    _close(page)


def test_decoder_running_past_several_short_pieces_still_needs_no_seek(tmp_path):
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    page = _page(project)
    first, _second, third, _fourth = _segments(project)
    page._active_video_preview_clip_id = first.id
    page.video._paused = False
    page.video.set_paused = _Recorder()
    seek = _Recorder()
    page.video.seek = seek

    page._position_changed(30.5, _bypass_throttle=True)

    assert seek.flat == []
    assert page._active_video_preview_clip_id == third.id
    assert page.timeline.playhead_ms == 30_500
    _close(page)


def test_a_real_jump_still_seeks_to_the_next_piece(tmp_path):
    QApplication.instance() or QApplication([])
    project = _project(tmp_path)
    page = _page(project)
    _first, _second, third, _fourth = _segments(project)
    page._active_video_preview_clip_id = third.id
    page.video._paused = False
    page.video.set_paused = _Recorder()
    seek = _Recorder()
    page.video.seek = seek

    page._position_changed(40.03, _bypass_throttle=True)

    assert seek.flat and seek.flat[0][0] == 45.0
    assert seek.calls[0][1].get("project_ms") == 40_000
    _close(page)
