"""Manual source choice is authoritative; synthetic transcripts only."""
import copy,json
from types import SimpleNamespace
import numpy as np
import pytest
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
from twobyteasr.recognition.language_decision import bind
from twobyteasr.recognition.language_diagnostics import audit_primary_language
from twobyteasr.recognition.transcript_acceptance import gate_primary,pending_ranges,identity_for
from twobyteasr.subtitle_rules.language_rules import SUPPORTED_REQUESTS,normalize_language
from tests.test_moss_empty_recovery import DE,EN,raw_rows


def process(tmp_path,requested,text=DE):
    rows=raw_rows(text=text);context=RuntimeContext(requested_language=requested)
    warnings=[];events=[]
    legacy=SimpleNamespace(record_run_event=lambda event,**data:events.append(dict(event=event,**data)),
        add_review_item=lambda *a,**kw:warnings.append((a,kw)))
    bind(context,[r['text'] for r in rows])
    audit=audit_primary_language(rows,context,legacy)
    selected=gate_primary({'segments':rows,'references':rows},np.zeros(5925776,np.float32),context,legacy,{'cache_dir':str(tmp_path)},audit)
    return selected,context,warnings,events


@pytest.mark.parametrize('requested',[x for x in SUPPORTED_REQUESTS if x!='auto'])
def test_every_manual_language_wins_observation(tmp_path,requested):
    selected,context,warnings,_=process(tmp_path,requested,EN if normalize_language(requested)=='de' else DE)
    assert context.language_mode=='manual' and context.task_language==normalize_language(requested)
    assert context.language_decision['adopted_language']==normalize_language(requested)
    assert len(selected['segments'])==133 and not pending_ranges(context.transcript_acceptance)
    assert context.transcript_acceptance['candidate_rows']==raw_rows(text=EN if normalize_language(requested)=='de' else DE)
    if normalize_language(requested) not in {'de'}:assert len(warnings)<=1


def test_manual_english_old_full_rejection_migrates_without_fee_or_language_change(tmp_path):
    audio=np.zeros(5925776,np.float32)
    old={'version':1,'identity':identity_for(audio,'en'),'ranges':[dict(id='old',start=0.,end=370.361,
        start_sample=0,end_sample=len(audio),status='pending',reason='text_language_conflict',raw_rows=raw_rows(),attempts=[])]}
    (tmp_path/'primary-selection-en.json').write_text(json.dumps(old),'utf8')
    selected,ctx,warnings,events=process(tmp_path,'en')
    assert len(selected['segments'])==133 and ctx.task_language=='en'
    assert len(warnings)==1 and not pending_ranges(ctx.transcript_acceptance)
    assert (tmp_path/'primary-selection-en.json').exists()
    assert list(tmp_path.glob('primary-selection-en-history-*.json'))
    assert any(e['event']=='transcript_selection_invalidated' for e in events)


def test_auto_evidence_and_manual_task_are_independent(tmp_path):
    _,automatic,_,_=process(tmp_path/'auto','auto')
    _,manual,_,_=process(tmp_path/'manual','en')
    assert automatic.language_mode=='auto' and automatic.task_language=='de'
    assert automatic.language_decision['decision_basis']=='transcript_heuristic'
    assert automatic.language_decision['acoustic_language_verified'] is False
    assert manual.task_language=='en' and manual.language_mode=='manual'
    assert automatic.requested_language=='auto'


def test_provider_declaration_is_distinct_from_audio_verification():
    c=RuntimeContext(requested_language='auto');bind(c,[DE],asr_detected='it')
    assert c.task_language=='it' and c.language_decision['decision_basis']=='recognizer_declaration'
    assert c.language_decision['observed_text_language']=='de' and not c.language_decision['acoustic_language_verified']
    c=RuntimeContext(requested_language='en');bind(c,[DE],asr_detected='it');assert c.task_language=='en'


@pytest.mark.parametrize('bad',[{'start':0.,'end':1.,'text':''},{'start':float('nan'),'end':1.,'text':'bad'},
    {'start':1.,'end':0.,'text':'bad'},{'start':0.,'end':2.,'text':'bad'}])
def test_manual_preference_does_not_disable_candidate_contract(tmp_path,bad):
    ctx=RuntimeContext(requested_language='en')
    legacy=SimpleNamespace(record_run_event=lambda *a,**kw:None)
    with pytest.raises(Exception):gate_primary({'segments':[bad]},np.zeros(16000),ctx,legacy,{'cache_dir':str(tmp_path)},{'regions':[],'conflicts':0})


