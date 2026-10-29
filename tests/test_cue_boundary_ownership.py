import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.projects.studio_runtime_state import state_for, DirtyDomain
from twobyteasr.projects.studio_session import StudioSession
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin
from twobyteasr.studio.studio_cue_table import CueTableModel

APP = QApplication.instance() or QApplication([])


def project():
    p = SubtitleProject(media=StudioMedia('synthetic.mp4', duration_ms=8000),
        speakers=[StudioSpeaker('S1'), StudioSpeaker('S2')],
        cues=[StudioCue(f'{track}-{i}', 250+i*225, 475+i*225, '字幕', track)
              for track in ('S1','S2') for i in range(32)])
    p.validate()
    return p


def test_playback_activity_never_materializes_selection_or_transactions():
    p = project(); runtime = state_for(p)
    session = StudioSession(project=p, selected_cue_id='S1-0', runtime=runtime,
                            _cue_lookup=runtime.cue_by_id)
    calls = []
    model = CueTableModel(p)
    model.dataChanged.connect(lambda left,right,roles: calls.append((left.row(),right.row(),roles)))
    timeline = SimpleNamespace(hidden_speakers=set(), set_active_cues=lambda ids: None)
    page = SimpleNamespace(session=session, project=p, _cue_lookup=runtime.cue_by_id,
        cue_model=model, timeline=timeline, _subtitle_track_visibility={}, selected_cue_id='S1-0')
    for ms in range(0,8001,10):
        StudioPlaybackFlowMixin._update_active_cues(page, ms)
        assert session.selected_cue_id=='S1-0'
    assert runtime.commit_count==0
    assert session.active_cue_id=='' and not session.active_cue_ids
    assert len(calls)==128  # every row becomes active and inactive, once each
    assert all(a==b and roles==[CueTableModel.ActiveCueRole] for a,b,roles in calls)


def test_visibility_and_reverse_seek_are_independent_of_editor():
    p=project();runtime=state_for(p)
    session=StudioSession(project=p,selected_cue_id='S1-31',runtime=runtime)
    page=SimpleNamespace(session=session,project=p,_cue_lookup=runtime.cue_by_id,
        cue_model=CueTableModel(p),timeline=SimpleNamespace(hidden_speakers={'S2'},set_active_cues=lambda ids:None),
        _subtitle_track_visibility={})
    StudioPlaybackFlowMixin._update_active_cues(page, 1200)
    assert session.active_cue_ids==frozenset({'S1-4'})
    StudioPlaybackFlowMixin._update_active_cues(page, 250)
    assert session.active_cue_id=='S1-0' and session.selected_cue_id=='S1-31'
    page._subtitle_track_visibility['S1']=False
    StudioPlaybackFlowMixin._update_active_cues(page, 250)
    assert not session.active_cue_ids


def test_selection_shares_frozen_render_metadata(monkeypatch):
    p=project();p.generation_metadata={'evidence':[{'words':['unchanged']*1000}]*50}
    store=StudioRevisionStore(p);runtime=state_for(p);runtime.subscribe(store.consume)
    before=store.render
    def no_freeze(*args):raise AssertionError('selection must not freeze the render project')
    monkeypatch.setattr('twobyteasr.projects.studio_revisions.freeze_json', no_freeze)
    with runtime.transaction(p, action_id='select_cue', dirty=DirtyDomain.CUE_SELECTION|DirtyDomain.TIMELINE_PIXELS,
                             selection_before='S1-0',selection_after='S1-1'):
        pass
    assert not runtime.subscriber_errors
    assert store.render.generation_metadata is before.generation_metadata
    assert store.render.cues is before.cues
    assert store.render.visual_revision==before.visual_revision
    assert store.render.revision_id==runtime.revision


def test_timeline_activity_keeps_static_raster_and_selection():
    from twobyteasr.studio.studio_timeline import WaveformTimeline
    timeline=WaveformTimeline();timeline.resize(1000,400);timeline.set_project(project())
    timeline.set_selected('S1-0');timeline.show();APP.processEvents()
    timeline.grab()
    cached=timeline._static_timeline_cache
    timeline.set_active_cues({'S1-3','S2-3'});APP.processEvents()
    assert timeline.selected_id=='S1-0'
    assert timeline._static_timeline_cache is cached
    assert not timeline._static_timeline_dirty
    timeline.close();timeline.deleteLater();APP.processEvents()


def test_session_close_retires_passive_activity():
    session=StudioSession(active_cue_id='a',active_cue_ids=frozenset({'a','b'}), selected_cue_id='b')
    session.close()
    assert session.active_cue_id=='' and not session.active_cue_ids and session.selected_cue_id==''


def test_background_cache_prepares_all_lookahead_cues_and_preserves_style():
    import time
    import threading
    from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache
    from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
    p=project();store=StudioRevisionStore(p);cache=PlaybackCaptionCache()
    ready=[];errors=[]
    cache.ready.connect(lambda key,ids:ready.extend(ids));cache.failed.connect(errors.append)
    ids=('S1-0','S1-1','S1-2')
    cache.prepare(store.render,ids,960,540)
    end=time.monotonic()+5
    while len(ready)<3 and time.monotonic()<end and not errors:
        APP.processEvents();time.sleep(.005)
    assert not errors
    assert set(ready)==set(ids)
    for cue_id in ids:
        snap=cache.snapshot(store.render,cue_id,960,540)
        assert snap.resolved_caption.style_hash==build_visual_cue_snapshot(p,cue_id,width=960,height=540).resolved_caption.style_hash
    cache.close()


def test_web_worker_survives_inactive_clock_and_only_stops_explicitly(monkeypatch):
    import time
    from twobyteasr.rendering.live_web_preview import LiveWebPreviewWorker
    from twobyteasr.rendering import renderer_service
    sessions=[]
    class Session:
        def __init__(self,*args):sessions.append(self)
        def close(self):self.closed=True
    monkeypatch.setattr(renderer_service,'LiveRendererSession',Session)
    worker=LiveWebPreviewWorker(time_provider=lambda:None)
    worker.start();time.sleep(.035)
    assert worker.running and len(sessions)==1
    worker.stop();worker._thread.join(1)
    assert not worker.running and sessions[0].closed


def test_first_web_frame_decodes_on_background_worker():
    import base64,time,threading
    from twobyteasr.rendering.latest_work import LatestWork
    from twobyteasr.rendering.live_web_preview import WebFrame
    from twobyteasr.studio.studio_advanced_flow import StudioAdvancedFlowMixin
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
    data=WebFrame(png,1,'cue',1,1);received=[];runner=LatestWork('test-web-decode')
    page=SimpleNamespace(_web_frame_is_current=lambda x:True,_web_frame_decode_runner=runner,
        _web_live_bridge=SimpleNamespace(frame=SimpleNamespace(emit=lambda *args:received.append((threading.get_ident(),args)))))
    StudioAdvancedFlowMixin._on_web_live_frame(page,data,50,250)
    end=time.monotonic()+2
    while not received and time.monotonic()<end:time.sleep(.005)
    runner.close()
    assert received and received[0][0]!=threading.get_ident()
    assert not received[0][1][0].decoded_image.isNull()
