import copy
import pytest
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.motion_ownership import motion_schedule,MotionOwnershipError


def fixture():
    return dict(version=1,runtime='gsap',buildMs=800,resolveMs=500,tracks=[
        dict(selector='.scan',phase='breathe',start=0,end=1,ease='none',durationMs=2400,
             repeat=1,yoyo=True,**{'from':{'backgroundPositionY':0},'to':{'backgroundPositionY':24}})])


@pytest.mark.parametrize('duration,available',[(1500,975),(3000,1950),(6000,4700),(10000,4800)])
def test_realtime_cycles_clip_to_available_reading_time(duration,available):
    s=validate_motion_spec(fixture(),cue_html='<i class="scan"></i>',duration_ms=duration)
    row=motion_schedule(s,duration)[0]
    assert row['end_ms']-row['start_ms']==available
    assert row['cycle_ms']==2400 and row['repeat']==1
    assert s['tracks'][0]['durationMs']==2400


@pytest.mark.parametrize('bad',[True,0,119,30001,float('inf')])
def test_cadence_rejects_unbounded_or_invalid_values(bad):
    s=fixture();s['tracks'][0]['durationMs']=bad
    with pytest.raises(ValueError):validate_motion_spec(s)


def test_legacy_track_retains_total_window_repetition():
    s=fixture();del s['tracks'][0]['durationMs']
    row=motion_schedule(validate_motion_spec(s),10000)[0]
    assert row['end_ms']-row['start_ms']==8700 and 'cycle_ms' not in row
    s['tracks'][0]['phase']='build';s['tracks'][0]['repeat']=0;s['tracks'][0]['durationMs']=300
    with pytest.raises(ValueError,match='阅读'):validate_motion_spec(s)


def test_conflicts_use_actual_material_time_but_not_beyond_it():
    s=fixture();s['tracks'][0].update(durationMs=120,repeat=0)
    second=copy.deepcopy(s['tracks'][0]);second.update(start=.1,end=1);s['tracks'].append(second)
    validate_motion_spec(s,duration_ms=6000)
    with pytest.raises(MotionOwnershipError):validate_motion_spec(s,duration_ms=1500)
