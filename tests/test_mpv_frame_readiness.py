import threading
from types import SimpleNamespace

from twobyteasr.playback.frame_readiness import video_frame_witness
from twobyteasr.playback.studio_mpv import _MpvCommandActor


def actor_fixture():
    seek = dict(generation=4, target=12., perf_counter=1.)
    controller = SimpleNamespace(source_epoch=4, _subtitle_binding_epoch=3,
        _subtitle_media_path='C:/fixture.mp4', applied_seek_state=lambda:dict(seek))
    actor = _MpvCommandActor.__new__(_MpvCommandActor)
    actor.controller = controller
    actor._source_generation = 4
    actor._properties_lock = threading.Lock()
    actor._frame_observation = {'status':'awaiting_restart','source_generation':4}
    actor._frame_witness_request = None
    actor._property_sequence = 0
    actor._position_observation = {}
    actor._seek_target = 12.
    actor._stopping = False
    controller._advance_source_epoch = lambda value: setattr(controller,'source_epoch',max(value,controller.source_epoch))
    # Actual bundled mpv shape: there is no pts field.
    state = {'path':'C:/fixture.mp4','seeking':False,'time-pos':12.,
        'video-frame-info':{'picture-type':'I','interlaced':False,'tff':False,
                            'repeat':False,'estimated-smpte-timecode':'00:00:12;00'}}
    actor._properties = dict(state, **{'container-fps':60.,'pause':True})
    calls = []
    actor.exchange = lambda command, **kwargs: (calls.append(command) or {'data':state[command[1]]})
    return actor, seek, state, calls


def test_real_frame_metadata_needs_a_matching_restart_not_only_a_seek_ack():
    actor, seek, state, calls = actor_fixture()
    video = SimpleNamespace(_media_path='C:/fixture.mp4',
        _playback_clock=SimpleNamespace(generation=4,exact_seek_pending=False),
        controller=SimpleNamespace(observed_frame=actor.frame_observation))
    assert not video_frame_witness(video)['ready']
    actor._capture_frame_witness(4,3,dict(seek),2.)
    observed = video_frame_witness(video)
    assert observed['ready'] and observed['frame_info'] == state['video-frame-info']
    assert 'pts' not in observed['frame_info']
    assert len(calls) == 4
    video._playback_clock.generation = 5
    assert video_frame_witness(video)['status'] == 'stale_generation'
    video._playback_clock.generation = 4
    video.controller._subtitle_binding_epoch = 4
    assert video_frame_witness(video)['status'] == 'stale_media_epoch'
    video.controller._subtitle_binding_epoch = 3
    video._media_path = 'C:/other.mp4'
    assert video_frame_witness(video)['status'] == 'stale_source'


def test_queued_old_restart_does_no_ipc_and_cannot_overwrite_new_seek():
    actor, seek, state, calls = actor_fixture()
    old = dict(seek)
    seek['perf_counter'] = 2.
    actor._capture_frame_witness(4,3,old,1.5)
    assert not calls and actor.frame_observation()['status'] == 'awaiting_restart'
    actor._capture_frame_witness(4,2,dict(seek),2.5)
    assert not calls


def test_a_frame_at_a_different_target_is_not_ready():
    actor, seek, state, calls = actor_fixture()
    state['time-pos'] = 8.
    actor._capture_frame_witness(4,3,dict(seek),2.)
    assert actor.frame_observation()['status'] == 'frame_or_target_not_ready'


def test_restart_before_matching_command_ack_is_ignored():
    actor, seek, state, calls = actor_fixture()
    seek['generation'] = 3
    posts = []
    actor.post = lambda *args, **kwargs: posts.append(args)
    actor._queue_frame_witness()
    assert not posts and not calls
    # A later ACK/property notification cannot adopt that discarded old event.
    seek.update(generation=4,perf_counter=2.)
    actor._handle_event({'event':'property-change','name':'video-frame-info','data':state['video-frame-info']})
    assert not posts and not calls and actor._frame_witness_request is None


