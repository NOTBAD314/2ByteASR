"""Fill ranges the cloud's content review stopped with a local model (2026-10-24).

MOSI (MOSS Pro cloud) stops a request whose audio or text its content safety
review does not accept. The cloud worker returns that range as a gap marker
and the task goes on (``mosi_asr.gap_row``). Here each gap is recognized with
an installed local primary model that runs on this computer and handles the
task language, and the rows join the primary transcript, marked by source.

Without such a model, or when it fails, the task still finishes with the range
uncovered; only a task without any text stops. Every outcome is one
``cloud_asr_gap_fill`` event (report, 排查原因) and one review item per gap.
"""
from __future__ import annotations

# Stage label of the progress page (progress_model.STAGE_WORDING).
STAGE_LABEL = "本地补识别被拦下的片段"
# Most capable first; the first one installed, runnable here and able to
# handle the language fills the gaps. Models with their own runtime (GLM-ASR,
# Canary) are left out: a missing runtime would only show up as a failure.
FILL_ORDER = ("moss", "qwen_local", "mlx_qwen3_asr_1_7b", "mlx_qwen3_asr", "firered_llm", "whisper_turbo",
              "sensevoice", "funasr_nano", "firered", "paraformer")
SUPPORTED = {"strong", "usable"}


def _workshop_model(backend: str):
    from ..local_models.model_workshop import MODELS
    return next((model for model in MODELS if ("primary", backend) in model.adapter_bindings), None)


def _speaks(model, language: str) -> bool:
    """Whether ``model`` handles ``language`` ('' = unknown)."""
    from ..local_models.model_languages import BADGE_LANGUAGES, language_support
    support = language_support(model.key) or {}
    tiers = support.get("tiers", {})
    if not language:
        # Nothing to judge by (every request was stopped): Chinese and English.
        return tiers.get("zh") in SUPPORTED and tiers.get("en") in SUPPORTED
    if language in BADGE_LANGUAGES:
        return tiers.get(language) in SUPPORTED
    # A language without a badge (es, de, fr, …): only models that publish
    # broad language coverage.
    return bool(support.get("more"))


def choose_backend(language: str, *, installed=None, host=None):
    """``(backend, model name)`` of the local model that fills gaps, or None."""
    from ..local_models.model_workshop import model_platform_available
    from .recognition_choices import host_profile, unavailable_on_host
    if installed is None:
        from ..local_models.model_registry import installed_model_keys
        installed = installed_model_keys()
    host = host or host_profile()
    for backend in FILL_ORDER:
        model = _workshop_model(backend)
        if model is None or not set(model.install_keys or ()) <= set(installed):
            continue
        if not model_platform_available(model) or unavailable_on_host("primary", backend, host):
            continue
        runtime = (host.moss_runtime if backend == "moss" else
                   host.mlx_runtime if backend.startswith("mlx_") else host.main_runtime)
        if runtime and _speaks(model, language):
            return backend, model.name
    return None


def merged_ranges(gaps) -> list[tuple[float, float]]:
    """Gap ranges in time order, touching ones joined (pieces of one block)."""
    ranges = []
    for start, end in sorted((float(gap["start"]), float(gap["end"])) for gap in gaps):
        if ranges and start <= ranges[-1][1] + 0.01:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def _regions_in(speech_regions, start: float, end: float) -> list[dict]:
    if speech_regions is None:
        return [dict(start=start, end=end)]
    return [dict(region, start=max(start, float(region["start"])), end=min(end, float(region["end"])))
            for region in speech_regions if float(region["end"]) > start and float(region["start"]) < end]


def _recognize(legacy, backend, ranges, *, media_path, shared_audio, speech_regions, audio_seconds, moss_runner):
    rows = []
    for start, end in ranges:
        if backend == "moss":
            rate = legacy.AUDIO_SAMPLE_RATE
            payload = moss_runner(shared_audio[int(start * rate):int(end * rate)])
            rows.extend(dict(row, start=start + float(row["start"]), end=start + float(row["end"]))
                        for row in payload.get("segments", []))
            continue
        regions = _regions_in(speech_regions, start, end)
        if regions:
            rows.extend(legacy.transcribe_primary_reference(backend, media_path, regions, shared_audio,
                                                            audio_seconds))
    return rows


def _clock(seconds: float) -> str:
    from ..providers.mosi_asr import _clock as clock
    return clock(seconds)


