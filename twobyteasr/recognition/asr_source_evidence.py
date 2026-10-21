"""Read-only cue projection of independent ASR observations.

References and ranges survive cue split/merge in the existing evidence store.
The project text, LLM edits, alternate copies and web sources do not vote.
Projection using stored words is text alignment, never new acoustic timing.
"""
from collections import defaultdict
from collections.abc import Mapping
from types import SimpleNamespace

from .caption_arbitration import content, usable_transcript
from .cue_evidence_slice import slice_evidence
from .model_execution import canonical_model_id, primary_model_id, review_model_id


MODEL_LABELS = {'moss': 'MOSS', 'firered': 'FireRed', 'qwen3-asr': 'Qwen',
    'whisper-turbo': 'Whisper', 'sensevoice': 'SenseVoice', 'funasr-nano': 'FunASR Nano'}
_NON_ASR = {'current', '当前', '当前字幕', 'alternate', 'alternate_text',
    'firered_llm', 'firered-llm', 'firered 校对', 'final', 'final_text',
    'polished', 'llm', 'web', 'terminology'}


def independent_model(value):
    raw = str(value or '').strip()
    if raw.casefold() in _NON_ASR or 'consensus' in raw.casefold() or '+' in raw:
        return ''
    model = canonical_model_id(raw)
    if raw.startswith('asr-api:') and raw[8:].strip() not in {'', 'unrecorded'}:
        return raw
    return model if model in MODEL_LABELS else ''


def _confidence(row, model):
    key = {'moss': 'moss_confidence', 'firered': 'firered_confidence',
        'qwen3-asr': 'qwen_confidence'}.get(model, 'confidence')
    value = row.get(key)
    # The old qwen_confidence=0 default means not provided, not failed ASR.
    if value is None or (model == 'qwen3-asr' and value == 0
                         and not row.get('qwen_confidence_available')):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 1 else None


def _observations(row, role_models=None):
    decision = row.get('caption_arbitration') or {}
    original = decision.get('independent_input_evidence') or {}
    coverage = decision.get('source_coverage') or row.get('source_coverage') or {}
    primary = primary_model_id(row.get('primary_source'))
    role_models = role_models or {}
    if not primary and row.get('primary_source'):
        primary = role_models.get('primary', '')
    if not primary and not row.get('primary_source') and row.get('moss_text'):
        primary = 'moss'
    values = [
        (primary, original.get('primary', row.get('moss_text') or row.get('text')), 'primary'),
        ('firered', original.get('firered', row.get('firered_text')), 'firered'),
        (role_models.get('review', 'qwen3-asr'), original.get('qwen', row.get('qwen_asr_text') or row.get('qwen_text')), 'qwen'),
    ]
    # A recorded review backend replaces a historical Qwen role label.
    review_models = [independent_model(key) for key in coverage
                     if independent_model(key) not in {'', primary, 'firered'}]
    if len(review_models) == 1:
        values[2] = (review_models[0], values[2][1], 'qwen')
    if isinstance(row.get('hypotheses'), (tuple, list)):
        for hypothesis in row['hypotheses']:
            if not isinstance(hypothesis, Mapping):
                continue
            model = independent_model(hypothesis.get('model') or hypothesis.get('source'))
            if model and usable_transcript(hypothesis.get('text')):
                yield model, str(hypothesis['text']), 'hypotheses', [hypothesis]
        return
    if not any(usable_transcript(text) for model, text, _field in values if model):
        model = independent_model(row.get('model') or row.get('source'))
        if model and usable_transcript(row.get('text')):
            yield model, str(row['text']), 'text', [row]
        return
    seen = set()
    for model, text, field in values:
        if not model or model in seen or not usable_transcript(text):
            continue
        seen.add(model)
        windows = coverage.get(model)
        yield model, str(text), field, windows


