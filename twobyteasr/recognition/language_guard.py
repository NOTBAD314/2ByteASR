"""Conservative source-text checks and an audio-only, bounded repair pass."""
from __future__ import annotations

import copy
import math
import re
import time
from dataclasses import replace

from ..subtitle_rules.language_rules import latin_language, normalize_language, script_counts
from .language_repair_budget import MAX_WINDOW_SECONDS, PRESETS, RepairBudget, plan_windows

VERSION = 'language-guard-v5'
MAX_REQUESTS, MAX_AUDIO_SECONDS, _ = PRESETS['normal']
REPAIR_SETTINGS = ('repair_profile', 'repair_max_requests', 'repair_max_audio_seconds',
                   'repair_max_elapsed_seconds', 'repair_max_cost_cents', 'repair_max_usd')
SCRIPT = {'zh': 'han', 'ja': 'kana', 'ko': 'hangul', 'ru': 'cyrillic',
          **dict.fromkeys(('en', 'de', 'it', 'fr', 'es', 'pt'), 'latin')}
LATIN_WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
NON_SPEECH = re.compile(r'(?i:https?://\S+|www\.\S+)|[\w.+-]+@[\w.-]+|\b[A-Z0-9_-]{2,}\b|[\d_]+')
QUOTATION = re.compile(r'「[^「」]+」|『[^『』]+』|“[^“”]+”|"[^"\n]+"')


def settings_policy(settings, requested):
    section = (settings or {}).get('subtitle_language') or {}
    language = normalize_language(requested)
    strict = language != 'auto' and section.get('strict_language') is not False
    return dict(version=VERSION, language=language, strict=strict,
                repair=strict and section.get('auto_language_repair') is not False,
                backup=strict and section.get('language_backup_review') is True,
                **{key: section[key] for key in REPAIR_SETTINGS if key in section})


def saved_options(policy):
    options = {option: bool(policy[field]) for option, field in (
        ('strict_language', 'strict'), ('auto_language_repair', 'repair'), ('language_backup_review', 'backup'))
        if field in policy}
    return {**options, **{key: policy[key] for key in REPAIR_SETTINGS if key in policy}}


def sensevoice_language(requested):
    language = normalize_language(requested)
    if language not in {'auto', 'zh', 'en', 'ja', 'ko'}:
        raise ValueError(f'SenseVoice Small 不支援指定語言 {language}，請選擇支援該語言的模型。')
    return language


def funasr_language_options(model, requested):
    language = normalize_language(requested)
    if model == 'sensevoice':
        return dict(language=sensevoice_language(language), use_itn=True)
    if model == 'funasr_nano' and language != 'auto':
        supported = {'zh': '中文', 'en': '英文', 'ja': '日文'}
        if language not in supported:
            raise ValueError(f'Fun-ASR Nano 不支援指定語言 {language}。')
        return {'language': supported[language]}
    return {}


def score(text, target):
    """Return a confident text language or None for mixed/ambiguous evidence."""
    clean = NON_SPEECH.sub(' ', str(text or ''))
    counts = script_counts(clean)
    total = sum(counts.values())
    if total < 7:
        return None
    if counts['kana'] >= 4 and (counts['kana'] + counts['han']) >= .85 * total:
        return 'ja'
    if counts['han'] >= 7 and counts['han'] >= .85 * total and target != 'ja' and not counts['kana']:
        return 'zh'
    for code in ('ko', 'ru'):
        count = counts[SCRIPT[code]]
        if count >= 7 and count >= .85 * total:
            return code
    if counts['latin'] < .85 * total or len(LATIN_WORDS.findall(clean)) < 5:
        return None
    # Reuse the local stopword/accent classifier but require independent
    # evidence across multiple words as well as a margin over the runner-up.
    _, scores = latin_language([clean])
    words = {word.casefold() for word in LATIN_WORDS.findall(clean)}
    _, diverse_scores = latin_language([' '.join(sorted(words))])
    best, next_best = sorted(scores, key=scores.get, reverse=True)[:2]
    return best if diverse_scores[best] >= 3 and scores[best] >= max(4, scores[next_best] + 2) else None


def conflict(text, target):
    detected = score(text, target)
    if not detected or detected == target:
        return None
    # Explicit quotations can dominate script counts even when the surrounding
    # speech is clearly in the requested language. Only use this exemption
    # when there is enough surrounding language evidence on its own.
    if score(QUOTATION.sub(' ', str(text or '')), target) == target:
        return None
    return detected


