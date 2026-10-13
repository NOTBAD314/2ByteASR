"""Distinguish source acoustic overlap from editorial display tails.

Unknown evidence is retained for review. No text, speaker, or cue is removed.
"""
from __future__ import annotations

import math
import re
import statistics
from copy import copy


def _speaker_view(project, speaker_id, views=None):
    """``project`` seeing only evidence rows of ``speaker_id`` (or unlabeled).

    ``views`` memoizes one view per speaker for a whole-project pass; building
    the filtered evidence for every cue was O(cues x evidence rows)."""
    if views is not None and speaker_id in views:
        return views[speaker_id]
    view = copy(project)
    view.asr_evidence = {ref: row for ref, row in project.asr_evidence.items()
                        if not row.get('speaker_id') or row['speaker_id'] == speaker_id}
    if views is not None:
        views[speaker_id] = view
    return view


def project_word_boundaries(project, cue, *, views=None):
    """Read measured cue boundaries in the current display clock.

    A saved complete alignment can still prove an unchanged first/last token
    after a spelling edit in the middle. A lone raw word or estimated spacing
    cannot. This never writes back to the immutable recognition evidence.
    """
    if not all(hasattr(project, key) for key in ('cues', 'render_settings', 'studio_state')):
        return None, None
    from .cue_word_alignment import cue_words, content_positions
    from .word_timing_provenance import estimated_word_timing
    view = _speaker_view(project, cue.speaker_id, views)
    words, reason = cue_words(view, cue)
    if words and reason in ('exact_token_text', 'derived_term_source_span'):
        return min(w.start_ms for w in words), max(w.end_ms for w in words)
    receipt = project.studio_state.get('caption_timeline', {}).get('instances', {}).get(cue.id, {})
    rows = receipt.get('words') or []
    if not rows or receipt.get('word_alignment') not in ('exact_token_text', 'derived_term_source_span'):
        return None, None
    if not receipt.get('acoustic_word_observation') and any(
            estimated_word_timing(view.asr_evidence.get(ref, {})) and not
            (view.asr_evidence.get(ref, {}).get('caption_arbitration') or {}).get('acoustic_words')
            for ref in cue.evidence_refs):
        return None, None
    normalize = lambda text: ''.join(c for _, c in content_positions(text))
    source = normalize(receipt.get('text', ''))
    if not source or ''.join(normalize(w['text']) for w in rows) != source:
        return None, None
    text = normalize(cue.text)
    first, last = normalize(rows[0]['text']), normalize(rows[-1]['text'])
    return (rows[0]['start_ms'] if first and text.startswith(first) else None,
            rows[-1]['end_ms'] if last and text.endswith(last) else None)


def project_frame_ms(project):
    rates=[float(asset.video_metadata.get("fps") or 0) for asset in project.media_pool]
    fps=next((rate for rate in rates if 1<=rate<=240),float(project.render_settings.get("fps") or 30))
    return 1000/max(1,min(240,fps))


def _evidence_points(project,cue,keys):
    points=[]
    for ref in cue.evidence_refs:
        row=project.asr_evidence.get(ref,{})
        if row.get('speaker_id') and row['speaker_id'] != cue.speaker_id:
            continue
        for key in keys:
            for item in row.get(key,[]) if isinstance(row.get(key),list) else []:
                if not isinstance(item,dict):continue
                try:
                    a=float(item['start_ms']) if 'start_ms' in item else float(item['start'])*1000
                    b=float(item['end_ms']) if 'end_ms' in item else float(item['end'])*1000
                except (KeyError,TypeError,ValueError):continue
                if math.isfinite(a+b) and b>a:points.append((round(a),round(b)))
    return sorted(set(points))


def independent_overlap_verified(project,left,right):
    """MOSS overlap or mono VAD alone is not independent simultaneous speech."""
    spans=[]
    for cue,other in ((left,right),(right,left)):
        independent=[]
        for ref in cue.evidence_refs:
            row=project.asr_evidence.get(ref,{})
            if other.id in (row.get('verified_overlap_with') or []):
                return True
            if row.get('speaker_independent') is True:
                independent.extend(_evidence_points(project,cue,('independent_speech_intervals',)))
        spans.append(independent)
    return classify_overlap(*spans)=='acoustic' if all(spans) else False


