"""The home AI card, the frosted 内容与术语 and the one-page AI settings (2026-10-22, design B).

User (10-22): the AI card stands with the recognition cards; without a
connected AI it and 内容与术语 are blue-grey, only the way to set it up is
readable and the content columns sit under frosted glass. The AI settings are
one page with no row that holds a few words across the whole width: one row of
three steps (service, key, test), the 「让 AI 负责」 tiles, and 高级设置 closed
to one line that names what is inside.
"""
import copy
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEEPSEEK = dict(ai_service='deepseek', polish_provider='deepseek', group_provider='deepseek',
                polish_transport='openai_compatible', group_transport='openai_compatible',
                polish_model='deepseek-chat', group_model='deepseek-chat',
                polish_base_url='https://api.deepseek.com/v1', group_base_url='https://api.deepseek.com/v1')


@pytest.fixture
def keys(monkeypatch):
    """The DeepSeek key as the scoped DPAPI store would return it."""
    from twobyteasr.providers import llm_config
    stored = {}
    monkeypatch.setattr(llm_config, 'read_scoped_api_key',
                        lambda provider, base_url='': (stored.get(provider, ''), 'test' if stored.get(provider) else ''))
    monkeypatch.setattr(llm_config, 'resolve_api_key', lambda stage: ('', ''))
    return stored


@pytest.fixture
def window(keys, monkeypatch):
    import subtitle_core
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'models',
                        {**subtitle_core.RUNTIME_SETTINGS.get('models', {}), **DEEPSEEK})
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'switches',
                        {**subtitle_core.RUNTIME_SETTINGS.get('switches', {}), 'enable_ai_polish': True,
                         'use_ai_grouping': True, 'unified_glm_processing': True})
    monkeypatch.setattr(ui, 'save_runtime_settings', lambda settings: None)
    win = ui.MainWindow([], subtitle_core, object(), None)
    win.resize(1600, 960)
    win.show()
    for _ in range(5):
        app.processEvents()
    yield win
    dialog = win.__dict__.get('_ai_settings_dialog')
    if dialog is not None:
        dialog.reject()
    win.close()
    win.deleteLater()
    app.processEvents()


def _settle(rounds=5):
    from PySide6.QtWidgets import QApplication
    for _ in range(rounds):
        QApplication.processEvents()


def test_the_card_shows_only_the_way_to_set_it_up_until_connected(window, keys):
    from twobyteasr.providers import ai_connection_record as record
    w = window
    card = w.setting_tiles['ai']
    w._refresh_home_process_facts()
    _settle()
    assert card.view.state == record.NO_KEY and card.title_label.text() == 'AI 智能断句'
    assert w.home_process_card.property('aiLock') is True and w.content_profile_card.property('aiLock') is True
    assert w.content_frost.isVisible() and w.content_frost.geometry() == w.content_terms_body.geometry()
    shown = {name: not getattr(card, name).isHidden()
             for name in ('connect_button', 'test_button', 'settings_button', 'help_button')}
    assert shown == dict(connect_button=True, test_button=False, settings_button=False, help_button=True)
    assert card.feature_row.isHidden()
    keys['deepseek'] = 'sk-card-test'
    w._refresh_home_process_facts()
    assert card.view.state == record.UNTESTED and not card.test_button.isHidden()
    assert not card.settings_button.isHidden() and card.connect_button.isHidden()
    record.remember(w.legacy.RUNTIME_SETTINGS, 'polish', False)
    w._refresh_home_process_facts()
    assert card.view.state == record.FAILED and card.test_button.text() == '重新测试'
    record.remember(w.legacy.RUNTIME_SETTINGS, 'polish', True)
    card.set_compact(False)      # a tall window (short ones drop the feature row)
    w._refresh_home_process_facts()
    _settle()
    assert card.view.state == record.READY
    assert w.home_process_card.property('aiLock') is False and w.content_profile_card.property('aiLock') is False
    assert not w.content_frost.isVisible()
    assert 'deepseek-chat' in card.title_label.text() and '测试通过' in card.summary_label.text()
    assert not card.feature_row.isHidden() and card.test_button.isHidden() and not card.settings_button.isHidden()
    assert w.terms.isEnabled()


