import queue
import threading
import time
from types import SimpleNamespace

import pytest

from twobyteasr.providers.fair_request_queue import FairRequestQueue


def request(lane,number,*,host='https://api.deepseek.com/v1',priority=0):
    runtime=SimpleNamespace(stage=lane,transport='http',adapter=SimpleNamespace(endpoint={'base_url':host,'api_key':'fixture'}))
    handle=SimpleNamespace(cancelled=False,deadline_monotonic=time.monotonic()+10)
    return SimpleNamespace(sort_priority=priority,lane=lane,runtime=runtime,handle=handle,number=number)


def test_grouping_and_translation_do_not_wait_behind_entire_polish_queue():
    broker=FairRequestQueue(4)
    for number in range(20):broker.put(request('polish',number))
    broker.put(request('group',100));broker.put(request('translation',200))
    lanes=[]
    for _ in range(3):
        row=broker.get();lanes.append(row.lane);broker.task_done()
    assert lanes==['polish','group','translation']


def test_account_budget_is_shared_across_stages_and_queue_is_bounded():
    broker=FairRequestQueue(2,max_pending=12)
    for number in range(12):broker.put(request(['polish','group','translation'][number%3],number))
    with pytest.raises(queue.Full):broker.put(request('group',50))
    lock=threading.Lock();active=peak=0;seen=[]
    def run():
        nonlocal active,peak
        while True:
            try:row=broker.get(timeout=.1)
            except queue.Empty:return
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.005)
            with lock:active-=1;seen.append(row.number)
            broker.task_done()
    threads=[threading.Thread(target=run) for _ in range(6)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(2)
    assert len(seen)==12 and peak==2 and broker.snapshot()['active']==0


def test_rate_limit_reduces_admission_and_does_not_resend_itself():
    broker=FairRequestQueue(8)
    broker.put(request('group',1));broker.get()
    broker.task_done(error=SimpleNamespace(category='rate_limited'))
    snapshot=broker.snapshot()
    assert snapshot['local_limits'][0]['limit']==4 and snapshot['queued']==0
