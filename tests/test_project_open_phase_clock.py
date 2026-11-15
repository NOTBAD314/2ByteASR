from collections import deque
from types import SimpleNamespace


def test_phase_interval_is_named_separately_from_next_stage_and_open_total(monkeypatch):
    from twobyteasr.studio import studio_loading
    from twobyteasr.diagnostics import event_log
    clock=[10.]
    monkeypatch.setattr(studio_loading.time,'perf_counter',lambda:clock[0])
    emitted=[]
    monkeypatch.setattr(event_log,'emit',lambda name,**fields:emitted.append(fields))
    loading=SimpleNamespace(started=10.,generation=1,events=deque(),
        _diagnostic_phase=None,_diagnostic_phase_started=10.,changed=SimpleNamespace(emit=lambda:None))
    studio_loading.StudioLoadingSession._record(loading,'stage',stage='读取工程')
    clock[0]=10.2
    studio_loading.StudioLoadingSession._record(loading,'stage',stage='建立时间轴')
    assert emitted[-1]['phase_name']=='读取工程'
    assert emitted[-1]['phase_elapsed_ms']==200
    assert emitted[-1]['elapsed_ms']==200
    clock[0]=10.5
    studio_loading.StudioLoadingSession._record(loading,'complete_stage',stage='建立时间轴')
    assert emitted[-1]['phase_name']=='建立时间轴'
    assert emitted[-1]['phase_elapsed_ms']==300
    assert emitted[-1]['elapsed_ms']==500
    assert emitted[-1]['operation_id']==emitted[0]['operation_id']
