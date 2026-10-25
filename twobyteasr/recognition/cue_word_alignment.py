"""Measured token evidence for a cue's current text, in the cue's time domain.

Multi-character tokens remain indivisible. Punctuation and whitespace have no
invented acoustic duration. Persisted evidence remains immutable across
undo/splits.

The current text is matched against measured tokens. An exact match keeps each
token. Otherwise the text is aligned to the heard tokens: removed fillers or
stutters leave every other token on its own interval; a replaced spelling keeps
the whole original span and cannot be cut inside; text with no heard
counterpart is merged with both neighbours, so no boundary is claimed beside
it. Nothing is ever distributed by character count or duration. When no
alignment is proven the reason is returned instead of words.

Matching ignores 简/繁 (2026-10-19): a cue delivered or edited in 繁體 still
matches its Simplified evidence, and its words carry the cue's own characters.
"""
from dataclasses import dataclass, replace
import copy
from collections.abc import Mapping
import difflib
from functools import lru_cache
from bisect import bisect_left
import unicodedata

from ..subtitle_rules.chinese_script import fold_map


def content_positions(text, *, fold=True):
    script = fold_map() if fold else {}
    return [(i, script.get(normalized, normalized)) for i, char in enumerate(text)
            if not char.isspace() and not unicodedata.category(char).startswith(('P', 'Z'))
            for normalized in char.casefold()]


def normalized_content(text, *, fold=True):
    return ''.join(c for _, c in content_positions(text, fold=fold))


@dataclass(frozen=True)
class AlignedWord:
    text: str
    char_start: int
    char_end: int
    start_ms: int
    end_ms: int
    evidence_ref: str


EXACT_OVERRIDES = frozenset({'case_only', 'deletion_only'})
# Reasons whose words are measured token intervals (whole spans for replaced
# spellings). Anything else is a missing-alignment reason.
MEASURED_ALIGNMENTS = frozenset({'exact_token_text', 'derived_term_source_span'})
TERM_PENDING = 'term_local_mapping_requires_acoustic_alignment'
# A non-exact alignment needs this share of the text heard verbatim, and at
# least two such characters, before any replaced span is trusted.
MIN_VERBATIM_SHARE = 0.5
MIN_VERBATIM_CHARS = 2
# Tokens considered around a cue when its text is not an exact substring.
ALIGN_WINDOW_MS = 1500
# Tokens of different rows that overlap this much are alternate transcripts.
STREAM_CONFLICT_MS = 40
# FireRed sometimes stretches a row's first token over the preceding silence.
PADDED_TOKEN_MS = 1000
# Arbitrary repeated text can make SequenceMatcher quadratic. A failed derived
# alignment is recoverable; it must never hold an interactive event for seconds.
MAX_ALIGNMENT_COMPARISONS = 1_000_000


@lru_cache(maxsize=32)
def _alignment_opcodes(source, target):
    # Cache only the exact strings/opcodes, never times or project identity.
    # Different evidence timing therefore always rebuilds the measured words.
    return tuple(difflib.SequenceMatcher(None, source, target, autojunk=False).get_opcodes())


def _token_ms(token):
    start = round(float(token['start_ms'])) if 'start_ms' in token else round(float(token['start']) * 1000)
    end = round(float(token['end_ms'])) if 'end_ms' in token else round(float(token['end']) * 1000)
    return start, end


