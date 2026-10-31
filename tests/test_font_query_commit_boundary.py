from tests.test_presentation_scope_contract import page
from PySide6.QtTest import QTest
from twobyteasr.caption_style.scoped_style import effective_layer_style
import copy


def test_search_and_cancel_never_create_project_or_undo_changes(page):
    p=page.project;cue=p.cues[0];page.select_cue(cue.id)
    before=copy.deepcopy(p.to_dict());undo=page.undo_stack.index()
    combo=page.style_font;combo.showPopup();combo.lineEdit().selectAll()
    QTest.keyClicks(combo.lineEdit(),'Cubic');QTest.qWait(450)
    combo.hidePopup();QTest.qWait(100)
    assert p.to_dict()==before
    assert page.undo_stack.index()==undo


def test_pending_numeric_edit_never_commits_a_font_search_query(page):
    p=page.project;cue=p.cues[0];page.select_cue(cue.id)
    page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
    page.style_layer.setCurrentIndex(page.style_layer.findData('original'))
    before=effective_layer_style(p,cue,'original').font_family
    combo=page.style_font;combo.showPopup();combo.lineEdit().selectAll()
    QTest.keyClicks(combo.lineEdit(),'Cubic')
    assert combo.committed_family()==before
    page.style_font_size.setValue(67);page._commit_style_now()
    assert effective_layer_style(p,cue,'original').font_family==before
    assert effective_layer_style(p,cue,'original').font_size==67
    combo.hidePopup();assert combo.currentText()==before
