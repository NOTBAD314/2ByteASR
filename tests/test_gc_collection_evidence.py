"""The decision receipt observes the original predicate, with no memory reread."""
from twobyteasr.playback import playback_gc_budget as policy
from twobyteasr.diagnostics import event_log


def prepare(monkeypatch,current,baseline,counts=(5,0,11),clock=31.):
    reads=[];times=[];events=[];collected=[]
    def memory():reads.append(current);return current
    def now():times.append(clock);return clock
    collector=policy.GuiThreadCollector(memory_reader=memory,clock=now)
    collector.active=True;collector._baseline=baseline;collector._last_full=0.
    times.clear()
    monkeypatch.setattr(policy.gc,'isenabled',lambda:False)
    monkeypatch.setattr(policy.gc,'get_count',lambda:counts)
    monkeypatch.setattr(policy.gc,'get_threshold',lambda:(700,10,10))
    monkeypatch.setattr(policy.gc,'collect',lambda generation=2:collected.append(generation) or 7)
    monkeypatch.setattr(event_log,'emit',lambda name,**fields:events.append((name,fields)))
    return collector,reads,times,events,collected


def test_actual_gen2_uses_the_private_value_that_decided_the_collection(monkeypatch):
    mib=1024*1024
    collector,reads,times,events,collected=prepare(monkeypatch,200*mib,100*mib)
    collector.tick()
    assert collected==[2] and collector.collections==[0,0,1]
    assert reads==[200*mib] and not times
    assert len(events)==1
    name,event=events[0]
    assert name=='gc.collection_decision' and event['owner']=='gui_thread_collector'
    assert event['private_bytes']==200*mib and event['baseline_private_bytes']==100*mib
    assert event['full_growth_threshold_bytes']==64*mib
    assert event['counts']==(5,0,11) and event['thresholds']==(700,10,10)
    assert event['full_due_branch']=='private_growth' and event['collected']==7


def test_unavailable_memory_uses_same_existing_elapsed_fallback(monkeypatch):
    collector,reads,times,events,collected=prepare(monkeypatch,None,100,clock=31.)
    collector.tick()
    assert collected==[2] and reads==[None] and times==[31.]
    event=events[0][1]
    assert event['private_bytes'] is None and event['full_growth_threshold_bytes'] is None
    assert event['full_due_branch']=='unavailable_memory_elapsed'
    assert event['elapsed_since_full_s']==31.


def test_undue_full_collection_still_allows_existing_young_collection_without_new_event(monkeypatch):
    collector,reads,times,events,collected=prepare(monkeypatch,100,100,counts=(701,0,11))
    collector.tick()
    assert collected==[0] and events==[] and reads==[100]


def test_receipt_uses_precollection_holder_count_and_logging_cannot_preempt_gc(monkeypatch):
    order=[];events=[]
    monkeypatch.setattr(policy,'_holders',{'held-at-decision'})
    def collect():
        order.append('collect');policy._holders.clear();return 9
    def emit(name,**fields):order.append('log');events.append(fields)
    monkeypatch.setattr(policy.gc,'collect',collect)
    monkeypatch.setattr(event_log,'emit',emit)
    assert policy._collect_observed(owner='fixture',reason='explicit')==9
    assert order==['collect','log'] and events[0]['full_gc_holders']==1
    def failing(*args,**kwargs):raise RuntimeError('logging failed')
    monkeypatch.setattr(event_log,'emit',failing)
    assert policy._collect_observed(owner='fixture',reason='explicit')==9
