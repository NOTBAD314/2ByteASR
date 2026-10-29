"""ASR production entry: bounded batches, explicit evidence and reusable success."""
import copy
import json
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_stage9_cache_and_budget import context
from twobyteasr.glossary import domain_terms
from twobyteasr.subtitle_rules import polishing
from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.providers.provider_input_budget import POLICIES, prepare_input, RetryBudget, retry_delay
from twobyteasr.recognition.transcript_data import SpeechSegment


def cue(i,text):
    return SpeechSegment(segment_id=i,start=i*1.25,end=i*1.25+1,text=text,
        confidence=.85,words=[],speaker=f'S{i%2+1:02d}',moss_text=text,firered_text=text,qwen_asr_text=text)


def call(rows,cache=None):
    return polishing.call_correction_api(rows,[], '只读前文','只读后文','合成夹具','原神',[],[],[],
                                        _cache_context=cache,batch_index=1,batch_total=1)


def singleton_budget(monkeypatch,rows):
    messages=polishing.call_correction_api([rows[0]],[],'只读前文','只读后文','合成夹具','原神',[],[],[],_messages_only=True)
    _,report=prepare_input(messages,max_tokens=4096,operation='polish')
    monkeypatch.setitem(POLICIES,'polish',replace(POLICIES['polish'],input_tokens=report['input_token_estimate']+80))


