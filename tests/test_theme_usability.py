import copy
from types import SimpleNamespace
import pytest
from twobyteasr.caption_design.theme_local_polish import polish_theme
from twobyteasr.caption_style.web_placement import cue_placement,scaled_placement
from twobyteasr.rendering.caption_proxy import eligible


def artwork():
    return dict(id='test-level-type',name='保留框体',cueHtml='<div class="plate"><div class="lean"><div class="copy" data-semantic-text="true">{{text}}</div></div><div class="flag"></div></div>',
        palette=dict(primary='#FF2010',text='#FFFFFF'),
        cueCss='.plate{background:#121318}.lean{transform:rotate(-2.2deg)}.flag{transform:rotate(8deg)}.copy{font-family:var(--wt-font);color:white}',
        motionSpec=dict(version=2,runtime='gsap',buildMs=350,resolveMs=200,tracks=[
            dict(selector='.plate',phase='build',start=0,end=1,ease='back.out(1.7)',from_={},to={})]))


def valid_artwork():
    a=artwork();a['motionSpec']['tracks'][0].pop('from_')
    a['motionSpec']['tracks'][0].update({'from':{'x':-72},'to':{'x':0}})
    return a


def test_local_finish_is_explicit_preserves_plate_and_source():
    original=valid_artwork();baseline=copy.deepcopy(original)
    out,receipt=polish_theme(original)
    assert original==baseline and out['cueHtml']==original['cueHtml']
    assert '.plate{background:#121318}' in out['cueCss']
    assert '.flag{transform:rotate(8deg)}' in out['cueCss']
    assert '.lean{transform:none}' in out['cueCss'] or '.lean{transform:}' in out['cueCss']
    assert 'linear-gradient' in out['cueCss'] and 'drop-shadow' in out['cueCss']
    assert out['motionSpec']['tracks'][0]['ease']=='power3.out'
    assert receipt['before_sha256']!=receipt['after_sha256'] and receipt['provider_calls']==0


def test_polish_without_semantic_binding_fails_without_modifying_source():
    a=valid_artwork();a['cueHtml']=a['cueHtml'].replace(' data-semantic-text="true"','')
    old=copy.deepcopy(a)
    with pytest.raises(ValueError,match='正文层'):polish_theme(a)
    assert a==old


def test_scaling_keeps_visual_anchor_and_relative_motion():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    p=SubtitleProject(media=StudioMedia(path='',width=1920,height=1080,duration_ms=3000),
        cues=[StudioCue('cue',0,3000,'等比缩放')]);p.validate();cue=p.cues[0]
    old=cue_placement(p,cue);a=(.52,.76);value=scaled_placement(p,cue,1.4,a)
    assert value['scaleX']==pytest.approx(old['scaleX']*1.4)
    assert value['scaleY']==pytest.approx(old['scaleY']*1.4)
    assert value['x']==pytest.approx(a[0]+(old['x']-a[0])*1.4)
    assert value['originX']==old['originX'] and not cue.transform


@pytest.mark.parametrize('explicit,safe,duration,expected',[(True,True,6,True),(True,False,6,False),
    (False,True,6,False),(True,True,16,False)])
def test_proxy_requires_cue_local_finite_clock(explicit,safe,duration,expected):
    assert eligible(SimpleNamespace(html='any-authored-cue',explicit_motion=explicit,proxy_safe=safe,duration=duration)) is expected
