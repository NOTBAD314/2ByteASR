"""Opening a project saved with the playhead at the timeline's end (2026-11-27).

User (2026-11-27): after recognising inside Subtitle Studio the result never opened: 「准备播放器」
failed with 准备超时 on every retry. Host log: the playhead was saved at the end (113628 ms) of
a cut FLV; the tail restore seeked inside the last clip [3391685, 3395858) and the picture landed
at 3395.864 (after the clip), the one fallback seek to the clip start landed at 3391.681 — 4 ms
before the clip's first millisecond, on the picture that is on screen at that millisecond — and
a strict test refused it, so no picture ever counted.
"""
from __future__ import annotations

from types import SimpleNamespace

from twobyteasr.playback.frame_readiness import frame_in_clip
from twobyteasr.timeline.studio_sequence_mapper import open_preview_position

LAST_CLIP = (3391685, 3395858)       # source ms of the last clip (timeline 109455-113628)


def _witness(position, tolerance=0.05):
    return dict(ready=True, position=position, target_tolerance_seconds=tolerance)


def test_the_picture_on_screen_at_the_clips_first_millisecond_is_the_clips():
    assert frame_in_clip(_witness(3391.681), LAST_CLIP)          # the host's fallback picture
    assert frame_in_clip(_witness(3393.0), LAST_CLIP)
    assert not frame_in_clip(_witness(3395.864), LAST_CLIP), 'a picture after the clip is not its own'
    assert not frame_in_clip(_witness(3395.858), LAST_CLIP)
    assert not frame_in_clip(_witness(3391.62), LAST_CLIP), 'more than a frame before: an earlier picture'
    assert not frame_in_clip(dict(_witness(3393.0), ready=False), LAST_CLIP)
    # Without a measured tolerance the witness's minimum (50 ms) applies.
    assert frame_in_clip(dict(ready=True, position=3391.681), LAST_CLIP)


def _preview(ms):
    clips = ((0, 16824, 3072143), (109455, 113628, 3391685))
    for timeline_in, timeline_out, source_in in clips:
        if timeline_in <= ms < timeline_out:
            return dict(timeline_in_ms=timeline_in, timeline_out_ms=timeline_out, clip_id=f'c{timeline_in}',
                        source_in_ms=source_in, source_out_ms=source_in + timeline_out - timeline_in,
                        source_ms=source_in + ms - timeline_in)
    return None


def test_the_hosts_open_now_finds_its_picture_after_the_one_fallback(monkeypatch):
    from twobyteasr.playback import frame_readiness
    from twobyteasr.studio.studio_readiness import StudioReadiness
    logical, preview, target, tail = open_preview_position(113628, 113628, _preview)
    assert (logical, preview, target['source_ms']) == (113628, 113627, 3395857)    # as logged
    assert tail['source_range'] == LAST_CLIP and tail['fallback_ms'] == 109455
    seeks = []
    page = SimpleNamespace(video=SimpleNamespace(_clock_only=False), _active_video_preview_clip_id='c109455',
                           _seek=seeks.append, _studio_trace=lambda *_a, **_k: None)
    gate = SimpleNamespace(page=page, last_progress=0.0)
    state = dict(tail, clip_id='c109455', logical_ms=logical, fallback_used=False, requested_at=0)
    monkeypatch.setattr(frame_readiness, 'video_frame_witness', lambda _video: _witness(3395.864))
    assert not StudioReadiness._validate_tail_restore(gate, state, True)
    assert seeks == [109.455], 'one fallback seek to the clip start (MEDIA_RESTORE_FALLBACK)'
    monkeypatch.setattr(frame_readiness, 'video_frame_witness', lambda _video: _witness(3391.681))
    assert StudioReadiness._validate_tail_restore(gate, state, True), 'the clip-start picture opens it'
    assert seeks == [109.455]
