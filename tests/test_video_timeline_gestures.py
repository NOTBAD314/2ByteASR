"""Logical-pixel hit testing, exact snap targets, and stale gap selection."""
import copy
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.selection_scope import SelectionScope
from tests.test_studio_clip_edit import project,add_v2,clip,edit


@pytest.fixture
def timeline():
    app=QApplication.instance() or QApplication([])
    p=project();add_v2(p)
    t=WaveformTimeline();t.resize(1200,650);t.set_project(p)
    t.set_visible_window(0,60000);t.show();app.processEvents()
    yield t
    t.close();t.deleteLater();app.processEvents()


def drag_state(t,lane='V2',mode='move'):
    c=clip(t.project,lane)
    return dict(track_id=lane,clip_id=c.id,mode=mode,origin_in=c.timeline_in_ms,
        origin_out=c.timeline_out_ms,min_in=0,max_out=100000,group_intervals={})


@pytest.mark.parametrize('view,zoom',[(0,60000),(8000,30000),(11000,10000)])
def test_video_snap_cross_track_exact_with_scroll_zoom(timeline,view,zoom):
    t=timeline
    edit(t.project,'V1','trim',start=0,end=12347)
    t.set_visible_window(view,zoom);t.set_playhead(35000)
    drag=drag_state(t)
    threshold=8*t.visible_duration_ms/(t._content_right()-t.TRACK_HEADER_WIDTH)
    start=12347+int(threshold*.7)
    a,b=t._snap_video_interval(start,start+5000,drag)
    assert (a,b)==(12347,17347)
    assert t._snap_target['time']==12347
    t.set_snap_enabled(False)
    assert t._snap_video_interval(start,start+5000,drag)==(start,start+5000)


def test_self_clip_audio_and_identity_caption_excluded(timeline):
    t=timeline;t.set_playhead(50000)
    t.project.cues[0].start_ms=1000;t.project.cues[0].end_ms=2000
    t.reindex_project()
    d=drag_state(t,'V1')
    assert t._snap_video_interval(950,3600950,d)==(950,3600950)
    d=drag_state(t)
    # Old 5000ms video/audio start may not attract its own move.
    assert t._snap_video_interval(5050,65050,d)==(5050,65050)


def test_precise_video_right_edge_hit(timeline):
    t=timeline;t.set_visible_window(0,90000)
    c=clip(t.project,'V2')
    point=QPoint(round(t._time_to_x(c.timeline_out_ms)),round(t._video_track_rect('V2').center().y()))
    QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,point)
    assert t._clip_drag and t._clip_drag['mode']=='trim_right'
    QTest.keyClick(t,Qt.Key_Escape)
    assert t._clip_drag is None


def test_narrow_clip_right_edge_uses_nearest_handle(timeline):
    from types import SimpleNamespace
    from PySide6.QtCore import QPointF
    t=timeline
    edit(t.project,'V2','trim',start=5000,end=5200)
    c=clip(t.project,'V2')
    t._begin_video_drag('V2',c,SimpleNamespace(position=lambda:QPointF(t._time_to_x(5200),100)))
    assert t._clip_drag['mode']=='trim_right'


@pytest.mark.parametrize('change',['scope','ids','tool','cue'])
def test_selection_clears_old_gap(timeline,change):
    t=timeline;t.selected_gap=('V2',0,5000)
    if change=='scope':t.set_selection_scope(SelectionScope.empty())
    elif change=='ids':t.set_selected_ids([])
    elif change=='tool':t.set_tool_mode('razor')
    else:t.set_selected('cross')
    assert t.selected_gap is None


def test_linked_selection_one_delta_and_one_commit(timeline):
    p=timeline.project
    edit(p,'V1','trim',start=0,end=20000)
    edit(p,'V1','split',time_ms=10000)
    ids={c.id for c in p.video_tracks[0].clips}
    c=edit(p,'V1','move',start=5000,clip_ids=ids)
    assert [(x.timeline_in_ms,x.timeline_out_ms) for x in p.video_tracks[0].clips]==[(5000,15000),(15000,25000)]
    c.undo()
    assert clip(p).timeline_in_ms==0
