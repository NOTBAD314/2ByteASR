"""Headless queue orchestration: the single queue interface between the
PySide6 UI and the subtitle core (see docs/adr/0001)."""

from __future__ import annotations

import glob
import inspect
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from twobyteasr.runtime import (
    RuntimeContext,
    activate_runtime_context,
    sync_legacy_runtime,
)


EventSink = Callable[["PipelineEvent"], None]


def preview_glossary_correction(*args, **kwargs):
    """Review copied original transcriptions without re-running ASR or saving."""
    from .studio_glossary_service import preview_glossary_correction as implementation
    return implementation(*args, **kwargs)


class CancelledError(RuntimeError):
    """Raised at a safe pipeline boundary after cancellation is requested."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise CancelledError("任务已取消。")


@dataclass(frozen=True)
class RunOptions:
    content_name: str = ""
    enable_domain_terms: bool = False
    enabled_glossary_ids: tuple[str, ...] = ()
    output_review_track: bool = False
    output_jianying_txt: bool = False
    output_speaker_tracks: bool = False
    force_refresh_polish: bool = False
    force_refresh_group: bool = False
    expected_speakers: int = 0
    dialogue_coverage_mode: str = "all_dialogue"
    overwrite_policy: str = "overwrite"
    studio_project_path: str = ""
    recognition_purpose: str = "final"
    recognition_snapshot_json: str = ""
    speaker_source: str = "single"
    settings_snapshot_json: str = field(default="", repr=False)
    glossary_snapshot_json: str = field(default="", repr=False)
    enable_term_search: bool = False
    job_id: str = ""
    # Spoken language of the media: auto (detect from the transcript), zh or ja.
    recognition_language: str = "auto"
    # Subtitles to produce: original, translation or bilingual (original + translation).
    subtitle_output: str = "original"
    translation_script: str = "zh-Hans"

    def __post_init__(self) -> None:
        if self.job_id:
            from .recognition_result import validate_job_id
            validate_job_id(self.job_id)
        if not 0 <= self.expected_speakers <= 6:
            raise ValueError("expected_speakers 只能是 0（自动）或 1 到 6")
        if self.dialogue_coverage_mode not in {
            "all_dialogue", "host_priority", "host_only"
        }:
            raise ValueError(
                "dialogue_coverage_mode 只能是 all_dialogue、host_priority 或 host_only"
            )
        if self.overwrite_policy not in {"overwrite", "skip", "error"}:
            raise ValueError("overwrite_policy 只能是 overwrite、skip 或 error")
        if self.recognition_purpose not in {"final", "analysis"}:
            raise ValueError("recognition_purpose 只能是 final 或 analysis")
        if self.recognition_language not in {"auto", "zh", "ja", "en"}:
            raise ValueError("recognition_language 只能是 auto、zh、ja 或 en")
        if self.subtitle_output not in {"original", "translation", "bilingual"}:
            raise ValueError("subtitle_output 只能是 original、translation 或 bilingual")
        if self.translation_script not in {"zh-Hans", "zh-Hant"}:
            raise ValueError("translation_script 只能是 zh-Hans 或 zh-Hant")

    @classmethod
    def from_legacy(cls, legacy: Any, *, overwrite_policy: str = "overwrite") -> "RunOptions":
        from .terminology import snapshot_glossaries
        enabled = bool(getattr(legacy, "RUNTIME_ENABLE_DOMAIN_TERMS", False))
        ids = tuple(getattr(legacy, "RUNTIME_ENABLED_GLOSSARY_IDS", ()) or ())
        if enabled and not ids and getattr(legacy, "RUNTIME_GAME_NAME", ""):
            ids = (getattr(legacy, "runtime_game_identity", str)(legacy.RUNTIME_GAME_NAME),)
        return cls(
            content_name=str(getattr(legacy, "RUNTIME_GAME_NAME", "") or ""),
            enable_domain_terms=bool(getattr(legacy, "RUNTIME_ENABLE_DOMAIN_TERMS", False)),
            enable_term_search=bool(getattr(legacy, "RUNTIME_ENABLE_TERM_SEARCH", False)),
            enabled_glossary_ids=tuple(
                getattr(legacy, "RUNTIME_ENABLED_GLOSSARY_IDS", ()) or ()
            ),
            output_review_track=bool(getattr(legacy, "RUNTIME_OUTPUT_REVIEW_TRACK", False)),
            output_jianying_txt=bool(getattr(legacy, "RUNTIME_OUTPUT_JIANYING_TXT", False)),
            output_speaker_tracks=bool(getattr(legacy, "RUNTIME_OUTPUT_SPEAKER_TRACKS", False)),
            force_refresh_polish=bool(getattr(legacy, "RUNTIME_FORCE_REFRESH_POLISH_CACHE", False)),
            force_refresh_group=bool(getattr(legacy, "RUNTIME_FORCE_REFRESH_GROUP_CACHE", False)),
            expected_speakers=int(getattr(legacy, "RUNTIME_EXPECTED_SPEAKERS", 0) or 0),
            dialogue_coverage_mode=str(
                getattr(legacy, "RUNTIME_DIALOGUE_COVERAGE_MODE", "all_dialogue")
                or "all_dialogue"
            ),
            overwrite_policy=overwrite_policy,
            studio_project_path=str(getattr(legacy, "RUNTIME_STUDIO_PROJECT_PATH", "") or ""),
            recognition_purpose=str(getattr(legacy, "RUNTIME_RECOGNITION_PURPOSE", "final") or "final"),
            speaker_source=__import__('twobyteasr.speaker_strategy', fromlist=['resolve']).resolve(getattr(legacy, 'RUNTIME_SETTINGS', {})),
            settings_snapshot_json=json.dumps(getattr(legacy, 'RUNTIME_SETTINGS', {}), ensure_ascii=False),
            glossary_snapshot_json=json.dumps(snapshot_glossaries(legacy, ids if enabled else ()).to_dict(), ensure_ascii=False),
        )

    def create_runtime_context(
        self,
        legacy: Any,
        *,
        cancellation_token: Any | None = None,
        _glossary_snapshot: Any | None = None,
    ) -> RuntimeContext:
        canonicalize = getattr(legacy, "canonicalize_runtime_game_name", str)
        identity = getattr(legacy, "runtime_game_identity", str)
        content_name = canonicalize(self.content_name)
        # 规范化 enabled ids（去空、去重保序）。旧单库回退只能发生在
        # 术语功能明确启用时，否则“空列表”会被当前内容悄悄重新启用。
        enabled_ids = []
        for item in self.enabled_glossary_ids:
            text = str(item).strip()
            if text and text not in enabled_ids:
                enabled_ids.append(text)
        if self.enable_domain_terms and not enabled_ids and content_name:
            enabled_ids = [identity(content_name)]
        from .terminology import GlossarySnapshot, snapshot_glossaries
        snapshot = _glossary_snapshot if _glossary_snapshot is not None else (GlossarySnapshot.from_dict(json.loads(self.glossary_snapshot_json))
            if self.glossary_snapshot_json else snapshot_glossaries(legacy, enabled_ids if self.enable_domain_terms else ()))
        if not self.enable_domain_terms:
            snapshot = GlossarySnapshot()
        enabled_ids = [library.id for library in snapshot.libraries]
        return RuntimeContext(
            job_id=self.job_id or uuid.uuid4().hex,
            game_name=content_name,
            enable_domain_terms=bool(self.enable_domain_terms and enabled_ids),
            enable_term_search=bool(self.enable_term_search),
            enabled_glossary_ids=enabled_ids,
            glossary_snapshot=snapshot,
            output_review_track=bool(self.output_review_track),
            output_jianying_txt=bool(self.output_jianying_txt),
            output_speaker_tracks=bool(self.output_speaker_tracks),
            force_refresh_api_cache=False,
            force_refresh_polish_cache=bool(self.force_refresh_polish),
            force_refresh_group_cache=bool(self.force_refresh_group),
            expected_speakers=int(self.expected_speakers),
            dialogue_coverage_mode=self.dialogue_coverage_mode,
            cancellation_token=cancellation_token,
            studio_project_path=str(self.studio_project_path or ""),
            recognition_purpose=self.recognition_purpose,
            recognition_snapshot=json.loads(self.recognition_snapshot_json) if self.recognition_snapshot_json else {},
            speaker_source=__import__('twobyteasr.speaker_strategy', fromlist=['resolve']).resolve(
                json.loads(self.settings_snapshot_json) if self.settings_snapshot_json else getattr(legacy, 'RUNTIME_SETTINGS', {})),
            requested_language=self.recognition_language,
            subtitle_output=self.subtitle_output,
            translation_script=self.translation_script,
        )

    def apply(
        self,
        legacy: Any,
        runtime_context: RuntimeContext | None = None,
    ) -> RuntimeContext:
        context = runtime_context or self.create_runtime_context(legacy)
        configured = self.create_runtime_context(
            legacy,
            cancellation_token=context.cancellation_token,
            _glossary_snapshot=context.glossary_snapshot,
        )
        context.game_name = configured.game_name
        context.enable_domain_terms = configured.enable_domain_terms
        context.enable_term_search = configured.enable_term_search
        context.enabled_glossary_ids = list(configured.enabled_glossary_ids)
        # apply() is also used with an already created context: never reload
        # task contents after its first snapshot was fixed.
        if context.glossary_snapshot is None or not configured.enable_domain_terms:
            context.glossary_snapshot = configured.glossary_snapshot
        context.enabled_glossary_ids = [x.id for x in context.glossary_snapshot.libraries]
        context.discovered_terms.clear()
        context.output_review_track = configured.output_review_track
        context.output_jianying_txt = configured.output_jianying_txt
        context.output_speaker_tracks = configured.output_speaker_tracks
        context.force_refresh_api_cache = configured.force_refresh_api_cache
        context.force_refresh_polish_cache = configured.force_refresh_polish_cache
        context.force_refresh_group_cache = configured.force_refresh_group_cache
        context.expected_speakers = configured.expected_speakers
        context.dialogue_coverage_mode = configured.dialogue_coverage_mode
        context.studio_project_path = configured.studio_project_path
        context.recognition_purpose = configured.recognition_purpose
        context.recognition_snapshot = configured.recognition_snapshot
        context.speaker_source = configured.speaker_source
        context.requested_language = configured.requested_language
        context.subtitle_output = configured.subtitle_output
        context.translation_script = configured.translation_script
        context.event_log_path = ""
        context.review_items.clear()
        sync_legacy_runtime(legacy, context)
        return context


@dataclass(frozen=True)
class PipelineEvent:
    kind: str
    timestamp: str
    media_path: str = ""
    media_index: int = 0
    media_total: int = 0
    stage_index: int = 0
    stage_total: int = 0
    label: str = ""
    resource: str = ""
    elapsed_seconds: float = 0.0
    message: str = ""
    output_path: str = ""
    error: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    job_id: str = ""


@dataclass(frozen=True)
class MediaResult:
    media_path: str
    status: str
    txt_path: str = ""
    srt_path: str = ""
    speaker_paths: tuple[str, ...] = ()
    review_path: str = ""
    report_json_path: str = ""
    report_text_path: str = ""
    project_path: str = ""
    elapsed_seconds: float = 0.0
    error: str = ""
    job_id: str = ""
    project_id: str = ""
    result_revision: str = ""
    media_fingerprint: str = ""
    result_ref_json: str = ""


@dataclass(frozen=True)
class QueueResult:
    results: tuple[MediaResult, ...]
    elapsed_seconds: float
    log_path: str = ""
    job_id: str = ""

    @property
    def successes(self) -> tuple[MediaResult, ...]:
        return tuple(
            item for item in self.results
            if item.status in {"success", "degraded_success"}
        )

    @property
    def failures(self) -> tuple[MediaResult, ...]:
        return tuple(item for item in self.results if item.status == "failed")

    @property
    def cancelled(self) -> tuple[MediaResult, ...]:
        return tuple(item for item in self.results if item.status == "cancelled")

    @property
    def skipped(self) -> tuple[MediaResult, ...]:
        return tuple(item for item in self.results if item.status == "skipped")

    @property
    def exit_code(self) -> int:
        if self.failures:
            return 1
        return 2 if self.cancelled else 0

    def legacy_successes(self) -> list[tuple[str, str, str]]:
        return [(item.media_path, item.txt_path, item.srt_path) for item in self.successes]

    def legacy_failures(self) -> list[tuple[str, str]]:
        return [(item.media_path, item.error) for item in (*self.failures, *self.cancelled)]


def _event_from_payload(kind: str, payload: dict[str, Any], state: dict[str, Any]) -> PipelineEvent:
    output_path = str(payload.get("path") or payload.get("output_path") or "")
    return PipelineEvent(
        kind=str(kind),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        media_path=str(payload.get("media_path") or state.get("media_path") or ""),
        media_index=int(payload.get("media_index") or state.get("media_index") or 0),
        media_total=int(payload.get("media_total") or state.get("media_total") or 0),
        stage_index=int(payload.get("index") or payload.get("stage_index") or 0),
        stage_total=int(payload.get("total") or payload.get("stage_total") or 0),
        label=str(payload.get("label") or ""),
        resource=str(payload.get("resource") or ""),
        elapsed_seconds=float(payload.get("elapsed_seconds") or 0.0),
        message=str(payload.get("message") or ""),
        output_path=output_path,
        error=str(payload.get("error") or ""),
        payload=dict(payload),
        job_id=str(payload.get("job_id") or state.get("job_id") or ""),
    )


def _existing_output(legacy: Any, media_path: str) -> bool:
    from .studio_project import canonical_project_path
    return canonical_project_path(media_path).is_file()


def _exception_message(exc: BaseException, fallback: str) -> str:
    message = " ".join(str(exc).split())
    return message or f"{fallback}（{exc.__class__.__name__}）"


def _result_output_details(media_path: str, srt_path: str, review_enabled: bool) -> tuple[tuple[str, ...], str]:
    if not srt_path:
        return (), ""
    base, extension = os.path.splitext(srt_path)
    speaker_paths = tuple(sorted(glob.glob(f"{glob.escape(base)}_主播*_*{glob.escape(extension)}")))
    review_path = ""
    if review_enabled:
        project_root = Path(__file__).resolve().parents[1]
        candidate = project_root / "review_tracks" / f"{Path(base).name}_疑似吞字幕复核{extension}"
        if candidate.is_file():
            review_path = str(candidate)
    return speaker_paths, review_path


def run_media_queue(
    media_paths: list[str] | tuple[str, ...],
    options: RunOptions | None = None,
    event_sink: EventSink | None = None,
    cancel_token: CancellationToken | None = None,
    *,
    _legacy: Any | None = None,
    _pipeline: Any | None = None,
    _startup_self_test: dict[str, Any] | None = None,
    _skip_environment_preflight: bool = False,
) -> QueueResult:
    """Run a media queue without opening UI dialogs or exiting the process.

    ``_skip_environment_preflight`` is an explicit opt-out for tests and
    legacy callers without a managed venv layout; production paths keep the
    environment correctness gate enabled (Phase B).
    """

    if _legacy is None:
        import subtitle_core as _legacy
    if _pipeline is None:
        import moss_firered_pipeline as _pipeline

    legacy = _legacy
    pipeline = _pipeline
    token = cancel_token or CancellationToken()
    run_options = options or RunOptions.from_legacy(legacy)
    runtime_context = run_options.create_runtime_context(
        legacy,
        cancellation_token=token,
    )
    runtime_context.identity_task_active = True
    runtime_scope = activate_runtime_context(runtime_context, legacy=legacy)
    runtime_scope.__enter__()
    try:
        # Acquire ownership before mirroring task settings into legacy globals.
        # A rejected concurrent queue must not overwrite the active review.
        run_options.apply(legacy, runtime_context)
    except BaseException:
        runtime_scope.__exit__(*sys.exc_info())
        raise
    try:
        process_media_supports_context = "runtime_context" in inspect.signature(
            pipeline.process_media
        ).parameters
    except (TypeError, ValueError):
        process_media_supports_context = False
    normalized_paths = [os.path.abspath(os.fspath(path)) for path in media_paths]
    state: dict[str, Any] = {"media_path": "", "media_index": 0, "media_total": len(normalized_paths), "job_id": runtime_context.job_id}

    def forward_event(kind: str, payload: dict[str, Any]) -> None:
        if event_sink is None:
            return
        event_sink(_event_from_payload(kind, payload, state))

    results: list[MediaResult] = []
    durations: list[float] = []
    queue_started = time.perf_counter()
    log_path = ""
    local_asr_session_started = False
    persistent_model_session = bool(str(run_options.studio_project_path or ""))
    try:
        pipeline.set_cancellation_token(token)
        with legacy.run_event_observer(forward_event):
            startup_self_test = _startup_self_test or legacy.run_startup_self_test()
            log_path = legacy.begin_run_event_log()
            print(f"[运行日志] {log_path}")
            legacy.record_run_event(
                "queue_configured",
                media_count=len(normalized_paths),
                runtime_profile=legacy.runtime_content_profile_signature(),
                pipeline_build=getattr(pipeline, "PIPELINE_BUILD_ID", ""),
                pipeline_path=os.path.realpath(getattr(pipeline, "__file__", "")),
                core_build=getattr(legacy, "PIPELINE_BUILD_ID", ""),
                core_path=os.path.realpath(getattr(legacy, "__file__", "")),
                startup_self_test=startup_self_test,
                runtime_settings=legacy.runtime_settings_snapshot(),
            )
            legacy.record_run_event("terminology_snapshot_loaded", job_id=runtime_context.job_id,
                **runtime_context.glossary_snapshot.summary())
            if legacy.HF_TOKEN:
                os.environ["HF_TOKEN"] = legacy.HF_TOKEN
                os.environ["HUGGINGFACE_HUB_TOKEN"] = legacy.HF_TOKEN

            try:
                token.raise_if_cancelled()
                runtime_settings = (json.loads(run_options.settings_snapshot_json)
                    if run_options.settings_snapshot_json else getattr(legacy, "RUNTIME_SETTINGS", None))
                if isinstance(runtime_settings, dict):
                    import copy
                    runtime_settings=copy.deepcopy(runtime_settings)
                    from .speaker_strategy import resolve
                    runtime_context.speaker_source = resolve(runtime_settings)
                    runtime_settings.setdefault('models', {})['speaker_source'] = runtime_context.speaker_source
                    runtime_context.asr_settings_snapshot=runtime_settings
                    from .llm_config import qwen_asr_endpoint_from_settings
                    runtime_context.asr_endpoint_snapshot=qwen_asr_endpoint_from_settings(runtime_settings)
                    runtime_context.asr_endpoint_snapshot['speaker_source']=runtime_context.speaker_source
                    from .speaker_strategy import execution_plan
                    speaker_plan=execution_plan(runtime_settings,runtime_context.speaker_source)
                    legacy.record_run_event('speaker_plan',job_id=runtime_context.job_id,
                        speaker_source=speaker_plan.source,steps=list(speaker_plan.steps),state='planned')
                    if runtime_settings.get('models',{}).get('primary_asr_backend')=='api':
                        from .cloud_asr_jobs import validate_speaker_strategy
                        validate_speaker_strategy(runtime_context.asr_endpoint_snapshot)
                    from .recognition_plan import bind_text_ai_snapshots
                    text_plan = bind_text_ai_snapshots(runtime_context, runtime_settings)
                    legacy.record_run_event('text_ai_plan', enabled=list(text_plan.roles),
                        disabled=[r for r in ('polish', 'group') if r not in text_plan.roles])
                    for role, snapshot in runtime_context.provider_snapshots.items():
                        legacy.record_run_event("asr_provider_snapshot", job_id=runtime_context.job_id,
                            stage=role,
                            **snapshot.public_identity())
                    group_identity = (f"{runtime_context.provider_snapshot.provider} / {runtime_context.provider_snapshot.model}"
                        if runtime_context.provider_snapshot is not None else "本地规则（AI 未启用）")
                    source_label='主转写原生结果'
                    print(f"[任务配置] 实际断句模型：{group_identity}；身份来源：{source_label}", flush=True)
                # Phase B：运行环境 preflight correctness gate——坏的 Main/MOSS
                # 环境必须在真正启动 ASR/MOSS worker/FireRed pipeline 之前
                # 被拒绝（UI 按钮检查只是更好展示，不是唯一保护）。
                if not _skip_environment_preflight:
                    runtime_settings = runtime_context.asr_settings_snapshot
                    if isinstance(runtime_settings, dict):
                        from twobyteasr.environment import ensure_environment_ready

                        ensure_environment_ready(runtime_settings)
                pipeline.check_runtime(legacy)
                if runtime_context.recognition_snapshot:
                    from .recognition_input import prepare_recognition_input
                    from .media_service import GLOBAL_MEDIA_SERVICE
                    snapshot = runtime_context.recognition_snapshot
                    from .recognition_result import media_identity_for_task, digest_payload
                    # Source hashes are computed by this worker once per job;
                    # mapping/range/audio graph stay part of the input identity.
                    for source, source_identity in snapshot["sources"].items():
                        current = media_identity_for_task(source, runtime_context)
                        if (current["size"], current["mtime_ns"]) != (source_identity["size"], source_identity["mtime_ns"]):
                            raise RuntimeError(f"识别启动后素材已改变：{source}")
                        source_identity["sha256"] = current["sha256"]
                    snapshot["fingerprint"] = digest_payload({k: snapshot[k] for k in
                        ("version", "duration_ms", "audio_graph", "sequence", "sources")})
                    legacy.record_run_event("timeline_input_preparing", fingerprint=snapshot["fingerprint"],
                                            duration_ms=snapshot["duration_ms"])
                    prepared = prepare_recognition_input(snapshot, legacy.CACHE_ROOT, GLOBAL_MEDIA_SERVICE.ffmpeg_path, token=token)
                    normalized_paths = [prepared]
                    result_root = Path(run_options.studio_project_path).parent / "recognition-results" / runtime_context.job_id
                    runtime_context.studio_project_path = str(result_root / "识别结果.2byteproj")
                    legacy.record_run_event("timeline_input_ready", input_path=prepared,
                        fingerprint=snapshot["fingerprint"], duration_ms=snapshot["duration_ms"],
                        time_domain="timeline", audio_graph=snapshot["audio_graph"])
                from .recognition_result import media_identity_for_task
                for path in normalized_paths:
                    media_identity_for_task(path, runtime_context)
                legacy.cleanup_old_cache()
                token.raise_if_cancelled()
                try:
                    pipeline.precompute_moss_batch_cache(normalized_paths, legacy)
                except CancelledError:
                    raise
                except KeyboardInterrupt:
                    token.cancel()
                    raise CancelledError("MOSS 预计算已取消。")
                except Exception as exc:
                    print(f"   [警告] MOSS 批量预计算未完成，改为逐文件继续：{exc}")
                    legacy.record_run_event("moss_batch_fallback", error=str(exc))
                if len(normalized_paths) > 1 or persistent_model_session:
                    begin_model_session = getattr(legacy, "begin_local_asr_session", None)
                    if callable(begin_model_session):
                        try:
                            begin_model_session(persistent=persistent_model_session)
                        except TypeError:
                            # Compatibility facades and external embedders may
                            # still expose the former no-argument hook.
                            begin_model_session()
                        local_asr_session_started = True
                        legacy.record_run_event(
                            "local_asr_session_started",
                            media_count=len(normalized_paths),
                            models=["qwen3-asr"],
                            persistent=persistent_model_session,
                        )
            except CancelledError as exc:
                for path in normalized_paths:
                    results.append(MediaResult(path, "cancelled", error=str(exc)))
                legacy.record_run_event("queue_cancelled", error=str(exc))
                return QueueResult(tuple(replace(r, job_id=runtime_context.job_id) for r in results), time.perf_counter() - queue_started, log_path, runtime_context.job_id)
            except Exception as exc:
                error = _exception_message(exc, "运行环境检查失败")
                for path in normalized_paths:
                    results.append(MediaResult(path, "failed", error=error))
                legacy.record_run_event("queue_failed", error=error)
                return QueueResult(tuple(replace(r, job_id=runtime_context.job_id) for r in results), time.perf_counter() - queue_started, log_path, runtime_context.job_id)

            for index, media_path in enumerate(normalized_paths, 1):
                state.update(media_path=media_path, media_index=index)
                runtime_context.media_path = media_path
                runtime_context.media_index = index
                if token.is_cancelled:
                    results.extend(
                        MediaResult(path, "cancelled", error="队列已取消。")
                        for path in normalized_paths[index - 1 :]
                    )
                    break

                if _existing_output(legacy, media_path):
                    if run_options.overwrite_policy == "skip":
                        result = MediaResult(media_path, "skipped", error="已存在字幕结果。")
                        results.append(result)
                        legacy.record_run_event("media_skipped", media_path=media_path, reason=result.error)
                        continue
                    if run_options.overwrite_policy == "error":
                        result = MediaResult(media_path, "failed", error="已存在字幕结果，覆盖策略为 error。")
                        results.append(result)
                        legacy.record_run_event("media_failed", media_path=media_path, error=result.error)
                        continue

                legacy.record_run_event(
                    "media_started",
                    media_path=media_path,
                    media_index=index,
                    media_total=len(normalized_paths),
                )
                file_started = time.perf_counter()
                try:
                    token.raise_if_cancelled()
                    from .recognition_result import media_identity_for_task, recognition_project_path
                    runtime_context.media_identity = media_identity_for_task(media_path, runtime_context)
                    if runtime_context.recognition_snapshot:
                        runtime_context.media_identity["fingerprint"] = runtime_context.recognition_snapshot["fingerprint"]
                    elif not run_options.studio_project_path:
                        runtime_context.studio_project_path = str(recognition_project_path(media_path, runtime_context.job_id, media_index=index))
                    runtime_context.committed_result_ref.clear()
                    sync_legacy_runtime(legacy, runtime_context)
                    process_kwargs = (
                        {"runtime_context": runtime_context}
                        if process_media_supports_context
                        else {}
                    )
                    txt_path, srt_path, elapsed = pipeline.process_media(
                        media_path,
                        index,
                        len(normalized_paths),
                        legacy,
                        **process_kwargs,
                    )
                    token.raise_if_cancelled()
                    report_json, report_text = legacy.task_reporting.report_paths_for_media(media_path)
                    speaker_paths, review_path = _result_output_details(
                        media_path, srt_path, run_options.output_review_track
                    )
                    media_status = "success"
                    report_payload = {}
                    if os.path.isfile(report_json):
                        try:
                            report_payload = json.loads(
                                Path(report_json).read_text(encoding="utf-8")
                            )
                            reported_status = str(report_payload.get("status") or "")
                            if reported_status in {"success", "degraded_success"}:
                                media_status = reported_status
                        except (OSError, ValueError, TypeError):
                            pass
                    outputs = report_payload.get('result',{}).get('outputs',{}) or report_payload.get('outputs',{})
                    project_error = str(outputs.get('project_error') or '')
                    reference = dict(runtime_context.committed_result_ref or {})
                    # Only the pipeline's validated atomic commit is publishable.
                    # A historical report or an old basename path is no fallback.
                    if reference:
                        from .recognition_result import verify_result_reference
                        verify_result_reference(reference)
                        if reference["job_id"] != runtime_context.job_id:
                            raise RuntimeError("工程交付的任务 ID 与当前任务不一致。")

                    result = MediaResult(
                        media_path=str(runtime_context.recognition_snapshot.get("project", {}).get("media", {}).get("path") or media_path),
                        status=media_status,
                        txt_path=txt_path,
                        srt_path=srt_path,
                        speaker_paths=speaker_paths,
                        review_path=review_path,
                        report_json_path=report_json if os.path.isfile(report_json) else "",
                        report_text_path=report_text if os.path.isfile(report_text) else "",
                        project_path=str(reference.get("path") or "") if not project_error else "",
                        error=('工程交付失败，字幕输出已保存，可从结果页恢复：'+project_error) if project_error else str(runtime_context.speaker_recovery.get('processing', {}).get('error', '')),
                        elapsed_seconds=float(elapsed),
                        job_id=runtime_context.job_id,
                        project_id=str(reference.get("project_id") or ""),
                        result_revision=str(reference.get("result_revision") or ""),
                        media_fingerprint=str(reference.get("media_fingerprint") or runtime_context.media_identity.get("fingerprint") or ""),
                        result_ref_json=json.dumps(reference, ensure_ascii=False) if reference else "",
                    )
                    results.append(result)
                    durations.append(float(elapsed))
                    legacy.record_run_event(
                        "media_completed",
                        media_path=media_path,
                        elapsed_seconds=round(float(elapsed), 3),
                        txt_path=txt_path,
                        srt_path=srt_path,
                    )
                except CancelledError as exc:
                    elapsed = time.perf_counter() - file_started
                    legacy.finish_media_report("cancelled", elapsed_seconds=round(elapsed, 3), error=str(exc))
                    results.append(MediaResult(media_path, "cancelled", elapsed_seconds=elapsed, error=str(exc)))
                    token.cancel()
                    legacy.record_run_event("media_cancelled", media_path=media_path, error=str(exc))
                except KeyboardInterrupt:
                    elapsed = time.perf_counter() - file_started
                    token.cancel()
                    error = "用户取消了任务。"
                    legacy.finish_media_report("cancelled", elapsed_seconds=round(elapsed, 3), error=error)
                    results.append(MediaResult(media_path, "cancelled", elapsed_seconds=elapsed, error=error))
                    legacy.record_run_event("media_cancelled", media_path=media_path, error=error)
                except Exception as exc:
                    elapsed = time.perf_counter() - file_started
                    durations.append(elapsed)
                    error = _exception_message(exc, "字幕处理失败")
                    legacy.finish_media_report("failed", elapsed_seconds=round(elapsed, 3), error=error)
                    results.append(MediaResult(media_path, "failed", elapsed_seconds=elapsed, error=error))
                    print(f"\n[文件失败] {os.path.basename(media_path)}：{error}")
                    legacy.record_run_event(
                        "media_failed",
                        media_path=media_path,
                        error=error,
                        traceback=__import__("traceback").format_exc(),
                    )

                if token.is_cancelled:
                    results.extend(
                        MediaResult(path, "cancelled", error="队列已取消。")
                        for path in normalized_paths[index:]
                    )
                    break
                remaining = len(normalized_paths) - index
                if remaining and durations:
                    average = sum(durations) / len(durations)
                    print(
                        f"\n[队列进度] 已完成 {index}/{len(normalized_paths)}，"
                        f"预计剩余 {legacy.format_elapsed(average * remaining)}。"
                    )

            total_elapsed = time.perf_counter() - queue_started
            legacy.record_run_event(
                "run_completed",
                success_count=sum(item.status in {"success", "degraded_success"} for item in results),
                degraded_count=sum(item.status == "degraded_success" for item in results),
                failure_count=sum(item.status == "failed" for item in results),
                cancelled_count=sum(item.status == "cancelled" for item in results),
                skipped_count=sum(item.status == "skipped" for item in results),
                elapsed_seconds=round(total_elapsed, 3),
            )
            session_state = getattr(legacy, "local_asr_session_state", None)
            if callable(session_state):
                legacy.record_run_event(
                    "local_asr_session_state",
                    **session_state(),
                )
            return QueueResult(tuple(replace(r, job_id=runtime_context.job_id) for r in results), total_elapsed, log_path, runtime_context.job_id)
    finally:
        end_event_log = getattr(legacy, "end_run_event_log", None)
        if callable(end_event_log):
            end_event_log()
        if local_asr_session_started and not persistent_model_session:
            end_model_session = getattr(legacy, "end_local_asr_session", None)
            if callable(end_model_session):
                end_model_session()
        runtime_context.cancellation_token = None
        try:
            pipeline.set_cancellation_token(None)
        finally:
            runtime_scope.__exit__(None, None, None)
