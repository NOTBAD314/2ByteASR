"""Execute the source Qwen worker contract with an owned double, without weights."""
from types import SimpleNamespace

import numpy as np


def test_source_qwen_context_audit_does_not_shadow_runtime_recorder(monkeypatch, tmp_path):
    import hashlib
    import json
    import sys
    from pathlib import Path
    from twobyteasr.recognition import asr, cache

    events = []
    requests = []
    context = "用户已确认的专名写法：autumn、DB CHICHOO。"
    chunk = dict(start=0.0, end=1.0, audio=(np.zeros(16000, dtype=np.float32), 16000))

    def worker_contract_double(command, output, **metadata):
        manifest = json.loads(Path(command[command.index("--manifest") + 1]).read_text("utf8"))
        requests.append(manifest)
        job = manifest["jobs"][0]
        actual_pcm = np.load(job["path"], allow_pickle=False)
        assert np.array_equal(actual_pcm, chunk["audio"][0])
        assert metadata["entrypoint"] == "qwen_asr_worker.py"
        return {"policy": manifest["policy"], "results": [{"segment_id": job["segment_id"],
            "text": "autumn在这个位置", "confidence": 0.8,
            "start": job["start"], "end": job["end"], "samples": int(actual_pcm.size),
            "pcm_sha256": hashlib.sha256(actual_pcm.tobytes()).hexdigest(),
            "context_sha256": hashlib.sha256(job["context"].encode("utf8")).hexdigest()}]}

    monkeypatch.setattr(asr, "_legacy_runtime_value", lambda name, default: {"USE_QWEN_ASR_REFERENCE": True, "QWEN_ASR_BACKEND": "local"}.get(name, default))
    monkeypatch.setattr(asr, "build_qwen_asr_chunks", lambda *a, **k: [chunk])
    monkeypatch.setattr(asr, "build_qwen_asr_context", lambda path: context)
    monkeypatch.setattr(asr, "resolve_qwen_asr_local_source", lambda: str(tmp_path))
    monkeypatch.setattr(asr, "_main_worker_python", lambda: sys.executable)
    monkeypatch.setattr(asr, "media_cache_context", lambda path: {"cache_dir": str(tmp_path)})
    monkeypatch.setattr(asr, "_run_isolated_asr_worker", worker_contract_double)
    monkeypatch.setattr(asr, "_raise_if_queue_cancelled", lambda: None)
    monkeypatch.setattr(asr.sys, "frozen", False, raising=False)
    recorder = lambda event, **payload: events.append((event, payload))
    monkeypatch.setattr(cache, "record_run_event", recorder)
    monkeypatch.setattr(asr, "record_run_event", recorder)

    rows = asr.transcribe_qwen_reference(str(tmp_path / "source.wav"), [dict(start=0.0, end=1.0)], chunk["audio"][0])

    assert rows and rows[0]["text"] == "autumn在这个位置"
    assert requests[0]["jobs"][0]["context"] == context
    scope = next(payload for name, payload in events if name == "asr_review_scope")
    assert scope["reason"].startswith("vad_speech_windows")
    assert "confidence_placeholder" in scope["reason"]
    assert scope["chunk_count"] == 1
    receipt = next(payload for name, payload in events if name == "asr_terminology_input")
    assert receipt["context_sent"] is True
    assert receipt["prompt_version"] == "custom-context"
    assert receipt["content_scene"] == {}
    assert events[-1][0] == "qwen_native_windows"
    assert events[-1][1]["window_count"] == 1
    assert events[-1][1]["context_sha256"] == hashlib.sha256(context.encode("utf8")).hexdigest()
    saved = json.loads((tmp_path / "speaker-evidence/qwen-native-windows.json").read_text("utf8"))
    assert saved["context"] == context
    assert saved["raw_worker_payload"]["results"][0]["text"] == rows[0]["text"]


def test_moss_audit_observes_actual_processor_audio_without_second_decode():
    from moss_worker import AudioInputAudit

    waveform = np.zeros(1082453, dtype=np.float32)
    calls = []
    observations = []

    class Processor:
        feature_extractor = SimpleNamespace(sampling_rate=16000)
        def apply_chat_template(self, *args, **kwargs): return "original-template"
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return "original-features"

    audit = AudioInputAudit(Processor(), observations.append)
    assert audit.apply_chat_template([]) == "original-template"
    assert audit(text="original", audio=[waveform]) == "original-features"
    assert audit(text="original", audio=[waveform]) == "original-features"
    assert calls[0]["audio"][0] is waveform
    assert len(observations) == 1
    assert observations[0]["sample_counts"] == [1082453]
    assert observations[0]["audio_seconds"] == [67.6533125]
    assert observations[0]["clock"] == "decoded_pcm_samples"
