"""A silent chunk must not throw away incremental recognition in the packaged app.

2026-10-23 user log (SenseVoice, installed app): 34 chunks came back from the
manifest, the next one held only tags such as <|BGM|>, the worker route raised
"sensevoice worker returned no parsed text", and the empty-chunk rule matched
only the in-process wording. The whole incremental run was discarded and the
task fell back to whole-file recognition.
"""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import subtitle_core  # noqa: F401  (legacy core first)
from twobyteasr.recognition import asr

TAGS_ONLY = "<|zh|><|NEUTRAL|><|BGM|><|withitn|>"


def _worker_returns(monkeypatch, texts):
    monkeypatch.setattr(asr, "resolve_funasr_local_source", lambda key: "model-dir")
    monkeypatch.setattr(asr, "_main_worker_python", lambda: __file__)
    monkeypatch.setattr(asr, "_run_isolated_asr_worker",
                        lambda *a, **kw: {"results": [{"text": text} for text in texts]})


def _chunks(count):
    return [{"start": 25.0 * index, "end": 25.0 * (index + 1), "audio": (np.zeros(1600, dtype=np.float32), 16000)}
            for index in range(count)]


def test_worker_route_reports_a_silent_chunk_as_no_recognized_text(monkeypatch):
    _worker_returns(monkeypatch, [TAGS_ONLY, ""])
    with pytest.raises(asr.NoRecognizedTextError, match="worker returned no parsed text"):
        asr._transcribe_funasr_worker("sensevoice", _chunks(2))


def test_worker_reports_empty_text_instead_of_failing(monkeypatch, tmp_path):
    """Fun-ASR Nano can return "" for silence; the worker no longer exits with an error."""
    import json
    import sys
    import types

    import sensevoice_worker
    from twobyteasr import model_integrity

    class Model:
        def __init__(self, **kwargs):
            pass

        def generate(self, **options):
            return [{"text": ""}]

    funasr = types.ModuleType("funasr")
    funasr.AutoModel = Model
    funasr.__file__ = str(tmp_path / "funasr" / "__init__.py")
    monkeypatch.setitem(sys.modules, "funasr", funasr)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(model_integrity, "verify_model_files", lambda *a, **kw: None)
    monkeypatch.setattr(sensevoice_worker, "_enable_unicode_sentencepiece_paths", lambda: None)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    manifest, output = tmp_path / "manifest.json", tmp_path / "results.json"
    manifest.write_text(json.dumps({"jobs": [{"segment_id": 1, "path": str(tmp_path / "a.wav"), "start": 0, "end": 1}]}),
                        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["sensevoice_worker.py", "--manifest", str(manifest), "--output", str(output),
                                      "--model-key", "funasr_nano", "--model-dir", str(model_dir),
                                      "--diagnostics-dir", str(tmp_path / "diagnostics")])
    sensevoice_worker.main()
    assert json.loads(output.read_text(encoding="utf-8"))["results"][0]["text"] == ""


def test_a_short_worker_answer_is_still_a_failure(monkeypatch):
    _worker_returns(monkeypatch, [TAGS_ONLY])
    with pytest.raises(RuntimeError, match="returned 1 of 2 results") as raised:
        asr._transcribe_funasr_worker("sensevoice", _chunks(2))
    assert not isinstance(raised.value, asr.NoRecognizedTextError)


class _StopAfterPrimary(BaseException):
    pass


def test_packaged_worker_silent_chunk_keeps_incremental_recognition(monkeypatch, tmp_path):
    import moss_firered_pipeline as pipeline
    from twobyteasr.media.media_service import GLOBAL_MEDIA_SERVICE
    from twobyteasr.recognition import incremental_asr, speaker_strategy
    from twobyteasr.recognition.run_context import RuntimeContext

    (tmp_path / "source.mp4").write_bytes(b"test transport fixture")
    _worker_returns(monkeypatch, [TAGS_ONLY, TAGS_ONLY])
    events, silent = [], []

    class Incremental:
        """The manifest already holds the earlier chunks; one new chunk is silent."""

        def __init__(self, media_path, *, recognize_chunk, **kwargs):
            self.recognize_chunk = recognize_chunk
            self.identity = SimpleNamespace(key="fixture")

        def run(self):
            silent.append(self.recognize_chunk(tmp_path / "chunk_0034.wav", SimpleNamespace(start_ms=0, end_ms=45_000)))
            return [{"start_ms": 0, "end_ms": 25_000, "text": "然后我们看一下", "speaker_id": "S00",
                     "source": "sensevoice"}]

    def primary(backend, path, regions, audio, seconds):
        if Path(path).name == "chunk_0034.wav":
            # The packaged app's route for one incremental chunk (25 s + 20 s pieces).
            return asr._transcribe_funasr_worker(backend, _chunks(2))
        # Whole-file recognition after a fallback (a cache hit in the user's log).
        return [{"start": 0.0, "end": 25.0, "text": "然后我们看一下", "source": "sensevoice"}]

    def stop(*args, **kwargs):
        raise _StopAfterPrimary()

    legacy = SimpleNamespace(
        RUNTIME_SETTINGS={}, PRIMARY_ASR_BACKEND="sensevoice", FIRERED_ASR_BACKEND="off",
        PARALLEL_GPU_ASR=True, PARALLEL_CPU_VAD=False, USE_FIRERED_BOUNDARY_REFINEMENT=False,
        AUDIO_SAMPLE_RATE=16000, reset_review_items=lambda: None,
        output_paths_for_media=lambda p: ("unused.txt", "unused.srt"), detect_timeline_fps=lambda p: 24,
        media_cache_context=lambda p: {"cache_dir": str(tmp_path)}, begin_media_report=lambda *a: None,
        run_timed_stage=lambda n, total, label, resource, run: run(),
        run_cached_stage=lambda name, cache, run, **kw: run(),
        load_shared_audio=lambda *a: np.zeros(16000, dtype=np.float32),
        record_run_event=lambda name, **data: events.append((name, data)),
        capture_review_items=lambda: nullcontext([]), extend_review_items=lambda rows: None,
        transcribe_primary_reference=primary,
        transcribe_firered_reference=lambda *a: [],
    )
    monkeypatch.setattr(GLOBAL_MEDIA_SERVICE, "metadata", lambda path: SimpleNamespace(duration_ms=60_000))
    monkeypatch.setattr(incremental_asr, "IncrementalASRPipeline", Incremental)
    monkeypatch.setattr(pipeline, "_script_paths", lambda _: {
        "firered_vad": str(tmp_path / "missing"), "firered_worker": "", "main_python": "", "firered_source": ""})
    monkeypatch.setattr(pipeline, "_moss_stage_signature", lambda _: {})
    monkeypatch.setattr(pipeline, "_cloud_hint_signature", lambda *a: {})
    monkeypatch.setattr(pipeline, "_gpu_runtime_snapshot", lambda: {})
    monkeypatch.setattr(pipeline, "detect_lightweight_vad", lambda *a: [dict(start=0.0, end=25.0)])
    monkeypatch.setattr(pipeline, "_run_audited_model_stage", lambda *a, runner, **kw: runner())
    monkeypatch.setattr(speaker_strategy, "resolve", stop)

    with pytest.raises(_StopAfterPrimary):
        pipeline.process_media(str(tmp_path / "source.mp4"), 1, 1, legacy, RuntimeContext(requested_language="zh"))

    names = [name for name, _ in events]
    assert silent == [[]]
    assert "incremental_asr_fallback" not in names, [data for name, data in events if name == "incremental_asr_fallback"]
    assert "incremental_asr_completed" in names
