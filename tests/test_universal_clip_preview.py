"""Source identity and actual held-mouse drawing, never just release state."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_project import SubtitleProject, StudioMedia, save_project, load_project, sync_linked_av_contract
from twobyteasr.studio_media_pool import add_media_asset, add_video_clip, create_video_track
from twobyteasr.studio_edit_sequence import sequence_of
from twobyteasr.studio_clip_edit import reassign_clips_command, clip_edit_command
from twobyteasr.studio_timeline import WaveformTimeline
from twobyteasr.audio_graph import capture_audio_graph, preview_audio_layers
from twobyteasr.clip_time_mapper import project_to_source


def sample():
    p = SubtitleProject(media=StudioMedia(path='A.mp4', duration_ms=120000))
    p.validate()
    p.video_tracks[0].locked = sequence_of(p).video_track_locked = False
    a = p.video_tracks[0].clips[0]
    a.source_in_ms, a.source_out_ms, a.timeline_out_ms = 30000, 40000, 10000
    from twobyteasr.studio_edit_sequence import VideoSegment
    sequence_of(p).segments = [VideoSegment(a.id, p.media.path, 30000, 40000, 0, 10000)]
    asset = add_media_asset(p, 'B.mp4', duration_ms=120000)
    create_video_track(p, 'V2')
    add_video_clip(p, 'V2', asset.asset_id, timeline_in_ms=15000, source_in_ms=100000, source_out_ms=105000)
    sync_linked_av_contract(p)
    for asset in p.media_pool:
        asset.offline = False
    return p


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def test_exact_user_mapping_edit_and_reopen(tmp_path):
    p = sample(); b = copy.deepcopy(p.video_tracks[1].clips[0]); before = p.to_dict()
    a = p.audio_tracks[1].clips[0]; a.gain_db = -7
    stack = QUndoStack(); stack.push(reassign_clips_command(p, 'V2', 'V1', [b.id], start=10000))
    moved = p.video_tracks[0].clips[1]
    assert moved.id == b.id and moved.asset_id == b.asset_id
    assert project_to_source(moved, 12000) == 102000
    layers = preview_audio_layers(capture_audio_graph(p), 12000)
    assert len(layers) == 1 and Path(layers[0]['source_path']).name == 'B.mp4'
    assert layers[0]['source_ms'] == 102000 and layers[0]['gain_db'] == -7
    loaded = load_project(save_project(p, tmp_path / 'mixed.2byteproj'))
    assert loaded.video_tracks == p.video_tracks and loaded.audio_tracks == p.audio_tracks
    clip_edit_command(loaded, 'V1', 'split', clip_id=b.id, time_ms=12000).redo()
    right = loaded.video_tracks[0].clips[-1]
    clip_edit_command(loaded, 'V1', 'trim', clip_id=right.id, start=13000, end=15000).redo()
    reassign_clips_command(loaded, 'V1', 'V2', [right.id], start=20000).redo()
    assert project_to_source(loaded.video_tracks[1].clips[0], 21000) == 104000
    stack.undo()
    assert p.video_tracks[1].clips[0] == b
    stack.redo()
    assert project_to_source(p.video_tracks[0].clips[1], 12000) == 102000


def test_detached_audio_never_reattaches_or_duplicates_after_crossing(tmp_path):
    p = sample(); b = p.video_tracks[1].clips[0]
    p.av_track_groups[1].linked = False
    detached = copy.deepcopy(p.audio_tracks[1])
    reassign_clips_command(p, 'V2', 'V1', [b.id], start=10000).redo()
    p = load_project(save_project(p, tmp_path / 'detached.2byteproj'))
    for asset in p.media_pool:
        asset.offline = False  # Logical mapping test; no decoder is invoked.
    assert p.audio_tracks[1] == detached
    assert not any(a.linked_video_clip_id == b.id for a in p.audio_tracks[0].clips)
    sources = [x for x in capture_audio_graph(p)['inputs'] if x['asset_id'] == b.asset_id]
    assert len(sources) == 1 and sources[0]['timeline_in_ms'] == 15000


@pytest.fixture
def timeline():
    t = WaveformTimeline(); t.resize(1200, 650); t.set_project(sample())
    t.filmstrip_visible = False; t.set_visible_window(0, 20000); t.set_playhead(0)
    t.show(); QApplication.processEvents()
    yield t
    t.close(); t.deleteLater(); QApplication.processEvents()


def point(t, lane, ms):
    return QPoint(round(t._time_to_x(ms)), round(t._video_track_rect(lane).center().y()))


def hold(t, target='V1', ms=12000):
    QTest.mousePress(t, Qt.LeftButton, Qt.NoModifier, point(t, 'V2', 17000))
    QTest.mouseMove(t, point(t, target, ms), 10)
    QApplication.processEvents()
    assert t._clip_drag and t._clip_drag['moved']


@pytest.mark.parametrize('lane,ms,expected', [('V1', 12000, 10000), ('V2', 14000, 12000)])
def test_held_mouse_projects_audio_and_video_without_commit(timeline, lane, ms, expected, monkeypatch):
    t = timeline
    t.set_snap_enabled(lane == 'V1')
    before = copy.deepcopy(t.project.to_dict())
    # Inspect actual painter inputs while the mouse is still held. No ffmpeg or
    # peak generation can be hidden by this test's deterministic source cache.
    drawn = []
    for asset in t.project.media_pool:
        t.waveform_caches[asset.asset_id] = SimpleNamespace(metadata=SimpleNamespace(source_path=asset.canonical_source))
    # 2026-10-12: the lane draws fixed-grid tiles; the hook receives the same
    # visible source range, left edge and lane rect as before.
    monkeypatch.setattr(t, '_waveform_envelope_tiles', lambda cache, a, b, left, right, rect, *clip_range:
        drawn.append((cache.metadata.source_path, a, b, left, rect.center().y())) or [])
    commits = []
    t.video_clip_move_committed.connect(lambda *v: commits.append(v))
    t.video_clip_reassign_committed.connect(lambda *v: commits.append(v))
    hold(t, lane, ms); t.repaint()
    snapshot = t._clip_drag['snapshot']; assert snapshot and not t._clip_drag['invalid']
    v = next(c for track in snapshot[0] if track.id == lane for c in track.clips if c.source_in_ms == 100000)
    audio_track = next(track for track in snapshot[1] if any(c.linked_video_clip_id == v.id for c in track.clips))
    a = next(c for c in audio_track.clips if c.linked_video_clip_id == v.id)
    assert abs(v.timeline_in_ms - expected) < 25
    assert (v.timeline_in_ms, v.timeline_out_ms) == (a.timeline_in_ms, a.timeline_out_ms)
    assert any(Path(path).name == 'B.mp4' and sin == 100000 and sout == 105000
               and abs(left - t._time_to_x(v.timeline_in_ms)) < 1
               and y == t._audio_track_rects()[audio_track.id].center().y()
               for path, sin, sout, left, y in drawn)
    assert t.project.to_dict() == before and not commits
    QTest.mouseRelease(t, Qt.LeftButton, Qt.NoModifier, point(t, lane, ms))
    assert len(commits) == 1 and t._clip_drag is None


@pytest.mark.parametrize('invalid', ['collision', 'video_lock', 'audio_lock', 'outside'])
def test_invalid_drop_and_escape_are_atomic(timeline, invalid):
    t = timeline
    if invalid == 'video_lock': t.project.video_tracks[0].locked = True
    if invalid == 'audio_lock': t.project.audio_tracks[0].locked = True
    before = copy.deepcopy(t.project.to_dict()); commits = []
    t.video_clip_reassign_committed.connect(lambda *v: commits.append(v))
    hold(t, ms=7000 if invalid == 'collision' else 12000)
    end = point(t, 'V1', 12000)
    if invalid == 'outside':
        # Lanes start under the ruler (2026-10-09, M16); the spare area
        # below the last lane is outside every media lane.
        below = round(t._stack_bottom()) + 20
        assert below < t._canvas_bottom()
        end = QPoint(600, below); QTest.mouseMove(t, end, 10)
    assert t._clip_drag['invalid']
    QTest.mouseRelease(t, Qt.LeftButton, Qt.NoModifier, end)
    assert not commits and t.project.to_dict() == before


def test_scroll_zoom_cancel_keep_common_source_and_no_history(timeline):
    t = timeline; t.set_snap_enabled(False); before = copy.deepcopy(t.project.to_dict())
    t.set_visible_window(10000, 10000); hold(t, 'V2', 18000)
    old = t._clip_drag['snapshot'][0][1].clips[0].timeline_in_ms
    t.set_visible_window(9000, 10000)
    assert t._clip_drag['snapshot'][0][1].clips[0].timeline_in_ms == old - 1000
    t.set_visible_window(9000, 8000)
    QTest.mouseMove(t, QPoint(t._content_right()-4, point(t, 'V2', 16000).y()), 10)
    start = t.visible_start_ms
    QTest.qWait(100)
    assert t.visible_start_ms > start
    v, a, _, _ = t._clip_drag['snapshot']
    assert v[1].clips[0].timeline_in_ms == a[1].clips[0].timeline_in_ms
    QTest.keyClick(t, Qt.Key_Escape)
    assert not t._clip_drag and not t._clip_scroll_timer.isActive()
    assert t.project.to_dict() == before


def test_speed_waveform_uses_trimmed_source_window(timeline, monkeypatch):
    t = timeline; c = t.project.video_tracks[1].clips[0]
    c.playback_rate = 2; c.timeline_out_ms = 17500
    sync_linked_av_contract(t.project)
    t.set_visible_window(16000, 1000)
    seen = []
    for asset in t.project.media_pool:
        t.waveform_caches[asset.asset_id] = SimpleNamespace(metadata=SimpleNamespace(source_path=asset.canonical_source))
    monkeypatch.setattr(t, '_waveform_envelope_tiles', lambda cache, a, b, *args: seen.append((a, b)) or [])
    t.repaint()
    assert (102000, 104000) in seen


@pytest.mark.parametrize('relink', [False, True])
def test_late_peak_result_after_cancel_never_restores_drag_or_wrong_source(timeline, monkeypatch, relink):
    t = timeline; asset = t.project.media_pool[1]
    old_path = asset.canonical_source
    before = copy.deepcopy(t.project.to_dict())
    hold(t); QTest.keyClick(t, Qt.Key_Escape)
    assert t.project.to_dict() == before
    if relink:
        asset.canonical_source = str(Path(old_path).with_name('replacement.mp4'))
    # Simulate an earlier asynchronous decode arriving after drag cancellation
    # (and optionally after relink). It owns source peaks, never clip position.
    cache = SimpleNamespace(metadata=SimpleNamespace(source_path=old_path, duration_ms=120000))
    t.set_cache(cache)
    drawn = []
    # 2026-10-12: the lane draws fixed-grid tiles; the hook receives the same
    # visible source range, left edge and lane rect as before.
    monkeypatch.setattr(t, '_waveform_envelope_tiles', lambda cache, a, b, left, right, rect, *clip_range:
        drawn.append((cache.metadata.source_path, a, b, left, rect.center().y())) or [])
    t.repaint()
    assert t._clip_drag is None
    clip = t.project.video_tracks[1].clips[0]
    assert clip.timeline_in_ms == 15000 and clip.source_in_ms == 100000
    if relink:
        assert t.waveform_cache_for_source(asset.canonical_source) is None
        assert not drawn
    else:
        assert t.waveform_cache_for_source(old_path) is cache
        assert any(a == 100000 and b == 105000 and abs(left-t._time_to_x(15000)) < 1
                   and y == t._audio_track_rects()['A2'].center().y()
                   for _, a, b, left, y in drawn)
