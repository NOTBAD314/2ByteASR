import copy,json,os,subprocess,sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from twobyteasr.caption_design.caption_design_trials import CaptionPreferences,local_specs,validate_spec,compile_web_theme,request_static_options,design_style_checks
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue


def test_local_specs_have_distinct_structures_and_fonts_and_dark_first_stroke():
    rows=local_specs()
    assert len({r['backplate']['structure'] for r in rows})==3
    assert len({r['typography']['family'] for r in rows})==3
    for row in rows:
        assert design_style_checks(row)['inner_is_theme_dark']
        theme=compile_web_theme(row)
        assert 'aria-hidden="true"' in theme['cueHtml']
        assert theme['cueHtml'].count('data-semantic-text')==1
        assert 'nowrap' in theme['cueCss'] and '{{text}}' in theme['cueHtml']
        assert '<script' not in theme['cueHtml'] and 'url(data:' not in theme['cueCss']


def test_schema_and_visual_grade_are_not_conflated():
    value=local_specs()[0];value['fill_gradient']['colors'][-1]='#101010'
    assert validate_spec(value)
    assert design_style_checks(value)['gradient_low_stop_luminance']<.02
    value['unexpected_script']='alert(1)'
    with pytest.raises(Exception):validate_spec(value)


def test_preferences_persist_and_rejected_design_never_becomes_positive(tmp_path):
    path=tmp_path/'prefs.json';store=CaptionPreferences(path)
    for accepted,rating,label in ((True,9,'positive-fixture'),(False,10,'rejected-fixture'),(True,6,'low-score-fixture')):
        store.record_choice(candidate_id=label,rating=rating,accepted=accepted,provider='TEST ONLY',model='fixture',
            spec=local_specs()[0],screenshots=['fixture.png'],notes='automated fixture; not an actual user rating',verification={'fixture':True})
    assert [r['candidate_id'] for r in store.positive_references()]==['positive-fixture']
    # A genuinely new interpreter reads only the serialized file.
    code='import json,sys; from twobyteasr.caption_design.caption_design_trials import CaptionPreferences; print(json.dumps(CaptionPreferences(sys.argv[1]).positive_references()))'
    result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0
    assert json.loads(result.stdout)[0]['candidate_id']=='positive-fixture'
    assert json.loads(path.read_text('utf8'))['choices'][1]['accepted'] is False


def test_normal_studio_generation_uses_spec_not_provider_html(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.providers import provider_service, provider_registry
    spec=local_specs()[0];spec['backplate']['structure']='pressed_ticket'
    calls=[]
    class Client:
        def complete(self,messages,**kwargs):
            calls.append((messages,kwargs));return json.dumps(spec)
    monkeypatch.setattr(provider_service.GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a:Client())
    monkeypatch.setattr(provider_registry.GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a:SimpleNamespace(provider='fixture',model='fixture'))
    project=SubtitleProject(media=StudioMedia('fixture.mp4'),cues=[StudioCue('c',0,3000,'测试字幕')])
    result=request_static_options(project,'c','文字和材质',{})
    assert len(calls)==1 and calls[0][1]['timeout']<90
    assert len(result.concepts)==3 and result.selected_concept_id==''
    assert sum(c['provider']=='local_rules' for c in result.concepts)==2
    assert all(c['hero_theme'] and c['design_spec'] for c in result.concepts)
    assert project.cues[0].style_id=='default'
