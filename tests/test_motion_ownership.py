import copy
import pytest
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.motion_ownership import MotionOwnershipError, motion_schedule
from twobyteasr.caption_design.theme_dom import selector_targets

HTML='<div class="device"><div class="text alias">{{text}}</div><i class="lamp"></i></div>'

def original():
    def track(phase,start,end,a,b,**kw):
        return dict(selector='.text',phase=phase,start=start,end=end,ease='none',**{'from':{'opacity':a},'to':{'opacity':b}},**kw)
    return dict(version=1,runtime='gsap',buildMs=600,resolveMs=300,tracks=[
        track('build',0,.6,0,1),track('breathe',.6,1,1,.8,repeat=2,yoyo=True),track('resolve',0,.5,1,0)])

@pytest.mark.parametrize('duration',[50,100,101,300,500,1500,3000,6000])
def test_original_sequential_opacity_and_repeat_window(duration):
    spec=validate_motion_spec(original(),cue_html=HTML,duration_ms=duration)
    rows=motion_schedule(spec,duration)
    assert rows[1]['end_tick']==rows[2]['start_tick']
    assert rows[1]['repeat']<=2
    if duration==500:assert rows[1]['end_tick']==425000

def test_alias_conflict_names_actual_node_and_both_authored_tracks():
    spec=original();spec['tracks'].append(copy.deepcopy(spec['tracks'][0]))
    spec['tracks'][-1]['selector']='.device > .alias'
    with pytest.raises(MotionOwnershipError) as caught:validate_motion_spec(spec,cue_html=HTML)
    issue=caught.value.issues[0]
    assert issue['track_indices']==[0,3] and issue['node']==dict(index=1,tag='div',classes=['alias','text'])
    assert issue['property']=='opacity' and all(r['source']=='authored' for r in issue['intervals'])

def test_adjacent_same_phase_aliases_legal_but_one_tick_overlap_rejected():
    spec=original();a=spec['tracks'][0];a['end']=.5
    b=copy.deepcopy(a);b.update(selector='.alias',start=.5,end=1);spec['tracks'].append(b)
    validate_motion_spec(spec,cue_html=HTML,duration_ms=500)
    b['start']=.49999
    with pytest.raises(MotionOwnershipError):validate_motion_spec(spec,cue_html=HTML,duration_ms=500)

def test_selector_child_positions_match_elements_not_classes():
    assert selector_targets(HTML,'.device > .alias:first-child')=={1}
    assert selector_targets(HTML,'.device .lamp:nth-child(2)')=={2}
    assert selector_targets(HTML,'.device .lamp:nth-last-child(1)')=={2}
    assert selector_targets(HTML,'.text:last-child')==set()

def test_short_cue_cannot_hide_source_conflict_and_missing_node():
    spec=original();spec['tracks'].append(copy.deepcopy(spec['tracks'][0]))
    with pytest.raises(MotionOwnershipError):validate_motion_spec(spec,cue_html=HTML,duration_ms=50)
    spec=original();spec['tracks'][0]['selector']='.missing'
    with pytest.raises(MotionOwnershipError) as caught:validate_motion_spec(spec,cue_html=HTML)
    assert caught.value.issues[0]['category']=='motion_target'

def test_zero_phase_is_explicit_instantaneous_pose():
    spec=original();spec.update(buildMs=0,resolveMs=0)
    rows=motion_schedule(validate_motion_spec(spec,cue_html=HTML),3000)
    assert rows[0]['start_tick']==rows[0]['end_tick']==0
    assert rows[2]['start_tick']==rows[2]['end_tick']==3000000
