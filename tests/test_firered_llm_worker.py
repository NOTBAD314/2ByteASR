from __future__ import annotations

import ast
import inspect
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_firered_llm_worker_is_isolated_and_releases_cuda():
    source = (ROOT / "firered_llm_worker.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "verify_model_files(\"firered_llm\"" in source
    assert "torch.cuda.empty_cache()" in source
    assert "torch.cuda.ipc_collect()" in source
    assert "FireRedAsr2.from_pretrained(\"llm\"" in source
    assert any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in ast.walk(tree))


def test_firered_llm_worker_refuses_empty_transcripts():
    source = (ROOT / "firered_llm_worker.py").read_text(encoding="utf-8")
    assert "returned empty text" in source


def test_production_adapter_uses_only_the_isolated_interpreter():
    from twobyteasr.recognition import asr

    source = inspect.getsource(asr._run_firered_llm_worker)
    assert 'resolve_runtime_python("firered_llm")' in source
    assert "sys.executable" not in source
    assert ".venv-main" not in source


def test_primary_firered_llm_routes_to_isolated_adapter(monkeypatch):
    from twobyteasr.recognition import asr

    expected = [{"start": 0.0, "end": 1.0, "text": "主力证据"}]
    calls = []
    monkeypatch.setattr(
        asr,
        "transcribe_firered_llm_reference",
        lambda audio_path, speech_regions, shared_audio: calls.append(
            (audio_path, speech_regions, shared_audio)
        )
        or expected,
    )

    result = asr.transcribe_primary_reference(
        "firered_llm", "fixture.wav", [{"start": 0.0, "end": 1.0}], "audio", 1.0
    )

    assert result == expected
    assert calls == [("fixture.wav", [{"start": 0.0, "end": 1.0}], "audio")]


def test_review_firered_llm_routes_to_isolated_adapter(monkeypatch):
    from twobyteasr.recognition import asr

    expected = [{"start": 0.0, "end": 1.0, "text": "复核证据"}]
    calls = []
    monkeypatch.setattr(
        asr,
        "transcribe_firered_llm_reference",
        lambda audio_path, speech_regions, shared_audio: calls.append(
            (audio_path, speech_regions, shared_audio)
        )
        or expected,
    )

    result = asr.transcribe_qwen_reference(
        "fixture.wav",
        [{"start": 0.0, "end": 1.0}],
        "audio",
        backend_override="firered_llm",
    )

    assert result == expected
    assert calls == [("fixture.wav", [{"start": 0.0, "end": 1.0}], "audio")]
