"""Separate raw candidates, accepted sentence points and display fallbacks."""
from __future__ import annotations
import copy
import hashlib
from dataclasses import replace
import numpy as np

POLICY='unit-peak-f64-to-f32+owned-padding80+verified-parent-or-context-v3'


def retry_window(job,start,end,available):
    """One fixed proposal: stored parent plus existing300ms, else natural1000ms context.

    Neither window is selected from a model's predicted boundary.
    """
    from .alignment_items import natural_regroup
    owner=job.get('parent_pcm_range_ms')
    # A display/SRT proposal is not certified lexical provenance for a tighter prompt.
    if owner and len(owner)==2 and job.get('source_clock_verified') and natural_regroup(job.get('source_parts'),job.get('text','')):
        lo=max(available[0],round(owner[0]*16)-4800)
        hi=min(available[1],round(owner[1]*16)+4800)
        if start<=lo<hi<=end and (lo>start or hi<end):return lo,hi,'fixed_parent_context'
    lo=max(available[0],start-16000);hi=min(available[1],end+16000)
    return lo,hi,'source_continuous_context'


def ownership_conflict(measured,parent_range):
    if not parent_range:return False
    a,b=parent_range;s,e=measured['start']['value_ms'],measured['end']['value_ms']
    return bool((s is not None and s>=b) or (e is not None and e<=a)
                or (s is not None and e is not None and max(s,a)>=min(e,b)))


def effective_metadata(payload,row):
    fields=('model','model_revision','code','unit_policy','dtype','torch_version','alignment_identity','execution_identity')
    meta={k:payload.get(k) for k in fields}
    if row.get('effective_model_identity'):
        meta.update(row['effective_model_identity'])
        meta['configured_alignment_identity']=payload.get('alignment_identity')
        meta['compatibility_fallback']=copy.deepcopy(row.get('compatibility_fallback'))
    return meta


def model_audio(audio,declared_padding=(0,0),*,enabled=True):
    """Never trim inferred silence. Only caller-declared exact padding is removed."""
    left,right=map(int,declared_padding)
    if left<0 or right<0 or left+right>=len(audio):raise ValueError('Invalid declared artificial padding')
    if (left and np.any(audio[:left]!=0)) or (right and np.any(audio[-right:]!=0)):
        raise ValueError('Declared artificial padding contains nonzero PCM')
    real=audio[left:len(audio)-right if right else None]
    peak=float(np.max(np.abs(real))) if len(real) else 0.
    if enabled:
        normalized=(real.astype('float64')/peak).astype('float32') if peak else real.copy()
        pad=1280 if len(real)+2560<=300*16000 else 0
        prepared=np.pad(normalized,(pad,pad))
        shift_ms=left/16-pad/16
    else:prepared=real;shift_ms=left/16
    details=dict(policy=POLICY if enabled else 'preserve',original_samples=len(audio),valid_samples=len(real),
        removed_declared_padding_samples=[left,right],added_model_padding_samples=[pad,pad] if enabled else [0,0],
        peak=peak,level_scale=1/peak if enabled and peak else 1.,integer_reencoding=False,resampling=False,clipping=False,
        input_pcm_sha256=hashlib.sha256(np.ascontiguousarray(audio).tobytes()).hexdigest(),
        effective_pcm_sha256=hashlib.sha256(np.ascontiguousarray(prepared).tobytes()).hexdigest(),
        model_to_original_shift_ms=shift_ms,feature_origin_original_samples=left-(pad if enabled else 0),
        valid_original_samples=[left,len(audio)-right])
    return prepared,shift_ms,details


def decoded_units(units,pair,offset_ms,original_samples,details,fa):
    raw,fixed,posterior=pair;shift=details['model_to_original_shift_ms']
    result=fa.timed_units(units,[x+shift for x in raw],[x+shift for x in fixed],offset_ms,posterior,original_samples/16)
    lo,hi=[x/16 for x in details['valid_original_samples']]
    out=[]
    for u in result:
        changes={}
        for side in ['start','end']:
            value=getattr(u,'raw_'+side+'_ms')
            if getattr(u,side+'_basis')=='model' and (value<=lo or value>=hi-fa.ALIGNER_STEP_MS):changes[side+'_basis']='window_edge'
        out.append(replace(u,**changes) if changes else u)
    return out


def point(text,word_rows,char_rows,side,valid_range):
    from ..forced_alignment import content_char_map
    chars=content_char_map(text)
    if not chars:return dict(value_ms=None,reason='no_content')
    index=chars[0][1] if side=='start' else chars[-1][2]
    matches=[]
    for name,rows in [('word',word_rows),('char',char_rows)]:
        for i,u in enumerate(rows or []):
            if u.get('char_'+side)!=index:continue
            value=u.get(side+'_ms');basis=u.get(side+'_basis')
            if basis=='model' and value is not None and valid_range[0]<=value<=valid_range[1]:
                return dict(value_ms=value,reason=None,source_pass=name,unit_id=i,original_span=[u['char_start'],u['char_end']],
                    raw_ms=u.get('raw_'+side+'_ms'),basis=basis,local_mass=u.get(side+'_local'),
                    unit_duration_reliable=(u['raw_end_ms']>u['raw_start_ms']) if u.get('raw_end_ms') is not None and u.get('raw_start_ms') is not None else None)
            matches.append(dict(source_pass=name,unit_id=i,basis=basis,value_ms=value,raw_ms=u.get('raw_'+side+'_ms')))
    return dict(value_ms=None,reason='guard_rejected' if matches else 'original_span_not_found',rejected=matches)


