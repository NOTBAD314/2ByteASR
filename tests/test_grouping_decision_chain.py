"""Independent semantic expectations from job 10ab and paired counterexamples."""
import copy
import hashlib
import json
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality, quality_for_segments
from twobyteasr.subtitle_rules.grouping_quality_request import QualityRetryBudget, retry_quality_windows
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot

FIXTURE = json.loads((Path(__file__).parent/'fixtures/grouping_contract/luoke_10ab.json').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh',enable_domain_terms=False),legacy=core):
        yield


def make_rows(parts, speakers=None):
    return [core.SpeechSegment(i+1,i*1.5,(i+1)*1.5,text,.9,[],speaker=(speakers or ['A']*len(parts))[i])
            for i,text in enumerate(parts)]


@pytest.mark.parametrize('number',range(4))
def test_frozen_main_response_hash_and_source_identity(number):
    batch=FIXTURE['batches'][number]
    raw=json.dumps({'boundaries':batch['model_boundaries']},separators=(',',':'))
    assert hashlib.sha256(raw.encode()).hexdigest() == batch['raw_response_sha256']
    assert ''.join(s['text'] for s in FIXTURE['segments'] if s['segment_id'] in batch['source_segment_ids']) == batch['source_text']


@pytest.mark.parametrize('workers,reverse',[(1,False),(4,True)])
def test_actual_grouping_entry_known_bad_edges_and_independent_short_answers(workers,reverse):
    from twobyteasr.acceptance.grouping_decision_audit import replay
    result,_,_=replay(FIXTURE,workers=workers,reverse_completion=reverse)
    assert result['passed'],result['checks']
    assert sum(e['state']=='unchanged_with_violations' for e in result['events'] if e['event']=='grouping_model_quality') == 4
    assert not any('failed_constraints' in r['body'] for r in result['requests'])


@pytest.mark.parametrize('parts',[
    ['霹雳滴滴真的能够去斩掉','满状态的一个寒音蛇吗'],
    ['因热爱并肩','让我们把最热烈的掌声送给他们'],
])
def test_good_complete_expressions_survive_neighbourhood_repair(parts):
    q=quality_for_segments(make_rows(parts))
    cuts=[len(parts[0]),sum(map(len,parts))]
    assert q.repair(cuts)[0] == cuts


@pytest.mark.parametrize('parts,speakers',[
    (['我们准备好了。','去吗？'],None),
    (['这一轮打完了。','舒服了'],None),
    (['好','是的'],['A','B']),
])
def test_contextually_independent_short_answers_are_not_banned(parts,speakers):
    from twobyteasr.subtitle_rules.grouping import cues_from_resegmented_texts
    rows=make_rows(parts,speakers)
    cues=cues_from_resegmented_texts(rows,parts)
    assert [c.text for c in cues] == parts


@pytest.mark.parametrize('text,term',[
    ('把水桶装满再拿出去','装满'),
    ('但是这个月光合奏还能够吃得下去吗','吃得下去吗'),
    ('因为他的这一把菊花力叠的太舒服了','菊花力'),
    ('让我们把最热烈的掌声送给他们','最热烈'),
])
def test_productive_dependencies_are_preserved_without_dictionary_task_terms(text,term):
    q=BoundaryQuality(text)
    cuts,issues=q.repair([q.total])
    start=q.index.content.index(term)
    assert not any(start < edge < start+len(term) for edge in cuts)
    assert all(len(p)<=14 for p in q.index.pieces(cuts))
    assert not issues


@pytest.mark.parametrize('parts',[
    ['我已经关门了','这里就是出口'],
    ['因为萌化叠的太多了','并且后台几乎每个精灵都有非常高的一个萌化层数'],
])
def test_right_hand_clause_opening_is_not_taken_by_completed_left_clause(parts):
    q=quality_for_segments(make_rows(parts))
    cuts,_=q.repair([len(parts[0]),sum(map(len,parts))])
    assert len(parts[0]) in cuts


def snapshot():
    return resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'offline'}}}})


