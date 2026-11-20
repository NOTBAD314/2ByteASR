"""Ctrl+F in the E caption editor opens 批量替换 with the chosen text (2026-11-19)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_editor_download_repair import page, select
from twobyteasr.studio.studio_find_replace import FindReplaceDialog


@pytest.fixture
def opened(monkeypatch):
    dialogs = []
    monkeypatch.setattr(FindReplaceDialog, 'exec', lambda self: dialogs.append(self) or 0)
    yield dialogs
    for dialog in dialogs:
        dialog.deleteLater()


def press(widget, key=Qt.Key_F):
    QApplication.setActiveWindow(widget.window()); widget.setFocus()
    QTest.keyClick(widget, key, Qt.ControlModifier)
    QTest.keyRelease(widget, key)
    QApplication.processEvents()


@pytest.mark.parametrize('key', [Qt.Key_F, Qt.Key_H])
def test_selection_prefills_find_and_draft_is_committed(page, opened, key):
    e = page.subtitle_edit_input
    select(page, len(e.toPlainText())); e.insertPlainText('啊')
    index = page.undo_stack.index()
    select(page, 3, 4)  # 他
    press(e, key)
    assert len(opened) == 1
    dialog = opened[0]
    assert dialog.find_edit.text() == '他' and dialog.replace_edit.text() == ''
    assert dialog.focusWidget() is dialog.replace_edit
    # The pending edit reached the project before the replace can read it.
    assert page.project.cues[0].text == '😀她说他和它，其他人弹吉他。啊'
    assert page._caption_draft is None and not page._caption_following
    assert page.undo_stack.index() == index + 1
    assert page._caption_consumed_commit_key is None


def test_no_selection_opens_empty_search_like_the_page_shortcut(page, opened):
    e = page.subtitle_edit_input
    select(page, 2)
    press(e)
    assert len(opened) == 1
    assert opened[0].find_edit.text() == ''
    assert opened[0].focusWidget() is opened[0].find_edit
    assert page.project.cues[0].text == '😀她说他和它，其他人弹吉他。'


def test_multiline_selection_keeps_first_line_and_rebound_key(page, opened):
    e = page.subtitle_edit_input
    e.setPlainText('第一行\n第二行'); select(page, 1, 6)
    page._shortcut_values = dict(page._shortcut_values, find='Ctrl+G')
    press(e, Qt.Key_F)
    assert not opened and page._caption_draft is not None
    press(e, Qt.Key_G)
    assert opened and opened[0].find_edit.text() == '一行'
    assert page.project.cues[0].text == '第一行\n第二行'