def test_cloud_controls_and_identity_do_not_assume_moss_support():
    from twobyteasr.providers.asr_language_control import policy,hints
    from twobyteasr.providers.asr_api_process import cache_hint_signature
    moss=dict(model='moss-transcribe-diarize-pro',protocol='mosi_transcriptions')
    assert policy(moss,'en')['request_language'] is None and hints(moss,'en')=={}
    assert cache_hint_signature(moss,{},'en')==cache_hint_signature(moss,{},'de')
    qwen=dict(model='qwen3-asr-flash-filetrans',protocol='dashscope_filetrans')
    assert hints(qwen,'pt-BR')=={'asr_request_language':'pt'}
    assert cache_hint_signature(qwen,{},'en')!=cache_hint_signature(qwen,{},'de')
    assert policy(qwen,'en')['remote_constraint_accepted'] is None


def test_manual_mismatch_pipeline_retains_source_once_and_legal_native_scope(tmp_path,monkeypatch):
    from tests.test_moss_recovery_pipeline import run_fixture
    project,report,ctx=run_fixture(tmp_path,monkeypatch,DE)
    original=raw_rows();assert ctx.task_language=='en' and project.cues
    assert report['status'] not in {'needs_recovery','failed','empty_result'}
    assert report['result']['transcript_counts']['accepted_segment_count']==len(original)
    assert len([r for r in report['review_items'] if r.get('category')=='转写语言需要核对'])==1
    grouped={i:[] for i in range(len(original))}
    width=370.361/len(original)
    for cue in project.cues:
        midpoint=(cue.start_ms+cue.end_ms)/2000
        index=min(len(original)-1,int(midpoint/width));grouped[index].append(cue)
        assert cue.start_ms>=original[index]['start']*1000-50 and cue.end_ms<=original[index]['end']*1000+50
    for index,cues in grouped.items():
        assert cues
        assert ' '.join(' '.join(c.text.split()) for c in cues)==' '.join(original[index]['text'].split())
    assert len({(c.start_ms,c.end_ms,c.text,c.speaker_id) for c in project.cues})==len(project.cues)
    assert len({c.speaker_id for c in project.cues})==1
    distribution={n:sum(len(v)==n for v in grouped.values()) for n in set(map(len,grouped.values()))}
    (tmp_path/'split-integrity.json').write_text(json.dumps({'raw':len(original),'final':len(project.cues),'per_source_split_distribution':distribution}),'utf8')


def test_alignment_unavailable_keeps_valid_text_and_native_times(monkeypatch):
    import subtitle_core as core
    from twobyteasr.recognition import cue_forced_alignment as alignment,asr
    # The real final aligner adapter reports unavailable; it must retain cues.
    def unavailable(*args,**kw):raise asr.AlignerUnavailableError('fixture aligner unavailable')
    monkeypatch.setattr(asr,'run_qwen_aligner_worker',unavailable)
    monkeypatch.setattr(alignment,'_predicted_second_engine',lambda jobs:None)
    cue=core.SubtitleCue('fixture',0.,2.,DE,speaker='S00')
    ctx=RuntimeContext(requested_language='en')
    before=(cue.start,cue.end,cue.text)
    with activate_runtime_context(ctx,legacy=core):
        count=alignment.align_final_cues([cue],np.zeros(32000,np.float32),core,language='English')
    assert count==0 and (cue.start,cue.end,cue.text)==before
    assert not getattr(cue,'forced_alignment',None)


def test_save_reopen_preserves_manual_request_even_if_old_code_overwrote_label(tmp_path):
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,save_project,load_project
    from twobyteasr.subtitle_rules.language_rules import project_language
    project=SubtitleProject(StudioMedia('',duration_ms=1000),generation_metadata={'language':{'requested':'en','code':'de','mode':'auto'}})
    reopened=load_project(save_project(project,tmp_path/'manual.2byteproj'))
    assert project_language(reopened)=='en'
    assert reopened.generation_metadata['language']['mode']=='manual'
    assert reopened.generation_metadata['language']['previous_adopted_language']=='de'


