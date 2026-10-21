import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.caption_design.authored_generation import generate_staged,normalize_directions
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
from twobyteasr.caption_design.caption_living_motion import compose,examples
from twobyteasr.caption_design.source_artifact import frame,from_theme,unframe
from twobyteasr.caption_design.artwork_recovery import inspect_source,save_recovery,saved_recovery,merge_completion
from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.caption_design.web_theme import WebThemeDocument
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.motion_ownership import motion_schedule


def theme():
    return WebThemeDocument.from_dict(dict(name='生命字幕',**compose(examples()[0]))).to_dict()


def test_materials_and_transition_grammar_combine_without_conflicting_tracks():
    for definition in examples():
        for transition in ('crt','score','foil'):
            value=compose(dict(definition,transition=transition))
            WebThemeDocument.from_dict(dict(name='组合',**value))
            assert len(value['motionSpec']['tracks'])<=32
            for ms in (900,1500,6000):
                validate_motion_spec(value['motionSpec'],cue_html=value['cueHtml'],duration_ms=ms)


@pytest.mark.parametrize('category,retries',[('render_timeout',1),('browser_startup',1),('render_error',1),('render_validation',0),('cancelled',0)])
def test_local_preview_retry_never_calls_model_or_retries_bad_art(category,retries):
    from twobyteasr.caption_design.design_recovery import preview_with_recovery
    calls=[];events=[]
    def render(*a,**kw):
        calls.append(1)
        if len(calls)==1:raise AIProviderError('模拟预览失败',category=category)
        return {'ready':True}
    if retries:
        assert preview_with_recovery(render,remaining=lambda:60,on_retry=lambda:events.append(1),cancel_check=lambda:False)=={'ready':True}
    else:
        with pytest.raises(AIProviderError):preview_with_recovery(render,remaining=lambda:60,on_retry=lambda:events.append(1),cancel_check=lambda:False)
    assert len(calls)==1+retries and len(events)==retries


@pytest.mark.parametrize('duration',[500,900,1500,6000,30000,120000])
def test_reading_life_covers_window_without_accelerating(duration):
    for example in examples():
        value=compose(example)
        spec=validate_motion_spec(value['motionSpec'],cue_html=value['cueHtml'],duration_ms=duration)
        rows=[r for r in motion_schedule(spec,duration) if r.get('sustain')]
        assert len(rows)==4
        for r in rows:
            assert r['cycle_ms']>=1100
            assert r['end_ms']==max(x['end_ms'] for x in motion_schedule(spec,duration) if x['phase']=='breathe')
        assert not any(r['phase']=='resolve' and r['selector']=='.bui-life' for r in spec['tracks'])


def test_python_and_browser_schedule_match(tmp_path):
    source=Path('renderer/src/webThemeMotion.js').resolve()
    spec=compose(examples()[0])['motionSpec']
    for ms in [500,1500,6000,30000,120000]:
        script=tmp_path/'schedule.cjs'
        script.write_text('require('+json.dumps(str(source))+');process.stdout.write(JSON.stringify(globalThis.__2byteMotionSchedule('+json.dumps(spec)+','+str(ms)+')));','utf8')
        result=subprocess.run(['tools/node/node.exe',str(script)],capture_output=True,text=True,check=True)
        assert json.loads(result.stdout)==motion_schedule(spec,ms)


@pytest.mark.parametrize('change',[{'repeat':1},{'durationMs':None},{'phase':'build'},{'sustain':'yes'}])
def test_sustain_rejects_ambiguous_clock(change):
    spec=compose(examples()[0])['motionSpec'];row=next(r for r in spec['tracks'] if r.get('sustain'))
    row.update(change)
    with pytest.raises(ValueError):validate_motion_spec(spec)


@pytest.mark.parametrize('fault',['zero','half_html','missing_motion','sections','twice'])
def test_generation_automatically_recovers_only_implementation(tmp_path,fault):
    source=theme();raw=from_theme(source,'test/A/v1');parts,_=unframe(raw,'test/A/v1')
    split=raw.index('bui-stock')+5;prefix=raw[:split]
    calls=[]
    class Client:
        def complete(self,messages,**kw):
            calls.append(dict(messages=messages,scope=kw['input_scope']))
            if len(calls)==1 or fault=='twice':
                if fault=='half_html':kw['on_stream_event']('delta',prefix)
                elif fault=='sections':kw['on_stream_event']('delta',raw.split('===PARAMETERS===')[0]+'===PARAMETERS===\n{"motionSpec":')
                elif fault=='missing_motion':return frame(dict(parts,PARAMETERS='{}'),'test/A/v1')
                raise AIProviderError('供应商有活动但正文未完成',category='provider_no_body' if fault in {'zero','twice'} else 'output_truncated')
            identity='test/A/completion-1'
            if fault=='half_html':return frame({'TAIL':raw[split:]},identity,kind='2BYTE-CONTINUATION/1')
            if fault in {'sections','missing_motion'}:return frame({'PARAMETERS':parts['PARAMETERS']},identity,kind='2BYTE-COMPLETION/1')
            return from_theme(source,identity)
    ledger=ThemeLedger(tmp_path/'job','CRT游戏弹窗字幕，全时段持续扫描')
    directions=normalize_directions({'candidates':[dict(name='既定设计',design='原说明必须保留，CRT屏幕与标签在同一框中配合') ]})
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{}},request_id='test',retained={'directions':directions})
    assert len(calls)==2
    assert calls[1]['scope']['kind']=='implementation_completion'
    assert ledger.value['directions']==directions
    concept=result.concepts[0]
    if fault=='twice':
        assert concept['technical_status']=='failed' and concept['automatic_completion']['status']=='failed'
    else:
        assert concept.get('technical_status')!='failed',concept.get('technical_errors')
        assert concept['authored_theme']['cueHtml']==source['cueHtml']
        assert concept['automatic_completion']['status']=='complete'
        stages=json.loads((tmp_path/'job/candidates/A/v1/checkpoints/index.json').read_text('utf8'))['stages']
        assert {'direction','description','structure','html','css','motion'}<=stages.keys()


