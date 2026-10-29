import copy
import json
import shutil
import subprocess
from pathlib import Path

from twobyteasr.caption_design.theme_revision_constraints import capture_constraints,enforce_constraints


def test_svg_material_bindings_can_name_geometry_without_relaxing_motion_selectors():
    import pytest
    from twobyteasr.caption_design.material_contract import validate_material_bindings
    from twobyteasr.caption_design.theme_dom import ThemeDOM
    html='<svg class="bear"><g><rect fill="#bee"/><circle fill="#123"/></g></svg>'
    validate_material_bindings({'selectors':['.bear rect']},{'cueHtml':html,'cueCss':''})
    assert ThemeDOM(html).targets('.bear rect') is None
    with pytest.raises(ValueError):
        validate_material_bindings({'selectors':['.bear path']},{'cueHtml':html,'cueCss':''})


def test_material_may_bind_conditional_focus_but_motion_cannot_depend_on_it():
    import pytest
    from twobyteasr.caption_design.material_contract import validate_material_bindings
    from twobyteasr.caption_design.theme_dom import ThemeDOM
    source=dict(cueHtml='<div class="copy" data-emphasis="滑雪">{{text}}</div>',
                cueCss='.copy .wt-focus{color:#effaff;text-shadow:0 1px #14334a}')
    validate_material_bindings({'selectors':['.copy .wt-focus']},source)
    assert not ThemeDOM(source['cueHtml']).targets('.copy .wt-focus')
    for markup in ('<div class="copy">{{text}}</div>',
                   '<div class="copy" data-emphasis="滑雪">{{words}}</div>',
                   '<div class="copy" data-emphasis="滑雪">literal</div>'):
        with pytest.raises(ValueError):validate_material_bindings({'selectors':['.copy .wt-focus']},dict(source,cueHtml=markup))


def test_default_type_is_editable_but_explicit_and_manual_values_survive():
    before={'appearance':{'fontSize':58,'fontWeight':700,'color':'#ffffff'},'cueHtml':'old','cueCss':'old'}
    current=copy.deepcopy(before);current['appearance']['color']='#ff0000'
    locks=capture_constraints(current,before,('appearance.fontWeight',))
    proposed={'appearance':{'fontSize':90,'fontWeight':400,'color':'#00ff00'},'cueHtml':'new','cueCss':'new'}
    value,changes=enforce_constraints(proposed,locks)
    assert value['appearance']=={'fontSize':90,'fontWeight':700,'color':'#ff0000'}
    assert value['cueHtml']=='new' and len(changes)==2
    assert before['appearance']['color']=='#ffffff' and proposed['appearance']['color']=='#00ff00'
    assert capture_constraints(before)==[]


def test_manual_source_keeps_its_topology_and_deleted_value_not_reintroduced():
    before={'appearance':{'fontSize':58,'color':'#fff'},'cueHtml':'old','cueCss':'.old{color:red}'}
    current=copy.deepcopy(before);current['cueCss']='.old{color:blue}';del current['appearance']['color']
    locks=capture_constraints(current,before)
    value,_=enforce_constraints({'cueHtml':'incompatible','cueCss':'new','appearance':{'fontSize':90,'color':'#000'}},locks)
    assert value['cueHtml']=='old' and value['cueCss']==current['cueCss']
    assert value['appearance']=={'fontSize':90}


def test_semantic_emphasis_keeps_exact_text_and_never_emphasizes_position():
    runtime=Path('renderer/src/webThemeClock.js').resolve()
    cases=[('这也能赢？！','赢'),('就差最后一下！','最后一下|最后'),('收看嗯','最后一下'),
           ('出发滑雪 GO 2026','滑雪|GO 2026'),('<>&😀\n最后一下！','最后一下')]
    code='require('+json.dumps(str(runtime))+');const cases='+json.dumps(cases,ensure_ascii=False)+';console.log(JSON.stringify(cases.map(([t,k])=>globalThis.__2byteEmphasisSegments(t,k))));'
    result=subprocess.run([shutil.which('node'),'-e',code],capture_output=True,text=True,encoding='utf8',check=True)
    rows=json.loads(result.stdout)
    assert all(''.join(p['text'] for p in row)==case[0] for row,case in zip(rows,cases))
    assert [p['text'] for p in rows[1] if p['focus']]==['最后一下']
    assert not any(p['focus'] for p in rows[2])
    assert [p['text'] for p in rows[3] if p['focus']]==['滑雪','GO 2026']


def test_art_adoption_preserves_manual_overrides_and_text_time_placement(tmp_path,monkeypatch):
    from tests.test_studio_style_controller import _page,_finish
    from tests.test_caption_creative_pipeline import candidates
    app,page=_page(tmp_path,monkeypatch)
    try:
        cue=page.project.cues[0]
        cue.appearance_override={'font_size':65,'primary_color':'#FF00AA'}
        before=(cue.text,cue.start_ms,cue.end_ms,copy.deepcopy(cue.appearance_override),copy.deepcopy(cue.transform))
        assert page._apply_web_theme(cue.id,candidates()[0]['generated_source'],preserve_overrides=True)
        assert (cue.text,cue.start_ms,cue.end_ms,cue.appearance_override,cue.transform)==before
        from twobyteasr.caption_design.theme_draft import ThemeDraft
        theme=candidates()[0]['generated_source']
        controller=page._theme_drafts();controller.project=page.project
        controller.current=ThemeDraft('revision',1,cue.id,cue.text,'','subtitle','test','test').with_theme(theme)
        controller.preserve_manual_overrides=True
        # Ordinary Adopt/Apply range buttons do not pass special kwargs.
        assert page._apply_web_theme(cue.id,theme)
        assert cue.appearance_override==before[3]
        different=copy.deepcopy(theme);different['name']='another deliberate style'
        assert page._apply_web_theme(cue.id,different)
        assert cue.appearance_override=={}
    finally:_finish(page)
