"""Candidate identity, actual mouse/key events and filtered bulk selection."""
import time
from types import SimpleNamespace

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.glossary.glossary_skill import SearchedTerm, TermDiff
from twobyteasr.glossary.glossary_skill_ui import DiffTableModel, GlossaryUpdateReviewDialog


def diffs(count=1200):
    return [TermDiff('new', SearchedTerm(term=f'候选{i:04d}',
        category=('角色', '技能', '装备')[i % 3],
        category_key=('character', 'skill', 'equipment')[i % 3],
        priority='core' if i % 3 == 0 else 'optional', verification='catalog_verified',
        sources=({'url': 'https://example.com/roster'},)), checked_by_default=False)
        for i in range(count)]


def test_filtered_bulk_and_append_keep_identity():
    app = QApplication.instance() or QApplication([])
    model = DiffTableModel(); model.set_diffs(diffs())
    model.set_filters(category='技能'); model.check_filtered(True)
    initial = {d.term.term for d in model.checked_diffs()}
    model.set_filters(category='角色'); model.check_filtered(True)
    assert model.checked_count() == 800
    model.check_filtered(False)
    assert {d.term.term for d in model.checked_diffs()} == initial
    model.check_filtered(None)
    before = {d.term.term for d in model.checked_diffs()}
    model.sort(1, Qt.SortOrder.DescendingOrder)
    model.append_diffs(diffs(1203))
    assert {d.term.term for d in model.checked_diffs()} == before
    assert model.rowCount() == 401
    model.check_none(); model.set_filters(); model.check_core_verified()
    assert model.checked_count() == 401


def test_mouse_checkbox_range_keyboard_and_filter_counts():
    app = QApplication.instance() or QApplication([])
    owner = QWidget(); owner.legacy = SimpleNamespace()
    owner.show()
    dlg = GlossaryUpdateReviewDialog(owner, '测试', {'diffs': diffs(), 'candidate_count':1200})
    dlg.resize(1150, 800); dlg.show(); app.processEvents()
    view = dlg.table; model = dlg.model
    def click(row, col=1, mods=Qt.KeyboardModifier.NoModifier):
        idx = model.index(row, col); view.scrollTo(idx); app.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, mods, view.visualRect(idx).center())
        app.processEvents()
    click(0); assert model.checked_count() == 1
    click(0); assert model.checked_count() == 0
    click(0, 0); assert model.checked_count() == 1
    click(0, 0); assert model.checked_count() == 0
    click(1, mods=Qt.KeyboardModifier.ControlModifier)
    click(4, mods=Qt.KeyboardModifier.ShiftModifier)
    assert model.checked_count() == 0
    QTest.keyClick(view, Qt.Key.Key_Space); app.processEvents()
    assert model.checked_count() == len(view.selectionModel().selectedRows())
    model.check_none()
    dlg.category_filter.setCurrentIndex(dlg.category_filter.findData('角色'))
    view.setFocus(); QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(view, Qt.Key.Key_Space); app.processEvents()
    assert model.checked_count() == 400
    dlg.category_filter.setCurrentIndex(dlg.category_filter.findData('技能'))
    assert '筛选外 400' in dlg.checked_label.text()
    dlg.search_box.setText('候选'); dlg.search_box.setFocus()
    QTest.keyClick(dlg.search_box, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert dlg.search_box.selectedText() == '候选'
    assert model.checked_count() == 400
    dlg.close(); owner.close()


def test_metadata_upgrade_and_resumed_choices_do_not_create_new_identity():
    from dataclasses import replace
    app=QApplication.instance() or QApplication([])
    original=diffs(3);shared={}
    model=DiffTableModel();model.review_choices=shared;model.set_diffs(original)
    model.check_rows([0],True);model.check_rows([1],False)
    chosen=model.row_identity(0);rejected=model.row_identity(1)
    upgraded=replace(original[0],change_type='alias_supplement',term=replace(original[0].term,verification='page_verified'))
    model.append_diffs([upgraded])
    assert len(model.diffs())==3 and chosen in model._checked
    assert next(d for d in model.diffs() if model.identity(d)==model.identity(upgraded)).term.verification=='page_verified'
    resumed=DiffTableModel();resumed.review_choices=shared
    resumed.set_diffs([replace(d,checked_by_default=True) for d in model.diffs()])
    assert chosen in resumed._checked and rejected not in resumed._checked


def test_detail_expand_and_copy_do_not_toggle_checked_candidates():
    app = QApplication.instance() or QApplication([])
    owner = QWidget(); owner.legacy = SimpleNamespace()
    owner.show()
    dlg = GlossaryUpdateReviewDialog(owner, '测试', {'diffs': diffs(3)})
    dlg.resize(1150, 800); dlg.show(); app.processEvents()
    index = dlg.model.index(0, 1)
    QTest.mouseClick(dlg.table.viewport(), Qt.LeftButton, pos=dlg.table.visualRect(index).center())
    checked = set(dlg.model._checked)
    QTest.mouseClick(dlg.detail_toggle, Qt.LeftButton); app.processEvents()
    assert dlg.detail.isVisible()
    assert 'https://example.com/roster' in dlg.detail.toPlainText()
    QTest.mouseClick(dlg.copy_detail, Qt.LeftButton)
    assert QApplication.clipboard().text() == dlg.detail.toPlainText()
    assert dlg.model._checked == checked
    assert dlg.table.currentIndex().row() == 0
    dlg.close(); owner.close()
