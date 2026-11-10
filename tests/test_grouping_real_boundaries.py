"""Offline regressions from the November 10 dialogue, through production code."""
import copy
import json
from pathlib import Path

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments, cues_from_quality

FIXTURE = Path(__file__).parent/'fixtures/grouping_contract/arknights_boundaries.json'


@pytest.fixture
def sample():
    data=json.loads(FIXTURE.read_text(encoding='utf-8'))
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh'),legacy=core):
        yield data, core.deserialize_segments(data['segments'])


def batch(data,rows,number):
    trace=next(b for b in data['batches'] if b['batch_index']==number)
    sources=[s for s in rows if s.segment_id in trace['source_segment_ids']]
    return trace,sources


def replay(data,rows,number):
    trace,sources=batch(data,rows,number)
    return cues_from_quality(sources,trace['model_boundaries'],data['acoustic_tokens'],
                            protected=trace['protected_source_offsets'])


def test_b_complete_short_clauses_survive_local_repair(sample):
    data,rows=sample
    cues,_,_=replay(data,rows,10)
    texts=[c.text.strip() for c in cues]
    assert '选这个东西' in texts
    assert '你得对你的队友足够信任' in texts
    assert all(not text.startswith(('东西你','信任我')) for text in texts)


def test_c_measure_word_does_not_move_to_next_sentence(sample):
    data,rows=sample
    cues,_,_=replay(data,rows,19)
    assert '不行 我们我们来一把' in [c.text for c in cues]
    assert not any(c.text.startswith('一把我们') for c in cues)


@pytest.mark.parametrize('number',[6,9,14])
def test_fragmented_model_words_names_and_quantities(sample,number):
    data,rows=sample
    cues,cuts,_=replay(data,rows,number)
    trace,sources=batch(data,rows,number)
    text=core.content_exact(''.join(s.text for s in sources))
    for term in ('阿戈尔','27个'):
        for i in range(len(text)):
            if text.startswith(term,i):
                assert not any(i < cut < i+len(term) for cut in cuts)
    if number==6:
        assert any('他要兜27个' in core.content_exact(c.text) for c in cues)
        assert not set(c.text.strip() for c in cues)&{'他','要','兜','27','个'}


def test_e_estimated_400ms_source_is_not_split(sample):
    data,rows=sample
    cues,_,_=replay(data,rows,8)
    affected=[c for c in cues if c.speaker=='API_S01' and c.start < 116.04 and c.end >115.64]
    assert [(c.text,c.start,c.end) for c in affected]==[('可以刷',115.64,116.04)]


def test_a_batch_seam_does_not_move_object(sample):
    data,rows=sample
    offsets=[];cursor=0
    for trace in sorted(data['batches'],key=lambda b:b['batch_index']):
        offsets.extend(cursor+x for x in trace['final_boundaries'])
        cursor+=len(core.content_exact(trace['source_text']))
    cues,_,_=cues_from_quality(rows,offsets,data['acoustic_tokens'])
    texts=[c.text.strip() for c in cues]
    assert '我觉得要相信他' in texts
    assert not any(t.startswith('他如果我们') for t in texts)


@pytest.mark.parametrize('number',range(1,20))
def test_all_batches_conserve_sources_and_are_idempotent(sample,number):
    data,rows=sample
    trace,sources=batch(data,rows,number)
    original=copy.deepcopy(sources)
    q=quality_for_segments(sources,data['acoustic_tokens'],protected=trace['protected_source_offsets'])
    cuts,_=q.repair(trace['model_boundaries'])
    q2=quality_for_segments(sources,data['acoustic_tokens'],protected=trace['protected_source_offsets'])
    assert q2.repair(cuts)[0]==cuts
    assert ''.join(q.index.pieces(cuts))==''.join(s.text for s in sources)
    assert sources==original


def test_independent_short_replies_and_actual_overlap_remain(sample):
    rows=[core.SpeechSegment(i,a,b,text,.9,[],speaker=speaker)
          for i,(a,b,text,speaker) in enumerate([(0,.2,'对','A'),(.1,.3,'嗯','B'),(.5,.7,'哎','A')],1)]
    cues,cuts,_=cues_from_quality(rows,[1,2,3])
    assert [(c.text,c.speaker) for c in cues]==[('对','A'),('嗯','B'),('哎','A')]
    assert cues[0].end>cues[1].start