def fill_cloud_gaps(legacy, payload: dict, *, media_path, shared_audio, speech_regions, audio_seconds,
                    cache_context, requested_language, stage_total, moss_runner) -> None:
    """Account for each gap separately, retaining partial results and refusals."""
    import copy
    import hashlib
    import time
    from .speech_coverage import automatic_speech, merge_rows, update_gap, union
    from ..subtitle_rules.language_rules import language_scope, resolve_task_language
    gaps = list(payload.get("cloud_gaps") or ())
    if not gaps:
        return
    texts = [str(row.get("text") or "") for row in payload.get("segments", [])]
    language, evidence = resolve_task_language(requested_language, texts)
    if evidence.get("decided_by") == "default_chinese":
        language = ""
    chosen = choose_backend(language)
    outcomes = []
    requests, audio_used = 0, 0.0
    for start, end in merged_ranges(gaps):
        originals = [copy.deepcopy(g) for g in gaps if float(g['end']) > start and float(g['start']) < end]
        regions = _regions_in(speech_regions, start, end)
        targets = [(r['start'], r['end']) for r in regions]
        eligible = [r for r in regions if automatic_speech(r, anomalous=True)]
        eligible_ranges = [(r['start'], r['end']) for r in eligible]
        gap_id = hashlib.sha256(f'{start}/{end}'.encode()).hexdigest()[:16]
        gap = dict(id=gap_id, start=start, end=end, reason='content_blocked',
            first_missing_stage='raw_response', status='pending', attempts=[],
            recovered_ranges=[], remaining_ranges=[list(r) for r in union(targets)], service_gaps=originals)
        event = dict(gaps=originals, ranges=[[start, end]], language=language, filled=False,
            rows=0, backend='', model='', resplittable=any(g.get('resplittable') for g in originals))
        rows, error = [], ''
        before = time.monotonic()
        if not targets:
            gap.update(status='non_speech', remaining_ranges=[])
            event['reason'] = 'no_speech_evidence'
        elif not eligible:
            gap.update(status='needs_confirmation', evidence='speech_unconfirmed')
            event['reason'] = 'speech_unconfirmed'
        elif chosen is None:
            event['reason'] = 'no_local_model'
        elif requests >= 24 or audio_used + end-start > 1800:
            event['reason'] = 'recovery_budget_exhausted'
        else:
            backend, name = chosen
            event.update(backend=backend, model=name)
            def recognize():
                with language_scope(language or None):
                    return _recognize(legacy, backend, [(start, end)], media_path=media_path,
                        shared_audio=shared_audio, speech_regions=eligible,
                        audio_seconds=audio_seconds, moss_runner=moss_runner)
            requests += 1
            audio_used += end-start
            try:
                rows = legacy.run_timed_stage(2, stage_total, STAGE_LABEL, name,
                    lambda: legacy.run_cached_stage(f'primary_gap_fill_{backend}', cache_context,
                        recognize, should_cache=bool, extra_signature={'gap_fill_v3':
                            dict(range=[start, end], language=language, speech_ranges=eligible_ranges)}))
            except Exception as exc:
                if type(exc).__name__ == 'CancelledError':
                    raise
                error = str(exc)[:300]
                event.update(reason='fill_failed', error=error,
                             error_category=getattr(exc, 'category', type(exc).__name__))
            valid = []
            for row in rows or ():
                speaker = str(row.get('speaker') or 'UNKNOWN')
                valid.append(dict(row, source=f'{backend}-gapfill',
                    gap_fill=dict(backend=backend, reason='content_blocked', gap_id=gap_id),
                    speaker=f'LOCAL_{gap_id}_{speaker}'))
            merged, rows = merge_rows(payload.get('segments', []), valid, eligible_ranges)
            payload['segments'] = merged
            refs, _ = merge_rows(payload.get('references', []), rows, [(start, end)])
            payload['references'] = refs
            update_gap(gap, rows, source=backend, elapsed=time.monotonic()-before, error=error)
            event.update(filled=gap['status'] == 'recovered', rows=len(rows),
                         reason=event.get('reason') or ('partial_coverage' if rows and gap['remaining_ranges'] else '' if rows else 'no_text'))
        event.update(gap_id=gap_id, remaining_ranges=gap['remaining_ranges'],
                     recovered_ranges=gap['recovered_ranges'], status=gap['status'])
        legacy.record_run_event('cloud_asr_gap_fill', **event)
        span = f'{_clock(start)}–{_clock(end)}'
        if event['filled']:
            legacy.add_review_item(start, '这一段由本地模型补识别',
                f"在线服务的内容审查拦下了 {span}，由本地 {event['model']} 补识别，请核对文字和待确认说话人。",
                priority=2, severity='review')
        elif gap['status'] != 'non_speech':
            legacy.add_review_item(start, '这一段仍有字幕缺口' if rows else '这一段没有字幕',
                f'在线服务的内容审查拦下了 {span}，仍有未恢复范围。', priority=3, severity='warning')
        outcomes.append(gap)
    payload['speech_gap_results'] = outcomes
    if not payload.get('segments'):
        from ..providers.cloud_api_worker import CONTENT_BLOCKED_ACTION, RESUBMIT_CATEGORIES
        details = ' '.join(str(g.get('detail') or '') for g in gaps)
        local = '这台电脑上没有能补识别这段语言的本地主力模型。' if chosen is None else '本地补识别未取得有效文字。'
        raise RuntimeError(' '.join((RESUBMIT_CATEGORIES['content_blocked'], details, local, CONTENT_BLOCKED_ACTION)))
