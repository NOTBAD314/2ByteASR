"""Offline resize/seek evidence. Missing pixels never inherit native ACK success."""
from __future__ import annotations
from bisect import bisect_left
import csv
import math
import os
from pathlib import Path

from .playback_metrics import desktop_cadence

SEEK_LIMIT_MS = 250.


def _rows(path):
    try:
        with Path(path).open(encoding='utf-8-sig') as stream:
            return list(csv.DictReader(stream))
    except OSError:
        return []


def _at(row):
    return float(row['desktop_qpc_s'])


def _path(value):
    return os.path.normcase(os.path.abspath(str(value or '')))


def _unknown(reason):
    return {'measurement_valid':False,'performance_pass':'UNVERIFIED','reason':reason}


def _latency_coverage(rows, start, end, display_hz):
    """A latency conclusion needs uninterrupted, timely capture around the event."""
    budget = 1/max(1.,display_hz)
    before = [row for row in rows if _at(row)<=start]
    after = [row for row in rows if _at(row)>=end]
    if not before or start-_at(before[-1])>budget*2:
        return False, 'no timely pixel sample before the request'
    if not after or _at(after[0])-end>budget*2:
        return False, 'pixel samples do not cover the latency boundary'
    selected = [before[-1],*[row for row in rows if start<_at(row)<end],after[0]]
    if any(_at(b)-_at(a)>budget*2+.001 or _at(b)<_at(a) for a,b in zip(selected,selected[1:])):
        return False, 'capture gap crosses the operation window'
    if any(int(row.get('frame_code',-1))<0 or int(row.get('accumulated_frames',1))>1
           or float(row.get('copy_decode_ms',0))>budget*1000
           or float(row.get('acquired_qpc_s',_at(row)))-_at(row)>budget
           for row in selected):
        return False, 'invalid, dropped, or late desktop sample in operation window'
    return True, ''


