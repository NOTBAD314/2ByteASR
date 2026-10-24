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

from twobyteasr.recognition.run_context import (
    RuntimeContext,
    activate_runtime_context,
    sync_legacy_runtime,
)


EventSink = Callable[["PipelineEvent"], None]


def preview_glossary_correction(*args, **kwargs):
    """Review copied original transcriptions without re-running ASR or saving."""
    from ..glossary.studio_glossary_service import preview_glossary_correction as implementation
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
    # Spoken language of the media: auto (detect from the transcript), zh, ja, en, ko,
    # or (2026-10-19) es, de, fr, pt, it, ru.
    recognition_language: str = "auto"
    # Subtitles to produce: original, translation or bilingual (original + translation).
    subtitle_output: str = "original"
    translation_script: str = "zh-Hans"
    # Script of Chinese subtitles: zh-Hant converts them after recognition (2026-10-19).
    chinese_script: str = "zh-Hans"
    # Audio tracks the home page picked per multi-track file
    # (``audio_stream_choice.request_json``, 2026-10-24); '' = FFmpeg's pick as before.
    audio_streams_json: str = ""

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
        from ..subtitle_rules.language_rules import SUPPORTED_REQUESTS
        if self.recognition_language not in SUPPORTED_REQUESTS:
            raise ValueError("recognition_language 只能是 " + "、".join(SUPPORTED_REQUESTS))
        if self.subtitle_output not in {"original", "translation", "bilingual"}:
            raise ValueError("subtitle_output 只能是 original、translation 或 bilingual")
        from ..subtitle_rules.subtitle_translation import TARGETS
        if self.translation_script not in TARGETS:
            raise ValueError("translation_script 只能是 " + "、".join(TARGETS))
        if self.chinese_script not in {"zh-Hans", "zh-Hant"}:
            raise ValueError("chinese_script 只能是 zh-Hans 或 zh-Hant")

    @classmethod
    def from_legacy(cls, legacy: Any, *, overwrite_policy: str = "overwrite") -> "RunOptions":
        from ..glossary.terminology import snapshot_glossaries
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
            speaker_source=__import__('twobyteasr.recognition.speaker_strategy', fromlist=['resolve']).resolve(getattr(legacy, 'RUNTIME_SETTINGS', {})),
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
        from ..glossary.terminology import GlossarySnapshot, snapshot_glossaries
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
            speaker_source=__import__('twobyteasr.recognition.speaker_strategy', fromlist=['resolve']).resolve(
                json.loads(self.settings_snapshot_json) if self.settings_snapshot_json else getattr(legacy, 'RUNTIME_SETTINGS', {})),
            requested_language=self.recognition_language,
            subtitle_output=self.subtitle_output,
            translation_script=self.translation_script,
            chinese_script=self.chinese_script,
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
        context.chinese_script = configured.chinese_script
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
    # The picked audio track (relative ordinal) a home-page entry recognized
    # on its own, -1 for a whole file or a combined result (2026-10-24).
    audio_stream: int = -1


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
    from ..projects.studio_project import canonical_project_path
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
        project_root = Path(__file__).resolve().parents[2]
        candidate = project_root / "review_tracks" / f"{Path(base).name}_疑似吞字幕复核{extension}"
        if candidate.is_file():
            review_path = str(candidate)
    return speaker_paths, review_path


def audio_lane_label(lane: dict[str, Any]) -> str:
    """'音轨 2｜中文配音' of a picked lane for logs and progress (plain text)."""
    from ..media.audio_streams import stream_label
    record = lane.get("record") or {}
    if record:
        return str(stream_label(record, with_channels=False))
    return f"{lane.get('lane_id', '')}"


