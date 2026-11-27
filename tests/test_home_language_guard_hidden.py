"""2026-11-26: the home language guard row (严格语言模式 / 自动修复异常语言 /
备用模型复核 / 修复档位) is hidden and always runs at its defaults."""


def test_guard_row_hidden_and_old_choices_reset_to_defaults(monkeypatch):
    import subtitle_core
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    from twobyteasr.recognition.language_guard import settings_policy
    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(subtitle_core.RUNTIME_SETTINGS, 'subtitle_language', {
        'recognition_language': 'en', 'output': 'original', 'translation_script': 'zh-Hans',
        'strict_language': False, 'auto_language_repair': False, 'language_backup_review': True,
        'repair_profile': 'custom'})
    saves = []
    monkeypatch.setattr(ui, 'save_runtime_settings', lambda settings: saves.append(True))
    win = ui.MainWindow([], subtitle_core, object(), None)
    try:
        win.show()
        app.processEvents()
        assert win._language_guard_row.isHidden() and not win._language_guard_row.isVisible()
        assert not win._language_repair_limits.isVisible()
        checks = {key: check.isChecked() for key, check in win._language_guard_checks.items()}
        assert checks == {'strict_language': True, 'auto_language_repair': True, 'language_backup_review': False}
        assert win._language_repair_profile.currentData() == 'normal'
        section = win.legacy.RUNTIME_SETTINGS['subtitle_language']
        assert (section['strict_language'], section['auto_language_repair'],
                section['language_backup_review'], section['repair_profile']) == (True, True, False, 'normal')
        assert saves
        policy = settings_policy(win.legacy.RUNTIME_SETTINGS, 'en')
        assert policy['strict'] and policy['repair'] and not policy['backup']
        # Changing the spoken language never brings the row or the limits back.
        win.recognition_language.setCurrentIndex(win.recognition_language.findData('ja'))
        app.processEvents()
        assert not win._language_guard_row.isVisible() and not win._language_repair_limits.isVisible()
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
