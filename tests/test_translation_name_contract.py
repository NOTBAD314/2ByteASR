"""Cue-scoped terminology regression through the normal translation API."""
import copy
import json
from types import SimpleNamespace

from tests.test_subtitle_translation import make_project, FakeProvider
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.glossary import translation_terms as terms


def policy(source='エイミスさん', target='爱弥斯小姐', **row):
    return dict(enabled=True, selected_ids=['names'], libraries=[dict(id='names', name='角色译名',
        source_language='ja', target_language='zh-Hans', terms=[dict(source=source, target=target, **row)])])


def test_missing_name_retries_only_bad_cue_with_required_names():
    project = make_project(['エイミスさん、こんにちは', 'こんにちは'])
    project.generation_metadata[terms.KEY] = policy()
    def respond(payload, number):
        if number == 2:
            assert payload['output_ids'] == ['c0']
            hint = payload['validation_repairs']['items'][0]
            assert hint['source'] == project.cues[0].text
            assert hint['rejected_translation'] == '小姐，你好'
            assert hint['required_terms'][0]['target'] == '爱弥斯小姐'
        return {'items': [dict(id=identity, translation=(('小姐，你好' if number == 1 else '爱弥斯小姐，你好')
            if identity == 'c0' else '你好')) for identity in payload['output_ids']]}
    provider = FakeProvider(respond)
    events, cache = [], {}
    original = [(cue.text, cue.start_ms, cue.end_ms) for cue in project.cues]
    result = st.translate(project, None, provider, target='zh-Hans', event=events.append, cache=cache)
    assert len(provider.calls) == 2 and not result.failed
    assert provider.calls[0]['payload']['required_terms_by_id']['c1'] == []
    assert all(value['text'] != '小姐，你好' for value in cache.values())
    st.apply_translation_result(project, result)
    assert st.translation_view(project)['c0']['text'] == '爱弥斯小姐，你好'
    assert st.translation_view(project)['c1']['text'] == '你好'
    assert original == [(cue.text, cue.start_ms, cue.end_ms) for cue in project.cues]
    assert any(event['event'] == 'writeback' for event in events)


def test_inline_pairs_wrong_name_and_cache_recovery_are_validated():
    project = make_project(['エイミスさん、こんにちは'])
    project.generation_metadata['translation_glossary'] = [['エイミスさん', '爱弥斯小姐']]
    provider = FakeProvider(lambda payload, number: {'items': [{'id': 'c0', 'translation': '艾米小姐，你好'}]})
    cache = {}
    result = st.translate(project, None, provider, target='zh-Hans', cache=cache)
    assert result.failed['c0'].startswith('terminology_mismatch:')
    assert not cache and len(provider.calls) == 2
    assert not result.translations


def test_unicode_aliases_longest_and_target_aliases():
    value = policy(source='Amy Smith', aliases=['Ａｍｙ　Ｓｍｉｔｈ'], target_aliases=['爱弥斯女士'])
    value['libraries'][0]['terms'].append(dict(source='Amy', target='艾米'))
    hits = terms.relevant(value, 'ja', 'zh-Hans', 'Ａｍｙ  Ｓｍｉｔｈ！')
    assert len(hits) == 1 and hits[0]['target'] == '爱弥斯小姐'
    assert not terms.violations('Ａｍｙ Ｓｍｉｔｈ', '爱弥斯女士，你好', hits)
    assert not terms.review_warnings('爱弥斯女士，你好', hits)
    assert terms.violations('Ａｍｙ Ｓｍｉｔｈ', '小姐，你好', hits)
    assert not terms.relevant(value, 'ja', 'zh-Hans', 'Amyloid')
    cjk = policy(source='爱弥斯小姐')
    assert terms.relevant(cjk, 'ja', 'zh-Hans', '爱 弥 斯 小姐')
    assert not terms.relevant(cjk, 'en', 'zh-Hans', '爱弥斯小姐')
    value['enabled'] = False
    effective = terms.effective_policy(value, [('other', '其他')], 'ja', 'zh-Hans')
    assert not terms.relevant(effective, 'ja', 'zh-Hans', 'Amy Smith')


