"""2026-10-25 (user): drag only the picture or only the sound of a source into the tracks.

Picture only = a video clip with ``audio_enabled=False`` and no linked audio
clip; sound only = an audio clip with no video owner on an ordinary A lane.
「分离音频」 turns a linked clip into both. No new project fields.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.audio_graph import capture_audio_graph, preview_audio_layers
from twobyteasr.projects.studio_project import (
    StudioMedia, SubtitleProject, load_project, save_project, sync_linked_av_contract)
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.timeline.studio_media_commands import media_graph_command
from twobyteasr.timeline.studio_media_pool import (
    add_media_asset, add_video_clip, apply_placement, can_detach_clip_audio, create_video_track,
    detach_clip_audio, linked_audio_clip, placement_plan, set_audio_master_mode,
    set_video_clip_audio_enabled)


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def _streams(count):
    return [{"ordinal": n, "index": n + 1, "default": n == 0} for n in range(count)]


@pytest.fixture
def project(tmp_path):
    for name in ("main.mp4", "clip.mp4", "song.wav", "mute.mp4", "dual.mkv"):
        (tmp_path / name).write_bytes(b"x")
    p = SubtitleProject(media=StudioMedia(str(tmp_path / "main.mp4"), duration_ms=60000, width=1920, height=1080))
    p.validate()
    p.media_pool[0].audio_metadata["has_audio"] = True
    add_media_asset(p, tmp_path / "clip.mp4", duration_ms=5000,
                    video_metadata={"has_video": True}, audio_metadata={"has_audio": True})
    add_media_asset(p, tmp_path / "song.wav", duration_ms=8000,
                    video_metadata={"has_video": False}, audio_metadata={"has_audio": True})
    add_media_asset(p, tmp_path / "mute.mp4", duration_ms=4000,
                    video_metadata={"has_video": True}, audio_metadata={"has_audio": False})
    add_media_asset(p, tmp_path / "dual.mkv", duration_ms=6000, video_metadata={"has_video": True},
                    audio_metadata={"has_audio": True, "streams": _streams(2)})
    sync_linked_av_contract(p)
    return p


def _asset(p, name):
    return next(a for a in p.media_pool if a.display_name == name).asset_id


def _clips(p):
    return {t.id: [(c.timeline_in_ms, c.timeline_out_ms, c.linked_video_clip_id or "free")
                   for c in t.clips] for t in p.audio_tracks}


def _audible(p, ms):
    return {(x["audio_track_id"], os.path.basename(x["source_path"]))
            for x in preview_audio_layers(capture_audio_graph(p), ms) if x["audio_enabled"]}


def test_picture_only_has_no_audio_clip_and_no_sound(project):
    p = project
    plan = placement_plan(p, _asset(p, "clip.mp4"), "video", timeline_in_ms=1000)
    assert plan["new_video_track"] and plan["audio_enabled"] is False
    clip_id = apply_placement(p, plan)
    track = next(t for t in p.video_tracks if any(c.id == clip_id for c in t.clips))
    assert track.id != "V1"
    assert linked_audio_clip(p, track.id, clip_id) is None
    sync_linked_av_contract(p)  # validation must not bring the sound back
    assert linked_audio_clip(p, track.id, clip_id) is None
    set_audio_master_mode(p, "mix_all")
    assert "clip.mp4" not in {name for _, name in _audible(p, 2000)}
    assert "main.mp4" in {name for _, name in _audible(p, 2000)}


def test_switching_audio_off_keeps_the_linked_clip(project):
    p = project
    track = create_video_track(p)
    clip = add_video_clip(p, track.id, _asset(p, "clip.mp4"), timeline_in_ms=0)
    set_video_clip_audio_enabled(p, track.id, clip.id, False)
    assert linked_audio_clip(p, track.id, clip.id) is not None
    set_video_clip_audio_enabled(p, track.id, clip.id, True)
    assert linked_audio_clip(p, track.id, clip.id) is not None


def test_picture_only_of_a_multi_stream_source_gets_no_stream_lanes(project):
    p = project
    clip_id = apply_placement(p, placement_plan(p, _asset(p, "dual.mkv"), "video", timeline_in_ms=0))
    track = next(t for t in p.video_tracks if any(c.id == clip_id for c in t.clips))
    assert not [t for t in p.audio_tracks if t.stream_ordinal >= 0 and t.linked_video_track_id == track.id]
    both = apply_placement(p, placement_plan(p, _asset(p, "dual.mkv"), "both", timeline_in_ms=10000))
    track = next(t for t in p.video_tracks if any(c.id == both for c in t.clips))
    assert [t.stream_ordinal for t in p.audio_tracks
            if t.stream_ordinal >= 0 and t.linked_video_track_id == track.id] == [1]


def test_sound_only_lands_on_the_free_lane_under_the_pointer(project):
    p = project
    a1 = next(g.audio_track_id for g in p.av_track_groups if g.video_track_id == "V1")
    busy = placement_plan(p, _asset(p, "song.wav"), "audio", timeline_in_ms=1000, audio_track_id=a1)
    assert busy["new_audio_track"]  # the main recording's sound fills A1 there
    clip_id = apply_placement(p, busy)
    lane = next(t for t in p.audio_tracks if any(c.id == clip_id for c in t.clips))
    assert lane.id not in {g.audio_track_id for g in p.av_track_groups} and lane.stream_ordinal == -1
    assert _clips(p)[lane.id] == [(1000, 9000, "free")]
    later = placement_plan(p, _asset(p, "clip.mp4"), "audio", timeline_in_ms=9000, audio_track_id=lane.id)
    assert later["audio_track_id"] == lane.id and not later["new_audio_track"]
    apply_placement(p, later)
    assert _clips(p)[lane.id] == [(1000, 9000, "free"), (9000, 14000, "free")]
    sync_linked_av_contract(p)
    assert _clips(p)[lane.id] == [(1000, 9000, "free"), (9000, 14000, "free")]
    set_audio_master_mode(p, "mix_all")
    assert (lane.id, "song.wav") in _audible(p, 2000)


def test_parts_follow_what_the_source_has(project):
    p = project
    assert placement_plan(p, _asset(p, "song.wav"), "both", timeline_in_ms=0)["part"] == "audio"
    plan = placement_plan(p, _asset(p, "mute.mp4"), "both", timeline_in_ms=0)
    assert plan["part"] == "video" and plan["audio_enabled"] is True
    with pytest.raises(ValueError):
        placement_plan(p, _asset(p, "song.wav"), "video", timeline_in_ms=0)
    with pytest.raises(ValueError):
        placement_plan(p, _asset(p, "mute.mp4"), "audio", timeline_in_ms=0)


def test_pictures_never_land_on_v1_and_prefer_the_track_under_the_pointer(project):
    p = project
    v2 = create_video_track(p)
    v3 = create_video_track(p)
    asset = _asset(p, "clip.mp4")
    assert placement_plan(p, asset, "both", timeline_in_ms=0, video_track_id="V1")["video_track_id"] == v2.id
    assert placement_plan(p, asset, "both", timeline_in_ms=0, video_track_id=v3.id)["video_track_id"] == v3.id
    add_video_clip(p, v3.id, asset, timeline_in_ms=0)
    plan = placement_plan(p, asset, "both", timeline_in_ms=2000, video_track_id=v3.id)
    assert plan["video_track_id"] == v2.id
    v2.locked = True
    assert placement_plan(p, asset, "both", timeline_in_ms=2000, video_track_id=v3.id)["new_video_track"]


def test_detach_audio_splits_picture_and_sound(project):
    p = project
    track = create_video_track(p)
    clip = add_video_clip(p, track.id, _asset(p, "clip.mp4"), timeline_in_ms=2000)
    sound = linked_audio_clip(p, track.id, clip.id)
    sound.gain_db = -6.0
    lane = next(g.audio_track_id for g in p.av_track_groups if g.video_track_id == track.id)
    stack = QUndoStack()
    stack.push(media_graph_command(p, "分离音频", lambda w: detach_clip_audio(w, track.id, clip.id)))
    clip = p.video_tracks[-1].clips[0]
    assert clip.audio_enabled is False and linked_audio_clip(p, track.id, clip.id) is None
    free = [c for c in next(t for t in p.audio_tracks if t.id == lane).clips]
    assert [(c.timeline_in_ms, c.timeline_out_ms, c.linked_video_clip_id, c.gain_db) for c in free] == [
        (2000, 7000, "", -6.0)]
    # The picture moves alone; the sound stays.
    from twobyteasr.timeline.studio_media_pool import move_video_clip
    move_video_clip(p, track.id, clip.id, 10000)
    assert [(c.timeline_in_ms, c.timeline_out_ms) for c in next(t for t in p.audio_tracks if t.id == lane).clips] == [
        (2000, 7000)]
    stack.undo()
    clip = p.video_tracks[-1].clips[0]
    assert clip.audio_enabled and linked_audio_clip(p, track.id, clip.id) is not None
    stack.redo()
    assert linked_audio_clip(p, track.id, p.video_tracks[-1].clips[0].id) is None


def test_detach_audio_on_the_main_track_survives_the_edit_sequence(project):
    p = project
    p.video_tracks[0].locked = False
    sequence_of(p).video_track_locked = False
    main = p.video_tracks[0].clips[0]
    assert can_detach_clip_audio(p, "V1", main.id) == ""
    detach_clip_audio(p, "V1", main.id)
    from twobyteasr.timeline.studio_media_pool import sync_primary_video_track_from_sequence
    sync_primary_video_track_from_sequence(p, sequence_of(p))
    assert p.video_tracks[0].clips[0].audio_enabled is False
    assert linked_audio_clip(p, "V1", p.video_tracks[0].clips[0].id) is None


def test_detach_audio_refuses_multi_stream_and_silent_clips(project):
    p = project
    track = create_video_track(p)
    dual = add_video_clip(p, track.id, _asset(p, "dual.mkv"), timeline_in_ms=0)
    mute = add_video_clip(p, track.id, _asset(p, "mute.mp4"), timeline_in_ms=7000)
    assert can_detach_clip_audio(p, track.id, dual.id) == "多音轨素材暂不支持分离音频"
    assert can_detach_clip_audio(p, track.id, mute.id) == "这个片段没有连着的音频"
    with pytest.raises(ValueError):
        detach_clip_audio(p, track.id, mute.id)


def test_picture_only_and_free_sound_survive_save_and_reopen(project, tmp_path):
    p = project
    picture = apply_placement(p, placement_plan(p, _asset(p, "clip.mp4"), "video", timeline_in_ms=0))
    sound = apply_placement(p, placement_plan(p, _asset(p, "song.wav"), "audio", timeline_in_ms=500))
    reopened = load_project(save_project(p, tmp_path / "av.2byteproj"))
    track = next(t for t in reopened.video_tracks if any(c.id == picture for c in t.clips))
    assert linked_audio_clip(reopened, track.id, picture) is None
    lane = next(t for t in reopened.audio_tracks if any(c.id == sound for c in t.clips))
    assert [(c.timeline_in_ms, c.linked_video_clip_id) for c in lane.clips] == [(500, "")]
