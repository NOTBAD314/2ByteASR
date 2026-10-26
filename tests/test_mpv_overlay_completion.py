"""Every accepted bitmap receives completion, including queue replacement."""
from collections import deque
import threading
from twobyteasr.playback.studio_mpv import _MpvCommandActor

def test_replaced_stopped_and_rejected_overlay_requests_complete_once():
    actor=object.__new__(_MpvCommandActor)
    actor._init_request_metrics()
    actor._condition=threading.Condition()
    actor._requests=deque()
    actor._stopping=False
    actor._thread=threading.current_thread()
    actor._drop_pipe=lambda:None
    events=[]
    assert actor.post(lambda:events.append('executed-old'),coalesce_key='overlay:0',on_discard=lambda:events.append('old-discarded'))
    assert actor.post(lambda:events.append('executed-new'),coalesce_key='overlay:0',on_discard=lambda:events.append('new-discarded'))
    assert events==['old-discarded']
    assert actor.request_metrics()['coalesced']==1
    actor.close()
    assert events==['old-discarded','new-discarded']
    assert actor.post(lambda:None,on_discard=lambda:events.append('rejected')) is False
    actor.close()
    assert events==['old-discarded','new-discarded','rejected']
