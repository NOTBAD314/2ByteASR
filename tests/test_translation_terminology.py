"""Exercise committed source → model input → checked result → versioned writeback."""
import copy
import json
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtGui import QUndoStack
from tests.test_subtitle_translation import make_project, FakeProvider
from twobyteasr.glossary.translation_terms import KEY, normalize, relevant, violations
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.projects.studio_project import save_project, load_project
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand


def policy():
    return normalize(dict(enabled=True, selected_ids=['jp'], libraries=[dict(id='jp', name='游戏译名',
        source_language='ja', target_language='zh-Hans', terms=[dict(source='アリス',target='爱丽丝',aliases=['アリヌ'],context='')])]))


def project():
    p = make_project(['アリヌが来た', '行くぞ！'] + ['ナイス！']*8 + ['無関係の話です'])
    p.glossary_ids = ['original-library']
    p.generation_metadata[KEY] = policy()
    return p


class Provider(FakeProvider):
    @staticmethod
    def translate_all(payload, call_no):
        terms = payload.get('translation_terminology', [])
        target = terms[0]['target'] if terms else '好的'
        return {'items':[{'id':row['id'], 'translation':target+'来了' if 'アリ' in row['text'] else '好的'}
                         for row in payload['lines'] if row['translate']]}


def run(p, provider=None, ids=None, **kwargs):
    return st.translate(p, ids, provider or Provider(), target='zh-Hans', retry_wait=lambda _: True, **kwargs)


def test_actual_request_uses_only_applied_source_and_directional_mapping():
    p = project(); stack = QUndoStack()
    stack.push(SetCueFieldsCommand(p, 'c0', {'text':'アリスが来た'}, '原文校对'))
    provider = Provider(); result = run(st.translation_source(p), provider, ['c0'])
    payload = provider.calls[0]['payload']
    assert next(row['text'] for row in payload['lines'] if row['id']=='c0') == 'アリスが来た'
    assert payload['translation_terminology'][0]['target'] == '爱丽丝'
    assert '原文' in provider.calls[0]['messages'][0]['content']
    assert result.translations['c0'].text == '爱丽丝来了'
    stack.undo()
    assert p.cues[0].text == 'アリヌが来た'
    # Unapplied proposals are not input: only the undo-restored source is read.
    assert st.translation_source(p).cues[0].text == 'アリヌが来た'


def test_wrong_online_or_common_name_is_rejected_and_retried_without_replacing_text():
    p = project(); provider = FakeProvider(lambda data,n: {'items':[{'id':row['id'],'translation':'阿莉丝来了'}
        for row in data['lines'] if row['translate']]})
    result = run(p, provider, ['c0'])
    assert result.failed['c0'].startswith('terminology_mismatch')
    assert len(provider.calls) == 2
    assert not result.translations and p.cues[0].text == 'アリヌが来た'


def test_homonyms_and_unrelated_libraries_are_not_mechanical_replacements():
    value = policy(); lib = value['libraries'][0]
    lib['terms'] = [dict(source='橋',target='角色桥',aliases=[],context='角色名字'),
                    dict(source='橋',target='桥梁',aliases=[],context='普通建筑')]
    terms = relevant(value,'ja','zh-Hans','橋を渡る')
    assert len(terms)==2 and not violations('橋を渡る','过桥',terms)
    assert not relevant(value,'en','zh-Hans','橋')
    assert not relevant(value,'ja','en','橋')
    assert not relevant({'enabled':True, 'libraries':[{'canonical':'Foo','aliases':['ふー']} ]},'ja','zh-Hans','ふー')


def test_latin_names_next_to_japanese_particles_have_a_real_term_boundary():
    from twobyteasr.glossary.translation_terms import matched_pairs
    value=policy();value['libraries'][0]['terms'][0]['source']='Alice';value['libraries'][0]['terms'][0]['aliases']=[]
    assert relevant(value,'ja','zh-Hans','Aliceが来た')
    assert not relevant(value,'ja','zh-Hans','Maliceが来た')
    assert matched_pairs([('Alice','爱丽丝')],'Aliceが来た','ja')==[('Alice','爱丽丝')]


