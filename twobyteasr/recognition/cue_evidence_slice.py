"""Project transcript evidence onto a cue's real word interval.

This is text alignment, not a newly measured acoustic timestamp. Original
segment evidence stays intact; neighboring partial segments cannot vote.
"""
from .caption_arbitration import align, content, usable_transcript


def slice_evidence(row, cue, field):
    value = str(row.get(field) or '')
    if not usable_transcript(value):
        return ''
    start, end = cue.start_ms, cue.end_ms
    a, b = int(row.get('start_ms', 0)), int(row.get('end_ms', 0))
    overlap = max(0, min(end, b)-max(start, a))
    if overlap < .3 * max(1, end-start):
        return ''
    words = row.get('words') or []
    if not words:
        return value if start <= a and b <= end else ''
    base, selected = '', []
    for word in words:
        text = content(word.get('text', ''))
        left = len(base); base += text
        midpoint = (float(word.get('start_ms', a))+float(word.get('end_ms', b)))/2
        if start <= midpoint < end:
            selected.append((left, len(base)))
    if not selected or not base or max(len(base), len(content(value))) > 512:
        return ''
    low, high = selected[0][0], selected[-1][1]
    # A player ID is one token even when the stored word timeline is per-letter.
    entity_char = lambda c: c.isascii() and (c.isalnum() or c == '_')
    while low > 0 and low < len(base) and entity_char(base[low-1]) and entity_char(base[low]):
        low -= 1
    while high < len(base) and high > 0 and entity_char(base[high-1]) and entity_char(base[high]):
        high += 1
    reference = content(value)
    # Case-fold only for alignment. Emit the original reference's characters.
    operations = align(base.casefold(), reference.casefold())
    cursor, pieces = 0, []
    for left, right, old, new in operations:
        text = reference[cursor:cursor+len(new)]
        cursor += len(new)
        if new and ((old and left < high and right > low) or (not old and low < left < high)):
            pieces.append(text)
    return ''.join(pieces)


def cue_evidence(project, cue, field):
    from .asr_source_evidence import cue_source_hypotheses
    wanted = {'moss_text': 'primary', 'firered_text': 'firered',
              'qwen_asr_text': 'qwen', 'qwen_text': 'qwen'}.get(field)
    if wanted:
        return ''.join(row['text'] for row in cue_source_hypotheses(project, cue)
                       if row['source'] == wanted)
    # Derived context is retained for callers that explicitly ask for it, but
    # it never becomes an independent acoustic source.
    return ''.join(dict.fromkeys(slice_evidence(project.asr_evidence.get(ref, {}), cue, field)
                                 for ref in cue.evidence_refs))
