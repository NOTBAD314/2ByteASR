"""Independent caption objects in integer project time, with immutable source receipts.

The additive studio_state receipt freezes the currently displayed legacy projection
once. It preserves original cues and acoustic evidence; video ownership never grants
or denies caption editing. All destructive interval edits use [start, end).
"""
from __future__ import annotations
import copy
import uuid
from dataclasses import asdict
from PySide6.QtGui import QUndoCommand

KEY = 'caption_timeline'
DISABLED_KEY = 'caption_ripple_disabled_speakers'
# Receipt field: project time minus the clock of the caption's evidence rows.
# Kept through moves, ripples, splits and merges; absent when unknown.
CLOCK = 'evidence_clock_offset_ms'


def independent_captions(project):
    return project.render_settings.get('_cue_domain') == 'timeline'


def ensure_independent_captions(project):
    """Idempotently freeze actual visible positions, never replay a historic cut."""
    if project is None or independent_captions(project):
        return False
    from .studio_edit_sequence import projected_cues, source_cue_id_of
    from .cue_word_alignment import cue_words
    original = copy.deepcopy(project.cues)
    visible = copy.deepcopy(projected_cues(project))
    sources = {c.id: c for c in original}
    instances = {}
    for cue in visible:
        source = sources.get(source_cue_id_of(cue.id), cue)
        words, reason = cue_words(project, cue)
        instances[cue.id] = {
            'source_cue_id': source.id,
            'source_start_ms': source.start_ms, 'source_end_ms': source.end_ms,
            'source_path': project.media.path,
            'evidence_refs': list(source.evidence_refs),
            'text': cue.text,
            'word_alignment': reason,
            'words': [asdict(w) for w in words],
            'word_base_interval': [cue.start_ms, cue.end_ms],
            'word_base_words': [asdict(w) for w in words],
            'word_base_alignment': reason,
        }
        if cue.end_ms - cue.start_ms == source.end_ms - source.start_ms:
            # An unclipped 1x projection: evidence time + this offset is
            # project time, so missing words can be re-derived later.
            instances[cue.id][CLOCK] = cue.start_ms - source.start_ms
        prior = (project.studio_state.get(KEY) or {}).get('instances', {}).get(source.id, {})
        if prior.get('source_spans'):
            instances[cue.id]['source_spans'] = copy.deepcopy(prior['source_spans'])
    project.studio_state[KEY] = {
        'version': 1, 'source_archive': [asdict(c) for c in original],
        'instances': instances,
    }
    project.cues = visible
    project.render_settings['_cue_domain'] = 'timeline'
    return True


def _word_clock(project, words, cache):
    """Most common project-minus-evidence offset of measured caption words."""
    from collections import Counter
    from .cue_word_alignment import evidence_tokens
    votes = Counter()
    for word in words:
        ref = word.evidence_ref
        if ref not in cache:
            records, _pending, _derived = evidence_tokens(project, [ref])
            index = {}
            for a, b, text, _ref in records:
                index.setdefault((text, b - a), []).append(a)
            cache[ref] = index
        starts = cache[ref].get((word.text, word.end_ms - word.start_ms), ())
        if len(starts) == 1:
            votes[word.start_ms - starts[0]] += 1
    if not votes:
        return None
    (offset, count), *rest = votes.most_common(2)
    return offset if count >= 2 and (not rest or rest[0][1] * 2 < count) else None