def test_required_target_name_does_not_match_inside_an_ordinary_word():
    value=policy();value['libraries'][0]['target_language']='en';value['libraries'][0]['terms'][0]['target']='Alice'
    terms=relevant(value,'ja','en','アリスが来た')
    assert violations('アリスが来た','Malice arrived',terms)
    assert not violations('アリスが来た','Alice arrived',terms)


def test_per_cue_cache_and_status_change_only_relevant_rules(tmp_path):
    p=project(); cache={}; first=run(p,cache=cache); st.apply_translation_result(p,first)
    assert st.cue_status(p,'c0')=='done'
    changed=copy.deepcopy(p.generation_metadata[KEY]); changed['libraries'][0]['terms'][0]['target']='艾丽丝'
    p.generation_metadata[KEY]=changed
    assert st.cue_status(p,'c0')=='needs_update'
    assert st.cue_status(p,'c10')=='done'
    provider=Provider(); result=run(p,provider,cache=cache,max_items=1)
    assert 'c10' in result.cache_hits and 'c0' not in result.cache_hits
    assert result.translations['c0'].text=='艾丽丝来了'
    saved=load_project(save_project(p,tmp_path/'terms.2byteproj'))
    assert saved.generation_metadata[KEY]==changed and saved.glossary_ids==['original-library']


def test_library_rename_is_not_a_semantic_cache_invalidation():
    p=project();cache={};result=run(p,cache=cache);st.apply_translation_result(p,result)
    p.generation_metadata[KEY]['libraries'][0]['name']='更友好的名字'
    provider=Provider();again=run(p,provider,cache=cache)
    assert not provider.calls and st.cue_status(p,'c0')=='done'


def test_explicit_manual_correction_is_current_until_relevant_rules_or_source_change():
    p=project(); st.set_manual(p,'c0','爱丽丝来了')
    assert st.cue_status(p,'c0')=='manual'
    p.generation_metadata[KEY]['libraries'][0]['terms'][0]['target']='艾丽丝'
    assert st.cue_status(p,'c0')=='needs_update'


def test_pending_manual_suggestion_is_rechecked_against_updated_terms():
    p=project();st.set_manual(p,'c0','保留手工')
    result=run(p,ids=['c0']);assert result.suggestions
    p.generation_metadata[KEY]['libraries'][0]['terms'][0]['target']='艾丽丝'
    st.accept_suggestions(p,result)
    assert st.records_of(p)['c0']['text']=='保留手工' and result.discarded['c0']=='terminology_changed'


def test_split_group_display_text_edits_one_real_owner_and_survives_export_undo():
    from twobyteasr.studio.subtitle_text_targets import text_entries
    from twobyteasr.studio.studio_text_tools import find_occurrences
    from twobyteasr.studio.studio_find_replace import apply_occurrences
    from twobyteasr.exports.studio_subtitle_export import layer_cues
    p=make_project(['アリスが','来た'])
    for cue,text in zip(p.cues,['阿莉丝','来了']):
        st.set_manual(p,cue.id,text)
        cue.appearance_override['translation_group']=dict(id='stable-parent',text='阿莉丝来了',original_source='旧的原文不得拿来翻译')
    p.studio_state['bilingual']={'mode':'bilingual'}
    entries=text_entries(p,mode='translation')
    assert all(e.text=='阿莉丝来了' and e.source_text=='アリスが\n来た' for e in entries)
    first=entries[0]
    hits=find_occurrences(p,[first.target.cue_id],'阿莉丝','爱丽丝',entries=[first])
    stack=QUndoStack();page=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=stack),_changed=lambda:None)
    assert apply_occurrences(page,hits,title='校对译文')==(1,1)
    assert 'translation_group' not in p.cues[0].appearance_override
    assert p.cues[1].appearance_override['translation_group']['text']=='阿莉丝来了'
    assert [c.text for c in p.cues]==['アリスが','来た']
    shown,_,_=layer_cues(p.cues,st.translation_view(p),'translation')
    assert [c.text for c in shown]==['爱丽丝来了','阿莉丝来了']
    stack.undo();assert p.cues[0].appearance_override['translation_group']['text']=='阿莉丝来了'
    stack.redo();assert text_entries(p,mode='translation')[0].text=='爱丽丝来了'


