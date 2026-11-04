# SPDX-License-Identifier: GPL-3.0-only
"""Acoustic words retain streaming text; unaligned text keeps chunk ranges."""
def content(text):
    return ''.join(c for c in str(text) if c.isalnum())

def exact_tokens(row,tokens):
    tokens=tokens or []
    selected=[token for token in tokens if token['start']>=row['start']-.05 and token['end']<=row['end']+.05]
    return selected if content(''.join(token.get('text','') for token in selected))==content(row['text']) else []

def grouping(segments,tokens,legacy,**kwargs):
    aligned=[s for s in segments if s.words];coarse=[s for s in segments if not s.words]
    cues=legacy.group_subtitles(aligned,firered_tokens=tokens,**kwargs) if aligned else []
    for s in coarse:
        cues.append(legacy.SubtitleCue(0,s.start,s.end,s.text,timing_locked=True,speaker=s.speaker))
        legacy.add_review_item(s.start,'VibeVoice 块级时间待对齐','无可靠字词对齐，保留官方流式块范围；不生成均分字戳。',priority=2)
    cues.sort(key=lambda c:(c.start,c.end))
    for index,cue in enumerate(cues):cue.cue_id=index+1
    return cues

def finalize_streaming(cues,segments,tokens,regions,duration,fps,legacy,finalizer):
    """Measured word cues use normal guards; native chunk cues keep their bounds.

    A long unaligned chunk is explicitly reviewable. Splitting it to satisfy a
    display-length rule would fabricate boundaries and misrepresent precision.
    """
    aligned=[s for s in segments if s.words and content(''.join(w.text for w in s.words))==content(s.text)]
    coarse=[s for s in segments if s not in aligned]
    def coarse_match(c):
        return any(c.speaker==s.speaker and abs(c.start-s.start)<.001 and abs(c.end-s.end)<.001
                   and content(c.text)==content(s.text) for s in coarse)
    measured=[c for c in cues if not coarse_match(c)]
    result=finalizer(measured,aligned,tokens,regions,duration,fps,legacy,_streaming_partition=True) if aligned else []
    for s in coarse:
        result.append(legacy.SubtitleCue(0,max(0,s.start),min(duration,s.end),s.text,timing_locked=True,speaker=s.speaker))
        legacy.add_review_item(s.start,'VibeVoice 块级时间待对齐','保留完整主稿与官方块范围；显示长度护栏需真实词级对齐后处理。',priority=2)
    result.sort(key=lambda c:(c.start,c.end,c.speaker))
    for i,c in enumerate(result,1):c.cue_id=i
    legacy.record_run_event('streaming_final_timing',measured_segments=len(aligned),chunk_only_segments=len(coarse),
        precision='measured words or native chunks',uniform_timestamps_created=False)
    return result
