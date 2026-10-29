import json
from types import SimpleNamespace
from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
from twobyteasr.projects.studio_project import StudioCue, SubtitleProject, StudioMedia
from twobyteasr.recognition.cue_word_alignment import cue_words


def install(monkeypatch, answers):
    calls=[]
    def complete(messages, **kw):
        calls.append(kw)
        value=answers.pop(0)
        if isinstance(value,Exception):raise value
        return value
    def provider(settings,stage,**kw):
        assert stage=='group'
        assert settings['models']['group_model']=='selected-group'
        return SimpleNamespace(complete=complete,provider_id='selected',model='selected-group')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',provider)
    return calls


SETTINGS={'models':{'group_model':'selected-group','polish_model':'other-polish'}}


def test_failed_batch_is_bounded_and_successful_batch_survives(monkeypatch):
    calls=install(monkeypatch,[ValueError('network'),'{"results":[]}',
        json.dumps({'results':[{'cue_id':'b','action':'keep'}]})])
    cues=[StudioCue('a',0,1000,'第一条'),StudioCue('b',1000,2000,'第二条')]
    result=refine_cues_with_llm(cues,runtime_settings=SETTINGS,batch_size=1)
    assert len(calls)==3 and all(c['timeout']==(10,60) for c in calls)
    assert result.llm_status=='partial' and result.failed_cue_ids==['a']
    assert [a.cue_id for a in result.actions]==['b']
    assert [r['status'] for r in result.requests]==['failed','failed','validated']


def test_cross_batch_or_duplicate_ids_cannot_apply(monkeypatch):
    wrong=json.dumps({'results':[{'cue_id':'other','action':'keep'}]})
    calls=install(monkeypatch,[wrong,wrong])
    outcome=refine_cues_with_llm([StudioCue('a',0,1000,'当前句')],runtime_settings=SETTINGS)
    assert outcome.llm_status=='failed' and not outcome.actions and len(calls)==2


def test_cancel_before_request_issues_no_calls(monkeypatch):
    calls=install(monkeypatch,[])
    outcome=refine_cues_with_llm([StudioCue('a',0,1000,'当前句')],runtime_settings=SETTINGS,cancel_check=lambda:True)
    assert outcome.llm_status=='cancelled' and not calls


def test_one_attempt_budget_and_explicit_json_contract(monkeypatch):
    from twobyteasr.subtitle_rules.sentence_refine import REFINE_SYSTEM_PROMPT,validate_action
    assert '"results"' in REFINE_SYSTEM_PROMPT and '"cue_id"' in REFINE_SYSTEM_PROMPT
    calls=install(monkeypatch,[ValueError('network')])
    outcome=refine_cues_with_llm([StudioCue('a',0,1000,'当前句')],runtime_settings=SETTINGS,max_attempts=1)
    assert len(calls)==1 and outcome.llm_status=='failed'
    assert validate_action('嗯 然后继续',{'cue_id':'a','action':'space','space_after_chars':[0]}).action=='keep'


def test_legacy_moss_uniform_words_cannot_be_acoustic_split_evidence():
    p=SubtitleProject(media=StudioMedia(path='task.wav'),cues=[StudioCue('a',0,1000,'甲乙丙丁',evidence_refs=['r'])])
    row=dict(start_ms=0,end_ms=1000,primary_source='moss-host',final_timing_owner='FireRed',
        caption_arbitration={'timing_evidence':{'independent_acoustic':False}},
        words=[dict(text=c,start_ms=i*250,end_ms=(i+1)*250) for i,c in enumerate('甲乙丙丁')])
    p.asr_evidence={'r':row}
    assert not cue_words(p,p.cues[0])[0]
    row['caption_arbitration']['acoustic_words']=[dict(text=c,start_ms=a,end_ms=b)
        for c,a,b in [('甲',0,110),('乙',110,400),('丙',600,730),('丁',730,1000)]]
    words,_=cue_words(p,p.cues[0])
    assert [(w.start_ms,w.end_ms) for w in words]==[(0,110),(110,400),(600,730),(730,1000)]
