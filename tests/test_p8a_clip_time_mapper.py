"""P8A unified ClipTimeMapper and seek authority."""

from __future__ import annotations

from twobyteasr.timeline.clip_time_mapper import (
    ClipTiming,
    map_project_time,
    moved_timing,
    project_to_source,
    source_to_project,
    trimmed_left,
    trimmed_right,
)


def test_project_to_source_formula():
    clip = ClipTiming(
        timeline_in_ms=9_000,
        timeline_out_ms=189_000,
        source_in_ms=0,
        source_out_ms=180_000,
        playback_rate=1.0,
        clip_id="v2",
        track_id="V2",
    )
    assert project_to_source(clip, 10_000) == 1_000
    assert project_to_source(clip, 8_999) is None
    assert source_to_project(clip, 1_000) == 10_000


def test_seek_ten_seconds_does_not_become_seventeen():
    v2 = ClipTiming(9_000, 189_000, 0, 180_000, 1.0, "v2", "V2")
    v1 = ClipTiming(0, 175_000, 0, 175_000, 1.0, "v1", "V1")
    mapped_v1 = map_project_time(v1, 10_000)
    mapped_v2 = map_project_time(v2, 10_000)
    assert mapped_v1.source_ms == 10_000
    assert mapped_v2.source_ms == 1_000
    assert mapped_v1.source_ms != 17_000
    assert mapped_v2.source_ms != 17_000


def test_move_keeps_source_in_out():
    clip = ClipTiming(9_000, 19_000, 500, 10_500, 1.0, "v2", "V2")
    moved = moved_timing(clip, 3_000)
    assert moved.timeline_in_ms == 3_000
    assert moved.timeline_out_ms == 13_000
    assert moved.source_in_ms == 500
    assert moved.source_out_ms == 10_500


def test_trim_left_and_right_keep_mapping():
    clip = ClipTiming(9_000, 19_000, 0, 10_000, 1.0, "v2", "V2")
    left = trimmed_left(clip, 10_000)
    assert left.timeline_in_ms == 10_000
    assert left.source_in_ms == 1_000
    assert left.source_out_ms == 10_000
    right = trimmed_right(clip, 15_000)
    assert right.timeline_out_ms == 15_000
    assert right.source_out_ms == 6_000
    assert right.source_in_ms == 0


def test_playback_rate_scales_source():
    clip = ClipTiming(0, 5_000, 0, 10_000, 2.0, "v2", "V2")
    assert project_to_source(clip, 1_000) == 2_000
    assert source_to_project(clip, 4_000) == 2_000