def test_ai_switched_off_offers_to_turn_it_on(window, keys):
    from twobyteasr.providers import ai_connection_record as record
    w = window
    keys['deepseek'] = 'sk-card-test'
    switches = w.legacy.RUNTIME_SETTINGS['switches']
    switches.update(enable_ai_polish=False, use_ai_grouping=False)
    w._refresh_home_process_facts()
    card = w.setting_tiles['ai']
    assert card.view.state == record.OFF and card.connect_button.text() == '打开 AI'
    assert w.content_frost.isVisible() and '打开 AI' in w.content_frost.note.text()


def test_a_click_on_the_frosted_glass_opens_the_ai_settings(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w = window
    w._refresh_home_process_facts()
    _settle()
    QTest.mouseClick(w.content_frost, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     w.content_frost.rect().center())
    _settle()
    dialog = w.__dict__.get('_ai_settings_dialog')
    assert dialog is not None and dialog.isVisible() and dialog.isAncestorOf(w.ai_panel)


def test_the_settings_put_the_guide_beside_the_form_and_move_the_pink_button(window):
    from PySide6.QtWidgets import QLabel
    w = window
    w._open_ai_settings_dialog()
    _settle()
    dialog = w._ai_settings_dialog
    main = w._ai_main_editor
    # The shared service is the one form; 校对 waits until line breaking gets its own.
    assert main is w.group_editor and main.isVisible() and not w.polish_editor.isVisible()
    texts = [label.text() for label in dialog.findChildren(QLabel) if label.isVisible()]
    assert not any(text in texts for text in ('Provider', 'Account / Auth', 'Connection', 'Model'))
    assert {'服务', 'API Key', '先拿到一把 API Key'} <= set(texts)
    # The guide column sits left of the form, level with it.
    guide = w.ai_guide
    assert guide.isVisible() and guide.mapTo(dialog, guide.rect().topLeft()).x() < main.mapTo(dialog, main.rect().topLeft()).x()
    assert abs(guide.mapTo(dialog, guide.rect().topLeft()).y() - main.mapTo(dialog, main.rect().topLeft()).y()) <= 4
    # No key: 申请教程 (lent to the guide) is the pink button; 测试连接 waits; 保存 is plain.
    assert guide.isAncestorOf(main.guide_button) and main.guide_button.property('emphasis') == 'primary'
    assert main.test_button.property('emphasis') == 'secondary' and not main.test_button.isEnabled()
    assert w.ai_dialog_save_button.property('buttonRole') == 'secondary'
    assert main.key.hasFocus() or not dialog.isActiveWindow()
    # A key typed: 测试连接 turns pink and the guide says to test next.
    main.key.setText('sk-typed-not-a-real-key')
    _settle()
    assert main.test_button.property('emphasis') == 'primary' and main.test_button.isEnabled()
    assert main.guide_button.property('emphasis') == 'secondary' and guide.property('state') == 'untested'
    assert '几秒' in main.status.text()
    main.key.clear()
    # 更多选项 starts closed; its line names who does what and the model.
    assert not w.ai_advanced_box.isVisible() and 'deepseek-chat' in w.ai_advanced_summary.text()
    w.ai_advanced_toggle.setChecked(True)
    _settle()
    assert w.ai_advanced_box.isAncestorOf(main.advanced_box) and main.model.isVisible()
    assert w.ai_grouping.isVisible() and not w.ai_advanced_summary.isVisible()


def test_a_passed_test_turns_the_guide_into_a_success_card(window):
    """User (10-23): the connected column was empty and dull; a beginner should
    see it worked: a check, what the AI now does, the one step left."""
    w = window
    w._open_ai_settings_dialog()
    _settle()
    main = w._ai_main_editor
    main.key.setText('sk-typed-not-a-real-key')
    main.last_connection_ok = True
    w._refresh_ai_dialog_state()
    _settle()
    guide = w.ai_guide
    assert guide.property('state') == 'ready'
    assert guide.win_box.isVisible() and guide.steps_box.isHidden() and guide.win_badge.isVisible()
    assert '接好了' in guide.win_heading.text() and '刚刚测试通过' in guide.win_meta.text()
    # Four tiles, four characters each (a wrapped 按意思断句 was the joke, 10-23).
    names = [tile.label.text() for tile in guide.win_tiles.values()]
    assert names == ['AI 断句', '字幕校对', '术语校对', '翻译字幕']
    assert '4' in guide.win_caption.text() and '拖进视频' in guide.win_next_text.text()
    assert all(tile.note.text() for tile in guide.win_tiles.values())
    assert main.key_help_button.isHidden()   # connected: no need to explain the key
    assert w.ai_dialog_save_button.property('buttonRole') == 'primary'
    # 字幕校对 switched off: its tile greys out and the count drops.
    w.ai_polish.setChecked(False)
    _settle()
    assert guide.win_tiles['polish'].property('on') is False and '3' in guide.win_caption.text()


def test_a_second_service_for_line_breaks_moves_into_advanced_and_cancel_puts_it_back(window):
    w = window
    w._open_ai_settings_dialog()
    _settle()
    w.ai_advanced_toggle.setChecked(True)
    w.separate_group_service.setChecked(True)
    _settle()
    assert not w.unified_glm.isChecked()
    assert w._ai_main_editor is w.polish_editor and w.polish_editor.isVisible()
    assert w.ai_advanced_box.isAncestorOf(w.group_editor) and w.group_editor.isVisible()
    assert w.ai_advanced_box.isAncestorOf(w.polish_editor.advanced_box)
    assert not w.share_key.isHidden() and w.separate_group_note.isHidden()   # one row: switch, key switch
    w._ai_settings_dialog.reject()
    from PySide6.QtTest import QTest
    for _ in range(60):  # the dialog closes with a short animation
        QTest.qWait(50)
        if w.__dict__.get('_ai_settings_dialog') is None:
            break
    assert w.unified_glm.isChecked() and not w.separate_group_service.isChecked()
    assert w._ai_main_editor is w.group_editor
    assert not w.ai_advanced_box.isAncestorOf(w.group_editor)


def test_account_services_name_the_login_step(window):
    from PySide6.QtWidgets import QApplication
    w = window
    editor = w.group_editor
    editor.service.setCurrentIndex(editor.service.findData('codex_cli'))
    QApplication.processEvents()
    assert editor.key_step_label.text() == '登录账号'
    assert editor.settings_stack.currentWidget() is editor.cli_page
    editor.service.setCurrentIndex(editor.service.findData('deepseek'))
    QApplication.processEvents()
    assert editor.key_step_label.text() == 'API Key'


def test_the_blue_grey_palette_follows_each_theme():
    from twobyteasr.design.home_qss import AI_LOCK_HUE, ai_lock_palette, build_home_qss
    from twobyteasr.design.ui_theme import theme_definition
    for key in ('grape', 'warm'):
        theme = theme_definition(key)
        palette = ai_lock_palette(theme)
        assert set(palette) >= {'band', 'card', 'edge', 'chip', 'title', 'text', 'frost'}
        assert AI_LOCK_HUE not in palette.values()             # always mixed into the theme's surface
        sheet = build_home_qss(theme)
        assert f'QFrame#homeProcessCard[aiLock="true"] {{ background: {palette["band"]};' in sheet
        assert 'QFrame#homeAiCard { background: transparent; border: 0;' in sheet   # no frame in the band (10-23)
        assert 'QFrame#homeContentProfile[aiLock="true"]' in sheet
    assert ai_lock_palette(theme_definition('grape'))['band'] != ai_lock_palette(theme_definition('warm'))['band']
