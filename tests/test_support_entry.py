"""Support is optional; only explicit, durable consent removes the entry."""
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from twobyteasr import i18n
from twobyteasr.app import support_entry as support


@pytest.fixture
def context(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    # Explicit INI path remains within the runner's TWOBYTEASR_TEST_ROOT.
    factory = lambda: QSettings(str(tmp_path / 'support.ini'), QSettings.Format.IniFormat)
    factory().clear()
    monkeypatch.setattr(support, '_settings', factory)
    monkeypatch.setattr(i18n, '_CURRENT_LANGUAGE_CACHE', 'zh')
    return app, factory


def test_only_one_user_key_changes_and_survives_other_preferences(context, monkeypatch):
    from twobyteasr.design import theme_manager
    from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings
    app, factory = context
    monkeypatch.setattr(theme_manager, '_settings', factory)
    settings = factory()
    settings.setValue('appearance/theme', 'warm')
    settings.setValue('unrelated/future', 'preserve me')
    settings.sync()
    assert not support.support_entry_hidden()
    before = {key: settings.value(key) for key in settings.allKeys()}
    runtime, path, _ = load_runtime_settings()
    save_runtime_settings(runtime)
    before_json = Path(path).read_bytes()
    support.hide_support_entry()
    assert support.support_entry_hidden()
    assert Path(path).read_bytes() == before_json
    after = factory()
    assert {key: after.value(key) for key in before} == before
    assert set(after.allKeys()) - set(before) == {support.SUPPORT_HIDDEN_KEY}
    for language in ('en', 'ja', 'zh'):
        i18n.save_language(language)
        theme_manager.save_theme_key('grape')
        assert support.support_entry_hidden()
    save_runtime_settings(deepcopy(runtime))  # old recognition snapshot / defaults
    assert support.support_entry_hidden()


def test_real_qsettings_write_failure_does_not_leave_hidden_cache(context, monkeypatch, tmp_path):
    # A directory in place of the INI file gives a real QSettings AccessError.
    from twobyteasr.test_isolation import isolation_root
    blocked = isolation_root() / 'qsettings' / 'cannot-write.ini'
    blocked.mkdir(exist_ok=True)
    monkeypatch.setattr(support, '_settings', lambda: QSettings(str(blocked), QSettings.Format.IniFormat))
    with pytest.raises(OSError):
        support.hide_support_entry()
    assert not support.support_entry_hidden()


@pytest.mark.parametrize('dismiss', ['close', 'escape', 'title_close'])
def test_ordinary_close_keeps_entry(context, dismiss):
    dialog = support.SupportDialog(None)
    dialog.show()
    QTest.qWait(20)
    if dismiss == 'close':
        dialog.close_button.click()
    elif dismiss == 'title_close':
        dialog.surface.close_button.click()
    else:
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert not support.support_entry_hidden()


@pytest.mark.parametrize('dismiss', ['cancel', 'escape', 'title_close', 'window_close', 'enter'])
def test_confirmation_defaults_to_cancel_and_never_saves(context, dismiss):
    _, factory = context
    dialog = support.SupportDialog(None)
    dialog.show()
    dialog.hide_button.click()
    confirmation = dialog._confirmation
    QTest.qWait(30)
    assert confirmation.cancel_button.isDefault()
    assert confirmation.focusWidget() is confirmation.cancel_button
    dialog._confirm_hide()
    assert dialog._confirmation is confirmation
    if dismiss == 'cancel':
        confirmation.cancel_button.click()
    elif dismiss == 'title_close':
        confirmation.surface.close_button.click()
    elif dismiss == 'window_close':
        confirmation.close()
    else:
        QTest.keyClick(confirmation, Qt.Key.Key_Escape if dismiss == 'escape' else Qt.Key.Key_Return)
    assert dialog.isVisible()
    assert dialog._confirmation is None
    assert not factory().contains(support.SUPPORT_HIDDEN_KEY)


def test_confirmed_hide_emits_only_after_persistence(context):
    dialog = support.SupportDialog(None)
    observed = []
    dialog.entry_hidden.connect(lambda: observed.append(support.support_entry_hidden()))
    dialog.show()
    dialog.hide_button.click()
    dialog._confirmation.confirm_button.click()
    assert observed == [True]
    assert not dialog.isVisible()
    assert dialog._confirmation is None


def test_save_failure_keeps_dialog_and_entry(context, monkeypatch):
    dialog = support.SupportDialog(None)
    errors, hidden = [], []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[1:]))
    def fail():
        raise OSError('access denied')
    monkeypatch.setattr(support, 'hide_support_entry', fail)
    dialog.entry_hidden.connect(lambda: hidden.append(True))
    dialog.show()
    dialog.hide_button.click()
    dialog._confirmation.confirm_button.click()
    assert dialog.isVisible() and not support.support_entry_hidden()
    assert not hidden and len(errors) == 1
    assert errors[0][1] == i18n.tr('未能保存关闭状态，支持入口仍会保留。请稍后重试。')


@pytest.mark.parametrize('result', [True, False, 'exception'])
def test_links_only_open_on_click_and_never_imply_payment(context, monkeypatch, result):
    opened, errors = [], []
    def open_url(url):
        opened.append(url.toString())
        if result == 'exception':
            raise RuntimeError('desktop unavailable')
        return result
    monkeypatch.setattr(support.QDesktopServices, 'openUrl', open_url)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: errors.append(args[1:]))
    dialog = support.SupportDialog(None)
    dialog.show()
    assert opened == []
    for button in dialog.channel_buttons:
        button.click()
    assert opened == ['https://paypal.me/2byte314', 'https://afdian.com/a/2byteasr']
    assert len(errors) == (0 if result is True else 2)
    assert dialog.isVisible() and not support.support_entry_hidden()


def test_all_dialog_bindings_retranslate(context, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.i18n_widgets import refresh_application
    dialog = support.SupportDialog(None)
    dialog.show()
    dialog.hide_button.click()
    confirmation = dialog._confirmation
    for language in ('en', 'ja', 'zh', 'en'):
        monkeypatch.setattr(i18n, '_CURRENT_LANGUAGE_CACHE', language)
        refresh_application(language)
        for root in (dialog, confirmation):
            for widget in [root, *root.findChildren(QWidget)]:
                for prop, (source, arguments) in getattr(widget, '_i18n_bindings', {}).items():
                    if language != 'zh':
                        assert source in i18n._TRANSLATIONS[language], source
                    expected = i18n.translate(source, language).format(**arguments)
                    assert getattr(widget, prop)() == expected