def recover_caption_words(project):
    """Re-derive missing caption words from the project's saved evidence.

    Earlier builds froze an empty word list whenever an edited spelling,
    a removed filler or a duplicated FireRed token blocked an exact match,
    and a split of such a caption stayed empty forever. The evidence is still
    in the project. Each caption is re-aligned on a clock taken from its own
    receipt, else from the nearest captions whose words map back to evidence,
    else zero; a clock counts only when the text aligns on the caption itself.
    Recovered receipts say so in ``word_recovery``. Returns the count.
    """
    if project is None or not independent_captions(project) or KEY not in project.studio_state:
        return 0
    import bisect
    from .cue_word_alignment import cue_words, recover_words_from_evidence
    receipts = project.studio_state[KEY].setdefault('instances', {})
    ordered = sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
    cache = {}
    clocks = []
    missing = []
    for cue in ordered:
        receipt = receipts.get(cue.id)
        if not receipt:
            continue
        words, _reason = cue_words(project, cue)
        if not words:
            missing.append(cue)
        elif CLOCK in receipt:
            clocks.append((cue.start_ms, cue.speaker_id, int(receipt[CLOCK])))
        else:
            offset = _word_clock(project, words, cache)
            if offset is not None:
                clocks.append((cue.start_ms, cue.speaker_id, offset))
    starts = [row[0] for row in clocks]
    recovered = 0
    for cue in missing:
        receipt = receipts[cue.id]
        if CLOCK in receipt:
            candidates = [int(receipt[CLOCK])]
        else:
            at = bisect.bisect_left(starts, cue.start_ms)
            nearby = sorted(clocks[max(0, at - 4):at + 4],
                            key=lambda row: (row[1] != cue.speaker_id, abs(row[0] - cue.start_ms)))
            candidates = list(dict.fromkeys([row[2] for row in nearby] + [0]))
        words, reason, offset = recover_words_from_evidence(project, cue, receipt, candidates)
        if not words:
            continue
        previous = receipt.get('word_alignment', '')
        rows = [asdict(w) for w in words]
        receipt.update(text=cue.text, words=rows, word_alignment=reason,
                       word_base_interval=[cue.start_ms, cue.end_ms], word_base_words=copy.deepcopy(rows),
                       word_base_alignment=reason, word_clock_offset_ms=0)
        receipt[CLOCK] = offset
        receipt['word_recovery'] = {'source': 'project_asr_evidence', 'clock_offset_ms': offset,
                                    'previous_alignment': previous}
        recovered += 1
    return recovered


def locked_caption_speakers(project, page=None, explicit=()):
    locked = set(explicit) | set(project.studio_state.get('locked_speakers', ()))
    if page is not None:
        locked.update(getattr(page.timeline, 'locked_speakers', ()))
    return locked


def caption_ripple_skipped(project, locked=()):
    present = {c.speaker_id for c in project.cues}
    return present.intersection(set(locked) | set(project.studio_state.get(DISABLED_KEY, ())))


def _words(project, cue):
    from .cue_word_alignment import cue_words
    words, reason = cue_words(project, cue)
    return [asdict(w) for w in words], reason


def _remember(project, cue, parent, words, reason, review=None, clock_delta=0):
    state = project.studio_state.setdefault(KEY, {'version': 1, 'instances': {}})
    receipts = state.setdefault('instances', {})
    receipt = copy.deepcopy(receipts.get(parent.id, {}))
    receipt.update(text=cue.text, words=copy.deepcopy(words), word_alignment=reason,
                   word_base_interval=[cue.start_ms, cue.end_ms], word_base_words=copy.deepcopy(words),
                   word_base_alignment=reason, word_clock_offset_ms=0)
    if CLOCK in receipt:
        receipt[CLOCK] = int(receipt[CLOCK]) + int(clock_delta)
    if review:
        receipt['needs_review'] = review
        from .studio_edit_sequence import source_cue_id_of
        statuses = project.studio_state.setdefault('cue_statuses', {})
        statuses[source_cue_id_of(cue.id)] = 'issue'
    receipts[cue.id] = receipt


def _shift_term_override(project, cue_id, delta):
    """A batch-replace word override is measured on the project clock too.

    cue_words prefers an exact (case/deletion-only) override over the
    receipt, so it has to travel with the caption; otherwise a moved caption
    keeps its old word times and the razor cuts at the wrong place. Shifted
    regardless of the current text so an undone text edit finds it in place.
    """
    override = project.studio_state.get('term_word_overrides', {}).get(cue_id)
    if not delta or not override:
        return
    for word in override.get('words', ()):
        word['start_ms'] += delta; word['end_ms'] += delta


def shift_caption(project, cue, delta):
    words, reason = _words(project, cue)
    for word in words:
        word['start_ms'] += delta; word['end_ms'] += delta
    cue.start_ms += delta; cue.end_ms += delta
    _remember(project, cue, cue, words, reason, clock_delta=delta)
    _shift_term_override(project, cue.id, delta)


