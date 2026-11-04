"""Canonical spellings and library identity use the real isolated store."""
import json

import pytest
import subtitle_core as legacy


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})


def test_canonical_case_and_zero_survive_store_and_import():
    legacy.add_learned_mapping('瓦罗兰特', 'BerLIN', 'BerLIN')
    legacy.add_learned_mapping('瓦罗兰特', 'Borlin', 'BerLIN')
    legacy.add_learned_mapping('瓦罗兰特', 'S0PP', 'S0PP')
    rows = legacy.learned_mappings_for_game('瓦罗兰特')
    assert {(r['from'], r['to']) for r in rows} == {
        ('BerLIN', 'BerLIN'), ('Borlin', 'BerLIN'), ('S0PP', 'S0PP')}
    # Imported/AI normalization cannot replace an explicitly confirmed spelling.
    legacy.persist_learned_mappings('瓦罗兰特', [
        {'from': 'berlin', 'to': 'berlin', 'confirmed': True, 'verification': 'web_official'},
        {'from': 'Borlin', 'to': 'Berlin', 'confirmed': True, 'verification': 'web_official'}])
    rows = legacy.learned_mappings_for_game('瓦罗兰特')
    assert {r['to'] for r in rows} == {'BerLIN', 'S0PP'}


def test_case_only_edit_is_atomic_and_preserves_evidence():
    legacy.add_learned_mapping('瓦罗兰特', 'berlin', 'berlin', category='选手 ID')
    legacy.add_learned_mapping('瓦罗兰特', 'Borlin', 'berlin')
    assert legacy.edit_learned_mapping('瓦罗兰特', ('berlin', 'berlin'),
                                       'BerLIN', 'BerLIN', category='选手 ID')
    rows = legacy.learned_mappings_for_game('瓦罗兰特')
    assert {(r['from'], r['to']) for r in rows} == {
        ('BerLIN', 'BerLIN'), ('Borlin', 'BerLIN')}
    assert all(r['verification'] == 'user_manual' for r in rows)
    assert json.loads(open(legacy.LEARNED_TERMS_PATH, encoding='utf8').read())['games']


def test_stable_identity_survives_rename_and_duplicate_display_names():
    assert legacy.ensure_learned_content('瓦罗兰特')
    library_id = legacy.resolve_glossary_identity('瓦罗兰特')
    legacy.add_learned_mapping(library_id, 'BerLIN', 'BerLIN')
    assert legacy.rename_learned_content(library_id, 'VALORANT')
    assert legacy.resolve_glossary_identity('VALORANT') == library_id
    assert legacy.glossary_display_name(library_id) == 'VALORANT'
    assert legacy.learned_mappings_for_game(library_id)[0]['to'] == 'BerLIN'
    duplicate_id = legacy.create_learned_content('VALORANT', create_new=True)
    assert duplicate_id and duplicate_id != library_id
    assert legacy.resolve_glossary_identity('VALORANT') == ''
    assert legacy.resolve_glossary_identity(library_id) == library_id


def test_confirmed_alias_conflict_is_explicit():
    legacy.add_learned_mapping('测试', '共同别名', '甲')
    with pytest.raises(ValueError, match='冲突'):
        legacy.add_learned_mapping('测试', '共同别名', '乙')
    assert legacy.learned_mappings_for_game('测试')[0]['to'] == '甲'


def test_legacy_display_change_never_guesses_historical_case(tmp_path):
    path = tmp_path / 'terms.json'
    original = {'schema': 2, 'games': {'旧库': {'game': '旧库', 'mappings': [
        {'from': 'berlin', 'to': 'berlin', 'confirmed': True, 'verification': 'user_manual'}]}}}
    path.write_text(json.dumps(original, ensure_ascii=False), encoding='utf8')
    assert legacy.rename_learned_content('旧库', '新库')
    assert legacy.learned_mappings_for_game('新库')[0]['to'] == 'berlin'
    assert legacy.resolve_glossary_identity('新库') == '旧库'


def test_background_glossary_task_freezes_target_evidence_before_rename(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.glossary.glossary_task_manager import GlossaryUpdateManager, GlossaryTaskRunner
    app = QApplication.instance() or QApplication([])
    legacy.add_learned_mapping('任务库', 'Borlin', 'BerLIN')
    library_id = legacy.resolve_glossary_identity('任务库')
    manager = GlossaryUpdateManager(legacy)
    monkeypatch.setattr(manager, '_pump', lambda: None)
    settings = {'models': {'polish_model': 'original-model'}}
    task_id, _ = manager.submit('任务库', 'full', settings)
    task = manager.get(task_id)
    legacy.rename_learned_content(library_id, '新名称')
    legacy.edit_learned_mapping(library_id, ('Borlin', 'BerLIN'), 'Borlin', 'OtherID')
    settings['models']['polish_model'] = 'draft-model'
    runner = GlossaryTaskRunner(legacy, task, manager._settings_by_task[task_id])
    assert runner.settings['models']['polish_model'] == 'original-model'
    assert task.library_id == library_id
    assert runner.legacy.learned_canonical_terms() == ['BerLIN']
    assert runner.legacy.user_confirmed_mappings_for_game('任务库')[0]['to'] == 'BerLIN'


def test_ambiguous_display_name_cannot_create_or_update_another_library():
    first = legacy.create_learned_content('同名', create_new=True)
    second = legacy.create_learned_content('同名', create_new=True)
    with pytest.raises(ValueError, match='同名'):
        legacy.add_learned_mapping('同名', 'BerLIN', 'BerLIN')
    assert len(legacy.glossary_catalog()) == 2
    legacy.add_learned_mapping(first, 'BerLIN', 'BerLIN')
    assert legacy.learned_mappings_for_game(second) == []