def evidence_tokens(project, refs, rows=None):
    """Measured tokens of immutable evidence rows in the rows' own clock.

    Returns ``(records, term_pending, derived)``; each record is
    ``(start_ms, end_ms, normalized_text, ref)``. A row whose text was changed
    after recognition (terminology or number formatting) only contributes its
    FireRed observations, which still carry the heard spelling; its remapped
    ``words`` are derived and never used.
    """
    from .word_timing_provenance import estimated_word_timing
    from .cue_forced_alignment import is_cue_alignment_row
    if rows is None:
        rows = [(ref, project.asr_evidence.get(ref, {})) for ref in refs]
    # A caption's own forced alignment of its current text supersedes the
    # segment rows it overlaps (whose tokens are another text's timing).
    own = [(ref, row) for ref, row in rows if is_cue_alignment_row(row)]
    if own:
        rows = own
    records = []
    term_pending = False
    derived = False
    for ref, row in rows:
        if not isinstance(row, dict):
            continue
        arbitration = row.get('caption_arbitration') or {}
        if not isinstance(arbitration, Mapping):
            continue
        term_receipts = (*arbitration.get('terminology_normalization', ()),
                         *arbitration.get('numeric_formatting', ()))
        acoustic = arbitration.get('acoustic_words')
        text_changed = any(isinstance(receipt, dict) and (
            receipt.get('requires_acoustic_alignment')
            or receipt.get('alignment_provenance') == 'term_local_mapping'
            or receipt.get('timing') == 'segment-only-no-word-alignment')
            for receipt in term_receipts)
        if text_changed and not acoustic:
            # Production rows persist the normalized words beside the original
            # timing owner. Matching that new text alone proves nothing.
            term_pending = True
            continue
        derived = derived or any(
            isinstance(receipt, dict) and receipt.get('alignment_provenance') == 'derived_term_source_span'
            and receipt.get('span_mappings') and all(
                mapping.get('precision') == 'whole_original_word_span'
                for mapping in receipt['span_mappings']) for receipt in term_receipts)
        owner = str(row.get('final_timing_owner', '')).casefold()
        if estimated_word_timing(row) and not acoustic:
            continue
        if any(word in owner for word in ('estimated', 'proportional', 'degraded', '估算', '均分')):
            continue
        tokens = acoustic or row.get('words', ())
        if not isinstance(tokens, (list, tuple)):
            continue
        for token in tokens:
            if not isinstance(token, Mapping):
                continue
            text = str(token.get('text', token.get('word', '')))
            try:
                start, end = _token_ms(token)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            normalized = normalized_content(text)
            if normalized and end > start:
                records.append((start, end, normalized, str(ref)))
    return records, term_pending, derived


def _stream(records):
    """Sorted unique tokens, or None when two rows are alternate transcripts."""
    records = sorted({(a, b, text): (a, b, text, ref) for a, b, text, ref in records}.values())
    for left, right in zip(records, records[1:]):
        # The same row may repeat or pad a token (a stutter, or a first token
        # that absorbed seconds of leading silence); the alignment chooses
        # which survives. Only ordinary tokens prove alternate transcripts.
        if (right[0] < left[1] - STREAM_CONFLICT_MS and left[3] != right[3]
                and left[2] != right[2] and left[1] - left[0] <= PADDED_TOKEN_MS):
            return None
    return records


def _monotonic(words):
    """Clip a padded end to the next onset; refuse reordered onsets."""
    result = list(words)
    for index in range(len(result) - 1):
        left, right = result[index], result[index + 1]
        if right.start_ms <= left.start_ms:
            return None
        if left.end_ms > right.start_ms:
            result[index] = AlignedWord(left.text, left.char_start, left.char_end,
                                        left.start_ms, right.start_ms, left.evidence_ref)
    return result


def _exact(target, positions, records, interval):
    source = ''.join(r[2] for r in records)
    offsets = []
    cursor = 0
    for start, end, text, ref in records:
        offsets.append((cursor, cursor + len(text), start, end, text, ref))
        cursor += len(text)
    starts = [row[0] for row in offsets]
    best = None
    ambiguous = False
    at = source.find(target)
    while at >= 0:
        lo = bisect_left(starts, at)
        hi = bisect_left(starts, at + len(target))
        if (lo < hi and offsets[lo][0] == at and offsets[hi - 1][1] == at + len(target)
                and offsets[hi - 1][3] > interval[0] and offsets[lo][2] < interval[1]):
            distance = abs(offsets[lo][2] - interval[0]) + abs(offsets[hi - 1][3] - interval[1])
            if best is None or distance < best[0]:
                best, ambiguous = (distance, at, lo, hi), False
            elif distance == best[0]:
                ambiguous = True
        at = source.find(target, at + 1)
    if best is None:
        return None, 'text_changed_or_inside_multi_character_token'
    if ambiguous:
        return None, 'ambiguous_repeated_text'
    _, at, lo, hi = best
    return [AlignedWord(text, positions[a - at][0], positions[b - at - 1][0] + 1, start, end, ref)
            for a, b, start, end, text, ref in offsets[lo:hi]], 'exact_token_text'


