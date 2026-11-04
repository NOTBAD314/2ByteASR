"""Real table double clicks must retain the chosen layer and one edit authority."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.subtitle_rules.subtitle_translation import records_of


@pytest.mark.parametrize('layer',['original','translation'])
@pytest.mark.parametrize('action',['confirm','cancel'])
def test_table_double_click_uses_current_text_and_never_commits_a_second_editor(tmp_path,monkeypatch,layer,action):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('entry',1000,4000,'Original entry sentence',speaker_id='S01')])
    try:
        page.cue_controller.set_translation('entry','原有译文')
        page.resize(1400,850)
        page.show()
        page.select_cue('entry')
        page.timeline.set_subtitle_layer(layer)
        QTest.qWait(250)
        index=page.cue_model.index(page.cue_model.row_for_cue_id('entry'),3)
        page.cue_table.scrollTo(index)
        app.processEvents()
        position=page.cue_table.visualRect(index).center()
        initial_index=page.undo_stack.index()
        before=records_of(page.project)['entry']['text'] if layer=='translation' else page.project.cues[0].text
        assert page.cue_table.isVisible() and page.cue_table.visualRect(index).isValid()
        QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,pos=position)
        QTest.mouseDClick(page.cue_table.viewport(),Qt.LeftButton,pos=position)
        QTest.qWait(80)
        assert page._caption_draft is not None
        assert page._caption_draft.target.layer==layer
        assert page.subtitle_edit_input.toPlainText()==before
        updated='双击后的译文' if layer=='translation' else 'Edited original entry'
        page.subtitle_edit_input.setPlainText(updated)
        QTest.mouseClick(page.caption_confirm_button if action=='confirm' else page.caption_cancel_button,Qt.LeftButton)
        QTest.qWait(250)
        actual=records_of(page.project)['entry']['text'] if layer=='translation' else page.project.cues[0].text
        assert actual==(updated if action=='confirm' else before)
        assert page.undo_stack.index()==initial_index+(action=='confirm')
        if layer=='translation':assert page.project.cues[0].text=='Original entry sentence'
        else:assert records_of(page.project)['entry']['text']=='原有译文'
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()
