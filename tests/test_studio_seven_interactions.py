import copy
import pytest
from PySide6.QtCore import Qt, QPoint, QEvent, QPointF
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.timeline.studio_commands import EditCueIntervalsCommand
from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, sync_caption_interval_words
from twobyteasr.timeline.studio_selection import forward_selection
from twobyteasr.timeline.studio_group_snap import snap_group_delta


@pytest.fixture
def timeline():
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia(path='fixture.mp4',duration_ms=10000), cues=[
        StudioCue('a',1000,3000,'甲完整句',speaker_id='S00'),
        StudioCue('b',3000,5000,'乙完整句',speaker_id='S00'),
        StudioCue('c',6000,7000,'第三条',speaker_id='S00')])
    p.validate();ensure_independent_captions(p)
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    p.video_tracks[0].locked=False;sequence_of(p).video_track_locked=False
    t=WaveformTimeline();t.resize(1200,650);t.set_project(p);t.set_visible_window(0,10000)
    t.show();app.processEvents()
    yield t
    t.close();t.deleteLater();app.processEvents()


def pointer(t,kind,p,mods=Qt.NoModifier):
    event=QMouseEvent(kind,QPointF(p),t.mapToGlobal(p),Qt.LeftButton if kind!=QEvent.MouseMove else Qt.NoButton,
        Qt.LeftButton if kind!=QEvent.MouseButtonRelease else Qt.NoButton,mods)
    QApplication.sendEvent(t,event)


@pytest.mark.parametrize('delta,gap,cancel',[(35,0,False),(-35,0,False),(25,200,False),(1000,0,False),(25,0,True)])
def test_real_ctrl_seam_is_atomic_and_bounded(timeline,delta,gap,cancel):
    t=timeline;p=t.project;p.cues[0].end_ms-=gap//2;p.cues[1].start_ms+=gap//2;t.reindex_project()
    original=copy.deepcopy(p.cues);media=copy.deepcopy(p.video_tracks)
    stack=QUndoStack();t.timing_edit_committed.connect(lambda changes:stack.push(EditCueIntervalsCommand(p,changes)))
    y=round(t._track_layout()[0]['S00'].center().y());a=QPoint(round(t._time_to_x(3000)),y);b=QPoint(a.x()+delta,y)
    QTest.keyPress(t,Qt.Key_Control)
    pointer(t,QEvent.MouseButtonPress,a,Qt.ControlModifier)
    assert t._drag[1]=='roll'
    pointer(t,QEvent.MouseMove,b,Qt.ControlModifier);t._flush_timing_preview()
    assert p.cues==original
    if cancel:QTest.keyClick(t,Qt.Key_Escape)
    pointer(t,QEvent.MouseButtonRelease,b,Qt.ControlModifier);QTest.keyRelease(t,Qt.Key_Control)
    if cancel:
        assert p.cues==original and stack.count()==0
    else:
        assert p.cues[0].end_ms==p.cues[1].start_ms
        assert 1050<=p.cues[0].end_ms<=4950
        assert p.cues[0].start_ms==1000 and p.cues[1].end_ms==5000 and p.cues[2]==original[2]
        assert stack.count()==1
        after=copy.deepcopy(p.cues);stack.undo();assert p.cues==original
        stack.redo();assert p.cues==after
    assert p.video_tracks==media and t._drag is None


def test_ctrl_pressed_after_seam_does_not_commit_without_pointer_change(timeline):
    t=timeline;p=t.project;before=copy.deepcopy(p.cues);committed=[]
    t.timing_edit_committed.connect(committed.append)
    a=QPoint(round(t._time_to_x(3000)),round(t._track_layout()[0]['S00'].center().y()))
    QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,a);QTest.keyPress(t,Qt.Key_Control)
    assert t._drag[1]=='roll'
    QTest.keyRelease(t,Qt.Key_Control);QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,a)
    assert p.cues==before and not committed


