# SPDX-License-Identifier: GPL-3.0-only
"""Conservative interval attribution, independent from editorial host selection."""
import copy
import math

def normalize_intervals(raw, *, task_id, source, duration, clip_to_audio=False):
    labels={};rows=[]
    for item in sorted(raw,key=lambda x:(float(x['start']),float(x['end']),str(x['speaker']))):
        a,b=float(item['start']),float(item['end']);label=str(item['speaker'])
        native_start,native_end=a,b
        if not math.isfinite(a+b) or b<=a:raise ValueError('Invalid native diarization interval')
        if clip_to_audio:
            a,b=max(0,a),min(duration,b)
            if b<=a:continue
        elif a<0 or b>duration+.01:raise ValueError('Invalid native diarization interval')
        if label not in labels:labels[label]=f'{task_id}:{source}:{len(labels)+1:03d}'
        rows.append(dict(start=a,end=b,raw_label=label,speaker=labels[label],confidence=None,
                         confidence_kind='unknown',source=source,overlaps=[],native_start=native_start,native_end=native_end,
                         boundary_correction='padded_window_clipped_to_task_audio' if (a,b)!=(native_start,native_end) else None))
    for i,left in enumerate(rows):
        for j,right in enumerate(rows[i+1:],i+1):
            if right['start']>=left['end']:break
            if right['speaker']!=left['speaker']:
                overlap=dict(start=max(left['start'],right['start']),end=min(left['end'],right['end']))
                left['overlaps'].append(dict(speaker=right['speaker'],**overlap))
                right['overlaps'].append(dict(speaker=left['speaker'],**overlap))
    return rows

def assign_segments(references, intervals):
    """One output per textual unit; ambiguous overlaps never use duration voting.

    A mixed native label is checked afresh for every segment. Splitting is only
    possible at existing acoustic word boundaries that reproduce the exact text.
    """
    output=[];mapping=[]
    for original in references:
        tokens=original.get('tokens') or []
        exact=bool(tokens) and ''.join(str(t.get('text','')) for t in tokens)==original['text']
        units=tokens if exact else [original]
        groups=[]
        for unit in units:
            a,b=float(unit['start']),float(unit['end'])
            touching=[r for r in intervals if min(b,r['end'])>max(a,r['start'])]
            speakers={r['speaker'] for r in touching}
            # Whole-unit unambiguous support, not a majority of an overlap.
            covering=[r for r in touching if r['start']<=a+.02 and r['end']>=b-.02]
            reliable=len(speakers)==1 and bool(covering)
            winner=next(iter(speakers)) if reliable else 'SPEAKER_UNCONFIRMED'
            if groups and groups[-1][0]==winner:groups[-1][1].append(unit)
            else:groups.append((winner,[unit]))
        for winner,group in groups:
            row=copy.deepcopy(original)
            if exact:row.update(start=group[0]['start'],end=group[-1]['end'],text=''.join(t['text'] for t in group),tokens=copy.deepcopy(group))
            raw_speaker=original.get('speaker')
            candidates=sorted({r['speaker'] for r in intervals if min(row['end'],r['end'])>max(row['start'],r['start'])})
            evidence=dict(source='diarizen',original_speaker=raw_speaker,final_speaker=winner,
                candidates=candidates,identity_confirmed=False,needs_confirmation=winner=='SPEAKER_UNCONFIRMED',
                confidence=None,confidence_kind='unknown',basis='unambiguous full interval' if winner!='SPEAKER_UNCONFIRMED' else 'overlap / insufficient temporal evidence')
            row.update(speaker=winner,speaker_evidence=evidence);output.append(row)
            mapping.append(dict(start=row['start'],end=row['end'],text=row['text'],**evidence))
    missing=[dict(r,needs_text_review=True) for r in intervals if not any(
        row['speaker']==r['speaker'] and min(row['end'],r['end'])>max(row['start'],r['start']) for row in output)]
    return output,dict(mapping=mapping,activity_without_reliable_text=missing,text_duplicated=False)

def parse_streaming_chunks(chunks, *, duration, chunk_seconds, source):
    import re
    speaker=None;output=[];seen=set()
    for item in chunks:
        index=int(item['index'])
        if index in seen:raise ValueError('Duplicate protocol chunk identity')
        seen.add(index)
        a=index*chunk_seconds;b=min(duration,(index+1)*chunk_seconds)
        if a>=duration:raise ValueError('Chunk beyond task audio')
        raw=str(item['text']);pieces=re.split(r'Speaker\s+(\d+)\s*:',raw)
        for pos in range(0,len(pieces),2):
            if pos: speaker=pieces[pos-1]
            text=pieces[pos].strip()
            if not text:continue
            output.append(dict(start=a,end=b,text=text,speaker='S'+speaker.zfill(2) if speaker is not None else 'SPEAKER_UNCONFIRMED',
                source=source,tokens=[],chunk_index=index,timestamp_source='streaming_chunk_bounds',timing_precision='chunk',
                speaker_evidence=dict(source=source,local_speaker=speaker,request_index=0,chunk_index=index,
                    needs_confirmation=speaker is None,identity_confirmed=False),confidence=None,confidence_kind='unknown'))
    return output
