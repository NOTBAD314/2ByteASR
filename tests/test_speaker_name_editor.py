"""Name edit boundaries use one identity while batch checks remain independent."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent, QUndoStack
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project
from twobyteasr.studio_speaker_manager import SpeakerManagerDialog

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def manager():
    page = QWidget()
    page.project = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=2000), speakers=[StudioSpeaker('S00', '原名'), StudioSpeaker('S01', '第二人'), StudioSpeaker('S02', '第三人')],
        cues=[StudioCue('a', 0, 1000, '第一句', speaker_id='S00'), StudioCue('b', 500, 1500, '第二句', speaker_id='S01')])
    page.undo_stack = QUndoStack(page)
    page._speaker_roles_pending = False
    page._populate_speakers = lambda: None
    page._speaker_structure_changed = lambda: None
    page.selected_cue_ids = lambda: []
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    APP.processEvents()
    yield dialog
    for card in dialog.cards.values():
        card.preedit = False
        card.name_edit.setText(card.committed_name or '有效名称')
    dialog.close()
    page.deleteLater()
    APP.processEvents()


def names(manager):
    return {speaker.id: speaker.name for speaker in manager.page.project.speakers}


def edit(manager, key):
    return manager.cards[key].name_edit


def test_enter_commits_one_identity_and_one_undo_without_resetting_checks(manager, tmp_path):
    manager.multi_button.setChecked(True)
    manager._select_visible('all')
    original_ids = [speaker.id for speaker in manager.page.project.speakers]
    edit(manager, 'S00').setFocus()
    QTest.keyClick(edit(manager, 'S00'), Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(edit(manager, 'S00'), 'Renamed')
    assert manager._selected_ids() == set(original_ids)
    assert manager.page.undo_stack.count() == 0
    QTest.keyClick(edit(manager, 'S00'), Qt.Key_Return)
    assert names(manager) == {'S00': 'Renamed', 'S01': '第二人', 'S02': '第三人'}
    assert manager.page.undo_stack.count() == 1
    assert manager._selected_ids() == set(original_ids)
    assert edit(manager, 'S00').text() == 'Renamed'
    manager.refresh()
    assert manager._selected_ids() == set(original_ids)
    path = save_project(manager.page.project, tmp_path/'renamed.2byteproj')
    assert load_project(path).speakers[0].name == 'Renamed'
    manager.page.undo_stack.undo()
    assert names(manager)['S00'] == '原名'
    assert edit(manager, 'S00').text() == '原名'
    assert manager._selected_ids() == set(original_ids)


def test_moving_to_another_card_submits_previous_name_and_keeps_checks(manager):
    manager.multi_button.setChecked(True)
    manager.cards['S00'].select_check.setChecked(True)
    manager.cards['S02'].select_check.setChecked(True)
    edit(manager, 'S00').setFocus()
    edit(manager, 'S00').setText('中文名字')
    edit(manager, 'S01').setFocus()
    APP.processEvents()
    assert names(manager)['S00'] == '中文名字'
    assert edit(manager, 'S01').text() == '第二人'
    assert manager._selected_ids() == {'S00', 'S02'}
    assert manager.page.undo_stack.count() == 1
    edit(manager, 'S01').setText('另一个名字')
    manager.done(1)
    assert names(manager)['S01'] == '另一个名字'
    assert [speaker.id for speaker in manager.page.project.speakers] == ['S00', 'S01', 'S02']
    assert manager.page.undo_stack.count() == 2


def test_focus_out_commits_valid_text_and_empty_name_keeps_draft_and_previous_value(manager):
    edit(manager, 'S00').setFocus()
    edit(manager, 'S00').setText('失焦保存')
    manager.done_button.setFocus()
    APP.processEvents()
    assert names(manager)['S00'] == '失焦保存'
    edit(manager, 'S00').setFocus()
    edit(manager, 'S00').setText('  ')
    edit(manager, 'S01').setFocus()
    APP.processEvents()
    assert names(manager)['S00'] == '失焦保存'
    assert edit(manager, 'S00').text() == '  '
    assert manager.cards['S00'].name_error.isVisible()
    manager.done(1)
    assert manager.isVisible()
    assert manager.page.undo_stack.count() == 1


def test_ime_preedit_never_becomes_name_and_committed_chinese_is_saved(manager):
    field = edit(manager, 'S00')
    field.setFocus()
    field.setText('')
    preedit = QInputMethodEvent('zhang', [])
    QApplication.sendEvent(field, preedit)
    card = manager.cards['S00']
    assert card.preedit
    assert not manager._card_commit_name(card)
    assert names(manager)['S00'] == '原名'
    assert manager.page.undo_stack.count() == 0
    commit = QInputMethodEvent('', [])
    commit.setCommitString('张三')
    QApplication.sendEvent(field, commit)
    assert not card.preedit
    manager.done(1)
    assert names(manager)['S00'] == '张三'
    assert manager.page.undo_stack.count() == 1


def test_filter_refresh_and_colour_changes_preserve_checks_and_active_draft(manager):
    manager.multi_button.setChecked(True)
    manager._select_visible('all')
    edit(manager, 'S00').setText('保留草稿')
    manager.speaker_filter.setText('第二人')
    assert manager.cards['S00'].isHidden() and not manager.cards['S01'].isHidden()
    assert manager._selected_ids() == {'S00', 'S01', 'S02'}
    manager.refresh()
    assert edit(manager, 'S00').text() == '保留草稿'
    assert manager._selected_ids() == {'S00', 'S01', 'S02'}
    manager._card_set_visible(manager.cards['S01'], False)
    assert manager.page.project.speakers[1].hidden
    assert edit(manager, 'S00').text() == '保留草稿'
    assert manager.page.undo_stack.count() == 1
