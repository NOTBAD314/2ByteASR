from types import SimpleNamespace
from twobyteasr.studio.studio_video_canvas import MpvCanvas


def canvas(payload,owner=(0,1,1),sequence=100):
    adopted=[]
    clock=SimpleNamespace(generation=3,snapshot=lambda:SimpleNamespace(actor_sequence=500,source='audio_engine_clock'),
        observe=lambda *a,**kw:(kw,True,''))
    obj=SimpleNamespace(_studio_page=lambda:None,_external_clock_enabled=True,
        _external_clock_provider=lambda:payload,_external_clock_sequence=sequence,
        _external_clock_owner=owner,_external_clock_source_generation=1,
        _playback_clock=clock,_paused=True,_playback_rate=1.,_clock_only=True,_project_time_mapping_enabled=False,
        _source_position_to_project_ms=lambda seconds,**_:seconds*1000,visual_position=lambda:12.,
        _adopt_playback_snapshot=adopted.append,_complete_external_clock_startup=lambda *_:None)
    return obj,adopted


def test_new_endpoint_counter_can_restart_at_one_without_freezing_audio_only_playhead():
    payload=dict(source_path='clip.wav',state='PAUSED',transport_generation=(3,0),
        session_generation=0,endpoint_generation=2,source_generation=1,clock_sequence=1,estimated_source_ms=12000,paused=True)
    obj,adopted=canvas(payload)
    assert MpvCanvas._observe_external_clock(obj)
    assert len(adopted)==1 and adopted[0]['discontinuity']


def test_retired_endpoint_counter_cannot_return_even_if_its_sequence_is_higher():
    payload=dict(source_path='clip.wav',state='PAUSED',transport_generation=(3,0),
        session_generation=0,endpoint_generation=1,source_generation=1,clock_sequence=999,estimated_source_ms=8000,paused=True)
    obj,adopted=canvas(payload,owner=(0,2,1),sequence=1)
    assert not MpvCanvas._observe_external_clock(obj) and not adopted
