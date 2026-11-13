import copy
import json
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.design.widget_teardown import delete_tree_before_collection

APP = QApplication.instance() or QApplication([])


class FixtureWidget(QWidget):
    __del__ = delete_tree_before_collection

from twobyteasr.glossary import multilingual_terms as m
from twobyteasr.glossary import translation_terms as t


@pytest.fixture
def store(tmp_path, monkeypatch):
    import subtitle_core as legacy
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms.json'))
    legacy.atomic_write_json(legacy.LEARNED_TERMS_PATH, {'schema': 2, 'games': {'test': {
        'game': '测试库', 'library_id': 'test', 'mappings': [
            {'from': '艾丽呀', 'to': '艾莉娅', 'category': '角色', 'confirmed': True,
             'provenance': 'user_confirmed', 'reason': 'original evidence'}]}}})
    return legacy


def multilingual():
    c = m.concept('艾莉娅', 'zh-Hans', category='角色')
    c['names']['zh-Hans']['mishearings'] = ['艾丽呀']
    c['names']['en'] = m.name_record('Aria', mistranslations=['Alyria'])
    c['names']['ja'] = m.name_record('アリア')
    c['names']['zh-Hant'] = m.name_record('艾莉亞')
    return c


def policy(store):
    return m.hydrate_policy(dict(enabled=True, concept_library_ids=['test']), store)


def test_legacy_read_is_idempotent_unspecified_and_first_write_backed_up(store):
    first = m.read_concepts(store, 'test')
    assert first == m.read_concepts(store, 'test')
    assert list(first[0]['names']) == ['und']
    assert first[0]['names']['und']['mishearings'] == ['艾丽呀']
    original = store.load_learned_term_payload()
    m.save_concept(store, 'test', first[0])
    assert json.loads(__import__('pathlib').Path(store.LEARNED_TERMS_PATH + '.pre-multilingual.bak').read_text('utf8')) == original
    assert store.load_learned_term_payload()['games']['test']['mappings'] == original['games']['test']['mappings']


def test_save_restart_and_remove_one_language(store):
    c = m.save_concept(store, 'test', multilingual())
    assert next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id']) == c
    before = copy.deepcopy(c)
    del c['names']['en']
    m.save_concept(store, 'test', c, expected=before)
    assert set(next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])['names']) == {'ja', 'zh-Hans', 'zh-Hant'}
    c['names'] = {}
    with pytest.raises(ValueError): m.save_concept(store, 'test', c)


@pytest.mark.parametrize('language,name', [('ja', 'アリア'), ('en', 'Aria')])
def test_independent_foreign_has_no_fabricated_pair(store, language, name):
    c = m.save_concept(store, 'test', m.concept(name, language))
    assert not t.relevant(policy(store), 'zh', language, '艾莉娅来了')
    assert m.read_concepts(store, 'test')[-1]['id'] == c['id']


def test_link_conflict_and_two_directions(store):
    a = m.save_concept(store, 'test', m.concept('艾莉娅', 'zh-Hans'))
    b = m.save_concept(store, 'test', m.concept('Aria', 'en'))
    m.link_concepts(store, 'test', a['id'], b['id'])
    assert t.relevant(policy(store), 'zh', 'en', '艾莉娅小姐来了')[0]['target'] == 'Aria'
    assert t.relevant(policy(store), 'en', 'zh-Hans', 'Miss Aria arrived')[0]['target'] == '艾莉娅'
    assert not t.relevant(policy(store), 'en', 'zh-Hans', 'Arian arrived')
    d = m.save_concept(store, 'test', m.concept('Aria Prime', 'en'))
    with pytest.raises(ValueError): m.link_concepts(store, 'test', a['id'], d['id'])
    merged = m.link_concepts(store, 'test', a['id'], d['id'], {'en': 'current'})
    assert 'Aria Prime' in merged['names']['en']['aliases']


def test_confirmation_is_per_language_and_hans_hant_exact(store):
    c = multilingual(); c['names']['en'] = m.name_record('Aria', confirmed=False)
    m.save_concept(store, 'test', c)
    assert not t.relevant(policy(store), 'zh', 'en', '艾莉娅')
    assert t.relevant(policy(store), 'en', 'zh-Hans', 'Aria') == []
    assert t.relevant(policy(store), 'zh', 'zh-Hant', '艾莉娅')[0]['target'] == '艾莉亞'


def test_source_mishearings_and_target_errors_are_separate(store):
    from twobyteasr.glossary.terminology import snapshot_glossaries, TermResolver
    c = m.save_concept(store, 'test', multilingual())
    snap = snapshot_glossaries(store, ['test'])
    assert TermResolver(m.source_snapshot(snap, 'en')).resolve('Alyria 艾丽呀').text == 'Alyria 艾丽呀'
    assert TermResolver(m.source_snapshot(snap, 'zh')).resolve('艾丽呀').text == '艾莉娅'
    assert m.target_rules(policy(store), 'en', 'Miss Alyria arrived', '艾莉娅小姐来了', 'zh')[0]['target'] == 'Aria'
    assert not m.target_rules(policy(store), 'en', 'Alyrian arrived', '艾莉娅来了', 'zh')


def test_frozen_task_and_new_tasks_read_latest(store):
    c = m.save_concept(store, 'test', multilingual())
    frozen = t.freeze(policy(store))
    c['names']['en']['name'] = 'Aria New'
    m.save_concept(store, 'test', c)
    assert t.relevant(frozen, 'zh', 'en', '艾莉娅')[0]['target'] == 'Aria'
    assert t.relevant(policy(store), 'zh', 'en', '艾莉娅')[0]['target'] == 'Aria New'
    assert t.rule_version(frozen, (), 'zh', 'en', '艾莉娅') != t.rule_version(policy(store), (), 'zh', 'en', '艾莉娅')