def test_ai_translation_snapshot_drops_only_its_own_stale_group_display():
    from twobyteasr.studio.studio_bilingual import ApplyTranslationSnapshotCommand
    p=project();st.set_manual(p,'c0','旧译文')
    p.cues[0].appearance_override['translation_group']=dict(id='parent',text='更旧的显示文本')
    before=st.snapshot(p);st.set_manual(p,'c0','爱丽丝来了');after=st.snapshot(p)
    st.restore_snapshot(p,before)
    stack=QUndoStack();stack.push(ApplyTranslationSnapshotCommand(p,before,after,['c0']))
    assert 'translation_group' not in p.cues[0].appearance_override
    stack.undo();assert p.cues[0].appearance_override['translation_group']['text']=='更旧的显示文本'
    stack.redo();assert st.records_of(p)['c0']['text']=='爱丽丝来了'


def test_midflight_term_edit_discards_only_affected_results():
    p=project(); result=run(st.translation_source(p))
    p.generation_metadata[KEY]['libraries'][0]['terms'][0]['target']='艾丽丝'
    st.apply_translation_result(p,result)
    assert result.discarded['c0']=='terminology_changed'
    assert 'c10' in result.translations and 'c0' not in st.records_of(p)


def test_manual_translation_is_protected_after_source_edit_and_candidate_is_reviewable():
    p=project(); st.set_manual(p,'c0','手工保留')
    p.cues[0].text='アリスがまた来た'
    assert st.cue_status(p,'c0')=='needs_update'
    result=run(p,ids=['c0']); st.apply_translation_result(p,result)
    assert st.records_of(p)['c0']['text']=='手工保留' and 'c0' in result.suggestions


def test_settings_undo_does_not_overwrite_source_selection_or_concurrent_translation():
    from twobyteasr.glossary.translation_terms_ui import TerminologySettingsCommand
    p=project(); stack=QUndoStack(); before=copy.deepcopy(p.generation_metadata[KEY])
    changed=copy.deepcopy(before); changed['enabled']=False
    stack.push(TerminologySettingsCommand(p,policy=changed))
    st.set_manual(p,'c0','新手工译文')
    stack.undo()
    assert p.glossary_ids==['original-library'] and p.generation_metadata[KEY]==before
    assert st.records_of(p)['c0']['text']=='新手工译文'
    stack.redo(); assert not p.generation_metadata[KEY]['enabled']


def test_automatic_recognition_translation_has_the_same_request_terms(monkeypatch):
    from twobyteasr.subtitle_rules import recognition_translation as rt
    from twobyteasr.recognition.run_context import RuntimeContext
    p=project(); provider=Provider()
    monkeypatch.setattr(rt,'load_cache',lambda:{})
    monkeypatch.setattr(rt,'save_cache',lambda cache:None)
    ctx=RuntimeContext(subtitle_output='bilingual', task_language='ja', translation_terminology=policy())
    legacy=SimpleNamespace(RUNTIME_SETTINGS={}, record_run_event=lambda *a,**kw:None,add_review_item=lambda *a,**kw:None)
    data=rt.translate_runtime_cues([SimpleNamespace(start=0,end=1,text='アリスが来た',speaker='S01')],ctx,legacy,provider=provider)
    assert provider.calls[0]['payload']['translation_terminology'][0]['target']=='爱丽丝'
    assert data[KEY]['enabled']


def test_translation_review_requests_reference_and_mapping_but_never_source_glossary(monkeypatch):
    from twobyteasr.glossary.translation_review import preview_language_correction
    from twobyteasr.glossary.terminology import snapshot_from_pairs
    from twobyteasr.studio.subtitle_text_targets import text_entries
    from twobyteasr.recognition.service import CancellationToken
    p=project(); st.set_manual(p,'c0','阿莉丝来了')
    captured=[]
    class Review:
        def complete(self,messages,**kwargs):
            body=json.loads(messages[1]['content']); captured.append(body)
            row=body['targets'][0]
            return {'changes':[dict(target_id=row['target_id'],original=row['target_text'],replacement='爱丽丝来了',reason='按用户译名') ]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**kw:Review())
    entries=[e for e in text_entries(p,mode='translation') if e.target.cue_id=='c0']
    result=preview_language_correction(p,entries,snapshot_from_pairs([('阿莉丝','来源词不应写入译文')]),{},token=CancellationToken())
    assert captured[0]['targets'][0]['source_reference']=='アリヌが来た'
    assert captured[0]['targets'][0]['translation_terminology'][0]['target']=='爱丽丝'
    assert not captured[0]['same_language_terms'] and result.hits
    assert p.cues[0].text=='アリヌが来た' and st.records_of(p)['c0']['text']=='阿莉丝来了'


