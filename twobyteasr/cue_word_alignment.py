"""Read-only, text-exact token evidence in the cue's actual time domain.

Multi-character tokens remain indivisible. Punctuation and whitespace have no
invented acoustic duration. Unmatched edits return a reason, never a guessed
character alignment. Persisted evidence remains immutable across undo/splits.
"""
from dataclasses import dataclass
import copy
import unicodedata


def content_positions(text):
    return [(i, normalized) for i, char in enumerate(text)
            if not char.isspace() and not unicodedata.category(char).startswith(('P', 'Z'))
            for normalized in char.casefold()]


@dataclass(frozen=True)
class AlignedWord:
    text: str
    char_start: int
    char_end: int
    start_ms: int
    end_ms: int
    evidence_ref: str


def cue_words(project, cue):
    if project is None:
        return (), 'missing_project_evidence'
    from .studio_edit_sequence import source_cue_id_of, projected_cues
    canonical_id = source_cue_id_of(cue.id)
    canonical = next((c for c in project.cues if c.id == canonical_id), cue)
    records = []
    refs = canonical.evidence_refs or list(project.asr_evidence)
    for ref in refs:
        row = project.asr_evidence.get(ref, {})
        owner = str(row.get('final_timing_owner', '')).casefold()
        if any(word in owner for word in ('estimated', 'proportional', 'degraded', '估算', '均分')):
            continue
        for token in row.get('words', ()):
            text = str(token.get('text', token.get('word', '')))
            normalized = ''.join(c for _, c in content_positions(text))
            try:
                start = round(float(token['start_ms'])) if 'start_ms' in token else round(float(token['start'])*1000)
                end = round(float(token['end_ms'])) if 'end_ms' in token else round(float(token['end'])*1000)
            except (KeyError, TypeError, ValueError):
                continue
            if normalized and end > start:
                records.append((start, end, normalized, str(ref)))
    records = sorted({(a,b,text):(a,b,text,ref) for a,b,text,ref in records}.values())
    # Overlapping transcripts from alternate models are not one token stream.
    if any(b[0] < a[1] for a, b in zip(records, records[1:])):
        return (), 'overlapping_token_streams'
    positions = content_positions(cue.text)
    target = ''.join(c for _, c in positions)
    source = ''.join(r[2] for r in records)
    if not target or not source:
        return (), 'missing_word_timestamps'
    offsets = []; cursor = 0
    for start, end, text, ref in records:
        offsets.append((cursor, cursor+len(text), start, end, text, ref)); cursor += len(text)
    candidates = []
    at = source.find(target)
    while at >= 0:
        selected = [r for r in offsets if at <= r[0] and r[1] <= at+len(target)]
        if selected and selected[0][0] == at and selected[-1][1] == at+len(target):
            if selected[-1][3] > canonical.start_ms and selected[0][2] < canonical.end_ms:
                distance = abs(selected[0][2]-canonical.start_ms)+abs(selected[-1][3]-canonical.end_ms)
                candidates.append((distance, at, selected))
        at = source.find(target, at+1)
    if not candidates:
        return (), 'text_changed_or_inside_multi_character_token'
    candidates.sort(key=lambda r: r[0])
    if len(candidates)>1 and candidates[0][0] == candidates[1][0]:
        return (), 'ambiguous_repeated_text'
    _, at, selected = candidates[0]
    result = []
    for lo, hi, start, end, text, ref in selected:
        if cue.id != canonical.id:
            token_cue = copy.deepcopy(canonical)
            token_cue.start_ms, token_cue.end_ms = start, end
            view = copy.copy(project); view.cues = [token_cue]
            mapped = [c for c in projected_cues(view, min_visible_ms=1) if c.id == cue.id]
            if len(mapped) != 1:
                return (), 'token_outside_current_clip'
            start, end = mapped[0].start_ms, mapped[0].end_ms
        result.append(AlignedWord(text, positions[lo-at][0], positions[hi-at-1][0]+1,
                                  start, end, ref))
    return tuple(result), 'exact_token_text'


def boundary_words(words, character_index):
    left = [w for w in words if w.char_end <= character_index]
    right = [w for w in words if w.char_start >= character_index]
    if not left or not right or any(w.char_start < character_index < w.char_end for w in words):
        return None
    return left[-1], right[0]
