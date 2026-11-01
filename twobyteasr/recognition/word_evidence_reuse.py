"""Conservative reuse of first-pass English forced-alignment evidence.

Only complete measured units that can be mapped back to the same words,
speaker and audio are reused. Ambiguous or incomplete cues are left for a
local alignment job. This module never changes caption text or display times.
"""
from __future__ import annotations

import copy
import bisect
import difflib
import hashlib
import re
from itertools import accumulate
from collections import Counter

from ..forced_alignment import ALIGNER_CODE, ALIGNER_REPO, ALIGNER_REVISION, UNIT_POLICY_VERSION, content_char_map

TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*")
POLICY = 'source-word-evidence-v1'
# Match the existing grouping source-time tolerance; never enlarge display
# intervals to make a reused word appear inside them.
MAX_CUE_PAD_MS = 50


def audio_sha256(audio):
    """Same bytes the Qwen worker receives, without copying a long audio array."""
    from .alignment_audio import pcm_digest
    try:
        return pcm_digest(audio)
    except ValueError:
        return ''


def _chars(text, start=0, end=None):
    end = len(text) if end is None else end
    return [(char.casefold(), start + a, start + b) for char, a, b in content_char_map(text[start:end])]


def _speaker(job_id):
    value = str(job_id or '')
    return value.rsplit('@', 1)[0] if '@' in value else ''


def _tokens(text):
    return [(match.group().casefold().replace('’', "'"), match.start(), match.end())
            for match in TOKEN.finditer(str(text or ''))]


def _remap_units(units, source_chars, mapping):
    """Map whole units only; a unit crossing a cue boundary is not reused."""
    out, covered = [], set()
    starts = [item[1] for item in source_chars]
    for unit in units or ():
        try:
            begin, end = int(unit['char_start']), int(unit['char_end'])
        except (KeyError, TypeError, ValueError):
            return None, set()
        if begin < 0 or end <= begin:
            return None, set()
        first = bisect.bisect_left(starts, begin)
        last = bisect.bisect_left(starts, end)
        indices = [i for i in range(first, last) if source_chars[i][2] <= end]
        mapped = [i for i in indices if i in mapping]
        if not mapped:
            continue
        if len(mapped) != len(indices) or any(i in covered for i in mapped):
            return None, set()
        targets = [mapping[i] for i in mapped]
        item = dict(unit, char_start=min(x[0] for x in targets), char_end=max(x[1] for x in targets))
        out.append(item)
        covered.update(mapped)
    return out, covered


