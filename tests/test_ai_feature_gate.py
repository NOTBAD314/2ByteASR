"""AI-only features wait for a key and a passed 测试连接 (2026-10-22).

User: without an API key and a tested connection, 术语库校对 and 联网补充核验
are dark grey and say a key is needed, and the subtitles can only show the
original (translation needs the AI). Punctuation is local and stays free.
The test result is remembered by a fingerprint (never the key itself).
"""
import copy
import json

import pytest

DEEPSEEK = dict(ai_service='deepseek', polish_provider='deepseek', group_provider='deepseek',
                polish_transport='openai_compatible', group_transport='openai_compatible',
                polish_model='deepseek-chat', group_model='deepseek-chat',
                polish_base_url='https://api.deepseek.com/v1', group_base_url='https://api.deepseek.com/v1')


def _settings(**switches):
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.setdefault('models', {}).update(DEEPSEEK)
    settings.setdefault('switches', {}).update(switches)
    return settings


@pytest.fixture
def keys(monkeypatch):
    """The DeepSeek key as the scoped DPAPI store would return it."""
    from twobyteasr.providers import llm_config
    stored = {}
    monkeypatch.setattr(llm_config, 'read_scoped_api_key',
                        lambda provider, base_url='': (stored.get(provider, ''), 'test' if stored.get(provider) else ''))
    monkeypatch.setattr(llm_config, 'resolve_api_key', lambda stage: ('', ''))
    return stored


def test_a_passed_test_is_remembered_by_service_model_and_key_never_the_key_itself(keys):
    from twobyteasr.providers import ai_connection_record as record
    keys['deepseek'] = 'sk-first-key-0001'
    settings = _settings()
    assert record.result_for(settings) is None
    record.remember(settings, 'polish', True)
    assert record.result_for(settings) is True
    text = record.record_path().read_text(encoding='utf-8')
    assert 'sk-first-key-0001' not in text and json.loads(text)['version'] == 1
    keys['deepseek'] = 'sk-second-key-0002'            # another key: not tested
    assert record.result_for(settings) is None
    keys['deepseek'] = 'sk-first-key-0001'
    other_model = _settings()
    other_model['models'].update(polish_model='deepseek-reasoner', group_model='deepseek-reasoner')
    assert record.result_for(settings) is True
    assert record.fingerprint(other_model) != record.fingerprint(settings)
    record.remember(settings, 'polish', False)          # a later failure counts
    assert record.result_for(settings) is False


def test_the_gate_says_why(keys):
    from twobyteasr.providers import ai_connection_record as record
    assert record.feature_gate(_settings()) == record.NO_KEY
    # Switched off without a key: the key is what is missing.
    assert record.feature_gate(_settings(enable_ai_polish=False, use_ai_grouping=False)) == record.NO_KEY
    keys['deepseek'] = 'sk-test-gate'
    assert record.feature_gate(_settings(enable_ai_polish=False, use_ai_grouping=False)) == record.OFF
    assert record.feature_gate(_settings()) == record.UNTESTED
    record.remember(_settings(), 'polish', False)
    assert record.feature_gate(_settings()) == record.FAILED
    record.remember(_settings(), 'polish', True)
    assert record.feature_gate(_settings()) == record.READY


def test_a_test_in_the_shared_form_unlocks_translation_and_glossary(keys):
    """One service for both stages (the default): AI 设置 shows only the 断句 form; its test counts."""
    from twobyteasr.providers import ai_connection_record as record
    keys['deepseek'] = 'sk-shared-form'
    settings = _settings(unified_glm_processing=True)
    record.remember(settings, 'group', True)
    assert record.feature_gate(settings) == record.READY


def test_the_editor_remembers_its_connection_test(keys, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from twobyteasr.providers import ai_connection_record as record
    from twobyteasr.providers.endpoint_editor_ui import EndpointEditor
    keys['deepseek'] = 'sk-editor-test'
    settings = _settings()
    editor = EndpointEditor('字幕校对模型', '#e39a73', 'polish', settings)
    seen = []
    editor.connection_tested.connect(seen.append)
    editor._connection_finished(True, '连接正常')
    assert seen == [True] and editor.last_connection_ok is True
    assert record.result_for(settings, 'polish') is True
    editor.deleteLater()


# ---------------------------------------------------------------- the home page

@pytest.fixture
def window(keys, monkeypatch):
    import subtitle_core
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'models',
                        {**subtitle_core.RUNTIME_SETTINGS.get('models', {}), **DEEPSEEK})
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'switches',
                        {**subtitle_core.RUNTIME_SETTINGS.get('switches', {}),
                         'enable_ai_polish': True, 'use_ai_grouping': True})
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'subtitle_language',
                        {'recognition_language': 'ja', 'output': 'bilingual', 'translation_script': 'zh-Hans'})
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'glossary',
                        {**subtitle_core.RUNTIME_SETTINGS.get('glossary', {}), 'enable_domain_terms': True})
    monkeypatch.setattr(ui, 'save_runtime_settings', lambda settings: None)
    win = ui.MainWindow([], subtitle_core, object(), None)
    yield win
    win.close()
    win.deleteLater()
    app.processEvents()


def test_local_glossary_is_independent_while_translation_waits_for_a_tested_service(window, keys):
    from twobyteasr.providers import ai_connection_record as record
    w = window
    w._refresh_home_process_facts()
    assert w._ai_gate_state == record.NO_KEY
    assert w.terms.isEnabled() and w.terms.isChecked()
    assert not w.term_search.isEnabled() and not w.term_search.isChecked()
    assert 'API Key' not in w.term_state_label.text() and not w.terms_unlock_button.isHidden()
    output = w.subtitle_output
    assert output.currentData() == 'original'
    locked = [output.model().item(i).isEnabled() for i in range(output.count())]
    assert locked == [True, False, False] and '文字服务未就绪' in output.itemText(1)
    assert w.subtitle_punctuation.isEnabled()                       # punctuation is local: never locked
    assert w._task_glossary_selection()[1] is True
    assert w._subtitle_language_options()['subtitle_output'] == 'original'
    # The saved choices are kept while locked, even when something else is saved.
    w.recognition_language.setCurrentIndex(w.recognition_language.findData('en'))
    w._save_glossary_settings()
    assert w.legacy.RUNTIME_SETTINGS['subtitle_language']['output'] == 'bilingual'
    assert w.legacy.RUNTIME_SETTINGS['glossary']['enable_domain_terms'] is True
    assert '翻译' in w.subtitle_language_hint.text()
    # A key that was never tested: the home card offers 测试连接.
    keys['deepseek'] = 'sk-home-test'
    w._refresh_home_process_facts()
    assert w._ai_gate_state == record.UNTESTED and not w.home_ai_test_button.isHidden()
    assert w.terms.isEnabled()
    # A passed test (remembered): everything comes back as it was chosen.
    record.remember(w.legacy.RUNTIME_SETTINGS, 'polish', True)
    w._refresh_home_process_facts()
    assert w._ai_gate_state == record.READY and w.home_ai_test_button.isHidden()
    assert w.terms.isEnabled() and w.terms.isChecked() and w.term_search.isEnabled()
    assert w.terms_unlock_button.isHidden()
    assert output.currentData() == 'bilingual' and all(output.model().item(i).isEnabled() for i in range(3))
    assert 'API Key' not in output.itemText(1)
    assert w._subtitle_language_options()['subtitle_output'] == 'bilingual'