def test_new_seek_during_query_rejects_the_entire_witness():
    actor, seek, state, calls = actor_fixture()
    original = actor.exchange
    def exchange(command, **kwargs):
        result = original(command, **kwargs)
        actor.controller.source_epoch = 5
        return result
    actor.exchange = exchange
    actor._capture_frame_witness(4,3,dict(seek),2.)
    assert actor.frame_observation()['status'] == 'awaiting_restart'


def test_same_generation_seek_during_query_cannot_reuse_previous_ack():
    actor,seek,state,calls=actor_fixture()
    original=actor.exchange
    def exchange(command,**kwargs):
        result=original(command,**kwargs)
        if len(calls)==1:actor.begin_seek(4,20.)
        return result
    actor.exchange=exchange
    actor._capture_frame_witness(4,3,dict(seek),2.)
    assert actor.frame_observation()['status']=='awaiting_restart'


def queued_actor():
    actor,seek,state,calls=actor_fixture()
    posts=[]
    actor.post=lambda callback,**kwargs:posts.append(callback) or True
    return actor,seek,state,calls,posts


def test_late_frame_refreshes_qualified_restart_without_a_screenshot():
    actor,seek,state,calls,posts=queued_actor()
    late=dict(state['video-frame-info'])
    state['video-frame-info']=None;actor._properties['video-frame-info']=None
    actor._queue_frame_witness();posts.pop(0)()
    request=actor._frame_witness_request
    assert actor.frame_observation()['status']=='frame_or_target_not_ready' and request['attempts']==1
    state['video-frame-info']=late
    actor._handle_event({'event':'property-change','name':'video-frame-info','data':late})
    # Other readiness events coalesce, and scheduling does not consume budget.
    actor._handle_event({'event':'property-change','name':'seeking','data':False})
    actor._handle_event({'event':'property-change','name':'time-pos','data':12.})
    assert len(posts)==1 and request['attempts']==1 and len(calls)==4
    posts.pop(0)()
    assert actor.frame_observation()['status']=='ready' and len(calls)==8
    assert actor._frame_witness_request is None and request['attempts']==2
    actor._handle_event({'event':'property-change','name':'video-frame-info','data':late})
    assert not posts


def test_late_properties_without_a_qualified_restart_do_no_queries():
    actor,seek,state,calls,posts=queued_actor()
    actor._handle_event({'event':'property-change','name':'video-frame-info','data':state['video-frame-info']})
    assert not posts and not calls
    assert actor.frame_observation()['status']=='awaiting_restart'


def test_restart_before_ack_cannot_reuse_previous_ack_in_same_generation():
    actor,seek,state,calls,posts=queued_actor()
    actor.begin_seek(4,12.)
    actor._queue_frame_witness()
    assert not posts
    seek['perf_counter']=2.
    actor._handle_event({'event':'property-change','name':'video-frame-info','data':state['video-frame-info']})
    assert not posts and not calls
    # Only a subsequent qualified restart can start a witness.
    actor._queue_frame_witness();posts.pop(0)()
    assert actor.frame_observation()['status']=='ready'


def test_frame_event_received_during_first_query_is_not_lost():
    actor,seek,state,calls,posts=queued_actor()
    late=dict(state['video-frame-info']);state['video-frame-info']=None
    actor._properties['video-frame-info']=None
    original=actor.exchange
    def exchange(command,**kwargs):
        result=original(command,**kwargs)
        if command==['get_property','video-frame-info'] and state['video-frame-info'] is None:
            state['video-frame-info']=late
            actor._handle_event({'event':'property-change','name':'video-frame-info','data':late})
        return result
    actor.exchange=exchange
    actor._queue_frame_witness();posts.pop(0)()
    assert len(posts)==1 and actor.frame_observation()['status']=='frame_or_target_not_ready'
    posts.pop(0)()
    assert actor.frame_observation()['status']=='ready' and len(calls)==8


def test_new_ack_or_media_rejects_queued_late_frame_refresh():
    for mutation in ('ack','media','generation'):
        actor,seek,state,calls,posts=queued_actor()
        actor._queue_frame_witness()
        if mutation=='ack':seek['perf_counter']=2.
        elif mutation=='media':actor.controller._subtitle_binding_epoch=4
        else:actor.begin_seek(5,20.)
        posts.pop(0)()
        assert not calls and actor._frame_witness_request is None
        assert actor.frame_observation()['status']=='awaiting_restart'