def test_localized_review_reasons_remain_plain_persistable_data():
    import marshal
    from twobyteasr.i18n import tr
    from twobyteasr.glossary.proofread_retention import row_record
    row=dict(cue_id='stable',origin='旧名',base='旧名',issues=[dict(kind='term',span=(0,2),
        original='旧名',replacement='新名',reason=tr('用户术语库'),options=(tr('新名'),))])
    record=row_record(row)
    assert type(record['issues'][0]['reason']) is str
    assert marshal.loads(marshal.dumps(record))==record


def test_real_library_editor_can_disable_translation_without_changing_source_selection(tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget, QDialogButtonBox
    from twobyteasr.glossary.translation_terms_ui import project_widget, TranslationTermsDialog
    app=QApplication.instance() or QApplication([])
    p=project();stack=QUndoStack();parent=QWidget()
    page=SimpleNamespace(project=p,session=SimpleNamespace(project=p,undo_stack=stack),_changed=lambda:None)
    widget=project_widget(page,parent)
    def edit():
        dialog=QApplication.activeModalWidget()
        assert isinstance(dialog,TranslationTermsDialog)
        assert dialog.source.currentData()=='ja' and dialog.target.currentData()=='zh-Hans'
        dialog.enabled.setChecked(False)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
    QTimer.singleShot(20,edit);widget.edit()
    assert not p.generation_metadata[KEY]['enabled'] and p.glossary_ids==['original-library']
    assert p.generation_metadata[KEY]['selected_ids']==['jp'] and stack.count()==1
    loaded=load_project(save_project(p,tmp_path/'disabled.2byteproj'))
    assert loaded.generation_metadata[KEY]==p.generation_metadata[KEY]
    stack.undo();assert p.generation_metadata[KEY]['enabled']
    stack.redo();assert not p.generation_metadata[KEY]['enabled']
    parent.close();parent.deleteLater();app.processEvents()


def test_run_options_freeze_independent_term_configuration():
    from twobyteasr.recognition.service import RunOptions
    value=policy();settings={'glossary':{KEY:value}}
    legacy=SimpleNamespace(canonicalize_runtime_game_name=lambda s:s,runtime_game_identity=lambda s:s,RUNTIME_SETTINGS=settings)
    options=RunOptions(settings_snapshot_json=json.dumps(settings), source_glossary_selection=('original-library',),
                       enable_domain_terms=False)
    runtime=options.create_runtime_context(legacy)
    value['libraries'][0]['terms'][0]['target']='后来改动'
    assert runtime.translation_terminology['libraries'][0]['terms'][0]['target']=='爱丽丝'
    assert runtime.selected_source_glossary_ids==['original-library'] and runtime.enabled_glossary_ids==[]


def test_changing_translation_library_retains_source_proposals_and_limits_rematching():
    from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage
    source=dict(cue_id='source-id',target=SimpleNamespace(layer='original'),issues=[dict(kind='ai',checked=False)])
    translated=dict(cue_id='translation-id',target=SimpleNamespace(layer='translation'),issues=[dict(kind='ai',checked=False)])
    calls=[]
    page=SimpleNamespace(_rows=[source,translated],_generation=1,_cancel_worker=lambda:None,_read_snapshot=lambda:None,
        term_conflicts_button=SimpleNamespace(hide=lambda:None),
        _apply_filter=lambda:None,_schedule_local_checks=lambda:None,_run=lambda ai,ids:calls.append(ids))
    GlossaryProofreadPage._reset_library_proposals(page,layers={'translation'})
    assert source['issues'] and not translated['issues'] and calls==[['translation-id']]


def test_home_translation_library_survives_real_settings_save_and_reload(tmp_path):
    from twobyteasr.storage.settings import DEFAULT_SETTINGS,save_runtime_settings,load_runtime_settings
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    settings['glossary'].update(enabled_glossary_ids=['original-library'],enable_domain_terms=True)
    settings['glossary'][KEY]=policy()
    save_runtime_settings(settings,project_root=tmp_path)
    loaded,_,_=load_runtime_settings(project_root=tmp_path)
    assert loaded['glossary'][KEY]==policy()
    assert loaded['glossary']['enabled_glossary_ids']==['original-library']


def test_conflicting_ai_review_is_visible_without_a_write_or_adoptable_wrong_name(monkeypatch):
    from twobyteasr.glossary.translation_review import preview_language_correction
    from twobyteasr.glossary.terminology import GlossarySnapshot
    from twobyteasr.studio.subtitle_text_targets import text_entries
    from twobyteasr.recognition.service import CancellationToken
    p=project();st.set_manual(p,'c0','爱丽丝来了')
    class Provider:
        def complete(self,messages,**kwargs):
            row=json.loads(messages[-1]['content'])['targets'][0]
            return {'changes':[dict(target_id=row['target_id'],original=row['target_text'],replacement='阿莉丝来了',reason='其他参考译法')]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**kw:Provider())
    entries=[e for e in text_entries(p,mode='translation') if e.target.cue_id=='c0']
    result=preview_language_correction(p,entries,GlossarySnapshot(),{},token=CancellationToken())
    assert not result.hits and result.receipt['empty_state']=='needs_confirmation'
    conflict=result.receipt['terminology_conflicts'][0]
    assert conflict['candidate']=='阿莉丝来了' and conflict['required'][0]['target']=='爱丽丝'
    assert st.records_of(p)['c0']['text']=='爱丽丝来了'


def test_inflight_language_direction_change_is_rejected_even_without_a_glossary():
    p=make_project(['Aliceが来た'])
    provider=FakeProvider(lambda data,n:{'items':[dict(id=row['id'],translation='爱丽丝来了') for row in data['lines'] if row['translate']]})
    result=run(st.translation_source(p),provider,ids=['c0'])
    assert result.translations
    p.generation_metadata['language']={'code':'en'}
    st.apply_translation_result(p,result)
    assert result.discarded['c0']=='source_language_changed' and not st.records_of(p)


def test_translation_source_scope_excludes_known_imported_translation_tracks():
    p=make_project(['アリスが来た','保留独立译文','アリスを見た'])
    p.generation_metadata[KEY]=policy()
    p.generation_metadata['subtitle_imports']={'tracks':{'S01':{'role':'translation','language':'zh-Hans'}}}
    assert {cue.id for cue in st.translation_source(p).cues}=={'c0','c2'}
    result=run(p);st.apply_translation_result(p,result)
    assert set(result.translations)=={'c0','c2'} and p.cues[1].text=='保留独立译文'
    assert 'c1' not in st.records_of(p) and sum(st.status_counts(p).values())==2


def test_review_direction_comes_from_the_actual_linked_source_track(monkeypatch):
    from twobyteasr.studio.subtitle_text_targets import text_entries
    from twobyteasr.glossary.translation_review import preview_language_correction
    from twobyteasr.glossary.terminology import GlossarySnapshot
    from twobyteasr.recognition.service import CancellationToken
    p=make_project(['Alice arrived','阿莉丝来了'])
    p.generation_metadata[KEY]=policy()
    p.generation_metadata[KEY]['libraries'][0]['terms'][0]['source']='Alice'
    p.generation_metadata['subtitle_imports']={'tracks':{
        'S00':{'role':'original','language':'en'},'S01':{'role':'translation','language':'zh-Hans'}},
        'cues':{'c1':{'association':{'project_id':p.project_id,'cue_id':'c0'}}}}
    entries=text_entries(p,mode='translation',tracks={'S01'})
    assert len(entries)==1 and entries[0].source_language=='en' and entries[0].source_text=='Alice arrived'
    bodies=[]
    class Provider:
        def complete(self,messages,**kwargs):
            bodies.append(json.loads(messages[-1]['content']));return {'changes':[]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**kw:Provider())
    preview_language_correction(p,entries,GlossarySnapshot(),{},token=CancellationToken())
    assert bodies[0]['targets'][0]['source_language']=='en'
    assert bodies[0]['targets'][0]['translation_terminology']==[]
