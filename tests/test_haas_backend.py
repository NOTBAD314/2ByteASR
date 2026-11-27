"""Contracts for the fixed Japanese model and its native clock."""
import pytest

from twobyteasr.recognition.asr_capabilities import LOCAL, issue
from twobyteasr.recognition.haas_backend import configuration, parse_transcription


def test_haas_rejects_unknown_or_other_primary_languages():
    item = LOCAL['haas_ja']
    assert item.languages == {'ja'} and item.manual_field is None
    assert not issue('haas_ja', 'ja')
    for language in ('en', 'zh', 'auto'):
        assert issue('haas_ja', language, strict=False)


def test_haas_offsets_are_milliseconds_and_fallback_ticks_are_centiseconds():
    payload = {'crispasr': {'language': 'en'}, 'transcription': [
        {'text': '日本語', 'offsets': {'from': 100, 'to': 660}, 'words': [
            {'text': '日', 'offsets': {'from': 100, 'to': 220}, 't0': 1, 't1': 2},
            {'text': '本', 't0': 22, 't1': 56},
            {'text': '語', 't0': 56, 't1': 66},
            {'text': '。', 't0': 66, 't1': 66},
        ]},
    ]}
    row, = parse_transcription(payload, 160000, 176000)
    assert row['text'] == '日本語'
    assert row['start'] == pytest.approx(10.1)
    assert row['end'] == pytest.approx(10.66)
    assert 'language' not in row
    assert [token['text'] for token in row['tokens']] == ['日', '本', '語']
    assert [token['start'] for token in row['tokens']] == pytest.approx([10.1, 10.22, 10.56])


def test_haas_missing_or_out_of_range_clock_fails_and_silence_stays_empty():
    assert parse_transcription({'transcription': []}, 0, 16000) == []
    with pytest.raises(ValueError, match='PCM'):
        parse_transcription({'transcription': [{'text': '日本語', 't0': 0, 't1': 120}]}, 0, 16000)
    with pytest.raises(ValueError, match='transcription'):
        parse_transcription({}, 0, 16000)


def test_haas_variant_identity_is_frozen_in_primary_and_review_caches():
    from twobyteasr.recognition.cache import cache_stage_signature
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context

    def signatures(precision, device):
        models = {'haas_quantization': precision, 'haas_device': device, 'qwen_asr_backend': 'haas_ja'}
        context = RuntimeContext(asr_settings_snapshot={'models': models}, requested_language='ja')
        with activate_runtime_context(context):
            return tuple(cache_stage_signature(stage) for stage in ('primary_haas_ja', 'qwen'))

    assert signatures('q8_0', 'cpu') != signatures('q4_k', 'cpu')
    assert signatures('q8_0', 'cpu') != signatures('q8_0', 'cuda')
    assert configuration({}).model_key == 'haas_ja_q8_0'


def test_workshop_requires_current_inference_for_selected_precision_and_device(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from twobyteasr.local_models import haas_preparation as setup
    from twobyteasr.local_models import haas_runtime

    model_root = tmp_path / 'Models'
    monkeypatch.setattr(setup, 'get_runtime_paths', lambda: SimpleNamespace(
        model_root=model_root, user_data_root=tmp_path))
    cpu = tmp_path / 'cpu' / 'crispasr.exe'
    cpu.parent.mkdir()
    monkeypatch.setattr(setup, 'runtime_executable', lambda device: cpu if device == 'cpu' else None)
    for name in haas_runtime.runtime_files('cpu'):
        cpu.with_name(name).write_bytes(b'fixture')
    config = configuration({})
    weight = setup._model_path(config)
    weight.parent.mkdir(parents=True)
    weight.write_bytes(b'fixture')
    assert setup.readiness(config) == 'inference_pending'
    receipt = setup._receipt(config)
    receipt.parent.mkdir()
    receipt.write_text(json.dumps(dict(inference_verified=True, identity=setup._identity(config))), 'utf-8')
    assert setup.readiness(config) == 'installed'
    assert setup.readiness(configuration({'models': {'haas_device': 'cuda'}})) == 'runtime_missing'
    weight.write_bytes(b'changed size')
    assert setup.readiness(config) == 'inference_pending'
    cpu.with_name('openblas.dll').unlink()
    assert setup.readiness(config) == 'runtime_missing'


def test_workshop_has_one_haas_card_with_three_pinned_downloads():
    from twobyteasr.local_models.model_workshop import CANONICAL_MODEL_ORDER, MODELS
    from twobyteasr.model_integrity import load_dependency_lock
    from twobyteasr.recognition.haas_backend import VARIANTS

    card, = [item for item in MODELS if item.key == 'haas_ja']
    assert CANONICAL_MODEL_ORDER.count(card.key) == 1
    assert dict(card.adapter_bindings) == {'primary':'haas_ja', 'review':'haas_ja', 'timeline':'haas_native'}
    entries = [load_dependency_lock()['models'][key] for key in VARIANTS.values()]
    assert len({entry['path'] for entry in entries}) == 3
    assert all(len(entry['required_files']) == 1 and entry['sha256'] for entry in entries)


def test_completed_haas_batch_resumes_without_redecoding(monkeypatch, tmp_path):
    import numpy as np
    from twobyteasr.recognition import haas_backend
    from twobyteasr.recognition.run_context import RuntimeContext
    from twobyteasr.storage import storage_service

    choices = configuration({})
    spans = [(0, 1600)]
    pcm = np.zeros(1600, dtype='float32')
    context = RuntimeContext(requested_language='ja')
    calls = []
    monkeypatch.setattr(storage_service, 'register_cache', lambda *args, **kwargs: None)
    monkeypatch.setattr(haas_backend, '_decode_batch',
                        lambda *args: calls.append(args[1]) or [{'start': 0., 'text': '日本語'}])

    def decode():
        return haas_backend._decode_or_resume(pcm, spans, choices, None, None, lambda: None, tmp_path, context)

    assert decode() == decode()
    assert calls == [spans]
    pcm[-1] = 0.5
    assert decode()
    assert calls == [spans, spans]


def test_haas_review_dispatch_uses_task_language_and_shared_audio(monkeypatch):
    from twobyteasr.recognition import asr, haas_backend
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context

    audio = object()
    spans = [{'start': 0., 'end': 1.}]
    calls = []
    monkeypatch.setattr(haas_backend, 'transcribe',
                        lambda data, regions, context: calls.append((data, regions, context.requested_language))
                        or [{'text': '日本語'}])
    with activate_runtime_context(RuntimeContext(requested_language='ja')):
        assert asr.transcribe_qwen_reference('fixture.wav', spans, audio, backend_override='haas_ja')
    with activate_runtime_context(RuntimeContext(requested_language='en')):
        assert asr.transcribe_qwen_reference('fixture.wav', spans, audio, backend_override='haas_ja') == []
    assert calls == [(audio, spans, 'ja')]
