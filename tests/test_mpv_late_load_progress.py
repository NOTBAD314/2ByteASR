from types import SimpleNamespace
from twobyteasr.playback.studio_mpv import MpvController


def test_verified_late_file_loaded_revokes_the_old_reload_decision(tmp_path):
    source=str(tmp_path/'late.mp4')
    actor=SimpleNamespace(_source_generation=7,_degraded=True,_transport_failures=3,_outage_started=1.,
                          mark_exchange_ok=lambda:None)
    controller=SimpleNamespace(_subtitle_binding_epoch=4,_subtitle_media_path=source,
        _subtitle_media_ready=False,_needs_media_reload=True,_pending_media_seek=None,
        _desired_subtitle_path='',_actor=actor,source_epoch=7,get_property=lambda *_:source)
    controller._post=lambda callback,**_:callback()
    MpvController._subtitle_file_loaded(controller)
    assert controller._subtitle_media_ready
    assert not controller._needs_media_reload
    assert actor._last_media_progress['media_epoch']==4
    assert actor._last_media_progress['source_generation']==7
    assert not actor._degraded and actor._transport_failures==0


def test_late_file_loaded_for_an_old_path_cannot_claim_current_progress(tmp_path):
    source=str(tmp_path/'current.mp4')
    actor=SimpleNamespace()
    controller=SimpleNamespace(_subtitle_binding_epoch=4,_subtitle_media_path=source,
        _subtitle_media_ready=False,_needs_media_reload=True,_pending_media_seek=None,
        _desired_subtitle_path='',_actor=actor,source_epoch=7,get_property=lambda *_:str(tmp_path/'old.mp4'))
    controller._post=lambda callback,**_:callback()
    MpvController._subtitle_file_loaded(controller)
    assert not controller._subtitle_media_ready and controller._needs_media_reload
    assert not hasattr(actor,'_last_media_progress')
