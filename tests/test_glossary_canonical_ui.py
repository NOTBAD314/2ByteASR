"""Actual Qt form actions with isolated glossary storage."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QMimeData, QTimer, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QCheckBox, QLabel, QWidget
import subtitle_core as legacy
from twobyteasr.main_ui_glossary import TermLibraryDialog

APP = QApplication.instance() or QApplication([])


class Owner(QWidget):
    def __init__(self):
        super().__init__()
        self.legacy = legacy
        self.game_box = QComboBox()
        self.game_box.setEditable(True)
        self.terms = QCheckBox()
        self.term_hint = QLabel()
        self.refreshes = 0

    def _enabled_glossary_ids(self):
        return list(legacy.RUNTIME_SETTINGS.get('glossary', {}).get('enabled_glossary_ids', []))

    def _save_glossary_settings(self):
        pass

    def _refresh_content_choices(self):
        self.refreshes += 1


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    monkeypatch.setattr(legacy, 'RUNTIME_SETTINGS', {'glossary': {'enabled_glossary_ids': []}})
    owner = Owner()
    page = TermLibraryDialog(owner, page_mode=True)
    page.resize(1200, 850)
    yield page
    page._task_manager and page._task_manager.shutdown(wait_ms=300)
    page.close()
    owner.close()


def create(page, name):
    page.game_input.setText(name)
    page.create_game()
    APP.processEvents()
    page.refresh_current_game()


def test_create_add_and_multi_enable_announce_real_result(dialog):
    create(dialog, '瓦罗兰特')
    assert dialog.owner.refreshes
    dialog.term_editor.setText('BerLIN')
    dialog.term_alias_editor.setText('Borlin')
    assert 'BerLIN' in dialog.term_parse_preview.text()
    dialog.add_single_term()
    assert {(r['from'], r['to']) for r in legacy.learned_mappings_for_game('瓦罗兰特')} == {
        ('BerLIN', 'BerLIN'), ('Borlin', 'BerLIN')}
    dialog.use_selected_game()
    assert '有效' in dialog.batch_status.text()
    create(dialog, '另一个库')
    dialog.use_selected_game()
    assert len(dialog.owner._enabled_glossary_ids()) == 2
    assert '0' in dialog.batch_status.text()


def test_quick_arrow_parse_and_filtered_bulk_scope(dialog):
    create(dialog, '测试')
    dialog.term_editor.setText('Borlin → BerLIN')
    assert 'Borlin' in dialog.term_parse_preview.text()
    assert 'BerLIN' in dialog.term_parse_preview.text()
    dialog.add_single_term()
    dialog.term_editor.setText('S0PP')
    dialog.add_single_term()
    dialog.search.setText('berlin')
    dialog.apply_filter()
    dialog.listing.selectAll()
    assert len(dialog._selected_rows_by_status()['confirmed']) == 1
    dialog.remove_selected_terms()
    assert [r['to'] for r in legacy.learned_mappings_for_game('测试')] == ['S0PP']


def test_case_only_form_edit_uses_atomic_edit(dialog):
    create(dialog, '测试')
    legacy.add_learned_mapping('测试', 'berlin', 'berlin')
    mapping = legacy.learned_mappings_for_game('测试')[0]
    dialog._show_edit_sheet(mapping)
    dialog.edit_canonical.setText('BerLIN')
    dialog.edit_save_button.click()
    assert legacy.learned_mappings_for_game('测试')[0]['to'] == 'BerLIN'


def test_import_preview_preserves_confirmed_spelling_export_and_rename(dialog, tmp_path):
    create(dialog, '测试')
    legacy.add_learned_mapping('测试', 'BerLIN', 'BerLIN')
    legacy.add_learned_mapping('测试', 'Borlin', 'BerLIN')
    library_id = legacy.resolve_glossary_identity('测试')
    dialog.show_import_dialog()
    dialog.import_editor.setPlainText('berlin\nBorlin → 别人\ns0pp → S0PP')
    assert '冲突' in dialog.import_preview.toPlainText()
    assert 'BerLIN' in dialog.import_preview.toPlainText()
    dialog.import_save_button.click()
    assert {row['to'] for row in legacy.learned_mappings_for_game(library_id)} == {'BerLIN', 'S0PP'}
    dialog.use_selected_game()
    dialog._rename_library(library_id, '新显示名')
    assert library_id in dialog.owner._enabled_glossary_ids()
    assert dialog.state['game'] == '新显示名'
    target = tmp_path / 'export.json'
    dialog._export_library_to(target)
    from twobyteasr.main_ui_glossary import preview_term_import
    rows = preview_term_import(target.read_text('utf8'))
    assert {row['to'] for row in rows} == {'BerLIN', 'S0PP'}


def test_try_sentence_uses_real_shared_resolver(dialog):
    create(dialog, '测试')
    legacy.add_learned_mapping('测试', 'Borlin', 'BerLIN')
    dialog.owner.resize(1250, 900)
    dialog.owner.show()
    dialog.show()
    APP.processEvents()
    dialog.term_try_input.setText('Borlin也没有接住')
    dialog.try_sentence()
    APP.processEvents()
    assert 'BerLIN也没有接住' in dialog.term_try_result.text()
    assert '替换 1 处' in dialog.term_try_result.text()
    label = dialog.term_try_result
    input_top = dialog.term_try_input.mapTo(dialog.term_try_panel, dialog.term_try_input.rect().topLeft()).y()
    label_top = label.mapTo(dialog.term_try_panel, label.rect().topLeft()).y()
    assert label_top >= input_top + dialog.term_try_input.height()
    ancestor = label.parentWidget()
    while ancestor is not None and ancestor is not dialog:
        top = label.mapTo(ancestor, label.rect().topLeft()).y()
        assert top >= 0 and top + label.height() <= ancestor.height(), (ancestor.objectName(), label.geometry(), ancestor.geometry())
        ancestor = ancestor.parentWidget()
    quick = dialog.term_try_panel.parentWidget()
    header = quick.parentWidget()
    # 2026-10-17 redesign: the AI card left the header; the tools below it
    # (content body) must still start under the grown trial.
    below = header.parentWidget().layout().itemAt(1).widget()
    assert quick.geometry().bottom() <= header.height()
    assert below.geometry().top() >= header.geometry().bottom()


def test_duplicate_labels_have_two_actual_ids_without_phantom_row(dialog):
    first = legacy.create_learned_content('同名库', create_new=True)
    second = legacy.create_learned_content('同名库', create_new=True)
    legacy.add_learned_mapping(first, 'BerLIN', 'BerLIN')
    legacy.add_learned_mapping(second, 'S0PP', 'S0PP')
    assert dialog.add_game_item('同名库') is None
    dialog.add_game_item('同名库', library_id=first)
    selected = dialog.add_game_item('同名库', library_id=second, select=True)
    dialog.refresh_current_game()
    assert dialog.state['library_id'] == second
    assert {r['to'] for r in dialog.state['mappings']} == {'S0PP'}
    ids = [dialog.game_list.item(i).data(Qt.ItemDataRole.UserRole + 1) for i in range(dialog.game_list.count())]
    assert ids.count(first) == 1 and ids.count(second) == 1
    assert '同名库' not in ids


def test_normal_alias_tab_canonical_and_multiword_name(dialog):
    create(dialog, '本地输入测试')
    dialog.owner.show(); dialog.show(); APP.processEvents()
    dialog.owner.activateWindow(); APP.processEvents()
    dialog.term_alias_editor.setText('NoxMist')
    dialog.term_alias_editor.setFocus()
    QTest.keyClick(dialog.term_alias_editor, Qt.Key.Key_Tab)
    assert dialog.term_editor.hasFocus()
    dialog.term_editor.setText('NoX7')
    QTest.keyClick(dialog.term_editor, Qt.Key.Key_Return)
    dialog.term_editor.setText('Silent Hill')
    dialog.add_term_button.click()
    rows = legacy.learned_mappings_for_game('本地输入测试')
    assert {('NoxMist', 'NoX7'), ('Silent Hill', 'Silent Hill')} <= {(r['from'], r['to']) for r in rows}


def test_normal_ime_preedit_does_not_save_or_consume_space(dialog):
    create(dialog, '输入法测试')
    event = QInputMethodEvent('夜 星', [])
    APP.sendEvent(dialog.term_editor, event)
    assert not legacy.learned_mappings_for_game('输入法测试')
    assert dialog.term_editor.text() == ''
    commit = QInputMethodEvent()
    commit.setCommitString('夜星')
    APP.sendEvent(dialog.term_editor, commit)
    assert not legacy.learned_mappings_for_game('输入法测试')
    assert dialog.term_editor.text() == '夜星'
    dialog.add_term_button.click()
    assert legacy.learned_mappings_for_game('输入法测试')[0]['to'] == '夜星'


def test_batch_mapping_table_edits_conflicts_and_real_revision_restore(dialog):
    from twobyteasr.terminology import snapshot_glossaries
    create(dialog, '通用解析测试')
    library_id = legacy.resolve_glossary_identity('通用解析测试')
    before = snapshot_glossaries(legacy, (library_id,))
    dialog.quick_mapping_button.click()
    dialog.import_editor.setPlainText('NoxMist -> NoX7\nSkyDust\tSkY9\ncommon Alpha\ncommon Beta\nSpider-Man')
    assert [r['status'] for r in dialog._import_rows] == ['ready', 'ready', 'conflict', 'conflict', 'invalid']
    assert dialog.has_pending_edits()
    # Resolving both sides explicitly in the table is the user confirmation.
    dialog.import_table.item(4, 1).setText('spider')
    dialog.import_table.item(4, 2).setText('Spider-Man')
    assert dialog._import_rows[4]['status'] == 'ready'
    dialog.import_save_button.click()
    rows = legacy.learned_mappings_for_game(library_id)
    assert {(r['from'], r['to']) for r in rows} == {
        ('NoxMist', 'NoX7'), ('SkyDust', 'SkY9'), ('spider', 'Spider-Man')}
    after = snapshot_glossaries(legacy, (library_id,))
    assert before.digest != after.digest
    assert before.libraries[0].revision < after.libraries[0].revision
    assert not dialog.has_pending_edits()
    dialog.use_selected_game()
    assert library_id in dialog.owner._enabled_glossary_ids()
    # Reload through the real file loader and effective snapshot/resolver.
    restored = snapshot_glossaries(legacy, (library_id,))
    assert restored.digest == after.digest
    dialog.term_try_input.setText('NoxMist SkyDust spider')
    dialog.try_sentence()
    assert 'NoX7 SkY9 Spider-Man' in dialog.term_try_result.text()


def test_single_conflict_preserves_unsubmitted_draft(dialog):
    create(dialog, '冲突测试')
    legacy.add_learned_mapping('冲突测试', 'common', 'Alpha')
    dialog.term_alias_editor.setText('common')
    dialog.term_editor.setText('Beta')
    assert dialog.add_single_term() is False
    assert dialog.term_editor.text() == 'Beta' and dialog.term_alias_editor.text() == 'common'
    assert [(r['from'], r['to']) for r in legacy.learned_mappings_for_game('冲突测试')] == [('common', 'Alpha')]
    dialog.term_editor.clear(); dialog.term_alias_editor.clear()


def test_mapping_editor_accepts_tab_and_table_paste_without_global_tab_override(dialog):
    create(dialog, '表格输入')
    dialog.show_import_dialog(mapping_mode=True)
    editor = dialog.import_editor
    editor.setPlainText('NorthAsh')
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    QTest.keyClicks(editor, 'NorTH4')
    assert editor.toPlainText() == 'NorthAsh\tNorTH4'
    assert dialog._import_rows[0]['status'] == 'ready'
    mime = QMimeData()
    mime.setText('\nSouthAsh\tSouTH3\nEastAsh\tEasT2')
    editor.insertFromMimeData(mime)
    assert [(r['from'], r['to']) for r in dialog._import_rows] == [
        ('NorthAsh', 'NorTH4'), ('SouthAsh', 'SouTH3'), ('EastAsh', 'EasT2')]
    dialog.import_save_button.click()


def test_mapping_draft_cancel_guard_preserves_input_until_explicit_discard(dialog):
    create(dialog, '批量草稿')
    dialog.show_import_dialog(mapping_mode=True)
    dialog.import_editor.setPlainText('NorthAsh NorTH4')
    def choose(text):
        message = dialog.pending_draft_dialog
        next(button for button in message.buttons() if button.text() == text).click()
    QTimer.singleShot(0, lambda: choose('返回编辑'))
    assert dialog.prepare_for_task() is False
    assert dialog.has_pending_edits()
    assert not legacy.learned_mappings_for_game('批量草稿')
    QTimer.singleShot(0, lambda: choose('放弃输入并继续'))
    assert dialog.prepare_for_task() is True
    assert not dialog.has_pending_edits()
    assert not legacy.learned_mappings_for_game('批量草稿')
