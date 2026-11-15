"""The 动效 stage timeline (2026-11-15, the user's pick A)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _app():
    return QApplication.instance() or QApplication([])

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_motion_workflow_ui import make_page, close
from twobyteasr.caption_style.motion_timeline_ui import MotionTimeline, MIN_SEGMENT


def test_timeline_segments_follow_durations_and_keep_the_stage_bar_surface(tmp_path):
    app, page = make_page(tmp_path)
    try:
        inspector = page.motion_inspector
        timeline = inspector.tabs
        assert isinstance(timeline, MotionTimeline) and timeline.count() == 4
        timeline.resize(400, timeline.height())
        inspector.choose('entry', 'char_wave')
        inspector.choose('exit', 'push_out')
        assert timeline.buttons[0].value_text == '波浪弹入' and timeline.buttons[1].value_text == '冲刺离场'
        assert timeline.durations == {'entry': page.effect_duration.value(), 'exit': page.effect_out_duration.value()}
        first, middle, last = timeline.widths(400)
        assert first >= MIN_SEGMENT and last >= MIN_SEGMENT and first+middle+last == 400-6
        long_first = timeline.widths(400)[0]
        page.effect_duration.setValue(1600); inspector.sync()
        assert timeline.widths(400)[0] > long_first
        inspector.choose('exit', 'none')
        assert timeline.durations['exit'] == 0 and not timeline.grips['exit'].isVisibleTo(timeline)
        timeline.setCurrentIndex(3)
        assert inspector.stages[inspector.tabs.currentIndex()] == 'words'
    finally:
        close(page)


@pytest.mark.parametrize('width', [360, 400, 440])
def test_durations_and_names_are_never_cut_in_a_normal_panel(width):
    """2026-11-15: 「入场 · 0.62s」 showed as 「入场 · 0.…」 in the user's ~400 px panel."""
    from PySide6.QtGui import QFontMetrics
    from twobyteasr.caption_style.motion_timeline_ui import TEXT_PADDING
    timeline = MotionTimeline()
    timeline.resize(width, timeline.height())
    timeline.segment('entry').set_value('放大', True)
    timeline.segment('exit').set_value('冲刺离场', True)
    timeline.segment('loop').set_value('无', False)
    timeline.set_durations(620, 380)
    for stage in ('entry', 'loop', 'exit'):
        segment = timeline.segment(stage)
        title_font, value_font = segment.fonts()
        inner = segment.width()-TEXT_PADDING+4          # the painted text box (9 px inset each side)
        assert QFontMetrics(title_font).horizontalAdvance(segment.title_line()) <= inner, (stage, width)
        assert QFontMetrics(value_font).horizontalAdvance(segment.value_text) <= inner, (stage, width)
    assert sum(timeline.widths(width)) == width-6


def test_the_parameter_card_wraps_instead_of_widening_a_narrow_panel(tmp_path):
    """2026-11-15: strength + four arrows made the card ~362 px and clipped a ~360 px panel."""
    app, page = make_page(tmp_path)
    try:
        inspector = page.motion_inspector
        inspector.tabs.setCurrentIndex(1)
        inspector.choose('exit', 'push_out')                     # a preset with directions
        assert not inspector.direction_group.isHidden()
        assert inspector.params_card.minimumSizeHint().width() <= 260
        inspector.choose('exit', 'soft_fade')                    # no direction: the group goes away
        assert inspector.direction_group.isHidden()
    finally:
        close(page)


def test_a_too_narrow_segment_keeps_the_seconds():
    timeline = MotionTimeline()
    segment = timeline.segment('entry')
    segment.set_value('放大', True); segment.duration_ms = 620
    assert segment.title_lines() == ['入场 · 0.62s', '入场 0.62s', '0.62s']


def test_dragging_the_entry_handle_is_one_undoable_duration_edit(tmp_path):
    app, page = make_page(tmp_path)
    try:
        inspector = page.motion_inspector
        timeline = inspector.tabs
        page.show(); timeline.resize(400, timeline.height()); timeline.relayout()
        inspector.choose('entry', 'zoom_in')
        timeline.setCurrentIndex(2)
        start = page.effect_duration.value()
        depth = page.undo_stack.count()
        grip = timeline.grips['entry']
        centre = grip.rect().center()
        QTest.mousePress(grip, Qt.LeftButton, pos=centre)
        for dx in (10, 25, 40):
            QTest.mouseMove(grip, centre + QPoint(dx, 0))
        QTest.mouseRelease(grip, Qt.LeftButton, pos=centre + QPoint(40, 0))
        assert inspector.stages[timeline.currentIndex()] == 'entry'
        # The handle follows the drag (it moves with the widening segment), so
        # synthetic moves relative to it overshoot a little; rightwards lengthens.
        dragged = page.effect_duration.value()
        assert dragged > start + 200 and dragged % 10 == 0
        effect = page.project.effects[page.project.cues[0].effect_id]
        assert effect['entry']['duration'] == dragged and timeline.durations['entry'] == dragged
        assert page.undo_stack.count() == depth + 1
        page.undo_stack.undo()
        assert page.project.effects.get(page.project.cues[0].effect_id, {}).get('entry', {}).get('duration') != dragged
    finally:
        close(page)


def test_playhead_walks_entry_reading_and_exit(tmp_path):
    timeline = MotionTimeline()
    timeline.resize(400, timeline.height())
    timeline.set_durations(400, 400)
    spans = timeline._spans
    timeline.set_time(200, 3000, (400, 400))
    assert spans['entry'][0] < timeline.playhead.x < spans['entry'][0] + spans['entry'][1]
    timeline.set_time(1500, 3000, (400, 400))
    assert spans['loop'][0] < timeline.playhead.x < spans['loop'][0] + spans['loop'][1]
    assert 0 < timeline.segment('words').lit < 1
    timeline.set_time(2900, 3000, (400, 400))
    assert spans['exit'][0] < timeline.playhead.x <= spans['exit'][0] + spans['exit'][1]