def seek_results(result, target, spec):
    rows = _rows(Path(target)/'desktop.csv')
    points = spec.get('frame_pts_ms') or []
    period = int(spec.get('frame_code_period',4096))
    rate = float(spec.get('rate',1.))
    screen = next((row for row in result.get('environment',{}).get('screens',[])
                   if row.get('name')==result.get('window',{}).get('screen')),{})
    hz = float(screen.get('refresh_hz') or 0)
    operations = [row for row in result.get('operations',[]) if row.get('kind')=='seek']
    measured=[]
    def index_for(code, position):
        candidates = range(code,len(points),period) if code>=0 else ()
        return min(candidates,key=lambda index:abs(points[index]-position),default=None)
    for index, operation in enumerate(operations):
        item = {'id':operation.get('id'), 'at':operation['at'],
            'generation':operation.get('generation'), 'threshold_ms':SEEK_LIMIT_MS,
            'native_frame_ready_ms':operation.get('native_frame_ready_ms'),
            'native_frame_witness':operation.get('native_frame_witness'),
            'ui_callback_ms':operation.get('gui_ms'),
            'measurement':'request QPC to desktop source-frame code; native readiness is separate'}
        measured.append(item)
        start=float(operation['at'])
        next_at=float(operations[index+1]['at']) if index+1<len(operations) else float(result.get('play_end_qpc',start+1))
        if next_at-start<SEEK_LIMIT_MS/1000:
            item.update(status='superseded',measurement_valid=True,performance_pass='NOT_APPLICABLE',
                        reason='a newer request replaced this generation before its deadline')
            continue
        source_target=operation.get('target_source_seconds')
        if (not rows or not points or hz<=0 or source_target is None or spec.get('barcode_y',-1)<0
                or _path(operation.get('source_path'))!=_path((result.get('media') or {}).get('path'))):
            item.update(_unknown('missing source PTS, calibrated barcode, display rate, or matching source identity'))
            continue
        target_ms=float(source_target)*1000
        expected_index=min(len(points)-1,bisect_left(points,target_ms))
        frame_ms=(points[min(len(points)-1,expected_index+1)]-points[max(0,expected_index-1)])/2
        frame_ms=max(.001,frame_ms)
        prior=[row for row in rows if _at(row)<=start and int(row.get('frame_code',-1))>=0]
        if not prior:
            item.update(_unknown('no pre-seek desktop frame identity'))
            continue
        prior=prior[-1]
        old_ms=operation.get('before_source_seconds')
        if old_ms is None:
            item.update(_unknown('missing pre-seek source position for code wrap disambiguation'))
            continue
        old_index=index_for(int(prior['frame_code']),float(old_ms)*1000)
        if old_index is None:
            item.update(_unknown('pre-seek code cannot be mapped to source PTS'))
            continue
        stop=min(next_at,start+1.)
        selected=[row for row in rows if start<=_at(row)<stop and int(row.get('frame_code',-1))>=0]
        changed=next((row for row in selected if row['frame_code']!=prior['frame_code']),None)
        item['first_pixel_change_ms']=(_at(changed)-start)*1000 if changed else None
        item['first_pixel_change_is_target_proof']=False
        exact=correct=None
        correct_index=None
        for row in selected:
            at=_at(row);source_index=index_for(int(row['frame_code']),target_ms+(at-start)*rate*1000)
            if source_index is None:continue
            pts=points[source_index]
            old_expected=points[old_index]+(at-_at(prior))*rate*1000
            # Ordinary pre-seek playback can change pixels too. It cannot
            # certify a seek merely by eventually reaching a forward target.
            if abs(pts-old_expected)<=frame_ms*2:continue
            if exact is None and source_index==expected_index:exact=row
            if correct is None and target_ms-frame_ms<=pts<=target_ms+(at-start)*rate*1000+frame_ms:
                correct,correct_index=row,source_index
        item['target_frame_index']=expected_index
        item['exact_target_frame_ms']=(_at(exact)-start)*1000 if exact else None
        item['target_timeline_frame_ms']=(_at(correct)-start)*1000 if correct else None
        item['target_timeline_frame_index']=correct_index
        boundary=_at(exact) if exact is not None else start+SEEK_LIMIT_MS/1000
        valid,reason=_latency_coverage(rows,start,boundary,hz)
        witness=operation.get('native_frame_witness') or {}
        native_current=(operation.get('request_issued') is True and witness.get('status')=='ready'
                        and witness.get('source_generation')==operation.get('generation'))
        stale=[]
        if correct is not None:
            for row in selected:
                if _at(row)<=_at(correct):continue
                source_index=index_for(int(row['frame_code']),target_ms+(_at(row)-start)*rate*1000)
                if source_index is not None and not (target_ms-frame_ms<=points[source_index]<=target_ms+(_at(row)-start)*rate*1000+frame_ms):
                    stale.append({'at':_at(row),'source_frame_index':source_index})
        item['stale_pixels_after_recovery']=stale
        item['native_witness_current']=native_current
        item['measurement_valid']=valid and native_current
        if not valid:
            item.update(performance_pass='UNVERIFIED',reason=reason)
        elif not native_current:
            item.update(performance_pass='UNVERIFIED',reason='no matching current-generation native frame witness')
        elif stale:
            item.update(performance_pass=False,reason='a prior source position returned after target recovery')
        elif exact is not None:
            item['performance_pass']=item['exact_target_frame_ms']<=SEEK_LIMIT_MS
        elif correct is not None:
            # Display sampling may have skipped the exact target frame. Keep
            # the useful recovery result without claiming exact-frame latency.
            item.update(performance_pass='UNVERIFIED',reason='target timeline recovered but exact target frame was not captured')
        else:
            item.update(performance_pass=False,reason='continuous capture did not show the target within 250 ms')
    applicable=[row for row in measured if row.get('status')!='superseded']
    valid=bool(applicable) and all(row.get('measurement_valid') for row in applicable)
    values=[row.get('performance_pass') for row in applicable]
    return {'measurement_valid':valid,
        'performance_pass':all(values) if valid and all(isinstance(value,bool) for value in values) else 'UNVERIFIED',
        'threshold_ms':SEEK_LIMIT_MS,'operations':measured,
        'scope':'primary source-frame seek latency; follower pixels and physical scanout are not certified',
        'target_accuracy':'exact source frame code checked against decoded PTS; no ACK-to-pixel substitution'}


