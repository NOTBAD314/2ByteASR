"""Immutable refinement ranges, measured timing and exact local reconstruction."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
import unicodedata
from dataclasses import asdict, dataclass

from .sentence_refine_contract import PROTOCOL_VERSION, RefineError, boundary_candidates


@dataclass
class RefineRange:
    cue: object
    originals: list
    candidates: dict
    owner_id: str = ''
    char_start: int = 0


def input_version(cues, project=None, configuration=None):
    receipts = ((project.studio_state.get("caption_timeline") or {}).get("instances", {})
                if project else {})
    value = [PROTOCOL_VERSION, [asdict(cue) for cue in cues],
             [receipts.get(cue.id) for cue in cues],
             [[project.asr_evidence.get(ref) for ref in cue.evidence_refs] for cue in cues] if project else [],
             (project.generation_metadata.get('language'), project.media.path) if project else None,
             (project.studio_state.get('locked_speakers', ()),
              (project.studio_state.get('ai_sentence_refine') or {}).get('protected_after_cue_ids', ())) if project else None,
             configuration]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _association(project, cue):
    receipts = (project.studio_state.get("caption_timeline") or {}).get("instances", {})
    receipt = receipts.get(cue.id, {})
    # Distinct track/source/translation ownership is a real range boundary.
    return (receipt.get("source_path", project.media.path), receipt.get("track_id"),
            receipt.get("source_clip_id"), tuple(receipt.get("translation_parent_ids", ())))


def refine_glossary_snapshot(project):
    from ..glossary.terminology import GlossarySnapshot, snapshot_glossaries
    if project is None or not project.glossary_ids:
        return GlossarySnapshot()
    import subtitle_core as legacy
    return snapshot_glossaries(legacy, project.glossary_ids)


def _edge_uses_word_separator(text, *, reverse=False):
    for char in reversed(text) if reverse else text:
        if char.isalnum():
            name = unicodedata.name(char, '')
            return not any(script in name for script in ('CJK', 'HIRAGANA', 'KATAKANA', 'IDEOGRAPHIC', 'BOPOMOFO'))
    return False


def make_ranges(cues, project, language, *, combine=False):
    from .segmentation_profiles import profile_for
    profile = profile_for(language or 'zh')
    combine = combine and profile.strategy != 'conservative'
    positions = {cue.id: index for index, cue in enumerate(project.cues)} if project else {}
    receipts = ((project.studio_state.get('caption_timeline') or {}).get('instances', {})
                if project else {})
    protected = set((project.studio_state.get('ai_sentence_refine') or {}).get('protected_after_cue_ids', ())) if project else set()
    locked_speakers = set(project.studio_state.get('locked_speakers', ())) if project else set()
    layers = []
    if project and combine:
        from ..playback.audio_graph import capture_audio_graph
        layers = capture_audio_graph(project)['segments']

    def ownership(cue):
        return tuple((row.get('audio_track_id'), row.get('clip_id'), row.get('source_path'), row.get('stream_index'))
                     for row in layers if row['timeline_in_ms'] < cue.end_ms and row['timeline_out_ms'] > cue.start_ms)
    groups = []
    for cue in cues:
        previous = groups[-1][-1] if groups else None
        compatible = bool(combine and project and previous
            and positions.get(cue.id, -2) == positions.get(previous.id, -4) + 1
            and 0 <= cue.start_ms - previous.end_ms < 400
            and cue.speaker_id == previous.speaker_id
            and cue.speaker_id not in locked_speakers
            and previous.id not in protected
            and not receipts.get(previous.id, {}).get('protected_end')
            and not receipts.get(cue.id, {}).get('protected_start')
            and not receipts.get(previous.id, {}).get('locked')
            and not receipts.get(cue.id, {}).get('locked')
            and (previous.text[-1:].isspace() or cue.text[:1].isspace()
                 or profile.strategy == 'cjk' and not (
                     _edge_uses_word_separator(previous.text, reverse=True) and _edge_uses_word_separator(cue.text)))
            and _association(project, cue) == _association(project, previous)
            and ownership(cue) == ownership(previous)
            and all(getattr(cue, key) == getattr(previous, key) for key in
                    ("style_id", "base_preset_id", "effect_id", "appearance_override", "transform", "raw_ass_override"))
            and sum(len(item.text) for item in groups[-1]) + len(cue.text) <= 1000
            and cue.end_ms - groups[-1][0].start_ms <= 30_000)
        if compatible:
            groups[-1].append(cue)
        else:
            groups.append([cue])
    terms = []
    for library in refine_glossary_snapshot(project).libraries:
        for term in library.terms:
            terms.extend((term.canonical, *term.aliases))
    result = []
    for originals in groups:
        cue = copy.deepcopy(originals[0])
        if len(originals) > 1:
            cue.id = "range-" + input_version(originals, project)[:20]
            cue.text = "".join(item.text for item in originals)
            cue.end_ms = originals[-1].end_ms
            cue.evidence_refs = list(dict.fromkeys(ref for item in originals for ref in item.evidence_refs))
        result.append(RefineRange(cue, originals, boundary_candidates(cue.text, language, terms)))
    return result


def repair_chinese_range(unit, action, project, *, fallback=False):
    """Run the recognition quality engine on an immutable Studio range.

    Real word evidence is copied in project seconds. Missing words permit
    removal of automatic edges, never invent a new timed split.
    """
    from ..recognition.transcript_data import SpeechSegment, WordUnit
    from ..recognition.cue_word_alignment import cue_words
    from .grouping_quality import quality_for_segments
    from .text_rules import display_length
    from .sentence_refine import CueRefineAction
    rows = []
    for index, cue in enumerate(unit.originals):
        words, _ = cue_words(project, cue)
        measured = [WordUnit(w.start_ms/1000, w.end_ms/1000, w.text, 1.) for w in words]
        rows.append(SpeechSegment(index+1, cue.start_ms/1000, cue.end_ms/1000,
                                  cue.text, 1., measured, speaker=cue.speaker_id))
        rows[-1].caption_arbitration['word_timing'] = {'basis': 'aligner_words',
            'measured_words': [dict(text=w.text, start_ms=w.start_ms, end_ms=w.end_ms) for w in words]}
    quality = quality_for_segments(rows)
    if action.action == 'keep':
        boundaries, cursor = [], 0
        for cue in unit.originals:
            cursor += display_length(cue.text)
            boundaries.append(cursor)
    else:
        boundaries = [display_length(unit.cue.text[:index+1]) for index in action.split_after_chars]
        boundaries.append(quality.total)
    from .ai_boundary_policy import inspect, minimal_fallback
    if fallback:
        final, _receipts = minimal_fallback(quality,boundaries)
    else:
        final = boundaries
    issues = inspect(quality,final)
    if issues:
        from .ai_boundary_policy import windows
        error=RefineError('当前范围仍有明确拆词或字数超限，需要定向修正', 'constraint_conflict')
        error.candidate_boundaries=list(boundaries)
        error.editable_windows=windows(quality,boundaries)
        raise error
    if final == boundaries and action.action == 'keep':
        return action, []
    offsets = [quality.index.raw_edges[edge]-1 for edge in final[:-1]]
    repaired = CueRefineAction(unit.cue.id, 'split', split_after_chars=offsets)
    # This check also refuses newly inferred cuts with no word/source timing.
    build_range_replacement(unit, repaired, project, set())
    return repaired, [dict(reason='local_minimal_fallback' if fallback else 'ai_accepted', before=boundaries, after=final)]


def validate_quality(unit, action, language, *, hard_limit=None):
    if action.action == "keep":
        pieces = [cue.text for cue in unit.originals] if not unit.owner_id else [unit.cue.text]
        cursor = 0
        for piece in pieces[:-1]:
            cursor += len(piece)
            if (not (hard_limit and language.split('-')[0]=='zh') and cursor-1 not in unit.candidates.values()
                    and not (unit.cue.text[cursor-1:cursor].isspace() or unit.cue.text[cursor:cursor+1].isspace())):
                raise RefineError('原字幕边界位于完整词语内部，需要重新选择边界', 'semantic_boundary')
    else:
        offsets = action.split_after_chars if action.action == "split" else action.space_after_chars
        if any(index not in unit.candidates.values() for index in offsets):
            raise RefineError("建议断点位于词语、专名、数字单位或 Unicode 字形内部", "semantic_boundary")
        bounds = [0, *(index + 1 for index in offsets), len(unit.cue.text)]
        pieces = [unit.cue.text[a:b] for a, b in zip(bounds, bounds[1:])]
    if hard_limit:
        _preferred, _hard, length = refinement_limits(language)
        if any(length(piece) > hard_limit for piece in pieces):
            raise RefineError(f"结果超过单条字幕硬限制 {hard_limit}，需要重新选择完整词语之间的断点", "constraint_conflict")
    return pieces


def refinement_limits(language):
    from .segmentation_profiles import profile_for, measure
    tag = language or 'zh'
    profile = profile_for(tag)
    return profile.preferred, profile.hard_max, lambda text: measure(text, tag)


def request_windows(ranges, language, *, max_chars=1200):
    """Disjoint core windows at legal word edges, with read-only neighboring text."""
    result = []
    for unit in ranges:
        text = unit.cue.text
        if len(text) <= max_chars:
            result.append(unit)
            continue
        cuts = [0]
        while len(text) - cuts[-1] > max_chars:
            legal = [index+1 for index in unit.candidates.values()
                     if cuts[-1] + max_chars//2 <= index+1 <= cuts[-1]+max_chars]
            if not legal:
                # The unbreakable input remains owned and will report its
                # length conflict. No raw N-character cut is manufactured.
                cuts = [0]
                break
            edge = max(legal, key=lambda offset: (text[offset-1] in '。！？.!?，,;；',
                                                   text[offset-1].isspace(), offset))
            cuts.append(edge)
        cuts.append(len(text))
        if len(cuts) == 2:
            result.append(unit)
            continue
        for left, right in zip(cuts, cuts[1:]):
            cue = copy.deepcopy(unit.cue)
            cue.id = f'{unit.cue.id}-w{left}'
            cue.text = text[left:right]
            candidates = {key: index-left for key, index in unit.candidates.items()
                          if left <= index < right-1}
            result.append(RefineRange(cue, unit.originals, candidates, unit.cue.id, left))
    return result


def build_range_replacement(unit, action, project, used_ids):
    """Retain every source character, using measured words or existing cue edges."""
    from ..recognition.cue_word_alignment import cue_words, boundary_words
    if action.action == "keep":
        # keep means keep the input boundaries, including a multi-cue range.
        return []
    if action.action != "split":
        from .sentence_refine import build_replacement_cues
        return build_replacement_cues(unit.cue, action, project=project, used_ids=used_ids)
    text = unit.cue.text
    bounds = [0, *(index + 1 for index in action.split_after_chars), len(text)]
    source_edges = []
    cursor = 0
    for cue in unit.originals:
        source_edges.append((cursor, cursor + len(cue.text), cue))
        cursor += len(cue.text)
    timings = {}
    for left, right, cue in source_edges:
        timings[left] = (timings.get(left, (None, None))[0], cue.start_ms)
        timings[right] = (cue.end_ms, None)
        words, _ = cue_words(project, cue)
        for offset in bounds[1:-1]:
            if left < offset < right:
                pair = boundary_words(words, offset - left)
                if pair is not None:
                    first, second = pair
                    timings[offset] = (min(first.end_ms, second.start_ms), second.start_ms)
    result = []
    for left, right in zip(bounds, bounds[1:]):
        start = timings.get(left, (None, None))[1]
        end = timings.get(right, (None, None))[0]
        if start is None or end is None or end - start < 50:
            raise RefineError("新断点缺少可匹配的字词时间或原字幕边界，保留原字幕", "time_mapping_error")
        owners = [cue for a, b, cue in source_edges if a < right and b > left]
        clone = copy.deepcopy(owners[0])
        parent = owners[0].id if len(owners) == 1 else unit.originals[0].id
        marker = 'split' if len(owners) == 1 else 'merge'
        clone.id = f"{parent}-{marker}-{uuid.uuid4().hex[:8]}"
        while clone.id in used_ids:
            clone.id = f"{parent}-{marker}-{uuid.uuid4().hex[:8]}"
        used_ids.add(clone.id)
        clone.text = text[left:right]
        if all(cue.original_text in ('', cue.text) for cue in owners):
            clone.original_text = clone.text
        elif len(owners) > 1:
            clone.original_text = ''.join(cue.original_text or cue.text for cue in owners)
        clone.start_ms, clone.end_ms = start, end
        clone.evidence_refs = list(dict.fromkeys(ref for cue in owners for ref in cue.evidence_refs))
        clone.validate()
        result.append(clone)
    if "".join(cue.text for cue in result) != text:
        raise RefineError("写回前逐字符校验失败", "text_fidelity_error")
    return result