def plan_reuse(cues, payload, *, language, audio_digest, cancel_check=None,
               audio=None,audio_clock_identity=None,valid_samples=None):
    """Return cue-index -> alignment plus explicit reasons for non-reuse.

    A changed token only invalidates matching cues; matching blocks are
    monotonic and each cue must map to consecutive words from one source job.
    """
    cues = list(cues)
    reasons = Counter()
    per_window=(isinstance(payload,dict) and audio is not None and bool(audio_clock_identity)
                and payload.get('audio_clock_identity')==audio_clock_identity)
    if (str(language).casefold() not in {'english', 'japanese'} or not isinstance(payload, dict)
            or payload.get('protocol') != 'qwen-aligner-units-v1'
            or payload.get('model') != ALIGNER_REPO or payload.get('model_revision') != ALIGNER_REVISION
            or payload.get('code') != ALIGNER_CODE or payload.get('unit_policy') != UNIT_POLICY_VERSION
            or not (per_window or bool(audio_digest) and payload.get('audio_sha256') == audio_digest)):
        return {}, {'evidence_unavailable': len(cues)}
    policy = payload.get('policy') or {}
    if (not isinstance(policy, dict) or policy.get('version') != 'qwen-aligner-units-v1'
            or policy.get('sample_rate') != 16000
            or policy.get('audio_format') != 'float32-mono-npy-v1'):
        return {}, {'invalid_receipt': len(cues)}
    rows = payload.get('results')
    if (not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get('id') for row in rows)
            or len({str(row['id']) for row in rows}) != len(rows)):
        return {}, {'invalid_receipt': len(cues)}
    verified={}
    def audio_matches(row):
        if not per_window:return True
        key=str(row['id'])
        if key not in verified:
            from .alignment_audio import pcm_digest
            start=max(0,int(row['window_start_ms'])*16)
            end=min(len(audio) if valid_samples is None else valid_samples,int(row['window_end_ms'])*16)
            expected=(payload.get('window_hashes') or {}).get(key)
            verified[key]=bool(expected) and pcm_digest(audio[start:end],check=cancel_check)==expected
        return verified[key]
    if str(language).casefold() == 'japanese':
        return _plan_japanese_reuse(cues,payload,audio_digest or audio_clock_identity,cancel_check,audio_matches)
    source, target = [], []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('text'), str):
            return {}, {'invalid_receipt': len(cues)}
        for token, start, end in _tokens(row['text']):
            source.append((token, row_index, start, end))
    for cue_index, cue in enumerate(cues):
        for token, start, end in _tokens(str(getattr(cue, 'text', '') or '')):
            target.append((token, cue_index, start, end))
    source_words, target_words = [x[0] for x in source], [x[0] for x in target]
    if source_words == target_words:
        matches = {i: i for i in range(len(target))}
    else:
        matches = {}
        matcher = difflib.SequenceMatcher(a=source_words, b=target_words, autojunk=True)
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                matches[block.b + offset] = block.a + offset
    target_by_cue = {}
    for index, item in enumerate(target):
        target_by_cue.setdefault(item[1], []).append(index)
    meta = {key: payload.get(key) for key in ('model', 'model_revision', 'code', 'unit_policy', 'dtype', 'torch_version')}
    reusable = {}
    for cue_index, cue in enumerate(cues):
        if cancel_check is not None:
            cancel_check()
        indices = target_by_cue.get(cue_index, [])
        src_indices = [matches.get(index) for index in indices]
        if not indices or any(index is None for index in src_indices):
            reasons['text_changed_or_unmapped'] += 1
            continue
        if any(right != left + 1 for left, right in zip(src_indices, src_indices[1:])):
            reasons['noncontiguous_source'] += 1
            continue
        row_ids = {source[index][1] for index in src_indices}
        if len(row_ids) != 1:
            reasons['cross_source_job'] += 1
            continue
        row = rows[next(iter(row_ids))]
        if not audio_matches(row):
            reasons['audio_window_mismatch']+=1
            continue
        if (row.get('status') != 'aligned' or str(row.get('language', '')).casefold() != 'english'
                or _speaker(row.get('id')) != str(getattr(cue, 'speaker', '') or 'S00')):
            reasons['speaker_or_status'] += 1
            continue
        source_chars = _chars(row['text'])
        source_lookup = {(a, b): index for index, (_, a, b) in enumerate(source_chars)}
        if len(source_lookup) != len(source_chars):
            reasons['ambiguous_normalization'] += 1
            continue
        mapping = {}
        for target_index, src_index in zip(indices, src_indices):
            _, _, ss, se = source[src_index]
            _, _, ts, te = target[target_index]
            src_chars, dst_chars = _chars(row['text'], ss, se), _chars(cue.text, ts, te)
            if [x[0] for x in src_chars] != [x[0] for x in dst_chars]:
                mapping = {}
                break
            for (_, sa, sb), (_, ta, tb) in zip(src_chars, dst_chars):
                index = source_lookup.get((sa, sb))
                if index is None or index in mapping:
                    mapping = {}
                    break
                mapping[index] = (ta, tb)
            if not mapping:
                break
        expected = {(a, b) for _, a, b in _chars(cue.text)}
        if not mapping or len(mapping) != len(expected) or set(mapping.values()) != expected:
            reasons['character_mapping'] += 1
            continue
        pieces, covered = _remap_units(row.get('segments'), source_chars, mapping)
        if pieces is None or covered != set(mapping):
            reasons['incomplete_or_crossing_unit'] += 1
            continue
        pieces.sort(key=lambda item: (item['char_start'], item['char_end']))
        cue_start = round(float(getattr(cue, 'start', 0)) * 1000)
        cue_end = round(float(getattr(cue, 'end', 0)) * 1000)
        try:
            valid = all(item.get('start_basis') == item.get('end_basis') == 'model'
                        and int(row['window_start_ms']) <= int(item['start_ms'])
                        and int(item['end_ms']) <= int(row['window_end_ms'])
                        and cue_start - MAX_CUE_PAD_MS <= int(item['start_ms'])
                        and int(item['start_ms']) < int(item['end_ms']) <= cue_end + MAX_CUE_PAD_MS
                        for item in pieces)
            valid = valid and all(int(left['end_ms']) <= int(right['start_ms'])
                                  for left, right in zip(pieces, pieces[1:]))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            reasons['unmeasured_or_outside_cue'] += 1
            continue
        units, _ = _remap_units(row.get('word_units'), source_chars, mapping)
        if units is None:
            reasons['crossing_word_unit'] += 1
            continue
        from .cue_forced_alignment import UNIT_FIELDS, _compact
        reusable[cue_index + 1] = {
            **meta, 'language': language, 'status': 'aligned', 'mapping': row.get('mapping'),
            'text': cue.text, 'window_start_ms': row.get('window_start_ms'),
            'window_end_ms': row.get('window_end_ms'),
            'run': {'id': str(row.get('id')), 'source': POLICY, 'audio_sha256': payload.get('audio_sha256'),
                    'audio_clock_identity':payload.get('audio_clock_identity'),
                    'source_window_sha256':(payload.get('window_hashes') or {}).get(str(row.get('id')))},
            'segments': copy.deepcopy(pieces), 'stats': {'reused_units': len(pieces), 'reused_words': len(indices)},
            'tokenizer_words': [target[index][0] for index in indices],
            'units_word': _compact(units), 'units_char': [], 'unit_fields': list(UNIT_FIELDS),
        }
    return reusable, dict(reasons)