def run_repair_window(backend, media_path, audio, start, end, cache_context, context, legacy):
    from .run_context import local_runtime_context
    from .speech_coverage import transcribe_recovery_window
    from ..glossary.terminology import GlossarySnapshot
    child = replace(context, enable_domain_terms=False, glossary_snapshot=GlossarySnapshot(),
                    enabled_glossary_ids=[], primary_ready_callback=None, input_session=None,
                    asr_manifest_key='', asr_provisional_cues=[], language_guard_repair=True,
                    language_evidence={}, language_decision={})
    with local_runtime_context(child):
        rows = transcribe_recovery_window(backend, media_path, audio, start, end, cache_context, child, legacy)
        if str(getattr(legacy, 'FIRERED_ASR_BACKEND', 'off')) in {'off', 'haas_native'}:
            return rows
        from .asr import transcribe_qwen_aligner_reference
        from ..subtitle_rules.language_rules import qwen_language_name
        code = normalize_language(context.requested_language)
        language = qwen_language_name(code)
        for row in rows:
            words = row.get('words') or row.get('tokens') or ()
            if (not language or score(row.get('text'), code) != code
                    or _complete_word_evidence(row.get('text'), words)):
                continue
            measured = transcribe_qwen_aligner_reference(audio, [row], language=language)
            if (_complete_word_evidence(row.get('text'), measured)
                    and all(piece.get('start_basis') == piece.get('end_basis') == 'model' for piece in measured)):
                row.pop('words', None)
                row.update(tokens=measured, timestamp_source='qwen_forced_aligner', timing_precision='word')
            elif measured:
                row['repair_alignment_note'] = 'some_word_edges_not_directly_measured'
        return rows


def probe_source_audio(audio, windows, cache_context, legacy):
    """Run the installed local detector in one unforced, context-free batch."""
    from pathlib import Path
    from .asr import _transcribe_qwen_worker, resolve_qwen_asr_local_source
    from ..subtitle_rules.language_rules import language_from_qwen_name
    model = resolve_qwen_asr_local_source()
    if not model:
        return {}
    rate = legacy.AUDIO_SAMPLE_RATE
    chunks = [dict(start=window.start, end=window.end,
                   audio=(audio[round(window.start*rate):round(window.end*rate)], rate)) for window in windows]
    root = Path(cache_context['cache_dir']) / 'language-acoustic-probes'
    rows = _transcribe_qwen_worker(audio, chunks, model, context='', evidence_root=str(root), automatic_language=True)
    findings = {}
    for row in rows:
        language = language_from_qwen_name(row.get('language')) or normalize_language(row.get('language'))
        if language != 'auto' and score(row.get('text'), language) == language:
            findings[(row['start'], row['end'])] = dict(language=language, method='unforced_qwen_local',
                                                       text=row['text'], start=row['start'], end=row['end'])
    return findings


def confirmed_mixed_reading(audio, context, row):
    from .alignment_audio import pcm_digest
    snapshot = context.recognition_snapshot or {}
    project = snapshot.get('project') or {}
    state = (project.get('generation_metadata') or {}).get('transcript_acceptance') or {}
    offset_ms = (snapshot.get('range_ms') or [0])[0]
    start, end = round(float(row['start'])*16000), round(float(row['end'])*16000)
    if not 0 <= start < end <= len(audio):
        return False
    for saved in state.get('observed_ranges', []):
        if not saved.get('confirmed_mixed_language') or not saved.get('pcm_sha256'):
            continue
        if normalize_language(saved.get('requested_language')) != normalize_language(context.requested_language):
            continue
        if (start + offset_ms*16, end + offset_ms*16) != (saved.get('start_sample'), saved.get('end_sample')):
            continue
        if (saved.get('language_guard') or {}).get('original_text') != row.get('text'):
            continue
        if pcm_digest(audio[start:end]) == saved['pcm_sha256']:
            return True
    return False


def snapshot_text(rows, policy):
    return {row.segment_id: row.text for row in rows} if policy['strict'] else {}


def validate_edits(before, after, policy, stage, event):
    """Report newly introduced conflicts using stable source time and identity."""
    if not policy['strict']:
        return set()
    target = policy['language']
    flagged = set()
    for row in after:
        original = before.get(row.segment_id, '')
        if original == row.text:
            continue
        detected = conflict(row.text, target)
        if detected and detected != conflict(original, target):
            flagged.add(row.segment_id)
            event('language_guard_stage_conflict', stage=stage, start=row.start, end=row.end,
                  requested_language=target, language=detected, original_text=original, candidate=row.text)
    return flagged


