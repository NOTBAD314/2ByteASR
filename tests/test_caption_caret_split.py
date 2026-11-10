"""Regressions for exact Unicode boundaries, provisional splices and input ownership."""
import copy

import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_review_replay_and_window_bounds import _page
from tests.test_cue_word_alignment import project as aligned_project
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.studio.caption_editor import qt_position
from twobyteasr.timeline.caret_split import plan_caret_cut


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [
        StudioCue('a', 1000, 9000, '今日はここまで。また明日ね。'),
        StudioCue('b', 10000, 13000, '无关字幕')])
    page.select_cue('a')
    page._open_caption_editor('a', 'original')
    page._lock_caption_editor()
    QTest.qWait(20)
    yield page
    page._cancel_canvas_inline_edit()
    page.close_page()
    page.deleteLater()
    app.processEvents()


def cursor_at(page, text, position, *, selection=None):
    editor = page.subtitle_edit_input
    editor.setPlainText(text)
    cursor = editor.textCursor()
    cursor.setPosition(qt_position(text, position))
    if selection is not None:
        cursor.setPosition(qt_position(text, selection), QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    QApplication.setActiveWindow(page.subtitle_edit_dock)
    editor.setFocus()


@pytest.mark.parametrize('text,position', [
    ('今日はここまで。また明日ね。', 8),
    ('Hello world.  See you!\nNext line.', 14),
    ('你好， 世界。\n明天见！', 8),
    ('😀Cafe\u0301 家庭👨‍👩‍👧‍👦 继续', 6)])
def test_latest_text_conserved_cancel_and_one_project_undo(page, text, position):
    before = copy.deepcopy(page.project.cues)
    baseline_index = page.undo_stack.index()
    cursor_at(page, text, position)
    QTest.mouseClick(page.subtitle_edit_card.split_button, Qt.MouseButton.LeftButton)
    assert len(page.project.cues) == 3, page.subtitle_edit_card.split_status.text()
    assert [c.text for c in page.project.cues[:2]] == [text[:position], text[position:]]
    assert page.subtitle_edit_input.toPlainText() == text[position:]
    assert page.selected_cue_id == page._caption_draft.target.cue_id == page.project.cues[1].id
    assert page.undo_stack.index() == baseline_index
    assert '估算切点' in page.subtitle_edit_card.split_status.text()
    assert page.project.cues[0].end_ms == page.project.cues[1].start_ms
    assert page.project.cues[0].start_ms == before[0].start_ms
    assert page.project.cues[1].end_ms == before[0].end_ms
    page._cancel_canvas_inline_edit()
    assert page.project.cues == before
    assert page.undo_stack.index() == baseline_index
    page._open_caption_editor('a', 'original')
    cursor_at(page, text, position)
    assert page._split_caption_at_cursor(), page.subtitle_edit_card.split_status.text()
    page._caption_trigger_commit('test')
    after = copy.deepcopy(page.project.cues)
    assert page.undo_stack.index() == baseline_index + 1
    page.undo_stack.undo()
    assert page.project.cues == before
    page.undo_stack.redo()
    assert page.project.cues == after


@pytest.mark.parametrize('text,position,selection', [
    ('甲乙', 0, None), ('甲乙', 2, None), ('  甲乙', 1, None),
    ('甲乙\n ', 2, None), ('  \n ', 1, None), ('甲乙丙', 1, 2),
    ('Ae\u0301B', 2, None), ('A👨‍👩‍👧‍👦B', 3, None)])
def test_invalid_boundaries_preserve_draft_and_selection(page, text, position, selection):
    cursor_at(page, text, position, selection=selection)
    assert not page._split_caption_at_cursor()
    assert len(page.project.cues) == 2
    assert page.subtitle_edit_input.toPlainText() == text
    assert page.subtitle_edit_input.textCursor().hasSelection() == (selection is not None)
    assert page.subtitle_edit_card.split_status.text()


def test_continuous_cuts_navigation_local_undo_redo_and_final_edit(page):
    original = copy.deepcopy(page.project.cues)
    cursor_at(page, '甲乙丙丁戊己', 2)
    assert page._split_caption_at_cursor(), page.subtitle_edit_card.split_status.text()
    cursor_at(page, page.subtitle_edit_input.toPlainText(), 2)
    assert page._split_caption_at_cursor()
    assert [c.text for c in page.project.cues[:3]] == ['甲乙', '丙丁', '戊己']
    assert page._undo_caption_split()
    assert page.subtitle_edit_input.toPlainText() == '丙丁戊己'
    assert len(page.project.cues) == 3
    assert page._undo_caption_split(redo=True)
    assert len(page.project.cues) == 4
    page._navigate_split_part(-1)
    assert page.subtitle_edit_input.toPlainText() == '丙丁'
    page.subtitle_edit_input.setPlainText('丙丁改')
    page._navigate_split_part(1)
    page.subtitle_edit_input.setPlainText('戊己改')
    assert page._caption_trigger_commit('test')
    after = copy.deepcopy(page.project.cues)
    assert [c.text for c in after[:3]] == ['甲乙', '丙丁改', '戊己改']
    page.undo_stack.undo()
    assert page.project.cues == original
    page.undo_stack.redo()
    assert page.project.cues == after


def test_normal_c_copy_shift_enter_ime_and_repeat(page):
    editor = page.subtitle_edit_input
    cursor_at(page, '甲乙丙丁', 2)
    QTest.keyClicks(editor, 'c')
    assert editor.toPlainText() == '甲乙c丙丁'
    # 2026-11-10 (user): Shift+C cuts at the caret even with C mode off.
    cursor_at(page, '甲乙丙丁', 2)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ShiftModifier)
    assert len(page.project.cues) == 3 and editor.toPlainText() == '丙丁'
    page._undo_caption_split()
    assert len(page.project.cues) == 2
    page.subtitle_edit_card.split_mode.setChecked(True)
    cursor_at(page, '甲乙丙丁', 2)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert len(page.project.cues) == 2
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert '\n' in editor.toPlainText()
    cursor_at(page, '甲乙丙丁', 2)
    QApplication.sendEvent(editor, QInputMethodEvent('に', []))
    QTest.keyClick(editor, Qt.Key.Key_C)
    assert len(page.project.cues) == 2
    commit = QInputMethodEvent()
    commit.setCommitString('日')
    QApplication.sendEvent(editor, commit)
    QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier, 'c'))
    assert len(page.project.cues) == 2
    QTest.qWait(5)
    cursor_at(page, '甲乙丙丁', 2)
    QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier, 'c'))
    assert len(page.project.cues) == 3
    for _ in range(5):
        QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier, 'c', True))
    assert len(page.project.cues) == 3
    QApplication.sendEvent(editor, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier, 'c'))