def sentence_measurement(text,word_rows,char_rows,valid_range):
    result={s:point(text,word_rows,char_rows,s,valid_range) for s in ['start','end']}
    a,b=result['start']['value_ms'],result['end']['value_ms']
    if a is not None and b is not None and b<=a:
        for s in ['start','end']:result[s]=dict(value_ms=None,reason='sentence_endpoint_order_conflict',candidate=result[s])
    return result


def matching_anchors(primary_words,retry_words):
    from ..forced_alignment import ALIGNER_STEP_MS
    lookup={(u['char_start'],u['char_end']):u for u in primary_words}
    anchors=[]
    for u in retry_words:
        p=lookup.get((u['char_start'],u['char_end']))
        if not p:continue
        if any(v.get('raw_end_ms',0)<=v.get('raw_start_ms',0) for v in (p,u)):continue
        for side in ['start','end']:
            if p.get(side+'_basis')==u.get(side+'_basis')=='model' and abs(p[side+'_ms']-u[side+'_ms'])<=ALIGNER_STEP_MS:
                anchors.append(dict(span=[u['char_start'],u['char_end']],side=side,
                    primary_ms=p[side+'_ms'],retry_ms=u[side+'_ms'],delta_ms=u[side+'_ms']-p[side+'_ms']))
    return anchors


def accept_retry(primary,retry,*,source_range,anchors=()):
    """A matching measured opposite endpoint anchors the same utterance, at one grid tolerance."""
    from ..forced_alignment import ALIGNER_STEP_MS
    accepted=copy.deepcopy(primary);used=[]
    for side,opposite in [('start','end'),('end','start')]:
        if primary[side]['value_ms'] is not None:continue
        candidate=retry[side]['value_ms'];anchor=retry[opposite]['value_ms'];expected=primary[opposite]['value_ms']
        if candidate is None or expected is None:continue
        endpoint_agrees=anchor is not None and abs(anchor-expected)<=ALIGNER_STEP_MS
        internal_agrees=len({tuple(a['span']) for a in anchors})>=2
        if not (endpoint_agrees or internal_agrees) or not source_range[0]<=candidate<=source_range[1]:continue
        if side=='start' and candidate>=expected or side=='end' and candidate<=expected:continue
        accepted[side]=dict(retry[side],source='source_continuous_context_retry',
            opposite_anchor_delta_ms=anchor-expected if anchor is not None else None,internal_anchors=list(anchors))
        used.append(side)
    return accepted,used


def display_segments(segments,accepted,*,valid_range):
    """Preserve text and measured inner cuts. Fallbacks never become measurements."""
    parts=copy.deepcopy(segments);fallback=[]
    if not parts:return parts,fallback
    start,end=accepted['start']['value_ms'],accepted['end']['value_ms']
    if start is not None:
        while len(parts)>1 and parts[0]['end_ms']<=start:
            first=parts.pop(0);parts[0]['char_start']=first['char_start'];parts[0]['granularity']='merged_uncertain_prefix'
            parts[0]['word_indices']=sorted(set(first.get('word_indices',[]))|set(parts[0].get('word_indices',[])))
        if start<parts[0]['end_ms']:parts[0].update(start_ms=int(round(start)),start_basis='model')
    elif parts[0]['start_ms']<valid_range[0]:
        fallback.append(dict(side='start',candidate_ms=parts[0]['start_ms'],display_ms=valid_range[0],basis='input_edge_fallback',measured=False))
        parts[0].update(start_ms=int(round(valid_range[0])),start_basis='input_edge_fallback')
    if end is not None:
        while len(parts)>1 and parts[-1]['start_ms']>=end:
            last=parts.pop();parts[-1]['char_end']=last['char_end'];parts[-1]['granularity']='merged_uncertain_suffix'
            parts[-1]['word_indices']=sorted(set(last.get('word_indices',[]))|set(parts[-1].get('word_indices',[])))
        if end>parts[-1]['start_ms']:parts[-1].update(end_ms=int(round(end)),end_basis='model')
    elif parts[-1]['end_ms']>valid_range[1]:
        fallback.append(dict(side='end',candidate_ms=parts[-1]['end_ms'],display_ms=valid_range[1],basis='input_edge_fallback',measured=False))
        parts[-1].update(end_ms=int(round(valid_range[1])),end_basis='input_edge_fallback')
    for side,piece in [('start',parts[0]),('end',parts[-1])]:
        if accepted[side]['value_ms'] is None and not any(x['side']==side for x in fallback):
            fallback.append(dict(side=side,display_ms=piece[side+'_ms'],basis=piece[side+'_basis'],measured=False))
    return parts,fallback
