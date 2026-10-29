import json,subprocess
from pathlib import Path
import pytest
from twobyteasr.caption_design.caption_components import compose
from twobyteasr.caption_design.theme_motion import validate_motion_spec
from twobyteasr.caption_design.motion_ownership import motion_schedule

def test_v10_retains_v8_static_source_and_early_text_window():
    base=compose(dict(version=8));source=compose(dict(version=10))
    for field in ('cueHtml','cueCss','appearance','stageHtml','stageCss'):assert source.get(field)==base.get(field)
    spec=validate_motion_spec(source['motionSpec'],cue_html=source['cueHtml'])
    rows=motion_schedule(spec,6000)
    text=next(r for r in rows if r['selector']=='.nt-copy' and r['phase']=='build')
    assert text['end_ms']<=spec['buildMs']*.55
    assert 420<=max(r['end_ms'] for r in rows if r['phase']=='build')<=620
    assert 320<=max(r['end_ms'] for r in rows if r['phase']=='resolve')-min(r['start_ms'] for r in rows if r['phase']=='resolve')<=520
    assert all('clipPath' not in t['to'] for t in spec['tracks'])

def test_python_and_shared_js_schedules_match_all_cue_tiers(tmp_path):
    root=Path(__file__).resolve().parents[1];spec=compose(dict(version=10))['motionSpec']
    durations=[50,260,261,700,1500,1799,1800,2400,3000,3001,6000]
    path=tmp_path/'inputs.json';path.write_text(json.dumps(dict(spec=spec,durations=durations)),'utf8')
    script="const fs=require('fs'),vm=require('vm'),ctx={};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx);const x=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));process.stdout.write(JSON.stringify(x.durations.map(d=>ctx.__2byteMotionSchedule(x.spec,d))));"
    actual=json.loads(subprocess.check_output(['node','-e',script,str(root/'renderer/src/webThemeMotion.js'),str(path)],text=True))
    assert actual==[motion_schedule(spec,d) for d in durations]
    assert actual[4][0]['cue_tier']=='short' and actual[7][0]['cue_tier']=='compact' and actual[-1][0]['cue_tier']=='full'

def test_legacy_schedule_is_opt_in_and_invalid_profile_is_rejected():
    source=compose(dict(version=9));rows=motion_schedule(source['motionSpec'],1500)
    assert max(r['end_ms'] for r in rows if r['phase']=='build')<=160
    source['motionSpec']['timingProfile']='unknown'
    with pytest.raises(ValueError):validate_motion_spec(source['motionSpec'])
