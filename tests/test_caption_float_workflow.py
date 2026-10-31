"""Bound drafts, first-click dispatch, follow/gap rules and native-free geometry."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QPushButton
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 0, 2000, '她在第一条'),
        StudioCue('b', 3000, 5000, '第二条'), StudioCue('c', 6000, 8000, '第三条')])
    page.timeline.set_playhead(100)
    page.select_cue('a')
    yield page
    page._cancel_canvas_inline_edit()
    page.close_page();page.deleteLater();app.processEvents()


def open_editor(page):
    page._open_caption_editor('a', 'original')
    QTest.qWait(20)
    return page.subtitle_edit_input


def test_float_does_not_resize_video_and_keeps_timeline_focus(page):
    geometry = page.video_overlay_host.geometry()
    open_editor(page)
    assert page.subtitle_edit_dock.isWindow()
    assert page.subtitle_edit_dock.windowModality() == Qt.WindowModality.NonModal
    assert page.video_overlay_host.geometry() == geometry
    assert not page._editing_has_focus()
    assert not page._caption_edit_locked
    page._end_caption_editor(keep_open=False)
    assert page.video_overlay_host.geometry() == geometry


def test_follow_changes_only_on_new_target_and_clears_gaps(page):
    editor = open_editor(page)
    draft = page._caption_draft
    for at in (200, 300, 700):
        page._follow_caption_editor(at)
        assert page._caption_draft is draft
    page._follow_caption_editor(3200)
    assert page._caption_draft.target.cue_id == 'b' and editor.toPlainText() == '第二条'
    page._follow_caption_editor(5200)
    assert page._caption_draft is None and not editor.isEnabled()
    assert '无字幕' in page.subtitle_edit_title.text()
    page._follow_caption_editor(6200)
    assert page._caption_draft.target.cue_id == 'c'


def test_cursor_interaction_locks_and_confirm_closes_until_explicit_reopen(page):
    editor = open_editor(page)
    QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton)
    assert page._caption_edit_locked
    page._follow_caption_editor(3200)
    assert page._caption_draft.target.cue_id == 'a'
    editor.setPlainText('锁定的A')
    page.timeline.set_playhead(6300)
    page._follow_caption_editor(6300)
    assert editor.toPlainText() == '锁定的A'
    QTest.keyClick(editor, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)
    assert page.project.cues[0].text == '锁定的A' and page.project.cues[2].text == '第三条'
    assert page._caption_draft is None and not page.subtitle_edit_dock.isVisible()
    page._follow_caption_editor(6300, force=True)
    QTest.qWait(30)
    assert not page._caption_following and not page.subtitle_edit_dock.isVisible()


@pytest.mark.parametrize('method', ['enter', 'keypad', 'shift-r', 'button'])
def test_unchanged_confirm_closes_without_review_or_extra_undo(page, method):
    editor = open_editor(page)
    before = page.undo_stack.count()
    if method == 'button':
        QTest.mouseClick(page.caption_confirm_button, Qt.LeftButton)
    else:
        key, mods = {'enter': (Qt.Key_Return, Qt.NoModifier),
                     'keypad': (Qt.Key_Enter, Qt.KeypadModifier),
                     'shift-r': (Qt.Key_R, Qt.ShiftModifier)}[method]
        QTest.keyClick(editor, key, mods)
    assert page.undo_stack.count() == before
    assert not page.subtitle_edit_dock.isVisible()
    assert page._caption_draft is None and not page._caption_following


@pytest.mark.parametrize('review',[False,True])
@pytest.mark.parametrize('key,mods',[(Qt.Key_Return,Qt.NoModifier),(Qt.Key_Enter,Qt.KeypadModifier),(Qt.Key_R,Qt.ShiftModifier)])
def test_follow_confirmation_owns_timeline_context_before_review_shortcuts(page,review,key,mods):
    page._set_review_mode(review)
    open_editor(page)
    QApplication.setActiveWindow(page.window());page.timeline.setFocus()
    QTest.qWait(10)
    count=page.undo_stack.count()
    QTest.keyClick(page.timeline,key,mods)
    assert not page.subtitle_edit_dock.isVisible() and not page._caption_following
    assert page.undo_stack.count()==count
    assert not page.project.studio_state.get('current_issue_decisions')


def test_external_button_first_click_saves_once_and_dispatches(page):
    editor = open_editor(page);editor.setPlainText('外点保存')
    button = QPushButton('outside', page);button.show()
    hits = [];button.clicked.connect(lambda: hits.append(True))
    before = page.undo_stack.count()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert hits == [True] and page.project.cues[0].text == '外点保存'
    assert page.undo_stack.count() == before + 1
    assert not page.subtitle_edit_dock.isVisible() and page._caption_draft is None


def test_close_saves_but_explicit_cancel_discards_and_clean_close_has_no_undo(page):
    editor = open_editor(page)
    before = page.undo_stack.count()
    QTest.mouseClick(page.caption_close_button, Qt.MouseButton.LeftButton)
    assert page.undo_stack.count() == before and not page._caption_following
    editor = open_editor(page);editor.setPlainText('关闭保存')
    QTest.mouseClick(page.caption_close_button, Qt.MouseButton.LeftButton)
    assert page.project.cues[0].text == '关闭保存'
    editor = open_editor(page);editor.setPlainText('取消不要')
    QTest.mouseClick(page.caption_cancel_button, Qt.MouseButton.LeftButton)
    assert page.project.cues[0].text == '关闭保存' and page._caption_draft is None


def test_failure_keeps_bound_draft_across_external_selection_and_retries(page, monkeypatch):
    editor = open_editor(page);editor.setPlainText('失败不丢字')
    target = page._caption_draft.target
    kind = type(page.cue_controller);original = kind.set_text
    def fail(*args, **kwargs):
        raise RuntimeError('controlled submission failure')
    monkeypatch.setattr(kind, 'set_text', fail)
    page._end_caption_editor(keep_open=False, restore_focus=False)
    page.select_cue('b');page._follow_caption_editor(6500)
    assert page._caption_draft.target == target and editor.toPlainText() == '失败不丢字'
    assert page.subtitle_edit_dock.isVisible() and page._caption_edit_locked
    assert '保留' in page.subtitle_edit_card.error_label.text()
    monkeypatch.setattr(kind, 'set_text', original)
    assert page._end_caption_editor(keep_open=False)
    assert page.project.cues[0].text == '失败不丢字' and page.project.cues[1].text == '第二条'


def test_confirm_waits_for_disk_success_and_failure_preserves_draft(page, monkeypatch):
    from twobyteasr.projects import studio_project as persistence
    editor = open_editor(page)
    editor.setPlainText('确认写盘失败仍保留')
    replace = persistence.os.replace
    def blocked(src, dst):
        if str(dst) == str(page.project_path):
            raise PermissionError('controlled confirmation disk failure')
        return replace(src, dst)
    monkeypatch.setattr(persistence.os, 'replace', blocked)
    monkeypatch.setattr(page, 'save', lambda: page.project_controller.save(message_box_fn=lambda *args: None))
    QTest.keyClick(editor, Qt.Key_Return)
    assert page.subtitle_edit_dock.isVisible() and page._caption_edit_locked
    assert page._caption_draft.target.cue_id == 'a'
    assert editor.toPlainText() == '确认写盘失败仍保留'
    assert page.subtitle_edit_card.error_label.isVisible()
    assert 'controlled confirmation disk failure' in page.subtitle_edit_card.error_detail.text()
    count = page.undo_stack.count()
    monkeypatch.setattr(persistence.os, 'replace', replace)
    QTest.keyClick(editor, Qt.Key_Return)
    assert persistence.load_project(page.project_path).cues[0].text == '确认写盘失败仍保留'
    assert not page.subtitle_edit_dock.isVisible() and page.undo_stack.count() == count


def test_preedit_and_owned_menu_do_not_retarget_or_close(page):
    editor = open_editor(page)
    QApplication.sendEvent(editor, QInputMethodEvent('ni', []))
    assert page._caption_edit_locked
    page._follow_caption_editor(3200)
    assert page._caption_draft.target.cue_id == 'a'
    menu = QMenu(editor);action = menu.addAction('复制')
    menu.popup(editor.mapToGlobal(QPoint(5, 5)));QTest.qWait(5)
    assert page._caption_window_owns(menu)
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    assert page._caption_draft.target.cue_id == 'a'
    menu.close()
    commit = QInputMethodEvent();commit.setCommitString('你')
    QApplication.sendEvent(editor, commit)
    assert '你' in editor.toPlainText()


def test_space_and_literal_e_in_text_do_not_toggle_playback(page, monkeypatch):
    editor = open_editor(page)
    hits = [];monkeypatch.setattr(page, '_toggle_playback', lambda: hits.append(1))
    QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton)
    QTest.keyClick(editor, Qt.Key.Key_Space);QTest.keyClick(editor, Qt.Key.Key_E)
    assert hits == [] and 'e' in editor.toPlainText() and ' ' in editor.toPlainText()


def test_E_in_gap_uses_project_clock_and_does_not_reuse_stale_selection(page):
    page.timeline.set_playhead(5500)
    page.select_cue('a')
    page.timeline.setFocus()
    QTest.keyClick(page.timeline, Qt.Key.Key_E)
    assert page._caption_following and page._caption_draft is None
    assert '无字幕' in page.subtitle_edit_title.text()
    assert page.subtitle_edit_dock.isVisible()


def test_ctrl_s_writes_disk_with_float_open_then_resumes_current_clock(page):
    from twobyteasr.projects.studio_project import load_project
    editor=open_editor(page);editor.setPlainText('CtrlS保存A')
    page.timeline.set_playhead(6300)
    QTest.keyClick(editor,Qt.Key.Key_S,Qt.ControlModifier)
    assert load_project(page.project_path).cues[0].text=='CtrlS保存A'
    assert page.undo_stack.isClean() and page.subtitle_edit_dock.isVisible()
    assert page._caption_draft.target.cue_id=='c' and not page._caption_edit_locked


def test_disk_failure_keeps_original_float_target_dirty_text_and_retries(page,monkeypatch):
    from twobyteasr.projects import studio_project as persistence
    editor=open_editor(page);editor.setPlainText('磁盘失败保留A')
    page.timeline.set_playhead(6300)
    original=persistence.os.replace
    def blocked(src,dst):
        if str(dst)==str(page.project_path):raise PermissionError('controlled disk failure')
        return original(src,dst)
    monkeypatch.setattr(persistence.os,'replace',blocked)
    errors=[];page.project_controller.save(message_box_fn=lambda *a:errors.append(str(a[-1])))
    assert errors and not page.undo_stack.isClean() and page._caption_edit_locked
    assert page._caption_draft.target.cue_id=='a' and editor.toPlainText()=='磁盘失败保留A'
    assert persistence.load_project(page.project_path).cues[0].text=='她在第一条'
    before=page.undo_stack.count()
    monkeypatch.setattr(persistence.os,'replace',original)
    QTest.keyClick(editor,Qt.Key.Key_S,Qt.ControlModifier)
    assert persistence.load_project(page.project_path).cues[0].text=='磁盘失败保留A'
    assert page.undo_stack.isClean() and page.undo_stack.count()==before
    assert page._caption_draft.target.cue_id=='c' and not page._caption_edit_locked


def test_translation_follow_and_locked_commit_keep_language_layer(page):
    from twobyteasr.subtitle_rules import subtitle_translation as st
    p=page.project
    p.generation_metadata['translations']={'a':'译文 A','b':'译文 B','c':'译文 C'}
    st.migrate(p)
    page._open_caption_editor('a','translation')
    page._follow_caption_editor(3200)
    assert page._caption_draft.target.cue_id=='b' and page._caption_draft.target.layer=='translation'
    editor=page.subtitle_edit_input
    QTest.mouseClick(editor.viewport(),Qt.LeftButton);editor.setPlainText('只改 B 的译文')
    page.timeline.set_playhead(6500);page._follow_caption_editor(6500)
    assert page._end_caption_editor(keep_open=True)
    assert p.generation_metadata['translations']['b']=='只改 B 的译文'
    assert page._cue_lookup['b'].text=='第二条'
    assert page._caption_draft.target.cue_id=='c' and page._caption_draft.target.layer=='translation'


def test_overlapping_import_tracks_follow_the_preferred_stable_track(tmp_path,monkeypatch):
    from twobyteasr.projects.studio_project import StudioSpeaker
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',0,7000,'原文',speaker_id='S00'),
        StudioCue('b',0,6000,'日本語',speaker_id='import-ja'),StudioCue('c',0,7000,'English',speaker_id='import-en')])
    try:
        p=page.project
        p.speakers.extend([StudioSpeaker('import-ja','日语'),StudioSpeaker('import-en','英语')])
        p.generation_metadata['subtitle_imports']={'tracks':{
            'import-ja':{'language':'ja','role':'independent'},'import-en':{'language':'en','role':'independent'}}}
        page._open_caption_editor('b','original')
        for at in (20,500,2000,5500):
            page._follow_caption_editor(at)
            assert page._caption_draft.target.cue_id=='b'
            assert page._caption_draft.target.track_id=='import-ja' and page._caption_draft.target.language=='ja'
        page._follow_caption_editor(6500)
        target=page._caption_draft.target
        for at in (6501,6502,6600):
            page._follow_caption_editor(at)
            assert page._caption_draft.target==target
    finally:
        page._cancel_canvas_inline_edit();page.close_page();page.deleteLater();app.processEvents()
