"""Trace provisional ASR IDs through explicit segment/character ownership."""
from bisect import bisect_left,bisect_right
from collections import defaultdict
import unicodedata


def _text(value):
    return ''.join(c for c in str(value or '') if unicodedata.category(c)[0] in 'LN')


def replacement_mapping(project,provisional,segment_rows):
    children=defaultdict(list)
    source_spans=project.generation_metadata.get('segmentation_source_spans',{}).get('cues',{})
    for cue in project.cues:
        for part in source_spans.get(cue.id,{}).get('parts',[]):
            key=str(part.get('source_id',''))
            if key and cue.id not in children[key]:children[key].append(cue.id)
    owners=defaultdict(list)
    for ref,row in segment_rows:
        if not str(ref).startswith('segment:'):continue
        owners[str(row.get('speaker_id') or 'S00')].append((int(row['start_ms']),int(row['end_ms']),str(ref).split(':',1)[1],row))
    indices={}
    for speaker,rows in owners.items():
        rows.sort(key=lambda r:(r[0],r[1],r[2]));maximum=-1;prefix=[]
        for start,end,key,row in rows:maximum=max(maximum,end);prefix.append(maximum)
        indices[speaker]=(rows,[r[0] for r in rows],prefix)
    mapping={};receipts={}
    for item in provisional:
        identity=str(item.get('id') or '')
        if not identity:continue
        start=int(item.get('start_ms') or 0);end=max(start+1,int(item.get('end_ms') or start+1))
        rows,starts,prefix=indices.get(str(item.get('speaker_id') or 'S00'),([],[],[]))
        candidates=[r for r in rows[bisect_right(prefix,start):bisect_left(starts,end)] if r[1]>start]
        exact=[r for r in candidates if _text(r[3].get('text'))==_text(item.get('text'))]
        selected=exact if len(exact)==1 else candidates if not exact and len(candidates)==1 else []
        ids=list(dict.fromkeys(child for row in selected for child in children[row[2]]))
        mapping[identity]=ids
        receipts[identity]=dict(source_ids=[r[2] for r in selected],final_ids=ids,
            basis='same_speaker_exact_text_source_spans' if exact and selected else 'same_speaker_unique_source_range' if selected else 'unresolved_ownership',
            status='resolved' if exact and ids else 'needs_confirmation')
    return mapping,receipts


def committed_cue_count(outputs,fallback):
    import json
    try:
        value=json.loads(outputs.get('result_ref_json') or '{}').get('cue_count')
        return value if type(value) is int and value>=0 else fallback
    except (TypeError,ValueError,AttributeError):return fallback