def test_context_terms_never_become_current_cue_requirements_or_displace_them():
    project = make_project(['エイミスさん', 'こんにちは'])
    source = st.translation_source(project)
    batch = next(iter(st.plan_batches(source, ['c1'])))
    frozen = terms.freeze(policy())
    body = json.loads(st.build_messages(batch, terminology=frozen)[-1]['content'])
    assert not body.get('translation_terminology')
    assert body['context_terminology'] and not body['required_terms_by_id']['c1']
    pairs = [('context' + str(i), '背景' + str(i)) for i in range(100)] + [('エイミスさん', '爱弥斯小姐')]
    project = make_project([' '.join(a for a, _ in pairs[:-1]), 'エイミスさん'])
    batch = next(iter(st.plan_batches(st.translation_source(project), ['c1'])))
    body = json.loads(st.build_messages(batch, glossary_pairs=pairs)[-1]['content'])
    assert any('爱弥斯小姐' in row.values() for row in body['glossary'])


def test_new_policy_rechecks_only_invalid_ai_and_protects_manual():
    project = make_project(['エイミスさん、こんにちは', 'こんにちは', 'エイミスさん、こんばんは'])
    provider = FakeProvider(lambda payload, number: {'items': [dict(id=i, translation='小姐，你好' if i != 'c1' else '你好') for i in payload['output_ids']]})
    st.apply_translation_result(project, st.translate(project, None, provider, target='zh-Hans'))
    st.set_manual(project, 'c2', '我的手工译文', target='zh-Hans')
    project.generation_metadata[terms.KEY] = policy()
    states = st.statuses(project)
    assert states == {'c0': st.NEEDS_UPDATE, 'c1': st.DONE, 'c2': st.MANUAL}
    assert st.ids_with_status(project, [st.NEEDS_UPDATE]) == ['c0']
    old = copy.deepcopy(st.records_of(project)['c0'])
    result = st.translate(project, ['c0'], FakeProvider(lambda p, n: {'items':[dict(id='c0', translation='小姐，你好')]}), target='zh-Hans')
    st.apply_translation_result(project, result)
    assert st.records_of(project)['c0']['text'] == old['text']
    assert 'terminology_mismatch' in st.records_of(project)['c0']['last_error']


def test_new_library_during_task_discards_late_unbound_results():
    project = make_project(['エイミスさん、こんにちは'])
    result = st.translate(project, None, FakeProvider(lambda p,n: {'items':[dict(id='c0', translation='小姐，你好')]}), target='zh-Hans')
    project.generation_metadata[terms.KEY] = policy()
    st.apply_translation_result(project, result)
    assert result.discarded == {'c0':'terminology_changed'}
    assert not st.records_of(project)


def test_automatic_translation_and_parallel_batches_use_selected_snapshot(monkeypatch):
    from twobyteasr.subtitle_rules import recognition_translation as automatic
    context=SimpleNamespace(subtitle_output='bilingual',task_language='ja',translation_script='zh-Hans',
        translation_terminology=policy(),cancellation_token=None,game_name='测试',asr_settings_snapshot={})
    cues=[SimpleNamespace(cue_id=i,start=i,end=i+.9,text='エイミスさん、こんにちは',speaker='S00') for i in range(4)]
    provider=FakeProvider(lambda body,n:{'items':[dict(id=i,translation='爱弥斯小姐，你好') for i in body['output_ids']]})
    events=[]
    legacy=SimpleNamespace(PARALLEL_CLOUD_BATCHES=False,record_run_event=lambda event,**fields:events.append((event,fields)),add_review_item=lambda *a,**k:None)
    monkeypatch.setattr(automatic,'load_cache',lambda:{})
    monkeypatch.setattr(automatic,'save_cache',lambda value:None)
    metadata=automatic.translate_runtime_cues(cues,context,legacy,provider=provider)
    assert metadata[terms.KEY]['selected_ids']==['names']
    assert all(value=='爱弥斯小姐，你好' for value in metadata['translations'].values())
    assert provider.calls[0]['payload']['translation_terminology'][0]['target']=='爱弥斯小姐'
    project=make_project(['エイミスさん、こんにちは']*8)
    project.generation_metadata[terms.KEY]=policy()
    provider=FakeProvider(lambda body,n:{'items':[dict(id=i,translation='爱弥斯小姐，你好') for i in body['output_ids']]})
    result=st.translate(project,None,provider,target='zh-Hans',workers=3,max_items=2)
    assert len(result.translations)==8 and len(provider.calls)==4
    assert all(call['payload']['required_terms_by_id'] for call in provider.calls)


