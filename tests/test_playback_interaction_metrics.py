import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.acceptance.playback_interactions import ResizeCapture, StableViewport
from twobyteasr.diagnostics.playback_interaction_metrics import resize_results, seek_results


def write_rows(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def row(at, code):
    return dict(desktop_qpc_s=at,acquired_qpc_s=at+.001,copy_decode_ms=.2,
                accumulated_frames=1,frame_code=code,roi_hash=code)


def resize_fixture(tmp_path):
    records=[]
    for index,begin in enumerate((10.,30.1,50.1)):
        rect=[30,60,1213,683] if index!=1 else [30,60,1053,593]
        name=str(index)
        records.append(dict(id=name,directory='segments/'+name,roi_generation=index+1,
            viewport=rect,geometry_valid=True,capture_exit_code=0,errors=[],refresh_hz=60.,
            sample_start_qpc=begin,sample_end_qpc=begin+16,
            capture_readiness={'desktop.csv':{'ready_qpc_s':begin-.05,'viewport':rect}}))
        first=begin-.1
        rows=[row(first+i/60,round((first+i/60)*60)%4096) for i in range(1200)]
        write_rows(tmp_path/'segments'/name/'desktop.csv',rows)
    operations=[dict(kind='resize',id=str(index),at=at,geometry_stable_at=at+.05,
        prior_segment=str(index-1),segment=str(index)) for index,at in ((1,29.9),(2,49.9))]
    result={'media':{'tracks':1},'capture_segments':records,'operations':operations,
        'uncaptured_intervals':[{'start':26.,'end':30.1,'reason':'not measured'}]}
    spec={'source_fps':60.,'rate':1.,'barcode_y':710,'regions':[]}
    return result,spec


def seek_fixture(tmp_path, *, delay=.1, exact=True, stale=False, missing=False):
    samples=[]
    for step in range(-6,67):
        at=10+step/60
        if missing or at<10+delay:
            code=300+step
        else:
            code=1200+round((at-(10+delay))*60)+(0 if exact else 1)
        if stale and step==12:code=300
        samples.append(row(at,code))
    write_rows(tmp_path/'desktop.csv',samples)
    operation=dict(kind='seek',id='seek-1',at=10.,generation=5,gui_ms=2.,request_issued=True,
        source_path='C:/fixture.mp4',target_source_seconds=20.,before_source_seconds=5.,
        native_frame_ready_ms=90.,native_frame_witness={'status':'ready','source_generation':5})
    result={'media':{'path':'C:/fixture.mp4','tracks':1},'operations':[operation],
        'window':{'screen':'screen'},'environment':{'screens':[{'name':'screen','refresh_hz':60}]},
        'play_end_qpc':12.}
    spec={'phase':'seek','source_fps':60.,'rate':1.,'barcode_y':710,
          'frame_pts_ms':[index*1000/60 for index in range(6000)]}
    return result,spec,samples


def test_geometry_stability_resets_after_every_actual_rectangle_change():
    probe=StableViewport()
    assert not probe.observe((1,2,100,60),0)
    assert not probe.observe((1,2,100,60),.02)
    assert not probe.observe((1,2,101,60),.06)
    assert not probe.observe((1,2,101,60),.08)
    assert probe.observe((1,2,101,60),.12)


def test_resize_keeps_old_thresholds_and_separate_current_viewports(tmp_path):
    result,spec=resize_fixture(tmp_path)
    evidence=resize_results(result,tmp_path,spec)
    assert evidence['measurement_valid'] and evidence['performance_pass'] is True
    assert evidence['uncaptured_intervals']==result['uncaptured_intervals']
    assert evidence['segments'][0]['viewport']!=evidence['segments'][1]['viewport']
    for segment in evidence['segments']:
        assert segment['layers']['primary']['effective_seconds']==pytest.approx(16)
        assert segment['layers']['primary']['thresholds']['min_seconds']==15
    assert evidence['recoveries'][0]['regions']['primary']['delay_upper_bound_ms']<=250


@pytest.mark.parametrize('failure',['geometry','wrong_roi','short','missing_region'])
def test_resize_invalid_segments_cannot_inherit_good_fps(tmp_path,failure):
    result,spec=resize_fixture(tmp_path)
    segment=result['capture_segments'][1]
    if failure=='geometry':segment['geometry_valid']=False
    if failure=='wrong_roi':segment['capture_readiness']['desktop.csv']['viewport']=[0,0,100,100]
    if failure=='short':segment['sample_end_qpc']=segment['sample_start_qpc']+10
    if failure=='missing_region':result['media']['tracks']=2
    evidence=resize_results(result,tmp_path,spec)
    assert not evidence['measurement_valid'] and evidence['performance_pass']=='UNVERIFIED'


def test_late_capture_restart_is_unknown_not_a_false_latency_failure(tmp_path):
    result,spec=resize_fixture(tmp_path)
    result['operations'][0]['at']-=.25
    # Keep a fresh pre-operation frame, but delay the new ROI capture past 250 ms.
    evidence=resize_results(result,tmp_path,spec)
    measured=evidence['recoveries'][0]['regions']['primary']
    assert measured['performance_pass']=='UNVERIFIED'
    assert evidence['performance_pass']=='UNVERIFIED'


def test_seek_distinguishes_initial_old_motion_from_the_exact_target(tmp_path):
    result,spec,_=seek_fixture(tmp_path)
    evidence=seek_results(result,tmp_path,spec)
    assert evidence['measurement_valid'] and evidence['performance_pass'] is True
    operation=evidence['operations'][0]
    assert operation['first_pixel_change_ms']<operation['exact_target_frame_ms']
    assert operation['exact_target_frame_ms']==pytest.approx(100)
    assert not operation['first_pixel_change_is_target_proof']
    assert operation['threshold_ms']==250


@pytest.mark.parametrize('failure',['slow','no_seek','stale'])
def test_continuous_pixels_can_prove_a_seek_failure(tmp_path,failure):
    result,spec,_=seek_fixture(tmp_path,delay=.3 if failure=='slow' else .1,
                               missing=failure=='no_seek',stale=failure=='stale')
    evidence=seek_results(result,tmp_path,spec)
    assert evidence['measurement_valid'] and evidence['performance_pass'] is False


def test_native_ready_does_not_replace_missing_exact_target_pixels(tmp_path):
    result,spec,_=seek_fixture(tmp_path,exact=False)
    evidence=seek_results(result,tmp_path,spec)
    operation=evidence['operations'][0]
    assert operation['native_witness_current']
    assert operation['target_timeline_frame_ms']==pytest.approx(100)
    assert operation['exact_target_frame_ms'] is None
    assert evidence['performance_pass']=='UNVERIFIED'


def test_capture_gap_or_missing_native_generation_cannot_pass(tmp_path):
    result,spec,samples=seek_fixture(tmp_path)
    write_rows(tmp_path/'desktop.csv',[sample for sample in samples if not 10.02<_at(sample)<10.09])
    assert seek_results(result,tmp_path,spec)['performance_pass']=='UNVERIFIED'
    write_rows(tmp_path/'desktop.csv',samples)
    result['operations'][0]['native_frame_witness']['source_generation']=4
    assert seek_results(result,tmp_path,spec)['performance_pass']=='UNVERIFIED'


def _at(value):return float(value['desktop_qpc_s'])


def test_superseded_seek_has_no_250ms_obligation(tmp_path):
    result,spec,_=seek_fixture(tmp_path)
    result['operations'].insert(0,dict(kind='seek',id='older',at=9.94,generation=4))
    evidence=seek_results(result,tmp_path,spec)
    assert evidence['operations'][0]['status']=='superseded'
    assert evidence['operations'][0]['performance_pass']=='NOT_APPLICABLE'
    assert evidence['performance_pass'] is True


def test_new_roi_collector_waits_for_previous_process_and_uses_fresh_geometry(tmp_path,monkeypatch):
    from twobyteasr.acceptance import playback_interactions as module
    processes=[]
    class Process:
        returncode=None
        def __init__(self,command,**kwargs):self.command=command;processes.append(self)
        def poll(self):return self.returncode
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    screen=SimpleNamespace(name=lambda:'screen',refreshRate=lambda:60.)
    window=SimpleNamespace(width=lambda:1440,height=lambda:900,devicePixelRatioF=lambda:1.75,
                           screen=lambda:screen)
    rect=[30,60,1213,683]
    audit=ResizeCapture(window,None,tmp_path,{'seconds':65,'capture':'capture.exe','barcode_y':710},[],lambda:list(rect))
    try:
        first=audit._start('first')
        with pytest.raises(RuntimeError,match='previous desktop collector'):
            audit._start('overlap')
        processes[0].returncode=0
        rect[:]=[50,80,1053,593]
        second=audit._start('second')
        assert first['viewport']==[30,60,1213,683]
        assert second['viewport']==rect and second['roi_generation']==2
        assert processes[1].command[1:5]==list(map(str,rect))
    finally:
        for _,log in audit.owned:log.close()
