"""No API key → local rules; the picture explainer; the two-part tutorial (2026-10-15).

User feedback: people who do not want to fill in an API key could not get
subtitles out, many do not know what a key is or that it needs credit, and the
tutorial had too much to read.
"""
import copy
import json
import re
from types import SimpleNamespace

import pytest

DEEPSEEK = dict(service='deepseek', provider='deepseek', transport='openai_compatible', model='deepseek-chat',
                base_url='https://api.deepseek.com/v1', protocol='auto')
BAILIAN = dict(service='bailian', provider='bailian', transport='openai_compatible', model='qwen-plus',
               base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', protocol='auto')


def _legacy():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    return SimpleNamespace(RUNTIME_SETTINGS=copy.deepcopy(DEFAULT_SETTINGS))


def _keys(monkeypatch, stored):
    from twobyteasr.app import ui
    monkeypatch.setattr(ui, 'read_api_key', lambda provider, base_url='': (stored.get(provider, ''), 'test'))
    monkeypatch.setattr(ui, 'resolve_api_key', lambda stage: ('', ''))


# ---------------------------------------------------------------- no key → local rules

def test_without_any_key_a_run_start_uses_the_local_rules_instead_of_refusing(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {})
    with pytest.raises(RuntimeError, match='API'):   # the old refusal, still what a plain ready-check says
        ui.persist_ai_configuration(_legacy(), dict(DEEPSEEK), dict(DEEPSEEK), unified=False, share_key=False,
                                    require_ready=True, dry_run=True)
    values = ui.persist_ai_configuration(_legacy(), dict(DEEPSEEK), dict(DEEPSEEK), unified=False, share_key=False,
                                         require_ready=True, dry_run=True, local_without_key=True)
    assert values['local_roles'] == ('polish', 'group')
    assert values['missing_keys'] == ('字幕校对模型', '全文断句模型')
    unified = ui.persist_ai_configuration(_legacy(), dict(DEEPSEEK), dict(DEEPSEEK), unified=True, share_key=False,
                                          require_ready=True, dry_run=True, local_without_key=True)
    assert unified['local_roles'] == ('polish', 'group')


def test_only_the_step_without_a_key_runs_locally(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {'bailian': 'sk-test-group'})
    values = ui.persist_ai_configuration(_legacy(), dict(DEEPSEEK), dict(BAILIAN), unified=False, share_key=False,
                                         require_ready=True, dry_run=True, local_without_key=True)
    assert values['local_roles'] == ('polish',)


def test_a_wrong_address_with_a_key_is_still_an_error_not_a_silent_local_run(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {'deepseek': 'sk-test'})
    broken = dict(DEEPSEEK, base_url='http://api.deepseek.com/v1')   # plain HTTP to a remote host
    with pytest.raises(RuntimeError):
        ui.persist_ai_configuration(_legacy(), broken, broken, unified=False, share_key=False,
                                    require_ready=True, dry_run=True, local_without_key=True)


def test_switches_off_need_no_key_and_have_no_local_roles(monkeypatch):
    from twobyteasr.app import ui
    _keys(monkeypatch, {})
    values = ui.persist_ai_configuration(_legacy(), dict(DEEPSEEK), dict(DEEPSEEK), unified=False, share_key=False,
                                         require_ready=True, dry_run=True, local_without_key=True,
                                         use_ai_grouping=False, enable_ai_polish=False)
    assert values['local_roles'] == () and values['missing_keys'] == ()


def test_the_task_snapshot_turns_off_only_the_steps_without_a_key_and_leaves_the_saved_switches():
    from twobyteasr.app.ui import MainWindow
    window = MainWindow.__new__(MainWindow)
    window.legacy = _legacy()
    window.legacy.RUNTIME_SETTINGS['switches'].update(enable_ai_polish=True, use_ai_grouping=True)
    window._text_ai_local_roles = ('group',)
    snapshot = window._run_settings_snapshot()
    assert snapshot['switches']['use_ai_grouping'] is False and snapshot['switches']['enable_ai_polish'] is True
    assert window.legacy.RUNTIME_SETTINGS['switches']['use_ai_grouping'] is True
    from twobyteasr.recognition.text_ai_plan import text_ai_plan
    assert text_ai_plan(snapshot).roles == ('polish',)
    window._text_ai_local_roles = ('polish', 'group')
    assert text_ai_plan(window._run_settings_snapshot()).roles == ()
    assert '本地规则' in window._text_ai_local_note()
    window._text_ai_local_roles = ()
    assert window._text_ai_local_note() == ''
    assert window._run_settings_snapshot() == window.legacy.RUNTIME_SETTINGS


def test_the_report_names_the_planned_grouping_not_the_saved_switch():
    import subtitle_core
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    saved = copy.deepcopy(subtitle_core.RUNTIME_SETTINGS)
    saved.setdefault('switches', {}).update(enable_ai_polish=True, use_ai_grouping=True)
    task = copy.deepcopy(saved)
    task['switches'].update(enable_ai_polish=False, use_ai_grouping=False)
    original = subtitle_core.RUNTIME_SETTINGS
    try:
        subtitle_core.RUNTIME_SETTINGS = saved
        with activate_runtime_context(RuntimeContext(asr_settings_snapshot=task)):
            switches = subtitle_core.runtime_settings_snapshot()['switches']
    finally:
        subtitle_core.RUNTIME_SETTINGS = original
    assert switches['use_ai_grouping'] is False and switches['enable_ai_polish'] is False


# ---------------------------------------------------------------- top up

def test_key_steps_say_top_up_ten_yuan_where_the_service_links_a_top_up_page():
    from twobyteasr.app.guide_steps import ICONS, topup_step
    from twobyteasr.providers.api_setup_catalog import guide_for
    deepseek = topup_step(guide_for('deepseek', 'text'))
    assert '充值' in deepseek.title and '10 元' in deepseek.title and deepseek.url.endswith('/top_up')
    assert deepseek.icon == 'coin' and 'coin' in ICONS
    # 2026-10-18 (user): MOSI gives free credit to try with, so no top-up step.
    assert topup_step(guide_for('mosi_moss_pro', 'asr')) is None
    assert topup_step(guide_for('gemini', 'text')) is None


# ---------------------------------------------------------------- the explainer

def test_the_explainer_shows_four_pictures_and_opens_the_text_ai_guide(monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.app import api_key_explainer as module
    dialog = module.ApiKeyExplainerDialog(None)
    # 2026-10-21: it opens with what the key is for (AI makes the lines read well), never "no key needed".
    assert [anim.name for anim in dialog.anims] == ['ai_polish', 'key_what', 'key_topup', 'key_get']
    assert all(anim._scene is not None for anim in dialog.anims)   # drawn in the theme's colours
    assert '不填' not in ''.join(module.explainer_strings())
    assert 'DeepSeek' in dialog.setup_button.text()
    dialog.deleteLater()
    opened = []
    window = SimpleNamespace(_open_api_setup_guide=lambda key, kind: opened.append((key, kind)))

    class Chosen:
        def __init__(self, parent, offer_setup=True):
            self.choice = 'setup' if offer_setup else ''

        def exec(self):
            return 1

        def deleteLater(self):
            pass
    monkeypatch.setattr(module, 'ApiKeyExplainerDialog', Chosen)
    assert module.open_api_key_explainer(window) == 'setup' and opened == [('deepseek', 'text')]
    app.processEvents()


# ---------------------------------------------------------------- the tutorial

def _tour_window():
    noop = lambda *a, **k: None  # noqa: E731
    return SimpleNamespace(_tutorial_prepare_demo=noop, _tutorial_add_demo_media=noop,
                           _tutorial_demo_completion=noop, _open_api_key_explainer=noop)


def _plain(step):
    return re.sub(r'\*\*', '', str(step.text() if callable(step.text) else step.text))


def _note(step):
    return re.sub(r'\*\*', '', str(step.note() if callable(step.note) else step.note))


# 2026-10-22: one tutorial instead of two parts: tests/test_tutorial_one_road.py.


def test_every_tutorial_and_explainer_string_has_english_and_japanese():
    from twobyteasr.app.api_key_explainer import explainer_strings
    from twobyteasr.app.home_tour import tutorial_steps
    catalogs = {language: json.loads((__import__('pathlib').Path(__file__).resolve().parents[1] / 'twobyteasr' / 'locales'
                                      / f'{language}.json').read_text(encoding='utf-8')) for language in ('en', 'ja')}
    texts = set(explainer_strings())
    for step in tutorial_steps(_tour_window()):
        texts.add(str(step.text() if callable(step.text) else step.text))
        note = step.note() if callable(step.note) else step.note
        if note:
            texts.add(str(note))
        texts.update(action.label for action in step.actions if action.label)
        texts.add(step.next_label)
    texts.update({'第一次用 API Key？看图解', '需要 API Key（先充值）· 会上传音频',
                  '充值 10 元就够先用', '充值 10 元（约 5 小时音频）'})
    texts -= {'中文', '日本語', 'English'}   # language names stay as they are
    missing = {language: sorted(text for text in texts if text not in catalog) for language, catalog in catalogs.items()}
    assert missing == {'en': [], 'ja': []}
