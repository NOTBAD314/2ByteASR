"""The two candy questions (2026-11-15): 「三颗糖」 save before leaving, 「两张卡片」 recovery."""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def _shown(dialog, app):
    dialog.show()
    for _ in range(5):
        app.processEvents()


# ---------------------------------------------------------------- 三颗糖
@pytest.mark.parametrize('button, expected', [('save_button', 'save'), ('discard_button', 'discard'),
                                              ('cancel_button', 'cancel')])
def test_each_candy_gives_its_answer(app, button, expected):
    from twobyteasr.projects.save_changes_dialog import SaveChangesDialog
    dialog = SaveChangesDialog(None, '退出应用', '第3集')
    _shown(dialog, app)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint          # our own round frame
    getattr(dialog, button).click()
    assert dialog.choice == expected and not dialog.isVisible()
    dialog.deleteLater()


def test_enter_saves_and_escape_cancels(app):
    from twobyteasr.projects.save_changes_dialog import SaveChangesDialog
    dialog = SaveChangesDialog(None, '退出应用', '第3集')
    _shown(dialog, app)
    assert dialog.save_button.isDefault()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.choice == 'cancel'
    again = SaveChangesDialog(None, '退出应用')
    _shown(again, app)
    QTest.keyClick(again.save_button, Qt.Key.Key_Return)
    assert again.choice == 'save'
    for item in (dialog, again):
        item.deleteLater()


def test_the_candies_say_what_they_do_and_look_different(app):
    from twobyteasr.projects.save_changes_dialog import SaveChangesDialog
    dialog = SaveChangesDialog(None, '退出应用', '第3集')
    _shown(dialog, app)
    tiles = (dialog.save_button, dialog.discard_button, dialog.cancel_button)
    assert [tile.property('tone') for tile in tiles] == ['save', 'drop', 'back']
    assert all(tile.title.text() and tile.note.text() for tile in tiles)
    assert dialog.save_button.badge is not None and dialog.save_button.badge.isVisible()
    heights = {tile.height() for tile in tiles}
    # 2026-11-15 evening: compact candies (icon and name on one line), still not squashed buttons.
    assert 60 <= min(heights) <= 90, heights
    assert dialog.height() <= 290, dialog.height()                # the first build was about 400
    sticker = dialog.save_button.badge
    corner = dialog.save_button.mapTo(dialog, dialog.save_button.rect().topLeft())
    assert sticker.parentWidget() is dialog and sticker.text() == '推荐'
    assert sticker.geometry().contains(corner)                    # hangs over the save tile's corner
    texts = ' '.join(label.text() for label in dialog.findChildren(type(dialog.save_button.title)))
    assert '退出应用' in texts and '第3集' in texts
    dialog.deleteLater()


@pytest.mark.parametrize('standard, expected', [('Save', 'save'), ('Discard', 'discard'), ('Cancel', 'cancel')])
def test_audits_can_still_answer_by_standard_button(app, standard, expected):
    from PySide6.QtWidgets import QMessageBox
    from twobyteasr.acceptance.question_boxes import question_boxes
    from twobyteasr.projects.save_changes_dialog import SaveChangesDialog
    dialog = SaveChangesDialog(None, '退出应用', '第3集')
    _shown(dialog, app)
    which = QMessageBox.StandardButton
    assert isinstance(dialog, question_boxes())
    assert dialog.standardButtons() == which.Save | which.Discard | which.Cancel
    assert dialog.button(which.Yes) is None and len(dialog.buttons()) == 3
    assert '退出应用' in dialog.text() and '第3集' in dialog.informativeText()
    dialog.button(getattr(which, standard)).click()
    assert dialog.choice == expected
    dialog.deleteLater()


