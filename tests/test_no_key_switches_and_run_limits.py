"""No API key → AI 校对 / AI 断句 shown off; the pre-run “确定要继续吗” (2026-10-21).

User: many people do not want to fill in a key for AI line breaks; without one
those steps are off by default (local line-break rules), and before a run a
box says when AI 断句 cannot be used for lack of a key or when there are no
word-level timestamps (only the primary transcription).
"""
import copy
from types import SimpleNamespace

import pytest

DEEPSEEK = dict(service='deepseek', provider='deepseek', transport='openai_compatible', model='deepseek-chat',
                base_url='https://api.deepseek.com/v1', protocol='auto')
BAILIAN = dict(service='bailian', provider='bailian', transport='openai_compatible', model='qwen-plus',
               base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', protocol='auto')


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _legacy():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    return SimpleNamespace(RUNTIME_SETTINGS=copy.deepcopy(DEFAULT_SETTINGS))


def _keys(monkeypatch, stored):
    from twobyteasr.app import ui
    monkeypatch.setattr(ui, 'read_api_key', lambda provider, base_url='': (stored.get(provider, ''), 'test'))
    monkeypatch.setattr(ui, 'resolve_api_key', lambda stage: ('', ''))


# ---------------------------------------------------------------- which step lacks a key

def test_without_any_key_both_steps_lack_one_whatever_the_switches(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {})
    for unified in (False, True):
        assert ui.text_ai_roles_without_key(_legacy(), dict(DEEPSEEK), dict(DEEPSEEK),
                                            unified=unified, share_key=False) == ('polish', 'group')


def test_a_saved_or_typed_key_counts(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {'bailian': 'sk-test-group'})
    assert ui.text_ai_roles_without_key(_legacy(), dict(DEEPSEEK), dict(BAILIAN),
                                        unified=False, share_key=False) == ('polish',)
    # Unified: one editor (the group one) serves both steps.
    assert ui.text_ai_roles_without_key(_legacy(), dict(DEEPSEEK), dict(BAILIAN),
                                        unified=True, share_key=False) == ()
    _keys(monkeypatch, {})
    typed = dict(DEEPSEEK, key='sk-typed')
    assert ui.text_ai_roles_without_key(_legacy(), typed, dict(DEEPSEEK), unified=False, share_key=True) == ()
    assert ui.text_ai_roles_without_key(_legacy(), typed, dict(DEEPSEEK), unified=False, share_key=False) == ('group',)


def test_a_cli_login_never_lacks_a_key(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {})
    cli = dict(DEEPSEEK, transport='codex_cli')
    assert ui.text_ai_roles_without_key(_legacy(), cli, cli, unified=False, share_key=False) == ()


# ---------------------------------------------------------------- the switch shows off, keeps the choice

def test_a_forced_off_switch_keeps_its_choice_and_shows_it_again():
    _app()
    from twobyteasr.design.ui_widgets import SwitchControl
    switch = SwitchControl('全文断句使用 AI')
    switch.setChecked(True)
    switch.set_forced_off(True)
    assert switch.isChecked() and not switch.is_shown_on() and not switch.isEnabled()
    assert switch._progress == 0.0
    switch.set_forced_off(False)
    assert switch.is_shown_on() and switch.isEnabled() and switch._progress == 1.0
    switch.setChecked(False)
    switch.set_forced_off(True)
    switch.set_forced_off(False)
    assert not switch.isChecked() and switch.isEnabled()
    switch.deleteLater()


def _sync_window(monkeypatch, missing, *, polish_on=True, group_on=True):
    _app()
    from PySide6.QtWidgets import QLabel
    from twobyteasr.app import ui
    from twobyteasr.design.ui_widgets import SwitchControl
    monkeypatch.setattr(ui, 'text_ai_roles_without_key', lambda *a, **k: tuple(missing))
    window = ui.MainWindow.__new__(ui.MainWindow)
    window.legacy = _legacy()
    window.polish_editor = SimpleNamespace(values=lambda: dict(DEEPSEEK))
    window.group_editor = SimpleNamespace(values=lambda: dict(DEEPSEEK))
    window.unified_glm = SimpleNamespace(isChecked=lambda: True)
    window.share_key = SimpleNamespace(isChecked=lambda: True)
    window.ai_polish, window.ai_grouping = SwitchControl('校对'), SwitchControl('断句')
    window.ai_polish.setChecked(polish_on)
    window.ai_grouping.setChecked(group_on)
    window.ai_key_off_note = QLabel()
    return window


def test_without_a_key_both_switches_show_off_with_the_reason_and_the_choice_stays(monkeypatch):
    window = _sync_window(monkeypatch, ('polish', 'group'))
    assert window._sync_ai_switches_with_keys() == ('polish', 'group')
    assert window.ai_polish.isChecked() and window.ai_grouping.isChecked()          # the saved choice
    assert window.ai_polish.is_forced_off() and window.ai_grouping.is_forced_off()  # shown off, locked
    assert not window.ai_key_off_note.isHidden() and '本地规则' in window.ai_key_off_note.text()


def test_a_key_lifts_the_lock_and_the_saved_choice_shows_again(monkeypatch):
    window = _sync_window(monkeypatch, ('polish', 'group'))
    window._sync_ai_switches_with_keys()
    from twobyteasr.app import ui
    monkeypatch.setattr(ui, 'text_ai_roles_without_key', lambda *a, **k: ())
    assert window._sync_ai_switches_with_keys() == ()
    assert window.ai_polish.is_shown_on() and window.ai_grouping.is_shown_on()
    assert window.ai_key_off_note.isHidden()


def test_only_the_step_without_a_key_is_locked_and_a_switch_turned_off_stays_free(monkeypatch):
    window = _sync_window(monkeypatch, ('group',))
    assert window._sync_ai_switches_with_keys() == ('group',)
    assert window.ai_polish.is_shown_on() and window.ai_grouping.is_forced_off()
    assert window.ai_key_off_note.text().startswith('全文断句模型')
    # A step the user switched off is just off: nothing to unlock, no note.
    window = _sync_window(monkeypatch, ('polish', 'group'), polish_on=False, group_on=False)
    assert window._sync_ai_switches_with_keys() == ()
    assert window.ai_polish.isEnabled() and window.ai_grouping.isEnabled() and window.ai_key_off_note.isHidden()


# ---------------------------------------------------------------- word-level timestamps

def _settings(**models):
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings['models'].update(models)
    return settings


def test_word_timing_comes_from_a_timeline_model_or_a_cloud_model_that_returns_words():
    from twobyteasr.providers.api_setup_catalog import guide_for, model_choice
    from twobyteasr.recognition.recognition_choices import run_disclosure
    assert run_disclosure(_settings(primary_asr_backend='moss', firered_asr_backend='local'))['word_timing']
    assert run_disclosure(_settings(primary_asr_backend='sensevoice', firered_asr_backend='qwen_aligner'))['word_timing']
    assert not run_disclosure(_settings(primary_asr_backend='moss', firered_asr_backend='off'))['word_timing']
    assert not run_disclosure(_settings(primary_asr_backend='sensevoice', firered_asr_backend='off'))['word_timing']
    moss = guide_for('mosi_moss_pro', 'asr')
    assert model_choice(moss, 'moss-transcribe-diarize-pro').timestamps == 'segment'
    cloud = dict(primary_asr_backend='api', qwen_asr_api_provider='mosi_moss_pro',
                 qwen_asr_api_model='moss-transcribe-diarize-pro', qwen_asr_api_url='https://studio.mosi.cn/v1')
    assert not run_disclosure(_settings(**cloud, firered_asr_backend='off'))['word_timing']
    assert run_disclosure(_settings(**cloud, firered_asr_backend='local'))['word_timing']
    qwen = guide_for('qwen31_filetrans', 'asr')
    word_model = next(choice.model for choice in qwen.models if choice.timestamps == 'word')
    assert run_disclosure(_settings(primary_asr_backend='api', qwen_asr_api_provider='qwen31_filetrans',
                                    qwen_asr_api_model=word_model, firered_asr_backend='off'))['word_timing']


# ---------------------------------------------------------------- 开始前请确认

class _Store(dict):
    def value(self, key, default=None, type=None):
        return self.get(key, default)

    def setValue(self, key, value):
        self[key] = value


def _run_window(monkeypatch, roles, timeline):
    from twobyteasr.app import ui
    window = ui.MainWindow.__new__(ui.MainWindow)
    window.legacy = _legacy()
    window._text_ai_local_roles = tuple(roles)
    window._asr_values = lambda: {'primary_asr_backend': 'moss', 'firered_asr_backend': timeline,
                                  'qwen_asr_backend': 'off'}
    window.console = []
    window._append_console_line = window.console.append
    window.store = _Store()
    window._progress_settings = lambda: window.store
    return window


def _box(monkeypatch, answer, *, remember=False):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from twobyteasr.app import ui
    shown = []

    class Box(QMessageBox):
        def __init__(self, _parent=None):
            super().__init__()

        def exec(self):
            shown.append(dict(title=self.windowTitle(), text=self.informativeText(),
                              buttons=[b.text() for b in self.buttons()]))
            self.checkBox().setChecked(remember)
            next(b for b in self.buttons() if b.text() == answer).click()
            return 0
    monkeypatch.setattr(ui, 'QMessageBox', Box)
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT', raising=False)
    return shown


def test_the_limits_name_the_missing_key_and_the_missing_word_times(monkeypatch):
    window = _run_window(monkeypatch, ('polish', 'group'), 'off')
    lines = window._run_limit_lines()
    assert len(lines) == 2 and '无法启用 AI 断句和 AI 校对' in lines[0] and '没有字级时间戳' in lines[1]
    assert _run_window(monkeypatch, ('group',), 'local')._run_limit_lines()[0].startswith('全文断句模型没填')
    assert _run_window(monkeypatch, (), 'local')._run_limit_lines() == []


def test_nothing_is_asked_when_the_run_has_ai_and_word_times(monkeypatch):
    shown = _box(monkeypatch, '继续生成')
    window = _run_window(monkeypatch, (), 'local')
    assert window._confirm_run_limits() is True and shown == [] and window.console == []


def test_continue_starts_and_cancel_does_not(monkeypatch):
    shown = _box(monkeypatch, '继续生成')
    window = _run_window(monkeypatch, ('polish', 'group'), 'off')
    assert window._confirm_run_limits() is True
    assert shown[0]['title'] == '开始前请确认' and '确定要继续吗' in shown[0]['text']
    assert set(shown[0]['buttons']) == {'继续生成', '去填 API Key', '取消'}
    assert sum('[开始前提醒]' in line for line in window.console) == 2
    shown = _box(monkeypatch, '取消')
    window = _run_window(monkeypatch, ('polish', 'group'), 'off')
    assert window._confirm_run_limits() is False
    assert '已取消' in window._run_block_reason and '已取消' in window.console[-1]


def test_word_times_only_box_offers_no_key_button(monkeypatch):
    shown = _box(monkeypatch, '继续生成')
    window = _run_window(monkeypatch, (), 'off')
    assert window._confirm_run_limits() is True
    assert set(shown[0]['buttons']) == {'继续生成', '取消'} and '没有字级时间戳' in shown[0]['text']


def test_add_key_opens_the_ai_settings_and_does_not_start(monkeypatch):
    from twobyteasr.app import ui
    _box(monkeypatch, '去填 API Key')
    later = []
    monkeypatch.setattr(ui, 'QTimer', SimpleNamespace(singleShot=lambda _ms, _ctx, call: later.append(call)))
    window = _run_window(monkeypatch, ('group',), 'local')
    window._open_ai_settings_dialog = lambda: None
    assert window._confirm_run_limits() is False
    assert later == [window._open_ai_settings_dialog]


def test_remember_skips_the_same_situation_only(monkeypatch):
    shown = _box(monkeypatch, '继续生成', remember=True)
    window = _run_window(monkeypatch, ('polish', 'group'), 'off')
    assert window._confirm_run_limits() is True and len(shown) == 1
    assert window._confirm_run_limits() is True and len(shown) == 1          # remembered
    window._asr_values = lambda: {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local'}
    assert window._confirm_run_limits() is True and len(shown) == 2          # a different situation asks


def test_a_test_root_logs_the_limits_without_a_box(monkeypatch, tmp_path):
    shown = _box(monkeypatch, '取消')
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path))
    window = _run_window(monkeypatch, ('polish', 'group'), 'off')
    assert window._confirm_run_limits() is True and shown == []
    assert len(window.console) == 2


def test_an_analysis_run_is_never_asked(monkeypatch):
    shown = _box(monkeypatch, '取消')
    window = _run_window(monkeypatch, ('polish', 'group'), 'off')
    window._studio_recognition_context = {'recognition_purpose': 'analysis'}
    assert window._confirm_run_limits() is True and shown == []


@pytest.mark.parametrize('key', ['AI 断句和校对已关闭', '开始前请确认', '继续生成', '去填 API Key',
                                 '同样的情况以后不再提醒', '这次生成字幕有以下限制：'])
def test_new_strings_have_every_ui_language(key):
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'twobyteasr' / 'locales'
    for language in ('en', 'ja', 'ko', 'es', 'de', 'fr', 'pt', 'it', 'ru', 'zh-Hant'):
        table = json.loads((root / f'{language}.json').read_text(encoding='utf-8'))
        assert table.get(key), (language, key)
