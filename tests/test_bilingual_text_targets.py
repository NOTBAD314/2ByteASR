"""Real record/command/export boundaries for bilingual text editing (A–F)."""
import copy
import json
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.studio.subtitle_text_targets import text_entries, review_project
from twobyteasr.studio.studio_text_tools import find_occurrences, values_from_occurrences, occurrence_conflicts
from twobyteasr.studio.studio_find_replace import apply_occurrences
from twobyteasr.glossary.terminology import snapshot_from_pairs
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction

APP = QApplication.instance() or QApplication([])


def make_project():
    p = SubtitleProject(StudioMedia('', duration_ms=20000), cues=[
        StudioCue('source-b', 3000, 5000, 'SHARED Neuvillette wins', speaker_id='S01'),
        StudioCue('source-a', 100, 2000, 'SHARED Neuvillette appears', speaker_id='S01'),
        StudioCue('source-missing', 6000, 8000, 'There is no translation', speaker_id='S02'),
        StudioCue('japanese-merged', 0, 5000, 'SHARED ヌヴィレットだ', speaker_id='ja-track'),
        StudioCue('independent-split-1', 5100, 5600, 'SHARED 那维来特', speaker_id='zh-import'),
        StudioCue('independent-split-2', 5600, 6000, '那维来特赢了', speaker_id='zh-import'),
    ], speakers=[StudioSpeaker('S01', 'Alice'), StudioSpeaker('S02', 'Bob'),
                 StudioSpeaker('ja-track', '日语导入'), StudioSpeaker('zh-import', '中文独立导入')],
        generation_metadata={'language': 'en', 'subtitle_imports': {'version': 1, 'tracks': {
            'ja-track': {'role': 'translation', 'language': 'ja'},
            'zh-import': {'role': 'independent', 'language': 'zh-Hans'}},
            'cues': {'japanese-merged': {'association': {}}, 'independent-split-1': {'association': {}}}}})
    p.validate()
    st.set_manual(p, 'source-a', 'SHARED 那维来特出现了', target='zh-Hans')
    st.set_manual(p, 'source-b', 'SHARED 那维来特赢了', target='zh-Hans')
    return p


def page_for(p):
    return SimpleNamespace(session=SimpleNamespace(project=p, undo_stack=QUndoStack()), _changed=lambda: None)


def find(p, mode='both', tracks=None, needle='SHARED', replacement='DONE', **kwargs):
    entries = text_entries(p, mode=mode, tracks=tracks)
    return find_occurrences(p, [c.id for c in p.cues], needle, replacement, entries=entries, **kwargs)


@pytest.mark.parametrize('mode,expected', [('original', 2), ('translation', 4), ('both', 6)])
def test_same_word_is_separate_per_layer_and_track(mode, expected):
    p = make_project()
    hits = find(p, mode)
    assert len(hits) == expected
    assert len({h.target_key for h in hits}) == expected
    assert not occurrence_conflicts(hits)
    page = page_for(p)
    assert apply_occurrences(page, hits, title='SHARED') == (expected, expected)
    assert page.session.undo_stack.count() == 1
    assert len(find(p, mode, needle='DONE')) == expected
    page.session.undo_stack.undo()
    assert len(find(p, mode)) == expected
    page.session.undo_stack.redo()
    assert len(find(p, mode, needle='DONE')) == expected


def test_chinese_only_preserves_source_japanese_timing_associations_and_undo(tmp_path):
    p = make_project()
    before_cues = copy.deepcopy(p.cues)
    before_metadata = copy.deepcopy(p.generation_metadata)
    tracks = {'translation-records:zh-Hans', 'zh-import'}
    hits = find(p, 'translation', tracks, needle='那维来特', replacement='那维莱特')
    page = page_for(p)
    assert len(hits) == 4
    assert apply_occurrences(page, hits, title='名字') == (4, 4)
    assert p.cues[:4] == before_cues[:4]
    assert p.generation_metadata['subtitle_imports'] == before_metadata['subtitle_imports']
    assert all('那维莱特' in e.text for e in text_entries(p, mode='translation', tracks=tracks))
    assert st.records_of(p)['source-a']['origin'] == 'manual'
    assert st.records_of(p)['source-a']['previous'][0]['text'] == 'SHARED 那维来特出现了'
    page.session.undo_stack.undo()
    assert p.cues == before_cues
    assert st.snapshot(p) == {key: before_metadata.get(key) for key in (st.RECORDS_KEY, st.RENDER_KEY)}
    page.session.undo_stack.redo()
    assert st.records_of(p)['source-a']['text'] == 'SHARED 那维莱特出现了'
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    from twobyteasr.exports.srt_codec import parse_srt
    artifacts = export_subtitle_artifacts(p,tmp_path/'independent-export','tracks',SubtitleExportOptions(speaker_mode='per_speaker'))
    artifact = next(a for a in artifacts if a.speaker_id=='zh-import')
    rows, errors = parse_srt(artifact.path.read_text('utf-8'))
    assert not errors and all('那维莱特' in row.text for row in rows)


