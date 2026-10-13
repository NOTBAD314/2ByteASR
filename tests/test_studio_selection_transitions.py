import copy
import math
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,VideoClip,VideoTrack,AudioClip,AudioTrack,save_project,load_project
from twobyteasr.studio_edit_sequence import sequence_of
from twobyteasr.studio_media_pool import sync_linked_av_contract,active_video_clips
from twobyteasr.studio_selection import forward_selection,move_selection_command,delete_selection_command
from twobyteasr.studio_transitions import set_transition,transition_windows,transition_gain,reconcile_transitions
from twobyteasr.studio_timeline import WaveformTimeline

@pytest.fixture(scope='module',autouse=True)
def app():
    yield QApplication.instance() or QApplication([])

def project():
    p=SubtitleProject(media=StudioMedia(path='test.mp4',duration_ms=30000,width=320,height=180),
        cues=[StudioCue('c1',1000,1500,'字幕一',speaker_id='S1'),StudioCue('c2',15000,15500,'字幕二',speaker_id='S1')])
    p.validate();p.video_tracks[0].locked=True;p.video_tracks[0].enabled=False;sequence_of(p).video_track_locked=True
    asset=p.media_pool[0];asset.offline=False
    p.video_tracks.append(VideoTrack('V2','剪辑',clips=[VideoClip('v2a',asset.asset_id,3000,7000,1000,5000),VideoClip('v2b',asset.asset_id,7000,11000,5000,9000),VideoClip('v2c',asset.asset_id,15000,18000,15000,18000)],z_index=1))
    sync_linked_av_contract(p)
    return p

def test_forward_all_offscreen_locked_and_shift():
    p=project();s=forward_selection(p,1200)
    assert s.video_ids=={'v2a','v2b','v2c'} and s.cue_ids=={'c1','c2'}
    assert len(s.audio_ids)==3 and p.video_tracks[0].clips[0].id not in s.video_ids
    one=forward_selection(p,1200,lane=('subtitle','S1'))
    assert one.cue_ids=={'c1','c2'} and not one.video_ids and not one.audio_ids
    single=forward_selection(p,1200,lane=('video','V2'))
    assert single.video_ids=={'v2a','v2b','v2c'} and not single.cue_ids
    muted=next(t for t in p.audio_tracks if t.linked_video_track_id=='V2');muted.muted=True
    assert forward_selection(p,1200).audio_ids==s.audio_ids

def test_rigid_group_move_single_undo_reopen(tmp_path):
    p=project();v1=copy.deepcopy(p.video_tracks[0]);s=forward_selection(p,1000)
    before=copy.deepcopy(p.to_dict());command=move_selection_command(p,s,2500);command.redo()
    assert [c.timeline_in_ms for c in p.video_tracks[1].clips]==[3500,7500,17500]
    assert [c.start_ms for c in p.cues]==[3500,17500]
    assert p.video_tracks[0]==v1
    assert [c.timeline_in_ms for c in next(t for t in p.audio_tracks if t.linked_video_track_id=='V2').clips]==[3500,7500,17500]
    saved=load_project(save_project(p,tmp_path/'moved.2byteproj'));assert saved.cues==p.cues
    command.undo();assert p.to_dict()==before
    command.redo();assert [c.start_ms for c in p.cues]==[3500,17500]

def test_transition_real_windows_repeat_and_persistence(tmp_path):
    p=project();item=set_transition(p,'video','V2','v2a','v2b',duration_ms=1000)
    original=[(c.timeline_in_ms,c.timeline_out_ms) for c in p.video_tracks[1].clips]
    again=set_transition(p,'video','V2','v2a','v2b',duration_ms=600)
    assert again['id']==item['id'] and len(p.studio_state['clip_transitions'])==1
    windows=transition_windows(p,'video');assert windows['v2a']['source_out_ms']==7300 and windows['v2b']['source_in_ms']==6700
    assert [c.id for t,c in active_video_clips(p,4900)]==['v2a','v2b']
    assert transition_gain(windows['v2b']['envelopes'],5000)==pytest.approx(.5)
    assert original==[(c.timeline_in_ms,c.timeline_out_ms) for c in p.video_tracks[1].clips]
    saved=load_project(save_project(p,tmp_path/'transition.2byteproj'));assert saved.studio_state['clip_transitions']==p.studio_state['clip_transitions']
    p.video_tracks[1].clips=[c for c in p.video_tracks[1].clips if c.id!='v2b'];assert not reconcile_transitions(p)

def test_audio_equal_power_and_single_fades():
    p=project();a=next(t for t in p.audio_tracks if t.linked_video_track_id=='V2');left,right=a.clips[:2]
    set_transition(p,'audio',a.id,left.id,right.id,duration_ms=1000)
    w=transition_windows(p,'audio')
    for t in (4500,4700,5000,5200,5499):
        l=transition_gain(w[left.id]['envelopes'],t);r=transition_gain(w[right.id]['envelopes'],t)
        assert l*l+r*r==pytest.approx(1.)
    set_transition(p,'video','V2',right_clip_id='v2a',edge='in',duration_ms=99999)
    assert transition_windows(p,'video')['v2a']['envelopes'][0]['end_ms']==5000
    assert p.cues[1].start_ms==15000

