import copy
import pytest
from twobyteasr.caption_design.theme_design_preservation import protect_structure,validate_surface_revision
from twobyteasr.caption_design.theme_revision_constraints import enforce_constraints

def sample():
    return dict(cueHtml='<div class="frame"><svg class="bear"></svg><b>{{text}}</b></div>',
        stageHtml='',stageCss='',cueCss='.frame{width:800px;opacity:1;background:#123}.bear{width:180px}',
        motionSpec={'tracks':[{'selector':'.bear','phase':'breathe'}]})

def test_material_revision_keeps_approved_character_frame_and_motion_but_allows_surface():
    old=sample();proposed=copy.deepcopy(old)
    proposed['cueHtml']='<b>{{text}}</b>';proposed['motionSpec']={'tracks':[]}
    proposed['cueCss']=old['cueCss'].replace('background:#123','background:linear-gradient(#246,#123);box-shadow:0 3px 6px #123')
    preserved,changes=enforce_constraints(proposed,protect_structure(old,[]))
    validate_surface_revision(old,preserved)
    assert preserved['cueHtml']==old['cueHtml'] and preserved['motionSpec']==old['motionSpec']
    assert len(changes)==2 and 'linear-gradient' in preserved['cueCss']

@pytest.mark.parametrize('css',['.frame{width:800px;opacity:0;background:#123}.bear{width:180px}',
    '.frame{width:800px;opacity:1;background:#123}.bear{width:18px}',
    '.frame{width:800px;opacity:1;background:#123}.bear{width:180px}.bear{display:none}'])
def test_material_revision_rejects_removing_frame_or_shrinking_character(css):
    old=sample();changed=dict(old,cueCss=css)
    with pytest.raises(ValueError,match='构图或可见性'):validate_surface_revision(old,changed)


def test_existing_authored_theme_can_be_refined_without_legacy_concept_tags(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from tests.test_caption_creative_pipeline import candidates
    from twobyteasr.caption_design import studio_ai as api
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    theme=copy.deepcopy(candidates()[0]['generated_source'])
    theme['concept']='带框的印刷作品，现有构图与动作已经选定。'
    theme=WebThemeDocument.from_dict(theme).to_dict()
    proposed=copy.deepcopy(theme);proposed['cueCss']+='\n.foil-shimmer{stroke-linecap:round}'
    # A provider may echo reformatted protected markup above the generic size
    # limit. Restore the selected source before validating that unused echo.
    proposed['cueHtml']=' ' * 9000 + '<div>{{text}}</div>'
    proposed['motionSpec']={'tracks':[]}
    proposed['appearance']={**theme['appearance'],'fontFamily':'var(--wt-font)','fontSize':'var(--wt-size)'}
    sent=[]
    class Provider:
        provider_id='test'
        def complete(self,messages,**kwargs):sent.append(messages);return json.dumps(proposed)
    monkeypatch.setattr(api,'provider_for_stage',lambda *a,**k:Provider())
    monkeypatch.setattr(api.GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='test',credential_ready=True))
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:SimpleNamespace(capabilities=lambda:SimpleNamespace(vision=False)))
    monkeypatch.setattr(api,'_persist_ai_design_trace',lambda trace:str(tmp_path/'trace.json'))
    result=api.refine_web_theme_design(theme,'增强框边材质',runtime_settings={'models':{}},art_revision=True)
    assert result.source=='refined',result.message
    assert result.theme['motionSpec']==theme['motionSpec'] and result.theme['cueHtml']==theme['cueHtml']
    assert 'stroke-linecap:round' in result.theme['cueCss']
    assert len(sent)==1 and '主题框体' in sent[0][1]['content']


def test_section_font_weight_and_explicit_current_font_references_survive():
    from twobyteasr.caption_design.web_theme import parse_web_theme_sections,WebThemeDocument
    from twobyteasr.caption_design.theme_design_preservation import resolve_appearance_references
    parsed=parse_web_theme_sections('===APPEARANCE===\nfontFamily=var(--wt-font)\nfontSize=var(--wt-size)\nfontWeight=900')
    old={'appearance':{'fontFamily':'ZCOOL KuaiLe','fontSize':64,'fontWeight':400}}
    restored,changes=resolve_appearance_references(parsed,old)
    assert restored['appearance']=={'fontFamily':'ZCOOL KuaiLe','fontSize':64,'fontWeight':900}
    assert len(changes)==2
    from tests.test_caption_creative_pipeline import candidates
    broken=copy.deepcopy(candidates()[0]['generated_source']);broken['appearance']={'fontFamily':'var(--wt-font)','fontSize':64}
    with pytest.raises(ValueError,match='fontFamily'):WebThemeDocument.from_dict(broken)


def test_directed_motion_revision_loads_current_guidance_without_surface_freeze(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from tests.test_caption_creative_pipeline import candidates
    from twobyteasr.caption_design import studio_ai as api
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.caption_design.web_theme import WebThemeDocument
    theme=WebThemeDocument.from_dict(copy.deepcopy(candidates()[0]['generated_source'])).to_dict()
    proposed=copy.deepcopy(theme);proposed['motionSpec']['buildMs']=701
    proposed['cueHtml']='<div class="revision-frame">'+theme['cueHtml']+'</div>'
    proposed['cueCss']+=' .revision-frame{position:absolute;inset:0}'
    sent=[];traces=[]
    class Provider:
        provider_id='test'
        def complete(self,messages,**kwargs):sent.append(messages);return json.dumps(proposed)
    monkeypatch.setattr(api,'provider_for_stage',lambda *a,**k:Provider())
    monkeypatch.setattr(api.GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='test',credential_ready=True))
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:SimpleNamespace(capabilities=lambda:SimpleNamespace(vision=False)))
    monkeypatch.setattr(api,'_persist_ai_design_trace',lambda trace:(traces.append(copy.deepcopy(trace)) or str(tmp_path/'trace.json')))
    result=api.refine_web_theme_design(theme,'明确修改已否定主动作，保留框体、角色与材质',runtime_settings={'models':{}},art_revision=False)
    assert result.source=='refined',result.message
    assert result.theme['cueHtml']==proposed['cueHtml'] and result.theme['motionSpec']['buildMs']==701
    assert len(sent)==1 and '材料稳定性与主题事件' in sent[0][1]['content'] and 'durationMs' in sent[0][1]['content']
    assert traces[0]['revision_kind']=='directed_repair'
    assert traces[0]['design_skills']['version'].endswith('20260921.3')