@pytest.mark.parametrize('mode', ['translation', 'both'])
def test_translation_batch_revisions_survive_local_content_reuse(mode):
    from twobyteasr.projects.studio_revisions import StudioRevisionStore, thaw_json
    from twobyteasr.projects.studio_runtime_state import state_for

    p = make_project()
    p.render_settings['_cue_domain'] = 'timeline'
    store = StudioRevisionStore(p)
    state_for(p).subscribe(store.consume)
    page = page_for(p)
    before = copy.deepcopy(p.generation_metadata['translations'])
    hits = find(p, mode, {'translation-records:zh-Hans'}, needle='SHARED', replacement='DONE')
    assert hits
    apply_occurrences(page, hits, title='revisions')
    after = copy.deepcopy(p.generation_metadata['translations'])
    assert after != before

    def check_current(expected):
        assert thaw_json(store.materialize_render().generation_metadata)['translations'] == expected
        assert thaw_json(store.persistence.generation_metadata)['translations'] == expected

    check_current(after)
    page.session.undo_stack.undo()
    check_current(before)
    page.session.undo_stack.redo()
    check_current(after)


def test_no_positional_mapping_with_reorder_missing_split_merge_and_import():
    p = make_project()
    hits = find(p, 'translation', needle='那维来特', replacement='那维莱特')
    p.cues.reverse()
    values = values_from_occurrences(p, hits)
    assert len(values) == 4
    del p.cues[next(i for i, c in enumerate(p.cues) if c.id == 'source-a')]
    values = values_from_occurrences(p, hits)
    assert len(values) == 3
    page = page_for(p)
    assert apply_occurrences(page, hits, title='partial') == (3, 3)
    assert next(c.text for c in p.cues if c.id == 'source-b') == 'SHARED Neuvillette wins'
    assert st.records_of(p)['source-b']['text'] == 'SHARED 那维莱特赢了'


def test_full_snapshot_blocks_old_suggestion_even_when_span_still_matches():
    p = make_project()
    hits = find(p, 'translation', {'translation-records:zh-Hans'}, needle='那维来特', replacement='那维莱特')
    st.set_manual(p, 'source-a', '手动改句子 SHARED 那维来特出现了')
    page = page_for(p)
    assert apply_occurrences(page, hits, title='stale') == (1, 1)
    assert st.records_of(p)['source-a']['text'].startswith('手动改句子')


def test_track_relabel_invalidates_old_address():
    p = make_project()
    hits = find(p, 'translation', {'zh-import'}, needle='那维来特', replacement='那维莱特')
    p.generation_metadata['subtitle_imports']['tracks']['zh-import']['language'] = 'ja'
    assert apply_occurrences(page_for(p), hits, title='stale') == (0, 0)


def test_independent_translation_without_known_source_language_is_explicitly_selectable():
    p = make_project()
    p.generation_metadata.pop('language')
    tracks = {'zh-import'}
    entries = text_entries(p, mode='translation', tracks=tracks)
    assert {e.key for e in entries} == {'independent-split-1','independent-split-2'}
    assert all(e.target.layer == 'translation' and not e.source_text for e in entries)
    hits = find(p, 'translation', tracks, needle='那维来特', replacement='那维莱特')
    assert apply_occurrences(page_for(p), hits, title='independent') == (2, 2)
    assert all('那维莱特' in e.text for e in text_entries(p, mode='translation', tracks=tracks))


