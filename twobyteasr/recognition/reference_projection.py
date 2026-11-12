"""Local text spans from timed ASR windows; never an acoustic probability."""
from collections import defaultdict
from difflib import SequenceMatcher


def _content(text):
    return ''.join(c for c in str(text or '') if c.isalnum() or c in 'ー々')


def project_reference_windows(segments, windows):
    ordered=sorted(segments,key=lambda s:(s.start,s.end,s.segment_id))
    candidates=defaultdict(list); diagnostics={}
    for window_id,window in enumerate(windows,1):
        if ((window.get('generation') or {}).get('token_limit_reached')
                or (window.get('generation') or {}).get('stop_reason')=='other_stop'):
            continue
        start,end=float(window['start']),float(window['end'])
        local=[s for s in ordered if s.start < end and s.end > start]
        source=''; intervals=[]
        for segment in local:
            text=_content(segment.text); low=len(source);source+=text
            intervals.append((segment,low,len(source)))
        reference=_content(window.get('text'))
        if not source or not reference or max(len(source),len(reference))>2000:
            continue
        operations=SequenceMatcher(None,source,reference,autojunk=False).get_opcodes()
        for segment,low,high in intervals:
            overlaps=any(other.segment_id!=segment.segment_id and other.speaker!=segment.speaker
                and min(segment.end,other.end)>max(segment.start,other.start) for other in local)
            if overlaps:
                diagnostics[segment.segment_id]='overlapping_speakers_context_only'
                continue
            spans=[];anchored=0
            for tag,a,b,c,d in operations:
                if tag=='equal':
                    x,y=max(a,low),min(b,high)
                    if x<y:spans.append((c+x-a,c+y-a));anchored+=y-x
                elif tag=='replace' and low<=a<b<=high:
                    spans.append((c,d))
                elif tag=='insert' and low<a<high:
                    spans.append((c,d))
            if not spans or anchored < min(2,max(1,high-low)):
                diagnostics[segment.segment_id]='insufficient_local_text_anchors'
                continue
            a,b=min(x for x,y in spans),max(y for x,y in spans)
            text=reference[a:b]
            if not text or len(text)>max(12,(high-low)*2):
                diagnostics[segment.segment_id]='unbounded_reference_slice'
                continue
            candidates[segment.segment_id].append({'text':text,'window_id':window.get('source_window_id',window_id),
                'window_time':[start,end],'reference_char_span':[a,b],
                'primary_char_span':[low,high],'anchor_characters':anchored,
                'mapping_basis':'temporal_envelope_and_ordered_text_spans','acoustic_alignment':False})
    result={}
    for segment in ordered:
        options=candidates.get(segment.segment_id,[])
        texts={row['text'] for row in options}
        if len(texts)==1:
            result[segment.segment_id]={'text':next(iter(texts)),'spans':options,'status':'associated'}
        else:
            result[segment.segment_id]={'text':'','spans':options,
                'status':'cross_window_disagreement' if options else diagnostics.get(segment.segment_id,'no_reference_window')}
    return result
