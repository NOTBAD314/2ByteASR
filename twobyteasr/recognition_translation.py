"""Japanese -> Chinese translation at the end of a recognition task.

Runs when the user chose "Chinese translation" or "bilingual" output before
starting and the task turned out to be Japanese. It runs before the project is
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
    from .runtime_paths import user_data_root
    return user_data_root() / "cache" / CACHE_FILE


def load_cache() -> dict:
    try:
        payload = json.loads(cache_path().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    if len(cache) > CACHE_LIMIT:
        for key in list(cache)[: len(cache) - CACHE_LIMIT]:
            cache.pop(key, None)
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


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
    from .studio_project import StudioCue
    from .subtitle_translation import apply_translation_result, status_counts, translate, translation_source
    cues = list(cues)
    fake = SimpleNamespace(cues=[StudioCue(id=cue_id, start_ms=round(float(cue.start) * 1000),
                                           end_ms=round(float(cue.end) * 1000), text=str(cue.text or ""),
                                           speaker_id=str(getattr(cue, "speaker", "S00") or "S00"))
                                 for cue_id, cue in zip(project_cue_ids(cues), cues)],
                           generation_metadata={"language": {"code": language}}, studio_state={}, speakers=[])
    if provider is None:
        from .ai_providers import provider_for_stage
        from .asr_provider_snapshot import resolve_provider_snapshot
        from .llm_adapter import post_chat_completion
        settings = getattr(runtime_context, "asr_settings_snapshot", None) or getattr(legacy, "RUNTIME_SETTINGS", {})
        snapshot = resolve_provider_snapshot(settings, stage="polish")
        provider = provider_for_stage(snapshot.execution_settings(), "polish", sender=post_chat_completion)
    token = getattr(runtime_context, "cancellation_token", None)
    cache = load_cache()
    source_label = {"zh": "中文", "ja": "日文", "en": "英文"}[language]
    print(f"   [翻译] {source_label} → {TARGET_LABELS[target]}：{len(fake.cues)} 条，按批发送字幕文字到已配置的 AI 服务…")

    def progress(done, total, message=""):
        print(f"   [翻译] {done}/{total} {message}".rstrip())

    result = translate(translation_source(fake), None, provider, target=target,
                       game_context=str(getattr(runtime_context, "game_name", "") or ""),
                       cancel_check=(lambda: bool(token and token.is_cancelled)), progress=progress, cache=cache)
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
    return {key: metadata[key] for key in ("translation_records", "translations") if key in metadata}
