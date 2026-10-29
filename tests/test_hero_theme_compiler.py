"""DESIGN -> three actual heroes -> explicit selection -> bounded motion repair."""
import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from twobyteasr.caption_design import studio_ai
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.caption_design.theme_draft import DraftValidationError
from tests.test_theme_motion import spec


def setup(monkeypatch,responses,*,vision=False):
    settings={'models':{'polish':'selected-high'}}
    selection=SimpleNamespace(credential_ready=True,provider='fixture',model='selected-high')
    monkeypatch.setattr(studio_ai.GLOBAL_PROVIDER_REGISTRY,'selection',lambda *_a,**_k:selection)
    calls=[];traces=[];clock=[100.]
    from twobyteasr.caption_design import web_theme_compiler
    monkeypatch.setattr(web_theme_compiler,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    class Provider:
        transport='codex_cli'
        def capabilities(self):return SimpleNamespace(vision=vision)
        def complete(self,messages,**kwargs):
            calls.append((copy.deepcopy(messages),kwargs));clock[0]+=.1
            result=responses.pop(0)
            if callable(result):return result(kwargs)
            if isinstance(result,Exception):raise result
            return result
    monkeypatch.setattr(studio_ai,'provider_for_stage',lambda *_a,**_k:Provider())
    monkeypatch.setattr(studio_ai,'_persist_ai_design_trace',lambda trace:traces.append(copy.deepcopy(trace)) or '')
    project=SubtitleProject(media=StudioMedia(path='fixture.mp4'),cues=[StudioCue('cue',0,3000,'完整中文')])
    return project,settings,calls,traces


def hero(motion=False):
    data=dict(name='完整主题',concept='字行 .lettering',palette=dict(primary='#FFFFFF',text='#FFFFFF'),
        appearance=dict(fontFamily='Smiley Sans, Source Han Sans SC',fontSize=80),stageHtml='',stageCss='',
        cueHtml='<div class="lettering">{{words}}</div>',cueCss='.wt-cue{position:absolute;inset:0}.lettering{font-family:var(--wt-font);font-size:var(--wt-size)}',notes='DESIGN_V2_HERO_GSAP')
    if motion:data['motionSpec']=spec()
    return data


def design(selected='b'):
    old=json.loads((Path(__file__).parent/'fixtures/death_stranding_concepts.json').read_text('utf8'))
    old.update(schema_version=2,selected_concept_id=selected)
    for i,row in enumerate(old['concepts']):
        row['id']=chr(97+i);row['design']={k:k+str(i) for k in ('metaphor','silhouette','hierarchy','font','material','rhythm','forbidden','content_relevance')}
        row['design']['colors']=[dict(hex=color,role=str(j)) for j,color in enumerate(('#FFFFFF','#223344','#AABBCC'))]
        row['hero_theme']=hero()
    return old


def test_legacy_compiler_saves_design_before_each_real_hero(monkeypatch,tmp_path):
    d=design('')
    for c in d['concepts']:c.pop('hero_theme')
    responses=[json.dumps({'brief':d['brief']}),json.dumps(d)]
    def actual_hero(_kwargs):
        saved=list(tmp_path.rglob('DESIGN.md'))
        assert len(saved)==len(calls)-2 and all(p.read_text('utf8').startswith('# ') for p in saved)
        return json.dumps(hero())
    responses.extend([actual_hero]*3)
    project,settings,calls,traces=setup(monkeypatch,responses)
    monkeypatch.setattr(studio_ai,'_persist_ai_design_trace',lambda t:traces.append(copy.deepcopy(t)) or str(tmp_path/'trace.json'))
    from twobyteasr.caption_design.web_theme_compiler import compile_theme
    result=compile_theme(project,'cue','历史编译器兼容',settings,request_id='test')
    assert len(calls)==5 and result.source=='concepts' and not result.theme and not result.selected_concept_id
    assert all(c['hero_theme']['cueHtml'] and c['design_markdown'] for c in result.concepts)
    assert all('rule_score' not in c for c in result.concepts)
    assert 'Smiley Sans' in calls[0][0][1]['content']
    assert calls[2][1]['timeout']==pytest.approx(90)


def test_selected_stage_sends_only_one_hero_and_preserves_full_original(monkeypatch):
    raw=json.dumps(hero(True),ensure_ascii=False)
    project,settings,calls,traces=setup(monkeypatch,[raw])
    result=studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=design())
    sent=json.loads(calls[0][0][1]['content'])
    assert len(calls)==1 and result.selected_concept_id=='b' and result.theme['motionSpec']
    assert sent['selected_concept']['hero_theme'] and 'concepts' not in sent and 'speaker' not in sent
    assert traces[-1]['raw_provider_responses'][-1]['response_text']==raw


