import copy
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from PySide6.QtGui import QUndoStack

from twobyteasr.glossary.translation_terms import normalize, relevant, KEY
from twobyteasr.glossary.translation_terms_import import parse_libraries, merge_library
from twobyteasr.glossary.translation_terms_ui import TranslationTermsDialog, TerminologySettingsCommand
from twobyteasr.projects.studio_project import save_project, load_project
from tests.test_subtitle_edit_integrity import project

APP = QApplication.instance() or QApplication([])


def policy():
    return normalize(dict(enabled=True, selected_ids=['a', 'b'], libraries=[
        dict(id='a', name='鸣潮', source_language='ja', target_language='zh-Hans', terms=[
            dict(source='アリス', target='爱丽丝', aliases=[], context='人物')]),
        dict(id='b', name='废案', source_language='ja', target_language='zh-Hans', terms=[
            dict(source='石', target='石头', aliases=[], context='')])]))


def tsv(text):
    return parse_libraries(text, is_json=False, name='extra', source_language='ja', target_language='zh-Hans')


def test_append_uses_highlighted_not_all_checked_and_deduplicates(tmp_path):
    value = policy(); before = copy.deepcopy(value)
    dialog = TranslationTermsDialog(value)
    try:
        dialog.list.setCurrentRow(0)
        stats = dialog.apply_import(tsv('新語\t新译名\n新語\t新译名'), mode='append')
        assert stats == dict(added=1, duplicates=1, conflicts=0, replaced=0)
        assert len(dialog.value()['libraries']) == 2
        assert dialog.value()['libraries'][0]['id'] == 'a'
        assert dialog.value()['libraries'][1] == before['libraries'][1]
        assert dialog.apply_import(tsv('新語\t新译名'), mode='append')['duplicates'] == 1
        assert len(dialog.value()['libraries'][0]['terms']) == 2
        # A cancelled draft cannot mutate caller-owned settings.
        dialog.reject(); assert value == before
        p = project(); stack = QUndoStack()
        stack.push(TerminologySettingsCommand(p, policy=dialog.value()))
        save_project(p, tmp_path/'terms.2byteproj')
        reopened = load_project(tmp_path/'terms.2byteproj')
        assert len(reopened.generation_metadata[KEY]['libraries'][0]['terms']) == 2
        stack.undo(); assert KEY not in p.generation_metadata
        stack.redo(); assert p.generation_metadata[KEY]['libraries'][0]['id'] == 'a'
    finally: dialog.close()


def test_conflicts_default_keep_explicit_adopt_or_keep_both():
    existing = policy()['libraries'][0]
    incoming = tsv('アリス\t艾丽丝')[0]
    unchanged, stats, conflicts = merge_library(existing, incoming)
    assert unchanged == existing and stats['conflicts'] == 1 and conflicts
    adopted, stats, _ = merge_library(existing, incoming, {'アリス': 'imported'})
    assert adopted['terms'][0]['target'] == '艾丽丝' and stats['replaced'] == 1
    both, stats, _ = merge_library(existing, incoming, {'アリス': 'both'})
    assert len(both['terms']) == 2 and stats['added'] == 1
    assert merge_library(both, incoming)[1]['duplicates'] == 1
    assert existing == policy()['libraries'][0]


def test_different_contexts_are_not_silently_collapsed():
    existing = policy()['libraries'][0]
    incoming = copy.deepcopy(existing)
    incoming['terms'][0]['context'] = '地名'
    merged, stats, _ = merge_library(existing, incoming, {'アリス': 'both'})
    assert stats['conflicts'] == 1 and len(merged['terms']) == 2


@pytest.mark.parametrize('bad', ['first\t译名\nbroken', 'a\tb\tc', '\t无源文'])
def test_malformed_tsv_is_atomic(bad):
    with pytest.raises(ValueError): tsv(bad)


def test_multi_library_json_is_fully_validated_and_directions_never_mix():
    libs = policy()['libraries']
    valid = json.dumps(dict(libraries=libs), ensure_ascii=False)
    assert len(parse_libraries(valid, is_json=True, name='x', source_language='', target_language='')) == 2
    broken = copy.deepcopy(libs); broken[1]['terms'].append(dict(source='bad'))
    with pytest.raises(ValueError):
        parse_libraries(json.dumps(dict(libraries=broken)), is_json=True, name='x', source_language='', target_language='')
    other = copy.deepcopy(libs[1]); other['source_language'] = 'en'
    with pytest.raises(ValueError, match='方向不一致'): merge_library(libs[0], other)
    dialog = TranslationTermsDialog(policy())
    before = dialog.value()
    with pytest.raises(ValueError): dialog.apply_import(libs, mode='append')
    assert dialog.value() == before
    with pytest.raises(ValueError): dialog.apply_import([other], mode='append')
    assert dialog.value() == before
    dialog.close()


def test_delete_current_library_cancel_and_empty_state(monkeypatch):
    value = policy(); dialog = TranslationTermsDialog(value)
    prompts = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: (prompts.append(a[2]) or QMessageBox.Yes))
    try:
        dialog.list.setCurrentRow(1)
        dialog.delete_library()
        assert '废案' in prompts[0] and '1' in prompts[0]
        assert [lib['id'] for lib in dialog.value()['libraries']] == ['a']
        assert dialog.value()['selected_ids'] == ['a']
        assert len(value['libraries']) == 2
        p = project(); p.generation_metadata[KEY] = policy()
        assert relevant(p.generation_metadata[KEY], 'ja', 'zh-Hans', '石')
        stack = QUndoStack(); stack.push(TerminologySettingsCommand(p, policy=dialog.value()))
        assert not relevant(p.generation_metadata[KEY], 'ja', 'zh-Hans', '石')
        stack.undo(); assert relevant(p.generation_metadata[KEY], 'ja', 'zh-Hans', '石')
        dialog.delete_library()
        assert dialog.list.count() == dialog.table.rowCount() == 0
        assert not dialog.delete_button.isEnabled() and not dialog.add_term_button.isEnabled()
        assert dialog.value()['libraries'] == []
        dialog.add_library(); assert dialog.add_term_button.isEnabled()
        dialog.add_term_button.click()
        dialog.table.setItem(0, 0, QTableWidgetItem('追加'))
        dialog.table.setItem(0, 1, QTableWidgetItem('新增'))
        assert dialog.value()['libraries'][0]['terms'][0]['target'] == '新增'
        dialog.reject(); assert value == policy()
    finally: dialog.close()
