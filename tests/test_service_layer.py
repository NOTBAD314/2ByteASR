from contextlib import contextmanager
from pathlib import Path
from functools import partial
from types import SimpleNamespace

import pytest

from twobyteasr.recognition.service import CancellationToken, RunOptions, run_media_queue as _run_media_queue

# These tests own FakePipeline/runtime doubles. Production keeps the mandatory
# environment gate; use its explicit test opt-out so assertions reach the fake.
run_media_queue = partial(_run_media_queue, _skip_environment_preflight=True)


class FakeLegacy:
    PIPELINE_BUILD_ID = "test"
    __file__ = __file__
    HF_TOKEN = ""
    RUNTIME_GAME_NAME = ""
    RUNTIME_ENABLE_DOMAIN_TERMS = False
    RUNTIME_DISCOVERED_TERMS = set()
    RUNTIME_OUTPUT_REVIEW_TRACK = False
    RUNTIME_FORCE_REFRESH_API_CACHE = False
    RUNTIME_FORCE_REFRESH_POLISH_CACHE = False
    RUNTIME_FORCE_REFRESH_GROUP_CACHE = False
    RUNTIME_EXPECTED_SPEAKERS = 0
    RUNTIME_CANCELLATION_TOKEN = None

    def __init__(self, root):
        self.root = Path(root)
        self.observer = None
        self.finished_reports = []
        self.local_asr_session_events = []
        self.task_reporting = SimpleNamespace(
            report_paths_for_media=lambda path: (
                str(self.root / f"{Path(path).stem}.json"),
                str(self.root / f"{Path(path).stem}.txt"),
            )
        )

    @staticmethod
    def canonicalize_runtime_game_name(value):
        return str(value).strip()

    @staticmethod
    def run_startup_self_test():
        return {"id": "test", "checks": 1}

    @staticmethod
    def runtime_content_profile_signature():
        return {}

    @staticmethod
    def runtime_settings_snapshot():
        return {}

    @staticmethod
    def cleanup_old_cache():
        return None

    @staticmethod
    def format_elapsed(seconds):
        return f"{seconds:.0f}s"

    def begin_run_event_log(self):
        return str(self.root / "events.jsonl")

    @contextmanager
    def run_event_observer(self, callback):
        self.observer = callback
        try:
            yield callback
        finally:
            self.observer = None

    def record_run_event(self, event, **payload):
        if self.observer:
            self.observer(event, payload)

    def output_paths_for_media(self, media_path):
        stem = Path(media_path).stem
        return str(self.root / f"{stem}.txt"), str(self.root / f"{stem}.srt")

    def finish_media_report(self, status, **result):
        self.finished_reports.append((status, result))
        return "", ""

    def begin_local_asr_session(self):
        self.local_asr_session_events.append("begin")

    def end_local_asr_session(self):
        self.local_asr_session_events.append("end")


class FakePipeline:
    PIPELINE_BUILD_ID = "test"
    __file__ = __file__

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.processed = []
        self.token = None

    def set_cancellation_token(self, token):
        self.token = token

    @staticmethod
    def check_runtime(legacy):
        return None

    @staticmethod
    def precompute_moss_batch_cache(media_paths, legacy):
        return None

    def process_media(self, media_path, file_index, file_total, legacy):
        self.processed.append(media_path)
        if Path(media_path).name in self.failing:
            raise RuntimeError("synthetic failure")
        txt_path, srt_path = legacy.output_paths_for_media(media_path)
        Path(txt_path).write_text("ok", encoding="utf-8")
        Path(srt_path).write_text("ok", encoding="utf-8")
        return txt_path, srt_path, 0.25


def _media(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"media")
    return str(path)


def test_run_options_apply_runtime_values(tmp_path):
    legacy = FakeLegacy(tmp_path)
    options = RunOptions(
        content_name=" 原神 ",
        enable_domain_terms=True,
        output_review_track=True,
        force_refresh_polish=True,
        expected_speakers=2,
    )
    options.apply(legacy)
    assert legacy.RUNTIME_GAME_NAME == "原神"
    assert legacy.RUNTIME_ENABLE_DOMAIN_TERMS is True
    assert legacy.RUNTIME_OUTPUT_REVIEW_TRACK is True
    assert legacy.RUNTIME_FORCE_REFRESH_POLISH_CACHE is True
    assert legacy.RUNTIME_EXPECTED_SPEAKERS == 2


@pytest.mark.parametrize("value", [-1, 7])
def test_run_options_reject_invalid_speaker_count(value):
    with pytest.raises(ValueError):
        RunOptions(expected_speakers=value)


@pytest.mark.parametrize("value", [0, 1, 2, 3, 4, 5, 6])
def test_run_options_accept_supported_speaker_count(value):
    assert RunOptions(expected_speakers=value).expected_speakers == value


def test_queue_isolates_media_failure_and_emits_ordered_events(tmp_path):
    legacy = FakeLegacy(tmp_path)
    pipeline = FakePipeline(failing={"bad.wav"})
    media = [_media(tmp_path, "bad.wav"), _media(tmp_path, "good.wav")]
    events = []
    result = run_media_queue(
        media,
        RunOptions(),
        events.append,
        _legacy=legacy,
        _pipeline=pipeline,
    )
    assert [item.status for item in result.results] == ["failed", "success"]
    assert len(result.failures) == 1
    assert len(result.successes) == 1
    assert result.exit_code == 1
    kinds = [event.kind for event in events]
    assert kinds.index("media_failed") < kinds.index("media_completed") < kinds.index("run_completed")
    assert events[kinds.index("media_completed")].media_path.endswith("good.wav")