def test_source_context_change_invalidates_old_translation_suggestion():
    p = make_project()
    hits = find(p,'translation',{'translation-records:zh-Hans'},needle='那维来特',replacement='那维莱特')
    next(c for c in p.cues if c.id=='source-a').text = 'A completely different meaning'
    assert apply_occurrences(page_for(p),hits,title='stale context') == (1,1)
    assert '那维来特' in st.records_of(p)['source-a']['text']


def test_unlabeled_independent_translation_does_not_inherit_english_and_can_be_reviewed(monkeypatch):
    p=make_project()
    p.generation_metadata['subtitle_imports']['tracks']['zh-import']['language']=''
    entries=text_entries(p,mode='translation',tracks={'zh-import'})
    assert entries and all(e.target.language=='' and e.target.layer=='translation' for e in entries)
    class Provider:
        def complete(self,messages,**kwargs):
            payload=json.loads(messages[1]['content'])
            assert all(row['target_language']=='und' for row in payload['targets'])
            return {'changes':[{'target_id':row['target_id'],'original':row['target_text'],
                'replacement':row['target_text'].replace('那维来特','那维莱特'),'reason':'请确认目标译名'} for row in payload['targets']]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:Provider())
    result=preview_glossary_correction(review_project(p,entries),[e.key for e in entries],
        snapshot_from_pairs([('那维来特','那维莱特')]),{},use_ai=True)
    assert result.hits and all(not hit.default_selected for hit in result.hits)
    assert apply_occurrences(page_for(p),list(result.hits),title='unlabeled')==(2,2)


@pytest.mark.parametrize('scope,count', [('all',5),('current',2),('selected',3),('speaker',4),('track',4),('range',5)])
def test_layer_selection_composes_with_existing_semantic_scopes(scope,count):
    from twobyteasr.studio.subtitle_text_targets import scope_entries
    p = make_project()
    page = SimpleNamespace(session=SimpleNamespace(project=p, selected_cue_id='source-a'),
        selected_cue_ids=lambda:['source-a','source-missing'], timeline=SimpleNamespace(active_subtitle_layer='original'))
    entries = scope_entries(page,scope,mode='both',tracks={'translation-records:zh-Hans'})
    assert len(entries)==count


def test_locked_owner_and_selected_translation_ids_are_respected():
    from twobyteasr.studio.subtitle_text_targets import scope_entries
    p=make_project()
    page=SimpleNamespace(session=SimpleNamespace(project=p,selected_cue_id='source-a'),selected_cue_ids=lambda:['source-b'],
        timeline=SimpleNamespace(active_subtitle_layer='translation',translation_selected_ids={'source-a'}))
    entries=scope_entries(page,'selected',mode='translation',tracks={'translation-records:zh-Hans'})
    assert [e.target.cue_id for e in entries]==['source-a']
    p.studio_state['locked_cue_ids']=['source-a']
    hits=find_occurrences(p,[c.id for c in p.cues],'SHARED','X',entries=entries,locked_ids=['source-a'])
    assert not hits


def test_regex_case_whole_word_and_body_offsets_use_the_same_text():
    p = make_project()
    st.set_manual(p, 'source-a', r'{\i1}shared SHARED sharedish')
    hits = find(p, 'translation', {'translation-records:zh-Hans'}, needle='shared', replacement='X', whole_word=True, body_only=True)
    assert len(hits) == 3
    assert values_from_occurrences(p, hits)[hits[0].target_key]
    regex = find(p, 'translation', {'translation-records:zh-Hans'}, needle='(SH)(ARED)', replacement=r'\2\1', regex=True, case_sensitive=True)
    assert len(regex) == 2 and all(h.replacement == 'AREDSH' for h in regex)


def test_translation_local_review_is_bound_to_its_language_and_original_reference():
    p = make_project()
    entries = text_entries(p, mode='translation', tracks={'translation-records:zh-Hans'})
    result = preview_glossary_correction(review_project(p, entries), [e.key for e in entries],
        snapshot_from_pairs([('那维来特', '那维莱特')]), {}, use_ai=False)
    assert len(result.hits) == 2
    assert all(h.target.layer == 'translation' and h.target.language == 'zh-Hans' for h in result.hits)
    assert all(row['source_reference'].startswith('SHARED Neuvillette') for row in result.receipt['segments'])
    assert apply_occurrences(page_for(p), list(result.hits), title='校对') == (2, 2)
    assert p.cues[0].text == 'SHARED Neuvillette wins'