def _deliver_audio_lanes(legacy, runtime_context, snapshot, lane_runs, results, result_root, normalized_paths):
    """Combine the picked tracks' results into one project (2026-10-24).

    Each track was recognized on its own input. Successful tracks become one
    result project with their captions kept apart by source; a failed or
    cancelled track is reported with its name and reason, and the captions
    the project already had for it stay untouched.
    """
    media_path = str((snapshot.get("project") or {}).get("media", {}).get("path") or "")
    by_input = dict(zip(normalized_paths, results[:len(normalized_paths)]))
    finished, problems = [], []
    for run in lane_runs:
        lane = run["audio_source"]
        label = audio_lane_label(lane)
        outcome = by_input.get(run.get("input_path") or "")
        if run.get("prepare_error"):
            problems.append((run, "failed", run["prepare_error"]))
        elif outcome is None:
            problems.append((run, "cancelled", "队列已取消。"))
        elif outcome.status in {"success", "degraded_success"} and outcome.project_path:
            finished.append((run, outcome))
        else:
            problems.append((run, outcome.status if outcome.status != "success" else "failed",
                             outcome.error or "没有生成工程"))
        legacy.record_run_event("audio_lane_finished", audio_lane=lane["lane_id"], label=label,
                                status=(outcome.status if outcome else "failed"))
    delivered = []
    if finished:
        from .audio_lane_results import combine_lane_results
        target = Path(result_root) / "识别结果.2byteproj"
        try:
            reference = combine_lane_results(snapshot, [(run, Path(outcome.project_path)) for run, outcome in finished],
                                             target, job_id=runtime_context.job_id,
                                             problems=[(run, status, error) for run, status, error in problems])
        except Exception as exc:
            error = _exception_message(exc, "合并各音轨结果失败")
            legacy.record_run_event("audio_lanes_combine_failed", error=error,
                                    traceback=__import__("traceback").format_exc())
            delivered = [MediaResult(media_path, "failed", error=f"合并各音轨结果失败：{error}")]
        else:
            first = finished[0][1]
            status = "success" if not problems and all(o.status == "success" for _r, o in finished) else "degraded_success"
            note = "；".join(f"{audio_lane_label(run['audio_source'])}：{error}" for run, _status, error in problems)
            delivered = [replace(first, media_path=media_path, status=status, project_path=reference["path"],
                                 project_id=reference["project_id"], result_revision=reference["result_revision"],
                                 media_fingerprint=reference["media_fingerprint"],
                                 result_ref_json=json.dumps(reference, ensure_ascii=False),
                                 elapsed_seconds=sum(o.elapsed_seconds for _r, o in finished),
                                 error=note)]
            legacy.record_run_event("audio_lanes_combined", project_path=reference["path"],
                                    lanes=[run["audio_source"]["lane_id"] for run, _o in finished],
                                    problems=[run["audio_source"]["lane_id"] for run, _s, _e in problems])
    for run, status, error in problems:
        delivered.append(MediaResult(media_path, status if status in {"failed", "cancelled"} else "failed",
                                     error=f"{audio_lane_label(run['audio_source'])}：{error}"))
    return delivered


