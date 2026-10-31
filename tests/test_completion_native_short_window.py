"""Actual MainWindow layout/translation sequence; no headed or model runtime."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
import subtitle_core as legacy
from twobyteasr.app.ui import MainWindow
from twobyteasr.design.theme_manager import apply_theme
from twobyteasr.acceptance.completion_real_audit import secondary_control_measurement


@pytest.mark.parametrize('language', ['zh', 'en', 'ja'])
def test_actual_mainwindow_translation_then_short_resize_keeps_supporting_heights(language, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.app.ui import _register_bundled_fonts, _app_font
    if not getattr(app, '_completion_fonts_ready', False):
        _register_bundled_fonts(); app.setFont(_app_font())
        app._completion_fonts_ready = True
    # Background model/GPU discovery is outside this layout regression.
    monkeypatch.setattr(MainWindow, '_background_preload', lambda self: None)
    monkeypatch.setattr(MainWindow, '_restore_last_project_profile', lambda self: None)
    apply_theme('grape')
    window = MainWindow([], legacy, object(), None)
    window.show(); app.processEvents()
    window.resize(1320, 850)
    window._switch_page(2)
    window.result_summary.setText('AI文字检查已执行 · 采纳 6 处文字修改 · 32 条字幕 · 本文件耗时 2:36')
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    window._apply_ui_language()
    app.processEvents()
    scroll = window.pages.widget(2)
    buttons = (window.result_todo.ai_card.action, window.result_more_button)
    heights = [button.height() for button in buttons]
    from twobyteasr.app.completion_todo import BAR_HEIGHT as height
    assert heights == [height] * 2
    # Reproduce all three native translation/resize cycles from the headed run.
    for _ in range(3):
        window.result_files_toggle.setChecked(True); app.processEvents()
        window.result_files_toggle.setChecked(False); app.processEvents()
        window._apply_ui_language()
        window.resize(900, 620); app.processEvents()
        assert window.result_action_grid.columns == 1 and window.result_todo.columns == 1
        assert [button.height() for button in buttons] == heights
        measured = [secondary_control_measurement(button, expected_height=36) for button in buttons]
        assert all(row["fits"] for row in measured), measured
        assert scroll.verticalScrollBar().maximum() > 0
        assert scroll.horizontalScrollBar().maximum() == 0
        # A short window scrolls to every supporting control.
        for button in buttons:
            scroll.ensureWidgetVisible(button); app.processEvents()
            assert scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), QPoint()))
        scroll.verticalScrollBar().setValue(0)
        window.resize(1320, 850); app.processEvents()
        assert [button.height() for button in buttons] == heights
    window.close(); window.deleteLater(); app.processEvents()