def project_row_observations(reference, row, cue, *, role_models=None):
    from ..subtitle_rules.studio_qc import normalize_spoken_text
    start, end = int(cue.start_ms), int(cue.end_ms)
    current = normalize_spoken_text(cue.text)
    a, b = int(row.get('start_ms', 0) or 0), int(row.get('end_ms', 0) or 0)
    timed = b > a
    if timed and max(0, min(end, b)-max(start, a)) < min(50, (end-start)*.2):
        return []
    output = []
    for model, value, field, windows in _observations(row, role_models):
        # Legacy segment scope is recoverable evidence; it is explicitly not
        # a newly recovered per-model native alignment.
        scopes = list(windows) if isinstance(windows, (list, tuple)) else [
            dict(start_ms=a, end_ms=b, coverage_basis='legacy_segment_scope')]
        for scope in scopes:
            if not isinstance(scope, Mapping):
                continue
            left = int(scope.get('start_ms', a) or 0)
            right = int(scope.get('end_ms', b) or 0)
            if right > left:
                low, high = max(start, left, a) if timed else max(start, left), min(end, right, b) if timed else min(end, right)
                if high <= low:
                    continue
            else:
                low, high = start, end
            # One original segment can feed several cues. Preserve its source
            # range, and align only the requested part against the stored words.
            proxy = dict(row, _observation=value)
            selection = SimpleNamespace(start_ms=low, end_ms=high)
            if not timed or (low <= a and b <= high):
                text = value
            else:
                text = slice_evidence(proxy, selection, '_observation')
            context_only = False
            if not text and not row.get('words'):
                text, context_only = value, True
            if not text:
                continue
            decision = row.get('caption_arbitration') or {}
            original = decision.get('independent_input_evidence') or {}
            comparison_source = original.get('primary') or row.get('moss_text') or row.get('text', '')
            comparison = slice_evidence(dict(row, _comparison=comparison_source),
                selection, '_comparison') if timed else str(cue.text)
            # Stored word midpoints may omit a displayed suffix even while
            # the clipped model window covers the cue's entire time range.
            # Record only a unique textual match; these are normalized text
            # offsets, never newly inferred acoustic timestamps.
            normalized_comparison = normalize_spoken_text(comparison)
            text_start = current.find(normalized_comparison) if normalized_comparison else -1
            if text_start >= 0 and current.find(normalized_comparison, text_start+1) >= 0:
                text_start = -1
            payload = dict(model=model, text=text, source=field, reference=reference,
                start_ms=low, end_ms=high, cue_start_ms=start, cue_end_ms=end,
                original_start_ms=left, original_end_ms=right,
                coverage_basis=scope.get('coverage_basis', 'observed_model_window'),
                coverage_unknown=(not timed and right <= left) or context_only,
                context_only=context_only,
                cue_text_length=len(current),
                cue_text_start=text_start if text_start >= 0 else None,
                cue_text_end=text_start+len(normalized_comparison) if text_start >= 0 else None,
                text_projection_basis='unique_normalized_primary_text_match',
                comparison_text=comparison, speaker_id=str(row.get('speaker_id') or ''),
                confidence=scope.get('confidence', _confidence(row, model)))
            output.append(payload)
    return output