def sync_caption_interval_words(project, cue, previous):
    """Trim only the display envelope; move measured words by a rigid offset."""
    if not independent_captions(project):
        return
    receipt = project.studio_state.get(KEY, {}).get('instances', {}).get(cue.id)
    if not receipt:
        return
    base_start, base_end = receipt.setdefault('word_base_interval', list(previous))
    base_words = receipt.setdefault('word_base_words', copy.deepcopy(receipt.get('words', ())))
    base_alignment = receipt.setdefault('word_base_alignment', receipt.get('word_alignment', 'missing_word_timestamps'))
    offset = int(receipt.get('word_clock_offset_ms', 0))
    if cue.end_ms-cue.start_ms == previous[1]-previous[0]:
        offset += cue.start_ms-previous[0]
        if CLOCK in receipt:
            receipt[CLOCK] = int(receipt[CLOCK]) + cue.start_ms-previous[0]
        _shift_term_override(project, cue.id, cue.start_ms-previous[0])
    receipt['word_clock_offset_ms'] = offset
    receipt['words'] = copy.deepcopy(base_words)
    for word in receipt['words']:
        word['start_ms'] += offset; word['end_ms'] += offset
    receipt['word_alignment'] = base_alignment
    receipt['display_interval'] = [cue.start_ms, cue.end_ms]



def caption_replacement_receipts(project, removed, inserted):
    """Keep proven token order for structural splits/merges, with local undo data."""
    if not independent_captions(project) or KEY not in project.studio_state:
        return None, None
    from .cue_word_alignment import content_positions
    receipts=project.studio_state[KEY].get('instances', {})
    keys={c.id for c in (*removed,*inserted)}
    before={key:copy.deepcopy(receipts.get(key)) for key in keys}
    after=copy.deepcopy(before)
    stream=[];tokens=[];cursor=0;derived=False
    for cue in removed:
        positions=content_positions(cue.text);stream.extend(char for _,char in positions)
        words,source_reason=_words(project,cue)
        derived=derived or source_reason=='derived_term_source_span'
        for word in words:
            lo=cursor+sum(index<word['char_start'] for index,_ in positions)
            hi=cursor+sum(index<word['char_end'] for index,_ in positions)
            tokens.append((lo,hi,word))
        cursor+=len(positions)
    wanted=[char for cue in inserted for _,char in content_positions(cue.text)]
    conserved=wanted==stream and bool(tokens)
    cursor=0
    for cue in inserted:
        positions=content_positions(cue.text);end=cursor+len(positions)
        rows=[(lo,hi,word) for lo,hi,word in tokens if cursor<=lo<hi<=end]
        complete=bool(rows) and rows[0][0]==cursor and rows[-1][1]==end and all(
            b[0]==a[1] for a,b in zip(rows,rows[1:]))
        words=[]
        if conserved and complete:
            for lo,hi,word in rows:
                item=copy.deepcopy(word)
                item['char_start']=positions[lo-cursor][0]
                item['char_end']=positions[hi-cursor-1][0]+1
                words.append(item)
        parent=next((c for c in removed if c.id==cue.id),removed[0] if removed else None)
        receipt=copy.deepcopy(receipts.get(parent.id,{})) if parent else {}
        ids=list(dict.fromkeys(source for c in removed for source in receipts.get(c.id,{}).get(
            'source_cue_ids',[receipts.get(c.id,{}).get('source_cue_id',c.id)])))
        spans = []
        for original in removed:
            for span in receipts.get(original.id, {}).get('source_spans', []):
                if span not in spans:
                    spans.append(copy.deepcopy(span))
        if spans:
            receipt['source_spans'] = spans
        clocks={receipts.get(c.id,{}).get(CLOCK) for c in removed}
        if len(clocks)==1 and None not in clocks:
            receipt[CLOCK]=next(iter(clocks))
        else:
            receipt.pop(CLOCK,None)
        # A split keeps the measured basis of its parent words, including
        # whole replaced spans; it never re-allocates them.
        reason=('derived_term_source_span' if derived else 'exact_token_text') if words else 'structural_edit_requires_acoustic_alignment'
        receipt.update(text=cue.text,words=words,word_alignment=reason,
            word_base_interval=[cue.start_ms,cue.end_ms],word_base_words=copy.deepcopy(words),
            word_base_alignment=reason,source_cue_ids=ids,word_clock_offset_ms=0)
        after[cue.id]=receipt;cursor=end
    return before,after

