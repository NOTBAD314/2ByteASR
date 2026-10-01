"""Per-queue mutable runtime state shared by pipeline stages.

The application currently runs one media queue at a time.  A queue owns one
``RuntimeContext`` instance; worker threads read the same object, so changing a
runtime option never relies on values copied by ``from subtitle_core import *``.
Legacy module attributes are mirrored while old entry points are still kept.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class RuntimeContext:
    game_name: str = ""
    enable_domain_terms: bool = False
    enabled_glossary_ids: list[str] = field(default_factory=list)
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
    speaker_source: str = "single"
    asr_provisional_cues: list[dict[str, Any]] = field(default_factory=list)
    asr_manifest_key: str = ""
    speaker_recovery: dict[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    provider_snapshot: Any | None = None
    provider_snapshots: dict[str, Any] = field(default_factory=dict)
    # Task-private audio-ASR credential snapshot; never persisted to projects.
    asr_endpoint_snapshot: dict[str, Any] = field(default_factory=dict,repr=False)
    asr_settings_snapshot: dict[str, Any] = field(default_factory=dict,repr=False)
    terminology_status: dict[str, Any] = field(default_factory=dict)
    polishing_summary: dict[str, Any] = field(default_factory=dict)

    def reset_for_media(self) -> None:
        """Clear output/report state while retaining queue-wide discovered terms."""
        self.review_items.clear()
        self.asr_provisional_cues.clear()
        self.asr_manifest_key = ""
        self.speaker_recovery.clear()
        self.terminology_status.clear()
        self.polishing_summary.clear()


_CONTEXT_LOCK = threading.RLock()
_ACTIVE_CONTEXT = RuntimeContext()


def get_runtime_context() -> RuntimeContext:
    """Return the context active for the current queue and its worker threads."""
    with _CONTEXT_LOCK:
        return _ACTIVE_CONTEXT


def runtime_context_from_legacy(legacy: Any) -> RuntimeContext:
    """Build a context from compatibility attributes without retaining them."""
    return RuntimeContext(
        game_name=str(getattr(legacy, "RUNTIME_GAME_NAME", "") or ""),
        enable_domain_terms=bool(getattr(legacy, "RUNTIME_ENABLE_DOMAIN_TERMS", False)),
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
    with _CONTEXT_LOCK:
        previous = _ACTIVE_CONTEXT
        _ACTIVE_CONTEXT = context
        if legacy is not None:
            sync_legacy_runtime(legacy, context)
    try:
        yield context
    finally:
        with _CONTEXT_LOCK:
            _ACTIVE_CONTEXT = previous
            if legacy is not None:
                sync_legacy_runtime(legacy, previous)


__all__ = [
    "RuntimeContext",
    "activate_runtime_context",
    "get_runtime_context",
    "runtime_context_from_legacy",
    "sync_legacy_runtime",
]
