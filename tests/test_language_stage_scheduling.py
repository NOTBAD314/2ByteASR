"""Actual pipeline scheduling: resolve Auto before launching a Chinese AED pass."""
from types import SimpleNamespace
from contextlib import nullcontext
import numpy as np
import pytest


class LanguageResolved(BaseException):
    pass


@pytest.mark.parametrize("requested,spoken,early,discarded", [
    ("ja", "今日はいい天気ですね", False, False),
    ("en", "This is an English conversation", False, False),
    ("auto", "今日はいい天気ですね", False, False),
    ("auto", "This is an English conversation", False, False),
    ("auto", "今天天气真好", False, False),
    ("zh", "今天天气真好", True, False),
])
def test_cloud_primary_chinese_timeline_follows_requested_language(monkeypatch, tmp_path, requested, spoken, early,
                                                                   discarded):
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import asr_progress
    from twobyteasr.recognition.run_context import RuntimeContext
    from twobyteasr.recognition import speaker_strategy
    context = RuntimeContext(requested_language=requested)
    (tmp_path / "source.mp4").write_bytes(b"test transport fixture")
    events, calls = [], []
    def event(name, **data):
        events.append((name, data))
    def language_routed(*a, **kw):
        # First call after the language decision and the early-result discard.
        raise LanguageResolved()
    legacy = SimpleNamespace(
        RUNTIME_SETTINGS={}, PRIMARY_ASR_BACKEND="api", FIRERED_ASR_BACKEND="local",
        PARALLEL_GPU_ASR=True, PARALLEL_CPU_VAD=False, USE_FIRERED_BOUNDARY_REFINEMENT=True,
        AUDIO_SAMPLE_RATE=16000, reset_review_items=lambda: None,
        output_paths_for_media=lambda p: ("unused.txt", "unused.srt"), detect_timeline_fps=lambda p: 24,
        media_cache_context=lambda p: {"cache_dir": str(tmp_path)}, begin_media_report=lambda *a: None,
        run_timed_stage=lambda n, total, label, resource, run: run(),
        run_cached_stage=lambda name, cache, run, **kw: run(),
        load_shared_audio=lambda *a: np.zeros(16000, dtype=np.float32),
        record_run_event=event,
        capture_review_items=lambda: nullcontext([]), extend_review_items=lambda rows: None,
        transcribe_primary_reference=lambda *a: [dict(start=0, end=1, text=spoken, speaker="S01")],
        transcribe_firered_reference=lambda *a: calls.append("FireRed") or [],
    )
    monkeypatch.setattr(pipeline, "_script_paths", lambda _: {
        "firered_vad": str(tmp_path/"missing"), "firered_worker": "", "main_python": "",
        "firered_source": ""})
    monkeypatch.setattr(pipeline, "_moss_stage_signature", lambda _: {})
    monkeypatch.setattr(pipeline, "_cloud_hint_signature", lambda *a: {})
    monkeypatch.setattr(pipeline, "_gpu_runtime_snapshot", lambda: {})
    monkeypatch.setattr(asr_progress, "api_local_admission", lambda *a, **kw: {"admitted": True})
    monkeypatch.setattr(pipeline, "detect_lightweight_vad", lambda *a: [dict(start=0, end=1)])
    monkeypatch.setattr(pipeline, "_run_audited_model_stage", lambda *a, runner, **kw: runner())
    monkeypatch.setattr(speaker_strategy, "resolve", language_routed)
    # Exercise the production parallel-stage orchestrator with both branches;
    # transport/model execution alone is replaced with deterministic fixtures.
    with pytest.raises(LanguageResolved):
        pipeline.process_media(str(tmp_path/"source.mp4"), 1, 1, legacy, context)
    assert calls == (["FireRed"] if early else [])
    assert any(name == "TASK_LANGUAGE" for name, _ in events)
    assert any(name == "timeline_result_discarded" for name, _ in events) == discarded