def test_final_review_replaces_cached_pre_crop_duration_and_old_id(sample):
    from twobyteasr.subtitle_rules.timing import refresh_final_cue_reviews
    context=core.get_runtime_context()
    context.review_items.append(dict(category='显示过短',detail='只显示 0.35 秒',
        timestamp=115.9,text='刷',cue_id=72))
    cue=core.SubtitleCue(71,115.65,116.05,'可以刷',speaker='API_S01')
    refresh_final_cue_reviews([cue],sample[1],legacy=core,audio_seconds=335.4)
    actual=[r for r in context.review_items if r['category']=='显示过短']
    assert len(actual)==1 and actual[0]['text']=='可以刷'
    assert actual[0]['cue_id']==71 and actual[0]['actual_duration_ms']==400
    assert actual[0]['start_ms']==115650 and actual[0]['timestamp']==cue.start
    assert actual[0]['detail']=='只显示 0.40 秒'


def test_model_sees_real_sources_constraints_and_estimated_timing(sample):
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    snapshot=resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'fixture'}}}})
    source=next(s for s in sample[1] if s.segment_id==72)
    messages=grouping.call_grouping_api([source],provider_snapshot=snapshot,_messages_only=True,
                                      _read_only_context={'before':'上一句','after':'下一句'})
    body=json.loads(messages[1]['content'])
    assert body['segments'][0]['speaker']=='API_S01'
    assert body['read_only_context']=={'before':'上一句','after':'下一句'}
    assert body['source_timing'][0]['basis']=='uniform_display_estimate'
    assert not body['source_timing'][0]['reliable_internal_timing']
    assert body['length_policy']['hard_max']==16 and body['length_policy']['max_seconds']==5
    assert body['length_policy']['hard_max_is_target'] is False
    assert '400ms' in messages[0]['content']


def test_unknown_adjacent_name_tokens_are_protected_without_term_rewriting(sample):
    from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
    q=BoundaryQuality('有阿戈尔吗这次')
    cuts,_=q.repair([2,5,7])
    assert 2 not in cuts and 3 not in cuts
    assert ''.join(q.index.pieces(cuts))=='有阿戈尔吗这次'


def test_verbs_keep_objects_without_swallowing_a_new_source_subject(sample):
    rows=[core.SpeechSegment(1,0,1,'我觉得要相信他',.9,[],speaker='A'),
          core.SpeechSegment(2,1.2,3,'如果我们真的把这五块钱花掉的话',.9,[],speaker='A')]
    q=quality_for_segments(rows)
    assert 6 in q.forbidden
    cuts,_=q.repair([7,q.total])
    assert cuts==[7,q.total]
    assert not q.accept_change(cuts,[6,q.total])[0]


@pytest.mark.parametrize('number',[4,8,10,19])
def test_boundaries_remain_correct_with_the_proven_failed_window_removed(sample,number):
    data,rows=sample
    trace,sources=batch(data,rows,number)
    _,before,_=cues_from_quality(sources,trace['model_boundaries'],data['acoustic_tokens'])
    _,after,_=cues_from_quality(sources,trace['model_boundaries'],data['filtered_acoustic_tokens'])
    assert before==after


@pytest.mark.parametrize('text',['中文，AB12 3个！','（中文）😀e\u0301 🧑\u200d🚀 12.5kg！',
    'a\tb\nc','张三／阿戈尔','１２３abc','Cafe\u0301与café','中文　English 27个'])
def test_codepoint_raw_edges_preserve_mixed_text_without_utf16_shifts(sample,text):
    from twobyteasr.subtitle_rules.grouping_quality import SourceIndex
    index=SourceIndex.build(text)
    for cut in range(1,len(index.content)+1):
        cuts=sorted({cut,len(index.content)})
        pieces=index.pieces(cuts)
        assert ''.join(pieces)==text
        assert ''.join(core.content_exact(p) for p in pieces)==index.content