def protect_fusion(originals, rows, policy, event):
    """Keep the source for disputed fusion edits and retain candidates in diagnostics."""
    before = snapshot_text(originals, policy)
    flagged = validate_edits(before, rows, policy, 'candidate_fusion', event)
    if not flagged:
        return rows
    by_id = {row.segment_id: row for row in originals}
    for row in rows:
        if row.segment_id in flagged and row.segment_id not in by_id:
            row.caption_arbitration['language_guard'] = {'stage': 'candidate_fusion', 'pending': True}
    return [by_id.get(row.segment_id, row) if row.segment_id in flagged else row for row in rows]


def audit_cues(cues, source, policy, stage, event):
    if not policy['strict']:
        return
    target = policy['language']
    flagged = [cue for cue in cues if conflict(cue.text, target)]
    if not flagged:
        return
    # Scope a short list of potentially foreign cues to their own source.
    active = sorted(source, key=lambda segment: segment.start)
    cursor = 0
    for cue in sorted(flagged, key=lambda row: row.start):
        while cursor < len(active) and active[cursor].end <= cue.start:
            cursor += 1
        parts = []
        for index in range(cursor, len(active)):
            segment = active[index]
            if segment.start >= cue.end:
                break
            if segment.end > cue.start and segment.speaker == cue.speaker:
                parts.append(segment.text)
        original = ' '.join(parts)
        detected = conflict(cue.text, target)
        if detected != conflict(original, target) and _reading(cue.text) not in _reading(original):
            event('language_guard_stage_conflict', stage=stage, start=cue.start, end=cue.end,
                  requested_language=target, language=detected, original_text=original, candidate=cue.text)


def _complete_word_evidence(text, words):
    return bool(words and _reading(''.join(str(w.get('word') or w.get('text') or '') for w in words)) == _reading(text)
                and all(w.get('start_basis', 'model') == w.get('end_basis', 'model') == 'model' for w in words))


def _silent_pcm_edge(audio, start, end):
    if audio is None:
        return False
    import numpy as np
    left, right = round(start * 16000), round(end * 16000)
    if not 0 <= left < right <= len(audio):
        return False
    samples = audio[left:right]
    # Only below -80 dBFS throughout. An audible pause, music bed or apparent
    # speech gap still needs the usual measured edge coverage.
    return bool(np.isfinite(samples).all() and np.abs(samples).max() <= .0001)


def _timed_candidate(rows, original, target, *, audio=None):
    """Require measured words wholly attributable to the original interval."""
    start, end = float(original['start']), float(original['end'])
    rows = [row for row in rows if float(row['start']) < end and float(row['end']) > start]
    if len(rows) != 1:
        return None, 'candidate_spans_ambiguous'
    row = rows[0]
    if row.get('cloud_gap') or score(row.get('text'), target) != target:
        return None, 'language_or_empty_candidate_unverified'
    words = row.get('words') or row.get('tokens') or ()
    if not words:
        return None, row.get('repair_alignment_note') or 'measured_words_missing'
    if any(not math.isfinite(float(w['start'])) or not math.isfinite(float(w['end']))
           or not start <= float(w['start']) < float(w['end']) <= end for w in words):
        return None, 'outside_original_time_bounds'
    if not _complete_word_evidence(row['text'], words):
        return None, 'word_text_coverage_mismatch'
    uncovered_start = float(words[0]['start']) - .48
    uncovered_end = float(words[-1]['end']) + .48
    if ((uncovered_start > start and not _silent_pcm_edge(audio, start, uncovered_start))
            or (uncovered_end < end and not _silent_pcm_edge(audio, uncovered_end, end))):
        return None, 'insufficient_edge_coverage'
    if any(float(a['end']) > float(b['start']) + .005 for a, b in zip(words, words[1:])):
        return None, 'overlapping_word_times'
    has_silent_margin = uncovered_start > start or uncovered_end < end
    return copy.deepcopy(row), 'measured_silent_source_edges' if has_silent_margin else 'measured'


def _reading(text):
    return ''.join(char for char in str(text or '').casefold() if char.isalnum())