def test_measured_cut_changed_text_and_playhead_validation():
    project = aligned_project('甲乙丙丁', [('甲', 100, 200), ('乙', 250, 300), ('丙', 1300, 1400), ('丁', 1500, 1750)])
    cue = project.cues[0]
    cut = plan_caret_cut(project, cue, cue.text, 2)
    assert cut.measured and cut.split_ms == 800
    changed = plan_caret_cut(project, cue, '甲加乙丙丁', 2)
    assert not changed.measured and changed.reason == 'text_changed'
    assert plan_caret_cut(project, cue, cue.text, 2, playhead_ms=600).split_ms == 600
    for time in (cue.start_ms, cue.end_ms, cue.start_ms + 1, cue.end_ms + 500):
        with pytest.raises(ValueError):
            plan_caret_cut(project, cue, cue.text, 2, playhead_ms=time)


def test_full_translation_once_no_other_track_change_and_cancel(page):
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual, snapshot, records_of
    set_manual(page.project, 'a', '今天就到这里。明天见。')
    before = snapshot(page.project)
    cursor_at(page, '今日はここまで。また明日ね。', 8)
    assert page._split_caption_at_cursor()
    records = records_of(page.project)
    assert records['a']['text'] == '今天就到这里。明天见。'
    right = page._caption_draft.target.cue_id
    assert records[right]['text'] == ''
    assert records['a']['status'] == records[right]['status'] == 'needs_update'
    assert records[right]['split_from']['translation'] == '今天就到这里。明天见。'
    assert page.project.cues[-1].id == 'b'
    page._cancel_canvas_inline_edit()
    assert snapshot(page.project) == before


def test_autosave_deferred_until_commit_and_no_track_or_table_reset(page, monkeypatch):
    from twobyteasr.projects.studio_save import capture_manual_save
    resets = []
    page.cue_model.modelReset.connect(lambda: resets.append(True))
    monkeypatch.setattr(page.timeline, 'reindex_project', lambda **kw: pytest.fail('whole track rebuild'))
    cursor_at(page, '甲乙丙丁', 2)
    assert page._split_caption_at_cursor()
    assert not resets
    with pytest.raises(RuntimeError):
        capture_manual_save(page, page.project, 1)
    page._start_autosave_worker(1)
    assert not getattr(page, '_autosave_worker_running', False)
    assert page._caption_trigger_commit('test')
    revision = capture_manual_save(page, page.project, 2)
    assert len(revision.cues) == 3


def test_cancel_after_navigation_text_edits_restores_metadata(page):
    state = copy.deepcopy(page.project.studio_state)
    metadata = copy.deepcopy(page.project.generation_metadata)
    cursor_at(page, '甲乙丙丁戊己', 2)
    assert page._split_caption_at_cursor()
    page.subtitle_edit_input.setPlainText('后半段修改')
    page._navigate_split_part(-1)
    page.subtitle_edit_input.setPlainText('前半段修改')
    page._navigate_split_part(1)
    page._cancel_canvas_inline_edit()
    assert page.project.studio_state == state
    assert page.project.generation_metadata == metadata


def test_manual_save_commits_once_and_preserves_active_part(page):
    cursor_at(page, '甲乙丙丁', 2)
    assert page._split_caption_at_cursor()
    target = page._caption_draft.target
    token = page._commit_caption_for_manual_save()
    assert token and page._caption_draft.target == target
    assert page._caption_split_session is None
    assert page.undo_stack.count() == 1


