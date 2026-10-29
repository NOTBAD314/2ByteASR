"""跟随播放头 with a field focused elsewhere (2026-10-27, user: follow is on
but the timeline does not move). Follow moves only the timeline's view, so a
focused number field (字号) or the timecode box must not switch it off; the
timeline's own text editor still holds the view still."""
from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

from tests.test_studio_cue_controller import _finish, _page


def _shown(tmp_path, monkeypatch):
    page = _page(tmp_path, monkeypatch)
    page.resize(1400, 850)
    page.show()
    page.workspace_splitter.show()   # the editor, not the project library
    QApplication.instance().processEvents()
    assert page.timeline.isVisible()
    QApplication.setActiveWindow(page)
    page.follow_playhead_toggle.setChecked(True)
    page.timeline.set_visible_window(0, 2000)
    page.timeline._follow_suspended_until = 0
    monkeypatch.setattr(page.video, '_paused', False)   # playing
    return page


def _focus(page, field):
    field.show()
    field.setFocus()
    QApplication.instance().processEvents()
    assert page._editing_has_focus()


def test_follow_keeps_moving_while_a_number_field_has_focus(tmp_path, monkeypatch):
    page = _shown(tmp_path, monkeypatch)
    _focus(page, QSpinBox(page))
    page._apply_project_playhead(2400)
    assert page.timeline.visible_start_ms > 0
    _finish(page)


def test_follow_keeps_moving_while_a_text_box_has_focus(tmp_path, monkeypatch):
    page = _shown(tmp_path, monkeypatch)
    _focus(page, QLineEdit(page))
    page._apply_project_playhead(2400)
    assert page.timeline.visible_start_ms > 0
    _finish(page)


def test_timeline_text_editor_still_holds_the_view(tmp_path, monkeypatch):
    page = _shown(tmp_path, monkeypatch)
    cue = page.project.cues[0]
    page.timeline._open_inline_editor(cue, False, cue.text)
    QApplication.instance().processEvents()
    assert page.timeline._inline_editor is not None and page.timeline._inline_editor.isVisible()
    page._apply_project_playhead(2400)
    assert page.timeline.visible_start_ms == 0
    _finish(page)