def _verified_overlap_pairs(project):
    """Overlapping cue pairs with independent simultaneous-speech evidence.

    Sweeps cues by start time: only time-overlapping pairs can qualify, so
    this is O(cues + overlaps) instead of checking every pair (50 million at
    10,000 captions). The check is symmetric; callers test both orders."""
    ordered = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms))
    verified = set()
    for index, a in enumerate(ordered):
        for later in range(index+1, len(ordered)):
            b = ordered[later]
            if b.start_ms >= a.end_ms:
                break
            if (min(a.end_ms,b.end_ms) > max(a.start_ms,b.start_ms)
                    and independent_overlap_verified(project,a,b)):
                verified.add((a.id, b.id))
    return verified


def project_display_tail_plan(project):
    rows=[dict(id=c.id,start_ms=c.start_ms,end_ms=c.end_ms,speaker=c.speaker_id) for c in project.cues]
    views = {}
    boundaries = {c.id: project_word_boundaries(project, c, views=views) for c in project.cues}
    acoustic={c.id:project_acoustics(project,c,boundaries=boundaries[c.id]) for c in project.cues}
    verified = _verified_overlap_pairs(project)
    changes,audit=protect_intervals(rows,acoustic,word_boundaries=boundaries,verified_pairs=verified)
    by_id={c.id:c for c in project.cues}
    frame=project_frame_ms(project)
    labels={}  # the first speaker entry with that id names it
    for speaker in project.speakers:
        labels.setdefault(speaker.id, speaker.name or speaker.id)
    for pair in audit:
        left,right=by_id[pair['left']],by_id[pair['right']]
        pair.update(raw_labels=[left.speaker_id,right.speaker_id],
                    display_labels=[labels.get(c.speaker_id,c.speaker_id) for c in (left,right)],
                    cue_before=[[left.start_ms,left.end_ms],[right.start_ms,right.end_ms]],frame_ms=frame,
                    independently_verified=independent_overlap_verified(project,left,right))
        if pair['classification'] == 'acoustic' and not pair['independently_verified']:
            pair.update(classification='source_overlap_unverified', review_required=True)
        if left.id in changes:
            pair.update(boundary_ms=changes[left.id], boundary_source='incoming_cue_or_measured_speech_end')
    report=dict(policy_version=4,status='applied',pairs_before=audit,changed_ends=changes,
                counts={name:sum(p['classification']==name for p in audit) for name in
                        ('display_compensation','acoustic','uncertain','source_overlap_unverified')},
                source='measured cue words before coarse source intervals; unknown overlap retained')
    return changes,report


def classify_overlap(left_spans, right_spans):
    if not left_spans or not right_spans:
        return "uncertain"
    if any(min(b, d) > max(a, c) for a, b in left_spans for c, d in right_spans):
        return "acoustic"
    if max(b for _, b in left_spans) <= min(a for a, _ in right_spans):
        return "display_compensation"
    if max(b for _, b in right_spans) <= min(a for a, _ in left_spans):
        return "display_compensation"
    return "uncertain"


def protect_intervals(rows, acoustic, *, word_boundaries=None, verified_pairs=()):
    """Return end-only changes and a pre-change cross-speaker overlap audit."""
    ends = {row["id"]: row["end_ms"] for row in rows}
    audit = []
    ordered = sorted(rows, key=lambda row: (row["start_ms"], row["end_ms"], row["id"]))
    for index, left in enumerate(ordered):
        for later in range(index+1, len(ordered)):
            right = ordered[later]
            if right["start_ms"] >= left["end_ms"]:
                break
            a, b = acoustic.get(left["id"], []), acoustic.get(right["id"], [])
            kind = classify_overlap(a, b)
            left_word_end = (word_boundaries or {}).get(left['id'], (None, None))[1]
            right_word_start = (word_boundaries or {}).get(right['id'], (None, None))[0]
            measured = left_word_end is not None and right_word_start is not None
            if measured:
                kind = 'display_compensation' if left_word_end <= right_word_start else 'acoustic'
            verified = ((left['id'],right['id']) in verified_pairs or
                        (right['id'],left['id']) in verified_pairs)
            if verified:
                kind = 'acoustic'
            if left["speaker"] != right["speaker"]:
                audit.append({"left": left["id"], "right": right["id"], "classification": kind,
                              "left_acoustic": a, "right_acoustic": b,
                              "word_boundaries_ms": [left_word_end, right_word_start],
                              "evidence_kind": 'measured_cue_words' if measured else 'source_intervals',
                              "overlap_ms": min(left["end_ms"], right["end_ms"]) - right["start_ms"]})
            ordered_speech = measured or (a and b and max(end for _, end in a) <= min(start for start, _ in b))
            if kind == "display_compensation" and ordered_speech:
                if right["start_ms"] > left["start_ms"]:
                    # An incoming display can start before its actual speech.
                    # Remove reading tails without cutting the outgoing word.
                    boundary = max(right['start_ms'], left_word_end) if measured else right['start_ms']
                    ends[left["id"]] = min(ends[left["id"]], boundary)
            elif not verified and left_word_end is not None and left_word_end > left['start_ms']:
                # Even when voices really overlap, the outgoing caption need
                # not linger after its last measured word. The speech overlap
                # itself remains intact; only the added display tail is cut.
                boundary = max(right['start_ms'], left_word_end)
                ends[left['id']] = min(ends[left['id']], boundary)
    return {row["id"]: ends[row["id"]] for row in rows if ends[row["id"]] != row["end_ms"]}, audit