def ripple_caption_range(project, start, end, *, locked=()):
    """Apply one deletion once to all eligible caption tracks.

    Exact tokens remain indivisible. Without an exact token stream, retain text
    once in the surviving compressed interval and mark it for manual review.
    This never distributes text proportionally or duplicates a whole sentence.
    """
    ensure_independent_captions(project)
    delta = end-start
    skipped = caption_ripple_skipped(project, locked)
    output = []
    for cue in project.cues:
        a, b = cue.start_ms, cue.end_ms
        if cue.speaker_id in skipped or b <= start:
            output.append(cue); continue
        if a >= end:
            shift_caption(project, cue, -delta); output.append(cue); continue
        if start <= a and b <= end:
            continue
        words, reason = _words(project, cue)
        if words:
            left = [w for w in words if w['end_ms'] <= start]
            right = [w for w in words if w['start_ms'] >= end]
            removed_boundary_words = any(w['start_ms'] < end and w['end_ms'] > start for w in words)
            groups = [(left, 0), (right, -delta)]
            kept = 0
            for rows, offset in groups:
                if not rows:
                    continue
                item = copy.deepcopy(cue)
                if kept:
                    item.id = cue.id + '-part-' + uuid.uuid4().hex[:10]
                lo, hi = rows[0]['char_start'], rows[-1]['char_end']
                if rows[0] is words[0]: lo = 0
                if rows[-1] is words[-1]: hi = len(cue.text)
                item.text = cue.text[lo:hi]
                item.start_ms = max(a, rows[0]['start_ms']) + offset
                item.end_ms = min(b, rows[-1]['end_ms']) + offset
                if item.end_ms <= item.start_ms or not item.text.strip():
                    continue
                adjusted = copy.deepcopy(rows)
                for w in adjusted:
                    w['char_start'] -= lo; w['char_end'] -= lo
                    w['start_ms'] += offset; w['end_ms'] += offset
                _remember(project, item, cue, adjusted, reason,
                          'word_crosses_deleted_boundary' if removed_boundary_words else None,
                          clock_delta=offset)
                output.append(item); kept += 1
            if kept:
                continue
            # No complete token survives, but surviving speech time is still
            # retained once with an explicit review receipt.
            reason = 'no_complete_surviving_token'
        item = copy.deepcopy(cue)
        item.start_ms = a if a < start else start
        item.end_ms = b-delta if b > end else start
        if item.end_ms > item.start_ms:
            _remember(project, item, cue, [], reason,
                      'ripple_boundary_requires_manual_text_review:' + reason)
            if a < start and b > end:
                # Text spans both sides of the deleted range: no single clock.
                project.studio_state[KEY]['instances'][item.id].pop(CLOCK, None)
            elif a >= start and CLOCK in project.studio_state[KEY]['instances'][item.id]:
                project.studio_state[KEY]['instances'][item.id][CLOCK] -= delta
            output.append(item)
    project.cues = sorted(output, key=lambda c: (c.start_ms, c.end_ms, c.id))
    return skipped


STASH_KEY = 'generated_edit_caption_stash'


def _to_source(sequence, time_ms, *, end=False):
    """(segment, source ms) for a project time on V1; ``end`` closes the interval."""
    for segment in sequence.segments:
        inside = (segment.timeline_in_ms < time_ms <= segment.timeline_out_ms if end
                  else segment.timeline_in_ms <= time_ms < segment.timeline_out_ms)
        if inside:
            rate = segment.source_duration_ms / max(1, segment.duration_ms)
            return segment, segment.source_in_ms + (time_ms - segment.timeline_in_ms) * rate
    return None, None


def _to_time(segment, source_ms):
    rate = segment.source_duration_ms / max(1, segment.duration_ms)
    return round(segment.timeline_in_ms + (source_ms - segment.source_in_ms) / rate)


def _source_of(sequence, segment):
    from .studio_project import _normalized_media_source
    return _normalized_media_source(segment.source_path or sequence.source_path)