def _for_member(candidates, original, shared):
    from .transcript_fidelity import transcript_spans
    start, end = float(original['start']), float(original['end'])
    selected = []
    for row in candidates:
        if float(row['start']) >= end or float(row['end']) <= start:
            continue
        if start <= float(row['start']) and float(row['end']) <= end:
            selected.append(row)
            continue
        words = row.get('words') or row.get('tokens') or ()
        if not words and not shared:
            # The padded context can still corroborate an identical reading
            # from an independent recognizer. It cannot supply timing itself.
            selected.append(row)
            continue
        spans = transcript_spans(row.get('text', ''), [word.get('word') or word.get('text') for word in words])
        if not spans:
            continue
        scoped = [(word, span) for word, span in zip(words, spans) if float(word['end']) > start and float(word['start']) < end]
        if not scoped or any(not span or not start <= float(word['start']) < float(word['end']) <= end for word, span in scoped):
            continue
        first, last = scoped[0][1][0], scoped[-1][1][1]
        selected.append(dict(start=scoped[0][0]['start'], end=scoped[-1][0]['end'], text=row['text'][first:last],
                             **{('words' if row.get('words') else 'tokens'): [word for word, _ in scoped]},
                             timestamp_source=row.get('timestamp_source'),
                             timing_precision=row.get('timing_precision') or 'word'))
    return selected


def _confirmed_short_switch(row, before, after, acoustic, detected, target):
    if not acoustic or acoustic.get('language') != detected or before is None or after is None:
        return False
    speaker = str(row.get('speaker') or '')
    if speaker in {'', 'S00', 'unknown'} or any(str(part.get('speaker') or '') != speaker for part in (before, after)):
        return False
    return (0 < row['end'] - row['start'] <= 6
            and 0 <= row['start'] - before['end'] <= 2
            and 0 <= after['start'] - row['end'] <= 2
            and all(score(part.get('text'), target) == target for part in (before, after)))