def test_longest_match_and_missing_name_is_not_satisfied_by_miss(store):
    p = {'enabled': True, 'selected_ids': ['a'], 'libraries': [dict(id='a', source_language='zh', target_language='en', terms=[
        dict(source='光合', target='Light'), dict(source='光合治愈', target='Photosynthesis')])]}
    assert [r['source'] for r in t.relevant(p, 'zh', 'en', '光合治愈')] == ['光合治愈']
    rows = [dict(source='艾莉娅', target='Aria', source_language='zh', target_language='en', aliases=[], target_aliases=[])]
    assert t.validation_issues('艾莉娅小姐来了', 'Miss has arrived', rows)
    assert not t.validation_issues('艾莉娅小姐来了', 'Here comes Miss Aria', rows)


def test_multi_library_conflict_and_visible_priority(store):
    m.save_concept(store, 'test', multilingual())
    second = multilingual(); second['names']['en']['name'] = 'Different Aria'
    m.save_concept(store, 'other', second)
    p = m.hydrate_policy({'enabled': True, 'concept_library_ids': ['test', 'other']}, store)
    rows = t.relevant(p, 'zh', 'en', '艾莉娅')
    assert len(rows) == 2 and all(r['conflict'] for r in rows)
    assert not t.validation_issues('艾莉娅来了', 'She arrived', rows)
    p['preferred_libraries'] = {'艾莉娅': 'concept-library:test'}
    assert [r['target'] for r in t.relevant(p, 'zh', 'en', '艾莉娅')] == ['Aria']


def test_full_export_import_and_duplicate_identity(store):
    c = m.save_concept(store, 'test', multilingual())
    exported = json.dumps(m.export_library(store, 'test'), ensure_ascii=False)
    incoming = m.parse_import(exported)
    m.import_concepts(store, 'destination', incoming)
    m.import_concepts(store, 'destination', incoming)
    restored = m.read_concepts(store, 'destination')
    assert len(restored) == len(incoming)
    assert next(r for r in restored if r['id'] == c['id'])['names'] == c['names']
    incoming[-1]['names']['en']['name'] = 'DO NOT OVERWRITE'
    stats, conflicts = m.import_concepts(store, 'destination', incoming)
    assert stats['conflicts'] and conflicts
    assert next(r for r in m.read_concepts(store, 'destination') if r['id'] == c['id'])['names']['en']['name'] == 'Aria'


def test_csv_mapping_and_repeat_import(store):
    text = '角色,日语,英文\n艾莉娅,アリア,Aria'
    rows = m.parse_import(text, {'角色': 'zh-Hans', '日语': 'ja', '英文': 'en'})
    m.import_concepts(store, 'csv', rows); m.import_concepts(store, 'csv', m.parse_import(text, {'角色': 'zh-Hans', '日语': 'ja', '英文': 'en'}))
    assert len(m.read_concepts(store, 'csv')) == 1


def test_ai_candidates_cancel_resume_and_confirmation(store):
    from twobyteasr.glossary.translation_name_candidates import complete_names, review_candidates
    from twobyteasr.recognition.service import CancellationToken
    c = m.save_concept(store, 'test', m.concept('艾莉娅', 'zh-Hans'))
    token = CancellationToken()
    def complete(*a, **k):
        return json.dumps({'name': 'Aria', 'sources': ['test fixture']})
    result = complete_names(store, 'test', [c['id']], ['en'], SimpleNamespace(complete=complete), token=token)
    assert result['done'] == 1
    candidate = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])['candidates']['en'][0]
    assert not t.relevant(policy(store), 'zh', 'en', '艾莉娅')
    assert complete_names(store, 'test', [c['id']], ['en'], SimpleNamespace(complete=complete), token=token)['total'] == 0
    review_candidates(store, 'test', [(c['id'], 'en', candidate['id'])], accept=True)
    assert t.relevant(policy(store), 'zh', 'en', '艾莉娅')[0]['target'] == 'Aria'


def project_for_test():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    project = SubtitleProject(media=StudioMedia(path='fixture.mp4', duration_ms=5000),
        cues=[StudioCue('cue-identity', 200, 1500, '艾莉娅小姐来了', speaker_id='S01')],
        glossary_ids=['test'], generation_metadata={'language': {'code': 'zh'},
            'translation_terminology': {'enabled': True, 'concept_library_ids': ['test']}})
    project.validate()
    return project


def test_production_translation_retranslation_and_runtime_entry(store, tmp_path, monkeypatch):
    from twobyteasr.subtitle_rules import subtitle_translation as st
    from twobyteasr.subtitle_rules import recognition_translation as rt
    c = m.save_concept(store, 'test', multilingual())
    p = project_for_test(); captured = []
    class Provider:
        provider_id = 'fixture-provider'
        model = 'fixture-model'
        def structured_complete(self, messages, schema, **kwargs):
            payload = json.loads(messages[-1]['content']); captured.append(payload)
            required = payload.get('translation_terminology', [])
            assert required and all(r['source'] != '艾丽呀' for r in required)
            name = required[0]['target']
            return {'items': [{'id': line['id'], 'translation': f'Miss {name} has arrived.'}
                              for line in payload['lines'] if line['translate']]}
    frozen = st.translation_source(p)
    first = st.translate(frozen, None, Provider(), target='en', cache={})
    assert not first.failed and first.translations['cue-identity'].text == 'Miss Aria has arrived.'
    st.apply_translation_result(p, first)
    old_translation = copy.deepcopy(p.generation_metadata['translations'])
    c['names']['en']['name'] = 'Aria Nova'; m.save_concept(store, 'test', c)
    assert p.generation_metadata['translations'] == old_translation
    old_job = st.translate(frozen, None, Provider(), target='en', cache={})
    assert 'Aria Nova' not in old_job.translations['cue-identity'].text
    new_job = st.translate(p, None, Provider(), target='en', cache={})
    assert new_job.translations['cue-identity'].text == 'Miss Aria Nova has arrived.'
    assert p.cues[0].text == '艾莉娅小姐来了' and (p.cues[0].start_ms, p.cues[0].end_ms) == (200, 1500)
    monkeypatch.setattr(rt, 'cache_path', lambda: tmp_path / 'runtime-cache.json')
    context = SimpleNamespace(subtitle_output='bilingual', task_language='zh', translation_script='en',
        cancellation_token=None, translation_terminology=policy(store))
    cues = [SimpleNamespace(cue_id='cue-identity', start=.2, end=1.5, text='艾莉娅小姐来了', speaker='S01')]
    output = rt.translate_runtime_cues(cues, context, SimpleNamespace(record_run_event=lambda *a, **k: None,
        add_review_item=lambda *a, **k: None), provider=Provider())
    assert output['translation_records']['records']['cue-identity']['text'] == 'Miss Aria Nova has arrived.'


