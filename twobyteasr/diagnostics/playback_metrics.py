"""Pure playback evidence calculations; capture clocks are named, never 'FPS'."""
from __future__ import annotations
import math
import statistics


def read_system_trace(path):
    """Read either ASCII/UTF-8 or BOM-prefixed PresentMon CSV after capture."""
    import csv
    with open(path,encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))

def distribution(values, *, budget_ms=1000/60):
    data=sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not data:
        return {'samples':0,'p50':None,'p95':None,'p99':None,'max':None,
                'over_budget':0,'over_50ms':0,'over_100ms':0,'budget_ms':budget_ms}
    quantile=lambda f:data[max(0,math.ceil(len(data)*f)-1)]
    return {'samples':len(data),'p50':statistics.median(data),'p95':quantile(.95),
            'p99':quantile(.99),'max':data[-1],'budget_ms':budget_ms,
            'over_budget':sum(x>budget_ms+.001 for x in data),
            'over_50ms':sum(x>50 for x in data),'over_100ms':sum(x>100 for x in data)}

def desktop_cadence(rows, start, end, *, source_fps, display_hz, rate=1., barcode=True):
    """DXGI LastPresentTime + frame content, with AccumulatedFrames loss audit.

    GDI/WGC acquisition timestamps cannot be substituted for these OS QPC
    timestamps. A missing capture or an occluded barcode yields UNVERIFIED.
    """
    expected=min(float(source_fps)*float(rate),float(display_hz))
    budget=1000/expected if expected>0 else 1000/60
    selected=[r for r in rows if start<=float(r['desktop_qpc_s'])<end]
    good=[r for r in selected if not barcode or int(r['frame_code'])>=0]
    key='frame_code' if barcode else 'roi_hash'
    changes=[r for i,r in enumerate(good) if i==0 or r[key]!=good[i-1][key]]
    times=[float(r['desktop_qpc_s']) for r in changes]
    intervals=[(b-a)*1000 for a,b in zip(times,times[1:])]
    stats=distribution(intervals,budget_ms=budget)
    lost=sum(max(0,int(r['accumulated_frames'])-1) for r in selected)
    fraction=len(good)/max(1,len(selected))
    lost_fraction=lost/max(1,len(selected)+lost)
    duration=max(0,end-start)
    frequency=len(changes)/duration if duration else 0
    quality=[]
    if duration<15:quality.append('stable window shorter than 15 seconds')
    if expected<=0:quality.append('source FPS/display refresh missing')
    if len(selected)<max(100,duration*expected*.9):quality.append('insufficient desktop update samples')
    if fraction<.99:quality.append('frame-code valid fraction below 99 percent')
    if lost_fraction>.01:quality.append('DXGI accumulated update loss exceeds 1 percent')
    if any(float(b['desktop_qpc_s'])<=float(a['desktop_qpc_s']) for a,b in zip(selected,selected[1:])):
        quality.append('non-monotonic desktop QPC')
    valid=not quality
    # Include edge holds: a stopped last frame must not disappear from max.
    longest=max(intervals+([(times[0]-start)*1000,(end-times[-1])*1000] if times else [duration*1000]))
    performance=bool(frequency>=expected*.97 and stats['p95'] is not None
                     and stats['p95']<=budget*1.25 and stats['p99']<=budget*2.1 and longest<=100)
    return {'measurement':'DXGI desktop image content; OS LastPresentTime QPC, not physical scanout',
        'content_identity':'binary source frame number' if barcode else 'video ROI pixel hash (content changes only)',
        'measurement_valid':valid,'performance_pass':performance if valid and barcode else 'UNVERIFIED',
        'performance_scope':'source frame-code cadence' if barcode else 'ROI changes only; source-frame uniqueness needs pixel-to-PTS matching or ETW corroboration',
        'invalid_reasons':quality,'effective_seconds':duration,'samples':len(selected),
        'valid_fraction':fraction,'accumulated_updates_lost':lost,'lost_fraction':lost_fraction,
        'expected_different_frames_per_second':expected,'different_frames':len(changes),
        'different_frames_per_second':frequency,'change_intervals_ms':stats,
        'longest_repeat_upper_bound_ms':longest,
        'copy_decode_ms':distribution([float(r['copy_decode_ms']) for r in selected],budget_ms=budget),
        'acquisition_delay_ms':distribution([(float(r['acquired_qpc_s'])-float(r['desktop_qpc_s']))*1000 for r in selected],budget_ms=budget),
        'thresholds':{'min_fraction':.97,'p95_budgets':1.25,'p99_budgets':2.1,'max_hold_ms':100,
                      'valid_fraction':.99,'max_capture_loss_fraction':.01,'min_seconds':15}}


