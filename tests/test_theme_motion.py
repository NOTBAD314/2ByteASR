import copy
import pytest
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.web_theme import WebThemeDocument,parse_web_theme_sections


def spec():
    return dict(version=1,runtime='gsap',buildMs=320,resolveMs=180,tracks=[
        dict(selector='.lettering',phase='build',start=0,end=1,ease='power2.out',**{'from':dict(x=40,opacity=0),'to':dict(x=0,opacity=1)})])


@pytest.mark.parametrize('mutate',[
    lambda s:s['tracks'][0].update(selector='.subtitle-placement'),
    lambda s:s['tracks'][0]['to'].update(x=float('nan')),
    lambda s:s['tracks'][0]['to'].update(onComplete='alert(1)'),
    lambda s:s['tracks'].append(copy.deepcopy(s['tracks'][0])),
    lambda s:s['tracks'][0].update(ease='arbitraryFunction()'),
])
def test_unsafe_or_competing_motion_rejected(mutate):
    s=spec();mutate(s)
    with pytest.raises(ValueError):validate_motion_spec(s)


def test_motion_roundtrip_and_static_css_boundary():
    import json
    payload=dict(name='fixture',palette=dict(primary='#FFFFFF',text='#FFFFFF'),
        stageHtml='',stageCss='',cueHtml='<div class="lettering">{{words}}</div>',
        cueCss='.lettering{font-family:var(--wt-font)}',motionSpec=spec())
    doc=WebThemeDocument.from_dict(payload);assert doc.clone().motion_spec==doc.motion_spec
    assert parse_web_theme_sections('===MOTION_SPEC===\n'+json.dumps(spec()))['motionSpec']==spec()
    payload['cueCss']+=' .lettering{animation:wt-in 1s}'
    with pytest.raises(ValueError,match='静态CSS'):WebThemeDocument.from_dict(payload)
    payload['motionSpec']={}
    with pytest.raises(ValueError,match='version=1'):WebThemeDocument.from_dict(payload)


def test_visual_rejection_cannot_be_averaged_away():
    from twobyteasr.caption_design.theme_art_direction_v2 import SCORE_LABELS,validate_visual_checks
    review=dict(passed=True,checks={k:dict(passed=True,evidence='保持帧对应结构清晰可见') for k in SCORE_LABELS},defects=[])
    review['checks']['theme_relevance']=dict(passed=False,evidence='熊只剩两个耳点，不能辨认主题身份')
    result=validate_visual_checks(review)
    assert not result['passed'] and '熊只剩' in result['defects'][0] and 'scores' not in result


@pytest.mark.parametrize('repeat',[-1,25,True,1.5,float('inf')])
def test_material_repetition_must_be_bounded(repeat):
    s=spec();s['tracks'][0].update(phase='breathe',repeat=repeat)
    with pytest.raises(ValueError,match='repeat'):validate_motion_spec(s)


def test_repeat_and_pixel_step_material_roundtrip():
    s=spec();s['tracks'][0].update(phase='breathe',repeat=9,yoyo=True,ease='steps(8)',
        **{'from':{'backgroundPositionY':0},'to':{'backgroundPositionY':48}})
    assert validate_motion_spec(s)==s
    s['tracks'][0]['phase']='build'
    with pytest.raises(ValueError,match='阅读'):validate_motion_spec(s)


def test_fixed_back_recoil_keeps_authored_collision_intent():
    s=spec();s['tracks'][0]['ease']='back.out(1.7)'
    assert validate_motion_spec(s)==s
    for unsafe in ('back.out(100)','back.out(1.7);alert(1)','elastic.out(1,0.01)'):
        s['tracks'][0]['ease']=unsafe
        with pytest.raises(ValueError):validate_motion_spec(s)


@pytest.mark.parametrize('ease',['steps(1)','steps(33)','steps(-1)','steps(8);alert(1)'])
def test_pixel_step_ease_is_a_finite_whitelist(ease):
    s=spec();s['tracks'][0]['ease']=ease
    with pytest.raises(ValueError,match='easing'):validate_motion_spec(s)
