"""Long overlaps must not hide short captions or leave stale timing indexes."""
import bisect
import random
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.interval_end_index import IntervalEndIndex
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import DirtyDomain, state_for
from twobyteasr.studio.studio_timeline import WaveformTimeline


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def captions():
    cues = [StudioCue('long', 0, 10000, 'long', speaker_id='A')]
    cues += [StudioCue(str(i), i*3+1, i*3+3, 'short', speaker_id=('A' if i % 2 else 'B'))
             for i in range(2000)]
    return cues


def test_range_max_index_matches_brute_force_for_overlaps_and_boundaries():
    rng = random.Random(8473)
    starts = sorted(rng.randrange(0, 3000) for _ in range(2000))
    ends = [start+rng.randrange(0, 200) for start in starts]
    ends[0] = 10000
    index = IntervalEndIndex(ends)
    assert IntervalEndIndex().before_with_end_after(3, 0) == ()
    for _ in range(300):
        start, end = sorted((rng.randrange(0, 3500), rng.randrange(0, 3500)))
        stop = bisect.bisect_left(starts, end)
        assert index.before_with_end_after(stop, start) == tuple(i for i in range(stop) if ends[i] > start)


def test_runtime_queries_keep_order_overlap_half_open_and_timing_edits():
    project = SubtitleProject(StudioMedia('', duration_ms=10000), cues=captions(),
                              render_settings={'_cue_domain': 'timeline'})
    runtime = state_for(project)
    ordered = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
    for value in (0, 1, 2, 3, 1999, 4000, 6000, 9999, 10000):
        assert [c.id for c in runtime.cues_at(value)] == [c.id for c in ordered if c.start_ms <= value < c.end_ms]
        assert [c.id for c in runtime.visible_cues(value, value+31)] == [c.id for c in ordered if c.start_ms < value+31 and c.end_ms > value]
    with runtime.transaction(project, action_id='move', dirty=DirtyDomain.CUE_TIMING, affected_cue_ids=('long',)):
        project.cues[0].end_ms = 100
    assert not runtime.cues_at(9999)
    assert runtime.cues_at(99)[0].id == 'long'


def test_timeline_viewport_and_live_timing_preview_preserve_order(app):
    project = SubtitleProject(StudioMedia('', duration_ms=10000), cues=captions(),
                              render_settings={'_cue_domain': 'timeline'})
    timeline = WaveformTimeline()
    try:
        timeline.set_project(project)
        start, end = 5500, 5520
        expected = [c.id for c in sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
                    if c.start_ms < end and c.end_ms > start]
        assert [c.id for c in timeline._cues_intersecting(start, end)] == expected
        moved = project.cues[10]
        timeline._timing_preview = {moved.id: SimpleNamespace(start_ms=5501, end_ms=5510, speaker_id='B')}
        visible = timeline._cues_intersecting(start, end)
        assert [c.id for c in visible] == [*expected, moved.id]
        assert visible[-1].start_ms == 5501 and visible[-1].end_ms == 5510
    finally:
        timeline.close()
