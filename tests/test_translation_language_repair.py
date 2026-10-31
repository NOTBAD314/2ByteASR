import json
import pytest
from twobyteasr.subtitle_rules import subtitle_translation as st
from tests.test_subtitle_translation import make_project,FakeProvider


def test_italian_translation_has_independent_numeric_and_name_rules():
    assert st.validate_translation('siamo al giro 49','现在是第49圈','zh-Hans','it') is None
    assert st.validate_translation('siamo al giro 49','现在是第50圈','zh-Hans','it')=='number_mismatch'
    assert st.validate_translation('Leclerc','Leclerc','zh-Hans','it') is None
    assert st.validate_translation('49','四十九','zh-Hans','it') is None
    assert st.validate_translation('Ciao ragazzi','Ciao ragazzi','zh-Hans','it')=='echo_source'


def test_translation_repair_sends_specific_errors_and_never_repeats_successes():
    project=make_project(['Ciao ragazzi','siamo al giro 49'],language='it')
    bodies=[]
    def answer(body,index):
        bodies.append(body)
        return {'items':[{'id':key,'translation':'Ciao ragazzi' if key=='c0' else '现在是第49圈'}
                         for key in body['output_ids']]}
    result=st.translate(project,None,FakeProvider(answer),target='zh-Hans',max_items=2)
    assert {key:item.text for key,item in result.translations.items()}=={'c1':'现在是第49圈'}
    assert result.failed=={'c0':'echo_source'} and result.requests==2
    assert bodies[1]['output_ids']==['c0']
    assert bodies[1]['validation_repairs']['items']==[{
        'id':'c0','reason':'echo_source','rejected_translation':'Ciao ragazzi'}]
    st.apply_translation_result(project,result)
    assert st.records_of(project)['c0']['rejected_response']['rejected_translation']=='Ciao ragazzi'


@pytest.mark.parametrize('source,translation',[
    ("le qualifiche all'orario dell'FP3",'在第三次自由练习赛的时间进行排位赛'),
    ('un weekend da 6 e mezzo','一个能打六分半的周末'),
    ('6 e mezzo da 6 e mezzo','六分半，六分半'),
    ('150.000 giri al minuto','每分钟十五万转'),
    ('125.000 giri','12.5万转'),
    ('dalle 10 e di quarto fino alle 11','从10点15分到11点'),
    ('3-4 anni','三四年'),
    ('centrato al 100%','百分百命中'),
    ('centrato al 100%','完全命中'),
    ('Browning al posto di Albon, poi Irakawa da Toyota WEC, Mini',
     'Browning替代Albon，然后是Toyota WEC的Irakawa和Mini'),
    ('quindi Mini al posto di Colapinto, Fornaroli','然后Mini替代Colapinto，还有Fornaroli'),
    ('十分だと思う','我觉得足够了'),
])
def test_quantity_units_locale_time_names_and_kanji_adverbs(source,translation):
    language='ja' if source=='十分だと思う' else 'it'
    assert st.validate_translation(source,translation,'zh-Hans',language) is None


def test_actual_number_changes_stay_rejected_after_locale_normalization():
    assert st.validate_translation('150.000 giri al minuto','每分钟125000转','zh-Hans','it')=='number_mismatch'
    assert st.validate_translation('al 1000%','百分之百','zh-Hans','it')=='number_mismatch'
    assert st.validate_translation('No','是的','zh-Hans','it')=='negation_mismatch'
    assert st.validate_translation('Leclerc','Hamilton','zh-Hans','it')=='entity_mismatch'


def test_targeted_numeric_repair_preserves_a_hyperbolic_percent():
    p=make_project(['non contentissimi al 1000%'],language='it');bodies=[]
    def answer(body,index):
        bodies.append(body)
        return {'items':[{'id':'c0','translation':'并非百分之百满意' if index==1 else '并非百分之一千满意'}]}
    result=st.translate(p,None,FakeProvider(answer),target='zh-Hans')
    assert not result.failed and result.requests==2
    assert bodies[1]['validation_repairs']['items'][0]['preserve_quantities']==[
        {'kind':'percent','value':'1000','count':1}]


def test_new_rules_can_recover_a_retained_translation_without_network(monkeypatch):
    p=make_project(['150.000 giri'],language='it')
    with monkeypatch.context() as patch:
        patch.setattr(st,'VALIDATION_VERSION','old-inappropriate-numeric-rule')
        patch.setattr(st,'validate_translation',lambda *a,**k:'number_mismatch')
        result=st.translate(p,['c0'],FakeProvider(lambda *a:{'items':[{'id':'c0','translation':'每分钟十五万转'}]}),target='zh-Hans')
    st.apply_translation_result(p,result)
    provider=FakeProvider(lambda *a:(_ for _ in ()).throw(AssertionError('offline replay must not request')))
    recovered=st.translate(p,['c0'],provider,target='zh-Hans')
    assert recovered.requests==0 and recovered.translations['c0'].text=='每分钟十五万转'


@pytest.mark.parametrize('changed',['context','model','provider','glossary','language'])
def test_retained_rejected_response_cannot_escape_full_input_identity(monkeypatch,changed):
    p=make_project(['150.000 giri','contesto originale'],language='it')
    with monkeypatch.context() as patch:
        patch.setattr(st,'VALIDATION_VERSION','old-inappropriate-numeric-rule')
        patch.setattr(st,'validate_translation',lambda *a,**k:'number_mismatch')
        failed=st.translate(p,['c0'],FakeProvider(lambda *a:{'items':[{'id':'c0','translation':'旧回答：十五万转'}]}),target='zh-Hans')
    st.apply_translation_result(p,failed)
    provider=FakeProvider(lambda *a:{'items':[{'id':'c0','translation':'新回答：十五万转'}]})
    kwargs={}
    if changed=='context':p.cues[1].text='contesto modificato'
    elif changed=='model':provider.model='changed-model'
    elif changed=='provider':provider.provider_id='changed-provider'
    elif changed=='language':p.generation_metadata['language']={'code':'pt'}
    else:kwargs['glossary_pairs']=[('giri','转')]
    result=st.translate(p,['c0'],provider,target='zh-Hans',**kwargs)
    assert result.requests==1 and result.translations['c0'].text=='新回答：十五万转' and not result.cache_hits


def test_graph_identity_does_not_serialize_caption_evidence():
    p=make_project(['字幕'],language='zh')
    from twobyteasr.recognition.recognition_result import input_graph_identity
    data=p.to_dict()
    expected=input_graph_identity(p)
    p.to_dict=lambda:(_ for _ in ()).throw(AssertionError('graph must not serialize captions'))
    assert input_graph_identity(p)==expected
