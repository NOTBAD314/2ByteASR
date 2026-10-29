import copy
import os
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QPushButton, QLabel, QPlainTextEdit
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, AudioClip, save_project, load_project, sync_linked_av_contract
from twobyteasr.timeline.studio_media_pool import create_video_track, add_video_clip, set_video_track_state
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.timeline.studio_track_delete import DeleteTrackCommand
from twobyteasr.studio.studio_track_header import ACTIONS, button_rect, action_at

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def project(tmp_path,app):
 p=SubtitleProject(media=StudioMedia(str(tmp_path/'same.mp4'),duration_ms=6000,width=640,height=360),cues=[StudioCue('cue',500,4500,'保留字幕')]);p.validate()
 p.media_pool[0].audio_metadata['has_audio']=True
 set_video_track_state(p,'V1',locked=False);sequence_of(p).video_track_locked=False
 t=create_video_track(p);add_video_clip(p,t.id,p.media_pool[0].asset_id,source_out_ms=2000)
 sync_linked_av_contract(p)
 for asset in p.media_pool:asset.offline=False
 return p

def test_header_geometry_identical_with_height_dpi_and_fixed_hit_slots():
 for height in (36,52,58,84,120):
  row=QRectF(0,111,228,height)
  for col in range(3):
   boxes=[button_rect(k,ACTIONS[k][col],row) for k in ACTIONS]
   assert len({(r.x(),r.y(),r.width(),r.height()) for r in boxes})==1
   for kind in ACTIONS:
    box=boxes[0];assert action_at(kind,box.center().x(),box.center().y(),row)==ACTIONS[kind][col]
    assert action_at(kind,box.center().x(),box.top()-1,row)==''
 assert 'muted' not in ACTIONS['video']

def test_last_clip_group_removal_undo_redo_save(project,tmp_path):
 p=project;t=p.video_tracks[1];g=p.av_track_groups[1];a=next(t for t in p.audio_tracks if t.id==g.audio_track_id)
 a.soloed=True;a.muted=True;p.studio_state['audio_track_gain_db']={a.id:-7}
 before=copy.deepcopy((p.video_tracks,p.audio_tracks,p.av_track_groups,p.cues,p.styles,p.studio_state))
 stack=QUndoStack();stack.push(DeleteTrackCommand(p,'video',t.id,clip_ids=[t.clips[0].id]))
 assert len(p.video_tracks)==1 and len(p.audio_tracks)==1 and p.cues==before[3]
 assert p.video_tracks[0].clips[0].asset_id==t.clips[0].asset_id
 stack.undo();assert (p.video_tracks,p.audio_tracks,p.av_track_groups,p.cues,p.styles,p.studio_state)==before
 stack.redo();save_project(p,tmp_path/'saved.2byteproj');new=load_project(tmp_path/'saved.2byteproj')
 assert len(new.video_tracks)==1 and len(new.audio_tracks)==1

def test_nonlast_primary_delete_leaves_gap_and_cues(project):
 p=project;t=p.video_tracks[0]
 from twobyteasr.timeline.studio_edit_commands import razor_video_command
 stack=QUndoStack();stack.push(razor_video_command(p,3000))
 t=p.video_tracks[0];before=copy.deepcopy(p.cues);remaining=copy.deepcopy(t.clips[-1])
 stack.push(DeleteTrackCommand(p,'video',t.id,clip_ids=[t.clips[0].id]))
 assert p.video_tracks[0].clips==[remaining]
 assert sequence_of(p).segments[0].timeline_in_ms==3000 and p.cues==before
 assert len(p.video_tracks)==2


def test_primary_last_delete_preserves_other_speed_trim_transform_and_mapping(project,tmp_path):
 from twobyteasr.timeline.studio_sequence_mapper import timeline_to_source,source_to_timeline
 p=project;t=p.video_tracks[1];c=t.clips[0]
 c.source_in_ms=1000;c.source_out_ms=5000;c.timeline_in_ms=3000;c.timeline_out_ms=5000;c.playback_rate=2
 c.transform.rotation=17;sync_linked_av_contract(p)
 before=copy.deepcopy(c);audio=copy.deepcopy(p.audio_tracks[1].clips)
 stack=QUndoStack();stack.push(DeleteTrackCommand(p,'video',p.video_tracks[0].id,clip_ids=[p.video_tracks[0].clips[0].id]))
 assert p.video_tracks[0].clips==[before] and p.audio_tracks[0].clips==audio
 save_project(p,tmp_path/'promoted.2byteproj');q=load_project(tmp_path/'promoted.2byteproj')
 assert q.video_tracks[0].clips==[before] and q.audio_tracks[0].clips==audio
 seq=sequence_of(q);assert (seq.segments[0].timeline_in_ms,seq.segments[0].timeline_out_ms)==(3000,5000)
 assert timeline_to_source(seq,4000).source_ms==3000
 assert source_to_timeline(seq,3000).timeline_ms==4000
 stack.undo();assert len(p.video_tracks)==2 and p.video_tracks[1].clips==[before]

def test_detached_audio_and_locked_pair(project):
 p=project;t=p.video_tracks[1];g=p.av_track_groups[1];a=next(t for t in p.audio_tracks if t.id==g.audio_track_id)
 a.locked=True
 with pytest.raises(ValueError,match='锁定'):DeleteTrackCommand(p,'video',t.id,clip_ids=[t.clips[0].id])
 a.locked=False;g.linked=False;before=copy.deepcopy(a.clips)
 from twobyteasr.timeline.studio_track_gain import audio_track_id
 assert audio_track_id(p,t.id)==t.id
 stack=QUndoStack();stack.push(DeleteTrackCommand(p,'video',t.id,clip_ids=[t.clips[0].id]))
 assert len(p.audio_tracks)==2
 assert [(c.id,c.asset_id,c.timeline_in_ms,c.timeline_out_ms) for c in a.clips]==[(c.id,c.asset_id,c.timeline_in_ms,c.timeline_out_ms) for c in before]
 assert next(x for x in p.audio_tracks if x.id==a.id).clips
 stack.undo();assert p.av_track_groups[1].linked is False