def test_chinese_translation_can_use_confirmed_latin_player_alias():
    p=make_project()
    st.set_manual(p,'source-a','球球赢了')
    entries=[e for e in text_entries(p,mode='translation',tracks={'translation-records:zh-Hans'}) if e.target.cue_id=='source-a']
    result=preview_glossary_correction(review_project(p,entries),[e.key for e in entries],
        snapshot_from_pairs([('球球','CHICHOO')]),{},use_ai=False)
    assert result.hits and all(hit.target.layer=='translation' for hit in result.hits)
    assert apply_occurrences(page_for(p),list(result.hits),title='player')==(1,1)
    assert st.records_of(p)['source-a']['text']=='CHICHOO赢了'


def test_real_ai_request_target_snapshot_and_foreign_script_guard(monkeypatch):
    p = make_project()
    entries = text_entries(p, mode='translation', tracks={'translation-records:zh-Hans'})
    seen = []
    class Provider:
        def complete(self, messages, **kwargs):
            payload = json.loads(messages[1]['content'])
            seen.append(payload)
            return {'changes': [{'target_id': row['target_id'], 'original': row['target_text'],
                    'replacement': row['target_text'].replace('那维来特', '那维莱特'), 'reason': '角色译名'} for row in payload['targets']]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: Provider())
    result = preview_glossary_correction(review_project(p, entries), [e.key for e in entries],
        snapshot_from_pairs([('那维来特', '那维莱特')]), {}, use_ai=True)
    assert seen[0]['targets'][0]['target_language'] == 'zh-Hans'
    assert seen[0]['targets'][0]['source_reference'].startswith('SHARED Neuvillette')
    assert p.cues[0].text == 'SHARED Neuvillette wins'
    # English has no proven Chinese translated-name mapping: do not normalize.
    english = text_entries(p, mode='original')
    english = [e for e in english if e.target.cue_id == 'source-a']
    result = preview_glossary_correction(review_project(p, english), [e.key for e in english],
        snapshot_from_pairs([('Neuvillette', '那维莱特')]), {}, use_ai=True)
    assert not result.hits


def test_failure_cancellation_and_empty_translation_never_clear_text(monkeypatch):
    from twobyteasr.recognition.service import CancellationToken
    p = make_project()
    before = copy.deepcopy(p.to_dict())
    entries = text_entries(p, mode='translation')
    class Provider:
        def complete(self, *a, **k):
            raise RuntimeError('offline failure')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: Provider())
    result = preview_glossary_correction(review_project(p, entries), [e.key for e in entries], snapshot_from_pairs([]), {}, use_ai=True)
    assert result.receipt['fallback_cues'] == len(entries) and not result.hits
    assert p.to_dict() == before
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Exception, match='取消'):
        preview_glossary_correction(p, [], snapshot_from_pairs([]), {}, cancel_token=token)
    assert not any(e.target.cue_id == 'source-missing' for e in text_entries(p, mode='translation'))


def test_save_reopen_and_display_projection_are_consistent(tmp_path):
    p = make_project()
    page = page_for(p)
    hits = find(p, 'translation', {'translation-records:zh-Hans'}, needle='那维来特', replacement='那维莱特')
    assert apply_occurrences(page, hits, title='names') == (2, 2)
    p.studio_state['bilingual'] = {'mode': 'bilingual'}
    saved = load_project(save_project(p, tmp_path / 'lifecycle.2byteproj'))
    assert st.translation_view(saved) == st.translation_view(p)
    assert saved.generation_metadata['translations']['source-a'] == 'SHARED 那维莱特出现了'
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    assert any('那维莱特' in c.text for c in project_display_cues(saved))
    assert next(c.text for c in saved.cues if c.id == 'source-a') == 'SHARED Neuvillette appears'
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    for label, live in (('live', p), ('reopened', saved)):
        exported = export_language_layers(live, tmp_path / label, '字幕', layers=('translation', 'bilingual'))
        for artifact in exported.artifacts:
            rows, errors = parse_srt(artifact.path.read_text('utf-8'))
            assert not errors
            assert any('那维莱特' in row.text for row in rows)
            assert all('那维来特' not in row.text for row in rows if row.start_ms == 100)

