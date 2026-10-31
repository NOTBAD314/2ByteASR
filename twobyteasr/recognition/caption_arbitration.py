"""Position-aligned independent transcript evidence; never prose generation."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re

VERSION='entity-span-evidence-v2'
PARTICLES=frozenset('啊呀呢吧嘛吗啦哦呃嗯')
NUMBERS=frozenset('0123456789零〇一二两三四五六七八九十百千万亿')


def content(text):return re.sub(r'[\s，。！？、,.!?；;：:]','',str(text))


def usable_transcript(text):
    """Damaged decoding is unavailable evidence, never an independent vote."""
    value = str(text or '')
    return bool(value.strip()) and value.strip().casefold() not in {'<sil>','<blank>','<s>','</s>','<unk>','[sil]'} and not any(
        char == '\ufffd' or 0xd800 <= ord(char) <= 0xdfff
        or (ord(char) < 32 and char not in '\t\r\n') for char in value)


def replacement_spans(source, reference):
    """Keep whole identifiers and contiguous substitutions together.

    The former character voting aligned the p in Sop with a Chinese particle
    after two recognizers omitted the name. Equal votes at that position were
    not evidence for the same word. Case and spelling of identifiers belong to
    terminology adjudication, not this transcript consensus pass.
    """
    operations = align(source, reference)
    spans = []
    pending = None
    for start, end, old, new in operations:
        # A leading interjection is a separate utterance unit. Different
        # guesses for that unit cannot swallow a later shared body span.
        if start == 0 and end == 1 and old in PARTICLES:
            if old != new:
                spans.append((start, end, old, new))
            continue
        if old == new:
            if pending is not None:
                spans.append(tuple(pending)); pending = None
            continue
        if pending is None:
            pending = [start, end, old, new]
        else:
            pending[1] = end; pending[2] += old; pending[3] += new
    if pending is not None:
        spans.append(tuple(pending))
    return spans


def align(primary,reference):
    """Minimum-edit character alignment, with substitutions preferred on ties."""
    n,m=len(primary),len(reference)
    costs=[[0]*(m+1) for _ in range(n+1)]
    for i in range(n+1):costs[i][0]=i
    for j in range(m+1):costs[0][j]=j
    for i in range(1,n+1):
        for j in range(1,m+1):
            costs[i][j]=min(costs[i-1][j-1]+(primary[i-1]!=reference[j-1]),costs[i-1][j]+1,costs[i][j-1]+1)
    operations=[];i,j=n,m
    while i or j:
        if i and j and costs[i][j]==costs[i-1][j-1]+(primary[i-1]!=reference[j-1]):
            operations.append((i-1,i,primary[i-1],reference[j-1]));i-=1;j-=1
        elif i and costs[i][j]==costs[i-1][j]+1:
            operations.append((i-1,i,primary[i-1],''));i-=1
        else:
            operations.append((i,i,'',reference[j-1]));j-=1
    return list(reversed(operations))


def arbitrate(primary,firered,qwen,*,manual_text=None,start_ms=0,end_ms=0,primary_model='MOSS'):
    source=content(primary);refs=[content(firered),content(qwen)]
    # Bound comparison to a single cue. Long segment evidence needs upstream
    # time slicing, and cannot be treated as an aligned acoustic observation.
    valid=all(usable_transcript(x) for x in (primary,firered,qwen)) and max(map(len,[source,*refs]))<=512
    aligned=[align(source,ref) for ref in refs] if valid else []
    votes=Counter(row for ref in refs for row in set(replacement_spans(source,ref))) if valid else Counter()
    edits=[];unresolved=[]
    for (start,end,old,new),count in sorted(votes.items()):
        support_context=valid and all(SequenceMatcher(None,source,ref,autojunk=False).ratio()>=.58 for ref in refs)
        safe=count==2 and support_context and not any(c in NUMBERS for c in old+new)
        safe=safe and bool(old) and bool(new) and len(old)==len(new) and len(old)<=4
        # Never split/change a Latin entity, including a numeric player ID.
        safe=safe and not re.search(r'[A-Za-z0-9]',old+new)
        # Uncertain interjections remain MOSS; a disputed first character must
        # not invalidate a later phrase supported by both recognizers.
        safe=safe and not (start==0 or (len(old)==len(new)==1 and (old in PARTICLES or new in PARTICLES)))
        row={'start':start,'end':end,'from':old,'to':new,'support':count,
             'confidence_source':'two_independent_asr_transcripts; not acoustic probability'}
        (edits if safe else unresolved).append(row)
    corrected=source
    for row in reversed(edits):corrected=corrected[:row['start']]+row['to']+corrected[row['end']:]
    reason='FireRed+Qwen片段共识' if edits else '三路一致' if valid and source==refs[0]==refs[1] else 'MOSS主稿回退' if valid else '声学证据不足'
    if manual_text is not None:corrected=str(manual_text);reason='用户手动确认'
    return {'version':VERSION,'selected_text':corrected if edits or manual_text is not None else primary,'reason':reason,
        'timestamp':datetime.now(timezone.utc).isoformat(), 'start_ms':start_ms,'end_ms':end_ms,
        'candidates':[{'provider':provider,'model':model,'text':text,'start_ms':start_ms,'end_ms':end_ms}
            for provider,model,text in [('local',primary_model,primary),('local','FireRed',firered),('local','Qwen',qwen)]],
        'alignment':aligned,'accepted_spans':edits,'unresolved_spans':unresolved,'acoustic_verified':False}


def project_arbitration(project,cue,*,apply=False):
    from ..subtitle_rules.studio_qc import model_evidence
    candidates={}
    for row in model_evidence(project,cue):
        label=row.label.lower()
        for key in ('moss','firered','qwen'):
            if key in label:candidates.setdefault(key,row.text)
    manual=project.studio_state.get('manual_caption_text',{}).get(cue.id)
    confirmations=project.studio_state.get('review_confirmations',{})
    if manual is None and (cue.id in confirmations or cue.text!=cue.original_text):manual=cue.text
    result=arbitrate(candidates.get('moss',cue.original_text),candidates.get('firered',''),candidates.get('qwen',''),
        manual_text=manual,start_ms=cue.start_ms,end_ms=cue.end_ms)
    if apply:
        # The caller chooses when to rerun arbitration. Manual text always wins.
        cue.text=result['selected_text']
        project.generation_metadata.setdefault('caption_arbitration',{}).setdefault(cue.id,[]).append(result)
    return result
