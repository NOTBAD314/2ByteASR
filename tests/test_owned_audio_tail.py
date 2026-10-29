"""Real PCM ownership and EOF fences for video shorter than its audio."""
import copy
from types import SimpleNamespace

import pytest

from twobyteasr.playback.owned_audio_tail import AudioTailWait, OwnedAudioTail, audio_pcm_drained, owned_audio_sample, held_video_frame_ready
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin


def sample():
    return dict(source_path='current.mp4', session_generation=7,
        transport_generation=[3, 2], source_generation=11, engine_thread_alive=True,
        paused=False, state='PLAYING', sink_state='ActiveState', sink_error='NoError',
        output_device_id='real-endpoint', estimated_source_ms=55800., effective_rate=1.,
        decoder_eof=True, decoded_bytes=192000, sink_consumed_bytes=96000,
        buffer_bytes=96000, processed_us=400000,
        output_format={'bytes_per_second': 192000})


def request():
    return dict(source_path='current.mp4', session_generation=7,
        transport_generation=[3, 2], audible=True, paused=False)


def owned(payload, req=None, **changes):
    args=dict(generation=3, session=7, source='current.mp4', paused=False, rate=1.)
    args.update(changes)
    return owned_audio_sample(payload, req or request(), **args)


def test_current_audio_with_buffered_eof_is_owned_and_not_drained():
    assert owned(sample())
    assert not audio_pcm_drained(sample())


@pytest.mark.parametrize('field,value', [
    ('session_generation', 6), ('transport_generation', [2, 2]),
    ('transport_generation', [3, 1]), ('source_path', 'other.mp4'),
    ('engine_thread_alive', False), ('paused', True), ('state', 'SILENT'),
    ('state', 'NO_OUTPUT_DEVICE'), ('state', 'DECODER_FAILED'),
    ('sink_state', 'SuspendedState'), ('sink_error', 'IOError'),
    ('output_device_id', ''), ('decoded_bytes', 0), ('effective_rate', 2.),
    ('estimated_source_ms', float('nan')),
])
def test_foreign_or_inactive_audio_cannot_take_video_clock(field, value):
    payload=sample();payload[field]=value
    assert not owned(payload)


@pytest.mark.parametrize('change', [dict(audible=False), dict(mix_layers=[{'source_path':'other.mp4'}]),
    dict(session_generation=8), dict(transport_generation=[3,3]), dict(source_path='other.mp4')])
def test_current_request_fences_old_telemetry(change):
    req=request();req.update(change)
    assert not owned(sample(), req)


def test_native_queued_pcm_must_finish_even_when_ring_empty():
    payload=sample();payload.update(buffer_bytes=0, sink_consumed_bytes=192000)
    assert not audio_pcm_drained(payload)
    payload['processed_us']=1_000_000
    assert audio_pcm_drained(payload)
    payload['processed_us']=900000;payload['sink_state']='IdleState'
    assert audio_pcm_drained(payload)
    payload['decoder_eof']=False
    assert not audio_pcm_drained(payload)


def test_paused_seek_can_ack_decoded_owned_pcm_without_playing_it():
    payload=sample();payload.update(paused=True, state='PAUSED', sink_state='StoppedState')
    assert owned(payload, paused=True)
    assert not owned(payload)
    payload['state']='BUFFERED'
    assert owned(payload, paused=True)


def test_project_clip_transport_and_audio_generation_all_fence_token():
    project=object();token=OwnedAudioTail(id(project),'primary','video-clip','current.mp4',3,7,(3,2),11,60000,False,1.)
    args=dict(project=project,key='primary',clip='video-clip',generation=3,payload=sample())
    assert token.matches(**args)
    for change in (dict(project=object()),dict(key='other'),dict(clip='new-clip'),dict(generation=4)):
        assert not token.matches(**{**args,**change})
    for change in (dict(transport_generation=[3,3]),dict(source_generation=12),
            dict(session_generation=8),dict(source_path='different.mp4'),dict(effective_rate=2.),dict(paused=True)):
        payload=sample();payload.update(change)
        assert not token.matches(**{**args,'payload':payload})


def eof_page(payload):
    class Page(StudioPlaybackFlowMixin):
        def _studio_trace(self, *a, **kw): pass
        def _advance_project_boundary(self, ms): self.advanced.append(ms)
    page=Page();page.advanced=[]
    page.project=SimpleNamespace(video_tracks=[SimpleNamespace(clips=[SimpleNamespace(id='v1',timeline_out_ms=60000)])])
    page._active_video_preview_clip_id='v1';page._active_video_preview_key='primary'
    page._active_video_preview_source_path='current.mp4';page.timeline=SimpleNamespace(playhead_ms=55050)
    page.video=SimpleNamespace(_paused=False,_playback_rate=1.,_source_rate_multiplier=1.,
        _playback_clock=SimpleNamespace(generation=3,exact_seek_pending=False,set_presentation_hold=lambda held:setattr(page,'held',held)),
        controller=SimpleNamespace(observed_position=lambda:{'source_generation':3}),
        set_external_clock_enabled=lambda enabled:setattr(page,'enabled',enabled))
    page.audio_engine=SimpleNamespace(clock_observation=lambda:payload,_last_payload=request(),_session_generation=7)
    return page