def test_empty_runtime_exception_still_returns_actionable_failure(tmp_path):
    class EmptyRuntimeFailurePipeline(FakePipeline):
        @staticmethod
        def check_runtime(legacy):
            raise RuntimeError()

    result = run_media_queue(
        [_media(tmp_path, "missing-cuda.wav")],
        RunOptions(),
        _legacy=FakeLegacy(tmp_path),
        _pipeline=EmptyRuntimeFailurePipeline(),
    )

    assert result.exit_code == 1
    assert "运行环境检查失败" in result.failures[0].error
    assert "RuntimeError" in result.failures[0].error


def test_skip_overwrite_policy_does_not_call_processor(tmp_path, monkeypatch):
    legacy = FakeLegacy(tmp_path)
    pipeline = FakePipeline()
    media_path = _media(tmp_path, "existing.wav")
    target = tmp_path / "existing.2byteproj"
    target.write_text("existing", encoding="utf-8")
    monkeypatch.setattr("twobyteasr.projects.studio_project.canonical_project_path", lambda _: target)
    result = run_media_queue(
        [media_path],
        RunOptions(overwrite_policy="skip"),
        _legacy=legacy,
        _pipeline=pipeline,
    )
    assert result.results[0].status == "skipped"
    assert pipeline.processed == []


def test_cancelled_queue_never_starts_processing(tmp_path):
    legacy = FakeLegacy(tmp_path)
    pipeline = FakePipeline()
    token = CancellationToken()
    token.cancel()
    media = [_media(tmp_path, "one.wav"), _media(tmp_path, "two.wav")]
    result = run_media_queue(
        media,
        RunOptions(),
        cancel_token=token,
        _legacy=legacy,
        _pipeline=pipeline,
    )
    assert [item.status for item in result.results] == ["cancelled", "cancelled"]
    assert pipeline.processed == []
    assert result.exit_code == 2


def test_multi_media_queue_reuses_and_always_releases_local_asr_session(tmp_path):
    legacy = FakeLegacy(tmp_path)
    pipeline = FakePipeline(failing={"bad.wav"})
    result = run_media_queue(
        [_media(tmp_path, "bad.wav"), _media(tmp_path, "good.wav")],
        RunOptions(),
        _legacy=legacy,
        _pipeline=pipeline,
    )

    assert result.exit_code == 1
    assert legacy.local_asr_session_events == ["begin", "end"]


def test_single_media_queue_does_not_keep_model_session_alive(tmp_path):
    legacy = FakeLegacy(tmp_path)
    run_media_queue(
        [_media(tmp_path, "one.wav")],
        RunOptions(),
        _legacy=legacy,
        _pipeline=FakePipeline(),
    )
    assert legacy.local_asr_session_events == []


def test_single_studio_run_starts_persistent_model_session_without_queue_release(tmp_path):
    legacy = FakeLegacy(tmp_path)
    project_path = tmp_path / "active.2byteproj"
    project_path.write_text("{}", encoding="utf-8")
    run_media_queue(
        [_media(tmp_path, "studio.wav")],
        RunOptions(studio_project_path=str(project_path), recognition_purpose="analysis"),
        _legacy=legacy,
        _pipeline=FakePipeline(),
    )
    assert legacy.local_asr_session_events == ["begin"]


def test_queue_passes_explicit_runtime_context_to_context_aware_pipeline(tmp_path):
    class ContextAwarePipeline(FakePipeline):
        def __init__(self):
            super().__init__()
            self.runtime_context = None

        def process_media(
            self,
            media_path,
            file_index,
            file_total,
            legacy,
            runtime_context=None,
        ):
            self.runtime_context = runtime_context
            return super().process_media(media_path, file_index, file_total, legacy)

    legacy = FakeLegacy(tmp_path)
    pipeline = ContextAwarePipeline()
    run_media_queue(
        [_media(tmp_path, "one.wav")],
        RunOptions(content_name="原神", enable_domain_terms=True, expected_speakers=3),
        _legacy=legacy,
        _pipeline=pipeline,
    )

    assert pipeline.runtime_context is not None
    assert pipeline.runtime_context.game_name == "原神"
    assert pipeline.runtime_context.enable_domain_terms is True
    assert pipeline.runtime_context.expected_speakers == 3


def test_runtime_event_observer_is_structured_and_nonfatal():
    import subtitle_core

    received = []
    with subtitle_core.run_event_observer(lambda kind, payload: received.append((kind, payload))):
        subtitle_core.record_run_event("test_event", value="safe")
    assert len(received) == 1 and received[0][0] == "test_event"
    assert received[0][1]["value"] == "safe"
    assert received[0][1]["monotonic_seconds"] >= 0

    def broken_observer(kind, payload):
        raise RuntimeError("UI observer failure")

    with subtitle_core.run_event_observer(broken_observer):
        subtitle_core.record_run_event("observer_failure_isolated")