@pytest.mark.parametrize('protocol,model,requested,expected',[
    ('dashscope_filetrans','qwen3-asr-flash-filetrans','en','en'),
    ('dashscope_filetrans','qwen3-asr-flash-filetrans','pt-BR','pt'),
    ('dashscope_filetrans','qwen3-asr-flash-filetrans','auto',None),
    ('dashscope_multimodal','unconfirmed-deployment','en',None),
    ('openai_transcription','whisper-1','it','it'),
    ('azure_transcription','deployment','ja','ja'),
    ('openai_transcription','whisper-1','auto',None),
])
def test_documented_request_serialization_keeps_source_choice(tmp_path,protocol,model,requested,expected):
    from tests.test_qwen_asr_api import FakeRequests,OpenAIResponse
    from twobyteasr.recognition.asr import call_qwen_asr_api
    if protocol=='dashscope_filetrans':
        from tests.test_no_cuda_cloud_asr import qwen3_endpoint,Storage,Response
        from twobyteasr.providers.cloud_asr_jobs import filetrans
        from twobyteasr.providers.qwen31_asr import filetrans_hints_for_model
        sent={}
        class Client:
            @staticmethod
            def post(url,**kw):
                sent.update(kw['json']);return Response({'output':{'task_id':'fixture','task_status':'PENDING'}})
            @staticmethod
            def get(url,**kw):raise OSError('stop after inspecting real submission')
        endpoint=qwen3_endpoint(**filetrans_hints_for_model(model,[],language=requested))
        with pytest.raises(OSError):filetrans(np.zeros(16000),endpoint,tmp_path,Storage(),client=Client)
        assert sent['parameters'].get('language')==expected
        if expected is None:assert 'language' not in sent['parameters']
        return
    requests=FakeRequests()
    if protocol!='dashscope_multimodal':
        requests.post=lambda url,**kwargs:requests.calls.append((url,kwargs)) or OpenAIResponse()
    context=RuntimeContext(requested_language=requested)
    endpoint=dict(protocol=protocol,model=model,provider='fixture',url='https://fixture.invalid/v1',api_key='offline-fixture')
    with activate_runtime_context(context):
        call_qwen_asr_api(np.zeros(1600,np.float32),'context',endpoint=endpoint,requests_module=requests)
    body=requests.calls[0][1]
    field=body['json']['parameters']['asr_options'] if protocol=='dashscope_multimodal' else body['data']
    assert field.get('language')==expected
    if expected is None:assert 'language' not in field
    assert context.requested_language==requested


def test_parallel_children_copy_bound_manual_decision_without_cross_task_pollution():
    from twobyteasr.recognition.streaming_recognition import LongMediaPipeline
    context=RuntimeContext(requested_language='it');bind(context,[DE],asr_detected='de')
    owner=LongMediaPipeline.__new__(LongMediaPipeline);owner.context=context
    owner.inputs={0:{'version':'one'},1:{'version':'two'}}
    a,b=owner._context(0),owner._context(1)
    assert a.task_language==b.task_language=='it'
    assert a.language_decision==context.language_decision
    a.language_decision['observed_text_language']='en'
    assert b.language_decision['observed_text_language']==context.language_decision['observed_text_language']=='de'
    other=RuntimeContext(requested_language='auto');bind(other,[DE])
    assert other.task_language=='de' and b.task_language=='it'



def test_legacy_project_text_observation_never_turns_usable_cues_into_pending():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.recognition.language_recovery_project import project_pending,project_review_ranges
    project=SubtitleProject(StudioMedia('',duration_ms=90000),cues=[StudioCue('old',0,60000,DE*12)],
        generation_metadata={'language':{'requested':'en','code':'en'}})
    assert not project_pending(project)
    review=project_review_ranges(project)
    assert review and all(x['status']=='observation' for x in review)
    assert project.cues[0].text==DE*12


def test_manual_locale_beats_old_observation_and_live_settings():
    from twobyteasr.subtitle_rules.segmentation_profiles import task_language_tag,project_language_tag
    c=RuntimeContext(requested_language='pt-PT',asr_settings_snapshot={'subtitle_language':{'recognition_language':'pt-BR'}})
    with activate_runtime_context(c):assert task_language_tag()=='pt-PT'
    project=SimpleNamespace(generation_metadata={'language':{'requested':'en','code':'de','evidence':{'locale':'de'}}})
    assert project_language_tag(project)=='en'
