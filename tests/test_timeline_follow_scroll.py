"""2026-10-22 user report: playback follow redrew the whole timeline every frame.

While playback follows, the static picture is drawn wider than the view and
later frames shift it; the selection that follows the playing caption no longer
forces a redraw at each caption start.
"""
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.selection_scope import SelectionScope

APP = QApplication.instance() or QApplication([])


def make_timeline():
    timeline = WaveformTimeline()
    timeline.resize(1200, 360)
    cues = [StudioCue(f'c{index}', index * 2000, index * 2000 + 1500, f'字幕{index}', 's') for index in range(60)]
    project = SubtitleProject(media=StudioMedia('follow.mp4', duration_ms=120_000),
                              speakers=[StudioSpeaker('s')], cues=cues)
    timeline.set_project(project)
    timeline.set_visible_window(0, 20_000)
    timeline.show(); APP.processEvents()
    timeline._thumbnails.paused = True  # the filmstrip is told "paused" while playback runs
    return timeline


def full_redraws(timeline):
    calls = []
    original = timeline._paint_timeline_contents
    timeline._paint_timeline_contents = lambda *args, **kwargs: (calls.append(timeline.visible_start_ms), original(*args, **kwargs))[1]
    return calls


def test_follow_shifts_the_cached_picture_until_the_overscan_runs_out():
    timeline = make_timeline()
    try:
        calls = full_redraws(timeline)
        assert timeline.follow_playing_playhead(8_000)
        APP.processEvents(); timeline.grab()
        assert len(calls) == 1  # the first follow draws the wider picture
        view = timeline._static_timeline_cache[3]
        assert view[3] == round((timeline._content_right() - timeline.TRACK_HEADER_WIDTH) * timeline.FOLLOW_OVERSCAN)
        for step in range(1, 40):
            timeline.follow_playing_playhead(8_000 + step * 100)
            APP.processEvents(); timeline.grab()
        # 3.9 s of a 20 s view at 60% overscan: never redrawn.
        assert len(calls) == 1
        assert timeline._last_paint_stats['static_cache_hit']
        assert timeline._last_paint_stats['static_shift_px'] > 0
        timeline.follow_playing_playhead(8_000 + 13_000)  # past the drawn 12 s
        APP.processEvents(); timeline.grab()
        assert len(calls) == 2
        # Any real change still redraws.
        timeline.update(); APP.processEvents(); timeline.grab()
        assert len(calls) == 3
    finally:
        timeline.close()


def test_shifted_picture_matches_a_fresh_drawing():
    timeline = make_timeline()
    try:
        timeline.follow_playing_playhead(8_000)
        APP.processEvents(); timeline.grab()
        timeline.follow_playing_playhead(10_300)
        APP.processEvents()
        shifted = timeline.grab().toImage()
        assert timeline._last_paint_stats['static_cache_hit']
        assert timeline._last_paint_stats['static_shift_px'] > 0
        calls = full_redraws(timeline)
        timeline._follow_active_until = 0.0
        timeline.update()
        fresh = timeline.grab().toImage()
        assert calls and timeline._static_timeline_cache[3][3] == 0  # a plain, exact drawing
        # Whole-pixel rounding moves an edge by at most one pixel. The clips cut
        # by the view's left and right edges are drawn differently on purpose
        # (the wider picture has no cut at the old right edge).
        left = timeline.TRACK_HEADER_WIDTH + 40
        right = timeline._content_right() - 80
        # Text and rounded corners anti-alias differently at a sub-pixel offset;
        # misplaced content would differ by whole colours over large areas.
        import numpy as np
        def pixels(image):
            image = image.convertToFormat(image.Format.Format_RGB32)
            return np.ndarray((image.height(), image.width(), 4), np.uint8, image.constBits(),
                              strides=(image.bytesPerLine(), 4, 1))[:, left:right, :3].astype(int)
        difference = np.abs(pixels(shifted) - pixels(fresh))
        assert difference.mean() < 1.0, difference.mean()
        assert (difference.max(axis=2) > 64).mean() < 0.01
    finally:
        timeline.close()


def test_selection_that_follows_the_playing_caption_does_not_redraw():
    timeline = make_timeline()
    try:
        calls = full_redraws(timeline)
        timeline.set_clock_selection_scope(SelectionScope.explicit(('c3',), 'c3'))
        timeline.follow_playing_playhead(8_000)
        APP.processEvents(); timeline.grab()
        drawn = len(calls)
        assert timeline._static_timeline_cache[3][4]  # drawn without the clock selection
        for index in range(4, 9):
            timeline.set_clock_selection_scope(SelectionScope.explicit((f'c{index}',), f'c{index}'))
            timeline.follow_playing_playhead(index * 2000 + 1000)
            APP.processEvents(); timeline.grab()
        assert len(calls) == drawn
        assert timeline.selected_id == 'c8'
        # A user selection redraws with the normal selected look.
        timeline.set_selection_scope(SelectionScope.explicit(('c8',), 'c8'))
        APP.processEvents(); timeline.grab()
        assert len(calls) == drawn + 1 and not timeline._static_timeline_cache[3][4]
        # Pausing (follow over) redraws the clock selection normally too.
        timeline.set_clock_selection_scope(SelectionScope.explicit(('c9',), 'c9'))
        timeline._thumbnails.paused = False
        APP.processEvents(); timeline.grab()
        assert not timeline._static_timeline_cache[3][4]
    finally:
        timeline.close()


def test_clock_selection_reuses_static_picture_when_follow_is_disabled():
    timeline = make_timeline()
    try:
        timeline._follow_active_until = 0.0
        calls = full_redraws(timeline)
        timeline.set_clock_selection_scope(SelectionScope.explicit(('c3',), 'c3'))
        APP.processEvents(); timeline.grab()
        assert timeline._static_timeline_cache[3][4]
        drawn = len(calls)
        for index in range(4, 9):
            timeline.set_clock_selection_scope(SelectionScope.explicit((f'c{index}',), f'c{index}'))
            APP.processEvents(); timeline.grab()
        assert len(calls) == drawn and timeline.selected_id == 'c8'
        timeline._thumbnails.paused = False
        timeline.playback_selection_state_changed()
        APP.processEvents(); timeline.grab()
        assert len(calls) == drawn + 1 and not timeline._static_timeline_cache[3][4]
        timeline.set_selection_scope(SelectionScope.explicit(('c7',), 'c7'))
        APP.processEvents(); timeline.grab()
        assert timeline.selected_id == 'c7' and not timeline._static_timeline_cache[3][4]
    finally:
        timeline.close()
