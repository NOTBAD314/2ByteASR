"""Namespace evidence after editorial helpers have renumbered local segments."""
from __future__ import annotations
import copy

STRIDE=1_000_000


def namespace_result(result):
    prefix=(int(result.index)+1)*STRIDE
    ids=[int(segment.segment_id) for segment in result.segments]
    if len(ids)!=len(set(ids)):
        raise ValueError('同一分片内出现重复来源段身份。')
    mapping={old:old if prefix<=old<prefix+STRIDE else prefix+old for old in ids}
    if any(not prefix<new<prefix+STRIDE for new in mapping.values()):
        raise ValueError('来源段身份超出本分片范围。')
    def remap(value):
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                if key in {'source_id','segment_id','source_segment_id'} and isinstance(item,(str,int)):
                    try:item=mapping.get(int(item),item)
                    except ValueError:pass
                else:item=remap(item)
                result[key]=item
            return result
        if isinstance(value,list):return [remap(item) for item in value]
        return value
    for segment in result.segments:
        segment.segment_id=mapping[int(segment.segment_id)]
    for cue in result.cues:
        for attr in ('source_spans','forced_alignment'):
            if hasattr(cue,attr):setattr(cue,attr,remap(getattr(cue,attr)))
    result.reviews=remap(result.reviews)
    return any(old!=new for old,new in mapping.items())


def repair_terminal(segments,cues,requests):
    """Read old terminal checkpoints using recorded request bounds, no models."""
    if len({s.segment_id for s in segments})==len(segments):return False
    from types import SimpleNamespace
    groups={}
    for key,row in requests.items():
        if 'start' in row and 'end' in row:
            groups[int(row.get('request_index',key))]=SimpleNamespace(index=int(row.get('request_index',key)),
                segments=[],cues=[],reviews=[],start=float(row['start']),end=float(row['end']))
    for segment in segments:
        midpoint=(segment.start+segment.end)/2
        matches=[group for group in groups.values() if group.start<=midpoint<group.end]
        if len(matches)!=1:raise ValueError('旧检查点来源范围不明确，未合并不确定的分片。')
        matches[0].segments.append(segment)
    for cue in cues:
        index=int(cue.cue_id)//STRIDE-1
        if index not in groups:raise ValueError('旧检查点字幕分片身份不明确。')
        groups[index].cues.append(cue)
    for group in groups.values():namespace_result(group)
    return True
