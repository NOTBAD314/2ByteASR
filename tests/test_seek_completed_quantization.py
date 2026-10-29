import pytest
from types import SimpleNamespace
from twobyteasr.playback.playback_clock import PlaybackClock


@pytest.mark.parametrize('completed,seeking,offset,generation,accepted',[
    (True,False,58,1,True),(False,False,58,1,False),
    (True,True,58,1,False),(True,False,150,1,False),
    (True,False,58,0,False),(True,False,-58,1,True)])
def test_nearby_actual_frame_requires_fresh_confirmed_decoder_restart(completed,seeking,offset,generation,accepted):
    clock=PlaybackClock(now=0)
    clock.begin_seek(300_000,now=1)
    snapshot,ok,reason=clock.observe(300_000+offset,source_generation=generation,actor_sequence=1,
        observed_monotonic_ts=1.1,playback_rate=1,paused=True,seeking=seeking,
        seek_completed=completed,now=1.1)
    assert ok==accepted
    assert snapshot.exact_seek_pending != accepted
    if accepted:assert snapshot.presentation_media_ms==300_000+offset


def test_restart_evidence_is_cleared_for_every_seek():
    import threading
    from twobyteasr.playback.studio_mpv import _MpvCommandActor
    actor=object.__new__(_MpvCommandActor)
    controller=SimpleNamespace(source_epoch=0, _subtitle_binding_epoch=0,
                               applied_seek_state=lambda: {})
    controller._advance_source_epoch=lambda value:setattr(controller,'source_epoch',value)
    actor.controller=controller
    actor._properties_lock=threading.Lock()
    actor.begin_seek(7,300)
    actor._handle_event({'event':'playback-restart'})
    assert actor._seek_completed_generation==-1
    actor._handle_event({'event':'seek'})
    actor._handle_event({'event':'playback-restart'})
    assert actor._seek_completed_generation==7
    actor.begin_seek(8,600)
    assert actor._seek_event_generation==-1 and actor._seek_completed_generation==-1