def test_actual_video_eof_keeps_owned_pcm_then_finishes_at_audio_drain():
    payload=sample();page=eof_page(payload)
    assert page._handle_source_eof()
    assert page.enabled and not page.advanced
    payload.update(buffer_bytes=0,sink_consumed_bytes=192000,processed_us=1_000_000)
    assert not page._refresh_audio_tail_clock()
    assert page.advanced==[60000]
    assert page._owned_audio_tail is None


def test_stale_eof_pause_new_project_and_clip_cannot_continue_audio():
    page=eof_page(sample());page.video._playback_clock.exact_seek_pending=True
    assert page._handle_source_eof() and not page.advanced
    page.video._playback_clock.exact_seek_pending=False;page.video._paused=True
    assert page._handle_source_eof() and not page.advanced
    page.video._paused=False;assert page._begin_audio_tail()
    page._active_video_preview_clip_id='new-clip'
    assert not page._refresh_audio_tail_clock() and page._owned_audio_tail is None


def test_video_eof_without_owned_audio_advances_normally():
    payload=sample();payload['state']='SILENT'
    page=eof_page(payload)
    assert page._handle_source_eof() and page.advanced==[60000]
    assert getattr(page, '_owned_audio_tail', None) is None


def test_close_or_session_unload_invalidates_audio_tail():
    payload=sample();page=eof_page(payload);assert page._begin_audio_tail()
    page._close_requested=True
    assert not page._refresh_audio_tail_clock() and page._owned_audio_tail is None
    page._close_requested=False;assert page._begin_audio_tail()
    page.audio_engine._session_generation+=1
    assert not page._refresh_audio_tail_clock() and page._owned_audio_tail is None


def test_video_boundary_is_runtime_only_and_keeps_metadata_contract():
    from twobyteasr.media.media_service import MediaMetadataSnapshot
    snapshot=MediaMetadataSnapshot('source',1,2,60160,True,True,video_stream_end_ms=55066.624)
    assert snapshot.video_stream_end_ms==55066.624
    assert 'video_stream_end_ms' not in snapshot.to_dict()


def test_tail_reopen_requires_current_video_actor_source_and_decoded_surface():
    tail=SimpleNamespace(source='current.mp4')
    args=dict(generation=3,attached=True,running=True,frame={'source_generation':3,'position':55.05},
        properties={'path':'current.mp4','video-out-params':{'dw':1920,'dh':1080},'video-frame-info':{'picture-type':'B'}})
    assert held_video_frame_ready(tail,**args)
    assert not held_video_frame_ready(None,**args)
    for change in (dict(running=False),dict(attached=False),dict(generation=4),
            dict(frame={'source_generation':3,'position':None}),
            dict(properties={'path':'old.mp4','video-out-params':{'dw':1920,'dh':1080}}),
            dict(properties={'path':'current.mp4','video-out-params':{'dw':1920,'dh':1080}}),
            dict(properties={'path':'current.mp4'})):
        assert not held_video_frame_ready(tail,**{**args,**change})


def waiting_page():
    import time
    payload=sample();payload.update(paused=True,state='PAUSED',sink_state='StoppedState')
    page=eof_page(payload);page.video._paused=True
    page.video._media_attached=True
    page.video.controller.running=True
    page.video.controller.observed_position=lambda:{'source_generation':3,'position':55.05}
    page.video.controller.observed_properties=lambda:{'path':'current.mp4',
        'video-out-params':{'dw':1920,'dh':1080},'video-frame-info':{'picture-type':'B'}}
    assert page._begin_audio_tail(paused=True)
    receipt=page._owned_audio_tail;page._invalidate_audio_tail()
    page._audio_tail_seek_pending=AudioTailWait(id(page.project),'primary','v1','current.mp4',3,7,1.,55800,55800.,receipt)
    page._audio_tail_seek_started=time.monotonic();page.video._paused=False
    page.audio_engine._last_payload['paused']=False
    return page,payload


def test_resume_gap_keeps_verified_tail_image_without_claiming_playing_audio():
    page,payload=waiting_page()
    assert page._audio_tail_waiting() and page._audio_tail_visual_active()
    assert not page._refresh_audio_tail_clock()
    assert page._owned_audio_tail is None and page._audio_tail_visual_active()
    payload.update(paused=False,state='PLAYING',sink_state='ActiveState')
    assert page._refresh_audio_tail_clock()
    assert page._audio_tail_seek_pending is None and page._owned_audio_tail is not None
    assert not page.held


