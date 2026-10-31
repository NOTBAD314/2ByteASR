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
            from ..recognition.transcript_data import WordUnit
            words=[WordUnit(float(t['start']),float(t['end']),t.get('text',''),t.get('confidence',1))
                   for t in firered_tokens if float(t['start'])>=segment.start-.05 and float(t['end'])<=segment.end+.05]
        if content_exact(''.join(w.text for w in words)) != content_exact(segment.text):return None
        timeline.extend(w for w in words for _ in content_exact(w.text))
    if not 0<offset<len(timeline):return None
    before,after=timeline[offset-1],timeline[offset]
    if before.end>after.start+.10:return None
    return (before.end+after.start)/2


def _spread_on_source(cues, source):
    """Spread rebuilt pieces over source spans without reversing their order.

    The local rebuild cuts each segment separately, so its pieces follow the
    segments in order; ``None`` when they do not line up.

    Contained/overlapping utterances share one span. Spreading each separately
    would put a short response inside the preceding sentence and reorder its
    text when exported chronologically. This is estimated display timing, not
    new acoustic word evidence. Non-overlapping segments keep their own spans.
    """
    from .text_rules import content_exact
    cursor, groups = 0, []
    for segment in sorted(source, key=lambda s: (s.start, s.end, s.segment_id)):
        need, mine, have = len(content_exact(segment.text)), [], 0
        while cursor < len(cues) and have < need:
            cue = cues[cursor]
            cursor += 1
            mine.append(cue)
            have += len(content_exact(cue.text))
        if have != need or not need or segment.end <= segment.start:
            return None
        if (groups and groups[-1]['speaker'] == segment.speaker
                and segment.start < groups[-1]['end']):
            group = groups[-1]
            group['end'] = max(group['end'], float(segment.end))
        else:
            group = dict(start=float(segment.start), end=float(segment.end),
                         speaker=segment.speaker, cues=[], characters=0)
            groups.append(group)
        group['cues'].extend(mine)
        group['characters'] += need
    if cursor != len(cues):
        return None
    # Validate all partitions before changing any cue times.
    for group in groups:
        done, span, need = 0, group['end'] - group['start'], group['characters']
        for cue in group['cues']:
            cue.start = group['start'] + span * done / need
            done += len(content_exact(cue.text))
            cue.end = group['start'] + span * done / need
    return cues


def _shorten_rebuilt_times(cues, high, max_seconds):
    """Pull ends in so rebuilt lines do not overlap, run past ``high`` or last over ``max_seconds``.

    2026-10-28 (a 98.5-minute lecture failed): the local rebuild pads short
    lines to the 0.35 s minimum, which ran 0.01-0.08 s into the next line,
    and spreading by character share gave sparse lines 6-9 s; either failed
    the whole file. Only ends move, and only earlier; starts and text stay.
    """
    ordered = sorted(cues, key=lambda c: (c.start, c.end))
    for cue, after in zip(ordered, ordered[1:] + [None]):
        end = min(cue.end, cue.start + max_seconds, high)
        if after is not None and after.start > cue.start:
            end = min(end, after.start)
        if end > cue.start:
            cue.end = end
    return cues