def test_the_dirty_guard_asks_with_the_candies(app, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.projects import save_changes_dialog
    from twobyteasr.projects.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
    asked = []
    monkeypatch.setattr(save_changes_dialog, 'ask_save_changes',
                        lambda parent, action, name: asked.append((action, name)) or 'discard')
    page = SimpleNamespace(project=SimpleNamespace(media=SimpleNamespace(display_name='第3集.mp4')))
    assert ProjectDirtyGuard(page)._prompt('退出应用') == DirtyGuardChoice.DISCARD
    assert asked == [('退出应用', '第3集.mp4')]


@pytest.mark.parametrize('answer, kept', [('DISCARD', False), ('CANCEL', True)])
def test_dont_save_takes_the_recovery_point_with_it(tmp_path, answer, kept):
    """「不保存」 must not come back: opening restores a newer autosave without asking now."""
    from types import SimpleNamespace
    from tests.test_project_recovery_inspection import fixture
    from twobyteasr.projects.project_dirty_guard import DirtyGuardChoice, ProjectDirtyGuard
    from twobyteasr.projects.studio_project import recoverable_autosave
    path, official, candidate = fixture(tmp_path)
    assert recoverable_autosave(path) == candidate
    page = SimpleNamespace(project=official, project_path=path, undo_stack=SimpleNamespace(isClean=lambda: False))
    ProjectDirtyGuard(page).confirm('退出应用', choice_provider=lambda _action: getattr(DirtyGuardChoice, answer))
    assert candidate.exists() is kept
    assert (recoverable_autosave(path) is not None) is kept


# ---------------------------------------------------------------- 两张卡片
def _request(tmp_path, error=''):
    from twobyteasr.projects.project_recovery_dialog import RecoveryChoice
    official, candidate = tmp_path / 'p.2byteproj', tmp_path / 'p.autosave'
    for path in (official, candidate):
        path.write_text('{}', 'utf8')
    yesterday = time.time() - 86400
    os.utime(official, (yesterday, yesterday))
    return RecoveryChoice(candidate, official, error)


def test_days_are_named_so_times_never_read_backwards(tmp_path):
    from twobyteasr.projects.project_recovery_dialog import saved_at
    path = tmp_path / 'f'
    path.write_text('x', 'utf8')
    stamp = datetime(2026, 11, 14, 22, 27).timestamp()
    os.utime(path, (stamp, stamp))
    assert saved_at(path, today=date(2026, 11, 14)) == ('22:27', '今天')
    assert saved_at(path, today=date(2026, 11, 15)) == ('22:27', '昨天')
    assert saved_at(path, today=date(2026, 11, 20)) == ('22:27', '11月14日')
    assert saved_at(tmp_path / 'missing') == ('--:--', '')


@pytest.mark.parametrize('name, expected', [('recovery_recover', 'recover'), ('recovery_saved', 'saved'),
                                            ('recovery_ignore', 'ignore')])
def test_a_card_or_the_link_is_the_answer(app, tmp_path, name, expected):
    from twobyteasr.projects.project_recovery_dialog import RecoveryDialog
    dialog = RecoveryDialog(None, _request(tmp_path))
    _shown(dialog, app)
    button = next(b for b in dialog.buttons() if b.objectName() == name)       # the audits' way in
    button.click()
    assert dialog.choice == expected and not dialog.isVisible()
    dialog.deleteLater()


def test_escape_cancels_and_the_newer_autosave_is_marked(app, tmp_path):
    from twobyteasr.projects.project_recovery_dialog import RecoveryDialog
    dialog = RecoveryDialog(None, _request(tmp_path, error='denied'))
    _shown(dialog, app)
    assert dialog.recover_button.property('newer') is True and dialog.recover_button.ribbon is not None
    assert dialog.saved_button.property('newer') is False and dialog.recover_button.isDefault()
    assert 'denied' in dialog.informativeText()
    assert dialog.recover_button.height() >= 120
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.choice == 'cancel'
    dialog.deleteLater()


def test_the_box_puts_the_default_back(app, tmp_path):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.projects.project_recovery_dialog import RecoveryDialog
    settings.save_hub_preferences('', True, 60, 9, True, True, 'ask')
    assert settings.effective_recovery_policy(settings.read_studio_preferences()) == 'ask'
    dialog = RecoveryDialog(None, _request(tmp_path))
    _shown(dialog, app)
    dialog.always.setChecked(True)
    dialog.recover_button.click()
    assert settings.effective_recovery_policy(settings.read_studio_preferences()) == 'auto'
    dialog.deleteLater()