def test_production_translation_review_apply_and_undo(store):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    from twobyteasr.subtitle_rules import subtitle_translation as st
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    from twobyteasr.glossary.terminology import snapshot_glossaries
    from twobyteasr.studio.subtitle_text_targets import text_entries, review_project
    from twobyteasr.studio.studio_find_replace import apply_occurrences
    app = QApplication.instance() or QApplication([])
    m.save_concept(store, 'test', multilingual()); p = project_for_test()
    p.generation_metadata['translation_records'] = st._empty_container('en')
    st.set_manual(p, 'cue-identity', 'Miss Alyria has arrived.', target='en')
    entries = text_entries(p, mode='translation'); view = review_project(p, entries)
    result = preview_glossary_correction(view, [e.key for e in entries], snapshot_glossaries(store, ['test']), {}, use_ai=False)
    assert result.hits and result.hits[0].replacement == 'Aria'
    page = SimpleNamespace(session=SimpleNamespace(project=p, undo_stack=QUndoStack()), _changed=lambda: None)
    assert apply_occurrences(page, result.hits, title='使用当前词库重新校对译文')[0] == 1
    assert text_entries(p, mode='translation')[0].text == 'Miss Aria has arrived.'
    page.session.undo_stack.undo()
    assert text_entries(p, mode='translation')[0].text == 'Miss Alyria has arrived.'
    assert p.cues[0].text == '艾莉娅小姐来了'


def test_standalone_target_rule_requires_positive_context(store):
    c = m.concept('Aria', 'en', description='royal court')
    c['names']['en']['mistranslations'] = ['Alyria']
    m.save_concept(store, 'test', c)
    assert not m.target_rules(policy(store), 'en', 'Alyria arrived')
    assert not m.target_rules(policy(store), 'en', 'Alyria in the royal courtroom')
    assert m.target_rules(policy(store), 'en', 'Alyria at the royal court')[0]['target'] == 'Aria'


def test_same_name_does_not_merge_and_cross_library_copy_retains_scope(store):
    a = m.save_concept(store, 'test', m.concept('相同名字', 'zh-Hans', category='角色'))
    b = m.save_concept(store, 'test', m.concept('相同名字', 'zh-Hans', category='地点'))
    assert a['id'] != b['id']
    foreign = m.save_concept(store, 'external', m.concept('Foreign Name', 'en'))
    before = copy.deepcopy(m.read_concepts(store, 'external'))
    result = m.link_concepts(store, 'test', a['id'], foreign['id'], source_library='external')
    assert result['id'] == a['id'] and result['names']['en']['name'] == 'Foreign Name'
    assert m.read_concepts(store, 'external') == before
    assert len([c for c in m.read_concepts(store, 'test') if c['names'].get('zh-Hans', {}).get('name') == '相同名字']) == 2


def test_traditional_source_uses_explicit_locale_and_preserves_written_names(store):
    from twobyteasr.subtitle_rules import subtitle_translation as st
    m.save_concept(store, 'test', multilingual())
    p = project_for_test(); p.cues[0].text = '艾莉亞小姐來了'
    p.generation_metadata['language']['script'] = 'zh-Hant'
    source = st.translation_source(p)
    assert t.relevant(source.terminology, 'zh', 'en', p.cues[0].text)[0]['target'] == 'Aria'
    assert not t.relevant(source.terminology, 'zh', 'en', '艾莉娅小姐来了')


def test_run_options_are_replayed_with_same_name_snapshot(store):
    from twobyteasr.recognition.service import RunOptions
    c = m.save_concept(store, 'test', multilingual())
    options = RunOptions(translation_terminology_json=json.dumps(m.task_policy({'enabled': True, 'concept_library_ids': ['test']}, store)))
    first = options.create_runtime_context(store)
    c['names']['en']['name'] = 'Changed'; m.save_concept(store, 'test', c)
    second = options.create_runtime_context(store)
    assert first.translation_terminology == second.translation_terminology
    assert t.relevant(second.translation_terminology, 'zh', 'en', '艾莉娅')[0]['target'] == 'Aria'


def test_background_candidate_arrival_does_not_block_manual_edit(store):
    from twobyteasr.glossary.translation_name_candidates import complete_names, review_candidates
    from twobyteasr.recognition.service import CancellationToken
    c = m.save_concept(store, 'test', m.concept('艾莉娅', 'zh-Hans'))
    original = copy.deepcopy(c)
    complete_names(store, 'test', [c['id']], ['en'], SimpleNamespace(complete=lambda *a, **kw: {'name': 'Aria'}), token=CancellationToken())
    c['description'] = '手动修改说明'
    saved = m.save_concept(store, 'test', c, expected=original)
    candidate = saved['candidates']['en'][0]
    review_candidates(store, 'test', [(c['id'], 'en', candidate['id'])], accept=False)
    final = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])
    assert final['description'] == '手动修改说明' and m.is_confirmed(final['names']['zh-Hans'])
    assert 'en' not in final['names'] and not final['candidates']


def test_ai_failure_retry_only_unfinished_names(store):
    from twobyteasr.glossary.translation_name_candidates import complete_names
    from twobyteasr.recognition.service import CancellationToken
    first = m.save_concept(store, 'test', m.concept('甲', 'zh-Hans'))
    second = m.save_concept(store, 'test', m.concept('乙', 'zh-Hans'))
    calls = []
    def provider(messages, **kwargs):
        identity = json.loads(messages[-1]['content'])['concept_id']; calls.append(identity)
        if identity == first['id'] and calls.count(identity) == 1: raise RuntimeError('fixture transient failure')
        return {'name': 'Candidate'}
    args = (store, 'test', [first['id'], second['id']], ['en'], SimpleNamespace(complete=provider))
    stats = complete_names(*args, token=CancellationToken())
    assert (stats['done'], stats['total'], stats['failed']) == (1, 2, 1)
    retry = complete_names(*args, token=CancellationToken())
    assert (retry['done'], retry['total'], retry['failed']) == (1, 1, 0)
    assert calls.count(second['id']) == 1