def _plan_japanese_reuse(cues, payload, audio_digest, cancel_check,audio_matches=lambda row:True):
    """Use exact characters in a unique speaker/time window, never a global diff.

    Repeated kana/short replies elsewhere cannot steal a mapping. A unit that
    crosses a new cue boundary, has repaired times or lacks coverage is sent
    back to the local aligner. Display times and text remain unchanged.
    """
    from .cue_forced_alignment import UNIT_FIELDS, _compact
    rows = payload['results']
    # A time index also handles long/nested overlapping utterances.
    by_speaker = {}
    for row in rows:
        if (row.get('status') == 'aligned' and str(row.get('language', '')).casefold() == 'japanese'
                and isinstance(row.get('text'), str)):
            by_speaker.setdefault(_speaker(row['id']), []).append(row)
    indexes = {}
    for speaker, values in by_speaker.items():
        values.sort(key=lambda row: int(row['window_start_ms']))
        indexes[speaker] = (values, [int(row['window_start_ms']) for row in values],
                            list(accumulate((int(row['window_end_ms']) for row in values), max)))
    reusable, reasons = {}, Counter()
    meta = {key: payload.get(key) for key in ('model', 'model_revision', 'code', 'unit_policy', 'dtype', 'torch_version')}
    for index, cue in enumerate(cues, 1):
        if cancel_check:
            cancel_check()
        text = str(getattr(cue, 'text', '') or '')
        target = _chars(text)
        cue_start, cue_end = round(cue.start * 1000), round(cue.end * 1000)
        values, starts, ends = indexes.get(str(getattr(cue, 'speaker', '') or 'S00'), ([], [], []))
        lo = bisect.bisect_left(ends, cue_start - MAX_CUE_PAD_MS)
        hi = bisect.bisect_right(starts, cue_end + MAX_CUE_PAD_MS)
        found = []
        needle = ''.join(x[0] for x in target)
        if any(len(item[0]) != 1 for item in target):
            reasons['ambiguous_normalization'] += 1
            continue
        for row in values[lo:hi]:
            source_chars = _chars(row['text'])
            if any(len(item[0]) != 1 for item in source_chars):
                continue
            source = ''.join(x[0] for x in source_chars)
            offset = source.find(needle) if needle else -1
            if offset>=0 and not audio_matches(row):continue
            while offset >= 0:
                mapping = {offset + i: (a, b) for i, (_, a, b) in enumerate(target)}
                pieces, covered = _remap_units(row.get('segments'), source_chars, mapping)
                valid = pieces is not None and covered == set(mapping) and bool(pieces)
                if valid:
                    pieces.sort(key=lambda item: item['char_start'])
                    valid = all(item.get('start_basis') == item.get('end_basis') == 'model'
                        and int(row['window_start_ms']) <= int(item['start_ms']) < int(item['end_ms']) <= int(row['window_end_ms'])
                        and cue_start - MAX_CUE_PAD_MS <= int(item['start_ms']) < int(item['end_ms']) <= cue_end + MAX_CUE_PAD_MS
                        for item in pieces)
                    valid = valid and all(a['end_ms'] <= b['start_ms'] for a, b in zip(pieces, pieces[1:]))
                if valid:
                    words, _ = _remap_units(row.get('word_units'), source_chars, mapping)
                    chars, _ = _remap_units(row.get('char_units'), source_chars, mapping)
                    # Raw units crossing a cue are diagnostic only; never
                    # manufacture a boundary in one. Measured pieces above
                    # provide the complete, validated timing coverage.
                    found.append((row, pieces, words or [], chars or []))
                offset = source.find(needle, offset + 1) if needle else -1
        if len(found) != 1:
            reasons['ambiguous_time_text' if found else 'changed_crossing_or_unmeasured'] += 1
            continue
        row, pieces, words, chars = found[0]
        reusable[index] = {
            **meta, 'language': 'Japanese', 'status': 'aligned', 'mapping': row.get('mapping'),
            'text': text, 'window_start_ms': row['window_start_ms'], 'window_end_ms': row['window_end_ms'],
            'run': {'id': str(row['id']), 'source': 'source-japanese-evidence-v1',
                    'audio_sha256':payload.get('audio_sha256'),'audio_clock_identity':payload.get('audio_clock_identity'),
                    'source_window_sha256':(payload.get('window_hashes') or {}).get(str(row['id']))},
            'segments': copy.deepcopy(pieces),
            'stats': {'reused_units': len(pieces), 'reused_words': len(words)},
            'tokenizer_words': [text[p['char_start']:p['char_end']] for p in pieces],
            'units_word': _compact(words), 'units_char': _compact(chars), 'unit_fields': list(UNIT_FIELDS)}
    return reusable, dict(reasons)