def test_complete_request_splits_and_reuses_only_successful_children(context,monkeypatch):
    _,owner,cache=context
    rows=[cue(i,'这段中文测验包含引号“名字”和路径 C:\\目录 空格\\。'+str(i)*320) for i in (101,102,103)]
    original=copy.deepcopy(rows)
    singleton_budget(monkeypatch,rows)
    calls=[]
    failing={102}
    def complete(messages,**kwargs):
        body=json.loads(messages[1]['content'])
        ids=[item['id'] for item in body['cues']]
        calls.append(ids)
        assert len(ids)==1 and 'read-only' in body['context_access']
        assert body['cues'][0]['primary_text']==original[ids[0]-101].text
        prepare_input(messages,max_tokens=kwargs['max_tokens'],operation='polish')
        if ids[0] in failing:
            raise AIProviderError('explicit permission denial',category='permission_denied')
        return json.dumps({'checked_ids':[item['id'] for item in json.loads(messages[1]['content'])['cues']],'cues':[]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    first=call(rows,cache)
    assert first.succeeded=={101,103} and first.failures=={102:'permission_denied'}
    assert calls==[[101],[102],[103]]
    owner.review_items.clear()
    failing.clear()
    second=call(rows,cache)
    assert second.succeeded=={101,102,103} and not second.failures
    assert calls==[[101],[102],[103],[102]]
    assert set(second)=={101,102,103}
    assert [(x.segment_id,x.text,x.speaker,x.start,x.end) for x in rows]==[
        (x.segment_id,x.text,x.speaker,x.start,x.end) for x in original]


def test_single_abnormal_cue_does_not_drop_neighbors_or_repeat(context,monkeypatch):
    rows=[cue(7,'普通句子'),cue(8,'超长异常正文'*18000),cue(9,'最后一句')]
    calls=[]
    def complete(messages,**kwargs):
        calls.extend(item['id'] for item in json.loads(messages[1]['content'])['cues'])
        return json.dumps({'checked_ids':[item['id'] for item in json.loads(messages[1]['content'])['cues']],'cues':[]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    result=call(rows)
    assert calls==[7,9] and result.failures=={8:'request_too_large'}
    assert set(result)=={7,8,9} and result[8]==rows[1].text


@pytest.mark.parametrize('ids',[[999],[11,11]])
def test_unknown_or_duplicate_edit_ids_are_rejected(context,monkeypatch,ids):
    attempts=[]
    def complete(*a,**k):
        attempts.append(1)
        return json.dumps({'checked_ids':[11],'cues':[{'id':i,'text':'越权内容'} for i in ids]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    monkeypatch.setattr(polishing,'API_RETRIES',1)
    result=call([cue(11,'原文')])
    assert result=={11:'原文'} and result.failures and len(attempts)==1


def term_fixture(monkeypatch,context,response,evidence=True):
    _,owner,_=context
    owner.provider_snapshot=replace(owner.provider_snapshot,kind='cli',transport='grok_cli',provider='grok_oauth')
    calls=[]
    def complete(messages,**kwargs):
        calls.append(messages)
        if evidence:
            kwargs['request_diagnostics']['search_evidence']=[{'tool':'web_search','urls':['https://example.org/term']}]
        return json.dumps(response,ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    monkeypatch.setattr(domain_terms,'persist_learned_mappings',lambda *a:None)
    return owner,calls


@pytest.mark.parametrize('response,state,checked',[
    ({'mappings':[]},'failed',0),
    ({'mappings':[],'checked_ids':[1,2],'unchecked_ids':[]},'success',2),
    ({'mappings':[],'checked_ids':[1],'unchecked_ids':[2]},'partial',1),
])
def test_empty_mapping_is_not_proof_of_full_verification(context,monkeypatch,response,state,checked):
    owner,calls=term_fixture(monkeypatch,context,response)
    result=domain_terms.discover_global_domain_term_mappings([cue(1,'这是新名字'),cue(2,'有待核实')],'原神',[],['枫原万叶'],[])
    assert result.status==state and owner.terminology_status['verified_count']==checked and len(calls)==1


def test_prose_claiming_search_without_tool_evidence_fails_once(context,monkeypatch):
    owner,calls=term_fixture(monkeypatch,context,{'checked_ids':[1],'mappings':[]},evidence=False)
    result=domain_terms.discover_global_domain_term_mappings([cue(1,'这是候选名字')],'原神',[],['枫原万叶'],[])
    assert result.status=='failed' and not result.checked_ids and len(calls)==1
    assert owner.terminology_status['failure_categories']=={'search_evidence_missing':1}


def test_many_candidates_share_complete_evidence_without_repeated_contexts(context,monkeypatch):
    terms=[{'term':f'角色{i}号','moss_segment_count':2} for i in range(80)]
    text='，'.join(x['term'] for x in terms)+'。这些名称尚未确定。'
    rows=[cue(1,text),cue(2,text)]
    owner,calls=term_fixture(monkeypatch,context,{'checked_ids':[1,2],'unchecked_ids':[],'mappings':[]})
    result=domain_terms.discover_global_domain_term_mappings(rows,'原神',[],['阿蕾奇诺'],terms)
    assert result.status=='success' and len(calls)==1
    messages=calls[0]
    prepare_input(messages,max_tokens=4096,operation='domain_terms')
    body=json.loads(messages[1]['content'])
    assert len(body['repeated_moss_term_candidates'])==80
    assert [r['primary_text'] for r in body['asr_disputes']]==[domain_terms.clean_subtitle_text(text)]*2
    assert all('contexts' not in x and x['context_ids']==[1,2] for x in body['repeated_moss_term_candidates'])
    assert body['verified_game_terms']==['阿蕾奇诺']


@pytest.mark.parametrize('checked',[None,[],[11,11],[12],[True]])
def test_missing_or_invalid_coverage_receipt_never_counts_as_success(context,monkeypatch,checked):
    def complete(*a,**k):
        return json.dumps({'checked_ids':checked,'cues':[]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    monkeypatch.setattr(polishing,'API_RETRIES',1)
    result=call([cue(11,'未检查正文')])
    assert not result.succeeded and result.failures and result[11]=='未检查正文'


def test_candidate_dedup_retains_unlisted_name_and_contextual_fragments():
    rows=[cue(i,s) for i,s in enumerate(['甲这是乙','丙这是丁','戊这是己','洛琪娜的技能还没确认'],1)]
    values=domain_terms.normalize_term_candidates([
        {'term':'这是','moss_segment_count':2},{'term':'这是','moss_segment_count':1},
        {'term':'洛琪娜','moss_segment_count':1},{'term':'技能','moss_segment_count':1}],rows)
    by_term={x['term']:x for x in values}
    assert by_term['这是']['moss_segment_count']==3 and by_term['这是']['verification_priority']=='low'
    assert by_term['洛琪娜']['verification_priority']=='normal' and '技能' in by_term
    assert all(x['read_only'] for value in values for x in value['contexts'])


def test_shared_retry_budget_is_atomic_and_deterministic_failures_do_not_sleep():
    from concurrent.futures import ThreadPoolExecutor
    budget=RetryBudget(2)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _:budget.take(),range(12)))==2
    for category in ('transport_length','request_too_large','permission_denied','authentication_required','cancelled'):
        assert retry_delay(AIProviderError('fixture',category=category),1) is None


def test_late_result_cannot_write_stage_cache(context):
    from twobyteasr.recognition.cache import run_cached_stage
    from twobyteasr.recognition.service import CancellationToken,CancelledError
    from pathlib import Path
    _,owner,cache=context
    owner.cancellation_token=CancellationToken()
    def run():
        owner.cancellation_token.cancel()
        return {'late':True}
    with pytest.raises(CancelledError):
        run_cached_stage('polished',cache,run)
    assert not (Path(cache['cache_dir'])/'polished.json').exists()


def test_completion_summary_exposes_partial_success_and_retry():
    from twobyteasr.app.main_ui_helpers import polishing_completion_details
    lines,retry=polishing_completion_details({'polishing_summary':{'success_batches':4,'success_cues':80,
        'fallback_batches':2,'fallback_cues':40,'failure_categories':{'transport_length':40}},
        'terminology_summary':{'status':'partial','verified_count':60,'unverified_count':20,
            'capability_available':True,'retryable':True,'evidence_verified':True,
            'search_evidence':[{'tool':'web_search','urls':['https://example.test/terms']}]}})
    assert retry and '4 批 / 80 条' in lines[0] and '2 批 / 40 条' in lines[0]
    assert any('联网核验部分完成' in line for line in lines)


def test_grouping_final_request_packing_reuses_successful_children(context,monkeypatch):
    from twobyteasr.subtitle_rules import grouping
    _,owner,cache=context
    rows=[cue(i,'测验正文'+str(i)) for i in (21,22,23)]
    for row in rows:row.speaker='S01'
    messages=grouping.call_grouping_api([rows[0]],_messages_only=True)
    _,report=prepare_input(messages,schema=grouping.GROUPING_SCHEMA,max_tokens=4096,operation='group')
    monkeypatch.setitem(POLICIES,'group',replace(POLICIES['group'],input_tokens=report['input_token_estimate']+1))
    calls=[];failed={22}
    def complete(messages,**kwargs):
        prepare_input(messages,schema=kwargs['json_schema'],max_tokens=4096,operation='group')
        body=json.loads(messages[1]['content']);ids=[r['id'] for r in body['segments']]
        calls.append(ids)
        if ids[0] in failed:raise AIProviderError('denied',category='permission_denied')
        return json.dumps({'boundaries':[body['total_length']]})
    monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    first=grouping.call_grouping_api(rows,_cache_context=cache)
    assert not first.validated and calls==[[21],[22],[23]]
    failed.clear();owner.review_items.clear()
    second=grouping.call_grouping_api(rows,_cache_context=cache)
    assert second.validated and calls==[[21],[22],[23],[22]]
    assert ''.join(x.text for x in second)==''.join(x.text for x in rows)
