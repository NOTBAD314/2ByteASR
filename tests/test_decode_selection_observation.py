"""Execute the worker's real demand/selection loop with deterministic I/O.

No player, GUI, encoding, clock policy or real worker process is involved.
Only codec/pixel I/O and thread startup are replaced; the production selection
and budget calculations execute unchanged with diagnostics on and off.
"""
from fractions import Fraction
import sys
import threading
from types import SimpleNamespace

import pytest

from twobyteasr.playback import video_decode_worker as worker


def run_worker(monkeypatch, *, rate, paused, detailed, advances=()):
    captured = {'clock':10., 'headers':[]}
    advances = iter(advances)
    request = dict(epoch=1, generation=4, path='fixture', source_ms=225,
                   clock_observed_at=10., paused=paused, rate=rate,
                   max_size=(16,9), capture_pixel_costs=detailed)
    class Condition:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def notify_all(self): pass
        def notify(self): pass
        def wait(self, timeout=None):
            captured['wait'] = timeout
            captured['headers'].append(captured['outgoing'][0][0])
            advance = next(advances, None)
            if advance is None:
                captured['closed'].set()
            else:
                captured['clock'] += advance
    class Thread:
        def __init__(self, target, **kwargs): self.target=target
        def start(self):
            cells = dict(zip(self.target.__code__.co_freevars,
                             (cell.cell_contents for cell in self.target.__closure__)))
            if self.target.__name__ == 'reader':
                cells['latest'][0] = dict(request)
                captured['closed'] = cells['closed']
            else:
                captured['outgoing'] = cells['outgoing']
    stream = SimpleNamespace(sample_aspect_ratio=1, start_time=0,
        time_base=Fraction(1,1000), codec_context=SimpleNamespace(name='fixture'))
    frames = [SimpleNamespace(pts=pts,dts=pts,time_base=Fraction(1,1000),
                              format=SimpleNamespace(name='fixture')) for pts in range(0,1000,20)]
    container = SimpleNamespace(start_time=0, seek=lambda *args,**kwargs:None,
                                decode=lambda stream: iter(frames), close=lambda:None)
    monkeypatch.setattr(worker,'threading',SimpleNamespace(Condition=Condition,
                         Thread=Thread,Event=threading.Event))
    monkeypatch.setattr(worker,'sys',SimpleNamespace(platform='unit',stderr=sys.stderr))
    monkeypatch.setattr(worker.time,'perf_counter',lambda:captured['clock'])
    monkeypatch.setattr(worker,'open_decoder',lambda *args:(container,stream,{}))
    def raster(frame,sar,size,*,costs=None):
        costs.update(pixel_bytes=4,input_pixels=[1,1],raster_pixels=[1,1])
        return 1,1,b'abcd'
    monkeypatch.setattr(worker,'display_bgra',raster)
    old_profile = sys.getprofile()
    def observe(frame,event,arg):
        if event=='return' and frame.f_code is worker.main.__code__:
            captured['budget'] = frame.f_locals['next_publish']
            captured['published_pts'] = frame.f_locals['published_pts']
    try:
        sys.setprofile(observe)
        assert worker.main() == 0
    finally:
        sys.setprofile(old_profile)
    header,pixels = captured['outgoing'][0]
    assert header.get('heartbeat') is not True, header
    return header,pixels,captured


@pytest.mark.parametrize('rate',[1.,2.,4.])
@pytest.mark.parametrize('paused',[False,True])
def test_diagnostics_preserve_real_worker_selection_pixels_and_deadline(monkeypatch,rate,paused):
    old,old_pixels,old_state=run_worker(monkeypatch,rate=rate,paused=paused,detailed=False)
    new,pixels,state=run_worker(monkeypatch,rate=rate,paused=paused,detailed=True)
    assert pixels == old_pixels == b'abcd'
    assert new['pts_ms'] == old['pts_ms'] == 220  # Latest real source PTS <=225, never240.
    assert new['requested_ms'] == old['requested_ms'] == 225
    assert new['generation'] == old['generation'] == 4
    assert new['epoch'] == old['epoch'] == 1
    assert state['budget'] == old_state['budget'] == pytest.approx(10+1/60)
    assert state['wait'] == old_state['wait']
    assert old['costs'] is None
    selection = new['costs']['selection']
    assert selection['budget_due_before'] == 0
    assert selection['budget_due_after'] == state['budget']
    assert selection['source_anchor_ms'] == selection['target_ms'] == 225
    assert selection['selected_pts_ms'] == 220 and selection['next_candidate_pts_ms'] == 240
    assert selection['target_computed_at'] == (None if paused else 10.)
    assert selection['rate'] == rate and selection['paused'] == paused


def test_existing_frame_context_preserves_target_and_selection_identity():
    from twobyteasr.playback.video_composition_worker import VideoCompositionWorker
    from twobyteasr.playback.video_decode_pipe import PipeFrame
    costs={'selection':{'target_ms':225,'budget_due_before':10.}}
    frame=PipeFrame(3,4,'fixture',225,220,1,1,memoryview(b'abcd'),costs=costs)
    context=VideoCompositionWorker._frame_context({'clip_id':'clip'},frame)
    assert context['requested_ms']==225 and context['pts_ms']==220
    assert context['generation']==4 and context['decode_epoch']==3
    assert context['pixel_costs']==costs


@pytest.mark.parametrize('rate',[1.,2.,4.])
def test_late_wake_selection_and_skipped_budget_slots_are_identical_with_probe(rate,monkeypatch):
    pattern=(1/60,.056,1/60)
    old,old_pixels,old_state=run_worker(monkeypatch,rate=rate,paused=False,detailed=False,advances=pattern)
    new,pixels,state=run_worker(monkeypatch,rate=rate,paused=False,detailed=True,advances=pattern)
    old_rows=old_state['headers'];new_rows=state['headers']
    assert len(old_rows)==len(new_rows)==4
    assert [r['pts_ms'] for r in old_rows]==[r['pts_ms'] for r in new_rows]
    assert [r['requested_ms'] for r in old_rows]==[r['requested_ms'] for r in new_rows]
    assert old_state['budget']==state['budget']
    assert pixels==old_pixels
    for row in new_rows:
        observed=row['costs']['selection']
        assert observed['selected_pts_ms']<=observed['target_ms']<observed['next_candidate_pts_ms']
        assert observed['selection_checked_at']<observed['budget_due_after']<=observed['selection_checked_at']+1/60+1e-10
    late=new_rows[2]['costs']['selection']
    assert late['selection_checked_at']-late['budget_due_before']>.03
