"""Measured, non-additive authoring milestones. Unknown provider internals stay null."""
import json
import time
from pathlib import Path


class DesignTiming:
    def __init__(self,path):
        self.path=Path(path);self.start=time.monotonic()
        self.value=dict(version=1,started_at=time.time(),milestones={},
            provider_queue_ms=None,provider_reasoning_ms=None,application_queue_ms=None,
            actual_calls=None,application_calls=1,attempt_events=[],terminal='running',intervals_overlap=True)
        self.mark('application_queued')

    def mark(self,name):
        if name in self.value['milestones']:return
        self.value['milestones'].setdefault(name,dict(at=time.time(),elapsed_ms=round((time.monotonic()-self.start)*1000,3)))
        self.save()

    def event(self,kind,detail=None):
        self.value['last_activity_at']=time.time()
        if kind=='request_identity':
            self.mark('dispatched')
            try:self.value['attempt_events'].append(json.loads(detail))
            except (TypeError,ValueError):pass
            submitted=self.value['milestones'].get('submitted_to_provider',{}).get('elapsed_ms')
            if submitted is not None:self.value['application_queue_ms']=self.value['milestones']['dispatched']['elapsed_ms']-submitted
        elif kind in ('transport','provider_event','thinking','thinking_end','delta','final','heartbeat'):
            self.mark('first_provider_event')
        if kind=='delta':self.mark('first_body')
        if kind=='final':self.mark('response_complete')

    def finish(self,status,trace):
        self.value['terminal']=status;self.mark('terminal')
        times=trace.get('timings',{})
        queue=times.get('queue_ms',times.get('queue_wait_ms'))
        if queue is not None:self.value['application_queue_ms']=queue
        self.value['transport_timings']=times
        attempts=self.value['attempt_events']
        self.value['actual_calls']=len(attempts) if attempts else (0 if trace.get('dispatched') is False else times.get('attempts',1 if trace.get('dispatched') else None))
        self.value['retry_count']=max(0,len(attempts)-1) if attempts else times.get('retry_count')
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text(json.dumps(self.value,ensure_ascii=False,indent=2),'utf8')
