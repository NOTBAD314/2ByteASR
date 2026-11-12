import copy
import pytest
from twobyteasr.subtitle_rules import subtitle_translation as st
from tests.test_subtitle_translation import make_project,FakeProvider


def provider():return FakeProvider(lambda body,n:{'items':[{'id':k,'translation':'你好'} for k in body['output_ids']]})

@pytest.mark.parametrize('changed',['speaker','speaker_name','neighbor','neighbor_speaker','locale'])
def test_context_change_misses_cache_and_discards_inflight_result(changed):
    p=make_project(['Hello there','Do not go'],language='en');cache={}
    first=st.translate(p,['c0'],provider(),target='zh-Hans',cache=cache)
    assert first.requests==1
    second=st.translate(p,['c0'],provider(),target='zh-Hans',cache=cache)
    assert second.requests==0
    if changed=='speaker':p.cues[0].speaker_id='another'
    elif changed=='speaker_name':p.speakers[0].name='different speaker'
    elif changed=='neighbor':p.cues[1].text='You can go now'
    elif changed=='neighbor_speaker':p.cues[1].speaker_id='another'
    else:p.generation_metadata['language']={'code':'en','locale':'en-GB'}
    st.apply_translation_result(p,first)
    assert 'c0' in first.discarded and not st.records_of(p)
    third=st.translate(p,['c0'],provider(),target='zh-Hans',cache=cache)
    assert third.requests==1


def test_request_names_output_ids_and_readonly_context_are_explicit():
    p=make_project(['Hello there','Do not go'],language='en');bodies=[]
    def reply(body,n):
        bodies.append(body)
        return {'items':[{'id':'c1','translation':'别走'},{'id':'c0','translation':'你好'}]}
    result=st.translate(p,['c0','c1'],FakeProvider(reply),target='zh-Hans')
    assert {k:v.text for k,v in result.translations.items()}=={'c0':'你好','c1':'别走'}
    assert all(row.get('speaker_id') for row in bodies[0]['lines'])


def test_neighbor_edit_marks_only_dependent_translations_and_keeps_manual_protection():
    p=make_project(['Hello there']*10,language='en')
    result=st.translate(p,None,provider(),target='zh-Hans');st.apply_translation_result(p,result)
    st.set_manual(p,'c0','人工译文')
    assert st.statuses(p)['c0']==st.MANUAL and st.statuses(p)['c9']==st.DONE
    p.cues[1].text='Do not go'
    states=st.statuses(p)
    assert states['c0']==st.NEEDS_UPDATE and states['c1']==st.NEEDS_UPDATE and states['c9']==st.DONE
    fresh=st.translate(p,['c0'],provider(),target='zh-Hans');st.apply_translation_result(p,fresh)
    assert st.records_of(p)['c0']['text']=='人工译文'


def test_old_record_context_baseline_is_explicit_and_persists_without_changing_text():
    p=make_project(['Hello there','Do not go'],language='en')
    st.set_manual(p,'c0','你好')
    record=st.records_of(p)['c0'];record.pop('source_context_identity',None)
    st.prepare_context_dependencies(p)
    assert st.records_of(p)['c0']['text']=='你好'
    assert st.records_of(p)['c0']['source_context_basis']=='first_observed_project_revision'
    p.cues[1].speaker_id='new-speaker'
    assert st.statuses(p)['c0']==st.NEEDS_UPDATE