def remap_captions_to_sequence(project, before, after, *, locked=()):
    """Carry independent captions from one V1 arrangement to another.

    Used when a whole sequence is replaced (generate from the clip bin, return
    to the full recording). Each caption is followed through SOURCE time: the
    old arrangement says which source moment it shows, the new one where that
    moment now plays. Measured words are indivisible, exactly as in a ripple:
    a cut keeps whole words on each side and never shares text by length.
    A caption without measured words is moved whole when it survives whole,
    otherwise kept once with a review receipt. Captions with no kept source are
    removed and returned (source anchored) so the full recording can restore
    them. Locked or ripple-disabled caption tracks are not moved.
    """
    ensure_independent_captions(project)
    skipped = caption_ripple_skipped(project, locked)
    targets = sorted(after.segments, key=lambda s: (s.timeline_in_ms, s.id))
    receipts = project.studio_state.setdefault(KEY, {'version': 1, 'instances': {}}).setdefault('instances', {})
    output, dropped = [], []
    for cue in project.cues:
        if cue.speaker_id in skipped:
            output.append(cue)
            continue
        words, reason = _words(project, cue)
        start_segment, start_source = _to_source(before, cue.start_ms)
        end_segment, end_source = _to_source(before, cue.end_ms, end=True)
        created = []
        original_receipt = copy.deepcopy(receipts.get(cue.id))
        mapped_words = []
        for word in words:
            first, a = _to_source(before, word['start_ms'])
            last, b = _to_source(before, word['end_ms'], end=True)
            mapped_words.append((word, first if first is not None and first is last else None, a, b))
        pieces = []
        if words:
            for target in targets:
                path = _source_of(after, target)
                runs, run = [], []
                for word, origin, a, b in mapped_words:
                    keep = (origin is not None and _source_of(before, origin) == path
                            and target.source_in_ms <= a and b <= target.source_out_ms)
                    if keep and run and run[-1][1] is origin:
                        run.append((word, origin, a, b))
                    elif keep:
                        if run:
                            runs.append(run)
                        run = [(word, origin, a, b)]
                    elif run:
                        runs.append(run); run = []
                if run:
                    runs.append(run)
                for run in runs:
                    pieces.append((target, run))
            pieces.sort(key=lambda item: _to_time(item[0], item[1][0][2]))

            def cut_through(origin, a, b):
                """A word that a kept-range boundary (or an old seam) cuts in two."""
                if origin is None:
                    return True
                path = _source_of(before, origin)
                same = [t for t in targets if _source_of(after, t) == path]
                inside = any(t.source_in_ms <= a and b <= t.source_out_ms for t in same)
                touched = any(a < t.source_out_ms and t.source_in_ms < b for t in same)
                return touched and not inside
            crossed = any(cut_through(origin, a, b) for _word, origin, a, b in mapped_words)
            kept_words = sum(len(run) for _target, run in pieces)
            for index, (target, run) in enumerate(pieces):
                item = copy.deepcopy(cue)
                if index:
                    item.id = cue.id + '-part-' + uuid.uuid4().hex[:10]
                lo, hi = run[0][0]['char_start'], run[-1][0]['char_end']
                first_word, last_word = run[0][0] is words[0], run[-1][0] is words[-1]
                if first_word:
                    lo = 0
                if last_word:
                    hi = len(cue.text)
                item.text = cue.text[lo:hi]
                begin = _to_time(target, run[0][2])
                finish = _to_time(target, run[-1][3])
                if (first_word and start_segment is run[0][1]
                        and target.source_in_ms <= start_source < target.source_out_ms):
                    begin = _to_time(target, start_source)
                if (last_word and end_segment is run[-1][1]
                        and target.source_in_ms < end_source <= target.source_out_ms):
                    finish = _to_time(target, end_source)
                item.start_ms, item.end_ms = begin, finish
                if item.end_ms <= item.start_ms or not item.text.strip():
                    continue
                adjusted = copy.deepcopy([word for word, _origin, _a, _b in run])
                for word, (_w, _origin, a, b) in zip(adjusted, run):
                    word['char_start'] -= lo; word['char_end'] -= lo
                    word['start_ms'], word['end_ms'] = _to_time(target, a), _to_time(target, b)
                offset = adjusted[0]['start_ms'] - run[0][0]['start_ms']
                review = 'word_crosses_generated_cut' if crossed else None
                _remember(project, item, cue, adjusted, reason, review, clock_delta=offset)
                output.append(item); created.append(item.id)
            if pieces and kept_words == len(words):
                continue
        else:
            # Source pieces this caption shows on the old V1 (several after a cut).
            spans = []
            for segment in before.segments:
                lo = max(cue.start_ms, segment.timeline_in_ms)
                hi = min(cue.end_ms, segment.timeline_out_ms)
                if hi > lo:
                    rate = segment.source_duration_ms / max(1, segment.duration_ms)
                    spans.append((segment, segment.source_in_ms + (lo - segment.timeline_in_ms) * rate,
                                  segment.source_in_ms + (hi - segment.timeline_in_ms) * rate))
            whole = len(spans) == 1 and start_segment is end_segment is spans[0][0]
            for target in targets:
                if not whole:
                    break
                origin, a, b = spans[0]
                if _source_of(before, origin) != _source_of(after, target):
                    continue
                if target.source_in_ms <= a and b <= target.source_out_ms:
                    item = copy.deepcopy(cue)
                    item.start_ms, item.end_ms = _to_time(target, a), _to_time(target, b)
                    _remember(project, item, cue, [], reason, clock_delta=item.start_ms - cue.start_ms)
                    output.append(item); created.append(item.id)
                    pieces.append((target, None))
                    break
            if pieces:
                continue
            # Cut across, or spanning several source pieces: keep the text once
            # where it first plays, for a person to check. Never split by length.
            for target in targets:
                overlaps = [(max(a, target.source_in_ms), min(b, target.source_out_ms))
                            for origin, a, b in spans
                            if _source_of(before, origin) == _source_of(after, target)]
                overlaps = [(a, b) for a, b in overlaps if b > a]
                if not overlaps:
                    continue
                item = copy.deepcopy(cue)
                item.start_ms, item.end_ms = _to_time(target, overlaps[0][0]), _to_time(target, overlaps[0][1])
                if item.end_ms > item.start_ms:
                    _remember(project, item, cue, [], reason,
                              'generated_edit_cut_requires_manual_text_review:' + reason,
                              clock_delta=item.start_ms - cue.start_ms)
                    receipts[item.id].pop(CLOCK, None)
                    output.append(item); created.append(item.id)
                    pieces.append((target, None))
                    break
            if pieces:
                continue
        anchor = None
        if start_segment is not None:
            anchor = dict(source_path=_source_of(before, start_segment), source_start_ms=round(start_source),
                          source_end_ms=round(end_source) if end_segment is start_segment
                          else round(start_source + (cue.end_ms - cue.start_ms)))
        dropped.append(dict(cue=asdict(cue), receipt=original_receipt, anchor=anchor,
                            parts=created))
    project.cues = sorted(output, key=lambda c: (c.start_ms, c.end_ms, c.id))
    return skipped, dropped


