import copy
import numpy as np
import pytest
from twobyteasr.recognition.alignment_items import annotate_row,can_join,bind_jobs,verify_items,natural_regroup,rejection,sample_bounds
from twobyteasr.recognition.alignment_measurements import model_audio,sentence_measurement,accept_retry,display_segments


def part(pid,a,b,text,time):return dict(source_id=pid,char_start=a,char_end=b,raw_text=text,source_time=time)


def test_display_adjacency_cannot_authorize_cross_parent_audio_join():
    row=dict(key='a',start_ms=100,end_ms=500,speaker='S01',text='hello')
    a=annotate_row(row,[part(1,0,5,'hello',[.1,.5])])
    b=annotate_row(dict(row,key='b',text='world'),[part(2,0,5,'world',[.5,.9])])
    assert not can_join(a,b)
    assert not can_join(row,dict(row,key='b'))
    c=annotate_row(dict(row,key='c',text='there'),[part(1,5,10,'there',[.1,.5])])
    assert can_join(a,c)


def test_natural_regroup_requires_source_time_text_and_order():
    parts=[part(1,0,2,'你好',[1,2]),part(2,0,2,'世界',[2.2,3])]
    assert natural_regroup(parts,'你好，世界！')
    assert not natural_regroup(parts[::-1],'世界你好')
    assert not natural_regroup(parts,'你好，再见')
    parts[1]['source_time']=[4,5]
    assert not natural_regroup(parts,'你好世界')


def test_known731ms_composite_is_rejected_not_labelled_ultra_success():
    job=dict(id='two',text='hello world',language='English',window_start_ms=0,window_end_ms=4000,parent_ids=['one','two'])
    assert rejection(job)=='unrelated_or_unmapped_acoustic_parents'
    with pytest.raises(ValueError,match='parent'):bind_jobs([job],dict(samples=64000,sha256='x'))


def test_exact_sample_geometry_and_text_mutation_are_guarded():
    job=dict(id='one',text='你好',language='Chinese',window_start_ms=0,window_end_ms=100,window_samples=[7,1599],available_context_samples=[7,1599])
    spec=dict(samples=1600,sha256='x');bound=bind_jobs([job],spec)
    assert bound[0]['alignment_item']['absolute_pcm_samples']==[7,1599]
    assert sample_bounds(job,1600)==(7,1599)
    verify_items(bound,spec)
    bound[0]['text']='再见'
    with pytest.raises(ValueError):verify_items(bound,spec)


def test_gain_policy_retains_time_zero_mask_and_never_quantizes():
    rng=np.random.default_rng(314);x=rng.normal(0,.1,3200).astype('float32');x[:32]=0
    a,_,da=model_audio(x);b,_,db=model_audio(np.float32(.7)*x)
    assert len(a)==len(b)==len(x)+2560
    assert np.array_equal(a==0,b==0)
    assert np.max(np.abs(a-b))<=1.2e-7
    assert not da['integer_reencoding'] and not da['clipping'] and not da['resampling']
    assert da['removed_declared_padding_samples']==[0,0]


def test_only_declared_artificial_padding_can_be_removed():
    real=np.r_[np.zeros(1600,dtype='float32'),np.ones(1600,dtype='float32')*.01]
    x=np.r_[np.zeros(5712,dtype='float32'),real]
    unchanged,_,d=model_audio(x)
    assert d['removed_declared_padding_samples']==[0,0]
    mapped,shift,known=model_audio(x,[5712,0])
    expected,_,_=model_audio(real)
    assert np.array_equal(mapped,expected) and shift==277
    assert known['valid_original_samples']==[5712,len(x)]
    bad=x.copy();bad[0]=1e-20
    with pytest.raises(ValueError,match='nonzero'):model_audio(bad,[5712,0])


def test_sentence_retry_cannot_move_existing_measurements_or_use_wrong_utterance():
    p=dict(start=dict(value_ms=None),end=dict(value_ms=2000))
    r=dict(start=dict(value_ms=500),end=dict(value_ms=4000))
    accepted,used=accept_retry(p,r,source_range=[0,5000]);assert not used and accepted==p
    r['end']['value_ms']=2040
    accepted,used=accept_retry(p,r,source_range=[0,5000]);assert used==['start'] and accepted['end']==p['end']


def test_local_char_failure_does_not_erase_sentence_start_with_two_word_anchors():
    p=dict(start=dict(value_ms=None),end=dict(value_ms=2000))
    r=dict(start=dict(value_ms=500),end=dict(value_ms=None,reason='local_repair'))
    anchors=[dict(span=[2,4],side='start'),dict(span=[4,6],side='end')]
    a,used=accept_retry(p,r,source_range=[0,3000],anchors=anchors)
    assert used==['start'] and a['end']['value_ms']==2000
    assert accept_retry(p,r,source_range=[0,3000],anchors=anchors[:1])[1]==[]


