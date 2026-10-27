"""Opening diagnostics observe caches without making a paused frame advance."""
from types import SimpleNamespace as NS

from twobyteasr.playback.playback_clock import PlaybackClock
from twobyteasr.studio import studio_readiness as readiness


def page_fixture():
    calls=[]
    def cached(name, value):
        def read():calls.append(name);return dict(value)
        return read
    def forbidden(*_a,**_k):raise AssertionError('diagnostics submitted player work')
    controller=NS(source_epoch=4,_subtitle_binding_epoch=3,
        observed_frame=cached('frame',dict(status='frame_or_target_not_ready',source_generation=4)),
        observed_properties=cached('properties',{'time-pos':0.,'pause':True,'seeking':False}),
        applied_seek_state=cached('seek',dict(generation=4,target=0.)),
        command=forbidden,get_property=forbidden,_send=forbidden,screenshot=forbidden)
    page=NS(video=NS(controller=controller,_playback_clock=PlaybackClock(),_media_path='clip.mp4',
                    _startup_state='READY',_media_has_video=True),
            audio_engine=NS(telemetry_snapshot=cached('audio',dict(state='PAUSED',buffer_bytes=8192))))
    return page,calls


def test_player_wait_snapshot_reads_cached_fields_without_ipc_or_screenshot():
    page,calls=page_fixture()
    result=readiness.player_wait_snapshot(page)
    assert sorted(calls)==['audio','frame','properties','seek']
    assert result['observed_frame']['status']=='frame_or_target_not_ready'
    assert result['applied_seek_state']['generation']==4
    assert result['target']['media_path']=='clip.mp4' and result['target']['media_epoch']==3
    assert result['audio']['buffer_bytes']==8192
    assert result['clock']['exact_seek_pending'] is False


def test_wait_diagnostics_are_bounded_and_failure_keeps_a_fresh_snapshot(monkeypatch):
    page,calls=page_fixture();records=[];now=[100.]
    page._studio_trace=lambda *a,**k:records.append(k)
    gate=NS(page=page,profile={},started=100.,generation=5)
    monkeypatch.setattr(readiness.time,'perf_counter',lambda:now[0])
    readiness.StudioReadiness._record_player_wait(gate)
    assert not calls
    for index in range(12):
        now[0]=101.+index*5.
        readiness.StudioReadiness._record_player_wait(gate)
    assert len(records)==7
    readiness.StudioReadiness._record_player_wait(gate,failed=True)
    assert len(records)==8 and records[-1]['failed']
    assert len(gate.profile['player_wait'])==8
