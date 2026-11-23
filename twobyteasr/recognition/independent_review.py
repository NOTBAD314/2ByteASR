"""Original independent ASR results, distinct from the current caption."""

from uuid import uuid4

KEY = 'independent_asr_runs'
FIRERED_MODELS = ('firered', 'firered_llm')


def reading_run(model, backend, role, rows, *, job_id, language, coverage=None, status='completed',
                result_type='independent_transcription', reason='', domain='source', input_identity=None):
    results = []
    for row in rows or ():
        start = round(float(row['start']) * 1000)
        end = round(float(row['end']) * 1000)
        if end <= start:
            continue
        results.append(dict(window_id=str(row.get('source_window_id') or len(results) + 1),
                            start_ms=start, end_ms=end, text=str(row.get('raw_text', row.get('text')) or ''),
                            words=row.get('words') or row.get('tokens') or [],
                            language=str(row.get('language') or language),
                            status='decoded' if str(row.get('text') or '').strip() else 'empty'))
    if status == 'completed' and not any(row['status'] == 'decoded' for row in results):
        status = 'empty'
    return dict(execution_id=uuid4().hex, job_id=job_id, model_id=model, backend=backend,
                role=role, result_type=result_type, language=language, status=status, reason=reason,
                time_domain=domain, coverage_ms=list(coverage) if coverage is not None else [],
                input_identity=input_identity or {}, windows=results)


def _cue_clock(project, cue, run):
    domain = project.render_settings.get('_cue_domain')
    if run.get('time_domain') == 'timeline' and domain != 'timeline':
        return None
    if (run.get('time_domain') == 'source' and domain == 'timeline'
            and not project.generation_metadata.get('timeline_recognition')):
        from ..timeline.studio_edit_sequence import sequence_of, timeline_to_source_range
        scope = timeline_to_source_range(sequence_of(project), cue.start_ms, cue.end_ms)
        return scope[0] if len(scope) == 1 else None
    return cue.start_ms, cue.end_ms


def primary_readings(project, cue):
    for run in project.generation_metadata.get(KEY, ()):
        if run.get('role') != 'primary_transcription' or run.get('result_type') != 'independent_transcription':
            continue
        scope = _cue_clock(project, cue, run)
        if scope is None:
            continue
        start, end = scope
        for window in run.get('windows', ()):
            if window['status'] != 'decoded' or window['start_ms'] >= end or window['end_ms'] <= start:
                continue
            exact = abs(window['start_ms']-start) <= 50 and abs(window['end_ms']-end) <= 50
            yield run, window, exact


def firered_readings(project, cue, hypotheses=(), *, mapped_models=()):
    """Return real observations and their coverage state for the selected cue."""
    runs = [run for run in project.generation_metadata.get(KEY, ())
            if run.get('model_id') in FIRERED_MODELS and run.get('role') != 'primary_transcription'
            and run.get('result_type') == 'independent_transcription']
    known = set(mapped_models) | {row.get('model') for row in hypotheses
             if row.get('text') and not row.get('context_only') and not row.get('coverage_unknown')}
    rows = []
    for run in runs:
        scope = _cue_clock(project, cue, run)
        if scope is None:
            continue
        start, end = scope
        coverage = run.get('coverage_ms')
        if coverage and (start >= coverage[1] or end <= coverage[0]):
            continue
        windows = [window for window in run['windows']
                   if window['start_ms'] < end and window['end_ms'] > start]
        status = run['status']
        if status == 'completed':
            if any(window['status'] == 'decoded' for window in windows):
                status = 'mapped' if run['model_id'] in known else 'unmapped'
            else:
                status = 'empty' if windows else 'outside'
        rows.append((run, status, windows))
    if rows:
        return rows
    if runs:
        return [({}, 'outside', [])]
    models = project.generation_metadata.get('models', {})
    execution = project.generation_metadata.get('model_statuses', {})
    legacy = []
    for model in FIRERED_MODELS:
        item = execution.get(model) or {}
        observed = [row for row in hypotheses if row.get('model') == model and row.get('observed_text')]
        if not observed or item.get('role') not in {'text_verification', 'independent_text_and_timing'}:
            continue
        unique = {}
        for row in observed:
            start = row.get('original_start_ms', row['start_ms'])
            end = row.get('original_end_ms', row['end_ms'])
            text = row['observed_text']
            unique[start, end, text] = dict(start_ms=start, end_ms=end, text=text, status='decoded')
        legacy.append((item, 'legacy_mapped' if model in known else 'unmapped', list(unique.values())))
    if legacy:
        return legacy
    if known.intersection(FIRERED_MODELS):
        return [({}, 'legacy_mapped', [])]
    backend = (models.get('qwen_asr_backend') if models.get('qwen_asr_backend') in FIRERED_MODELS
               else 'firered' if models.get('firered_asr_backend') == 'local' else '')
    if backend and models.get('primary_asr_backend') != backend:
        item = execution.get(backend) or {}
        if item.get('failed'):
            return [(item, 'empty' if item.get('failure_reason') == 'empty_result' else 'failed', [])]
        if item.get('selected') and not item.get('completed') and not item.get('skipped'):
            return [(item, 'running' if item.get('started') else 'queued', [])]
        return [(item, 'legacy_unknown', [])]
    return [({}, 'disabled', [])]