def _timeline_row_observations(project, cue, reference, row, role_models, receipt=None):
    """Recover source character ranges from the existing caption receipt.

    Caption word clocks may have moved after ripple editing; the evidence_ref
    and immutable source words identify the original observation. This avoids
    confusing the current video's clock with an independently moved caption.
    """
    if receipt is None:
        receipt = ((project.studio_state.get('caption_timeline') or {}).get('instances') or {}).get(cue.id) or {}
        spans = receipt.get('source_spans') or []
        if spans:
            return [observation for span in spans if reference in span.get('evidence_refs', ())
                for observation in _timeline_row_observations(project, cue, reference, row, role_models,
                    {**receipt, **span})]
    words = receipt.get('word_base_words') or receipt.get('words') or []
    selected = [word for word in words if word.get('evidence_ref') == reference]
    if words and not selected:
        return []
    acoustic = receipt.get('acoustic_word_observation') or {}
    original_words = (acoustic.get('words') if reference in acoustic.get('evidence_refs', ()) else None) or (
        (row.get('caption_arbitration') or {}).get('acoustic_words')) or row.get('words') or []
    from .word_timing_provenance import estimated_word_timing
    if estimated_word_timing(row) and not acoustic and not (row.get('caption_arbitration') or {}).get('acoustic_words'):
        original_words = []
    wanted = ''.join(content(word.get('text') or '') for word in selected)
    base = ''.join(content(word.get('text') or '') for word in original_words)
    matches = []
    if wanted and base:
        cursor = base.find(wanted)
        while cursor >= 0:
            matches.append((cursor, cursor+len(wanted)))
            cursor = base.find(wanted, cursor+1)
    selected_original = []
    if len(matches) == 1:
        low, high = matches[0]
        cursor = 0
        for word in original_words:
            size = len(content(word.get('text') or ''))
            if cursor < high and cursor+size > low:
                selected_original.append(word)
            cursor += size
    proven = bool(selected_original) and len(selected_original) == len(selected) and all(
        content(left.get('text') or '').casefold() == content(right.get('text') or '').casefold()
        for left, right in zip(selected_original, selected))
    frozen_start = int(receipt.get('source_start_ms', 0) or 0)
    frozen_end = int(receipt.get('source_end_ms', 0) or 0)
    if proven:
        base_start, base_end = receipt.get('word_base_interval') or [cue.start_ms, cue.end_ms]
        delta = int(cue.start_ms)-int(base_start) if cue.end_ms-cue.start_ms == base_end-base_start else 0
        # The receipt's actual word clock survives independent moves/cuts.
        # A character proportion inside the cue would stretch word coverage
        # and pull words beyond its frozen source boundary back into view.
        anchors = sorted(set((int(original[key]), int(recorded[key])+delta)
            for original, recorded in zip(selected_original, selected)
            for key in ('start_ms', 'end_ms')))
        proven = len(anchors) > 1 and all(
            right[0] > left[0] and right[1] > left[1]
            for left, right in zip(anchors, anchors[1:]))
    if proven:
        def project_clock(value, reverse=False):
            points = [(b, a) for a, b in anchors] if reverse else anchors
            pair = next(((left, right) for left, right in zip(points, points[1:])
                if left[0] <= value <= right[0]), (points[0], points[1]) if value < points[0][0] else (points[-2], points[-1]))
            (a, x), (b, y) = pair
            return round(x+(value-a)*(y-x)/(b-a))
        source_start = max(anchors[0][0], project_clock(int(cue.start_ms), True))
        source_end = min(anchors[-1][0], project_clock(int(cue.end_ms), True))
        if frozen_end > frozen_start:
            source_start, source_end = max(source_start, frozen_start), min(source_end, frozen_end)
        if source_end <= source_start:
            return []
    else:
        source_start, source_end = frozen_start, frozen_end
        if source_end <= source_start:
            return []
        # Without a proven word mapping this is context for the whole display
        # cue, never a proportional estimate of acoustic word positions.
    source_cue = SimpleNamespace(start_ms=source_start, end_ms=source_end, text=cue.text)
    observations = project_row_observations(reference, row, source_cue, role_models=role_models)
    if not observations:
        # An exact task/parent receipt still owns the original transcript when
        # its old word stream cannot be sliced (e.g. corrected text differs).
        # Expose context explicitly; it cannot vote as cue-local alignment.
        context_cue = SimpleNamespace(start_ms=int(row.get('start_ms', source_start)),
            end_ms=int(row.get('end_ms', source_end)), text=cue.text)
        observations = project_row_observations(reference, row, context_cue, role_models=role_models)
        for observation in observations:
            observation.update(context_only=True, coverage_unknown=True)
    for observation in observations:
        a, b = observation['start_ms'], observation['end_ms']
        observation['source_start_ms'], observation['source_end_ms'] = a, b
        observation['start_ms'] = max(int(cue.start_ms), project_clock(a)) if proven else int(cue.start_ms)
        observation['end_ms'] = min(int(cue.end_ms), project_clock(b)) if proven else int(cue.end_ms)
        observation['cue_start_ms'], observation['cue_end_ms'] = int(cue.start_ms), int(cue.end_ms)
        observation['projection_basis'] = 'existing_caption_receipt_word_clock' if proven else 'frozen_caption_source_interval'
        for key in ('job_id', 'result_revision', 'task_fingerprint', 'source_cue_id', 'instances'):
            if key in receipt:
                observation[key] = receipt[key]
        observation['coverage_unknown'] = observation['coverage_unknown'] or not proven
    return observations


def cue_source_hypotheses(project, cue, *, index=None):
    refs = list(dict.fromkeys(getattr(cue, 'evidence_refs', ()) or ()))
    evidence = getattr(project, 'asr_evidence', {})
    settings = (getattr(project, 'generation_metadata', {}) or {}).get('models') or {}
    role_models = {}
    if settings:
        def identity(backend):
            if backend in {'api', 'qwen_api'}:
                actual = str(settings.get('qwen_asr_api_model') or '').strip()
                return f'asr-api:{actual}' if actual else ''
            return independent_model(review_model_id(backend))
        if settings.get('qwen_asr_backend'):
            role_models['review'] = identity(settings['qwen_asr_backend'])
        if settings.get('primary_asr_backend'):
            role_models['primary'] = identity(settings['primary_asr_backend'])
    if refs:
        candidates = [(ref, evidence.get(ref)) for ref in refs]
    elif index is not None:
        candidates = [(ref, row) for _start, ref, row in index.overlapping(cue.start_ms, cue.end_ms, 0)]
    else:
        candidates = list(evidence.items())
    result, seen = [], set()
    for ref, row in candidates:
        if not isinstance(row, Mapping):
            continue
        if not refs and not (int(row.get('end_ms', 0) or 0) > int(cue.start_ms)
                             and int(row.get('start_ms', 0) or 0) < int(cue.end_ms)):
            continue
        observations = (_timeline_row_observations(project, cue, ref, row, role_models)
            if (getattr(project, 'render_settings', {}) or {}).get('_cue_domain') == 'timeline'
            else project_row_observations(ref, row, cue, role_models=role_models))
        for observation in observations:
            key = tuple(observation.get(name) for name in ('model', 'reference', 'start_ms', 'end_ms', 'text'))
            if key not in seen:
                seen.add(key)
                result.append(observation)
    result.sort(key=lambda item: (item['start_ms'], item['reference']))
    return tuple(result)


