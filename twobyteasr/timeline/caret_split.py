"""Exact-text cuts for the caption editor, using the existing cue splice contract."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from ..caption_style.text_marks import boundaries
from .studio_timing import SPLIT_MIN_CUE_DURATION_MS


@dataclass(frozen=True)
class CaretCut:
    position: int
    split_ms: int
    measured: bool
    reason: str


def plan_caret_cut(project, cue, text, position, *, playhead_ms=None):
    """Keep the exact insertion boundary. Never reuse offsets from changed text."""
    if position not in boundaries(text):
        raise ValueError('请把光标移到完整字符之间')
    if not text[:position].strip() or not text[position:].strip():
        raise ValueError('光标两侧都需要有文字')
    minimum = SPLIT_MIN_CUE_DURATION_MS
    low, high = cue.start_ms + minimum, cue.end_ms - minimum
    if low > high:
        raise ValueError('字幕太短，无法切出两段有效时长')
    if playhead_ms is not None:
        if not low <= playhead_ms <= high:
            raise ValueError(f'播放头须在字幕内部，且两侧至少保留 {minimum} 毫秒')
        return CaretCut(position, int(playhead_ms), False, '播放头校准')
    from ..recognition.cue_word_alignment import cue_words, boundary_words
    from .text_split import _cut_time
    words, reason = cue_words(project, cue, allow_realign=False) if text == cue.text else ((), 'text_changed')
    pair = boundary_words(words, position)
    cut = _cut_time(words, position) if pair is not None else None
    if cut is not None and low <= cut <= high and pair[0].end_ms <= pair[1].start_ms:
        return CaretCut(position, cut, True, reason)
    # The existing content-character estimate ignores punctuation/whitespace.
    # Count whole graphemes so emoji and combining marks remain indivisible.
    edges = boundaries(text)
    weights = [int(bool(text[a:b].strip())) for a, b in zip(edges, edges[1:])]
    before = sum(weight for a, weight in zip(edges, weights) if a < position)
    share = before / max(1, sum(weights))
    cut = round(cue.start_ms + (cue.end_ms - cue.start_ms) * share)
    return CaretCut(position, max(low, min(high, cut)), False, 'text_changed' if text != cue.text else reason)


def caret_split_command(project, cue, text, cut):
    """Derive marks/word receipts on a narrow shadow, then splice the live cue."""
    from .studio_commands import split_cue_command, SpliceCuesCommand
    from .studio_caption_timeline import KEY
    from ..subtitle_rules import subtitle_translation as translation
    shadow = copy.copy(project)
    edited = copy.deepcopy(cue)
    if text != cue.text:
        from ..caption_style.text_marks import remap_marks, layer_marks, with_marks
        edited.appearance_override = with_marks(edited, remap_marks(cue.text, text, layer_marks(cue)))
        edited.text = text
    shadow.cues = [edited]
    shadow.generation_metadata = dict(project.generation_metadata)
    for key in (translation.RECORDS_KEY, translation.RENDER_KEY):
        shadow.generation_metadata.pop(key, None)
    shadow.__dict__.pop('_studio_state_runtime', None)
    shadow.studio_state = dict(project.studio_state)
    if KEY in shadow.studio_state:
        shadow.studio_state[KEY] = dict(shadow.studio_state[KEY], instances={
            cue.id: copy.deepcopy(shadow.studio_state[KEY].get('instances', {}).get(cue.id, {}))})
    # TranslationSplice handles only these records. Keep its established metadata
    # template/migration support and replace its estimated text assignment below.
    source = split_cue_command(shadow, cue.id, cut.split_ms, text[:cut.position], text[cut.position:])
    index = next(i for i, item in enumerate(project.cues) if item.id == cue.id)
    command = SpliceCuesCommand(project, index, 1, source._after_cues, '按文字光标切割字幕',
                               selection_after=source._after_cues[-1].id)
    command._caption_after = source._caption_after
    records = command._translations
    old = records.before.get(cue.id)
    if old and str(old.get('text') or '').strip():
        group = copy.deepcopy(cue.appearance_override.get('translation_group') or {
            'id': cue.id, 'original_source': cue.text, 'original_translation': old['text']})
        displayed = str(group.pop('text', '') or old['text'])
        group['review'] = 'split_needs_translation_alignment'
        for number, part in enumerate(command._after_cues):
            value = displayed if number == 0 else ''
            record = copy.deepcopy(old)
            record.update(text=value, source_text=part.text, source_sha=translation.source_sha(part.text),
                          status=translation.NEEDS_UPDATE, split_estimate=True, group_id=group['id'],
                          split_from={'cue_id': group['id'], 'source_text': group['original_source'],
                                      'translation': group['original_translation']})
            records.after[part.id] = record
            records.after_view[part.id] = value
            part.appearance_override['translation_group'] = copy.deepcopy(group)
            # Full translation remains on its owner. A new empty member has no marks.
            part.appearance_override.setdefault('translation', {})['text_marks'] = (
                copy.deepcopy(cue.appearance_override.get('translation', {}).get('text_marks', [])) if number == 0 else [])
    return command
