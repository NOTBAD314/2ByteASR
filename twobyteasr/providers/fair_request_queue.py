"""Bounded stage-fair admission with one adaptive local budget per account."""
from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections import defaultdict,deque
from urllib.parse import urlsplit


class FairRequestQueue:
    def __init__(self, workers, *, max_pending=128):
        self.workers, self.max_pending = workers, max_pending
        self.condition=threading.Condition()
        self.rows=defaultdict(deque)
        self.order=deque()
        self.accounts={}
        self.local=threading.local()
        self.pending=0

    def _identity(self,item):
        endpoint=getattr(item.runtime.adapter,'endpoint',{}) or {}
        host=urlsplit(str(endpoint.get('base_url') or endpoint.get('url') or '')).netloc
        credential=str(endpoint.get('api_key') or '')
        transport=str(item.runtime.transport)
        key=hashlib.sha256((transport+'\0'+host+'\0'+credential).encode()).hexdigest()
        from ..system.task_resources import live_budget
        ceiling=min(self.workers,live_budget().ai_requests) if host in {'api.deepseek.com'} else min(4,self.workers)
        return key,max(1,ceiling)

    def put(self,item,block=True,timeout=None):
        # Submission stays cheap even from a GUI-triggered operation. The
        # callers' bounded workers supply backpressure before this last gate.
        with self.condition:
            if self.pending>=self.max_pending:raise queue.Full
            lane=(item.sort_priority,item.lane or item.runtime.stage)
            if lane not in self.rows or not self.rows[lane]:self.order.append(lane)
            self.rows[lane].append(item);self.pending+=1
            self.condition.notify_all()

    def get(self,block=True,timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        with self.condition:
            while True:
                priorities=sorted({lane[0] for lane in self.order})
                for priority in priorities:
                    for _ in range(len(self.order)):
                        lane=self.order.popleft()
                        if not self.rows[lane]:continue
                        self.order.append(lane)
                        if lane[0]!=priority:continue
                        item=self.rows[lane][0]
                        key,ceiling=self._identity(item)
                        state=self.accounts.setdefault(key,dict(active=0,limit=ceiling,ceiling=ceiling,
                            cooldown=0.,successes=0,timeouts=0))
                        state['ceiling']=ceiling;state['limit']=min(state['limit'],ceiling)
                        expired=item.handle.cancelled or time.monotonic()>=item.handle.deadline_monotonic
                        if not expired and (state['active']>=state['limit'] or time.monotonic()<state['cooldown']):
                            continue
                        self.rows[lane].popleft();self.pending-=1
                        if not self.rows[lane]:self.order.remove(lane)
                        state['active']+=1;self.local.account=key
                        return item
                if not block:raise queue.Empty
                if deadline is not None and time.monotonic()>=deadline:raise queue.Empty
                self.condition.wait(.05)

    def task_done(self,*,error=None):
        with self.condition:
            key=getattr(self.local,'account',None)
            if key is None:return
            state=self.accounts[key];state['active']=max(0,state['active']-1)
            category=str(getattr(error,'category',''))
            limited=category in {'rate_limit','rate_limited'}
            if 'timeout' in category:state['timeouts']+=1
            if limited or state['timeouts']>=3:
                state['limit']=max(1,state['limit']//2)
                state['cooldown']=time.monotonic()+(3. if limited else 1.)
                state['successes']=state['timeouts']=0
            elif error is None:
                state['successes']+=1
                if state['successes']>=8:
                    state['limit']=min(state['ceiling'],state['limit']+1)
                    state['successes']=0
                state['timeouts']=0
            self.local.account=None
            self.condition.notify_all()

    def qsize(self):
        with self.condition:return self.pending

    def snapshot(self):
        with self.condition:
            return dict(queued=self.pending,active=sum(row['active'] for row in self.accounts.values()),
                local_limits=[dict(active=row['active'],limit=row['limit'],ceiling=row['ceiling']) for row in self.accounts.values()])