def test_saved_names_survive_a_new_python_process(store):
    import subprocess, sys
    c = m.save_concept(store, 'test', multilingual())
    code = 'import json,sys; import subtitle_core as s; from twobyteasr.glossary.multilingual_terms import read_concepts; s.LEARNED_TERMS_PATH=sys.argv[1]; print(json.dumps(read_concepts(s,"test"),ensure_ascii=False))'
    raw = subprocess.check_output([sys.executable, '-X', 'utf8', '-c', code, store.LEARNED_TERMS_PATH], text=True, encoding='utf8')
    restored = next(row for row in json.loads(raw) if row['id'] == c['id'])
    assert restored['names'] == c['names']


def test_foreign_asr_pass_used_by_local_and_streaming_routes(store):
    from twobyteasr.recognition.service import RunOptions
    from twobyteasr.recognition.run_context import activate_runtime_context
    from twobyteasr.glossary.terminology import snapshot_glossaries
    from twobyteasr.recognition.transcript_data import SpeechSegment
    c = m.concept('Aria', 'en'); c['names']['en']['mishearings'] = ['Areya']
    c['names']['en']['mistranslations'] = ['Alyria']; m.save_concept(store, 'test', c)
    options = RunOptions(enable_domain_terms=True, enabled_glossary_ids=('test',), recognition_language='en',
        glossary_snapshot_json=json.dumps(snapshot_glossaries(store, ['test']).to_dict()))
    context = options.create_runtime_context(store)
    segment = SpeechSegment(1, .1, 1.8, 'Areya and Arian met Alyria 艾丽呀', .9, [])
    with activate_runtime_context(context):
        m.apply_source_terms([segment], store)
    assert segment.text == 'Aria and Arian met Alyria 艾丽呀'
    assert (segment.start, segment.end, segment.segment_id) == (.1, 1.8, 1)


def test_migration_keeps_disabled_correction_and_emphasis(store):
    from twobyteasr.glossary.terminology import snapshot_glossaries, TermResolver
    payload = store.load_learned_term_payload()
    payload['games']['test']['mappings'][0].update(correction_enabled=False, emphasis_enabled=True)
    store.atomic_write_json(store.LEARNED_TERMS_PATH, payload)
    row = m.read_concepts(store, 'test')[0]
    row['names']['en'] = m.name_record('Aria')
    m.save_concept(store, 'test', row)
    snapshot = m.source_snapshot(snapshot_glossaries(store, ['test']), 'zh')
    assert TermResolver(snapshot).resolve('艾丽呀').text == '艾丽呀'
    assert next(term for lib in snapshot.libraries for term in lib.terms if term.canonical == '艾莉娅').emphasis_enabled


def test_conflict_choice_without_legacy_directional_library(store):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QTableWidget, QDialog
    from twobyteasr.glossary.translation_terms_ui import TranslationTermsDialog
    app = QApplication.instance() or QApplication([])
    m.save_concept(store, 'test', multilingual())
    other = multilingual(); other['names']['en']['name'] = 'Alternative'
    m.save_concept(store, 'other', other)
    dialog = TranslationTermsDialog({'enabled': True, 'concept_library_ids': ['test', 'other']})
    assert dialog.source.isEnabled() and dialog.target.isEnabled()
    dialog.source.setCurrentIndex(dialog.source.findData('zh')); dialog.target.setCurrentIndex(dialog.target.findData('en'))
    def choose_owned_fixture():
        popup = app.activeModalWidget(); assert isinstance(popup, QDialog)
        table = popup.findChild(QTableWidget); assert table.rowCount() > 0
        box = table.cellWidget(0, 1); box.setCurrentIndex(box.findData('concept-library:test'))
        popup.accept()
    QTimer.singleShot(0, choose_owned_fixture)
    dialog.shared_panel.conflicts()
    assert t.relevant(m.hydrate_policy(dialog.value(), store), 'zh', 'en', '艾莉娅')[0]['target'] == 'Aria'
    dialog.close()


def test_view_or_link_never_confirms_unsaved_manual_name(store):
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.glossary.multilingual_terms_ui import NamesEditor
    app = QApplication.instance() or QApplication([])
    c = multilingual(); c['names']['en'] = m.name_record('Aria', confirmed=False)
    original = m.save_concept(store, 'test', c)
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    editor = NamesEditor(page, original)
    editor.names.setCurrentRow(list(editor.draft['names']).index('en'))
    editor.standard.setText('Manually edited but unsaved')
    editor.review(); editor.link()
    actual = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])
    assert actual == original and not m.is_confirmed(actual['names']['en'])
    assert '未保存' in editor.message.text()
    editor.close(); page.close()


def test_existing_proofread_term_editor_updates_one_language_and_undo(store):
    from twobyteasr.glossary.term_editing import edit_term, library_terms
    from twobyteasr.glossary.terminology import snapshot_glossaries
    c = m.save_concept(store, 'test', multilingual())
    record = next(r for r in library_terms(snapshot_glossaries(store, ['test'])) if r.canonical == 'Aria')
    command = edit_term(store, record, 'Aria Updated', ['Areya'])
    updated = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])
    assert updated['names']['en']['name'] == 'Aria Updated'
    assert updated['names']['zh-Hans'] == c['names']['zh-Hans']
    assert updated['names']['en']['mistranslations'] == ['Alyria']
    assert len(m.read_concepts(store, 'test')) == 2
    command.undo(store)
    assert next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id']) == c


def test_editing_another_language_preserves_default_card_language(store):
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.glossary.multilingual_terms_ui import NamesEditor
    app = QApplication.instance() or QApplication([])
    c = m.save_concept(store, 'test', multilingual())
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    editor = NamesEditor(page, c)
    editor.names.setCurrentRow(list(c['names']).index('en')); editor.standard.setText('Aria New')
    editor.save()
    saved = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])
    assert m.card_rows([saved])[0]['target'] == '艾莉娅'
    assert list(saved['names']) == list(c['names'])
    editor.close(); page.close()