def coverage_summary(hypotheses):
    from ..subtitle_rules.studio_qc import normalize_spoken_text
    rows = [dict(row) for row in hypotheses or () if isinstance(row, Mapping)]
    rows = [dict(row, model=independent_model(row.get('model') or row.get('source')))
            for row in rows]
    rows = [row for row in rows if row['model']]
    unique = {}
    for row in rows:
        key = (row['model'], str(row.get('text') or ''), row.get('start_ms'),
               row.get('end_ms'), row.get('reference'))
        unique.setdefault(key, row)
    rows = list(unique.values())
    present = set(row['model'] for row in rows)
    intervals = defaultdict(list)
    timed_rows = [row for row in rows if row.get('cue_end_ms') is not None]
    spans = []
    if timed_rows:
        start = min(int(row['cue_start_ms']) for row in timed_rows)
        end = max(int(row['cue_end_ms']) for row in timed_rows)
        points = {start, end}
        for row in timed_rows:
            left, right = max(start, int(row['start_ms'])), min(end, int(row['end_ms']))
            if right > left:
                intervals[row['model']].append((left, right))
                points.update((left, right))
        ordered = sorted(points)
        for left, right in zip(ordered, ordered[1:]):
            supporting = sorted(model for model, ranges in intervals.items()
                if any(a <= left and right <= b for a, b in ranges))
            spans.append(dict(start_ms=left, end_ms=right, models=supporting, source_count=len(supporting)))
        minimum = min((span['source_count'] for span in spans), default=0)
        maximum = max((span['source_count'] for span in spans), default=0)
    else:
        minimum = maximum = len(present)
    temporal_minimum = minimum
    # Keep text ranges distinct from time spans. A full clipped time window
    # cannot guarantee independent support for words lost during projection.
    text_intervals = defaultdict(list)
    text_length = max((int(row.get('cue_text_length') or 0) for row in rows), default=0)
    for row in rows:
        left, right = row.get('cue_text_start'), row.get('cue_text_end')
        if left is not None and right is not None and 0 <= int(left) < int(right) <= text_length:
            text_intervals[row['model']].append((int(left), int(right)))
    text_spans = []
    current_text_supported = None
    if text_intervals and text_length:
        points = {0, text_length}
        points.update(point for ranges in text_intervals.values() for pair in ranges for point in pair)
        ordered = sorted(points)
        for left, right in zip(ordered, ordered[1:]):
            supporting = sorted(model for model, ranges in text_intervals.items()
                if any(a <= left and right <= b for a, b in ranges))
            text_spans.append(dict(normalized_char_start=left, normalized_char_end=right,
                models=supporting, source_count=len(supporting)))
        text_minimum = min(span['source_count'] for span in text_spans)
        minimum = min(minimum, text_minimum)
        current_text_supported = text_minimum > 0
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['model']].append(row)
    # Compare each partial observation with its own aligned primary range.
    local_comparisons = [(normalize_spoken_text(row.get('text') or ''), normalize_spoken_text(row.get('comparison_text') or ''))
        for row in rows if row.get('comparison_text')]
    texts = [''.join(normalize_spoken_text(row.get('text') or '') for row in model_rows)
             for model_rows in grouped.values()]
    known_texts = [value for value in texts if value]
    conflict = any(left != right for left, right in local_comparisons) if local_comparisons else len(set(known_texts)) > 1
    unknown_coverage = any(row.get('coverage_unknown') for row in rows)
    partial = bool((spans or text_spans) and minimum < len(present))
    return dict(models=sorted(present), known_count=len(present), minimum_count=minimum,
        maximum_count=maximum, spans=spans, text_spans=text_spans,
        temporal_minimum_count=temporal_minimum, current_text_supported=current_text_supported,
        conflict=conflict,
        missing=not present, partial=partial, coverage_unknown=unknown_coverage,
        agreement=bool(present and known_texts and not conflict),
        single_source=bool(minimum == maximum == 1 and not unknown_coverage))
