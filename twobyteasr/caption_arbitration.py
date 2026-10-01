"""Position-aligned independent transcript evidence; never prose generation."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re

VERSION='char-evidence-v1'
PARTICLES=frozenset('啊呀呢吧嘛吗啦哦呃嗯')
NUMBERS=frozenset('0123456789零〇一二两三四五六七八九十百千万亿')


def content(text):return re.sub(r'[\s，。！？、,.!?；;：:]','',str(text))


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


def arbitrate(primary,firered,qwen,*,manual_text=None,start_ms=0,end_ms=0):
    source=content(primary);refs=[content(firered),content(qwen)]
    # Bound comparison to a single cue. Long segment evidence needs upstream
    # time slicing, and cannot be treated as an aligned acoustic observation.
    valid=all(refs) and max(map(len,[source,*refs]))<=512
    aligned=[align(source,ref) for ref in refs] if valid else []
    votes=Counter(row for alignment in aligned for row in set(alignment) if row[2]!=row[3])
    edits=[];unresolved=[]
    for (start,end,old,new),count in sorted(votes.items()):
        support_context=valid and all(SequenceMatcher(None,source,ref,autojunk=False).ratio()>=.58 for ref in refs)
        safe=count==2 and support_context and not any(c in NUMBERS for c in old+new)
        # Uncertain interjections remain MOSS; a disputed first character must
        # not invalidate a later phrase supported by both recognizers.
        safe=safe and not (start==0 or (old in PARTICLES and new in PARTICLES))
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
            for provider,model,text in [('local','MOSS',primary),('local','FireRed',firered),('local','Qwen',qwen)]],
        'alignment':aligned,'accepted_spans':edits,'unresolved_spans':unresolved,'acoustic_verified':False}


def project_arbitration(project,cue,*,apply=False):
    from .studio_qc import model_evidence
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
