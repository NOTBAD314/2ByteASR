"""Retired model identities cannot install or run; other selections survive."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REMOVED = {'diarizen', 'diarizen_embedding', 'vibevoice_1_5b', 'vibevoice_7b'}


def test_active_inventory_has_no_removed_models_and_preserves_remaining_contracts():
    from twobyteasr.local_models.model_workshop import MODELS
    from twobyteasr.system.runtime_registry import RUNTIME_ROLES
    lock = json.loads((ROOT/'dependencies.lock.json').read_text('utf-8-sig'))
    assert not REMOVED.intersection(lock['models'])
    assert not {'diarizen','vibevoice'}.intersection(m.key for m in MODELS)
    assert not {'diarizen','vibevoice'}.intersection(RUNTIME_ROLES)
    assert {'moss','firered_aed','qwen_asr'}.issubset(lock['models'])


@pytest.mark.parametrize('key', ['vibevoice_1_5b', 'vibevoice_7b'])
def test_removed_inference_rejected_before_dispatch(key):
    from twobyteasr.recognition.asr import transcribe_primary_reference
    with pytest.raises(RuntimeError, match='已移除'):
        transcribe_primary_reference(key, None, (), None, 0)


@pytest.mark.parametrize('key', sorted(REMOVED))
def test_old_download_request_rejected_before_preparation(key, tmp_path):
    from twobyteasr.repository_download import download_model
    with pytest.raises(ValueError, match='removed'):
        download_model(model_key=key, spec={}, destination=tmp_path/'model', mode='auto', staging_root=tmp_path/'downloads')
    assert not list(tmp_path.iterdir())


def test_current_moss_fire_qwen_settings_preserved_and_removed_selection_migrates():
    from twobyteasr.storage.settings import _merge_known_settings, DEFAULT_SETTINGS
    from twobyteasr.recognition.speaker_strategy import resolve
    source = {'models': {'primary_asr_backend':'moss', 'qwen_asr_backend':'local',
                        'firered_asr_backend':'local', 'speaker_source':'moss'}}
    settings, warnings = _merge_known_settings(DEFAULT_SETTINGS, source)
    for key, value in source['models'].items():
        assert settings['models'][key] == value
    source['models']['primary_asr_backend'] = 'vibevoice_7b'
    source['models']['speaker_source'] = 'diarizen'
    settings, warnings = _merge_known_settings(DEFAULT_SETTINGS, source)
    assert settings['models']['primary_asr_backend'] == 'moss'
    assert settings['models']['qwen_asr_backend'] == 'local'
    assert settings['models']['firered_asr_backend'] == 'local'
    assert resolve(settings) == 'moss'
    assert any('primary_asr_backend' in warning for warning in warnings)
