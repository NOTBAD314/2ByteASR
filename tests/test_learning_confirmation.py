"""Regression coverage for the explicit learning/authority boundary."""
import copy
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import subtitle_core as legacy
from twobyteasr.glossary.glossary_learning import GlossaryLearningStore, extract_term_replacements
from twobyteasr.glossary.learning_review import AUTO_ORIGIN, storage_lock
from twobyteasr.glossary.terminology import GlossarySnapshot, TermResolver, snapshot_glossaries
from twobyteasr.glossary import translation_terms


@pytest.fixture
def libraries(tmp_path, monkeypatch):
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'formal.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    first = legacy.create_learned_content('原文甲', create_new=True)
    second = legacy.create_learned_content('原文乙', create_new=True)
    return first, second


def candidate(store, library, before='那维来特', after='那维莱特', **kwargs):
    return store.record_manual_edit(before, after, glossary_id=library,
        glossary_ids=[library], language='zh', **kwargs)[0]


def test_candidates_never_enter_snapshot_prompt_resolver_export_or_counts(tmp_path, libraries):
    first, _ = libraries
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    for before, after in [('今天天气很好', '我们去吃午饭吧'), ('这就来', '这就来！'),
                          ('那维来特', '那维莱特'), ('星见鸦', '星见雅')]:
        store.record_manual_edit(before, after, glossary_id=first, language='zh')
    assert len(store.pending()) == 2
    snapshot = snapshot_glossaries(legacy, [first])
    assert snapshot.canonical_terms == ()
    assert snapshot.review_names == ()
    assert snapshot.evidence()['aliases'] == []
    assert legacy.user_confirmed_mappings_for_game(first) == []
    assert TermResolver(snapshot).effective_term_count == 0
    ids = [row['id'] for row in store.pending()]
    assert store.accept(ids, first) == 2
    assert store.accept(ids, first) == 0
    assert len(legacy.user_confirmed_mappings_for_game(first)) == 2
    assert len(snapshot_glossaries(legacy, [first]).canonical_terms) == 2
    assert GlossaryLearningStore(store.path).pending() == []


def test_ignore_is_a_persistent_tombstone_in_its_library_and_language(tmp_path, libraries):
    first, second = libraries
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    row = candidate(store, first, token='one')
    assert store.ignore([row['id']]) == 1
    store.revert_evidence_tokens(['one'])
    candidate(store, first, token='redo')
    assert GlossaryLearningStore(store.path).pending() == []
    assert candidate(store, second)['status'] == 'pending'
    assert store.record_manual_edit('那维来特', '那维莱特', glossary_id=first, language='ja')
    assert len(store.pending()) == 2
    assert store.record_manual_edit('那维来特', '那维莱特', scope='translation', language='ja') == []


def test_false_write_and_conflict_keep_pending_and_manual_rule(tmp_path, libraries):
    first, _ = libraries
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    row = candidate(store, first)
    assert store.accept([row['id']], first, add_mapping=lambda *_a, **_kw: False) == 0
    assert store.pending()[0]['last_error']
    legacy.add_learned_mapping(first, '那维来特', '另一个名字')
    before = Path(legacy.LEARNED_TERMS_PATH).read_bytes()
    assert store.accept([row['id']], first) == 0
    assert '冲突' in store.errors[0]
    assert Path(legacy.LEARNED_TERMS_PATH).read_bytes() == before
    assert store.pending()


