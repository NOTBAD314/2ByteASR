"""Small boundary helpers shared by grouping and final validation."""
import re

INDEPENDENT_RESPONSES = frozenset(('对','对啊','对的','是','是的','确实','多少','好','好的','嗯','哦','行','不','不是'))


def independent_response(text):
    return ''.join(re.findall(r'[\u3400-\u9fffA-Za-z0-9]',str(text))) in INDEPENDENT_RESPONSES


def aligned_boundary_time(left, right, target, segments, firered_tokens):
    from .text_rules import content_exact
    from .number_fidelity import mapped_content_timeline
    rows=[s for s in segments if s.speaker==left.speaker and s.end>left.start and s.start<right.end]
    if not rows:return None
    rows.sort(key=lambda s:(s.start,s.end))
    source=''.join(content_exact(s.text) for s in rows)
    joined=content_exact(left.text+right.text)
    if source.count(joined)!=1:return None
    offset=source.index(joined)+target
    timeline=[]
    for segment in rows:
        mapped=mapped_content_timeline(segment)
        if mapped is not None:
            timeline.extend(mapped)
            continue
        # Only directly matched tokens can justify moving a boundary. Do not
        # promote the general aligner's interpolated fallback into word evidence.
        words=list(segment.words)
        if content_exact(''.join(w.text for w in words)) != content_exact(segment.text):
            from .models import WordUnit
            words=[WordUnit(float(t['start']),float(t['end']),t.get('text',''),t.get('confidence',1))
                   for t in firered_tokens if float(t['start'])>=segment.start-.05 and float(t['end'])<=segment.end+.05]
        if content_exact(''.join(w.text for w in words)) != content_exact(segment.text):return None
        timeline.extend(w for w in words for _ in content_exact(w.text))
    if not 0<offset<len(timeline):return None
    before,after=timeline[offset-1],timeline[offset]
    if before.end>after.start+.10:return None
    return (before.end+after.start)/2


def recover_final_content(finalized, grouped, segments, tokens, legacy):
    """Bounded recovery per continuous turn; never silently export invalid text.

    Numeric events are compared per cue, so a split 20 -> 2 | 0 is rejected
    even when ordinary character coverage would pass.
    """
    from .number_fidelity import numeric_event_values
    from .text_rules import content_exact
    from .asr_provider_snapshot import restore_source_text
    turns=[]
    for segment in sorted(segments,key=lambda s:(s.start,s.end,s.segment_id)):
        if not turns or turns[-1][-1].speaker!=segment.speaker or segment.start-turns[-1][-1].end>2:
            turns.append([])
        turns[-1].append(segment)
    def belongs(cue, turn):
        return cue.speaker==turn[0].speaker and turn[0].start-.15<=cue.start<turn[-1].end
    def signature(rows):
        ordered=sorted(rows,key=lambda r:(r.start,r.end))
        return (''.join(content_exact(r.text) for r in ordered),
                tuple(v for r in ordered for v in numeric_event_values(r.text)))
    for source in turns:
        rows=[c for c in finalized if belongs(c,source)]
        expected=signature(source)
        if signature(rows)==expected:continue
        legacy.record_run_event('final_content_conservation_recovery',speaker=source[0].speaker,
            start=source[0].start,end=source[-1].end,expected_numbers=expected[1],actual_numbers=signature(rows)[1])
        safe=[c for c in grouped if belongs(c,source)]
        def valid(cues):
            return (signature(cues)==expected and all(0<c.end-c.start<=legacy.MAX_SUBTITLE_SECONDS+.05
                    and legacy.display_length(c.text)<=legacy.COMPLETE_PHRASE_SOFT_MAX_CHARS for c in cues))
        if not valid(safe):
            safe=legacy.build_local_source_cues(source,tokens)
            restore_source_text(source,safe)
        if not valid(safe):
            # Keep stage artifacts and fail visibly instead of changing values,
            # fabricating character timestamps, or exporting an overlong cue.
            raise ValueError(f'字幕保真检查未通过：{source[0].speaker} {source[0].start:.3f}s；原文和阶段记录已保留')
        finalized=[c for c in finalized if not belongs(c,source)]+safe
    return finalized