def test_parallel_translation_freezes_policy_and_rejects_live_change(monkeypatch):
    import threading
    import contextlib
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.recognition.translation_overlap import TranslationTask
    from twobyteasr.subtitle_rules import recognition_translation
    entered,released=threading.Event(),threading.Event();observed=[]
    def translate(cues,context,legacy):
        observed.append(copy.deepcopy(context.translation_terminology));entered.set()
        if not released.wait(3):raise TimeoutError('test release')
        return {'snapshot':context.translation_terminology}
    monkeypatch.setattr(recognition_translation,'translate_runtime_cues',translate)
    context=RuntimeContext(task_language='ja',subtitle_output='bilingual',translation_terminology=policy())
    legacy=SimpleNamespace(capture_review_items=lambda:contextlib.nullcontext([]),extend_review_items=lambda items:None,record_run_event=lambda *a,**k:None)
    cues=[SimpleNamespace(cue_id=1,text='エイミスさん',speaker='S00',start=0,end=1)]
    with activate_runtime_context(context):
        task=TranslationTask(cues,context,legacy)
        try:
            assert entered.wait(3)
            context.translation_terminology=policy(target='新译名')
            released.set()
            assert task.result(cues) is None
            assert observed[0]['libraries'][0]['terms'][0]['target']=='爱弥斯小姐'
        finally:
            released.set();task.close()


def test_context_notes_cannot_silently_waive_name_validation():
    project=make_project(['エイミスさん、こんにちは'])
    project.generation_metadata[terms.KEY]=policy(context='游戏角色名，称呼人物时使用')
    provider=FakeProvider(lambda body,n:{'items':[dict(id='c0',translation='小姐，你好' if n==1 else '爱弥斯小姐，你好')]})
    cache={}
    result=st.translate(project,None,provider,target='zh-Hans',cache=cache)
    assert len(provider.calls)==2 and result.translations['c0'].text=='爱弥斯小姐，你好'
    assert all(value['text']!='小姐，你好' for value in cache.values())
    st.apply_translation_result(project,result)
    project.generation_metadata[terms.KEY]['libraries'][0]['terms'][0]['context']='仅人物称呼，更新说明'
    assert st.statuses(project)['c0']==st.DONE
    ambiguous=policy(source='Apple',target='苹果公司',context='仅公司名称')
    ambiguous['libraries'][0]['terms'].append(dict(source='Apple',target='苹果',context='仅水果'))
    hits=terms.relevant(ambiguous,'ja','zh-Hans','Apple')
    assert not terms.validation_issues('Apple','我吃了一个苹果',hits)
    assert terms.validation_issues('Apple','我吃了一个水果',hits)
    assert not terms.relevant(ambiguous,'ja','zh-Hans','pineapple')


def test_studio_pending_scope_uses_edited_inline_snapshot_before_selection(monkeypatch):
    from PySide6.QtWidgets import QApplication,QLabel
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    from twobyteasr.providers import llm_config
    app=QApplication.instance() or QApplication([])
    project=make_project(['エイミスさん、こんにちは'])
    old=[['エイミスさん','旧名']]
    project.generation_metadata['translation_glossary']=copy.deepcopy(old)
    provider=FakeProvider(lambda p,n:{'items':[dict(id='c0',translation='旧名，你好')]})
    st.apply_translation_result(project,st.translate(project,None,provider,target='zh-Hans'))
    assert st.statuses(project)['c0']==st.DONE
    selected=[]
    def scope(candidate=None):
        ids=st.ids_with_status(candidate or project,{st.UNTRANSLATED,st.FAILED,st.NEEDS_UPDATE},target='zh-Hans')
        selected.extend(ids);return ids
    dialog=SimpleNamespace(_thread=None,_owns_project=lambda:True,_scope_ids=scope,_target=lambda:'zh-Hans',
        project=project,status=QLabel(),_describe_service=lambda:None,settings_button=SimpleNamespace(setFocus=lambda:None),
        glossary=SimpleNamespace(toPlainText=lambda:'エイミスさん = 爱弥斯小姐'))
    monkeypatch.setattr(llm_config,'text_ai_key_missing',lambda *a,**k:True)
    SubtitleTranslationDialog._start(dialog)
    assert selected==['c0']
    assert project.generation_metadata['translation_glossary']==old
    assert st.records_of(project)['c0']['text']=='旧名，你好'
