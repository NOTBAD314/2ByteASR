import copy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit, QVBoxLayout, QLabel

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, AudioTrack, AudioClip, save_project, load_project
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip, set_video_track_state, audio_master_mode, audio_master_track_id
from twobyteasr.playback.audio_graph import capture_audio_graph, preview_audio_layers
from twobyteasr.timeline.studio_track_delete import DeleteTrackCommand, delete_current, delete_track
from twobyteasr.timeline.studio_media_commands import media_graph_command
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.studio.studio_timeline import WaveformTimeline


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def project(tmp_path):
    p=SubtitleProject(media=StudioMedia(str(tmp_path/'source.mp4'),duration_ms=5000,width=160,height=90),
        speakers=[StudioSpeaker('S1'),StudioSpeaker('S2'),StudioSpeaker('EMPTY')],
        cues=[StudioCue('one',0,2000,'一号字幕','S1'),StudioCue('two',0,2000,'二号字幕','S2')])
    p.validate()
    set_video_track_state(p,'V1',locked=False)
    sequence_of(p).video_track_locked=False
    a=add_media_asset(p,tmp_path/'two.mp4',duration_ms=5000,video_metadata={'has_video':True,'width':160,'height':90},audio_metadata={'has_audio':True})
    t=create_video_track(p,'第二轨');add_video_clip(p,t.id,a.asset_id,source_in_ms=200,source_out_ms=3200)
    p.audio_tracks.append(AudioTrack('AX','独立音频',[AudioClip('ax-clip',a.asset_id,0,2000,0,2000)]))
    for a in p.media_pool:a.offline=False;a.audio_metadata['has_audio']=True
    p.studio_state['speaker_track_order']=['S2','EMPTY','S1']
    return p


def audible(project):return {x['track_id'] for x in preview_audio_layers(capture_audio_graph(project),500)}


def test_default_old_auto_manual_single_multi_solo_mute_and_offline(project,app):
    assert audio_master_mode(project)=='mix_all' and audio_master_track_id(project)==''
    assert audible(project)=={'V1','V2','AX'}
    project.studio_state.update(audio_master_mode='follow_active_video',audio_master_track_id='V1',selected_video_track_id='V2')
    assert audible(project)=={'V1','V2','AX'}
    assert not any(t.soloed for t in (*project.video_tracks,*project.audio_tracks))
    project.studio_state['audio_master_mode']='manual'
    assert audible(project)=={'V1'}
    stack=QUndoStack()
    stack.push(media_graph_command(project,'Solo',lambda p:set_video_track_state(p,'V2',soloed=True)))
    assert audible(project)=={'V2'}
    project.audio_tracks[-1].soloed=True
    assert audible(project)=={'V2','AX'}
    set_video_track_state(project,'V2',muted=True)
    assert audible(project)=={'AX'}
    for asset in project.media_pool:
        if asset.asset_id==project.audio_tracks[-1].clips[0].asset_id:asset.offline=True
    assert audible(project)==set()  # Explicit offline Solo never falls back.


def test_solo_undo_restores_legacy_flags_and_does_not_restore_unrelated_playhead(project,app):
    project.studio_state['audio_solo_track_ids']=['A2']
    stack=QUndoStack();stack.push(media_graph_command(project,'Solo off',lambda p:set_video_track_state(p,'V2',soloed=False)))
    assert audible(project)=={'V1','V2','AX'}
    project.studio_state['playhead_ms']=1700
    stack.undo()
    assert audible(project)=={'V2'} and project.studio_state['playhead_ms']==1700
    stack.redo();assert audible(project)=={'V1','V2','AX'}


def test_delete_undo_restores_full_tracks_order_cues_gain_and_last_track_reopen(project,app,tmp_path):
    project.studio_state['audio_track_gain_db']={'V2':-8,'A2':-8,'AX':-3}
    set_video_track_state(project,'V2',soloed=True,muted=True)
    before=copy.deepcopy((project.video_tracks,project.audio_tracks,project.av_track_groups,project.cues,project.speakers,project.studio_state))
    stack=QUndoStack();stack.push(DeleteTrackCommand(project,'audio','A2'))
    assert {t.id for t in project.video_tracks}=={'V1'} and 'A2' not in {t.id for t in project.audio_tracks}
    stack.undo()
    assert (project.video_tracks,project.audio_tracks,project.av_track_groups,project.cues,project.speakers,project.studio_state)==before
    stack.redo();stack.push(DeleteTrackCommand(project,'video','V1'))
    assert not project.video_tracks and sequence_of(project).empty_timeline
    path=tmp_path/'deleted.2byteproj';save_project(project,path)
    restored=load_project(path)
    assert not restored.video_tracks and {t.id for t in restored.audio_tracks}=={'AX'}
    assert len(restored.cues)==2
    for speaker in list(project.speakers):stack.push(DeleteTrackCommand(project,'subtitle',speaker.id))
    assert not project.cues and not project.speakers
    save_project(project,path);assert not load_project(path).speakers
    stack.undo();assert project.speakers


