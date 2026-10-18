"""Actual pipeline scheduling: a manual Japanese/English task never launches the Chinese recognizer.

Chinese and Auto tasks keep the 0.8.0 overlap with the cloud transcript (Auto is the default and
usually Chinese); an Auto task that turns out Japanese/English discards that early result.
"""
from types import SimpleNamespace
from contextlib import nullcontext
import numpy as np
import pytest


class LanguageResolved(BaseException):
    pass


@pytest.mark.parametrize("requested,spoken,early,discarded", [
    ("ja", "今日はいい天気ですね", False, False),
    ("en", "This is an English conversation", False, False),
    ("auto", "今日はいい天気ですね", True, True),
    ("auto", "This is an English conversation", True, True),
    ("auto", "今天天气真好", True, False),
    ("zh", "今天天气真好", True, False),
])
def test_cloud_primary_chinese_timeline_follows_requested_language(monkeypatch, tmp_path, requested, spoken, early,
                                                                   discarded):
    import moss_firered_pipeline as pipeline
    from twobyteasr import asr_progress
    from twobyteasr.runtime import RuntimeContext
    from twobyteasr import speaker_strategy
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