@pytest.mark.parametrize('category',['cancelled','candidate_cancelled','request_too_large','auth','quota_exhausted','provider_auth','provider_rate_limit'])
def test_no_automatic_call_on_policy_or_cancel_failure(tmp_path,category):
    calls=[]
    class Client:
        def complete(self,*a,**k):
            calls.append(1);raise AIProviderError('停止',category=category)
    ledger=ThemeLedger(tmp_path,'字幕')
    dirs=normalize_directions({'candidates':[dict(name='原方向',design='保留说明并只完成当前实现的测试')]})
    try:generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{}},request_id='test',retained={'directions':dirs})
    except AIProviderError:assert category=='cancelled'
    assert len(calls)==1


def test_half_html_preserved_and_wrong_tail_identity_rejected(tmp_path):
    raw=from_theme(theme(),'old');cut=raw.index('bui-stock')+4
    (tmp_path/'provider-partial.txt').write_text(raw[:cut],'utf8');save_recovery(tmp_path,'old')
    recovery=saved_recovery(tmp_path)
    assert recovery['mode']=='continue_tail'
    result=merge_completion(frame({'TAIL':raw[cut:]},'new',kind='2BYTE-CONTINUATION/1'),recovery,'new')
    assert unframe(result,'new')[0]==unframe(raw,'old')[0]
    with pytest.raises(ValueError):merge_completion(frame({'TAIL':raw[cut:]},'wrong',kind='2BYTE-CONTINUATION/1'),recovery,'new')


def test_explicit_resume_is_one_call_without_hidden_second_request(tmp_path):
    calls=[]
    class Client:
        def complete(self,*a,**k):calls.append(1);raise AIProviderError('仍未完成',category='provider_no_body')
    result=generate_staged(ThemeLedger(tmp_path,'字幕'),Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{}},request_id='test',retained={'directions':normalize_directions({'candidates':[dict(name='原方向',design='保留说明并只完成当前实现的测试')]}),'explicit_recovery':True})
    assert len(calls)==1 and result.concepts[0]['technical_status']=='failed'


def test_invalid_component_preserves_direction_and_gets_one_source_completion(tmp_path):
    calls=[];source=theme()
    class Client:
        def complete(self,messages,**kw):
            calls.append(kw)
            return from_theme(source,'test/A/v1')
    saved=normalize_directions({'candidates':[dict(name='已有说明',design='保留这份通电说明，组件参数错误只补实现',components=dict(version=5,transition='invalid'))]})
    result=generate_staged(ThemeLedger(tmp_path,'CRT字幕'),Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{}},request_id='test',retained={'directions':saved})
    assert len(calls)==1 and calls[0]['input_scope']['kind']=='implementation_completion'
    assert result.concepts[0].get('technical_status')!='failed'
    assert result.concepts[0]['automatic_completion']['status']=='complete'


def test_empty_direction_response_gets_one_compact_completion_with_provenance(tmp_path):
    calls=[]
    class Client:
        def complete(self,messages,**kw):
            calls.append(kw)
            if len(calls)==1:raise AIProviderError('只有活动无正文',category='provider_no_body')
            return json.dumps({'candidates':[dict(name='已恢复方向',design='CRT屏幕通电与持续扫描，标签扣合后压线关机',components=examples()[0])]},ensure_ascii=False)
    ledger=ThemeLedger(tmp_path,'CRT字幕')
    result=generate_staged(ledger,Client(),SimpleNamespace(provider='fixture',model='test'),'unused',{'models':{'ai_design_mode':'drafts'}},request_id='test')
    assert len(calls)==2 and ledger.value['automatic_direction_completion']['attempt']==1
    assert 'directions-completion' in ledger.value['direction_response']['path']
    assert result.concepts[0].get('technical_status')!='failed'


def test_dialog_emits_distinct_recovery_actions():
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    concept=dict(id='A',name='未完成方向',technical_status='failed',technical_errors=[],authored_theme=theme())
    dialog=ThemeConceptDialog([concept],{})
    events=[];dialog.recovery_requested.connect(lambda ident,mode:events.append((ident,mode)))
    from twobyteasr.caption_design.design_recovery import recovery_actions
    labels={mode:label for mode,label,_ in recovery_actions(concept)}
    for mode in ['implementation','preview','rebuild']:
        next(a for a in dialog.more.menu().actions() if a.text()==labels[mode]).trigger()
    assert events==[('A',m) for m in ['implementation','preview','rebuild']]
    dialog.primary.click()
    assert events[-1]==('A',dialog._action)
    dialog.close()