def test_short_handles_constrain_or_prompt():
    p=project();p.video_tracks[1].clips[1].source_in_ms=20;p.video_tracks[1].clips[1].source_out_ms=4020
    item=set_transition(p,'video','V2','v2a','v2b',duration_ms=1000);assert item['duration_ms']==40
    p.video_tracks[1].clips[1].source_in_ms=0;p.video_tracks[1].clips[1].source_out_ms=4000
    with pytest.raises(ValueError,match='余量不足'):set_transition(p,'video','V2','v2a','v2b')

def test_real_qt_forward_and_marquee_match_move(app):
    p=project();t=WaveformTimeline();t.thumbnail_requests_enabled=False;t.resize(1200,500);t.set_project(p);t.set_visible_window(0,10000);t.show();app.processEvents()
    t.set_tool_mode('track_forward');x=round(t._time_to_x(2000));row=t._video_track_rect('V2')
    point=QPoint(x,round(row.center().y()));QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,point)
    assert t.selected_segment_ids=={'v2a','v2b','v2c'} and t.selected_ids=={'c1','c2'}
    QTest.mouseClick(t,Qt.LeftButton,Qt.ShiftModifier,point);assert t.selected_segment_ids=={'v2a','v2b','v2c'} and not t.selected_ids and not t.selected_audio_clip_ids
    t.set_tool_mode('selection')
    empty=QPoint(round(t._time_to_x(9300)),round(t._track_layout()[0]['S1'].center().y()))
    end=QPoint(round(t._time_to_x(800)),round(row.top()+8))
    QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,empty);QTest.mouseMove(t,end)
    during=t.clip_selection();assert during.video_ids=={'v2a','v2b'} and during.cue_ids=={'c1'}
    assert t.grab().save('tmp/studio-workflow-20261004/selection-marquee.png')
    QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,end);assert t.clip_selection()==during
    emitted=[];t.group_move_committed.connect(lambda s,d:emitted.append((s,d)))
    point=QPoint(round(t._time_to_x(2000)),round(row.center().y()));QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,point)
    QTest.mouseMove(t,point+QPoint(50,0));QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,point+QPoint(50,0))
    assert len(emitted)==1 and emitted[0][0]==during
    t.close();t.deleteLater();app.processEvents()


def test_transitions_follow_razor_terminals_and_group_move():
    from twobyteasr.studio_clip_edit import clip_edit_command
    p=project()
    seam=set_transition(p,'video','V2','v2a','v2b',duration_ms=600)
    tail=set_transition(p,'video','V2','v2b',edge='out',duration_ms=600)
    clip_edit_command(p,'V2','split',clip_id='v2a',time_ms=3000).redo()
    clip_edit_command(p,'V2','split',clip_id='v2b',time_ms=7000).redo()
    records={t['id']:t for t in p.studio_state['clip_transitions']}
    left=next(c for c in p.video_tracks[1].clips if c.timeline_out_ms==5000)
    right=next(c for c in p.video_tracks[1].clips if c.timeline_out_ms==9000)
    assert records[seam['id']]['left_clip_id']==left.id
    assert records[tail['id']]['left_clip_id']==right.id
    selection=forward_selection(p,1000)
    move_selection_command(p,selection,2000).redo()
    records={t['id']:t for t in p.studio_state['clip_transitions']}
    assert records[seam['id']]['start_ms']==6700
    assert records[tail['id']]['end_ms']==11000


def test_duplicate_clip_id_windows_remain_track_scoped():
    p=project();p.video_tracks.append(copy.deepcopy(p.video_tracks[1]));p.video_tracks[-1].id='V3'
    item=set_transition(p,'video','V2','v2a','v2b',duration_ms=600)
    w=transition_windows(p,'video')
    assert ('V2','v2b') in w and 'v2b' not in w and ('V3','v2b') not in w


def test_unified_delete_preserves_unselected_caption_and_locked_v1():
    from twobyteasr.studio_selection import ClipSelection
    p=project();original=copy.deepcopy(p.video_tracks[0])
    command=delete_selection_command(p,ClipSelection(video_ids={'v2a'},cue_ids={'c1'}));command.redo()
    assert p.video_tracks[0]==original and [c.id for c in p.cues]==['c2']
    assert [c.id for c in p.video_tracks[1].clips]==['v2b','v2c']
    command.undo();assert [c.id for c in p.cues]==['c1','c2']


