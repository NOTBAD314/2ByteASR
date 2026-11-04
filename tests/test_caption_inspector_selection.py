import copy
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from tests.test_studio_style_controller import _page, _finish
from twobyteasr.caption_style.style_resolution import resolve_cue_visual
from twobyteasr.timeline.selection_scope import SelectionScope


def test_default_single_and_mixed_patch_from_real_panel(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        project = page.project
        before = copy.deepcopy(project.styles)
        page.select_cue('b')
        page.style_font_size.setValue(81)
        page._commit_style_now()
        assert resolve_cue_visual(project, project.cues[0]).style.font_size == 48
        assert resolve_cue_visual(project, project.cues[1]).style.font_size == 81
        assert project.styles == before
        page.undo_stack.undo()
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(['a','c'], 'a'))
        page.style_fill_color.setText('#00FF00')
        page._style_control_changed()
        assert resolve_cue_visual(project, project.cues[1]).style.primary_color == '#FF99CC'
        assert [resolve_cue_visual(project, c).style.primary_color for c in (project.cues[0],project.cues[2])] == ['#00FF00']*2
        page.undo_stack.undo()
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(['a','b'], 'a'))
        page.style_font_size.setValue(67)
        page._commit_style_now()
        assert resolve_cue_visual(project, project.cues[1]).style.primary_color == '#FF99CC'
        assert resolve_cue_visual(project, project.cues[1]).style.bold is True
    finally:
        _finish(page)