def test_ctrl_after_single_edge_motion_retains_visible_preview(timeline):
    t=timeline;t.snap_enabled=False
    a=QPoint(round(t._time_to_x(3000)),round(t._track_layout()[0]['S00'].center().y()))
    pointer(t,QEvent.MouseButtonPress,a)
    b=QPoint(a.x()+24,a.y());pointer(t,QEvent.MouseMove,b);t._flush_timing_preview()
    previous=copy.deepcopy(t._timing_preview)
    QTest.keyPress(t,Qt.Key_Control)
    assert all(t._timing_preview[key]==value for key,value in previous.items())
    pointer(t,QEvent.MouseMove,QPoint(b.x()+5,b.y()),Qt.ControlModifier);t._flush_timing_preview()
    assert t._timing_preview['a'].end_ms==t._timing_preview['b'].start_ms
    QTest.keyClick(t,Qt.Key_Escape);QTest.keyRelease(t,Qt.Key_Control)


def test_ctrl_body_toggles_selection_without_duration_edit(timeline):
    t=timeline;before=copy.deepcopy(t.project.cues)
    y=round(t._track_layout()[0]['S00'].center().y())
    for time in (2000,4000):
        QTest.mouseClick(t,Qt.LeftButton,Qt.ControlModifier,QPoint(round(t._time_to_x(time)),y))
    assert t.clip_selection().cue_ids=={'a','b'}
    QTest.mouseClick(t,Qt.LeftButton,Qt.ControlModifier,QPoint(round(t._time_to_x(2000)),y))
    assert t.clip_selection().cue_ids=={'b'} and t.project.cues==before


@pytest.mark.parametrize('threshold',[8,40,120])
def test_group_snap_uses_one_delta_and_excludes_all_selected_edges(timeline,threshold):
    p=timeline.project;selection=forward_selection(p,0)
    delta,guide=snap_group_delta(p,selection,1000+threshold//2,playhead=1000,threshold=threshold)
    assert delta==1000 and guide['time']==1000
    delta,guide=snap_group_delta(p,selection,500+threshold//2,playhead=9000,threshold=threshold)
    assert delta==500+threshold//2 and guide is None
    QTest.keyClick(timeline,Qt.Key_A,Qt.ControlModifier)
    assert timeline.clip_selection()==selection


def test_trim_preserves_original_words_and_move_translates_without_stretch(timeline):
    p=timeline.project;c=p.cues[0];receipt=p.studio_state['caption_timeline']['instances'][c.id]
    words=[dict(text='甲',char_start=0,char_end=1,start_ms=1000,end_ms=1200,evidence_ref='r')]
    receipt.update(words=copy.deepcopy(words),word_base_words=copy.deepcopy(words),word_base_interval=[1000,3000])
    c.start_ms=1100;c.end_ms=3400;sync_caption_interval_words(p,c,(1000,3000))
    assert receipt['words']==words and receipt['word_base_words']==words
    c.start_ms+=500;c.end_ms+=500;sync_caption_interval_words(p,c,(1100,3400))
    assert receipt['words'][0]['start_ms']==1500 and receipt['words'][0]['end_ms']==1700
    assert receipt['word_base_words']==words


def test_tiny_gap_remains_selected_after_mouse_release(timeline):
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    t=timeline;p=t.project;first=p.video_tracks[0].clips[0]
    clip_edit_command(p,'V1','split',clip_id=first.id,time_ms=3389).redo()
    right=p.video_tracks[0].clips[1]
    clip_edit_command(p,'V1','move',clip_id=right.id,start=3412).redo()
    t.reindex_project();t.set_visible_window(2000,3400)
    point=QPoint(round(t._time_to_x(3400)),round(t._video_track_rect('V1').center().y()))
    QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,point)
    assert t.selected_gap==('V1',3389,3412)
    assert t._clip_drag is None


@pytest.mark.parametrize('mode',[Qt.WindowNoState,Qt.WindowMaximized,Qt.WindowFullScreen])
def test_bounds_does_not_resize_special_state_or_lose_it_on_restore(mode):
    app=QApplication.instance() or QApplication([])
    from twobyteasr.app.window_constraints import install_window_bounds,constrain
    w=QWidget();w.resize(600,400);bounds=install_window_bounds(w)
    w.setWindowState(mode);w.show();app.processEvents();before=w.geometry()
    constrain(w);assert w.windowState()==mode
    w.showMinimized();app.processEvents()
    w.setWindowState(Qt.WindowNoState);app.processEvents()
    assert w.windowState()==mode
    if mode==Qt.WindowNoState:assert w.geometry()==before
    w.close();w.deleteLater();app.processEvents()