def _aligned(target, positions, records, interval):
    """Units of the current text over heard tokens; see the module docstring."""
    window = [r for r in records
              if r[1] > interval[0] - ALIGN_WINDOW_MS and r[0] < interval[1] + ALIGN_WINDOW_MS]
    if not window:
        return None, 'text_changed_or_inside_multi_character_token'
    source = ''.join(r[2] for r in window)
    owner = [index for index, record in enumerate(window) for _ in record[2]]
    if len(source) * len(target) > MAX_ALIGNMENT_COMPARISONS or max(len(source), len(target)) > 8192:
        return None, 'alignment_complexity_limit'
    links = [set() for _ in target]     # heard tokens behind each target char
    exact_char = [False] * len(target)
    joined = []                         # (j, j+1) pairs that must stay together
    inserted = []
    verbatim = 0
    for tag, i1, i2, j1, j2 in _alignment_opcodes(source, target):
        if tag == 'equal':
            verbatim += j2 - j1
            for k in range(j2 - j1):
                links[j1 + k].add(owner[i1 + k])
                exact_char[j1 + k] = True
        elif tag == 'replace':
            heard = {owner[i] for i in range(i1, i2)}
            for j in range(j1, j2):
                links[j] |= heard
            joined.extend((j, j + 1) for j in range(j1, j2 - 1))
        elif tag == 'insert':
            inserted.append((j1, j2))
    if verbatim < min(MIN_VERBATIM_CHARS, len(target)) or verbatim < MIN_VERBATIM_SHARE * len(target):
        return None, 'text_changed_or_inside_multi_character_token'
    for j1, j2 in inserted:
        # Unheard text has no measured side: keep it with both neighbours.
        joined.extend((j, j + 1) for j in range(max(0, j1 - 1), min(len(target) - 1, j2)))
    parent = list(range(len(target)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        parent[find(b)] = find(a)

    for a, b in joined:
        union(a, b)
    for j in range(len(target) - 1):
        if links[j] & links[j + 1] or positions[j][0] == positions[j + 1][0]:
            union(j, j + 1)
    groups = []
    for j in range(len(target)):
        if groups and find(groups[-1][0]) == find(j):
            groups[-1].append(j)
        else:
            groups.append([j])
    words = []
    all_exact = True
    for group in groups:
        heard = sorted(set().union(*(links[j] for j in group)))
        if not heard:
            return None, 'text_changed_or_inside_multi_character_token'
        if heard != list(range(heard[0], heard[-1] + 1)):
            heard = list(range(heard[0], heard[-1] + 1))
        text = ''.join(target[j] for j in group)
        tokens = [window[i] for i in heard]
        exact = len(tokens) == 1 and tokens[0][2] == text and all(exact_char[j] for j in group)
        all_exact = all_exact and exact
        words.append(AlignedWord(text, positions[group[0]][0], positions[group[-1]][0] + 1,
                                 min(t[0] for t in tokens), max(t[1] for t in tokens), tokens[0][3]))
    for left, right in zip(words, words[1:]):
        if right.start_ms < left.start_ms:
            return None, 'overlapping_token_streams'
    if not (words[-1].end_ms > interval[0] and words[0].start_ms < interval[1]):
        return None, 'text_changed_or_inside_multi_character_token'
    return words, 'exact_token_text' if all_exact else 'derived_term_source_span'


def align_text_to_tokens(text, records, interval, *, derived=False, allow_realign=True):
    """Words of ``text`` over measured ``records`` near ``interval``.

    The single matcher behind recognition evidence, edited captions and
    recovered receipts. Returns ``(words, reason)``; ``words`` is empty when
    no alignment is proven.
    """
    positions = content_positions(text)
    target = ''.join(c for _, c in positions)
    if not target or not records:
        return (), 'missing_word_timestamps'
    stream = _stream(records)
    if stream is None:
        return (), 'overlapping_token_streams'
    words, reason = _exact(target, positions, stream, interval)
    if allow_realign and words is None and reason != 'ambiguous_repeated_text':
        words, reason = _aligned(target, positions, stream, interval)
    if words is None:
        return (), reason
    words = _monotonic(words)
    if words is None:
        return (), 'overlapping_token_streams'
    if target != normalized_content(text, fold=False):
        # Matched across scripts: each word shows the cue's characters, not the heard spelling.
        words = [replace(w, text=normalized_content(text[w.char_start:w.char_end], fold=False)) for w in words]
    if derived and reason == 'exact_token_text':
        reason = 'derived_term_source_span'
    return tuple(words), reason


def _receipt_tokens(rows):
    records = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            start, end = int(row['start_ms']), int(row['end_ms'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        normalized = normalized_content(str(row.get('text', '')))
        if normalized and end > start:
            records.append((start, end, normalized, str(row.get('evidence_ref', ''))))
    return records


def recover_words_from_evidence(project, cue, receipt, offsets, *, allow_realign=True):
    """Re-align the immutable evidence of an independent caption.

    ``offsets`` are candidate project-minus-evidence clocks. A clock is used
    only when the cue text aligns to tokens lying on the cue itself.
    """
    refs = list(receipt.get('evidence_refs') or cue.evidence_refs)
    if not refs:
        return (), None, None
    records, pending, derived = evidence_tokens(project, refs)
    if not records:
        return (), (TERM_PENDING if pending else None), None
    duration = max(1, cue.end_ms - cue.start_ms)
    for offset in offsets:
        shifted = [(a + offset, b + offset, text, ref) for a, b, text, ref in records]
        words, reason = align_text_to_tokens(cue.text, shifted, (cue.start_ms, cue.end_ms), derived=derived, allow_realign=allow_realign)
        if not words:
            continue
        span = (words[0].start_ms, max(w.end_ms for w in words))
        shared = min(span[1], cue.end_ms) - max(span[0], cue.start_ms)
        if shared * 2 >= min(duration, max(1, span[1] - span[0])):
            return words, reason, offset
    return (), None, None


def _independent_words(project, cue, *, allow_realign=True):
    from ..timeline.studio_caption_timeline import KEY
    pending = None
    override = project.studio_state.get('term_word_overrides', {}).get(cue.id, {})
    if override.get('text') == cue.text:
        if override.get('alignment_provenance') in EXACT_OVERRIDES:
            # case_only / deletion_only keep each character on its measured interval.
            positions = content_positions(cue.text)
            target = ''.join(c for _, c in positions)
            words = override.get('words', ())
            if ''.join(normalized_content(w['text']) for w in words) == target:
                result, offset = [], 0
                for word in words:
                    text = normalized_content(word['text'])
                    if not text:
                        continue
                    result.append(AlignedWord(word['text'], positions[offset][0],
                        positions[offset+len(text)-1][0]+1, word['start_ms'], word['end_ms'], 'term:'+cue.id))
                    offset += len(text)
                return tuple(result), 'exact_token_text'
        # A spelling remap's own word list is derived. The caption's measured
        # words below may still prove the replaced span as one unit.
        pending = TERM_PENDING
    receipt = project.studio_state[KEY].get('instances', {}).get(cue.id, {})
    if not isinstance(receipt, Mapping):
        return (), 'word_structure_invalid'
    if not allow_realign and receipt.get('text', cue.text) != cue.text:
        return (), 'stale_word_alignment'
    from .word_timing_provenance import estimated_word_timing
    from .cue_forced_alignment import is_cue_alignment_row
    if (not receipt.get('acoustic_word_observation')
            and not any(is_cue_alignment_row(project.asr_evidence.get(ref)) for ref in cue.evidence_refs)
            and any(
            estimated_word_timing(project.asr_evidence.get(ref, {}))
            and not (project.asr_evidence.get(ref, {}).get('caption_arbitration') or {}).get('acoustic_words')
            for ref in cue.evidence_refs)):
        return (), 'legacy_uniform_display_estimate_not_acoustic'
    stored = receipt.get('words') if receipt.get('word_alignment', 'exact_token_text') in MEASURED_ALIGNMENTS else ()
    if pending is None and receipt.get('text') == cue.text and stored:
        from ..projects.subtitle_consistency import word_receipt_problem
        problem = word_receipt_problem(receipt, cue.text)
        if problem:
            return (), problem[0]
        # 'realign:<id>' words are the Studio re-alignment's own measurement, kept in this
        # receipt (2026-10-22: they were rejected here, so a re-aligned caption lost its words).
        if any(row['evidence_ref'] and row['evidence_ref'] not in project.asr_evidence
               and not row['evidence_ref'].startswith(('term:', 'realign:')) for row in stored):
            return (), 'word_source_missing'
        return tuple(AlignedWord(**{k: row[k] for k in AlignedWord.__dataclass_fields__})
                     for row in stored), receipt.get('word_alignment', 'exact_token_text')
    if not allow_realign:
        return (), pending or ('stale_word_alignment' if receipt.get('text') != cue.text
                               else receipt.get('word_alignment', 'missing_word_timestamps'))
    if stored:
        # Edited text: realign it to this caption's own measured words, which
        # already live on the project clock.
        words, reason = align_text_to_tokens(
            cue.text, _receipt_tokens(stored), (cue.start_ms, cue.end_ms),
            derived=receipt.get('word_alignment') == 'derived_term_source_span')
        if words:
            return words, reason
        if reason == 'alignment_complexity_limit':
            return (), reason
    if 'evidence_clock_offset_ms' in receipt:
        words, reason, _offset = recover_words_from_evidence(
            project, cue, receipt, [int(receipt['evidence_clock_offset_ms'])])
        if words:
            return words, reason
    if stored:
        return (), pending or 'text_changed_or_inside_multi_character_token'
    return (), pending or receipt.get('word_alignment', 'independent_caption_requires_acoustic_alignment')


def cue_words(project, cue, *, allow_realign=True):
    appearance = getattr(cue, 'appearance_override', {})
    if not isinstance(appearance, Mapping):
        from ..projects.studio_revisions import thaw_json
        appearance = thaw_json(appearance) or {}
    if appearance.get('_translation_display'):
        return (), 'translation_has_no_measured_word_alignment'
    if project is None:
        return (), 'missing_project_evidence'
    from ..timeline.studio_caption_timeline import independent_captions, KEY
    if independent_captions(project) and KEY in project.studio_state:
        return _independent_words(project, cue, allow_realign=allow_realign)
    from ..timeline.studio_edit_sequence import source_cue_id_of, projected_cues
    canonical_id = source_cue_id_of(cue.id)
    canonical = next((c for c in project.cues if c.id == canonical_id), cue)
    refs = canonical.evidence_refs or list(project.asr_evidence)
    override = project.studio_state.get('term_word_overrides', {}).get(canonical_id, {})
    rows = None
    pending = False
    if override.get('text') == canonical.text:
        if override.get('alignment_provenance') in EXACT_OVERRIDES:
            rows = [('term:' + canonical_id, override)]
        else:
            # The override's own words are a remap; realign the evidence.
            pending = True
    records, term_pending, derived = evidence_tokens(project, refs, rows)
    pending = pending or term_pending
    if not records:
        return (), TERM_PENDING if pending else 'missing_word_timestamps'
    words, reason = align_text_to_tokens(cue.text, records, (canonical.start_ms, canonical.end_ms),
                                         derived=derived, allow_realign=allow_realign)
    if not words:
        return (), TERM_PENDING if pending and reason == 'text_changed_or_inside_multi_character_token' else reason
    if cue.id == canonical.id:
        return words, reason
    result = []
    for word in words:
        token_cue = copy.deepcopy(canonical)
        token_cue.start_ms, token_cue.end_ms = word.start_ms, word.end_ms
        view = copy.copy(project); view.cues = [token_cue]
        mapped = [c for c in projected_cues(view, min_visible_ms=1) if c.id == cue.id]
        if len(mapped) != 1:
            return (), 'token_outside_current_clip'
        result.append(AlignedWord(word.text, word.char_start, word.char_end,
                                  mapped[0].start_ms, mapped[0].end_ms, word.evidence_ref))
    return tuple(result), reason


def boundary_words(words, character_index):
    left = [w for w in words if w.char_end <= character_index]
    right = [w for w in words if w.char_start >= character_index]
    if not left or not right or any(w.char_start < character_index < w.char_end for w in words):
        return None
    return left[-1], right[0]