def test_header_focus_text_delete_clip_selection_and_empty_track_layout(project,app,monkeypatch):
    # Real timeline mouse hit testing + Qt editing focus, without media decoder.
    window=QWidget();layout=QVBoxLayout(window);timeline=WaveformTimeline();editor=QLineEdit('abc')
    layout.addWidget(editor);layout.addWidget(timeline);window.resize(1000,750)
    timeline.set_project(project);timeline.set_waveform_visible(True)
    calls=[]
    page=SimpleNamespace(project=project,timeline=timeline,undo_stack=QUndoStack(),save_state=QLabel(),
        _editing_has_focus=lambda:editor.hasFocus(),cue_controller=SimpleNamespace(delete_current=lambda:calls.append('clip')),
        select_cue=lambda *_:None,ensure_active_subtitle_renderer=lambda **_:None)
    timeline.track_delete_requested.connect(lambda kind,tid:delete_track(page,kind,tid))
    window.show();window.activateWindow();QTest.qWait(30)
    assert timeline.speaker_ids()==['S2','EMPTY','S1']
    assert 'AX' in timeline._audio_track_rects()
    rect=timeline._track_layout()[0]['S2']
    QTest.mouseClick(timeline,Qt.MouseButton.LeftButton,pos=QPoint(75,round(rect.center().y())))
    assert timeline.selected_track_header==('subtitle','S2') and timeline.hasFocus()
    editor.setFocus();editor.setCursorPosition(0);QTest.keyClick(editor,Qt.Key.Key_Delete)
    delete_current(page)
    assert editor.text()=='bc' and len(project.speakers)==3
    timeline.setFocus();delete_current(page)
    assert {s.id for s in project.speakers}=={'EMPTY','S1'}
    page.undo_stack.undo();assert len(project.speakers)==3
    timeline.selected_track_header=None;delete_current(page);assert calls==['clip']
    timeline.locked_speakers.add('S2');delete_track(page,'subtitle','S2')
    assert '锁定' in page.save_state.text() and len(project.speakers)==3
    timeline.locked_speakers.clear()
    rect=timeline._track_layout()[0]['EMPTY']
    QTest.mouseClick(timeline,Qt.MouseButton.LeftButton,pos=QPoint(214,round(rect.center().y())))
    assert 'EMPTY' not in {s.id for s in project.speakers}
    page.undo_stack.undo();assert 'EMPTY' in timeline.speaker_ids()
    window.close()


def test_deleted_standalone_audio_does_not_resurrect_on_probe_or_new_import(project,app,tmp_path):
    from twobyteasr.projects.studio_project import hydrate_media_contract
    audio=add_media_asset(project,tmp_path/'voice.wav',duration_ms=3000,
        video_metadata={'has_video':False},audio_metadata={'has_audio':True})
    tid=next(t.id for t in project.audio_tracks if any(c.asset_id==audio.asset_id for c in t.clips))
    stack=QUndoStack();stack.push(DeleteTrackCommand(project,'audio',tid))
    hydrate_media_contract(project,{'duration_ms':5000,'width':160,'height':90,'has_video':True,'has_audio':True})
    add_media_asset(project,tmp_path/'another.wav',duration_ms=3000,
        video_metadata={'has_video':False},audio_metadata={'has_audio':True})
    assert not any(c.asset_id==audio.asset_id for t in project.audio_tracks for c in t.clips)


def test_add_empty_subtitle_track_is_reversible_and_preserves_order(project,app):
    from twobyteasr.timeline.studio_track_delete import AddSubtitleTrackCommand
    timeline=WaveformTimeline();timeline.set_project(project)
    page=SimpleNamespace(project=project,timeline=timeline,_populate_speakers=lambda:None,ensure_active_subtitle_renderer=lambda **_:None)
    before=copy.deepcopy(project.speakers);order=list(project.studio_state['speaker_track_order'])
    stack=QUndoStack();command=AddSubtitleTrackCommand(page);stack.push(command)
    assert len(project.speakers)==4 and timeline.selected_track_header==('subtitle',command.speaker.id)
    assert timeline.speaker_ids()==order+[command.speaker.id]
    stack.undo();assert project.speakers==before and project.studio_state['speaker_track_order']==order
    stack.redo();assert timeline.speaker_ids()==order+[command.speaker.id]


def test_single_key_press_deletes_one_track_and_next_press_is_not_debounced(tmp_path,monkeypatch):
    from tests.test_studio_style_controller import _page,_finish
    from twobyteasr.timeline.studio_track_delete import AddSubtitleTrackCommand
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.show();page.activateWindow();QTest.qWait(40)
        original=[c.id for c in page.project.cues]
        for _ in range(2):
            page.undo_stack.push(AddSubtitleTrackCommand(page))
            sid=page.project.speakers[-1].id;timeline=page.timeline
            rect=timeline._track_layout()[0][sid]
            QTest.mouseClick(timeline,Qt.LeftButton,pos=QPoint(75,round(rect.center().y())))
            before=page.undo_stack.index()
            QTest.keyClick(timeline,Qt.Key_Delete)
            assert sid not in {s.id for s in page.project.speakers}
            assert [c.id for c in page.project.cues]==original
            assert page.undo_stack.index()==before+1
    finally:_finish(page)