def test_retry_reconsiders_local_stable_boundary_and_current_constraints():
    from twobyteasr.subtitle_rules.grouping import GROUPING_SCHEMA
    q=BoundaryQuality('但是这个月光合奏还能够吃得下去吗')
    q.stable_boundaries={14,16}
    calls=[]
    def complete(messages,**kwargs):
        calls.append(json.loads(messages[1]['content']))
        return '{"boundaries":[8,16]}'
    result=retry_quality_windows(q,[14,16],[14,16],provider=SimpleNamespace(complete=complete),
        snapshot=snapshot(),schema=GROUPING_SCHEMA,budget=QualityRetryBudget(),record=lambda *a,**k:None)
    assert result==[8,16]
    assert calls and 14 not in calls[0]['required_boundaries']


def test_unchanged_invalid_retry_remains_unresolved():
    from twobyteasr.subtitle_rules.grouping import GROUPING_SCHEMA
    q=BoundaryQuality('SuperLongPlayerIdentifier')
    events=[]
    result=retry_quality_windows(q,[q.total],[q.total],provider=SimpleNamespace(
        complete=lambda messages,**k:json.dumps({'boundaries':json.loads(messages[1]['content'])['current_boundaries']})),
        snapshot=snapshot(),schema=GROUPING_SCHEMA,budget=QualityRetryBudget(),
        record=lambda name,**data:events.append(dict(event=name,**data)))
    retry=next(e for e in events if e['event']=='grouping_quality_retry')
    assert retry['outcome']=='unchanged_with_violations' and retry['review_required'] and not retry['accepted']
    assert result==[q.total] and any(i['kind']=='length' for i in q.inspect(result))


def test_task_retry_budget_is_independent_of_thread_completion_order():
    budget=QualityRetryBudget(requests=1)
    budget.register_batches([1,2])
    entered=threading.Event()
    def second():
        entered.set()
        return budget.take(2048,batch_index=2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(second)
        assert entered.wait(2)
        assert budget.take(2048,batch_index=1) is not None
        budget.finish_batch(1)
        assert future.result(timeout=2) is None
        budget.finish_batch(2)


def test_alignment_block_does_not_become_a_lexical_word():
    text='但是这个月光合奏还能够吃得下去吗'
    rows=make_rows([text])
    rows[0].caption_arbitration['word_timing']={'basis':'provider_words','measured_words':[
        {'text':text,'start_ms':0,'end_ms':1500}]}
    q=quality_for_segments(rows)
    cuts,issues=q.repair([q.total])
    assert cuts==[8,16] and not issues


def test_long_institution_team_reports_length_conflict_without_cutting_the_name():
    text='广东工业大学毛豆后援会应援战队'
    q=BoundaryQuality(text)
    cuts,issues=q.repair([q.total])
    assert cuts==[q.total]
    assert any(issue['kind']=='length' for issue in issues)


@pytest.mark.parametrize('text,expected',[
    ('不知道下一轮会不会进行一轮毒罐',['不知道下一轮','会不会进行一轮毒罐']),
    ('但在这里其实对一只呆鸟选手来说非常的不妙',['但在这里其实','对一只呆鸟选手来说非常的不妙']),
])
def test_complete_modal_and_comparative_components_choose_an_earlier_cut(text,expected):
    q=BoundaryQuality(text)
    cuts,issues=q.repair([q.total])
    assert q.index.pieces(cuts)==expected
    assert not issues


def test_candidates_record_actual_pos_and_protection_evidence():
    batch=FIXTURE['batches'][2]
    rows=core.deserialize_segments([r for r in FIXTURE['segments'] if r['segment_id'] in batch['source_segment_ids']])
    q=quality_for_segments(rows,FIXTURE['acoustic_tokens'],protected=batch['protected_source_offsets'])
    at=q.index.content.index('最热烈',300)+1
    evidence=q.explain_boundary(at)
    assert not evidence['allowed']
    assert any(span['reason']=='degree_predicate' for span in evidence['syntax'])
    assert any(t['text']=='最' and t['pos']=='a' for t in q.tagged_tokens)
    assert len(q.tokenizer_identity()['dictionary_sha256'])==64