def project_acoustics(project, cue, *, boundaries=None):
    start, end = project_word_boundaries(project, cue) if boundaries is None else boundaries
    if start is not None and end is not None and end > start:
        return [(start, end)]
    spans = []
    for ref in cue.evidence_refs:
        row = project.asr_evidence.get(ref, {})
        # Evidence refs include temporally nearby turns from other speakers.
        # Those turns cannot become the selected cue's acoustic interval.
        if row.get('speaker_id') and row['speaker_id'] != cue.speaker_id:
            continue
        if row.get('speaker_independent') is True:
            independent = _evidence_points(project, cue, ('independent_speech_intervals',))
            if independent:
                spans.extend(independent)
                continue
        if "acoustic_start_ms" in row and "acoustic_end_ms" in row:
            a, b = row["acoustic_start_ms"], row["acoustic_end_ms"]
        elif (row.get("firered_end", 0) > row.get("firered_start", 0)
              and row.get("firered_alignment_confidence", 0) >= 0.65
              and "degraded" not in str(row.get("final_timing_owner", "")).lower()
              and not bounded_search_window(row)):
            a, b = round(row["firered_start"]*1000), round(row["firered_end"]*1000)
        elif row.get("moss_end", 0) > row.get("moss_start", 0):
            a, b = round(row["moss_start"]*1000), round(row["moss_end"]*1000)
        else:
            continue
        if b > a:
            spans.append((a, b))
    receipt = getattr(project, 'studio_state', {}).get('caption_timeline', {}).get('instances', {}).get(getattr(cue, 'id', ''), {})
    if getattr(project, 'render_settings', {}).get('_cue_domain') == 'timeline' and receipt:
        source_spans = receipt.get('source_spans') or []
        base = receipt.get('word_base_interval')
        if len(source_spans) != 1 or not base:
            return []  # Never compare task-clock evidence to edited timeline time.
        source = source_spans[0]
        a, b = source.get('source_start_ms'), source.get('source_end_ms')
        if a is None or b is None:
            return []
        offset = base[0] - a + int(receipt.get('word_clock_offset_ms', 0))
        spans = [(max(a,x)+offset,min(b,y)+offset) for x,y in spans if min(b,y)>max(a,x)]
    return sorted(set(spans))


def bounded_search_window(row):
    """A neighbourhood-clipped window is not independent word evidence.

    Older results did not name this provenance. Their exact ±80ms clipping
    signature can identify it without assuming every FireRed result is padded.
    """
    get = row.get if isinstance(row, dict) else lambda key, default=0: getattr(row, key, default)
    metadata = get('caption_arbitration', {}) or {}
    if metadata.get('timing_evidence', {}).get('kind') == 'bounded_search_window':
        return True
    try:
        a, b = float(get('moss_start', 0)), float(get('moss_end', 0))
        fa, fb = float(get('firered_start', 0)), float(get('firered_end', 0))
        return b > a and abs(fa - max(0, a - .08)) < .001 and abs(fb - b - .08) < .001
    except (TypeError, ValueError):
        return False


def protect_project_display_tails(project):
    changes,report=project_display_tail_plan(project)
    for cue in project.cues:
        if cue.id in changes:
            cue.end_ms = changes[cue.id]
    project.generation_metadata["display_overlap_audit"] = report
    return report['pairs_before']