def test_migration_cannot_promote_ai_provenance_even_with_old_true_flag(store):
    from twobyteasr.glossary.terminology import snapshot_glossaries, TermResolver
    payload = store.load_learned_term_payload()
    payload['games']['test']['mappings'][0].update(confirmed=True, provenance='candidate', origin='AI 学习')
    store.atomic_write_json(store.LEARNED_TERMS_PATH, payload)
    row = m.read_concepts(store, 'test')[0]
    assert not m.is_confirmed(row['names']['und'])
    assert row['legacy_records'][0]['confirmed'] is True
    m.save_concept(store, 'test', row)
    assert TermResolver(snapshot_glossaries(store, ['test'])).resolve('艾丽呀').text == '艾丽呀'


def test_pending_imported_name_can_be_explicitly_confirmed_per_language(store):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.glossary.multilingual_terms_ui import NamesEditor
    c = multilingual(); c['names']['en'] = m.name_record('Aria', confirmed=False)
    c['names']['ja'] = m.name_record('アリア', confirmed=False)
    original = m.save_concept(store, 'test', c)
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    editor = NamesEditor(page, original); editor.names.setCurrentRow(list(c['names']).index('en'))
    editor.confirm_name_button.click()
    assert not m.is_confirmed(next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])['names']['en'])
    editor.save()
    saved = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])
    assert m.is_confirmed(saved['names']['en']) and not m.is_confirmed(saved['names']['ja'])
    assert saved['names']['zh-Hans'] == c['names']['zh-Hans']
    editor.close(); page.close()


@pytest.mark.parametrize('name,aliases,text', [
    ('Alyria', [], 'Alyria at the royal court'),
    ('Lyrien', ['Alyria'], 'Alyria at the royal court'),
    ('Alyria Royal', [], 'Alyria Royal at the royal court'),
])
def test_target_error_cannot_destroy_another_valid_name_or_alias(store, name, aliases, text):
    c = m.concept('Aria', 'en', description='royal court')
    c['names']['en']['mistranslations'] = ['Alyria']; m.save_concept(store, 'test', c)
    other = m.concept(name, 'en'); other['names']['en']['aliases'] = aliases
    m.save_concept(store, 'test', other)
    frozen = t.freeze(policy(store))
    assert not m.target_rules(frozen, 'en', text)
    assert any(row['name'] == 'Aria' and row['ambiguous'] for row in m.target_candidates(frozen, 'en', text))


def test_target_error_does_not_split_a_longer_valid_cjk_name(store):
    c = m.concept('光合治愈', 'zh-Hans', description='祭司')
    c['names']['zh-Hans']['mistranslations'] = ['光合']; m.save_concept(store, 'test', c)
    m.save_concept(store, 'test', m.concept('光合剑', 'zh-Hans'))
    assert not m.target_rules(t.freeze(policy(store)), 'zh-Hans', '光合剑站在祭司旁边')


def test_standalone_target_name_reaches_ai_without_invented_source_pair(store, monkeypatch):
    from PySide6.QtGui import QUndoStack
    from twobyteasr.subtitle_rules import subtitle_translation as st
    from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
    from twobyteasr.glossary.terminology import GlossarySnapshot
    from twobyteasr.studio.subtitle_text_targets import text_entries, review_project
    from twobyteasr.studio.studio_find_replace import apply_occurrences
    from twobyteasr.providers import ai_providers
    c = m.concept('Aria', 'en'); c['names']['en']['mistranslations'] = ['Alyria']
    m.save_concept(store, 'test', c); p = project_for_test(); p.cues[0].text = '她来了'
    p.generation_metadata['translation_records'] = st._empty_container('en')
    st.set_manual(p, 'cue-identity', 'Miss Alyria has arrived.', target='en')
    before = copy.deepcopy(m.read_concepts(store, 'test'))
    seen = []
    def complete(messages, **kwargs):
        payload = json.loads(messages[-1]['content']); target = payload['targets'][0]; seen.append(target)
        assert not target['translation_terminology']
        assert target['target_terminology'][0]['name'] == 'Aria'
        assert target['target_terminology'][0]['wrong_in_text'] == ['Alyria']
        return json.dumps({'changes': [{'target_id': target['target_id'], 'original': target['target_text'],
            'replacement': 'Miss Aria has arrived.', 'reason': '仅校对已有英文误译名'}]})
    monkeypatch.setattr(ai_providers, 'provider_for_stage', lambda *a, **kw: SimpleNamespace(complete=complete))
    entries = text_entries(p, mode='translation')
    result = preview_glossary_correction(review_project(p, entries), [e.key for e in entries], GlossarySnapshot(), {}, use_ai=True)
    assert seen and result.hits
    page = SimpleNamespace(session=SimpleNamespace(project=p, undo_stack=QUndoStack()), _changed=lambda: None)
    assert apply_occurrences(page, result.hits, title='校对已有英语')[0] == 1
    assert text_entries(p, mode='translation')[0].text == 'Miss Aria has arrived.'
    assert not m.target_candidates(t.freeze(policy(store)), 'en', 'Miss has arrived.')
    assert m.read_concepts(store, 'test') == before


def test_card_rows_keep_own_name_and_show_display_language_state():
    """2026-11-13 (plan 2026-11-13-glossary-library-redesign-c)."""
    c = multilingual(); c['names']['en'] = m.name_record('Aria', confirmed=False)
    c['candidates'] = {'ko': [{'id': 'k1', 'name': '아리아'}]}
    rows = {code: m.card_rows([c], code)[0] for code in ('en', 'ja', 'ko', 'fr-FR', '')}
    assert all(row['target'] == '艾莉娅' for row in rows.values())
    assert (rows['en']['translation_code'], rows['en']['translation'], rows['en']['translation_state']) == ('EN', 'Aria', 'pending')
    assert rows['ja']['translation_state'] == 'confirmed'
    assert (rows['ko']['translation'], rows['ko']['translation_state']) == ('아리아', 'candidate')
    assert (rows['fr-FR']['translation'], rows['fr-FR']['translation_state']) == ('', 'missing')
    assert rows['']['translation_code'] == '' and m.card_rows([c], 'zh-Hans')[0]['translation_code'] == ''


