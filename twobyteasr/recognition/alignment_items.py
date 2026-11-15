"""Identity and continuity of one acoustic item; display grouping grants no merge."""
from __future__ import annotations
import copy
import hashlib
import json

VERSION='parent-acoustic-item-v1'


def natural_regroup(parts,text):
    """Require ordered, text-matched source evidence; adjacency alone is insufficient."""
    from ..forced_alignment import content_char_map
    if not parts:return False
    heard=''.join(str(p.get('raw_text','')) for p in parts)
    if [c for c,_,_ in content_char_map(heard)]!=[c for c,_,_ in content_char_map(text)]:return False
    previous=None;seen=set()
    for p in parts:
        if not isinstance(p,dict) or p.get('source_id') is None:return False
        times=p.get('source_time');a=p.get('char_start');b=p.get('char_end')
        if not isinstance(times,(list,tuple)) or len(times)!=2 or not 0<=float(times[0])<float(times[1]):return False
        if not isinstance(a,int) or not isinstance(b,int) or not 0<=a<b:return False
        if previous:
            if previous['source_id']==p['source_id']:
                if previous['char_end']!=a:return False
            else:
                if p['source_id'] in seen:return False
                gap=float(times[0])-float(previous['source_time'][1])
                if not 0<=gap<=.6:return False
        seen.add(p['source_id']);previous=p
    return True


def parent_of_parts(parts):
    """A continuous source span, or None. Unknown provenance stays independent."""
    if not isinstance(parts,list) or not parts:return None
    parent=None;first=last=None;raw=[]
    for part in parts:
        if not isinstance(part,dict) or part.get('source_id') is None:return None
        key=str(part['source_id']);a=part.get('char_start');b=part.get('char_end');text=part.get('raw_text')
        if not isinstance(a,int) or not isinstance(b,int) or b<=a or not isinstance(text,str):return None
        if parent is not None and (key!=parent or a!=last):return None
        if first is None:first=a
        parent=key;last=b;raw.append(text)
    return dict(parent_id=parent,source_span=[first,last],raw_text=''.join(raw))


def annotate_row(row,parts=None,*,material_id=None,track_id=None):
    row=dict(row);parts=copy.deepcopy(parts or []);parent=parent_of_parts(parts)
    row['source_parts']=parts
    row['material_id']=material_id
    row['track_id']=track_id
    unknown=hashlib.sha256(json.dumps([material_id,track_id,row.get('speaker'),row['start_ms'],row['end_ms'],row['text']],ensure_ascii=False).encode('utf8')).hexdigest()
    row['parent_ids']=sorted({str(p['source_id']) for p in parts if isinstance(p,dict) and p.get('source_id') is not None}) or ['unrecorded-cue:'+unknown]
    # Modified text is still aligned, but does not certify lexical continuity.
    if parent and parent['raw_text']==str(row['text']):row['continuity']=parent
    return row


def can_join(left,right):
    a,b=left.get('continuity'),right.get('continuity')
    return bool(a and b and a['parent_id']==b['parent_id']
        and a['source_span'][1]==b['source_span'][0]
        and left.get('material_id')==right.get('material_id')
        and left.get('track_id')==right.get('track_id')
        and left.get('speaker')==right.get('speaker'))


def run_provenance(run):
    members=run['members'];parents=sorted({p for m in members for p in m.get('parent_ids',['cue:'+str(m['key'])])})
    parts=[copy.deepcopy(p) for m in members for p in m.get('source_parts',[])]
    verified=all(m.get('source_clock_verified') for m in members) and natural_regroup(parts,run['text'])
    source_times=[p['source_time'] for p in parts if isinstance(p.get('source_time'),(list,tuple)) and len(p['source_time'])==2]
    owner_range=([round(min(x[0] for x in source_times)*1000),round(max(x[1] for x in source_times)*1000)]
                 if source_times and all(m.get('source_clock_verified') for m in members) else None)
    return dict(parent_ids=parents,parent_pcm_range_ms=owner_range,speaker=run.get('speaker'),
        source_parts=parts,source_clock_verified=verified,
        original_text_members=[dict(cue_id=str(m['key']),span=list(span),text=m['text']) for m,span in zip(members,run['spans'])],
        material_contiguous=True)


def rejection(job):
    parents=set(str(x) for x in job.get('parent_ids') or [job.get('parent_id') or job['id']])
    if len(parents)>1 and not (job.get('source_clock_verified') and natural_regroup(job.get('source_parts'),job['text'])):
        return 'unrelated_or_unmapped_acoustic_parents'
    return None


def sample_bounds(job,valid_samples):
    value=job.get('window_samples')
    a,b=(value if value is not None else [int(job['window_start_ms'])*16,int(job['window_end_ms'])*16])
    if not isinstance(a,int) or not isinstance(b,int):raise ValueError('PCM sample bounds must be integer')
    return max(0,a),min(valid_samples,b)


def bind_jobs(jobs,audio_spec):
    """Bind immutable parent/text/time identity before serialization and caching."""
    out=[];valid=int(audio_spec.get('valid_samples',audio_spec['samples']))
    material=audio_spec.get('audio_clock_identity') or audio_spec.get('sha256') or 'window-hash-owned-pcm'
    for source in jobs:
        job=copy.deepcopy(source);a,b=sample_bounds(job,valid)
        anonymous=hashlib.sha256(json.dumps([job.get('material_id') or material,a,b,job['text']],ensure_ascii=False).encode('utf8')).hexdigest()
        parents=[str(x) for x in job.get('parent_ids') or [job.get('parent_id') or 'anonymous-physical-item:'+anonymous]]
        if len(set(parents))!=1 and not (job.get('source_clock_verified') and natural_regroup(job.get('source_parts'),job['text'])):
            raise ValueError('不同 acoustic parent 不能合成一个对齐 prompt；须拆为独立 item')
        available=job.get('available_context_samples') or ([0,valid] if job.get('material_contiguous') else [a,b])
        if len(available)!=2 or not 0<=int(available[0])<=a<b<=int(available[1])<=valid:
            raise ValueError('对齐 item 的有效范围/连续上下文与 PCM 不符')
        supplied=job.get('alignment_item')
        item=dict(version=VERSION,material_id=job.get('material_id') or material,parent_id=parents[0] if len(parents)==1 else None,parent_ids=parents,
            track_id=job.get('track_id'),speaker=job.get('speaker'),absolute_pcm_samples=[a,b],
            available_context_samples=[int(x) for x in available],text_span=[0,len(job['text'])],
            text_sha256=hashlib.sha256(job['text'].encode('utf8')).hexdigest(),sample_rate=16000,
            time_unit='samples',local_to_task_offset_samples=a,artificial_padding_samples=list(job.get('artificial_padding_samples',[0,0])),
            parent_pcm_range_ms=job.get('parent_pcm_range_ms'),parent_source_kind=job.get('parent_source_kind','unverified_proposal'),source_mapping=copy.deepcopy(job.get('source_mapping')),source_parts=copy.deepcopy(job.get('source_parts') or []),original_text_members=copy.deepcopy(job.get('original_text_members') or []))
        if supplied is not None and supplied!=item:raise ValueError('对齐 item 身份与原文/PCM 范围发生变化')
        job['alignment_item']=item;out.append(job)
    return out


def verify_items(jobs,audio_spec):
    bound=bind_jobs(jobs,audio_spec)
    for before,after in zip(jobs,bound):
        if before.get('alignment_item')!=after['alignment_item']:raise ValueError('worker 缺少经过绑定的 acoustic parent 身份')