def system_cadence(rows,start,end,*,process_id,source_fps,display_hz,rate=1.):
    """PresentMon v2 CSV: CPU QPC + DisplayLatency gives system display QPC.

    Tracks exactly the audited mpv PID and a single stable swapchain. Submitted
    FrameTime and DisplayedTime are reported separately. No screen-content or
    physical photon claim is inferred from these ETW events.
    """
    def number(row,key):
        try:return float(row[key])
        except (ValueError,KeyError,TypeError):return None
    expected=min(source_fps*rate,display_hz);budget=1000/expected
    process=[r for r in rows if str(r.get('ProcessID'))==str(process_id) and r.get('Application','').lower()=='mpv.exe']
    shown=[]
    for row in process:
        cpu=number(row,'CPUStartQPCTime');latency=number(row,'DisplayLatency');duration=number(row,'DisplayedTime')
        if cpu is not None and latency is not None and duration is not None:
            at=(cpu+latency)/1000
            if start<=at<end:shown.append((at,row))
    shown.sort(key=lambda x:x[0]);chains={r['SwapChainAddress'] for _,r in shown}
    times=[at for at,_ in shown]
    intervals=distribution([(b-a)*1000 for a,b in zip(times,times[1:])],budget_ms=budget)
    duration=end-start;frequency=len(shown)/max(.001,duration)
    reasons=[]
    if duration<15:reasons.append('stable window shorter than 15 seconds')
    if len(shown)<100:reasons.append('too few system display samples for the audited PID')
    if len(chains)!=1:reasons.append('no single stable swapchain; inspect per-chain segments')
    if not times or times[0]>start+.25 or times[-1]<end-.25:reasons.append('display samples do not cover the stable window')
    valid=not reasons
    passed=bool(intervals['p95'] is not None and frequency>=expected*.97 and intervals['p95']<=budget*1.25
                and intervals['p99']<=budget*2.1 and intervals['max']<=100)
    submitted=[r for r in process if number(r,'CPUStartQPCTime') is not None and start<=number(r,'CPUStartQPCTime')/1000<end]
    return {'measurement':'PresentMon ETW system display events; CPUStartQPCTime + DisplayLatency, not physical scanout',
        'measurement_valid':valid,'performance_pass':passed if valid else 'UNVERIFIED','invalid_reasons':reasons,
        'process_id':process_id,'swapchains':sorted(chains),'present_modes':sorted({r['PresentMode'] for _,r in shown}),
        'effective_seconds':duration,'displayed_frames':len(shown),'system_display_events_per_second':frequency,
        'expected_events_per_second':expected,'display_change_intervals_ms':intervals,
        'submitted_frames':len(submitted),'not_displayed':sum(r.get('DisplayedTime')=='NA' for r in submitted),
        'submission_intervals_ms':distribution([number(r,'FrameTime') for r in submitted],budget_ms=budget),
        'display_latency_ms':distribution([number(r,'DisplayLatency') for _,r in shown],budget_ms=budget),
        'gpu_busy_ms':distribution([number(r,'GPUBusy') for _,r in shown],budget_ms=budget)}
