"""The procedural contract survives storage and still uses normal ownership."""
import copy
import pytest
from twobyteasr.caption_design.motion_ownership import MotionOwnershipError, motion_schedule
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.web_theme import WebThemeDocument


def fixture():
    return dict(version=2,runtime='gsap',buildMs=360,resolveMs=240,tracks=[dict(
        selector='.rig',phase='breathe',start=0,end=1,ease='none',
        **{'from':dict(x=0,y=0,rotation=0),'to':dict(x=0,y=0,rotation=0)},
        wiggle=dict(amplitudeX=1,amplitudeY=.65,rotation=.1,frequency=2.4,
                    seed=1703,intensity=.6,fadeInMs=180,fadeOutMs=180))])


def test_wiggle_storage_and_duration_policy_preserve_parameters():
    spec=fixture();spec['tracks'][0].update(durationMs=180,minCueMs=2000)
    theme=WebThemeDocument.from_dict(dict(name='冰内轻颤',palette=dict(primary='#FFFFFF',text='#FFFFFF'),
        stageHtml='',stageCss='',cueHtml='<div class="rig">{{text}}</div>',cueCss='.rig{color:white;font-family:var(--wt-font)}',motionSpec=spec))
    assert theme.clone().motion_spec==spec
    assert WebThemeDocument.from_dict(theme.to_dict()).motion_spec==spec
    long=motion_schedule(theme.motion_spec,6000)[0]
    short=motion_schedule(theme.motion_spec,1500)[0]
    assert long['end_ms']-long['start_ms']==180 and not long['omitted_for_duration']
    assert short['omitted_for_duration'] and short['procedural']=='wiggle'


def test_wiggle_does_not_bypass_alias_ownership_or_short_cue_checks():
    spec=fixture();spec['tracks'][0]['minCueMs']=2000
    extra=copy.deepcopy(spec['tracks'][0]);extra['selector']='.alias';spec['tracks'].append(extra)
    with pytest.raises(MotionOwnershipError):
        validate_motion_spec(spec,cue_html='<div class="rig alias">{{text}}</div>',duration_ms=500)


def test_wiggle_requires_explicit_finite_parameters_and_zero_base():
    for mutation in (
        lambda s:s['tracks'][0]['wiggle'].update(seed=True),
        lambda s:s['tracks'][0]['wiggle'].update(frequency=float('nan')),
        lambda s:s['tracks'][0]['wiggle'].update(amplitudeX=241),
        lambda s:s['tracks'][0]['to'].update(x=1),
        lambda s:s['tracks'][0].update(repeat=1),
        lambda s:s.update(version=1),
    ):
        spec=fixture();mutation(spec)
        with pytest.raises(ValueError):validate_motion_spec(spec)


def test_wiggle_can_share_adjacent_phases_without_conflicting():
    spec=fixture()
    for phase in ('build','resolve'):
        spec['tracks'].append(dict(selector='.rig',phase=phase,start=0,end=1,ease='none',
            **{'from':dict(x=3 if phase=='build' else 0),'to':dict(x=0 if phase=='build' else 3)}))
    validate_motion_spec(spec,cue_html='<div class="rig">{{text}}</div>')
