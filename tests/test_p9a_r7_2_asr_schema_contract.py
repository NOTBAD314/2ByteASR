from __future__ import annotations

from types import SimpleNamespace

import pytest

import moss_firered_pipeline as pipeline
from twobyteasr.recognition.asr_schema import (
    SchemaContractError,
    flatten_segment_tokens,
    normalize_firered_worker_result,
    normalize_moss_result,
)


def _seg(i, *, speaker="S01"):
    return {"start": float(i), "end": float(i + 0.8), "text": f"句子{i}", "speaker": speaker}


def test_five_moss_chunks_merge_to_one_flat_canonical_result(monkeypatch):
    legacy = SimpleNamespace(
        AUDIO_SAMPLE_RATE=16000,
        content_only=lambda text: text,
        clean_subtitle_text=lambda text: text,
        asr_consensus_similarity=lambda left, right: 1.0 if left == right else 0.0,
        record_run_event=lambda *args, **kwargs: None,
    )
    payload = {"chunks": [{"chunk_id": i, "offset": float(i * 30), "duration": 30.0, "segments": [_seg(11)]} for i in range(5)]}
    monkeypatch.setattr(pipeline, "_compute_chunk_speaker_embeddings", lambda *args, **kwargs: {})
    result = pipeline._merge_moss_chunks(payload, 150.0, legacy)
    assert result["result_type"] == "ASRResult"
    assert len(result["segments"]) == 5
    assert all(isinstance(item, dict) for item in result["segments"])


def test_nested_moss_segment_is_rejected():
    payload = {"chunks": [{"segments": [[_seg(0)]]}]}
    with pytest.raises(SchemaContractError):
        pipeline._validate_moss_worker_payload(payload, producer="worker", consumer="merger")


def test_firered_nineteen_worker_rows_keep_nineteen_canonical_segments():
    rows = [{"segment_id": i, "text": f"词{i}", "timestamp": [[f"词{i}", 0.0, 0.5]]} for i in range(19)]
    jobs = [{"segment_id": i, "offset": float(i), "duration": 1.0} for i in range(19)]
    result = normalize_firered_worker_result({"results": rows}, jobs)
    assert len(result["segments"]) == 19
    assert len(flatten_segment_tokens(result)) == 19


def test_stage5_canonical_fire_red_is_flattened_once():
    canonical = {"result_type": "ASRResult", "segments": [_seg(0)]}
    flat = pipeline._flatten_firered_stage5_result(canonical)
    assert flat == canonical["segments"]


def test_stage5_rejects_malformed_value_with_schema_error():
    with pytest.raises(SchemaContractError) as error:
        pipeline._flatten_firered_stage5_result([[ _seg(0) ]])
    assert "stage5_firered_token_boundary" in str(error.value)
    assert "AttributeError" not in str(error.value)


def test_alignment_dtype_parser_accepts_supported_float_sample():
    stdout = '[2BYTEASR_FIRERED_AED] {"event":"align_dtype","log_probs_dtype":"torch.float16","log_probs_device":"cuda:0","targets_dtype":"torch.int64","targets_device":"cuda:0"}'
    sample = __import__("twobyteasr.recognition.asr", fromlist=["_parse_firered_alignment_telemetry"])._parse_firered_alignment_telemetry(stdout)
    assert sample[0]["log_probs_dtype"] == "torch.float16"


def test_model_result_count_uses_canonical_segment_count():
    assert pipeline._model_result_count({"result_type": "ASRResult", "segments": [_seg(i) for i in range(19)]}) == 19


def test_frozen_qwen_worker_result_survives_finally_without_torch(monkeypatch):
    """frozen 进程没有 torch；worker 路径的成功返回值不得被 finally 清理吞掉。"""
    import sys

    from twobyteasr.recognition import asr

    references = [{"start": 0.0, "end": 1.0, "text": "真实短块", "confidence": 0.9}]
    monkeypatch.setattr(asr, "USE_QWEN_ASR_REFERENCE", True)
    monkeypatch.setattr(asr, "QWEN_ASR_BACKEND", "local")
    monkeypatch.setattr(asr, "_legacy_runtime_value", lambda name, default: {
        "USE_QWEN_ASR_REFERENCE": True, "QWEN_ASR_BACKEND": "local"}.get(name, default))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(asr, "resolve_qwen_asr_local_source", lambda: "C:/fake/qwen3-asr")
    monkeypatch.setattr(
        asr,
        "build_qwen_asr_chunks",
        lambda audio, regions, rate, **kwargs: [{"start": 0.0, "end": 1.0, "audio": audio}],
    )
    monkeypatch.setattr(asr, "_transcribe_qwen_worker", lambda audio, chunks, model_path: list(references))
    # sys.modules['torch'] = None 让任何 `import torch` 直接 ImportError，
    # 模拟冻结 GUI 里 torch 不存在的事实。
    monkeypatch.setitem(sys.modules, "torch", None)

    result = asr.transcribe_qwen_reference("media.mp3", [], shared_audio=[0.0])

    assert result == references