def test_late_frame_queries_are_bounded_by_executed_work():
    actor,seek,state,calls,posts=queued_actor()
    state['video-frame-info']=None
    actor._queue_frame_witness();request=actor._frame_witness_request
    posts.pop(0)()
    for index in range(12):
        actor._handle_event({'event':'property-change','name':'video-frame-info',
                            'data':{'picture-type':'I','estimated-frame-number':index}})
        if posts:posts.pop(0)()
    assert request['attempts']==actor.FRAME_WITNESS_QUERY_LIMIT
    assert len(calls)==4*actor.FRAME_WITNESS_QUERY_LIMIT
    assert actor._frame_witness_request is None and not posts
    assert actor.frame_observation()['status']=='frame_or_target_not_ready'


def test_close_discards_pending_frame_refresh_without_ipc():
    from collections import deque
    actor,seek,state,calls,posts=queued_actor()
    actor._condition=threading.Condition();actor._requests=deque()
    actor._drop_pipe=lambda:None;actor._thread=SimpleNamespace(is_alive=lambda:False)
    actor._queue_frame_witness()
    actor.close()
    posts.pop(0)()
    assert actor._frame_witness_request is None and not calls

def test_seek_to_start_lands_on_a_late_first_picture():
    """User's 20-minute FLV (2026-10-28): audio at 0.013 s, video at 0.077 s,
    so mpv shows its first picture at 0.064 for a seek to 0 and the Studio
    timed out after 34 s waiting for a frame at 0."""
    from twobyteasr.playback.studio_mpv import MpvController
    for first in (0.064, None):
        actor, seek, state, calls = actor_fixture()
        seek['target'] = 0.
        state['time-pos'] = 0.064
        firsts = {} if first is None else {'C:/fixture.mp4': first}
        actor.controller.first_picture_seconds = lambda path, firsts=firsts: firsts.get(path)
        actor._capture_frame_witness(4,3,dict(seek),2.)
        observed = actor.frame_observation()
        assert observed['status'] == 'ready', first
        assert observed['landing_target'] == (0.064 if first else 0.)
    controller = MpvController.__new__(MpvController)
    controller._first_pictures = {}
    controller.set_first_picture('C:/fixture.mp4', .998)
    assert controller.first_picture_seconds('c:/FIXTURE.mp4') == .998
    controller.set_first_picture('C:/fixture.mp4', None)
    assert controller.first_picture_seconds('C:/fixture.mp4') is None


def test_first_picture_allowance_does_not_accept_other_positions():
    cases = [(12., 12.5, .064), (0., 3., None), (0., .5, .064), (.5, .9, .064)]
    for target, position, first in cases:
        actor, seek, state, calls = actor_fixture()
        seek['target'] = target
        state['time-pos'] = position
        actor.controller.first_picture_seconds = lambda path, first=first: first
        actor._capture_frame_witness(4,3,dict(seek),2.)
        assert actor.frame_observation()['status'] == 'frame_or_target_not_ready', (target, position)


def test_first_picture_comes_from_the_recorded_probe():
    from twobyteasr.playback.frame_readiness import first_picture_seconds
    asset = SimpleNamespace(canonical_source='H:/record/a.flv', video_metadata={
        'has_video': True, 'first_pts_ms': 77.0, 'start_time_ms': 77.0, 'source_start_ms': 13.0})
    project = SimpleNamespace(media_pool=[asset])
    assert abs(first_picture_seconds(project, 'h:/RECORD/A.flv') - .064) < 1e-9
    assert first_picture_seconds(project, 'C:/cache/continuous.mkv') is None
    asset.video_metadata = {'has_video': False, 'start_time_ms': 0.}
    assert first_picture_seconds(project, 'H:/record/a.flv') is None
    asset.video_metadata = {'width': 1920}
    assert first_picture_seconds(project, 'H:/record/a.flv') is None
    assert first_picture_seconds(None, 'H:/record/a.flv') is None