def test_switching_drawer_cards_shows_no_stray_window(store, monkeypatch):
    """2026-11-13 (user): every card switch flashed blank windows (header
    buttons shown before they had a parent); an open drawer stays open."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QFrame, QVBoxLayout
    from twobyteasr.glossary import multilingual_terms_ui as ui
    monkeypatch.setattr(ui, 'refresh', lambda _page: None)
    first = m.save_concept(store, 'test', multilingual())
    second = m.save_concept(store, 'test', m.concept('迪莫', 'zh-Hans'))
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    page.names_drawer = QFrame(page); QVBoxLayout(page.names_drawer)
    page.show(); APP.processEvents()
    shown, hidden = [], []

    class Watch(QObject):
        def eventFilter(self, widget, event):
            if isinstance(widget, QWidget) and widget.isWindow() and widget is not page:
                if event.type() == QEvent.Type.Show: shown.append(type(widget).__name__)
            if widget is page.names_drawer and event.type() == QEvent.Type.Hide: hidden.append(True)
            return False
    watch = Watch(); APP.installEventFilter(watch)
    try:
        ui.open_editor(page, first['id']); APP.processEvents()
        ui.open_editor(page, second['id']); APP.processEvents()
    finally:
        APP.removeEventFilter(watch)
    assert shown == [] and hidden == []
    assert page._names_editor.draft['id'] == second['id'] and page.names_drawer.layout().count() == 1
    page.close()


def test_names_drawer_switches_cards_but_keeps_unsaved_edits(store, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout
    from twobyteasr.glossary import multilingual_terms_ui as ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, 'refresh', lambda _page: None)
    first = m.save_concept(store, 'test', multilingual())
    second = m.save_concept(store, 'test', m.concept('迪莫', 'zh-Hans'))
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    page.names_drawer = QFrame(page); QVBoxLayout(page.names_drawer)
    ui.open_editor(page, first['id'])
    editor = page._names_editor
    assert editor.embedded and editor.parentWidget() is page.names_drawer and not editor.isWindow()
    assert editor.title.text() == '艾莉娅'
    editor.standard.setText('艾莉娅改')
    ui.open_editor(page, second['id'])
    assert page._names_editor is editor and '未保存' in editor.message.text()
    editor.save()  # the drawer stays open after saving
    assert page._names_editor is editor and '已保存' in editor.message.text()
    assert next(r for r in m.read_concepts(store, 'test') if r['id'] == first['id'])['names']['zh-Hans']['name'] == '艾莉娅改'
    ui.open_editor(page, second['id'])
    assert page._names_editor is not editor and page._names_editor.draft['id'] == second['id']
    page._names_editor.reject()
    app.processEvents()
    assert page._names_editor is None and page.names_drawer.isHidden()
    page.close()


class _SearchProvider:
    """Structured web-search reply with receipts, like the real CLI/百炼 transports."""
    def __init__(self, names, receipts):
        self.names, self.receipts, self.calls = names, receipts, []

    def structured_complete(self, messages, schema, **kwargs):
        self.calls.append((messages, kwargs))
        kwargs['request_diagnostics']['search_evidence'] = self.receipts
        return {'names': self.names}


def test_web_name_search_needs_real_sources_and_checks_existing_names(store, monkeypatch):
    """2026-11-13: 联网补全与校对译名 — sourced names become candidates; a name
    matching the sources is marked checked; a different one is a candidate
    with a note; nothing is confirmed without review."""
    from twobyteasr.glossary import translation_name_candidates as tn
    from twobyteasr.glossary import glossary_skill
    from twobyteasr.providers import ai_providers
    from twobyteasr.recognition.service import CancellationToken
    c = m.save_concept(store, 'test', multilingual())            # has en Aria (confirmed)
    other = m.save_concept(store, 'test', m.concept('迪莫', 'zh-Hans'))
    third = m.save_concept(store, 'test', m.concept('冰点', 'zh-Hans'))
    url = 'https://example.org/en/characters'
    provider = _SearchProvider([
        {'concept_id': c['id'], 'language': 'en', 'name': 'Aria', 'formality': 'official', 'sources': [{'url': url}]},
        {'concept_id': other['id'], 'language': 'en', 'name': 'Dimo', 'formality': 'official', 'sources': [{'url': url}]},
        {'concept_id': third['id'], 'language': 'en', 'name': 'Freeze', 'sources': [{'url': 'https://made.up/page'}]},
    ], [{'tool': 'web_search', 'urls': [url]}])
    monkeypatch.setattr(glossary_skill, 'detect_search_capability', lambda _s: {'provider_search': True, 'transport': 'grok_cli'})
    monkeypatch.setattr(ai_providers, 'provider_for_stage', lambda _s, _stage: provider)
    stats = tn.search_translation_names(store, 'test', '测试游戏', [c['id'], other['id'], third['id']], ['en'], {},
                                        token=CancellationToken())
    assert (stats['web'], stats['added'], stats['agreed'], stats['unsourced'], stats['failed']) == (True, 1, 1, 1, 0)
    assert provider.calls[0][1]['enable_search'] is True
    rows = {r['id']: r for r in m.read_concepts(store, 'test')}
    assert rows[c['id']]['names']['en']['web_check']['sources'] == [url]
    dimo = rows[other['id']]['candidates']['en'][0]
    assert (dimo['name'], dimo['formality'], dimo['verification'], m.is_confirmed(dimo)) == ('Dimo', 'official', 'web_search', False)
    assert 'en' not in rows[other['id']]['names'] and 'en' not in rows[third['id']].get('candidates', {})
    assert tn.sourced_official_candidates(store, 'test') == [(other['id'], 'en', dimo['id'])]


def test_web_name_search_without_receipts_files_nothing(store, monkeypatch):
    from twobyteasr.glossary import translation_name_candidates as tn
    from twobyteasr.glossary import glossary_skill
    from twobyteasr.providers import ai_providers
    from twobyteasr.recognition.service import CancellationToken
    c = m.save_concept(store, 'test', m.concept('迪莫', 'zh-Hans'))
    provider = _SearchProvider([{'concept_id': c['id'], 'language': 'en', 'name': 'Dimo',
                                 'sources': [{'url': 'https://example.org/a'}]}], [])
    monkeypatch.setattr(glossary_skill, 'detect_search_capability', lambda _s: {'provider_search': True, 'transport': 'grok_cli'})
    monkeypatch.setattr(ai_providers, 'provider_for_stage', lambda _s, _stage: provider)
    stats = tn.search_translation_names(store, 'test', '测试游戏', [c['id']], ['en'], {}, token=CancellationToken())
    assert stats['failed'] == 1 and '检索证据' in stats['errors'][0]['error']
    assert not next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id']).get('candidates')

class _PlainProvider:
    """A chat model without its own search (DeepSeek): it only reads the results it is given."""
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def structured_complete(self, messages, schema, **kwargs):
        self.calls.append((messages, kwargs))
        return {'names': self.reply(json.loads(messages[1]['content']))}


def test_deepseek_search_feeds_results_and_keeps_only_returned_urls(store, monkeypatch):
    """2026-11-13 (user): DeepSeek has its own Search API. The app searches each
    term, hands the results to the model and files only names whose source URL
    the search returned; the model call itself asks for no search."""
    from twobyteasr.glossary import translation_name_candidates as tn
    from twobyteasr.glossary import glossary_skill
    from twobyteasr.providers import ai_providers, llm_config
    from twobyteasr.recognition.service import CancellationToken
    c = m.save_concept(store, 'test', m.concept('倾泻', 'zh-Hans'))
    other = m.save_concept(store, 'test', m.concept('冰点', 'zh-Hans'))
    queries = []

    def search(key, query, *, count, ori_question, cancel_check=None):
        queries.append((key, query, ori_question))
        if '倾泻' in query:
            return [dict(title='Downpour - Roco Kingdom World Wiki', url='https://wiki.example/en/Downpour',
                         summary='Downpour (倾泻) is a water skill.', snippet='')]
        return []

    def reply(payload):
        rows = {row['concept_id']: row for row in payload['terms']}
        assert rows[c['id']]['search_results']['en'][0]['url'] == 'https://wiki.example/en/Downpour'
        assert rows[other['id']]['search_results']['en'] == []
        return [{'concept_id': c['id'], 'language': 'en', 'name': 'Downpour', 'formality': 'community',
                 'sources': [{'url': 'https://wiki.example/en/Downpour'}]},
                {'concept_id': other['id'], 'language': 'en', 'name': 'Freezing Point',
                 'sources': [{'url': 'https://invented.example/x'}]}]

    provider = _PlainProvider(reply)
    monkeypatch.setattr(glossary_skill, 'detect_search_capability',
                        lambda _s: {'provider_search': False, 'tool_search': True, 'transport': 'openai_compatible_chat'})
    monkeypatch.setattr(ai_providers, 'provider_for_stage', lambda _s, _stage: provider)
    monkeypatch.setattr(llm_config, 'endpoint_from_settings', lambda _s, _stage: {'api_key': 'sk-test'})
    stats = tn.search_translation_names(store, 'test', '洛克王国：世界', [c['id'], other['id']], ['en'], {},
                                        token=CancellationToken(), search=search)
    assert (stats['web'], stats['added'], stats['unsourced'], stats['failed'], stats['searches']) == (True, 1, 1, 0, 2)
    assert {q[0] for q in queries} == {'sk-test'} and all('洛克王国：世界' in q[1] for q in queries)
    messages, kwargs = provider.calls[0]
    assert kwargs['enable_search'] is False and kwargs['extra_body'] is None
    assert 'search_results' in messages[0]['content']
    rows = {r['id']: r for r in m.read_concepts(store, 'test')}
    downpour = rows[c['id']]['candidates']['en'][0]
    assert (downpour['name'], downpour['verification'], m.is_confirmed(downpour)) == ('Downpour', 'web_search', False)
    assert 'en' not in rows[other['id']].get('candidates', {})


def test_deepseek_balance_error_stops_the_run(store, monkeypatch):
    from twobyteasr.glossary import translation_name_candidates as tn
    from twobyteasr.glossary import glossary_skill
    from twobyteasr.providers import ai_providers, llm_config
    from twobyteasr.providers.deepseek_tools import DeepSeekToolError
    from twobyteasr.recognition.service import CancellationToken
    ids = [m.save_concept(store, 'test', m.concept(f'词{i}', 'zh-Hans'))['id'] for i in range(20)]

    def search(*_a, **_k):
        raise DeepSeekToolError('DeepSeek 账户余额不足，充值后再查。', status=402, category='balance')

    monkeypatch.setattr(glossary_skill, 'detect_search_capability', lambda _s: {'provider_search': False, 'tool_search': True})
    monkeypatch.setattr(ai_providers, 'provider_for_stage', lambda _s, _stage: _PlainProvider(lambda _p: []))
    monkeypatch.setattr(llm_config, 'endpoint_from_settings', lambda _s, _stage: {'api_key': 'sk-test'})
    stats = tn.search_translation_names(store, 'test', '游戏', ids, ['en'], {}, token=CancellationToken(), search=search)
    assert stats['total'] == 2 and stats['failed'] == 1 and '余额不足' in stats['stopped']


def test_deepseek_tools_client_and_capability():
    from twobyteasr.providers import deepseek_tools as ds
    sent = []

    class Response:
        def __init__(self, status, payload): self.status_code, self._payload = status, payload
        def json(self): return self._payload

    def post(url, headers, json, timeout):
        sent.append((url, headers['Authorization'], json))
        return Response(200, {'results': [{'title': 'T', 'url': 'https://a.example/p', 'snippet': 's', 'summary': 'x' * 900},
                                          {'title': 'bad', 'url': 'ftp://nope'}]})
    rows = ds.search('sk-1', 'q' * 200, count=99, ori_question='为什么', post=post)
    assert sent[0][0] == 'https://api.deepseek.com/v1/tools/search' and sent[0][1] == 'Bearer sk-1'
    assert len(sent[0][2]['query']) == 128 and sent[0][2]['count'] == 50 and sent[0][2]['ori_question'] == '为什么'
    assert [r['url'] for r in rows] == ['https://a.example/p'] and len(rows[0]['summary']) == 800
    with pytest.raises(ds.DeepSeekToolError) as error:
        ds.search('sk-1', 'q', post=lambda *a, **k: Response(402, {'error': {'message': 'Insufficient Balance'}}))
    assert error.value.category == 'balance'
    assert ds.supports({'provider': 'deepseek', 'api_key': 'sk', 'base_url': 'https://api.deepseek.com/v1'})
    assert not ds.supports({'provider': 'deepseek', 'api_key': 'sk', 'base_url': 'https://proxy.example/v1'})
    assert not ds.supports({'provider': 'deepseek', 'api_key': '', 'base_url': 'https://api.deepseek.com/v1'})


def test_name_search_sheet_counts_scopes_and_tries_twenty_first(store, monkeypatch):
    """2026-11-13 (user, option A): which language, which terms (with counts),
    先试 20 条 by default, and a plain line on whether the AI can go online."""
    from twobyteasr.glossary import glossary_skill
    from twobyteasr.glossary.name_search_sheet import NameSearchSheet, TRIAL
    ids = [m.save_concept(store, 'test', m.concept(f'词{i}', 'zh-Hans'))['id'] for i in range(25)]
    done = m.concept('迪莫', 'zh-Hans'); done['names']['en'] = m.name_record('Dimo', confirmed=True)
    m.save_concept(store, 'test', done)
    concepts = m.read_concepts(store, 'test')  # the fixture's legacy mapping is a concept too
    missing = [c['id'] for c in concepts if m.translation_state(c, 'en') != 'confirmed']
    assert set(ids) <= set(missing) and len(missing) < len(concepts)
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    page._ai_update_settings = lambda: {}
    monkeypatch.setattr(glossary_skill, 'detect_search_capability',
                        lambda _s: {'provider_search': False, 'tool_search': True, 'model': 'deepseek-v4-flash'})
    sheet = NameSearchSheet(page, 'en', selected=[ids[0]])
    assert sheet.scope() == 'selected' and sheet.chosen() == ('en', [ids[0]])
    sheet.scope_buttons['missing'].click()
    code, chosen = sheet.chosen()
    assert code == 'en' and len(chosen) == TRIAL and set(chosen) <= set(missing)
    assert sheet.scope_labels['missing'][1].text() == f'{len(missing)} 条'
    assert sheet.scope_labels['all'][1].text() == f'{len(concepts)} 条'
    assert 'DeepSeek 搜索' in sheet.estimate.text() and f'剩下 {len(missing) - TRIAL} 条' in sheet.estimate.text()
    assert 'DeepSeek' in sheet.ai_text.text() and sheet.start.text() == '开始查'
    sheet.trial.setChecked(False)
    assert len(sheet.chosen()[1]) == len(missing)
    sheet._pick_other('fr-FR')
    assert sheet.code == 'fr-FR' and sheet.language_buttons['fr-FR'].isChecked()
    assert sheet.scope_labels['missing'][1].text() == f'{len(concepts)} 条'
    monkeypatch.setattr(glossary_skill, 'detect_search_capability', lambda _s: {'provider_search': False})
    sheet._refresh()
    assert sheet.ai_box.property('web') == 'no' and sheet.start.text() == '仍然开始（只靠猜）'
    sheet.close(); page.close()


def test_capability_marks_deepseek_as_tool_search(monkeypatch):
    from twobyteasr.glossary import glossary_skill
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, 'endpoint_from_settings', lambda _s, _stage: {
        'provider': 'deepseek', 'api_key': 'sk-test', 'base_url': 'https://api.deepseek.com/v1', 'model': 'deepseek-v4-flash'})
    monkeypatch.setattr(llm_config, 'get_active_service', lambda _s: 'deepseek')
    capability = glossary_skill.detect_search_capability({'models': {}})
    assert (capability['provider_search'], capability['tool_search'], capability['web']) == (False, True, True)
    assert 'DeepSeek' in capability['reason']


def test_drawer_rows_candidates_and_banner_follow_draft_c(store, monkeypatch):
    from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QVBoxLayout
    from twobyteasr.glossary import multilingual_terms_ui as ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, 'refresh', lambda _page: None)
    c = m.concept('玳龟', 'zh-Hans', category='角色'); c['names']['zh-Hans']['mishearings'] = ['带龟']
    c['names']['ja'] = m.name_record('タイマイ', confirmed=False)
    c['candidates'] = {'en': [m.name_record('Daigui', confirmed=False, id='candidate:1', formality='official', verification='web_search')]}
    c = m.save_concept(store, 'test', c)
    page = FixtureWidget(); page.legacy = store; page._library_key = lambda: 'test'
    page.term_display_language = QComboBox(); page.term_display_language.addItem('English', 'en')
    page.names_drawer = QFrame(page); QVBoxLayout(page.names_drawer)
    ui.open_editor(page, c['id']); editor = page._names_editor
    assert 'Daigui' in editor.banner_text.text() and editor.banner_button.text() == '采用'
    assert editor.name_rows.count() == 3 and editor.name_count.text() == '1 已确认 / 3'
    assert editor.candidate_badge.text() == '1'
    editor.heard_input.setText('代龟'); editor.add_heard()
    assert editor.draft['names']['zh-Hans']['mishearings'] == ['带龟', '代龟'] and '1 处修改' in editor.message.text()
    editor.save(); editor.confirm_display()   # 采用 the official candidate from the banner
    saved = next(r for r in m.read_concepts(store, 'test') if r['id'] == c['id'])
    assert m.is_confirmed(saved['names']['en']) and saved['names']['en']['name'] == 'Daigui' and not saved.get('candidates')
    assert '已确认' in editor.banner_text.text()
    page.close()