def test_unknown_edge_is_a_display_fallback_not_a_measurement():
    seg=[dict(char_start=0,char_end=4,start_ms=-80,end_ms=1000,start_basis='window_edge',end_basis='model',word_indices=[0])]
    accepted=dict(start=dict(value_ms=None),end=dict(value_ms=1000))
    display,fallback=display_segments(seg,accepted,valid_range=[0,1200])
    assert seg[0]['start_ms']==-80 and display[0]['start_ms']==0
    assert display[0]['start_basis']=='input_edge_fallback'
    assert fallback[0]['measured'] is False and accepted['start']['value_ms'] is None


def test_sentence_retry_merges_uncertain_prefix_without_fabricating_internal_cuts():
    seg=[dict(char_start=0,char_end=1,start_ms=0,end_ms=100,start_basis='window_edge',end_basis='model',word_indices=[0]),
         dict(char_start=1,char_end=3,start_ms=100,end_ms=800,start_basis='model',end_basis='model',word_indices=[1])]
    out,_=display_segments(seg,dict(start=dict(value_ms=500),end=dict(value_ms=800)),valid_range=[0,1000])
    assert len(out)==1 and out[0]['char_start']==0 and out[0]['char_end']==3 and out[0]['start_ms']==500
    assert out[0]['word_indices']==[0,1]


def test_raw_zero_duration_pair_is_not_a_sentence_success():
    row=dict(text='a',char_start=0,char_end=1,start_ms=500,end_ms=500,raw_start_ms=500,raw_end_ms=500,start_basis='model',end_basis='model')
    points=sentence_measurement('a',[row],[],[0,1000])
    assert points['start']['value_ms'] is None and points['end']['value_ms'] is None
    assert points['start']['reason']=='sentence_endpoint_order_conflict'


def test_single_character_zero_width_does_not_erase_a_valid_sentence_start():
    # An80ms-bin alias is not a measured character duration. The direct sentence
    # START remains usable when the whole sentence has a separate valid END.
    rows=[dict(char_start=0,char_end=1,start_ms=400,end_ms=400,raw_start_ms=400,raw_end_ms=400,start_basis='model',end_basis='model'),
          dict(char_start=1,char_end=2,start_ms=400,end_ms=800,raw_start_ms=400,raw_end_ms=800,start_basis='model',end_basis='model')]
    m=sentence_measurement('这是',rows,[],[0,1000])
    assert m['start']['value_ms']==400 and m['end']['value_ms']==800
    assert m['start']['unit_duration_reliable'] is False


def test_neighboring_parent_voice_is_rejected_without_clamping_to_parent():
    from twobyteasr.recognition.alignment_measurements import ownership_conflict
    measurement=dict(start=dict(value_ms=316772),end=dict(value_ms=317372))
    assert ownership_conflict(measurement,[313672,316711])
    assert measurement['start']['value_ms']==316772
    # An independently measured onset before a coarse ASR parent is allowed.
    assert not ownership_conflict(dict(start=dict(value_ms=348329),end=dict(value_ms=350769)),[348869,350787])


def test_compatibility_identity_is_not_reported_as_pure_ultra():
    from twobyteasr.recognition.alignment_measurements import effective_metadata
    result=effective_metadata(dict(model='Ultra',alignment_identity={'backend':'ultra'}),
        dict(effective_model_identity={'model':'official','alignment_identity':{'backend':'official_compat'}},compatibility_fallback={'reason':'ownership'}))
    assert result['model']=='official' and result['configured_alignment_identity']['backend']=='ultra'
def test_retry_window_uses_fixed_parent_or_bounded_natural_context():
    from twobyteasr.recognition.alignment_measurements import retry_window,POLICY
    from twobyteasr.recognition.alignment_backend import profile
    assert profile('qwen_ultra_aligner')['audio']['input_policy']==POLICY
    job={'parent_pcm_range_ms':[1500,4000],'source_clock_verified':True,'text':'hello','source_parts':[dict(source_id='p1',char_start=0,char_end=5,raw_text='hello',source_time=[1.5,4.0])]}
    assert retry_window(job,0,96000,[0,96000])==(19200,68800,'fixed_parent_context')
    assert retry_window({'parent_pcm_range_ms':[1500,4000]},0,96000,[0,96000])==(0,96000,'source_continuous_context')
    assert retry_window({},16000,80000,[0,96000])==(0,96000,'source_continuous_context')
    assert retry_window({'parent_pcm_range_ms':[9000,12000]},16000,80000,[0,96000])==(0,96000,'source_continuous_context')

