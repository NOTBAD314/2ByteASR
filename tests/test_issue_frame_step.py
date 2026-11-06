"""Issue #11: repeat policy and real-frame clock acknowledgements."""
import time
from types import SimpleNamespace, MethodType

import pytest
from twobyteasr.playback.playback_clock import PlaybackClock
from twobyteasr.playback.studio_mpv import MpvController
from twobyteasr.studio.studio_video_canvas import MpvCanvas
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def canvas(position=2.5, mapping=lambda seconds:seconds*1000):
    observation=dict(position=position,source_generation=0,actor_sequence=1,
        observed_monotonic_ts=time.monotonic(),paused=True,playback_rate=1.)
    posted=[];samples=[]
    controller=SimpleNamespace(running=True,source_epoch=0,observed_position=lambda:dict(observation),
        post_frame_step=lambda backwards,intent:(posted.append(intent) or True))
    clock=PlaybackClock();clock.force_position(mapping(position),paused=True)
    value=SimpleNamespace(controller=controller,_playback_clock=clock,_playback_rate=1.,_paused=True,
        _frame_step_timer=SimpleNamespace(start=lambda:None,stop=lambda:None),
        _source_position_to_project_ms=mapping,visual_position=lambda:clock.snapshot().presentation_media_ms/1000,
        set_paused=lambda paused:clock.set_local_state(clock.snapshot().presentation_media_ms,paused=paused,reason='pause'),
        _adopt_playback_snapshot=lambda sample:samples.append(sample))
    for name in ('frame_step','cancel_frame_step','_finish_frame_step','_consume_frame_step'):
        setattr(value,name,MethodType(getattr(MpvCanvas,name),value))
    return value,observation,posted,samples


@pytest.mark.parametrize('backwards,target',[(True,2.4666333333333),(False,2.5333666666667)])
def test_actual_noninteger_frame_position_updates_paused_clock(backwards,target):
    value,observation,posted,samples=canvas()
    assert value.frame_step(backwards)
    assert not samples
    posted[0]['started']=True
    observation.update(position=target,actor_sequence=2,observed_monotonic_ts=time.monotonic())
    value._consume_frame_step()
    assert samples[-1].presentation_media_ms==pytest.approx(target*1000)
    assert samples[-1].source=='frame_step'
    assert value._frame_step_pending is None


def test_cut_clip_source_mapping_is_used_for_real_frame_acknowledgement():
    mapping=lambda seconds:500+(seconds*1000-2000)/1.25
    value,observation,posted,samples=canvas(mapping=mapping)
    value.frame_step(True);posted[0]['started']=True
    observation.update(position=2.4666333333333,actor_sequence=2)
    value._consume_frame_step()
    assert samples[-1].presentation_media_ms==pytest.approx(mapping(observation['position']))


def test_hold_is_bounded_and_release_cancels_not_yet_executed_intent():
    value,observation,posted,samples=canvas()
    assert value.frame_step(False,repeat=True)
    for _ in range(100):assert not value.frame_step(False)
    assert len(posted)==1
    value.cancel_frame_step()
    assert posted[0]['cancelled'] and value._frame_step_pending is None
    value._consume_frame_step()
    assert not samples


def test_quick_single_click_still_executes_once_after_key_release():
    value,observation,posted,samples=canvas()
    assert value.frame_step(False)
    value.cancel_frame_step()
    assert not posted[0]['cancelled'] and value._frame_step_pending is posted[0]
    value.cancel_frame_step(cancel_initial=True)
    assert posted[0]['cancelled'] and value._frame_step_pending is None


def test_native_and_qt_same_event_execute_once_and_other_commands_do_not_repeat():
    dispatched=[]
    page=SimpleNamespace(_shortcut_lookup={'Left':'frame_left','Space':'play_pause'},_review_mode=False,
        _dispatch_shortcut_sequence=lambda sequence:(dispatched.append(sequence) or True))
    dispatch=lambda sequence,**kw:SubtitleStudioPage._dispatch_shortcut_key(page,sequence,**kw)
    assert dispatch('Left',timestamp=100,native=True)
    assert dispatch('Left',timestamp=100)
    assert dispatch('Left',timestamp=200,native=True,auto_repeat=True)
    assert not dispatch('Space',timestamp=300,native=True,auto_repeat=True)
    assert dispatched==['Left','Left']


