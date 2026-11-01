"""Every explicit dismissal discards only the bound draft, including late work."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import traceback

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue, load_project, save_project


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [
        StudioCue('stable-a', 6333, 11417, "Mina wan uh basically uh it's might be driver updates or something", speaker_id='S00'),
        StudioCue('stable-b', 12000, 14500, 'Another caption', speaker_id='S01')])
    page.select_cue('stable-a')
    page.cue_controller.set_translation('stable-a', '原有译文', target='zh-CN')
    yield app, page
    page.close_page(); page.deleteLater(); app.processEvents()


@pytest.mark.parametrize('layer', ['original', 'translation'])
@pytest.mark.parametrize('exit_kind', ['cancel', 'escape', 'header_close', 'window_close'])
def test_dismissal_never_commits_an_empty_draft(page, tmp_path, monkeypatch, layer, exit_kind):
    app, page = page
    page._open_caption_editor('stable-a', layer)
    draft = page._caption_draft
    before = draft.target.read(page.project)
    page.subtitle_edit_input.setPlainText('')
    page._flush_edit_preview()
    index, count = page.undo_stack.index(), page.undo_stack.count()
    autosave = page._autosave_generation
    calls = []
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand
    original = SetCueFieldsCommand.redo
    def observed(command):
        calls.append(dict(command=command.text(), fields=command.after,
                          stack=traceback.format_stack()))
        return original(command)
    monkeypatch.setattr(SetCueFieldsCommand, 'redo', observed)
    # Exercise the actual widgets and the OS-close handler, not a cancel stub.
    if exit_kind == 'cancel': QTest.mouseClick(page.caption_cancel_button, Qt.LeftButton)
    elif exit_kind == 'escape': QTest.keyClick(page.subtitle_edit_input, Qt.Key_Escape)
    elif exit_kind == 'header_close': QTest.mouseClick(page.caption_close_button, Qt.LeftButton)
    else: page.subtitle_edit_dock.close()
    QTimer.singleShot(0, page._flush_edit_preview)
    QTimer.singleShot(0, page._commit_canvas_inline_edit)
    QTest.qWait(250); app.processEvents()
    (tmp_path / 'writes.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2), 'utf8')
    assert draft.target.read(page.project) == before, calls
    assert page.undo_stack.index() == index and page.undo_stack.count() == count
    assert page._autosave_generation == autosave
    assert page._caption_draft is None and not page.subtitle_edit_dock.isVisible()
    assert not page._live_edit_text_overrides
    saved = save_project(page.project, tmp_path / 'dismissed.2byteproj')
    assert draft.target.read(load_project(saved)) == before


@pytest.mark.parametrize('layer', ['original', 'translation'])
@pytest.mark.parametrize('exit_kind', ['cancel', 'escape', 'header_close', 'window_close'])
def test_rejected_draft_keeps_current_authority_and_prior_undo(page, tmp_path, layer, exit_kind):
    app, page = page
    page._open_caption_editor('stable-a', layer)
    draft = page._caption_draft
    page.subtitle_edit_input.setPlainText('My rejected draft')
    if layer == 'original': page.cue_controller.set_text('stable-a', 'Concurrent legal edit')
    else: page.cue_controller.set_translation('stable-a', 'Concurrent legal edit', target=draft.target.language)
    page._flush_edit_preview()
    assert not page._caption_trigger_commit('button')
    assert 'text_conflict' in page.subtitle_edit_card.error_detail.text()
    index, count = page.undo_stack.index(), page.undo_stack.count()
    revision = page._autosave_generation
    if exit_kind == 'cancel': QTest.mouseClick(page.caption_cancel_button, Qt.LeftButton)
    elif exit_kind == 'escape': QTest.keyClick(page.subtitle_edit_input, Qt.Key_Escape)
    elif exit_kind == 'header_close': QTest.mouseClick(page.caption_close_button, Qt.LeftButton)
    else: page.subtitle_edit_dock.close()
    QTest.qWait(250); app.processEvents()
    assert draft.target.read(page.project) == 'Concurrent legal edit'
    assert (page.undo_stack.index(), page.undo_stack.count()) == (index, count)
    assert page._autosave_generation == revision
    assert page._caption_draft is None and not page._live_edit_text_overrides
    saved = save_project(page.project, tmp_path / 'rejected.2byteproj')
    assert draft.target.read(load_project(saved)) == 'Concurrent legal edit'
    page.undo_stack.undo()
    assert draft.target.read(page.project) == draft.before
    page.undo_stack.redo()
    assert draft.target.read(page.project) == 'Concurrent legal edit'