def test_no_selection_or_missing_hero_cannot_start_motion(monkeypatch):
    project,settings,calls,_=setup(monkeypatch,[])
    with pytest.raises(Exception,match='先选择'):
        studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=design(''))
    d=design();d['concepts'][1].pop('hero_theme')
    with pytest.raises(Exception,match='缺少静态英雄帧'):
        studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=d)
    assert not calls


def test_pixel_defect_repairs_only_selected_theme_with_full_original(monkeypatch):
    raw=json.dumps(hero(True));project,settings,calls,_=setup(monkeypatch,[raw,raw]);count=[]
    def validate(theme,deadline):
        count.append(theme)
        if len(count)==1:raise DraftValidationError('主字幕位置错误')
        return {'passed':True}
    result=studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=design(),render_validator=validate)
    assert result.repair_count==1 and raw in calls[-1][0][1]['content'] and '主字幕位置错误' in calls[-1][0][1]['content']


def test_renderer_failure_retains_theme_without_provider_retry(monkeypatch):
    project,settings,calls,_=setup(monkeypatch,[json.dumps(hero(True))])
    def validate(*_):raise DraftValidationError('browser timed out','render_timeout')
    with pytest.raises(DraftValidationError) as failed:
        studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=design(),render_validator=validate)
    assert failed.value.preview_theme['motionSpec'] and len(calls)==1


def test_three_failed_repairs_stop_without_builtin_substitution(monkeypatch):
    project,settings,calls,traces=setup(monkeypatch,['invalid theme']*4)
    with pytest.raises(Exception,match='三次定向修复后仍未通过'):
        studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=design())
    assert len(calls)==4 and traces[-1]['web_theme_source']=='failed' and traces[-1]['repair_count']==3


def test_partial_hero_failure_preserves_completed_directions_for_retry(monkeypatch):
    from twobyteasr.providers.ai_providers import AIProviderError
    d=design('');d['concepts'][1].pop('hero_theme');d['concepts'][2].pop('hero_theme')
    def interrupted(kwargs):
        kwargs['on_stream_event']('delta','partial hero')
        raise AIProviderError('broken connection',category='transport_error')
    project,settings,calls,traces=setup(monkeypatch,[interrupted])
    with pytest.raises(AIProviderError) as failed:
        studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=d,concepts_only=True)
    assert failed.value.design_checkpoint['concepts'][0]['hero_theme']
    assert calls[0][1]['stage'].startswith('studio_web_theme_静态英雄帧')
    assert traces[-1]['raw_provider_responses'][-1]['partial_response_text']=='partial hero'


def test_actual_frame_review_uses_evidence_not_scores(monkeypatch,tmp_path):
    from twobyteasr.caption_design.theme_art_direction_v2 import SCORE_LABELS
    review=dict(passed=True,checks={k:dict(passed=True,evidence='保持帧对应结构清晰可见') for k in SCORE_LABELS},defects=[])
    project,settings,calls,_=setup(monkeypatch,[json.dumps(hero(True)),json.dumps(review)],vision=True)
    frame=tmp_path/'frame.png';frame.write_bytes(b'fixture-image')
    def validate(*_):return {'passed':True,'frames':[dict(path=str(frame),seconds=i*.5) for i in range(6)]}
    result=studio_ai.request_web_theme_design(project,'cue','字幕',settings,resume_design=design(),render_validator=validate)
    assert len(calls)==2 and len(calls[-1][0][1]['content'])==7
    assert result.quality['visual_review']['passed'] and 'scores' not in result.quality['visual_review']