def stash_generated_edit_captions(project, dropped):
    """Remember captions a generated edit left out, anchored in source time."""
    if not dropped:
        return
    stash = project.studio_state.setdefault(STASH_KEY, {'version': 1, 'entries': []})
    stash['entries'].extend(copy.deepcopy(dropped))


def restore_generated_edit_captions(project, media_path):
    """Put stashed captions back on the full recording (project time = source time)."""
    from .studio_project import StudioCue, _normalized_media_source
    stash = project.studio_state.pop(STASH_KEY, None)
    if not stash:
        return 0
    receipts = project.studio_state.setdefault(KEY, {'version': 1, 'instances': {}}).setdefault('instances', {})
    wanted = _normalized_media_source(media_path)
    restored = 0
    cues = list(project.cues)
    for entry in stash.get('entries', ()):
        anchor = entry.get('anchor') or {}
        if anchor.get('source_path') != wanted:
            continue
        parts = set(entry.get('parts') or ())
        cues = [cue for cue in cues if cue.id not in parts]
        for part in parts:
            receipts.pop(part, None)
        original = StudioCue(**entry['cue'])
        delta = int(anchor['source_start_ms']) - original.start_ms
        original.start_ms += delta
        original.end_ms = int(anchor['source_end_ms'])
        receipt = copy.deepcopy(entry.get('receipt') or {})
        for word in receipt.get('words', ()):
            word['start_ms'] += delta; word['end_ms'] += delta
        if receipt:
            receipt['word_base_interval'] = [original.start_ms, original.end_ms]
            receipt['word_base_words'] = copy.deepcopy(receipt.get('words', []))
            receipt['word_clock_offset_ms'] = 0
            if CLOCK in receipt:
                receipt[CLOCK] = int(receipt[CLOCK]) + delta
            receipts[original.id] = receipt
        cues.append(original)
        restored += 1
    project.cues = sorted(cues, key=lambda c: (c.start_ms, c.end_ms, c.id))
    return restored


class SetCaptionRippleCommand(QUndoCommand):
    def __init__(self, project, speaker_id, enabled, changed=None):
        super().__init__('跟随波纹编辑' if enabled else '停止跟随波纹编辑')
        self.project, self.changed = project, changed
        self.before = list(project.studio_state.get(DISABLED_KEY, ()))
        disabled = set(self.before)
        disabled.discard(speaker_id) if enabled else disabled.add(speaker_id)
        self.after = sorted(disabled)

    def _apply(self, values):
        from .studio_runtime_state import state_for, DirtyDomain as D
        with state_for(self.project).transaction(self.project, action_id=self.text(),
                dirty=D.PROJECT_METADATA | D.TIMELINE_PIXELS | D.AUTOSAVE):
            self.project.studio_state[DISABLED_KEY] = list(values)
        if self.changed: self.changed()

    def redo(self): self._apply(self.after)
    def undo(self): self._apply(self.before)


def set_caption_ripple_command(project, speaker_id, enabled, changed=None):
    return SetCaptionRippleCommand(project, speaker_id, enabled, changed)