def _whole_file_run(monkeypatch, tmp_path, *, cached):
    import threading
    import moss_firered_pipeline as pipeline
    from twobyteasr.providers.mosi_asr import MODEL as MOSI_MODEL
    from twobyteasr.recognition.run_context import RuntimeContext
    from twobyteasr.recognition import speaker_strategy
    context = RuntimeContext(requested_language="ja")
    context.asr_endpoint_snapshot = {"provider": "mosi_moss_pro", "model": MOSI_MODEL, "url": "https://example.invalid",
                                     "protocol": "mosi_transcriptions"}
    (tmp_path / "source.mp4").write_bytes(b"test transport fixture")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    if cached:
        (cache_dir / "primary_api.json").write_text("{}", encoding="utf-8")
    events, signatures, order = [], {}, []
    uploading = threading.Event()

    def cached_stage(name, cache, run, **kw):
        signatures[name] = kw.get("extra_signature")
        return run()

    def primary(*a):
        order.append("primary")
        uploading.set()
        return [dict(start=0, end=1, text="今日はいい天気ですね", speaker="S01")]

    def vad(*a):
        order.append("vad")
        if not cached:  # serial order would run this first and never see the upload start
            assert uploading.wait(5), "VAD ran before the cloud upload started"
        return [dict(start=0, end=1)]

    legacy = SimpleNamespace(
        RUNTIME_SETTINGS={}, PRIMARY_ASR_BACKEND="api", FIRERED_ASR_BACKEND="local",
        PARALLEL_GPU_ASR=True, PARALLEL_CPU_VAD=True, USE_FIRERED_BOUNDARY_REFINEMENT=True,
        AUDIO_SAMPLE_RATE=16000, reset_review_items=lambda: None,
        output_paths_for_media=lambda p: ("unused.txt", "unused.srt"), detect_timeline_fps=lambda p: 24,
        media_cache_context=lambda p: {"cache_dir": str(cache_dir), "identity": {"media": "fixture"}},
        begin_media_report=lambda *a: None,
        run_timed_stage=lambda n, total, label, resource, run: run(),
        run_cached_stage=cached_stage,
        load_shared_audio=lambda *a: np.zeros(16000, dtype=np.float32),
        record_run_event=lambda name, **data: events.append((name, data)),
        capture_review_items=lambda: nullcontext([]), extend_review_items=lambda rows: None,
        transcribe_primary_reference=primary,
        transcribe_firered_reference=lambda *a: [],
    )
    monkeypatch.setattr(pipeline, "_script_paths", lambda _: {
        "firered_vad": str(tmp_path/"missing"), "firered_worker": "", "main_python": "",
        "firered_source": ""})
    monkeypatch.setattr(pipeline, "_moss_stage_signature", lambda _: {})
    monkeypatch.setattr(pipeline, "_cloud_hint_signature", lambda *a: {})
    monkeypatch.setattr(pipeline, "_gpu_runtime_snapshot", lambda: {})
    monkeypatch.setattr(pipeline, "detect_lightweight_vad", vad)
    monkeypatch.setattr(pipeline, "_run_audited_model_stage", lambda *a, runner, **kw: runner())
    monkeypatch.setattr(speaker_strategy, "resolve", lambda *a, **kw: (_ for _ in ()).throw(LanguageResolved()))
    with pytest.raises(LanguageResolved):
        pipeline.process_media(str(tmp_path/"source.mp4"), 1, 1, legacy, context)
    return SimpleNamespace(events=events, signatures=signatures, order=order, cache_dir=cache_dir)


def test_whole_file_cloud_upload_runs_beside_vad(monkeypatch, tmp_path):
    """2026-10-22 (user report): MOSS Pro waited 26 s for VAD it never reads; now they run together."""
    import json
    run = _whole_file_run(monkeypatch, tmp_path, cached=False)
    assert ("local_stages_parallel", {"stages": ["primary_api", "firered_vad"]}) in run.events
    assert "primary_api" not in run.signatures  # no lookup: there was nothing to find
    stored = json.loads((run.cache_dir / "primary_api.json").read_text("utf-8"))
    assert stored["data"][0]["text"] == "今日はいい天気ですね"
    # Written under the same key a later serial run looks up (VAD regions included).
    from twobyteasr.recognition.cache import stable_digest
    (tmp_path / "second").mkdir()
    serial = _whole_file_run(monkeypatch, tmp_path / "second", cached=True)
    assert stored["dependency_hash"] == stable_digest(serial.signatures["primary_api"])


def test_cached_whole_file_upload_keeps_the_serial_lookup(monkeypatch, tmp_path):
    run = _whole_file_run(monkeypatch, tmp_path, cached=True)
    assert run.order == ["vad", "primary"]
    assert run.signatures["primary_api"]["vad"] == [dict(start=0, end=1)]