def test_stale_generation_cannot_move_clock_after_another_seek():
    value,observation,posted,samples=canvas()
    value.frame_step(True);posted[0]['started']=True
    value._playback_clock.begin_seek(5000)
    observation.update(position=2.4666333333333,actor_sequence=2)
    value._consume_frame_step()
    assert not samples and value._frame_step_pending is None
    assert value._playback_clock.snapshot().presentation_media_ms==5000


def test_released_native_intent_never_reaches_the_player_actor():
    callbacks=[];commands=[]
    controller=SimpleNamespace(observed_position=lambda:{'actor_sequence':1,'source_generation':0,'position':2.5},
        frame_step=lambda direction:commands.append(direction),
        _post=lambda callback,**kw:(callbacks.append(callback) or True))
    intent={'cancelled':False}
    assert MpvController.post_frame_step(controller,False,intent=intent)
    intent['cancelled']=True
    callbacks[0]()
    assert not commands


@pytest.mark.parametrize('fps,expected',[(25,1.96),(30000/1001,1.968)])
def test_backward_cut_boundary_uses_source_rate_then_real_seek(fps,expected):
    from twobyteasr.timeline.studio_edit_sequence import VideoSegment,EditSequence
    from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin
    first=VideoSegment('a','fixture.mp4',0,2000,0,2000)
    second=VideoSegment('b','fixture.mp4',4000,6000,2000,4000)
    sequence=EditSequence(source_path='fixture.mp4',source_duration_ms=6000,segments=[first,second])
    seeks=[]
    page=SimpleNamespace(video=SimpleNamespace(controller=SimpleNamespace(observed_property=lambda *a:fps)),
        _seek=lambda seconds:seeks.append(seconds))
    assert StudioPlaybackFlowMixin._step_across_mapped_boundary(page,sequence,second,3960)
    assert seeks==[expected]
    assert StudioPlaybackFlowMixin._step_across_mapped_boundary(page,sequence,first,2000)
    assert seeks[-1]==2.


@pytest.mark.parametrize('mode',['ready','project_changed','cancelled','editor'])
def test_one_deferred_initial_key_waits_without_surviving_context_changes(monkeypatch,mode):
    from twobyteasr.studio import studio_playback_flow as flow
    callbacks=[];frames=[];focus=[False]
    monkeypatch.setattr(flow,'QTimer',SimpleNamespace(singleShot=lambda delay,callback:callbacks.append(callback)))
    clock=SimpleNamespace(exact_seek_pending=True)
    page=SimpleNamespace(project=object(),video=SimpleNamespace(controller=object(),_playback_clock=clock),
        isVisible=lambda:True,_editing_has_focus=lambda:focus[0],_frame_step=lambda direction:frames.append(direction))
    flow.StudioPlaybackFlowMixin._defer_frame_step(page,True,None)
    callbacks.pop(0)()
    assert len(callbacks)==1 and not frames
    clock.exact_seek_pending=False
    if mode=='project_changed':page.project=object()
    if mode=='cancelled':page._deferred_frame_step=None
    if mode=='editor':focus[0]=True
    callbacks.pop(0)()
    assert frames==([True] if mode=='ready' else [])


def test_pause_wins_even_when_direct_frame_request_meets_a_seek():
    value,observation,posted,samples=canvas()
    pauses=[];value._paused=False;value.set_paused=lambda paused,**kwargs:pauses.append(paused)
    value._playback_clock.begin_seek(4000)
    assert not value.frame_step(True)
    assert pauses==[True] and not posted


def test_actor_samples_actual_paused_position_instead_of_stale_cache():
    callbacks=[];frames=[]
    controller=SimpleNamespace(source_epoch=1,
        observed_position=lambda:{'actor_sequence':7,'source_generation':1,'position':3.0},
        _send=lambda command:{'data':3.04},frame_step=lambda backwards:frames.append(backwards),
        _post=lambda callback,**kwargs:(callbacks.append(callback) or True))
    intent={'cancelled':False,'source_epoch':1}
    assert MpvController.post_frame_step(controller,True,intent=intent)
    callbacks[0]()
    assert frames==[True] and intent['baseline_position']==3.04