def test_selection_cancel_linked_and_new_project_reset(app):
    from twobyteasr.studio_selection import ClipSelection,expand_linked_selection,remove_linked_selection
    p=project();s=expand_linked_selection(p,ClipSelection(video_ids={'v2a'},cue_ids={'c1'}))
    assert len(s.audio_ids)==1
    remove_linked_selection(p,s,'audio',next(iter(s.audio_ids)))
    assert not s.video_ids and not s.audio_ids and s.cue_ids=={'c1'}
    timeline=WaveformTimeline();timeline.set_project(p);timeline._publish_clip_selection(s)
    timeline.set_project(project());assert not timeline._unified_selection and timeline.clip_selection().count==0
    timeline.close();timeline.deleteLater();app.processEvents()


def test_shortcut_existing_conflicts_empty_and_input_guard(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    import twobyteasr.studio_ui as ui
    from twobyteasr.i18n import translate
    path=tmp_path/'studio-settings.json'
    path.write_text(json.dumps({'shortcuts':{'save':'Ctrl+D','play_pause':'A','undo':'Ctrl+Shift+D','selection_tool':''}}),'utf8')
    monkeypatch.setattr(ui,'studio_settings_path',lambda:path)
    # 2026-10-13: Studio reads its keys through the shared shortcut registry.
    import twobyteasr.shortcut_registry as registry
    monkeypatch.setattr(registry,'settings_path',lambda:path)
    dummy=SimpleNamespace();loaded=ui.SubtitleStudioPage._load_shortcut_values(dummy)
    assert loaded['save']=='Ctrl+D' and loaded['play_pause']=='A' and loaded['selection_tool']==''
    assert all(loaded[key]=='' for key in ('track_forward_tool','video_transition','audio_transition'))
    assert len(dummy._new_shortcut_conflicts)==3
    dummy._editing_has_focus=lambda:True
    assert not ui.SubtitleStudioPage._dispatch_shortcut_sequence(dummy,'A')
    dummy._editing_has_focus=lambda:False;dummy._studio_ime_composing=True
    assert not ui.SubtitleStudioPage._dispatch_shortcut_sequence(dummy,'Ctrl+D')
    for label in ('轨道向前选择','应用默认视频转场','应用默认音频转场','转场','恒定功率交叉淡化'):
        assert translate(label,'en')!=label and translate(label,'ja')!=label


def test_toolbar_wraps_without_overlap_and_narrow_highlight(app):
    from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel
    from PySide6.QtCore import QRectF
    from types import SimpleNamespace
    from twobyteasr.studio_toolbar_layout import install_command_groups
    host=QWidget();outer=QVBoxLayout(host);old=QHBoxLayout();outer.addLayout(old);widgets=[]
    for i in range(18):
        w=QPushButton('Timeline control '+str(i));old.addWidget(w);widgets.append(w)
    timecode=QLineEdit('00:00:00.000');timecode.setFixedWidth(128);old.insertWidget(8,timecode)
    host.resize(800,300);host.show();app.processEvents()
    dummy=SimpleNamespace();install_command_groups(dummy,outer,old,widgets[6],widgets[12]);app.processEvents()
    for group in dummy._timeline_command_groups:
        assert all(w.isVisible() for w in group)
        for left,right in zip(group,group[1:]):
            l=QRectF(left.mapTo(dummy._timeline_command_bar,left.rect().topLeft()),left.size())
            r=QRectF(right.mapTo(dummy._timeline_command_bar,right.rect().topLeft()),right.size())
            assert not l.intersects(r)
    assert timecode.width()==128
    assert WaveformTimeline._selection_highlight_rect(QRectF(20,20,.3,30)).width()>=2
    host.close();host.deleteLater();app.processEvents()


def test_normal_overlap_still_uses_topmost_without_transition():
    p=project();p.video_tracks[1].clips.append(VideoClip('overlap',p.media_pool[0].asset_id,1000,2000,2000,3000))
    assert [c.id for _,c in active_video_clips(p,2300)]==['overlap']


def test_escape_cancels_group_before_shortcut_dispatch_and_preserves_forward_cursor(app):
    from types import SimpleNamespace
    from twobyteasr.studio_ui import SubtitleStudioPage
    t=WaveformTimeline();t.resize(1200,500);t.set_project(project());t.set_visible_window(0,10000);t.show();app.processEvents()
    t.set_tool_mode('track_forward');row=t._video_track_rect('V2');point=QPoint(round(t._time_to_x(2000)),round(row.center().y()))
    state=[];commits=[];t.interaction_changed.connect(state.append);t.group_move_committed.connect(lambda *_:commits.append(True))
    QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,point);QTest.mouseMove(t,point+QPoint(35,0))
    dummy=SimpleNamespace(timeline=t,_editing_has_focus=lambda:False)
    assert SubtitleStudioPage._dispatch_shortcut_sequence(dummy,'Esc')
    QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,point+QPoint(35,0))
    assert t._group_drag is None and not commits and state[-1] is False
    assert t.tool_mode=='track_forward' and not t.cursor().pixmap().isNull()
    t.close();t.deleteLater();app.processEvents()