def _restores_recorded_omissions(rows, omitted, expected):
    """True when ``rows`` are the turn's source minus exactly the ``omitted`` cues.

    Each omitted piece goes back once, in time order, between the lines around
    it in time (0.05 s slack); a different character, one more or one fewer,
    or a changed number is still lost text.
    """
    from .number_fidelity import numeric_event_values
    from .text_rules import content_exact
    ordered=sorted(rows,key=lambda r:(r.start,r.end))
    owner=[r for r in ordered for _ in content_exact(r.text)]
    actual=''.join(content_exact(r.text) for r in ordered)
    pieces=sorted(omitted,key=lambda c:(c.start,c.end))
    texts=[content_exact(c.text) for c in pieces]
    if (tuple(v for r in ordered for v in numeric_event_values(r.text))!=expected[1] or not all(texts)
            or len(expected[0])!=len(actual)+sum(map(len,texts))):
        return False
    offsets=[0]
    for text in texts:
        offsets.append(offsets[-1]+len(text))
    def fits(k,j):
        left=owner[j-1] if j else None
        right=owner[j] if j<len(owner) else None
        return ((left is None or left.start<=pieces[k].start+.05)
                and (right is None or right.end>=pieces[k].end-.05))
    source,seen,stack=expected[0],set(),[(0,0)]
    while stack:
        i,k=stack.pop()
        if (i,k) in seen:continue
        seen.add((i,k))
        if i==len(source):
            if k==len(texts):return True
            continue
        j=i-offsets[k]
        if k<len(texts) and source.startswith(texts[k],i) and fits(k,j):
            stack.append((i+len(texts[k]),k+1))
        if j<len(actual) and source[i]==actual[j]:
            stack.append((i+1,k))
    return False


