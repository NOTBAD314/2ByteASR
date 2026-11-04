import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.studio.studio_timeline import WaveformTimeline


@pytest.fixture
def timeline():
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia('missing.mp4',duration_ms=100000),cues=[StudioCue('a',1000,2000,'甲')]);p.validate()
    t=WaveformTimeline();t.resize(1200,650);t.set_project(p);t.set_visible_window(0,30000)
    yield t
    t.close();t.deleteLater();app.processEvents()


@pytest.mark.parametrize('zoom',[5000,30000,60000])
def test_overflow_left_aligned_and_holds_until_next_page(timeline,zoom):
    t=timeline;t.set_visible_window(0,zoom);duration=t._duration_ms();t.set_selected('a')
    assert not t.page_playhead(zoom//2) and t.visible_start_ms==0
    for point in (zoom+200,min(99999,zoom*2+400),99999):
        t.page_playhead(point)
        if point==99999 or point>=zoom+200:
            assert t._time_to_x(point)>=t.TRACK_HEADER_WIDTH
        assert t.horizontal_scrollbar.value()==t.visible_start_ms
        before=t.visible_start_ms
        assert not t.page_playhead(point) and t.visible_start_ms==before
    t.page_playhead(100000)
    t.page_playhead(500)
    assert t.visible_start_ms==500 and t._time_to_x(500)==t.TRACK_HEADER_WIDTH
    assert t._duration_ms()==duration and t.selected_id=='a'


def test_tail_keeps_scrollbar_and_project_duration_separate(timeline):
    t=timeline;t.page_playhead(99000)
    assert t.visible_start_ms==99000 and t.horizontal_scrollbar.value()==99000
    assert t._duration_ms()==100000 and t.visible_start_ms+t.visible_duration_ms==129000
    t._sync_scrollbars();assert t.horizontal_scrollbar.value()==99000


def test_drag_owns_viewport_and_continuous_follow_differs(timeline):
    t=timeline;t.horizontal_scrollbar.setSliderDown(True)
    assert not t.page_playhead(31000) and t.visible_start_ms==0
    t.horizontal_scrollbar.setSliderDown(False);t._follow_suspended_until=0
    assert t.page_playhead(31000) and t.visible_start_ms==31000
    assert not t.page_playhead(35000) and t.visible_start_ms==31000
    t.follow_playing_playhead(35000);assert t.visible_start_ms==24500