def test_disabled_video_lane_excludes_its_owned_audio(project):
 from twobyteasr.playback.audio_graph import capture_audio_graph
 p=project;before=capture_audio_graph(p)['segments'];set_video_track_state(p,'V2',enabled=False)
 after=capture_audio_graph(p)['segments']
 assert {x['track_id'] for x in before}=={'V1','V2'}
 assert {x['track_id'] for x in after}=={'V1'}
 assert [(x['source_path'],x['source_in_ms'],x['gain_db']) for x in before if x['track_id']=='V1']==[(x['source_path'],x['source_in_ms'],x['gain_db']) for x in after]

def test_new_generate_preflight_visible_identity_and_recovery(app,project,tmp_path,monkeypatch):
 import twobyteasr.studio.studio_ai_flow as module
 monkeypatch.setattr(module,'studio_data_root',lambda:tmp_path)
 class Page(module.StudioAIFlowMixin):
  def _studio_trace(self,*args,**kwargs):pass
  def _show_ai_progress_bar(self,*args):pass
  def _set_ai_input_sections_visible(self,*args):pass
  def _show_studio_hint(self,message):self.hint=message
  def _scroll_ai_panel_into_view(self,*args):pass
  def _launch_ai_suggestion(self,**kwargs):self.launches.append(kwargs);raise RuntimeError('worker 创建失败')
 page=Page();page.project=project;page.selected_cue_id='';page._ai_request_active=False;page._ai_cancel_event=None
 page._ai_needs_key=lambda settings:False  # a configured design service (no-key note, 2026-10-15)
 page.ai_generate=QPushButton();page.ai_suggestion_card=QLabel();page.ai_suggestion_title=QLabel();page.ai_confidence=QLabel();page.ai_preview=QPlainTextEdit();page.launches=[]
 page.ai_generate.clicked.connect(page._request_ai_suggestion)
 page.ai_generate.click();first=page._ai_last_start['request_id'];assert page.ai_generate.text()=='取消准备'
 app.processEvents();assert '选中一条字幕' in page.hint and not page.launches and page.ai_generate.isEnabled()
 page.selected_cue_id='cue';page.ai_generate.click();second=page._ai_last_start['request_id'];app.processEvents()
 assert first!=second and page.launches==[dict(request_id=second)] and 'worker 创建失败' in page.hint
 assert not page._ai_request_active and page.ai_generate.isEnabled()
 page.ai_generate.click();page.ai_generate.click();app.processEvents();assert len(page.launches)==1 and '已取消' in page.hint


def test_relink_warning_cancel_and_decode_failure_never_mutate(project,app,monkeypatch):
 from twobyteasr.studio.studio_media_availability import StudioMediaAvailability
 from PySide6.QtWidgets import QMessageBox
 p=project;asset=p.media_pool[0];before=copy.deepcopy(p)
 page=SimpleNamespace(project=p,save_state=QLabel(),undo_stack=QUndoStack())
 controller=SimpleNamespace(page=page,relink_generation=3,cancel_relink=lambda:None)
 messages=[]
 monkeypatch.setattr(QMessageBox,'question',lambda parent,title,body,*args:messages.append(body) or QMessageBox.Cancel)
 monkeypatch.setattr(QMessageBox,'warning',lambda parent,title,body:messages.append(body))
 result=dict(status='available',path='new.mp4',identity=dict(duration_ms=500,has_video=True,has_audio=False))
 StudioMediaAvailability.apply_relink(controller,p,asset.asset_id,asset.canonical_source,3,result)
 assert '源时间范围短' in messages[-1] and '没有音轨' in messages[-1]
 assert p==before and page.undo_stack.count()==0
 StudioMediaAvailability.apply_relink(controller,p,asset.asset_id,asset.canonical_source,3,dict(status='decode_failed',reason='无法解码所选媒体'))
 assert messages[-1]=='无法解码所选媒体' and p==before
 # Old generation and old source results cannot touch a later selection.
 StudioMediaAvailability.apply_relink(controller,p,asset.asset_id,asset.canonical_source,2,result)
 assert len(messages)==2
 # A replacement only 20ms shorter must still warn, even if edits fit.
 result['identity'].update(duration_ms=5980,has_audio=True)
 StudioMediaAvailability.apply_relink(controller,p,asset.asset_id,asset.canonical_source,3,result)
 assert '比原素材短' in messages[-1] and p==before and page.undo_stack.count()==0


def test_waveform_relink_rejects_cache_for_old_source(project):
 from pathlib import Path
 from twobyteasr.studio.studio_timeline import WaveformTimeline
 asset=project.media_pool[0]
 old=SimpleNamespace(metadata=SimpleNamespace(source_path=asset.canonical_source))
 page=SimpleNamespace(project=project,waveform_caches={asset.asset_id:old},waveform_clip_keys={'clip':'old'})
 assert WaveformTimeline.waveform_cache_for_source(page,asset.canonical_source) is old
 asset.canonical_source=str(Path(asset.canonical_source).with_name('new name.mp4'))
 assert WaveformTimeline.waveform_cache_for_source(page,asset.canonical_source) is None
 assert not page.waveform_caches and not page.waveform_clip_keys
