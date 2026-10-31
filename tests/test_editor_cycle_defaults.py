"""User-requested candidate ring, complete draft pronouns and safe E defaults."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtCore import QPoint,QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_caption_editor_a import page, seed_candidates, key


def test_candidates_and_body_form_bidirectional_ring(page, monkeypatch):
    before=seed_candidates(page,monkeypatch);editor=page.subtitle_edit_input;view=page.caption_suggestion_text
    editor.setFocus();key(editor,Qt.Key_W)
    assert view.selected==(0,0)
    for selected in ((0,1),(1,0),None,(0,0)):
        key(QApplication.focusWidget(),Qt.Key_D)
        assert editor.hasFocus() if selected is None else view.owns_focus() and view.selected==selected
    for selected in (None,(1,0),(0,1),(0,0)):
        key(QApplication.focusWidget(),Qt.Key_A)
        assert editor.hasFocus() if selected is None else view.owns_focus() and view.selected==selected
    assert editor.toPlainText()==before and page.project.cues[0].text==before


def test_shift_s_no_longer_navigates(page,monkeypatch):
    seed_candidates(page,monkeypatch);key(page.subtitle_edit_input,Qt.Key_W)
    key(QApplication.focusWidget(),Qt.Key_S)
    assert page.caption_suggestion_text.selected==(0,0)
    assert 'Shift+S' not in page.caption_editor_hint.text()


@pytest.mark.parametrize('from_timeline',[False,True])
def test_pronoun_key_flips_all_draft_pronouns_without_cursor_requirement(page,from_timeline):
    editor=page.subtitle_edit_input;before=page.project.cues[0].text
    editor.setPlainText('他和她带他们去弹吉他，其他人等她。')
    cursor=editor.textCursor();cursor.setPosition(12);editor.setTextCursor(cursor)
    target=page.timeline if from_timeline else editor
    target.setFocus();key(target,Qt.Key_P)
    assert editor.toPlainText()=='她和他带她们去弹吉他，其他人等他。'
    assert page.project.cues[0].text==before and page.project.cues[1].text=='第二条保持不变'
    page._cancel_canvas_inline_edit()
    assert page.project.cues[0].text==before


def test_gap_has_no_stale_disabled_caption(page):
    page._caption_edit_locked=False
    page._follow_caption_editor(5050,force=True)
    page.select_cue('b')
    assert page._caption_draft is None and not page.subtitle_edit_input.isEnabled()
    assert page.subtitle_edit_input.toPlainText()==''
    assert '无字幕' in page.subtitle_edit_title.text()


@pytest.mark.parametrize('pause',[True,False])
@pytest.mark.parametrize('layer',['original','translation'])
def test_E_pause_and_preferred_layer_are_independent_preferences(page,monkeypatch,pause,layer):
    from twobyteasr.subtitle_rules import subtitle_translation as st
    page._cancel_canvas_inline_edit();p=page.project
    p.generation_metadata['translations']={'a':'Translated A','b':'Translated B'}
    st.migrate(p)
    monkeypatch.setattr(page,'_studio_preferences',lambda:dict(caption_pause_on_edit=pause,caption_default_layer=layer))
    calls=[];monkeypatch.setattr(page.video,'set_paused',lambda value:calls.append(value))
    page.timeline.set_playhead(100);page.timeline.active_subtitle_layer='original'
    page._edit_subtitle_at_playhead()
    assert calls==([True] if pause else [])
    assert page._caption_draft.target.layer==layer
    assert page.subtitle_edit_input.toPlainText()==('Translated A' if layer=='translation' else p.cues[0].text)
    assert ('译文' if layer=='translation' else '原文') in page.subtitle_edit_title.text()


def test_missing_preferences_choose_pause_and_translation(page,monkeypatch):
    from twobyteasr.app.settings_lifecycle import normalized_preferences
    values,_=normalized_preferences({})
    assert values['caption_pause_on_edit'] is True and values['caption_default_layer']=='translation'


def test_E_preferences_round_trip_and_old_saving_call_preserves_them(tmp_path,monkeypatch):
    import json
    from twobyteasr.app import application_settings as settings
    path=tmp_path/'settings.json'
    monkeypatch.setattr(settings,'studio_settings_path',lambda:path)
    settings.save_hub_preferences('',True,60,9,True,True,
        caption_pause_on_edit=False,caption_default_layer='original')
    settings.save_hub_preferences('',True,120,9,True,True)
    saved=json.loads(path.read_text('utf8'))['studio_preferences']
    assert saved['caption_pause_on_edit'] is False and saved['caption_default_layer']=='original'


def test_E_controls_appear_in_studio_settings_with_new_defaults(page,tmp_path):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    dialog=ApplicationSettingsDialog(page.window(),{},tmp_path,browse=lambda *a:None,
        clear_recent=lambda:None,reset_layout=lambda:None)
    dialog.ensure_section('Studio 与维护')
    assert dialog.caption_pause_on_edit.isChecked()
    assert dialog.caption_default_layer.currentData()=='translation'
    dialog.deleteLater()


def test_two_candidate_rows_fit_their_viewport(page,monkeypatch):
    from twobyteasr.design.theme_manager import apply_theme
    apply_theme('grape')
    seed_candidates(page,monkeypatch);QTest.qWait(100)
    view=page.caption_suggestion_text
    details=dict(view=view.size().toTuple(),viewport=view.viewport().size().toTuple(),
        hint=view._layout.sizeHint().toTuple(),body=view._body.size().toTuple(),
        rows=[dict(rect=f.geometry().getRect(),hint=f.sizeHint().toTuple(),
            buttons=[dict(rect=b.geometry().getRect(),hint=b.sizeHint().toTuple()) for b in f.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)]) for f in view._frames])
    for frame in view._frames:
        for button in frame.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton):
            rect=QRect(button.mapTo(view.viewport(),QPoint()),button.size())
            assert view.viewport().rect().contains(rect),details
    assert view.geometry().bottom()<page.subtitle_edit_input.geometry().top(),dict(
        suggestions=view.geometry().getRect(),editor=page.subtitle_edit_input.geometry().getRect())


def test_shortcut_groups_are_atomic_and_newline_precedes_commit(page):
    hint=page.caption_editor_hint
    page.subtitle_edit_card.update_hint()
    assert hint.text().index('Shift+Enter')<hint.text().index('Enter/Shift+R')
    assert all(not label.wordWrap() for label in hint.groups)
    assert hint.groups[-1].text()=='Enter/Shift+R 保存并关闭'