def test_close_page_rolls_back_pending_split(page):
    original = copy.deepcopy(page.project.cues)
    project = page.project
    cursor_at(page, '甲乙丙丁', 2)
    assert page._split_caption_at_cursor()
    page.begin_close_page()
    assert project.cues == original


def test_four_segments_and_explicit_playhead_calibration(page):
    cursor_at(page, '甲乙丙丁戊己庚辛', 2)
    page.timeline.set_playhead(2800)
    page.subtitle_edit_card.split_playhead.setChecked(True)
    assert page._split_caption_at_cursor()
    assert page.project.cues[0].end_ms == 2800
    assert '播放头校准' in page.subtitle_edit_card.split_status.text()
    page.subtitle_edit_card.split_playhead.setChecked(False)
    for text in ('丙丁戊己庚辛', '戊己庚辛'):
        cursor_at(page, text, 2)
        assert page._split_caption_at_cursor()
    assert [c.text for c in page.project.cues[:4]] == ['甲乙', '丙丁', '戊己', '庚辛']
    cursor_at(page, '庚辛', 1)
    page.subtitle_edit_card.split_playhead.setChecked(True)
    page.timeline.set_playhead(1000)
    assert not page._split_caption_at_cursor()
    assert len(page.project.cues) == 5


def test_full_style_speaker_and_word_receipts_are_retained(page):
    cue = page.project.cues[0]
    cue.appearance_override = {'font_size': 44, 'original': {'text_marks': []}}
    cue.transform = {'position_x': 0.3}
    before = copy.deepcopy(cue)
    page._bind_caption_editor(page._caption_draft.target)
    cursor_at(page, cue.text, 8)
    assert page._split_caption_at_cursor()
    left, right = page.project.cues[:2]
    assert left.id != right.id
    for part in (left, right):
        assert (part.speaker_id, part.style_id, part.effect_id, part.base_preset_id) == (
            before.speaker_id, before.style_id, before.effect_id, before.base_preset_id)
        assert part.transform == before.transform
        assert part.appearance_override['font_size'] == 44


def test_linked_translation_editor_refuses_ambiguous_source_mapping_without_loss(page):
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual, snapshot
    set_manual(page.project, 'a', '今天到这里，明天见。')
    page._cancel_canvas_inline_edit()
    page._open_caption_editor('a', 'translation')
    page._lock_caption_editor()
    before = snapshot(page.project)
    cursor_at(page, '今天到这里，明天见。', 6)
    assert not page._split_caption_at_cursor()
    assert '原文位置映射' in page.subtitle_edit_card.split_status.text()
    assert snapshot(page.project) == before and len(page.project.cues) == 2


def test_legacy_review_metadata_and_prior_manual_text_restored(page):
    from twobyteasr.subtitle_rules.current_issues import legacy_review_inputs
    page.project.studio_state['manual_caption_text'] = {'a': page.project.cues[0].text}
    page.project.studio_state['review_confirmations'] = {'a': 'accepted'}
    page.project.__dict__.pop('_legacy_review_inputs', None)
    legacy_review_inputs(page.project)
    before = copy.deepcopy(page.project.studio_state)
    cursor_at(page, '甲乙丙丁', 2)
    assert page._split_caption_at_cursor()
    page._cancel_canvas_inline_edit()
    assert page.project.studio_state == before


def test_c_from_initial_timeline_focus_belongs_to_open_window(page):
    cursor_at(page, '甲乙丙丁', 2)
    page.timeline.setFocus()
    assert not page._dispatch_shortcut_sequence('C')
    QTest.keyClick(page.timeline, Qt.Key_C)
    assert page.subtitle_edit_input.toPlainText() == '甲乙c丙丁'
    assert len(page.project.cues) == 2
    cursor_at(page, '甲乙丙丁', 2)
    page.subtitle_edit_card.split_mode.setChecked(True)
    page.timeline.setFocus()
    QTest.keyClick(page.timeline, Qt.Key_C)
    assert len(page.project.cues) == 3


def test_cut_undo_redo_retains_later_draft_edits(page):
    cursor_at(page, '甲乙丙丁', 2)
    assert page._split_caption_at_cursor()
    page.subtitle_edit_input.setPlainText('后段新文字')
    assert page._undo_caption_split()
    assert page.subtitle_edit_input.toPlainText() == '甲乙丙丁'
    assert page._undo_caption_split(redo=True)
    assert page.subtitle_edit_input.toPlainText() == '后段新文字'


def test_split_strip_keeps_complete_part_label_in_narrow_video(page):
    page.resize(1320, 880)
    cursor_at(page, '甲乙丙丁', 2)
    assert page._split_caption_at_cursor()
    QTest.qWait(100)
    page.subtitle_edit_dock.fit_to_workspace()
    panel = page.subtitle_edit_card
    assert panel._controls.hasHeightForWidth()
    assert panel._controls.heightForWidth(380) > panel.split_button.height()
    assert panel.split_part.width() >= panel.split_part.sizeHint().width()
    for widget in (panel.parts_host, panel.split_button, panel.pronoun_button,
                   panel.more_button, panel.cancel_button, panel.confirm_button):
        assert panel.strip_row.rect().contains(widget.geometry())
