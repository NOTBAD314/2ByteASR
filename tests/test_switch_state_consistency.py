"""Restore, interaction and task intent share checked state; isolated Qt only."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSignalBlocker, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from twobyteasr.design.ui_widgets import SwitchControl
from twobyteasr.app.ui import MainWindow


APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize('checked', [False, True])
def test_blocked_restore_and_first_paint_match_checked(checked):
    control = SwitchControl('游戏术语增强')
    with QSignalBlocker(control):
        control.setChecked(not checked)
        control.setChecked(checked)
    assert control._progress == float(checked)
    control.show(); APP.processEvents()
    assert control._progress == float(checked)
    control.setEnabled(False)
    assert control.isChecked() == checked
    control.close()


def test_programmatic_restore_replaces_running_animation_and_keeps_blocking():
    control = SwitchControl('联网补充核验'); control.show(); APP.processEvents()
    QTest.mouseClick(control, Qt.LeftButton)
    with QSignalBlocker(control):
        control.setChecked(False)
        assert control.signalsBlocked()
    QTest.qWait(220)
    assert not control.isChecked() and control._progress == 0.0
    control.close()


def test_row_click_keyboard_and_fast_toggle_each_change_once():
    control = SwitchControl('游戏术语增强'); control.resize(360, 36)
    control.show(); APP.processEvents()
    events = []; control.toggled.connect(events.append)
    QTest.mouseClick(control, Qt.LeftButton, pos=QPoint(270, 18))
    assert events == [True]
    control.setFocus(); QTest.keyClick(control, Qt.Key_Space)
    assert events == [True, False]
    for _ in range(11):
        QTest.mouseClick(control, Qt.LeftButton, pos=QPoint(20, 18))
    QTest.qWait(220)
    assert len(events) == 13 and control.isChecked() and control._progress == 1.0
    control.close()


class Owner(QWidget):
    _enabled_glossary_ids = MainWindow._enabled_glossary_ids
    _save_glossary_settings = MainWindow._save_glossary_settings
    _refresh_glossary_chips = MainWindow._refresh_glossary_chips
    _task_glossary_selection = MainWindow._task_glossary_selection
    _restore_glossary_switch = MainWindow._restore_glossary_switch
    _glossary_display_name = lambda self, value: value
    _refresh_asr_summary = lambda self: None

    def __init__(self, settings):
        super().__init__()
        self.legacy = SimpleNamespace(RUNTIME_SETTINGS=settings, glossary_catalog=lambda: [])
        self.terms = SwitchControl('游戏术语增强')
        self.term_search = SwitchControl('联网补充核验')
        self.term_hint = QLabel()
        self.batch_glossary_status = QLabel()
        self.add_glossary_button = QPushButton()
        self.glossary_chips_layout = QHBoxLayout(self)


@pytest.mark.parametrize('checked', [False, True])
def test_save_empty_selection_preserves_intent_and_restores_without_signals(monkeypatch, checked):
    saved = []
    monkeypatch.setattr('twobyteasr.app.ui.save_runtime_settings', lambda payload: saved.append(payload['glossary'].copy()))
    owner = Owner({'glossary': {'enable_domain_terms': checked, 'enabled_glossary_ids': []}})
    owner._restore_glossary_switch()
    assert owner.terms.isChecked() == checked and owner.terms._progress == float(checked)
    owner._save_glossary_settings()
    assert saved[-1]['enable_domain_terms'] == checked
    assert owner._task_glossary_selection() == ((), checked)
    assert ('ON' if checked else 'OFF') in owner.batch_glossary_status.text()
    if checked: assert '暂不应用' in owner.batch_glossary_status.text()
    assert not owner.term_search.isChecked()
    owner.close()


def test_off_snapshot_never_carries_previous_batch_and_online_is_independent(monkeypatch):
    monkeypatch.setattr('twobyteasr.app.ui.save_runtime_settings', lambda _: None)
    owner = Owner({'glossary': {'enable_domain_terms': False, 'enabled_glossary_ids': ['previous']}})
    owner._restore_glossary_switch(); owner.term_search.setChecked(True)
    assert owner._task_glossary_selection() == ((), False)
    owner._save_glossary_settings()
    assert owner.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] == ['previous']
    assert not owner.legacy.RUNTIME_SETTINGS['glossary']['enable_domain_terms']
    assert owner.term_search.isChecked()
    owner._studio_recognition_context = {'enabled_glossary_ids': ['previous'], 'enable_domain_terms': False}
    assert owner._task_glossary_selection() == ((), False)
    owner.close()