@pytest.mark.parametrize('mutation', ['source','key','clip','epoch','session','rate','transport','frame','timeout','close'])
def test_resume_visual_receipt_cannot_cross_transport_or_media_boundary(mutation):
    page,payload=waiting_page()
    if mutation=='source':page._active_video_preview_source_path='other.mp4'
    elif mutation=='key':page._active_video_preview_key='other'
    elif mutation=='clip':page._active_video_preview_clip_id='other'
    elif mutation=='epoch':page.video._playback_clock.generation=4
    elif mutation=='session':page.audio_engine._session_generation=8
    elif mutation=='rate':page.video._playback_rate=2.
    elif mutation=='transport':page.audio_engine._last_payload['transport_generation']=[3,3]
    elif mutation=='frame':page.video.controller.observed_properties=lambda:{}
    elif mutation=='timeout':page._audio_tail_seek_started-=11
    elif mutation=='close':page._close_requested=True
    assert not page._audio_tail_visual_active()
    assert not page._refresh_audio_tail_clock()
    assert page._audio_tail_seek_pending is None and not page.held


def test_new_tail_seek_without_prior_pcm_cannot_promote_a_single_caption():
    page,payload=waiting_page()
    from dataclasses import replace
    page._audio_tail_seek_pending=replace(page._audio_tail_seek_pending,visual_receipt=None)
    assert page._audio_tail_waiting() and not page._audio_tail_visual_active()


def test_resume_wait_holds_single_clock_without_changing_play_intent():
    from twobyteasr.playback.playback_clock import PlaybackClock
    clock=PlaybackClock(now=0.)
    clock.force_position(55950,paused=True,now=0.)
    clock.set_presentation_hold(True)
    clock.set_local_state(55950,paused=False,now=1.,reason='local_pause_state')
    assert not clock.paused
    for source in ('visual_tick','ui_flush','caption_boundary'):
        assert clock.sample_presentation(elapsed_ms=2000,source=source).presentation_media_ms==55950
    assert clock.presentation_position_ms(elapsed_ms=2000)==55950
    clock.set_presentation_hold(False)
    assert clock.presentation_position_ms(elapsed_ms=50)==56000


def test_pause_gap_can_keep_last_verified_tail_image_until_real_paused_pcm():
    page,payload=waiting_page()
    from dataclasses import replace
    pending=page._audio_tail_seek_pending
    page._audio_tail_seek_pending=replace(pending,visual_receipt=replace(pending.visual_receipt,paused=False))
    payload.update(paused=False,state='PLAYING',sink_state='ActiveState')
    page.video._paused=True;page.audio_engine._last_payload['paused']=True
    assert page._audio_tail_visual_active()
    assert not page._refresh_audio_tail_clock()
    payload.update(paused=True,state='PAUSED',sink_state='StoppedState')
    assert page._refresh_audio_tail_clock() and page._owned_audio_tail.paused


def test_pending_tail_does_not_reaccept_previous_paused_audio_observation():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=SimpleNamespace(_studio_page=lambda:SimpleNamespace(_audio_tail_waiting=lambda:True))
    # The provider and Clock are deliberately absent: pending must stop before
    # adopting the old PCM pause bit or sequence into the user's play intent.
    assert MpvCanvas._observe_external_clock(canvas) is False


def test_tail_startup_requires_current_applied_bitmap_not_only_a_queued_scene():
    from twobyteasr.playback.owned_audio_tail import tail_caption_publication_ready
    project=object();token=(id(project),1,1,3,('36',))
    scene=SimpleNamespace(project=project,active=True,closed=False,published=object(),token=token,
        trace=lambda:dict(visible=True,rendered_cue_ids=['36']))
    args=dict(project=project,generation=3,expected=('36',),publications=[])
    assert not tail_caption_publication_ready(scene,**args)
    args['publications']=[dict(applied=True,scene_token=token)]
    assert tail_caption_publication_ready(scene,**args)
    for change in (dict(generation=4),dict(project=object()),dict(expected=('35',)),
            dict(publications=[dict(applied=False,scene_token=token)]),
            dict(publications=[dict(applied=True,scene_token=(id(project),1,1,2,('36',)))])):
        assert not tail_caption_publication_ready(scene,**{**args,**change})
    scene.published=None
    assert not tail_caption_publication_ready(scene,**args)
    scene.published=object();scene.trace=lambda:dict(visible=False,rendered_cue_ids=[])
    assert not tail_caption_publication_ready(scene,**args)