def firered_status_text(status):
    return {
        'disabled': '未启用 FireRed 独立文字识别',
        'queued': 'FireRed 等待执行',
        'running': 'FireRed 正在识别这一段',
        'failed': 'FireRed 识别失败',
        'cancelled': 'FireRed 识别已取消',
        'empty': 'FireRed 未返回文字',
        'outside': 'FireRed 未覆盖这段音频',
        'unmapped': 'FireRed 已保存原始结果，待核对字幕映射',
        'mapped': 'FireRed 独立识别已保存',
        'legacy_mapped': '已有 FireRed 独立候选',
        'legacy_unknown': '旧工程缺少 FireRed 执行或覆盖记录',
    }.get(status, status)


def capture_candidate_audio(project, cue):
    """Freeze the exact current audio range without serializing the project."""
    from .recognition_input import _graph_sources
    from ..playback.audio_graph import capture_audio_graph
    from ..timeline.studio_edit_sequence import sequence_of, timeline_duration_ms
    from ..subtitle_rules.language_rules import project_language

    graph = capture_audio_graph(project)
    start, end = cue.start_ms, cue.end_ms
    if start < 0 or end > timeline_duration_ms(project) or not 0 < end-start <= 30_000:
        raise ValueError('请选择时间轴上 30 秒以内、具有音频的字幕')
    graph['segments'] = [layer for layer in graph['segments']
                         if layer['timeline_in_ms'] < end and layer['timeline_out_ms'] > start]
    if not graph['segments']:
        raise ValueError('当前字幕范围没有可识别的音轨')
    return dict(version=2, audio_graph=graph, sources=_graph_sources(graph),
                duration_ms=end-start, range_ms=[start, end], sequence=sequence_of(project).to_dict(),
                project_id=project.project_id, language=project_language(project))


def recognize_candidate_audio(snapshot, token, progress=lambda value: None, *, backend='firered'):
    """Decode only this range and keep the exact result separate from captions."""
    import subtitle_core
    from .asr import (transcribe_firered_llm_reference, _transcribe_firered_worker,
                      tokens_to_reference_chunks)
    from .asr_schema import flatten_segment_tokens
    from .recognition_input import prepare_recognition_input
    from .run_context import RuntimeContext, activate_runtime_context
    from .service import CancelledError
    from ..media.media_service import GLOBAL_MEDIA_SERVICE
    from ..runtime_paths import get_runtime_paths, resolve_model_dir

    context = RuntimeContext(cancellation_token=token)
    ffmpeg = GLOBAL_MEDIA_SERVICE.ffmpeg_path
    status, reason, rows = 'completed', '', []
    offset = snapshot['range_ms'][0] / 1000
    try:
        progress('正在准备该段音频…')
        wav = prepare_recognition_input(snapshot, get_runtime_paths().cache_root, ffmpeg, token=token)
        duration = snapshot['duration_ms'] / 1000
        progress('正在用 FireRed 独立识别…')
        with activate_runtime_context(context):
            if backend == 'firered_llm':
                rows = transcribe_firered_llm_reference(
                    wav, [{'start': 0, 'end': duration}], keep_empty=True)
            else:
                audio = subtitle_core.decode_audio_to_array(wav)
                model = str(resolve_model_dir('FireRedASR2-AED'))
                result = _transcribe_firered_worker(audio, duration, model)
                words = flatten_segment_tokens(result, producer='firered_aed_worker', consumer='studio_candidate')
                rows = tokens_to_reference_chunks(words, [], source='firered')
        token.raise_if_cancelled()
    except CancelledError:
        status, reason, rows = 'cancelled', 'user_cancelled', []
    except (OSError, ValueError, RuntimeError) as exc:
        status = 'empty' if str(exc) == 'FireRed worker returned no parsed tokens' else 'failed'
        reason, rows = str(exc)[:400], []
    for row in rows:
        row['start'] += offset
        row['end'] += offset
        for word in row.get('words') or row.get('tokens') or ():
            word['start'] += offset
            word['end'] += offset
    return reading_run(backend, backend, 'text_verification', rows, job_id=context.job_id,
                       language=snapshot['language'], coverage=snapshot['range_ms'], status=status,
                       reason=reason, domain='timeline', input_identity={'fingerprint': snapshot.get('fingerprint')})


def supplemental_readings(project, cue):
    """A supplemental run owns its measured word times or its exact input range."""
    from .asr_source_evidence import _has_competing_speaker
    from ..subtitle_rules.language_rules import project_language

    if (not any(run.get('time_domain') == 'timeline' for run in project.generation_metadata.get(KEY, ()))
            or _has_competing_speaker(project, cue)):
        return ()
    results = []
    for run, status, windows in firered_readings(project, cue):
        if status != 'unmapped' or run.get('time_domain') != 'timeline' or run.get('language') != project_language(project):
            continue
        coverage = run.get('coverage_ms', ())
        if len(coverage) != 2 or coverage[0] > cue.start_ms or coverage[1] < cue.end_ms:
            continue
        window_text = []
        clipped_word = False
        for window in windows:
            if window['status'] != 'decoded':
                continue
            words = window.get('words') or []
            if words:
                inside = []
                for word in words:
                    start = round(float(word['start']) * 1000)
                    end = round(float(word['end']) * 1000)
                    if start >= cue.end_ms or end <= cue.start_ms:
                        continue
                    if start < cue.start_ms - 50 or end > cue.end_ms + 50:
                        clipped_word = True
                        break
                    inside.append(word['text'])
                text = ''.join(inside)
            elif coverage == [cue.start_ms, cue.end_ms]:
                text = window['text']
            else:
                continue
            if text:
                window_text.append(text)
        if window_text and not clipped_word:
            results.append((run['model_id'], ''.join(window_text)))
    return tuple(dict.fromkeys(results))
