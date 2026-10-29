"""Align desktop source-frame codes with the existing PCM consumption clock.

This measures a captured image against QAudioSink's processed clock, never
speaker acoustics or physical display scanout. Request/PCM drift stays separate.
"""
from bisect import bisect_right
import os
from .playback_metrics import distribution


def desktop_pcm_alignment(rows, telemetry, *, start, end, play_start,
                          source_start_ms, source_fps, source_path, rate=1.,
                          code_period=4096, display_hz=60., frame_pts_ms=None):
    identity=lambda p:os.path.normcase(os.path.normpath(str(p)))
    samples=[]
    for item in telemetry:
        audio=item.get('audio') or {}
        at=audio.get('clock_perf_counter_ts');position=audio.get('estimated_source_ms')
        if (at is None or position is None or audio.get('sink_state')!='ActiveState'
                or identity(audio.get('source_path',''))!=identity(source_path)):
            continue
        if abs(float(audio.get('effective_rate',rate))-rate)>.0001:continue
        samples.append((float(at),float(position),tuple(audio.get('transport_generation') or ()),
                        float(audio.get('clock_sample_uncertainty_ms',0)),int(audio.get('underruns',0))))
    samples.sort();times=[s[0] for s in samples]
    budget=1000/min(source_fps*rate,display_hz)
    selected=[r for r in rows if start<=float(r['desktop_qpc_s'])<end]
    deltas=[];uncertainties=[];paired_times=[];previous=None;offset=None;regressions=0
    for row in selected:
        code=int(row['frame_code']);at=float(row['desktop_qpc_s'])
        if code<0:continue
        if offset is None:
            expected=(source_start_ms/1000+(at-play_start)*rate)*source_fps
            offset=round((expected-code)/code_period)*code_period
        if previous is not None and code<previous:
            if previous-code>code_period/2:offset+=code_period
            else:regressions+=1
        previous=code
        index=bisect_right(times,at)-1
        if not 0<=index<len(samples)-1:continue
        left,right=samples[index:index+2]
        if (right[0]<=left[0] or right[0]-left[0]>1.1 or left[2]!=right[2]
                or left[4]!=right[4] or max(left[3],right[3])>1.):continue
        delay=(float(row['acquired_qpc_s'])-at)*1000
        if delay>budget/2 or int(row['accumulated_frames'])>1:continue
        fraction=(at-left[0])/(right[0]-left[0])
        pcm=left[1]+fraction*(right[1]-left[1])
        frame_index=code+offset
        if frame_pts_ms is not None:
            if not 0<=frame_index<len(frame_pts_ms):continue
            video=float(frame_pts_ms[frame_index])
        else:video=frame_index*1000/source_fps
        deltas.append((video-pcm)/rate)
        uncertainties.append(budget+max(left[3],right[3]))
        paired_times.append(at)
    reasons=[]
    if len(samples)<2:reasons.append('no matching PCM clock samples with QPC timestamps')
    if len({s[2] for s in samples})>1:reasons.append('transport generation changed; analyze separate steady segments')
    if regressions:reasons.append('unexpected frame-code regression; split seek generations first')
    if len(deltas)<100:reasons.append('too few aligned desktop/PCM samples')
    coverage=len(deltas)/max(1,len(selected))
    if coverage<.95:reasons.append('aligned sample coverage below 95 percent')
    valid=not reasons
    absolute=distribution([abs(v) for v in deltas],budget_ms=50.)
    uncertainty=max(uncertainties,default=0.)
    enough=end-start>=60
    passed=(absolute['p95']+uncertainty<=50 and absolute['max']+uncertainty<=150) if valid and enough else 'UNVERIFIED'
    return {'measurement':'DXGI frame-code source PTS vs interpolated QAudioSink processed source time at the same QPC; not acoustic or physical scanout',
            'measurement_valid':valid,'performance_pass':passed,'invalid_reasons':reasons,
            'effective_seconds':max(0.,end-start),'pairs':len(deltas),'coverage':coverage,
            'signed_video_minus_pcm_ms':distribution(deltas,budget_ms=50.),'absolute_delta_ms':absolute,
            'conservative_uncertainty_ms':uncertainty,'long_drift_window_valid':enough,
            'thresholds':{'min_seconds':60,'p95_with_uncertainty_ms':50,'max_with_uncertainty_ms':150,'min_coverage':.95},
            'frame_code_period':code_period,'rate':rate,
            'video_time_mapping':'explicit decoded-frame PTS' if frame_pts_ms is not None else 'uniform CFR assumption'}
