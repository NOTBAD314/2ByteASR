import threading
import time
from types import SimpleNamespace as NS

from PySide6.QtCore import QObject, QRect
from PySide6.QtWidgets import QApplication, QLabel

from twobyteasr.studio.caption_seek_preparation import CaptionSeekPreparation, COVER_ID

APP=QApplication.instance() or QApplication([])


def fixture(monkeypatch):
    import twobyteasr.studio.caption_seek_preparation as module
    import twobyteasr.studio.studio_readiness as readiness
    class Project:
        cues=[object()]
        def __eq__(self,other):raise AssertionError('project data must not be deeply compared on a seek tick')
    page=QObject();page.project=Project();page._readiness=NS(generation=1)
    page._close_requested=False;page.save_state=QLabel('已保存');page.calls=[];page.positions=[]
    page._studio_trace=lambda *a,**k:None
    page.timeline=NS(set_playhead=page.positions.append)
    applied={};scene=NS(active=True,closed=False,lock=threading.RLock(),token=('scene',),
        _last_published_sample_ms=42,_priority_warm_time=None,_seek_reserved_frame=None)
    page._caption_scene=scene
    video=NS(_startup_state='READY',_media_has_video=True,_clock_only=False,_seek_hold_active=False,
        _playback_clock=NS(generation=1),playback_intended=False,
        controller=NS(instance_id='player',_subtitle_binding_epoch=1,screenshot_to_file=lambda *a,**k:None,
            post_raw_overlay=lambda *a,**k:True,applied_visual_state=lambda:{'overlays':applied}),
        visual_position=lambda:0.,begin_caption_seek_hold=lambda:None,rect=lambda:QRect(0,0,640,360),
        _prepared_caption_publications=[],remove_compositor_overlay=lambda *a,**k:page.calls.append('remove-cover'))
    page.video=video
    def commit(seconds,**kwargs):
        page.calls.append(seconds);video._playback_clock.generation+=1
    page._seek_immediate=commit;page._present_caption_scene=lambda:None
    page._caption_sample_ms=lambda:42
    page._playback_buffers_ready=lambda **kwargs:True
    owner=CaptionSeekPreparation(page)
    monkeypatch.setattr(owner,'_capture',lambda:None)
    prepared=set();covered=[False];decoded=[False];caption=[False]
    monkeypatch.setattr(owner,'_prepare_caption',lambda r:r['target'] in prepared)
    monkeypatch.setattr(owner,'_publish_cover',lambda:covered[0])
    monkeypatch.setattr(readiness,'player_surface_ready',lambda p:decoded[0])
    monkeypatch.setattr(module,'active_cues',lambda p,t:[NS(id='a')])
    monkeypatch.setattr(module,'complete_scene_for_seek',lambda *a:caption[0])
    return page,owner,prepared,covered,decoded,caption,applied


def test_latest_seek_waits_for_caption_cover_decoder_and_upload_ack(monkeypatch):
    p,o,prepared,covered,decoded,caption,applied=fixture(monkeypatch)
    try:
        assert o.request(1,True);first=o.pending
        assert o.request(2,True)
        prepared.add(1000);covered[0]=True;o.tick()
        assert not p.calls and p.positions==[1000,2000]
        prepared.add(2000);o.cover=NS(started=0.,finished=0.,timings={});o.tick()
        assert p.calls==[2.] and o.pending is not first
        o.tick();assert o.pending['phase']=='seek'
        decoded[0]=caption[0]=True;o.tick()
        assert o.pending['phase']=='seek'  # Pixels queued without mpv ACK are insufficient.
        p.video._prepared_caption_publications.append(dict(applied=True,scene_token=p._caption_scene.token,sample_ms=42))
        o.tick();assert o.pending['phase']=='reveal' and p.calls[-1]=='remove-cover'
        applied[COVER_ID]=dict(visible=True,monotonic=time.perf_counter());o.tick()
        assert o.pending is not None
        applied[COVER_ID]=dict(visible=False,monotonic=time.perf_counter());o.tick()
        assert o.pending is None and o.cover is None and o.samples[-1]['target']==2000
    finally:o.cancel();p.deleteLater()


def test_project_switch_rejects_late_capture_and_never_commits_old_target(monkeypatch):
    p,o,prepared,covered,decoded,caption,applied=fixture(monkeypatch)
    try:
        o.request(1,True);epoch=o.cover_epoch
        p.project=NS(cues=[object()]);p._readiness.generation+=1
        o.tick();o._captured(epoch,object(),'')
        assert o.pending is None and o.cover is None and not p.calls
    finally:o.cancel();p.deleteLater()


def test_seek_cover_is_foreground_and_not_a_caption_boundary_member():
    from twobyteasr.playback.studio_mpv import MpvController
    sent=[];options=[]
    def post(fn,**kwargs):options.append(kwargs);fn();return True
    owner=NS(_caption_boundary_publisher=NS(allows=lambda cue:False),_post=post,
        _send=lambda command:sent.append(command) or {},_record_visual_applied=lambda *a:None)
    MpvController.post_raw_overlay(owner,COVER_ID,'cover.rgba',x=0,y=0,width=8,height=8,stride=32,cue_id='cover')
    assert sent and options[-1]['foreground'] and not options[-1]['deferred']
    sent.clear()
    MpvController.post_raw_overlay(owner,1,'caption.rgba',x=0,y=0,width=8,height=8,stride=32,cue_id='stale')
    assert not sent  # The real caption fence remains strict.


def test_fast_capture_restores_compression_even_when_snapshot_fails(tmp_path):
    import pytest
    from twobyteasr.playback.studio_mpv import MpvController
    commands=[]
    def exchange(command,**kwargs):
        commands.append(command)
        if command[0]=='get_property':return {'data':7}
        if command[0]=='screenshot-to-file':raise RuntimeError('controlled')
        return {}
    owner=NS(_actor=NS(exchange=exchange,call=lambda callback,timeout:callback()))
    with pytest.raises(RuntimeError,match='controlled'):
        MpvController.screenshot_to_file(owner,tmp_path/'frame.png',fast=True)
    assert commands[-1]==['set_property','screenshot-png-compression',7]


def test_pending_seek_preserves_caption_clock_but_moves_input_playhead():
    from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin
    positions=[]
    page=NS(_caption_seek_preparation=NS(pending=dict(phase='prepare',target=9000000,held_sample_ms=1000)),
            timeline=NS(set_playhead=positions.append))
    assert StudioPlaybackFlowMixin._caption_sample_ms(page)==1000
    StudioPlaybackFlowMixin._position_changed(page,1)
    assert positions==[9000000]
