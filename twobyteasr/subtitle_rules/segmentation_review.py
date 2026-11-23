"""Review the current boundaries and retain the source of historical fallbacks."""

from collections import defaultdict

VERSION = 1
RECORDS = 'segmentation_review_records'

_REASONS = {
    'confirmed_term_split': '拆开了数字、量词或已知术语',
    'known_word_split': '拆开了完整词语或专名',
    'split_reduplicated_sound': '拆开了重复发声',
    'dependent_adjacent_text': '前一句需要后面的内容才能说完整',
    'detached_postposition': '后一句开头的助词应连着前一句',
    'word_or_dependency_split': '断点落在依存词组中间',
}


def current_boundaries(project):
    from subtitle_core import content_exact
    from .ai_boundary_policy import inspect
    from .current_issues import _language
    from .grouping_quality import BoundaryQuality, INDEPENDENT_RESPONSES
    from .sentence_refine_ranges import _spoken_gap

    receipts = project.studio_state.get('caption_timeline', {}).get('instances', {})
    manual = set(project.studio_state.get('ai_sentence_refine', {}).get('protected_after_cue_ids', ()))
    ordered = sorted(project.cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    run = []
    for left, right in zip(ordered, ordered[1:]):
        ltext, rtext = content_exact(left.text), content_exact(right.text)
        if (not ltext or not rtext or left.speaker_id != right.speaker_id
                or left.id in manual or receipts.get(left.id, {}).get('protected_end')
                or receipts.get(right.id, {}).get('protected_start')
                or left.text.rstrip().endswith(tuple('。！？，；.!?,;'))
                or ltext in INDEPENDENT_RESPONSES or rtext in INDEPENDENT_RESPONSES
                or not -50 <= right.start_ms - left.end_ms < 550
                or not _language(project, left, 'original').startswith('zh')
                or not _language(project, right, 'original').startswith('zh')):
            run = []
            continue
        gap = _spoken_gap(project, left, right)
        if not -50 <= gap < 550:
            run = []
            continue
        edge = len(ltext)
        quality = BoundaryQuality(left.text + right.text, pauses={edge: gap/1000})
        options = [issue for issue in inspect(quality, [edge, quality.total], advisory=True)
                   if issue['start'] == issue['end'] == edge
                   and issue['kind'] in {'semantic_boundary', 'incomplete_expression', 'word_or_dependency_split'}
                   and (issue['kind'] != 'word_or_dependency_split' or edge in quality.syntax_reasons)]
        if options:
            issue = options[0]
            reason = issue.get('reason', issue['kind'])
            yield reason, _REASONS.get(reason, _REASONS.get(issue['kind'], '断点拆开了前后相连的词组')), (left, right)
        if gap < 180 and max(len(ltext), len(rtext)) <= 4:
            if not run:
                run = [left]
            run.append(right)
            if len(run) == 4:
                yield 'continuous_fragments', '同一段连续发言切成四个短片段，未量到足以区分发言的停顿', tuple(run)
                run = []
        else:
            run = []


def history_rows(project):
    from .sentence_refine_history import map_grouping_window

    state = project.studio_state.get('ai_sentence_refine', {})
    verified = state.get('verified_history', {})
    fingerprint = project.generation_metadata.get('media_identity', {}).get('fingerprint')
    by_id = None
    for window in state.get('historical_windows', ()):
        if window.get('project_id') != project.project_id:
            continue
        cues = map_grouping_window(project, window) if fingerprint == window.get('media_fingerprint') else ()
        receipt = verified.get(window['range_id'], {})
        if (not cues and fingerprint == window.get('media_fingerprint')
                and receipt.get('basis') == 'independent_transcription_review'):
            if by_id is None:
                by_id = {cue.id: cue for cue in project.cues}
            targets = [by_id.get(row[0]) for row in receipt.get('cues', ())]
            if targets and all(targets) and _same_text_review_sources(project, window, receipt, targets):
                cues = tuple(targets)
        stamp = [[cue.id, cue.text, cue.start_ms, cue.end_ms] for cue in cues]
        resolved = bool(stamp and receipt.get('cues') == stamp and receipt.get('detection_version') == VERSION)
        yield window, cues, 'verified' if resolved else 'actionable' if cues else 'unmapped'


def _same_text_review_sources(project, window, receipt, targets):
    """A proofread resolution is tied to complete independent readings."""
    from subtitle_core import content_exact
    from ..recognition.independent_review import KEY

    ids = set(receipt.get('execution_ids', ()))
    expected = content_exact(''.join(cue.text for cue in targets))
    start, end = window.get('start_ms'), window.get('end_ms')
    if not ids or not expected or start is None or end is None:
        return False
    models = set()
    for run in project.generation_metadata.get(KEY, ()):
        scope = run.get('coverage_ms', ())
        if (run.get('execution_id') not in ids or run.get('status') != 'completed'
                or run.get('role') != 'text_verification'
                or run.get('result_type') != 'independent_transcription'
                or len(scope) != 2 or scope[0] > start or scope[1] < end):
            continue
        observed = ''.join(row.get('text', '') for row in run.get('windows', ())
                           if row.get('status') == 'decoded')
        if content_exact(observed) == expected:
            models.add(run.get('model_id'))
    return len(models - {None, ''}) >= 2

def transcription_disagreements(project, cue_ids=None):
    """Separate overlong numeric text disputes from timing/segmentation retries."""
    from ..recognition.independent_review import supplemental_readings
    from .studio_qc import normalize_spoken_text
    from .sentence_refine_ranges import refinement_limits
    from .segmentation_profiles import project_language_tag

    state = project.studio_state.get('ai_sentence_refine', {})
    disputed = {key for row in state.get('range_results', ())
                if row.get('category') == 'asr_text_disagreement'
                for key in row.get('cue_ids', ())}
    language = project_language_tag(project)
    if language.split('-')[0] != 'zh':
        return disputed
    _, limit, count = refinement_limits(language)
    selected = set(cue_ids) if cue_ids is not None else None
    for cue in project.cues:
        if selected is not None and cue.id not in selected:
            continue
        if not cue.text.strip().isdigit() or count(cue.text) <= limit:
            continue
        observed = supplemental_readings(project, cue)
        current = normalize_spoken_text(cue.text)
        if any(normalize_spoken_text(text) != current for _, text in observed):
            disputed.add(cue.id)
    return disputed


def retryable_refine_ids(project, history=None):
    state = project.studio_state.get('ai_sentence_refine', {})
    failed = set(state.get('failed_cue_ids', ()))
    if history is None:
        history = ([cue.id for cue in mapped] for _, mapped, status in history_rows(project)
                   if status == 'actionable')
    failed.update(key for ids in history for key in ids)
    return failed - transcription_disagreements(project, failed)


def record_verified_history(project, task, previous):
    """Tie a successful retry to the saved output version, including undo."""
    from .sentence_refine_history import map_grouping_window

    accepted = {}
    for row in task.rows.values():
        if (row.get('status') in {'applied', 'unchanged'} and row.get('candidate_verified')
                and not row.get('alignment_pending')):
            origin = row.get('decision_origin') or ('local_validated' if row.get('local_fallback') else 'validated_review')
            accepted.update(dict.fromkeys(row.get('cue_ids', ()), origin))
    if not accepted:
        return
    issues = {cue.id for _, _, cues in current_boundaries(project) for cue in cues}
    state = project.studio_state['ai_sentence_refine']
    for window in state.get('historical_windows', ()):
        inputs = previous.get(window['range_id'], ())
        if not inputs or not set(inputs) <= accepted.keys():
            continue
        cues = map_grouping_window(project, window)
        if cues and not issues.intersection(cue.id for cue in cues):
            state.setdefault('verified_history', {})[window['range_id']] = {
                'task_id': task.task_id, 'detection_version': VERSION,
                'decision_origins': sorted({accepted[key] for key in inputs}),
                'cues': [[cue.id, cue.text, cue.start_ms, cue.end_ms] for cue in cues],
            }


def review_rows(project, issue_class, digest):
    from .language_rules import project_language

    language = project_language(project)
    for reason, detail, cues in current_boundaries(project):
        ids = tuple(cue.id for cue in cues)
        stamp = [(cue.text, cue.start_ms, cue.end_ms) for cue in cues]
        anchor = cues[0]
        source = sorted({str(ref) for cue in cues for ref in cue.evidence_refs if not str(ref).startswith('cue-align:')})
        location = [source, anchor.end_ms, cues[1].start_ms] if source else ids
        yield issue_class(digest([project.project_id, 'segmentation', reason, location]), digest([VERSION, stamp]),
            anchor.id, anchor.speaker_id, 'original', language, 'segmentation_semantic', 'suggested',
            '检查断句边界', detail + '：' + '｜'.join(cue.text for cue in cues),
            anchor.text, anchor.start_ms, cues[-1].end_ms, cue_ids=ids, detection_reason=reason)
    disputed = transcription_disagreements(project)
    for window, cues, disposition in history_rows(project):
        anchor = cues[0] if cues else None
        ids = tuple(cue.id for cue in cues)
        mismatch = bool(disputed.intersection(ids)) and disposition == 'actionable'
        yield issue_class(window['range_id'], digest([VERSION, ids, disposition, mismatch]),
            anchor.id if anchor else '', anchor.speaker_id if anchor else '', 'original', language,
            'segmentation_fallback', 'suggested', '文字待核对' if mismatch else '本地断句回退待复核',
            ('已通过断句复核，保留来源记录' if disposition == 'verified' else
             '当前字幕尚未可靠定位，保留原范围供核对' if disposition == 'unmapped' else
             '同一音频范围的独立识别与主稿不一致，请试听核对文字' if mismatch else
             '识别时使用了本地断句，仍待复核。可选中关联字幕后重试 AI 断句'),
            anchor.text if anchor else '', window.get('start_ms') or 0, window.get('end_ms') or 0,
            disposition=disposition, cue_ids=ids,
            detection_reason='asr_text_disagreement' if mismatch else str(window.get('category') or 'local_fallback'))


def update_records(project, rows):
    """Save source anchors and observed state without duplicating cue text."""
    from ..recognition.cue_word_alignment import cue_words

    previous = project.studio_state.get(RECORDS, {})
    next_records = {key: dict(row, status='not_reproduced', cue_ids=[])
                    if row['status'] in {'actionable', 'handled'} else row
                    for key, row in previous.items()}
    cues = {cue.id: cue for cue in project.cues}
    asr_state = project.studio_state.get('ai_sentence_refine', {})
    history = {row['range_id']: row for row in asr_state.get('historical_windows', ())}
    identity = project.generation_metadata.get('media_identity', {})
    spans = project.generation_metadata.get('segmentation_source_spans', {}).get('cues', {})
    manual = project.studio_state.get('manual_caption_text', {})
    for row in rows:
        old = previous.get(row.issue_id, {})
        if old.get('input_version') == row.input_version and old.get('status') == row.disposition:
            next_records[row.issue_id] = old
            continue
        receipt = history.get(row.issue_id, {})
        parts = {key: spans.get(key, {}).get('parts', ()) for key in row.cue_ids}
        words = set()
        for key in row.cue_ids:
            if key not in cues:
                continue
            measured, _ = cue_words(project, cues[key])
            for word in (measured[:1] + measured[-1:]) if measured else ():
                words.add((str(word.evidence_ref), word.start_ms, word.end_ms))
        origins = {str(spans.get(key, {}).get('boundary_receipt', {}).get('origin') or 'source_unknown')
                   for key in row.cue_ids}
        if any(key in manual for key in row.cue_ids):
            origins.add('manual_edit')
        if receipt:
            origins.add('local_fallback')
        solution = asr_state.get('verified_history', {}).get(row.issue_id, {})
        next_records[row.issue_id] = dict(
            issue_id=row.issue_id, input_version=row.input_version, status=row.disposition,
            cue_ids=list(row.cue_ids), media_fingerprint=receipt.get('media_fingerprint', identity.get('fingerprint')),
            start_ms=row.start_ms, end_ms=row.end_ms, detector_version=VERSION, reason=row.detection_reason,
            source_segment_ids=sorted({str(part['source_id']) for value in parts.values()
                                       for part in value if part.get('source_id') is not None}
                                      | {str(key) for key in receipt.get('source_ids', ())}),
            source_word_refs=sorted(words), origins=sorted(set(old.get('origins', ())) | origins),
            content_span=receipt.get('source_span'), source_parts=parts,
            resolution={'task_id': solution.get('task_id'), 'basis': solution.get('basis', 'verified_range_recheck')}
                if row.disposition == 'verified' else
                {'basis': 'user_confirmation'} if row.disposition == 'handled' else {})
    if next_records != previous:
        project.studio_state[RECORDS] = next_records
