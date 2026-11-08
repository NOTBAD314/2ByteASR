"""Subtitle translation at the end of a recognition task.

Runs when the user chose translated or bilingual output before starting.  The
source is the task language (zh/ja/en/ko/es/de/fr/pt/it/ru, SOURCE_LANGUAGES)
and the target is the task's ``translation_script``; nothing runs when the
target is the source language. It runs before the project is
written, so the delivered project already holds its translation records; a
failure never fails the recognition (the user can translate later in Studio).
Only subtitle text goes to the configured text AI service.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

CACHE_FILE = "subtitle-translation-cache.json"
CACHE_LIMIT = 20000


def cache_path() -> Path:
    from ..runtime_paths import user_data_root
    return user_data_root() / "cache" / CACHE_FILE


def load_cache() -> dict:
    try:
        payload = json.loads(cache_path().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    from ..recognition.task_journal import FileLease,TaskBusy
    from ..storage.atomic_files import write_text_atomic
    import time
    path=cache_path();path.parent.mkdir(parents=True,exist_ok=True)
    lease=FileLease(path.with_suffix('.lock'))
    for attempt in range(8):
        try:lease.acquire();break
        except TaskBusy:
            if attempt==7:raise OSError('Translation cache is busy; task checkpoints remain available')
            time.sleep(.02*(attempt+1))
    try:
        merged=load_cache();merged.update(cache)
        _save_cache_locked(merged,path,write_text_atomic)
    finally:lease.close()


def _save_cache_locked(cache,path,writer):
    if len(cache) > CACHE_LIMIT:
        for key in list(cache)[: len(cache) - CACHE_LIMIT]:
            cache.pop(key, None)
    writer(path,json.dumps(cache,ensure_ascii=False))


def task_cache(context,cache):
    journal=getattr(context,'task_journal',None)
    if journal is not None:
        for key in tuple(journal.record['task'].get('artifacts',{})):
            if str(key).startswith('translation-cache:'):
                value=journal.load_artifact(key,{'kind':'translation-cache-v1'})
                if isinstance(value,dict):cache.update(value)
    return cache


def checkpoint_cache(context,cache,previous):
    journal=getattr(context,'task_journal',None)
    if journal is None:return
    added={key:cache[key] for key in cache.keys()-previous}
    if not added:return
    from ..recognition.task_journal import digest
    journal.publish('translation-cache:'+digest(sorted(added))[:24],added,{'kind':'translation-cache-v1'})
    previous.update(added)


def metadata_complete(metadata):
    records=(metadata.get('translation_records') or {}).get('records') or {}
    return not any(row.get('status') in {'failed','untranslated','needs_update','cancelled'} for row in records.values())


def project_cue_ids(cues) -> list[str]:
    """The ids ``project_from_runtime_cues`` will give these runtime cues."""
    used, ids = set(), []
    for index, cue in enumerate(cues, 1):
        cue_id = str(getattr(cue, "cue_id", index) or index)
        if cue_id in used:
            cue_id = f"{cue_id}-{index}"
        used.add(cue_id)
        ids.append(cue_id)
    return ids


def translate_runtime_cues(cues, runtime_context, legacy, *, provider=None) -> dict:
    """Metadata additions (translation records + render view), or {} when not applicable."""
    mode = str(getattr(runtime_context, "subtitle_output", "original") or "original")
    if mode == "original":
        return {}
    language = str(getattr(runtime_context, "task_language", "") or "")
    from .subtitle_translation import (SOURCE_LANGUAGES, TARGET_LABELS, normalize_target, same_language)
    try:
        target = normalize_target(getattr(runtime_context, "translation_script", "zh-Hans") or "zh-Hans")
    except ValueError:
        target = "zh-Hans"
    # Any direction since 2026-10-14; only "translate into the same language" is skipped.
    if language not in SOURCE_LANGUAGES or same_language(language, target):
        legacy.record_run_event("subtitle_translation_skipped",
                                reason="unknown_source_language" if language not in SOURCE_LANGUAGES
                                else "target_is_source_language", language=language, target=target)
        print(f"   [翻译] 译文语言（{TARGET_LABELS[target]}）与识别语言相同，不翻译。")
        return {}
    from ..projects.studio_project import StudioCue
    from .subtitle_translation import (apply_translation_result, status_counts, translate, translation_source,
                                       RECOMMENDED_BATCH_ITEMS)
    cues = list(cues)
    from ..glossary.translation_terms import KEY, normalize
    term_policy = normalize(getattr(runtime_context, KEY, None))
    fake = SimpleNamespace(cues=[StudioCue(id=cue_id, start_ms=round(float(cue.start) * 1000),
                                           end_ms=round(float(cue.end) * 1000), text=str(cue.text or ""),
                                           speaker_id=str(getattr(cue, "speaker", "S00") or "S00"))
                                 for cue_id, cue in zip(project_cue_ids(cues), cues)],
                           generation_metadata={"language": {"code": language}, KEY: term_policy}, studio_state={}, speakers=[])
    snapshot = (getattr(runtime_context, "provider_snapshots", {}) or {}).get("polish")
    if provider is None:
        from ..providers.ai_providers import provider_for_stage
        from ..providers.asr_provider_snapshot import resolve_provider_snapshot
        from ..providers.llm_adapter import post_chat_completion
        settings = getattr(runtime_context, "asr_settings_snapshot", None) or getattr(legacy, "RUNTIME_SETTINGS", {})
        snapshot = (getattr(runtime_context, "provider_snapshots", {}) or {}).get("polish")
        if snapshot is None:
            snapshot = resolve_provider_snapshot(settings, stage="polish")
        provider = provider_for_stage(snapshot.execution_settings(), "polish", sender=post_chat_completion)
    from ..providers.provider_service import AIClient
    if isinstance(provider,AIClient):
        provider=provider.concurrent_client()
        provider.scheduling_lane='translation'
    token = getattr(runtime_context, "cancellation_token", None)
    cache = task_cache(runtime_context,load_cache())
    checkpointed=set(cache)
    from .european_text import LABELS as european_labels
    source_label = {"zh": "中文", "ja": "日文", "en": "英文", "ko": "韩文", **european_labels}[language]
    print(f"   [翻译] {source_label} → {TARGET_LABELS[target]}：{len(fake.cues)} 条，按批发送字幕文字到已配置的 AI 服务…")

    def progress(done, total, message=""):
        checkpoint_cache(runtime_context,cache,checkpointed)
        print(f"   [翻译] {done}/{total} {message}".rstrip())
        # 2026-10-15: the progress page shows translated / total cues live.
        legacy.record_run_event("subtitle_translation_progress", target=target, done=int(done),
                                total=int(total), message=str(message or "")[:120])

    from .translation_diagnostics import TranslationLog
    request_log = TranslationLog()
    print(f"   [翻译] 请求日志（含字幕文字，不含 API Key）：{request_log.path}")
    # 2026-10-22: batches go out like AI proofreading's, within the broker's admission limit.
    workers = 1
    if getattr(legacy, "PARALLEL_CLOUD_BATCHES", False):
        from ..providers.provider_service import GLOBAL_PROVIDER_SERVICE
        from ..system.task_resources import cloud_request_workers
        workers = max(1, min(cloud_request_workers(snapshot,int(getattr(legacy, "CLOUD_BATCH_WORKERS", 1) or 1)),
                             int(GLOBAL_PROVIDER_SERVICE.scheduling_capacity()["effective_workers"])))
    result = translate(translation_source(fake), None, provider, target=target,
                       max_items=RECOMMENDED_BATCH_ITEMS,
                       game_context=str(getattr(runtime_context, "game_name", "") or ""),
                       cancel_check=(lambda: bool(token and token.is_cancelled)), progress=progress, cache=cache,
                       event=request_log, workers=workers, entrypoint="recognition_auto")
    if request_log.error:
        print(f"   [翻译] 请求日志写入失败：{request_log.error}")
    try:
        save_cache(cache)
    except OSError:
        pass
    apply_translation_result(fake, result)
    counts = status_counts(fake, target=target)
    legacy.record_run_event("subtitle_translation", target=target, requested_output=mode,
                            translated=len(result.translations), failed=len(result.failed),
                            cache_hits=result.cache_hits, requests=result.requests, cancelled=result.cancelled,
                            fatal_error=str(getattr(result, "fatal_error", "") or ""), counts=counts)
    if result.failed or getattr(result, "fatal_error", None):
        legacy.add_review_item(0.0, "翻译未全部完成",
                               f"{len(result.failed)} 条没有译文；可在工作台“双语 → 翻译 / 生成双语字幕”只重试这些字幕",
                               priority=2, severity="warning")
    print(f"   [翻译] 完成 {len(result.translations)} 条，失败 {len(result.failed)} 条，缓存命中 {result.cache_hits} 条。")
    metadata = fake.generation_metadata
    return {key: metadata[key] for key in ("translation_records", "translations", KEY) if key in metadata}