def test_markdown_entry_keeps_raw_editor_and_plain_project(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        page.original_text_tools.mode.setCurrentIndex(1)
        page.cue_text.setPlainText('今天**最後一關**。')
        assert page.project.cues[0].text == '今天最後一關。'
        assert page.cue_text.toPlainText() == '今天**最後一關**。'
        assert page.project.cues[0].appearance_override['text_marks'] == [{'start':2,'end':6,'bold':True}]
        assert (page.project.cues[0].start_ms,page.project.cues[0].end_ms) == (0,1200)
        page.undo_stack.undo()
        assert page.project.cues[0].text == 'First'
    finally:
        _finish(page)


def test_review_aliases_and_typing_context(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch)
    try:
        page._review_mode = True
        directions = []
        page._step_priority = directions.append
        page.cue_table.setFocus()
        for key in ('W','A','S','D','Down','Up'):
            assert page._dispatch_shortcut_sequence(key)
        assert directions == [1,1,-1,-1,1,-1]
        page.cue_text.show(); page.cue_text.setFocus(); app.processEvents()
        page._studio_ime_composing = True
        assert not page._dispatch_shortcut_sequence('W')
        page._studio_ime_composing = False
    finally:
        _finish(page)


def test_visible_highlight_does_not_reenter_text_commands(tmp_path, monkeypatch):
    from PySide6.QtTest import QSignalSpy
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.show();page.context_drawer.setCurrentIndex(1)
        page.original_text_tools.mode.setCurrentIndex(1)
        page.cue_text.setPlainText('**文字**')
        page.original_text_tools.mode.setCurrentIndex(0)
        spy=QSignalSpy(page.cue_text.textChanged)
        before=page.undo_stack.count()
        for _ in range(8):page.original_text_tools.rehighlight()
        app.processEvents()
        assert spy.count()==0
        assert page.undo_stack.count()==before
        assert page.project.cues[0].text=='文字'
    finally:_finish(page)


def test_insert_identical_word_before_marked_second_occurrence(tmp_path, monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.original_text_tools.mode.setCurrentIndex(1)
        page.cue_text.setPlainText('火球**火球**')
        page.original_text_tools.mode.setCurrentIndex(0)
        cursor=page.cue_text.textCursor();cursor.setPosition(0);page.cue_text.setTextCursor(cursor)
        page.cue_text.insertPlainText('火球')
        assert page.project.cues[0].text=='火球火球火球'
        assert page.project.cues[0].appearance_override['text_marks']==[{'start':4,'end':6,'bold':True}]
    finally:_finish(page)


def test_translation_inspector_loads_and_changes_its_own_shadow(tmp_path, monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.project.generation_metadata['translations']={'a':'譯文'}
        page.project.cues[0].appearance_override={'translation':{'recipe':{
            'outline':{'shadow':{'enabled':True,'opacity':.23,'offset_x':3,'offset_y':4,'blur_radius':2}}}}}
        page._changed()
        page.style_layer.setCurrentIndex(page.style_layer.findData('translation'))
        assert page.style_shadow_opacity.value()==23
        page.style_shadow_opacity.setValue(67);page._commit_style_now()
        assert page.project.cues[0].appearance_override['translation']['recipe']['outline']['shadow']['opacity']==.67
        assert not page.project.style_recipes
    finally:_finish(page)


def test_translation_then_group_position_uses_the_new_layer(tmp_path, monkeypatch):
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    from twobyteasr.caption_style.style_resolution import resolve_cue_visual
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.project.generation_metadata['translations']={'a':'Translated'}
        page.project.studio_state['bilingual']={'mode':'bilingual'}
        page._changed();page.select_cue('a')
        page.style_layer.setCurrentIndex(page.style_layer.findData('translation'))
        page.style_font_size.setValue(29);page._commit_style_now()
        page.style_layer.setCurrentIndex(page.style_layer.findData('group'))
        assert page.style_position_x.isEnabled()
        page.style_position_x.setValue(550);page._commit_style_now()
        shown={c.id:c for c in project_display_cues(page.project)}
        assert resolve_cue_visual(page.project,shown['a']).style.position_x==550
        assert resolve_cue_visual(page.project,shown['a#tr']).style.position_x==550
    finally:_finish(page)


def test_copy_paste_preserves_local_marks_and_one_project_undo(tmp_path, monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.original_text_tools.mode.setCurrentIndex(1)
        page.cue_text.setPlainText('前**火球**後')
        page.original_text_tools.mode.setCurrentIndex(0)
        cursor=page.cue_text.textCursor();cursor.setPosition(1);cursor.setPosition(3,QTextCursor.KeepAnchor)
        page.cue_text.setTextCursor(cursor)
        mime=page.cue_text.createMimeDataFromSelection()
        assert mime.hasFormat(page.cue_text.MIME), mime.formats()
        page.select_cue('b');before=page.undo_stack.count()
        page.cue_text.selectAll();page.cue_text.insertFromMimeData(mime)
        assert page.project.cues[1].text=='火球'
        assert page.project.cues[1].appearance_override['text_marks']==[{'start':0,'end':2,'bold':True}]
        assert page.undo_stack.count()==before+1
        page.undo_stack.undo()
        assert page.project.cues[1].text=='Second'
        page.original_text_tools.mode.setCurrentIndex(1)
        page.cue_text.selectAll();page.cue_text.insertFromMimeData(mime)
        assert page.project.cues[1].text=='火球'
        assert page.project.cues[1].appearance_override['text_marks']==[{'start':0,'end':2,'bold':True}]
    finally:_finish(page)


def test_markdown_tool_edit_preserves_color_and_glossary_suppression(tmp_path, monkeypatch):
    from twobyteasr.caption_style.text_marks import runs
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.original_text_tools.apply('火球火球',[{'start':2,'end':4,'color':'#FF0000','highlight':False}])
        page.original_text_tools.mode.setCurrentIndex(1)
        cursor=page.cue_text.textCursor();cursor.setPosition(2);cursor.setPosition(4,QTextCursor.KeepAnchor)
        page.cue_text.setTextCursor(cursor);page.original_text_tools.format_selection('italic')
        cue=page.project.cues[0]
        assert cue.text=='火球火球'
        formatted=runs(cue.text,cue.appearance_override['text_marks'])[-1]
        assert formatted[2]['color']=='#FF0000' and formatted[2]['highlight'] is False and formatted[2]['italic']
        cursor=page.cue_text.textCursor();cursor.movePosition(QTextCursor.End);page.cue_text.setTextCursor(cursor)
        page.cue_text.insertPlainText('!')
        assert any(m.get('highlight') is False for m in cue.appearance_override['text_marks'])
    finally:_finish(page)


def test_caption_editor_keeps_existing_manual_glossary_learning(tmp_path, monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        cue=page.project.cues[0];cue.text='那维来特最强辅助'
        page._manual_text_baselines[cue.id]=cue.text
        page.original_text_tools.hydrate(cue,cue.text)
        page.cue_text.setPlainText('那维莱特最强辅助')
        page.cue_controller.commit_manual_term_learning(cue.id)
        assert len(page._learning_store.pending())==1
        page.undo_stack.undo()
        assert cue.text=='那维来特最强辅助'
    finally:_finish(page)