def test_ledger_failure_after_formal_write_is_retryable(tmp_path, libraries, monkeypatch):
    first, _ = libraries
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    row = candidate(store, first)
    save = store._save
    monkeypatch.setattr(store, '_save', lambda _payload: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        store.accept([row['id']], first)
    assert store.pending()
    assert len(legacy.user_confirmed_mappings_for_game(first)) == 1
    monkeypatch.setattr(store, '_save', save)
    assert store.accept([row['id']], first) == 1
    assert len(legacy.user_confirmed_mappings_for_game(first)) == 1


def test_legacy_auto_quarantine_preserves_manual_unknown_and_original(tmp_path, libraries):
    first, _ = libraries
    legacy.add_learned_mapping(first, '人工听成', '人工词')
    payload = legacy.load_learned_term_payload()
    automatic = dict(payload['games'][first]['mappings'][0], **{
        'from': '历史听成', 'to': '历史词', 'origin': AUTO_ORIGIN})
    automatic.pop('confirmation_action', None)
    unknown = dict(automatic, **{'from': '未知听成', 'to': '未知词', 'origin': '旧工具'})
    payload['games'][first]['mappings'].extend([automatic, unknown])
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    original = Path(legacy.LEARNED_TERMS_PATH).read_bytes()
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    store.sync_legacy(legacy)
    assert len(store.pending()) == 1
    assert store.pending()[0]['legacy_mapping'] == automatic
    assert Path(legacy.LEARNED_TERMS_PATH).read_bytes() == original
    assert {row['to'] for row in legacy.user_confirmed_mappings_for_game(first)} == {'人工词', '未知词'}
    assert '历史词' not in snapshot_glossaries(legacy, [first]).review_names
    store.sync_legacy(legacy)
    assert len(store.pending()) == 1
    legacy.review_legacy_mappings(first, [('未知听成', '未知词')])
    store.sync_legacy(legacy)
    assert len(store.pending()) == 2
    assert {row['to'] for row in legacy.user_confirmed_mappings_for_game(first)} == {'人工词'}
    assert store.accept([row['id'] for row in store.pending()], first) == 2
    assert len(legacy.user_confirmed_mappings_for_game(first)) == 3
    store.sync_legacy(legacy)
    assert store.pending() == []


def test_old_auto_accepted_candidate_does_not_count_as_user_confirmation(tmp_path, libraries):
    first, _ = libraries
    path = tmp_path / 'learning.json'
    path.write_text(json.dumps(dict(candidates=[dict(id='old', original_term='听成', corrected_term='规范词',
        status='accepted', accepted=True, auto_saved=True, accepted_glossary=first)])), 'utf8')
    store = GlossaryLearningStore(path)
    assert store.pending()[0]['accepted'] is False
    assert store.pending()[0]['previous_auto_acceptance']['status'] == 'accepted'
    assert store.accept(['old'], first) == 1
    assert GlossaryLearningStore(path).pending() == []


@pytest.mark.parametrize('before,after', [('凛', '鈴'), ('Cpp', 'C++'), ('尼奈', '妮奈')])
def test_short_names_and_symbol_names_are_collectable(before, after):
    assert extract_term_replacements(before, after) == [(before, after)]


@pytest.mark.parametrize('before,after', [('今天很好', '今天真好'), ('他老是迟到', '他老师迟到'),
    ('你好，世界', '你好！世界'), ('hello world', 'hello  world'), ('所以他走了', '所以她走了'),
    ('我想我们今天先走了', '今天就先到这里吧')])
def test_layout_grammar_and_rewrites_are_skipped(before, after):
    assert extract_term_replacements(before, after) == []


def test_pending_translation_rows_do_not_enter_index_or_frozen_cache():
    policy = dict(enabled=True, selected_ids=['t'], libraries=[dict(id='t', source_language='en',
        target_language='zh', terms=[dict(source='Alice', target='爱丽丝', status='pending'),
            dict(source='Bob', target='鲍勃', confirmed=False), dict(source='Eve', target='伊芙')])])
    frozen = translation_terms.freeze(policy)
    assert [row['source'] for row in translation_terms.relevant(frozen, 'en', 'zh', 'Alice Bob Eve')] == ['Eve']
    assert translation_terms.relevant(frozen, 'zh', 'en', '伊芙') == []


def test_explicit_alias_confirmation_inherits_existing_disabled_canonical(tmp_path, libraries):
    first, _ = libraries
    legacy.add_learned_mapping(first, '那维莱特', '那维莱特')
    legacy.edit_learned_mapping(first, ('那维莱特', '那维莱特'), '那维莱特', '那维莱特', correction_enabled=False)
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    row = candidate(store, first)
    assert store.accept([row['id']], first) == 1
    assert snapshot_glossaries(legacy, [first]).canonical_terms == ()


def test_target_edit_is_candidate_only_and_cannot_be_accepted_into_another_library(tmp_path, libraries):
    first, second = libraries
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    row = candidate(store, first)
    store.edit_candidate(row['id'], '那维来特', '那维莱特', second)
    assert legacy.user_confirmed_mappings_for_game(second) == []
    assert store.accept([row['id']], first) == 0
    assert store.accept([row['id']], second) == 1
    assert legacy.user_confirmed_mappings_for_game(first) == []


def test_busy_formal_storage_keeps_candidate_for_retry(tmp_path, libraries):
    from PySide6.QtCore import QLockFile
    first, _ = libraries
    store = GlossaryLearningStore(tmp_path / 'learning.json')
    row = candidate(store, first)
    lock = QLockFile(legacy.LEARNED_TERMS_PATH + '.lock')
    assert lock.tryLock(0)
    try:
        assert store.accept([row['id']], first) == 0
        assert store.pending()
        assert legacy.user_confirmed_mappings_for_game(first) == []
    finally:
        lock.unlock()
    assert store.accept([row['id']], first) == 1


def test_legacy_hints_replacements_adjudication_and_studio_qc_require_confirmation(libraries, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.recognition.transcript_data import SpeechSegment
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    from twobyteasr.subtitle_rules.studio_qc import terminology_from_project
    first, _ = libraries
    legacy.add_learned_mapping(first, '原听成', '正式词')
    legacy.add_learned_mapping(first, '旧听成', '已停用词')
    legacy.edit_learned_mapping(first, ('旧听成', '已停用词'), '旧听成', '已停用词', correction_enabled=False)
    payload = legacy.load_learned_term_payload()
    payload['games'][first]['mappings'].extend([
        dict(**{'from': '自动听成', 'to': '自动词'}, confirmed=True, provenance='user_confirmed', origin=AUTO_ORIGIN),
        dict(**{'from': '候选听成', 'to': '候选词'}, confirmed=False, provenance='candidate')])
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, payload)
    assert legacy.learned_canonical_terms(first) == ['正式词']
    rows = legacy.prepared_learned_mappings([SpeechSegment(1, 0, 1, '原听成 自动听成 候选听成 旧听成', .8, [])], first)
    assert [(row['from'], row['to']) for row in rows] == [('原听成', '正式词')]
    monkeypatch.setattr(legacy, 'get_runtime_context', lambda: SimpleNamespace(glossary_snapshot=None))
    monkeypatch.setattr(legacy, 'runtime_enabled_glossary_ids', lambda: [first])
    evidence = legacy.enabled_glossary_adjudication_evidence()
    assert evidence['canonical_terms'] == ['正式词']
    project = SubtitleProject(StudioMedia(''), glossary_ids=[first])
    assert [row.canonical for row in terminology_from_project(project)] == ['正式词']


def test_legacy_confirmed_hint_preserves_short_and_symbol_names(libraries):
    first, _ = libraries
    legacy.add_learned_mapping(first, 'Cpp', 'C++')
    legacy.add_learned_mapping(first, '凛', '鈴')
    assert set(legacy.learned_canonical_terms(first)) == {'C++', '鈴'}


@pytest.mark.parametrize('before,after,pair', [('使用Cpp开发', '使用C++开发', ('Cpp', 'C++')),
    ('学习C+', '学习C++', ('C+', 'C++')), ('今天Hello world', '今天Hello  world', None),
    ('He is ready', 'She is ready', None)])
def test_symbol_name_extraction_keeps_token_boundaries(before, after, pair):
    assert extract_term_replacements(before, after) == ([pair] if pair else [])


def test_ui_check_all_edit_close_and_ignore_are_separate_from_commit(tmp_path, libraries):
    from tests.test_glossary_manual_case_ui import Owner
    from twobyteasr.glossary.main_ui_glossary import TermLibraryDialog
    app = QApplication.instance() or QApplication([])
    first, _ = libraries
    owner = Owner()
    page = TermLibraryDialog(owner, page_mode=True)
    panel = page.learning_panel
    panel.store = GlossaryLearningStore(tmp_path / 'learning.json')
    page._learning_store = panel.store
    for before, after in [('那维来特', '那维莱特'), ('星见鸦', '星见雅')]:
        candidate(panel.store, first, before, after)
    try:
        panel.refresh()
        assert panel.checked_ids() == []
        panel.listing.setCurrentRow(0)
        panel.edit_current()
        panel.editor.close()
        panel._select_all()
        panel.refresh()
        assert len(panel.checked_ids()) == 2
        assert legacy.user_confirmed_mappings_for_game(first) == []
        panel.commit(panel.checked_ids())
        assert len(legacy.user_confirmed_mappings_for_game(first)) == 2
        assert panel.listing.count() == 0
    finally:
        if page._task_manager:
            page._task_manager.shutdown(wait_ms=300)
        page.close()
        owner.close()
        app.processEvents()
