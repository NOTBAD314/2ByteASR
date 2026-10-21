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
    # Background model/GPU discovery is outside this layout regression.
    monkeypatch.setattr(MainWindow, '_background_preload', lambda self: None)
    monkeypatch.setattr(MainWindow, '_restore_last_project_profile', lambda self: None)
    apply_theme('grape')
    window = MainWindow([], legacy, object(), None)
    window.show(); app.processEvents()
    window.resize(1320, 850)
    window._switch_page(2)
    window.result_summary.setText('AI文字检查已执行 · 采纳 6 处文字修改 · 32 条字幕 · 本文件耗时 2:36')
    window.open_priority_review_button.show()
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    window._apply_ui_language()
    app.processEvents()
    scroll = window.pages.widget(2)
    buttons = window.result_action_grid.secondary_actions
    from twobyteasr.app.completion_widgets import COMPLETION_SECONDARY_HEIGHT as height
    assert [button.height() for button in buttons] == [height] * 3
    # Reproduce all three native translation/resize cycles from the headed run.
    for _ in range(3):
        window.result_files_toggle.setChecked(True); app.processEvents()
        window.result_files_toggle.setChecked(False); app.processEvents()
        window._apply_ui_language()
        window.resize(900, 620); app.processEvents()
        assert window.result_action_grid.columns == 1
        assert [button.height() for button in buttons] == [height] * 3
        assert all(secondary_control_measurement(button)['fits'] for button in buttons)
        assert scroll.verticalScrollBar().maximum() > 0
        assert scroll.horizontalScrollBar().maximum() == 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()); app.processEvents()
        assert all(scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), QPoint())) for button in buttons)
        scroll.verticalScrollBar().setValue(0)
        window.resize(1320, 850); app.processEvents()
        assert [button.height() for button in buttons] == [height] * 3
    window.close(); window.deleteLater(); app.processEvents()
