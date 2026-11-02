"""Per-queue mutable runtime state shared by pipeline stages.

(Named ``twobyteasr/runtime.py`` before 2026-10-15; "runtime" also meant
Python environments, paths, caches and traces, so the file was renamed.)

The application currently runs one media queue at a time.  A queue owns one
``RuntimeContext`` instance; worker threads read the same object, so changing a
runtime option never relies on values copied by ``from subtitle_core import *``.
Legacy module attributes are mirrored while old entry points are still kept.
"""

from __future__ import annotations

import threading
import uuid
import contextvars
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class RuntimeContext:
    game_name: str = ""
    enable_domain_terms: bool = False
    enabled_glossary_ids: list[str] = field(default_factory=list)
    # Immutable content, stable IDs and revisions, owned by this queue.
    glossary_snapshot: Any | None = None
    discovered_terms: set[str] = field(default_factory=set)
    output_review_track: bool = False
    output_jianying_txt: bool = False
    output_speaker_tracks: bool = False
    force_refresh_api_cache: bool = False
    force_refresh_polish_cache: bool = False
    force_refresh_group_cache: bool = False
    expected_speakers: int = 0
    dialogue_coverage_mode: str = "all_dialogue"
    cancellation_token: Any | None = None
    event_log_path: str = ""
    review_items: list[dict[str, Any]] = field(default_factory=list)
    studio_project_path: str = ""
    recognition_purpose: str = "final"
    recognition_snapshot: dict[str, Any] = field(default_factory=dict)
    # 2026-10-24: the audio stream a home-page run of a multi-track file
    # recognizes for the current media (``audio_stream_choice``); {} = as before.
    audio_stream: dict[str, Any] = field(default_factory=dict)
    speaker_source: str = "single"
    asr_provisional_cues: list[dict[str, Any]] = field(default_factory=list)
    asr_manifest_key: str = ""
    speaker_recovery: dict[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    media_path: str = ""
    media_index: int = 1
    media_identity: dict[str, Any] = field(default_factory=dict)
    media_identities: dict[Any, dict[str, Any]] = field(default_factory=dict, repr=False)
    media_identity_lock: Any = field(default_factory=threading.RLock, repr=False)
    committed_result_ref: dict[str, Any] = field(default_factory=dict)
    identity_task_active: bool = False
    provider_snapshot: Any | None = None
    provider_snapshots: dict[str, Any] = field(default_factory=dict)
    # Task-private audio-ASR credential snapshot; never persisted to projects.
    asr_endpoint_snapshot: dict[str, Any] = field(default_factory=dict,repr=False)
    asr_settings_snapshot: dict[str, Any] = field(default_factory=dict,repr=False)
    terminology_status: dict[str, Any] = field(default_factory=dict)
    polishing_summary: dict[str, Any] = field(default_factory=dict)
    # Local glossaries never imply permission to perform optional web searches.
    enable_term_search: bool = False
    # Recognition language: the user's request (auto/zh/ja), the language the
    # task actually runs with once the primary transcript is known, and why.
    requested_language: str = "auto"
    task_language: str = ""
    language_evidence: dict[str, Any] = field(default_factory=dict)
    language_mode: str = 'auto'
    language_decision: dict[str, Any] = field(default_factory=dict)
    transcript_acceptance: dict[str, Any] = field(default_factory=dict)
    language_recovery_result: Any | None = field(default=None, repr=False)
    # Requested subtitle output (original/translation/bilingual) and translation
    # target (zh-Hans / zh-Hant / en / ja / ko; the name predates non-Chinese targets).
    subtitle_output: str = "original"
    translation_script: str = "zh-Hans"
    # Script of Chinese subtitles: zh-Hans, or zh-Hant (converted before the
    # project is written, subtitle_rules.chinese_script; 2026-10-19).
    chinese_script: str = "zh-Hans"
    # Japanese bunsetsu boundaries of this task's segment texts (line breaking).
    japanese_phrases: Any | None = None
    # Task-private first-pass alignment receipt; never written to settings.
    segment_alignment_evidence: Any | None = field(default=None, repr=False)
    alignment_audio_inputs: dict[Any, str] = field(default_factory=dict, repr=False)
    alignment_checkpoint_dir: str = ''
    aligner_sessions: dict[Any, Any] = field(default_factory=dict, repr=False)
    shard_id: str = ''
    primary_ready_callback: Any | None = field(default=None, repr=False)
    long_pipeline: Any | None = field(default=None, repr=False)
    root_context: Any | None = field(default=None, repr=False)
    execution_budget: Any | None = field(default=None, repr=False)
    provider_quota_rejections: dict[str,str] = field(default_factory=dict,repr=False)
    translation_ready: Any | None = field(default=None, repr=False)
    streaming_preparation: Any | None = field(default=None, repr=False)
    early_primary: Any | None = field(default=None, repr=False)
    input_session: Any | None = field(default=None, repr=False)
    shard_input_version: str = ''
    shard_bounds: tuple[float,float] | None = None

    def __post_init__(self):
        from .language_decision import initialise
        initialise(self)

    def reset_for_media(self) -> None:
        """Clear output/report state while retaining queue-wide discovered terms."""
        self.close_resources()
        self.review_items.clear()
        self.asr_provisional_cues.clear()
        self.asr_manifest_key = ""
        self.speaker_recovery.clear()
        self.terminology_status.clear()
        self.polishing_summary.clear()
        self.committed_result_ref.clear()
        self.task_language = ""
        self.language_evidence = {}
        from .language_decision import initialise
        initialise(self)
        self.transcript_acceptance = {}
        self.language_recovery_result = None
        self.japanese_phrases = None
        self.segment_alignment_evidence = None
        self.alignment_audio_inputs.clear()
        self.alignment_checkpoint_dir = ''

    def close_resources(self):
        if self.long_pipeline is not None:
            pipeline, self.long_pipeline = self.long_pipeline, None
            pipeline.close()
        if self.early_primary is not None:
            pool,future=self.early_primary
            self.early_primary=None
            pool.shutdown(wait=True,cancel_futures=True)
        if self.input_session is not None:
            session,self.input_session=self.input_session,None
            session.close()
        with self.media_identity_lock:
            sessions = list(self.aligner_sessions.values())
            self.aligner_sessions.clear()
        for session in sessions:
            session.close()
        if self.streaming_preparation is not None:
            producer,self.streaming_preparation=self.streaming_preparation,None
            producer.close()


_CONTEXT_LOCK = threading.RLock()
_OPERATION_LOCK = threading.RLock()
_ACTIVE_CONTEXT = RuntimeContext()
_LOCAL_CONTEXT = contextvars.ContextVar('2byteasr_local_stage_context', default=None)


def get_runtime_context() -> RuntimeContext:
    """Return the context active for the current queue and its worker threads."""
    local = _LOCAL_CONTEXT.get()
    if local is not None:
        return local
    with _CONTEXT_LOCK:
        return _ACTIVE_CONTEXT


def context_is_current(context):
    with _CONTEXT_LOCK:
        root = getattr(context, 'root_context', None)
        return root is None or _ACTIVE_CONTEXT is root


@contextmanager
def local_runtime_context(context):
    """A shard's local outputs/settings; queue ownership stays with its root."""
    token = _LOCAL_CONTEXT.set(context)
    try:
        if not context_is_current(context):
            from .service import CancelledError
            raise CancelledError('分片所属的识别任务已结束。')
        yield context
    finally:
        _LOCAL_CONTEXT.reset(token)


class ContextExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        captured = contextvars.copy_context()
        return super().submit(captured.run, fn, *args, **kwargs)


def bounded_results(pool, runner, jobs, *, limit):
    """Completion-order consumption without queueing the entire corpus."""
    jobs, pending, exhausted = iter(jobs), set(), False
    while pending or not exhausted:
        while len(pending) < max(1, limit) and not exhausted:
            job = next(jobs, None)
            if job is None:
                exhausted = True
            else:
                pending.add(pool.submit(runner, job))
        if pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                yield future.result()


def runtime_context_from_legacy(legacy: Any) -> RuntimeContext:
    """Build a context from compatibility attributes without retaining them."""
    return RuntimeContext(
        game_name=str(getattr(legacy, "RUNTIME_GAME_NAME", "") or ""),
        enable_domain_terms=bool(getattr(legacy, "RUNTIME_ENABLE_DOMAIN_TERMS", False)),
        enable_term_search=bool(getattr(legacy, "RUNTIME_ENABLE_TERM_SEARCH", False)),
        enabled_glossary_ids=list(
            getattr(legacy, "RUNTIME_ENABLED_GLOSSARY_IDS", ()) or ()
        ),
        discovered_terms=set(getattr(legacy, "RUNTIME_DISCOVERED_TERMS", set()) or ()),
        output_review_track=bool(getattr(legacy, "RUNTIME_OUTPUT_REVIEW_TRACK", False)),
        output_jianying_txt=bool(getattr(legacy, "RUNTIME_OUTPUT_JIANYING_TXT", False)),
        output_speaker_tracks=bool(getattr(legacy, "RUNTIME_OUTPUT_SPEAKER_TRACKS", False)),
        force_refresh_api_cache=bool(
            getattr(legacy, "RUNTIME_FORCE_REFRESH_API_CACHE", False)
        ),
        force_refresh_polish_cache=bool(
            getattr(legacy, "RUNTIME_FORCE_REFRESH_POLISH_CACHE", False)
        ),
        force_refresh_group_cache=bool(
            getattr(legacy, "RUNTIME_FORCE_REFRESH_GROUP_CACHE", False)
        ),
        expected_speakers=int(getattr(legacy, "RUNTIME_EXPECTED_SPEAKERS", 0) or 0),
        dialogue_coverage_mode=str(
            getattr(legacy, "RUNTIME_DIALOGUE_COVERAGE_MODE", "all_dialogue")
            or "all_dialogue"
        ),
        cancellation_token=getattr(legacy, "RUNTIME_CANCELLATION_TOKEN", None),
        event_log_path=str(getattr(legacy, "RUN_EVENT_LOG_PATH", "") or ""),
        review_items=list(getattr(legacy, "RUN_REVIEW_ITEMS", ()) or ()),
        studio_project_path=str(getattr(legacy, "RUNTIME_STUDIO_PROJECT_PATH", "") or ""),
        recognition_purpose=str(getattr(legacy, "RUNTIME_RECOGNITION_PURPOSE", "final") or "final"),
    )


def sync_legacy_runtime(legacy: Any, context: RuntimeContext) -> None:
    """Mirror the active context for callers that still use the old attributes."""
    legacy.RUNTIME_GAME_NAME = context.game_name
    legacy.RUNTIME_ENABLE_DOMAIN_TERMS = context.enable_domain_terms
    legacy.RUNTIME_ENABLE_TERM_SEARCH = context.enable_term_search
    legacy.RUNTIME_ENABLED_GLOSSARY_IDS = list(context.enabled_glossary_ids)
    legacy.RUNTIME_DISCOVERED_TERMS = context.discovered_terms
    legacy.RUNTIME_OUTPUT_REVIEW_TRACK = context.output_review_track
    legacy.RUNTIME_OUTPUT_JIANYING_TXT = context.output_jianying_txt
    legacy.RUNTIME_OUTPUT_SPEAKER_TRACKS = context.output_speaker_tracks
    legacy.RUNTIME_STUDIO_PROJECT_PATH = context.studio_project_path
    legacy.RUNTIME_RECOGNITION_PURPOSE = context.recognition_purpose
    legacy.RUNTIME_FORCE_REFRESH_API_CACHE = context.force_refresh_api_cache
    legacy.RUNTIME_FORCE_REFRESH_POLISH_CACHE = context.force_refresh_polish_cache
    legacy.RUNTIME_FORCE_REFRESH_GROUP_CACHE = context.force_refresh_group_cache
    legacy.RUNTIME_EXPECTED_SPEAKERS = context.expected_speakers
    legacy.RUNTIME_DIALOGUE_COVERAGE_MODE = context.dialogue_coverage_mode
    legacy.RUNTIME_CANCELLATION_TOKEN = context.cancellation_token
    legacy.RUN_EVENT_LOG_PATH = context.event_log_path
    legacy.RUN_REVIEW_ITEMS = context.review_items


@contextmanager
def activate_runtime_context(
    context: RuntimeContext,
    *,
    legacy: Any | None = None,
) -> Iterator[RuntimeContext]:
    """Activate a queue context and restore the previous one on every exit path."""
    global _ACTIVE_CONTEXT
    if not _OPERATION_LOCK.acquire(blocking=False):
        raise RuntimeError("已有识别或校对任务运行中，请待其结束后重试。")
    with _CONTEXT_LOCK:
        previous = _ACTIVE_CONTEXT
        _ACTIVE_CONTEXT = context
        if legacy is not None:
            sync_legacy_runtime(legacy, context)
    try:
        yield context
    finally:
        try:
            context.close_resources()
        finally:
            with _CONTEXT_LOCK:
                _ACTIVE_CONTEXT = previous
                if legacy is not None:
                    sync_legacy_runtime(legacy, previous)
            _OPERATION_LOCK.release()


__all__ = [
    "RuntimeContext",
    "activate_runtime_context",
    "get_runtime_context",
    "runtime_context_from_legacy",
    "sync_legacy_runtime",
]
