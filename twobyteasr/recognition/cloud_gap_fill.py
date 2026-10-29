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
    """Recognize ``payload['cloud_gaps']`` locally and merge the rows into
    ``payload`` (``segments`` and ``references``). Raises only when the task
    has no text at all."""
    from ..subtitle_rules.language_rules import language_scope, resolve_task_language
    gaps = list(payload.get("cloud_gaps") or ())
    if not gaps:
        return
    ranges = merged_ranges(gaps)
    texts = [str(row.get("text") or "") for row in payload.get("segments", [])]
    language, evidence = resolve_task_language(requested_language, texts)
    if evidence.get("decided_by") == "default_chinese":
        language = ""  # nothing to go by: a multilingual model
    chosen = choose_backend(language)
    event = dict(gaps=[dict(gap) for gap in gaps], ranges=[[round(a, 3), round(b, 3)] for a, b in ranges],
                 language=language, filled=False, rows=0, backend="", model="",
                 resplittable=any(gap.get("resplittable") for gap in gaps))
    rows, error = [], ""
    if chosen is None:
        event["reason"] = "no_local_model"
    else:
        backend, name = chosen
        event.update(backend=backend, model=name)

        def recognize():
            with language_scope(language or None):
                return _recognize(legacy, backend, ranges, media_path=media_path, shared_audio=shared_audio,
                                  speech_regions=speech_regions, audio_seconds=audio_seconds,
                                  moss_runner=moss_runner)
        try:
            rows = legacy.run_timed_stage(2, stage_total, STAGE_LABEL, name, lambda: legacy.run_cached_stage(
                f"primary_gap_fill_{backend}", cache_context, recognize, should_cache=bool,
                extra_signature={"gap_fill_v1": dict(ranges=event["ranges"], language=language,
                                                     regions=len(speech_regions or ()))}))
        except Exception as exc:  # noqa: BLE001 - the gap stays; the rest of the task is still good
            if exc.__class__.__name__ == "CancelledError":
                raise
            error = str(exc)[:300]
            event.update(reason="fill_failed", error=error)
        rows = [row for row in rows or () if str(row.get("text") or "").strip()]
        if not error:
            event.update(filled=bool(rows), rows=len(rows), reason="" if rows else "no_text")
    for row in rows:
        speaker = str(row.get("speaker") or "")
        row.update(source=f"{event['backend']}-gapfill", gap_fill=dict(backend=event["backend"], reason="content_blocked"),
                   speaker=f"LOCAL_{speaker}" if speaker and speaker != "S00" else "S00")
    legacy.record_run_event("cloud_asr_gap_fill", **event)
    for start, end in ranges:
        span = f"{_clock(start)}–{_clock(end)}"
        if event["filled"]:
            legacy.add_review_item(start, "这一段由本地模型补识别",
                                   f"在线识别服务的内容审查拦下了 {span}，这一段改用本地 {event['model']} 识别；"
                                   "字和说话人可能跟其他段不同。", priority=2, severity="review")
        else:
            legacy.add_review_item(start, "这一段没有字幕",
                                   f"在线识别服务的内容审查拦下了 {span}，本地也没能补上。", priority=3,
                                   severity="warning")
    if rows:
        payload.setdefault("references", []).extend(dict(row) for row in rows)
        payload.setdefault("segments", []).extend(
            dict(row, start=float(row["start"]), end=float(row["end"]), text=str(row["text"])) for row in rows)
        for key in ("references", "segments"):
            payload[key].sort(key=lambda row: (float(row["start"]), float(row["end"])))
    if not payload.get("segments"):
        from ..providers.cloud_api_worker import CONTENT_BLOCKED_ACTION, RESUBMIT_CATEGORIES
        details = " ".join(str(gap.get("detail") or "") for gap in gaps)
        local = {"no_local_model": "这台电脑上没有能补识别这段语言的本地主力模型。",
                 "fill_failed": "本地模型补识别失败：" + error + "。",
                 "no_text": "本地模型没有识别出文字。"}.get(event.get("reason"), "")
        raise RuntimeError(" ".join(part for part in (RESUBMIT_CATEGORIES["content_blocked"], details, local,
                                                       CONTENT_BLOCKED_ACTION) if part))