def resize_results(result, target, spec):
    target=Path(target);segments=[];row_sets={}
    for record in result.get('capture_segments',[]):
        folder=target/record['directory'];layers={};problems=list(record.get('errors',[]))
        if not record.get('geometry_valid',False):problems.append('native viewport changed inside this fixed-ROI segment')
        if record.get('capture_exit_code')!=0:problems.append('collector did not finish normally')
        begin=record.get('sample_start_qpc');end=record.get('sample_end_qpc')
        regions=[{'name':'primary','barcode_y':spec.get('barcode_y',-1)},*spec.get('regions',[])]
        for region in regions:
            name=region['name'];filename='desktop.csv' if name=='primary' else name+'-desktop.csv'
            rows=_rows(folder/filename);row_sets[(record['id'],name)]=rows
            ready=(record.get('capture_readiness') or {}).get(filename)
            if not ready or begin is None or ready.get('ready_qpc_s',math.inf)>begin:
                problems.append(name+' not ready before the stable interval')
            if name=='primary' and ready and ready.get('viewport')!=record['viewport']:
                problems.append('collector viewport differs from the measured native rectangle')
            elif name!='primary' and ready:
                x,y,w,h=record['viewport'];rx,ry,rw,rh=region['rect']
                rounded=lambda value:math.floor(value+.5)
                expected=[x+rounded(rx*w),y+rounded(ry*h),rounded(rw*w),rounded(rh*h)]
                if ready.get('viewport')!=expected:
                    problems.append(name+' collector ROI differs from its current native viewport mapping')
            if not rows or begin is None or end is None:
                layers[name]=_unknown('no complete desktop segment')
            else:
                layers[name]=desktop_cadence(rows,begin,end,source_fps=spec['source_fps'],
                    display_hz=record.get('refresh_hz',0),rate=spec.get('rate',1),barcode=region['barcode_y']>=0)
        valid=not problems and all(row.get('measurement_valid') for row in layers.values())
        values=[row.get('performance_pass') for row in layers.values()]
        segments.append({**record,'layers':layers,'invalid_reasons':problems,'measurement_valid':valid,
            'performance_pass':all(values) if valid and all(isinstance(value,bool) for value in values) else 'UNVERIFIED'})
    recoveries=[]
    for operation in result.get('operations',[]):
        if operation.get('kind')!='resize':continue
        region_results={}
        for name in ['primary',*[region['name'] for region in spec.get('regions',[])]]:
            before=row_sets.get((operation.get('prior_segment'),name),[])
            after=row_sets.get((operation.get('segment'),name),[])
            previous=[row for row in before if _at(row)<=operation['at'] and int(row.get('frame_code',-1))>=0]
            candidates=[row for row in after if _at(row)>=operation.get('geometry_stable_at',math.inf)
                        and int(row.get('frame_code',-1))>=0]
            changed=next((row for row in candidates if previous and row['frame_code']!=previous[-1]['frame_code']),None)
            if not previous or not changed or operation['at']-_at(previous[-1])>.1:
                region_results[name]=_unknown('no nearby pre-resize frame and post-resize changed frame')
                continue
            upper=(_at(changed)-operation['at'])*1000
            budget=1000/max(1.,float(spec['source_fps']))
            bounded=(upper>=0 and float(changed.get('copy_decode_ms',math.inf))<=budget
                     and int(changed.get('accumulated_frames',1))<=1
                     and (float(changed.get('acquired_qpc_s',math.inf))-_at(changed))*1000<=budget)
            region_results[name]={'measurement_valid':bounded,'delay_upper_bound_ms':upper,
                'threshold_ms':SEEK_LIMIT_MS,'performance_pass':True if bounded and upper<=SEEK_LIMIT_MS else 'UNVERIFIED',
                'measurement':'changed source frame observed after new native ROI settled; earliest recovery lies in the uncaptured gap',
                'reason':None if bounded and upper<=SEEK_LIMIT_MS else 'capture resumed too late to decide the 250 ms target'}
        valid=bool(region_results) and all(row.get('measurement_valid') for row in region_results.values())
        recoveries.append({'id':operation.get('id'),'regions':region_results,'measurement_valid':valid,
            'performance_pass':True if valid and all(row.get('performance_pass') is True for row in region_results.values()) else 'UNVERIFIED'})
    covered=len(spec.get('regions',[]))>=max(0,int((result.get('media') or {}).get('tracks',1))-1)
    valid=len(segments)==3 and len(recoveries)==2 and covered and all(row['measurement_valid'] for row in segments+recoveries)
    values=[row['performance_pass'] for row in segments+recoveries]
    return {'measurement_valid':bool(valid),
        'performance_pass':all(values) if valid and all(isinstance(value,bool) for value in values) else 'UNVERIFIED',
        'segments':segments,'recoveries':recoveries,'uncaptured_intervals':result.get('uncaptured_intervals',[]),
        'scope':'separately measured stable native viewports and bounded post-resize recovery; gaps are not steady samples',
        'continuous_resize_animation':'UNVERIFIED: collector handoff intervals are explicitly excluded',
        'threshold_ms':SEEK_LIMIT_MS}