def recover_final_content(finalized, grouped, segments, tokens, legacy, omitted=()):
    """Bounded recovery per continuous turn; never silently export invalid text.

    Numeric events are compared per cue, so a split 20 -> 2 | 0 is rejected
    even when ordinary character coverage would pass.

    2026-10-18 (日常 19): a cue belonged to a turn when it *started* inside it.
    A cue whose times had drifted past the turn's end was left out, the turn
    was rebuilt, and the drifted cue stayed too: the same words twice, stacked
    (「メガネ…」 at 48.5 s). A later turn's recovery could also take a cue
    rebuilt for the previous turn and drop it (a line lost). Each cue now
    belongs to exactly one turn of its speaker - the one it overlaps most, else
    the nearest - decided once, and a rebuilt turn must keep its lines in order
    inside the turn without overlapping; otherwise its pieces are spread over
    their segments by character count.

    2026-10-23 (second user, ``S00 0.000s``): the single-character pass drops
    lone fillers such as 「哦」 on purpose. This check did not know, rebuilt
    the whole 425-second turn (bringing the filler back) and failed the job
    when no rebuild fit. ``omitted`` lists those dropped cues; a turn that
    differs from its source only by them passes as it is.

    2026-10-28 (Mac user, ``S00 4096.460s``, a lecture full of numbers): a
    line across two segments read 19 where the segments read nothing (看到 |
    十九题), the 30-minute turn was rebuilt, and the rebuild failed on timing
    alone. Lines with the source's exact text that read its numbers - each
    segment alone or joined as the lines join them - and cut none now pass
    as they are (``cues_read_source_numbers``); a rebuild whose only fault is
    timing gets its ends pulled in (``_shorten_rebuilt_times``) before the
    check gives up.
    """
    from .number_fidelity import cues_read_source_numbers, cuts_inside_numbers, numeric_event_values
    from .text_rules import content_exact
    from ..providers.asr_provider_snapshot import restore_source_text
    turns=[]
    turn_bounds=[]
    for segment in sorted(segments,key=lambda s:(s.start,s.end,s.segment_id)):
        if not turns or turns[-1][-1].speaker!=segment.speaker or segment.start-turn_bounds[-1][1]>2:
            turns.append([])
            turn_bounds.append((segment.start,segment.end))
        turns[-1].append(segment)
        turn_bounds[-1]=(turn_bounds[-1][0],max(turn_bounds[-1][1],segment.end))
    by_speaker={}
    for index,turn in enumerate(turns):
        by_speaker.setdefault(turn[0].speaker,[]).append(index)
    def turn_of(cue):
        best=None
        for index in by_speaker.get(cue.speaker,()):
            start,high=turn_bounds[index]
            low=start-.15
            overlap=min(cue.end,high)-max(cue.start,low)
            key=(overlap<=0,max(low-cue.end,cue.start-high,0.0),-overlap)
            if best is None or key<best[0]:
                best=(key,index)
        return None if best is None else best[1]
    def signature(rows):
        ordered=sorted(rows,key=lambda r:(r.start,r.end))
        return (''.join(content_exact(r.text) for r in ordered),
                tuple(v for r in ordered for v in numeric_event_values(r.text)))
    owners=[turn_of(c) for c in finalized]
    grouped_owners=[turn_of(c) for c in grouped]
    omitted_owners=[turn_of(c) for c in omitted]
    rebuilt={}
    for index,source in enumerate(turns):
        source_end=turn_bounds[index][1]
        rows=[c for c,owner in zip(finalized,owners) if owner==index]
        expected=signature(source)
        def same_content(cues):
            # The numbers may read differently only because the context moved.
            actual=signature(cues)
            return actual==expected or (actual[0]==expected[0] and cues_read_source_numbers(source,cues))
        actual=signature(rows)
        if actual==expected:continue
        if same_content(rows):
            legacy.record_run_event('final_content_number_context_only',speaker=source[0].speaker,
                start=source[0].start,end=source_end,expected_numbers=expected[1],actual_numbers=actual[1])
            continue
        dropped=[c for c,owner in zip(omitted,omitted_owners) if owner==index]
        if dropped and _restores_recorded_omissions(rows,dropped,expected):
            legacy.record_run_event('final_content_recorded_omissions',speaker=source[0].speaker,
                start=source[0].start,end=source_end,omitted=[c.text for c in dropped])
            continue
        split=[expected[0][a:cut]+'|'+expected[0][cut:b] for a,b,cut in cuts_inside_numbers(source,rows)] \
            if actual[0]==expected[0] else []
        legacy.record_run_event('final_content_conservation_recovery',speaker=source[0].speaker,
            start=source[0].start,end=source_end,expected_numbers=expected[1],actual_numbers=actual[1],
            split_numbers=split[:5])
        from .language_rules import finished_cue_limits   # Japanese: two lines (2026-10-21)
        max_chars,max_seconds=finished_cue_limits(legacy.COMPLETE_PHRASE_SOFT_MAX_CHARS,legacy.MAX_SUBTITLE_SECONDS)
        low,high=source[0].start-.15,source_end+.05
        def valid(cues):
            ordered=sorted(cues,key=lambda c:(c.start,c.end))
            return (same_content(cues) and all(0<c.end-c.start<=max_seconds+.05
                    and legacy.display_length(c.text)<=max_chars
                    and low<=c.start and c.end<=high for c in cues)
                    and all(b.start>=a.end-.001 for a,b in zip(ordered,ordered[1:])))
        safe=[c for c,owner in zip(grouped,grouped_owners) if owner==index]
        if not valid(safe):
            safe=legacy.build_local_source_cues(source,tokens)
            restore_source_text(source,safe)
            if not valid(safe) and not valid(_shorten_rebuilt_times(safe,high,max_seconds)):
                spread=_spread_on_source(safe,source)
                if spread is not None:
                    safe=spread
                    legacy.record_run_event('final_content_source_span_retime',speaker=source[0].speaker,
                        start=source[0].start,end=source_end,cues=len(safe),
                        timing_basis='estimated_character_share_in_source_overlap_components')
                if not valid(safe):
                    _shorten_rebuilt_times(safe,high,max_seconds)
        if not valid(safe):
            # Keep stage artifacts and fail visibly instead of changing values,
            # fabricating character timestamps, or exporting an overlong cue.
            raise ValueError(f'字幕保真检查未通过：{source[0].speaker} {source[0].start:.3f}s；原文和阶段记录已保留')
        rebuilt[index]=safe
    if not rebuilt:
        return finalized
    return ([c for c,owner in zip(finalized,owners) if owner not in rebuilt]
            +[c for index in sorted(rebuilt) for c in rebuilt[index]])