def _same_media(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _stream_entries(entries, entry_streams, media_path) -> list[int]:
    """1-based queue positions of one file's picked tracks."""
    return [index for index, (path, choice) in enumerate(zip(entries, entry_streams), 1)
            if choice and _same_media(path, media_path)]


def _stream_position(entries, entry_streams, index) -> int:
    return _stream_entries(entries, entry_streams, entries[index - 1]).index(index) + 1


def _stream_count(entries, entry_streams, media_path) -> int:
    return len(_stream_entries(entries, entry_streams, media_path))


def _stream_result_path(entries, entry_streams, media_path, job_id) -> Path:
    """The combined result project of one file's picked tracks."""
    from .recognition_result import recognition_project_path
    first = _stream_entries(entries, entry_streams, media_path)[0]
    return recognition_project_path(media_path, job_id, media_index=first)


def _stream_project_path(entries, entry_streams, index, job_id) -> Path:
    """One picked track's own working project, inside its file's combined result."""
    media_path = entries[index - 1]
    target = _stream_result_path(entries, entry_streams, media_path, job_id)
    ordinal = int(entry_streams[index - 1]["ordinal"])
    folder = f"{_stream_position(entries, entry_streams, index):02d}-track{ordinal + 1}"
    return target.parent / "audio-tracks" / folder / target.name


def _deliver_audio_streams(legacy, runtime_context, run_options, results, entries, entry_streams):
    """Combine each multi-track file's picked tracks into one result (2026-10-24).

    Every picked track ran as its own entry. Per file, the tracks that finished
    become one project whose captions keep their track as speaker source (the
    same merge as the Studio track picker, ``audio_lane_results``). A track
    that failed or was cancelled stays a result of its own, named with its
    track, so the completion page and 重试失败项 know exactly which one.
    """
    from .audio_stream_choice import base_projects, choice_label
    tagged = [replace(item, audio_stream=int(choice["ordinal"])) if choice else item
              for item, choice in zip(results, entry_streams)]
    tagged.extend(results[len(entry_streams):])
    bases = base_projects(run_options.audio_streams_json)
    delivered: list[MediaResult] = []
    done: set[str] = set()
    for index, (item, choice) in enumerate(zip(tagged, entry_streams), 1):
        if not choice:
            delivered.append(item)
            continue
        media_path = entries[index - 1]
        key = os.path.normcase(os.path.abspath(media_path))
        if key in done:
            continue
        done.add(key)
        rows = [(tagged[position - 1], entry_streams[position - 1])
                for position in _stream_entries(entries, entry_streams, media_path)]
        finished = [(row, pick) for row, pick in rows
                    if row.status in {"success", "degraded_success"} and row.project_path]
        problems = [(row, pick) for row, pick in rows if all(row is not done_row for done_row, _p in finished)]
        labelled = [replace(row, status=row.status if row.status in {"failed", "cancelled", "skipped"} else "failed",
                            error=f"{choice_label(pick)}：{row.error or ('没有生成工程' if row.status != 'cancelled' else '队列已取消。')}")
                    for row, pick in problems]
        for row, pick in problems:
            legacy.record_run_event("audio_lane_finished", audio_lane=f"a{pick['ordinal']}", label=choice_label(pick),
                                    status=row.status, error=row.error)
        if not finished:
            delivered.extend(labelled)
            continue
        target = _stream_result_path(entries, entry_streams, media_path, runtime_context.job_id)
        base = bases.get(str(Path(media_path).resolve()), "")
        try:
            from .audio_lane_results import combine_stream_results
            reference = combine_stream_results(media_path, finished, problems, target,
                                               job_id=runtime_context.job_id, base_project=base)
        except Exception as exc:
            error = _exception_message(exc, "合并各音轨结果失败")
            legacy.record_run_event("audio_streams_combine_failed", media_path=media_path, error=error,
                                    traceback=__import__("traceback").format_exc())
            # Each finished track still has its own usable project.
            delivered.extend(replace(row, error=f"{choice_label(pick)}：合并各音轨结果失败：{error}")
                             for row, pick in finished)
            delivered.extend(labelled)
            continue
        first = finished[0][0]
        status = ("success" if not problems and all(row.status == "success" for row, _pick in finished)
                  else "degraded_success")
        note = "；".join(error.error for error in labelled)
        delivered.append(replace(first, status=status, project_path=reference["path"],
                                 project_id=reference["project_id"], result_revision=reference["result_revision"],
                                 media_fingerprint=reference["media_fingerprint"],
                                 result_ref_json=json.dumps(reference, ensure_ascii=False),
                                 elapsed_seconds=sum(row.elapsed_seconds for row, _pick in finished),
                                 error=note or first.error, audio_stream=-1))
        delivered.extend(labelled)
        legacy.record_run_event("audio_streams_combined", media_path=media_path, project_path=reference["path"],
                                tracks=[pick["ordinal"] for _row, pick in finished],
                                problems=[pick["ordinal"] for _row, pick in problems])
    return delivered


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
    # Picked audio tracks of a Studio run (one snapshot each), 2026-10-24.
    lane_runs: list[dict[str, Any]] = []
    # Picked audio tracks of home-page files: one choice per queue entry
    # ({} for a whole file), 2026-10-24.
    entry_streams: list[dict[str, Any]] = []
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
                    from ..providers.llm_config import qwen_asr_endpoint_from_settings
                    runtime_context.asr_endpoint_snapshot=qwen_asr_endpoint_from_settings(runtime_settings)
                    runtime_context.asr_endpoint_snapshot['speaker_source']=runtime_context.speaker_source
                    from .speaker_strategy import execution_plan
                    speaker_plan=execution_plan(runtime_settings,runtime_context.speaker_source)
                    legacy.record_run_event('speaker_plan',job_id=runtime_context.job_id,
                        speaker_source=speaker_plan.source,steps=list(speaker_plan.steps),state='planned')
                    if runtime_settings.get('models',{}).get('primary_asr_backend')=='api':
                        from ..providers.cloud_asr_jobs import validate_speaker_strategy
                        validate_speaker_strategy(runtime_context.asr_endpoint_snapshot)
                    from .text_ai_plan import bind_text_ai_snapshots
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
                        from twobyteasr.system.environment import ensure_environment_ready

                        ensure_environment_ready(runtime_settings)
                pipeline.check_runtime(legacy)
                if runtime_context.recognition_snapshot:
                    from .recognition_input import lane_snapshots, prepare_recognition_input
                    from ..media.media_service import GLOBAL_MEDIA_SERVICE
                    snapshot = runtime_context.recognition_snapshot
                    from .recognition_result import media_identity_for_task, digest_payload
                    # 2026-10-24: picked audio tracks of a multi-track source
                    # each get their own input; otherwise one timeline mix.
                    lane_runs = lane_snapshots(snapshot) if snapshot.get("audio_lanes") else []
                    normalized_paths = []
                    for target in lane_runs or [snapshot]:
                        # Source hashes are computed by this worker once per job;
                        # mapping/range/audio graph stay part of the input identity.
                        for source, source_identity in target["sources"].items():
                            current = media_identity_for_task(source, runtime_context)
                            if (current["size"], current["mtime_ns"]) != (source_identity["size"], source_identity["mtime_ns"]):
                                raise RuntimeError(f"识别启动后素材已改变：{source}")
                            source_identity["sha256"] = current["sha256"]
                        target["fingerprint"] = digest_payload({k: target[k] for k in
                            ("version", "duration_ms", "audio_graph", "sequence", "sources")
                            + (("audio_source",) if target.get("audio_source") else ())})
                        lane = target.get("audio_source") or {}
                        legacy.record_run_event("timeline_input_preparing", fingerprint=target["fingerprint"],
                                                duration_ms=target["duration_ms"], audio_lane=lane.get("lane_id", ""),
                                                audio_stream_ordinal=lane.get("ordinal"),
                                                audio_stream_index=lane.get("stream_index"))
                        try:
                            prepared = prepare_recognition_input(target, legacy.CACHE_ROOT, GLOBAL_MEDIA_SERVICE.ffmpeg_path, token=token)
                        except CancelledError:
                            raise
                        except Exception as exc:
                            if not lane_runs:
                                raise
                            # One track that cannot be prepared never stops the others.
                            target["prepare_error"] = _exception_message(exc, "时间轴音频准备失败")
                            legacy.record_run_event("audio_lane_failed", audio_lane=lane.get("lane_id", ""),
                                                    stage="prepare", error=target["prepare_error"])
                            continue
                        target["input_path"] = prepared
                        normalized_paths.append(prepared)
                        legacy.record_run_event("timeline_input_ready", input_path=prepared,
                            fingerprint=target["fingerprint"], duration_ms=target["duration_ms"],
                            time_domain="timeline", audio_graph=target["audio_graph"],
                            audio_lane=lane.get("lane_id", ""), audio_stream_ordinal=lane.get("ordinal"),
                            audio_stream_index=lane.get("stream_index"))
                    result_root = Path(run_options.studio_project_path).parent / "recognition-results" / runtime_context.job_id
                    runtime_context.studio_project_path = str(result_root / "识别结果.2byteproj")
                    if lane_runs and not normalized_paths:
                        raise RuntimeError("所选音轨都无法准备识别音频：" + "；".join(
                            str(run.get("prepare_error") or "") for run in lane_runs))
                    state["media_total"] = len(normalized_paths)
                elif run_options.audio_streams_json:
                    from .audio_stream_choice import expand_queue, parse_request
                    from ..media.media_service import GLOBAL_MEDIA_SERVICE
                    # Each audio track the home page picked of a multi-track
                    # file is one entry that hears only that track.
                    normalized_paths, entry_streams = expand_queue(
                        normalized_paths, parse_request(run_options.audio_streams_json),
                        lambda path: GLOBAL_MEDIA_SERVICE.metadata(path).audio_streams)
                    if not any(entry_streams):
                        entry_streams = []
                    state["media_total"] = len(normalized_paths)
                    legacy.record_run_event("audio_streams_planned", entries=[
                        {"media_path": path, "audio_stream_ordinal": choice.get("ordinal"),
                         "audio_stream_index": choice.get("stream_index"), "offset_ms": choice.get("offset_ms")}
                        for path, choice in zip(normalized_paths, entry_streams)])
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
                stream_choice = entry_streams[index - 1] if entry_streams else {}
                runtime_context.audio_stream = dict(stream_choice)
                if stream_choice:
                    from .audio_stream_choice import choice_label
                    legacy.record_run_event("audio_lane_started", audio_lane=f"a{stream_choice['ordinal']}",
                                            lane_index=_stream_position(normalized_paths, entry_streams, index),
                                            lane_total=_stream_count(normalized_paths, entry_streams, media_path),
                                            label=choice_label(stream_choice),
                                            audio_stream_ordinal=stream_choice["ordinal"],
                                            audio_stream_index=stream_choice["stream_index"], input_path=media_path)
                lane_run = next((run for run in lane_runs if run.get("input_path") == media_path), None)
                if lane_run is not None:
                    # This input is one picked audio track: its own snapshot,
                    # its own result project, combined after the last one.
                    lane = lane_run["audio_source"]
                    runtime_context.recognition_snapshot = lane_run
                    runtime_context.studio_project_path = str(
                        result_root / "lanes" / f"{lane_run['lane_index']:02d}-{lane['lane_id']}" / "识别结果.2byteproj")
                    legacy.record_run_event("audio_lane_started", audio_lane=lane["lane_id"],
                                            lane_index=lane_run["lane_index"], lane_total=lane_run["lane_total"],
                                            label=audio_lane_label(lane), audio_stream_ordinal=lane.get("ordinal"),
                                            audio_stream_index=lane.get("stream_index"), input_path=media_path)
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
                    elif stream_choice:
                        runtime_context.studio_project_path = str(
                            _stream_project_path(normalized_paths, entry_streams, index, runtime_context.job_id))
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

            if lane_runs:
                runtime_context.recognition_snapshot = snapshot
                results = _deliver_audio_lanes(legacy, runtime_context, snapshot, lane_runs, results,
                                               result_root, normalized_paths)
            if entry_streams:
                runtime_context.audio_stream = {}
                results = _deliver_audio_streams(legacy, runtime_context, run_options, results,
                                                 normalized_paths, entry_streams)
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