def inspect_primary(rows, policy, *, duration, primary, runner, backup=None, event, review, speech=(), quote=None,
                    prior_cost_usd=0, acoustic_probe=None, confirmed_mixed=None, audio=None):
    """Keep every unresolved row and carry timing and speaker identity on repair."""
    if not policy['strict'] or policy['language'] not in SCRIPT:
        return rows
    target = policy['language']
    result = list(rows)
    from collections import Counter
    suspects = {}
    accepted_mixed = 0
    for index, row in enumerate(rows):
        if row.get('cloud_gap') or not (detected := conflict(row.get('text'), target)):
            continue
        if confirmed_mixed and confirmed_mixed(row):
            accepted_mixed += 1
        else:
            suspects[index] = detected
    windows = list(plan_windows(rows, suspects, duration))
    budget = RepairBudget(windows, duration, speech, policy, quote=quote, prior_cost_usd=prior_cost_usd)
    observed = {}
    if acoustic_probe and windows and policy['repair'] and budget.max_elapsed > 0:
        eligible = [window for window in windows if 1.2 <= window.end-window.start <= MAX_WINDOW_SECONDS]
        try:
            observed = acoustic_probe(eligible[:8]) if eligible else {}
        except Exception as exc:
            from .service import CancelledError
            if isinstance(exc, CancelledError):
                raise
            event('language_guard_acoustic_probe_failed', category=type(exc).__name__)
    repaired_by = Counter()
    short_switch_count = 0
    order = sorted(range(len(rows)), key=lambda index: (rows[index]['start'], rows[index]['end'])) if observed else []
    neighbors = {index: (rows[order[pos - 1]], rows[order[pos + 1]])
                 for pos, index in enumerate(order) if 0 < pos < len(order) - 1}
    for window in windows:
        acoustic = observed.get((window.start, window.end))
        evidence = {index: dict(stage='primary_asr', start=rows[index]['start'], end=rows[index]['end'],
                                language=suspects[index], requested_language=target, attempts=[],
                                original_text=rows[index].get('text'), repair_window=[window.start, window.end],
                                acoustic_observation=acoustic)
                    for index in window.rows}
        pending = dict.fromkeys(window.rows)
        prior = {index: {} for index in window.rows}
        for index in window.rows:
            before, after = neighbors.get(index, (None, None))
            if len(window.rows) == 1 and _confirmed_short_switch(
                    rows[index], before, after, acoustic, suspects[index], target):
                receipt = dict(evidence[index], classification='confirmed_short_switch', pending=False)
                result[index] = dict(rows[index], language_guard=receipt)
                event('language_guard_segment', **receipt, repaired=False)
                del evidence[index]
                pending.pop(index)
                short_switch_count += 1
        for backend in (primary, backup if policy['backup'] and backup != primary else None):
            if not (policy['repair'] and runner and backend and pending):
                continue
            if any(rows[index].get('text_locked') or rows[index].get('locked') for index in pending):
                continue
            if acoustic and acoustic['language'] != target:
                for index in pending:
                    evidence[index]['attempts'].append(dict(backend=backend, outcome='deferred', category='source_language_may_differ'))
                break
            reason = budget.reserve(window, backend)
            if reason:
                for index in pending:
                    evidence[index]['attempts'].append(dict(backend=backend, outcome='deferred', category=reason))
                continue
            started = time.monotonic()
            before = len(pending)
            try:
                candidates = list(runner(backend, window.start, window.end))
            except Exception as exc:
                from .service import CancelledError
                if isinstance(exc, CancelledError):
                    raise
                for index in pending:
                    evidence[index]['attempts'].append(dict(backend=backend, outcome='failed', category=type(exc).__name__))
                budget.observe(window, backend, time.monotonic()-started, 0)
                continue
            for index in tuple(pending):
                row = rows[index]
                scoped = _for_member(candidates, row, len(window.rows) > 1)
                timed, timing_reason = _timed_candidate(scoped, row, target, audio=audio)
                prior_candidates = prior[index]
                readings = {_reading(c.get('text')) for c in scoped if score(c.get('text'), target) == target
                            and float(c['end']) > float(row['start']) and float(c['start']) < float(row['end'])}
                confirmation_backend = backend
                if (timed and len(window.rows) == 1 and acoustic and acoustic.get('language') == target
                        and acoustic.get('method') == 'unforced_qwen_local' and backend != 'qwen_local'
                        and _reading(acoustic.get('text')) == _reading(timed['text'])):
                    # The unforced decode already covered this PCM window.
                    # Its language tag alone, or a second decode by the same
                    # model, cannot corroborate the replacement text.
                    replacement = timed
                    repair_source = backend
                    confirmation_backend = 'qwen_local'
                elif timed and _reading(timed['text']) in prior_candidates:
                    replacement = timed
                    repair_source = backend
                else:
                    replacement = next((prior_candidates[reading] for reading in sorted(readings)
                                        if prior_candidates.get(reading)), None)
                    repair_source = primary
                for reading in readings:
                    prior_candidates.setdefault(reading, timed if timed and _reading(timed['text']) == reading else None)
                receipt = evidence[index]
                receipt['attempts'].append(dict(backend=backend, outcome='repaired' if replacement else 'unconfirmed',
                                                candidates=[str(c.get('text') or '') for c in scoped],
                                                timing_evidence=timing_reason))
                if not replacement:
                    continue
                receipt.update(confirmation_backend=confirmation_backend, repair_source=repair_source)
                repaired_by[repair_source] += 1
                updated = dict(row, text=replacement['text'], language_guard=receipt)
                for key in ('words', 'tokens', 'provider_source', 'timestamp_source', 'timing_precision', 'native_timing_owner'):
                    updated.pop(key, None)
                    if key in replacement:
                        updated[key] = replacement[key]
                result[index] = updated
                pending.pop(index)
            budget.observe(window, backend, time.monotonic()-started, before-len(pending))
        for index in pending:
            row = rows[index]
            receipt = evidence[index]
            result[index] = dict(row, language_guard=dict(receipt, pending=True))
            message = ('本機原音檢查顯示可能使用另一種語言，已保留字幕供試聽確認。'
                       if acoustic and acoustic['language'] != target else '已保留來源字幕，請對照此範圍的原聲。')
            review(row['start'], '转写语言需要核对', message,
                   priority=2, severity='warning', language_guard=receipt,
                   retry_action='inspect_audio_then_recognize_range')
        for index, receipt in evidence.items():
            event('language_guard_segment', **receipt, repaired=index not in pending)
    fixed = sum(repaired_by.values())
    anomalies = len(suspects) - short_switch_count
    event('language_guard_summary', stage='primary_asr', requested_language=target, examined=len(rows),
          anomalies=anomalies, repaired=fixed, pending=anomalies - fixed,
          requests=sum(budget.requests.values()), repaired_by=dict(repaired_by), budget=budget.receipt(),
          acoustic_observations=len(observed), confirmed_mixed_count=accepted_mixed + short_switch_count,
          audio_seconds=round(sum(budget.audio.values()), 3), elapsed_seconds=round(time.monotonic()-budget.started, 3))
    return result
