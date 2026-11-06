from types import SimpleNamespace
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin


def test_retry_from_silent_audio_only_preview_restores_the_real_clock_before_play():
    events=[]
    page=SimpleNamespace(_silent_preview_selected=True,_show_audio_status=lambda *_:None,
        audio_engine=SimpleNamespace(retry_playback_output=lambda:events.append('retry')),
        _audio_playback_decision=SimpleNamespace(has_owner=True))
    page.video=SimpleNamespace(_clock_only=True,playback_prepare=lambda:events.append('prepare'),
        set_external_clock_enabled=lambda value:events.append(('audio_clock',value)),
        set_paused=lambda value:events.append(('paused',value)))
    StudioPlaybackFlowMixin._retry_audio_output(page)
    assert events==['retry','prepare',('audio_clock',True),('paused',False)]
    assert not page._silent_preview_selected


def test_retry_in_a_timeline_gap_keeps_its_local_clock():
    flags=[]
    page=SimpleNamespace(_silent_preview_selected=True,_show_audio_status=lambda *_:None,
        audio_engine=SimpleNamespace(retry_playback_output=lambda:None),
        _audio_playback_decision=SimpleNamespace(has_owner=False))
    page.video=SimpleNamespace(_clock_only=True,playback_prepare=lambda:None,
        set_external_clock_enabled=flags.append,set_paused=lambda *_:None)
    StudioPlaybackFlowMixin._retry_audio_output(page)
    assert flags==[False]


def test_audio_only_routing_cannot_reenable_a_suppressed_sequence_clock():
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    page=SimpleNamespace(_silent_preview_selected=True)
    video=SimpleNamespace(_studio_page=lambda:page,_external_clock_provider=lambda:{},
        _external_clock_enabled=False,_external_clock_sequence=-1,_external_clock_source_generation=-1)
    page.video=video
    MpvCanvas.set_external_clock_enabled(video,True)
    assert not video._external_clock_enabled
    page._silent_preview_selected=False
    MpvCanvas.set_external_clock_enabled(video,True)
    assert video._external_clock_enabled
