import pytest
from twobyteasr.app import ui


@pytest.mark.parametrize('language,expected', [('en', 'qwen_aligner'), ('ja', 'qwen_aligner'),
                                                ('zh', 'local'), ('auto', 'local')])
def test_language_preflight_does_not_change_saved_timeline(language, expected):
    selected = {'primary_asr_backend': 'api', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}
    effective = ui._language_preflight_values(selected, language, {})
    assert effective['firered_asr_backend'] == expected
    assert selected['firered_asr_backend'] == 'local'


def test_english_gate_checks_aligner_not_firered(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, 'installed_model_keys', lambda root: {'qwen_aligner'})
    values = ui._language_preflight_values({'primary_asr_backend': 'api',
                                           'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}, 'en', {})
    assert ui.missing_selected_local_models(values, tmp_path) == ()
    monkeypatch.setattr(ui, 'installed_model_keys', lambda root: {'firered_aed'})
    assert any('qwen_aligner' in message for message in ui.missing_selected_local_models(values, tmp_path))