def protect_runtime_display_tails(cues, segments):
    if not segments:
        return []  # No source evidence: leave timing unchanged for review.
    # Key by position: content recovery may append cues whose ids repeat an
    # existing cue's id until the final renumbering (2026-10-11 688 s run).
    keys = [str(index) for index in range(len(cues))]
    rows = [dict(id=key, start_ms=round(cue.start*1000), end_ms=round(cue.end*1000), speaker=cue.speaker)
            for key, cue in zip(keys, cues)]
    acoustic = {}
    from types import SimpleNamespace
    evidence = {}
    for index, segment in enumerate(segments):
        row = {key: getattr(segment, key, None) for key in
               ('primary_source', 'final_timing_owner', 'caption_arbitration')}
        row['speaker_id'] = segment.speaker
        row['words'] = [dict(word) if isinstance(word, dict) else dict(
            text=getattr(word, 'text', getattr(word, 'word', '')),
            start=getattr(word, 'start', 0), end=getattr(word, 'end', 0))
            for word in getattr(segment, 'words', ()) or ()]
        evidence[str(index)] = row
    view = SimpleNamespace(asr_evidence=evidence, render_settings={}, studio_state={}, cues=[])
    for key, cue in zip(keys, cues):
        view.cues.append(SimpleNamespace(id=key, text=cue.text,
            start_ms=round(cue.start*1000), end_ms=round(cue.end*1000), speaker_id=cue.speaker,
            evidence_refs=[str(i) for i,s in enumerate(segments) if s.speaker==cue.speaker
                           and s.end>cue.start and s.start<cue.end]))
    boundaries = {c.id: project_word_boundaries(view,c) for c in view.cues}
    for key, cue in zip(keys, cues):
        spans = []
        for segment in segments:
            if segment.speaker != cue.speaker or segment.end <= cue.start or segment.start >= cue.end:
                continue
            firered = (getattr(segment, "firered_alignment_confidence", 0) >= .65
                       and "degraded" not in str(getattr(segment, "final_timing_owner", "")).lower()
                       and getattr(segment, "firered_end", 0) > getattr(segment, "firered_start", 0)
                       and not bounded_search_window(segment))
            a = getattr(segment, "firered_start", 0) if firered else getattr(segment, "moss_start", 0)
            b = getattr(segment, "firered_end", 0) if firered else getattr(segment, "moss_end", 0)
            if b > a:
                spans.append((round(a*1000), round(b*1000)))
        acoustic[key] = spans
    changes, audit = protect_intervals(rows, acoustic, word_boundaries=boundaries)
    for pair in audit:
        pair.update(left=str(cues[int(pair['left'])].cue_id), right=str(cues[int(pair['right'])].cue_id))
        # Mono source boundaries alone do not prove simultaneous speakers.
        if pair['classification'] == 'acoustic':
            pair.update(classification='source_overlap_unverified', review_required=True)
        if pair['evidence_kind'] != 'measured_cue_words':
            pair['evidence_kind'] = 'source_intervals_without_editorial_or_search_padding'
    for key, cue in zip(keys, cues):
        if key in changes:
            cue.end = changes[key] / 1000
    return audit


SHORT_GAP_BRIDGE_MS = 500


def short_gap_bridges(rows, threshold, *, full_track=True, same_speaker=True, max_duration=None):
    """New end values that close short blank gaps; the next start never moves.

    2026-10-10 (user): a gap of 0.5 s or less between captions makes them
    flicker, so the earlier caption runs on until the next one appears.
    ``rows`` are ``(key, speaker, start, end)`` in any one unit.

    * full_track: a moment where no caption is on screen at all.
    * same_speaker: one speaker's caption disappears and comes back while
      someone else's caption stays up. Skipped when another speaker starts
      talking inside the gap, which would create a new overlap.
    """
    rows = sorted(rows, key=lambda row: (row[2], row[3], str(row[1]), str(row[0])))
    original = {key: end for key, _speaker, _start, end in rows}
    ends = dict(original)

    def fits(start, target):
        return max_duration is None or target - start <= max_duration

    if full_track and rows:
        owner_key, _speaker, owner_start, cover = rows[0]
        for key, _speaker, start, _end in rows[1:]:
            if cover < start <= cover + threshold and fits(owner_start, start):
                ends[owner_key] = cover = start
            if ends[key] > cover:
                owner_key, owner_start, cover = key, start, ends[key]
    if same_speaker:
        starts = [(start, speaker) for _key, speaker, start, _end in rows]
        lanes = {}
        for row in rows:
            lanes.setdefault(row[1], []).append(row)
        for speaker, lane in lanes.items():
            for (key, _s, start, _e), (_k, _s2, next_start, _e2) in zip(lane, lane[1:]):
                end = ends[key]
                if not (end < next_start <= end + threshold) or not fits(start, next_start):
                    continue
                if any(end < other < next_start and who != speaker for other, who in starts):
                    continue
                ends[key] = next_start
    return {key: end for key, end in ends.items() if end != original[key]}
