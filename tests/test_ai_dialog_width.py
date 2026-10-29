"""AI 文字服务设置: nothing is cut off at the right (2026-10-25).

User (0.8.5): with 更多选项 open the service box, the key box, 保存设置, the
协议 box and 断句提示词 ran past the dialog's right edge. The form has no
horizontal scroll bar, and the dialog's width was a fixed number while the
form's minimum width (notes on one fixed line, 协议 at the end of the model
row) was larger. Now the notes wrap when they must, 协议 has its own row, and
the dialog is never narrower than its form; only a main window narrower than
the form makes it scroll sideways.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DEEPSEEK = dict(ai_service='deepseek', polish_provider='deepseek', group_provider='deepseek',
                polish_transport='openai_compatible', group_transport='openai_compatible',
                polish_model='deepseek-chat', group_model='deepseek-chat',
                polish_base_url='https://api.deepseek.com/v1', group_base_url='https://api.deepseek.com/v1')


@pytest.fixture
def window(monkeypatch):
    import subtitle_core
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    from twobyteasr.providers import llm_config
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda provider, base_url='': ('', ''))
    monkeypatch.setattr(llm_config, 'resolve_api_key', lambda stage: ('', ''))
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


def _settle(rounds=8):
    from PySide6.QtWidgets import QApplication
    for _ in range(rounds):
        QApplication.processEvents()


def _open_advanced(w):
    from PySide6.QtWidgets import QScrollArea
    w._open_ai_settings_dialog()
    _settle()
    w.ai_advanced_toggle.setChecked(True)
    _settle()
    dialog = w._ai_settings_dialog
    return dialog, dialog.findChild(QScrollArea, 'aiDialogScroll')


def test_a_note_keeps_one_line_while_there_is_room_and_wraps_when_there_is_not():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app.ai_settings_widgets import NoteLabel
    QApplication.instance() or QApplication([])
    note = NoteLabel('关着时断句、校对和翻译共用上面的服务和 Key')
    one_line = note.sizeHint().width()
    assert one_line >= note.fontMetrics().horizontalAdvance(note.text())
    # It asks for its whole line, but can give most of it back.
    assert note.minimumSizeHint().width() < one_line // 3
    assert note.heightForWidth(one_line // 3) > note.heightForWidth(one_line)


def test_the_notes_in_more_options_can_wrap(window):
    from twobyteasr.app.ai_settings_widgets import NoteLabel
    w = window
    notes = [w.ai_advanced_summary, w.separate_group_note, *w._ai_duty_notes.values()]
    assert all(isinstance(note, NoteLabel) and note.wordWrap() for note in notes)


def test_protocol_has_its_own_row_under_the_model(window):
    from PySide6.QtWidgets import QGridLayout
    editor = window.group_editor
    grid = editor.advanced_box.findChild(QGridLayout) or editor.advanced_box.layout().itemAt(0).layout()
    assert isinstance(grid, QGridLayout)

    def cell(widget):
        index = grid.indexOf(widget)
        assert index >= 0, widget
        return grid.getItemPosition(index)[:2]

    model_row = cell(editor.model_label)[0]
    assert cell(editor.protocol_label) == (cell(editor.protocol)[0], 0)
    assert cell(editor.protocol)[1] == 1 and cell(editor.protocol)[0] != model_row
    # The model row keeps the model and 刷新列表 only.
    row = grid.itemAtPosition(model_row, 1).layout()
    widgets = {row.itemAt(i).widget() for i in range(row.count())}
    assert editor.model in widgets and editor.discover_models_button in widgets
    assert editor.protocol not in widgets and editor.protocol_label not in widgets


def test_the_dialog_is_never_narrower_than_its_form(window):
    from PySide6.QtCore import Qt
    from twobyteasr.app.window_constraints import available_rect
    w = window
    dialog, scroll = _open_advanced(w)
    body = scroll.widget()
    bounds = available_rect(dialog, within_parent=True)
    bar = scroll.verticalScrollBar().sizeHint().width()
    # Make the form ask for nearly all the room the main window gives.
    host = w._ai_main_editor.capabilities_host
    extra = bounds.width() - bar - 30 - body.minimumSizeHint().width()
    host.setMinimumWidth(host.minimumSizeHint().width() + max(0, extra))
    _settle()
    w._ai_dialog_fit()
    _settle()
    need = body.minimumSizeHint().width() + bar
    assert need <= bounds.width()
    assert dialog.width() >= need
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert body.width() <= scroll.viewport().width()
    # Inside the main window, on its screen.
    assert bounds.contains(dialog.geometry())


def test_a_main_window_narrower_than_the_form_scrolls_sideways_instead_of_cutting(window):
    from PySide6.QtCore import Qt
    from twobyteasr.app.window_constraints import available_rect
    w = window
    dialog, scroll = _open_advanced(w)
    body = scroll.widget()
    bounds = available_rect(dialog, within_parent=True)
    host = w._ai_main_editor.capabilities_host
    host.setMinimumWidth(bounds.width() + 200)
    _settle()
    w._ai_dialog_fit()
    _settle()
    assert dialog.width() == bounds.width()
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    # Every part can be scrolled to.
    assert scroll.horizontalScrollBar().maximum() >= body.width() - scroll.viewport().width() > 0
    # Narrow again: no sideways scroll bar is left behind.
    host.setMinimumWidth(0)
    _settle()
    w._ai_dialog_fit()
    _settle()
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert body.width() <= scroll.viewport().width()


def test_switches_in_more_options_keep_their_whole_label(window):
    """English, 10-25: 「Use a separate service for line breaks」 lost its last letters."""
    from PySide6.QtWidgets import QSizePolicy
    w = window
    _open_advanced(w)
    for switch in (w.ai_grouping, w.ai_polish, w.prefer_arabic_numbers, w.separate_group_service, w.share_key):
        assert switch.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Minimum
    for switch in (w.ai_grouping, w.ai_polish, w.prefer_arabic_numbers, w.separate_group_service):
        assert switch.width() >= switch.sizeHint().width()


def test_the_notes_beside_the_switches_keep_to_one_line_when_the_window_has_room(window, monkeypatch):
    """The model group gives way first; the dialog widens (within the window) for the rest."""
    from PySide6.QtCore import QRect
    from twobyteasr.app import window_constraints
    w = window
    dialog, scroll = _open_advanced(w)
    # The offscreen screen is small; a maximized main window on the user's screen has room.
    monkeypatch.setattr(window_constraints, 'available_rect', lambda widget, within_parent=False: QRect(0, 0, 2400, 1400))
    narrow = [note for note in w._ai_duty_notes.values() if note.width() < note.sizeHint().width() - 1]
    assert narrow   # this test's small screen squeezed them first
    for _ in range(3):
        w._ai_dialog_fit()
        _settle()
    row = w._ai_options_row
    assert dialog.width() < 2400
    assert row.geometry().width() >= row.sizeHint().width()
    for note in w._ai_duty_notes.values():
        assert note.width() >= note.sizeHint().width() - 1, note.text()
