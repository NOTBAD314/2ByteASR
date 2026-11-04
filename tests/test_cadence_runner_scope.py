import importlib.util
import argparse
from pathlib import Path
import pytest

def runner():
    path=Path(__file__).resolve().parents[1]/'scripts/verify_playback_cadence.py'
    spec=importlib.util.spec_from_file_location('cadence_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_primary_frame_rate_cannot_certify_an_unmeasured_second_track():
    module=runner()
    row={'media':{'tracks':2},'functional_pass':True,'measurement_valid':True,'performance_pass':True}
    module.annotate_measurement_scope(row)
    assert row['functional_pass'] and row['measurement_valid']
    assert row['primary_video_performance_pass'] is True
    assert row['performance_pass']=='UNVERIFIED'

@pytest.mark.parametrize('value',['../unsafe,0,0,.4,.4,710','primary,0,0,.4,.4,710','v2,.8,0,.4,.4,710','v2,0,0,nan,.4,710'])
def test_probe_region_must_stay_inside_the_video(value):
    with pytest.raises(argparse.ArgumentTypeError):runner().capture_region(value)

def test_missing_secondary_measurement_cannot_inherit_primary_pass(tmp_path):
    module=runner();region=module.capture_region('v2,.495,.075,.45,.45,710')
    row={'media':{'tracks':2},'functional_pass':True,'measurement_valid':True,'performance_pass':True,
         'desktop':{'measurement_valid':True,'performance_pass':True}}
    module.annotate_measurement_scope(row)
    module.attach_region_results(row,[region],{'regions':[],'errors':[]},tmp_path,source_fps=60,rate=1)
    assert row['functional_pass'] is True
    assert row['measurement_valid'] is False
    assert row['performance_pass']=='UNVERIFIED'
    assert row['primary_video_performance_pass'] is True

def test_secondary_failure_keeps_valid_measurement_and_fails_performance(tmp_path,monkeypatch):
    from twobyteasr.diagnostics import playback_metrics
    module=runner();region=module.capture_region('v2,.495,.075,.45,.45,710')
    (tmp_path/'v2-desktop.csv').write_text('header\n',encoding='utf8')
    row={'media':{'tracks':2},'functional_pass':True,'measurement_valid':True,'performance_pass':True,
         'desktop':{'measurement_valid':True,'performance_pass':True},'play_start_qpc':1,'play_end_qpc':21,
         'environment':{'screens':[{'name':'screen','refresh_hz':59.94}]},'window':{'screen':'screen'}}
    def measured(*args,**kwargs):
        assert kwargs['source_fps']==120 and kwargs['display_hz']==59.94
        return {'measurement_valid':True,'performance_pass':False}
    monkeypatch.setattr(playback_metrics,'desktop_cadence',measured)
    module.attach_region_results(row,[region],{'regions':[],'errors':[]},tmp_path,source_fps=60,rate=2)
    assert row['functional_pass'] is True and row['measurement_valid'] is True
    assert row['performance_pass'] is False

def test_seek_window_is_never_an_uninterrupted_cadence_pass(tmp_path):
    row={'functional_pass':True,'measurement_valid':True,'performance_pass':True}
    runner().annotate_phase_evidence(row,tmp_path,{'phase':'seek'})
    assert row['whole_window_video_performance_pass'] is True
    assert row['performance_pass']=='UNVERIFIED'

def test_first_frame_requires_the_paused_frame_to_be_observed(tmp_path):
    path=tmp_path/'desktop.csv'
    header='desktop_qpc_s,frame_code,copy_decode_ms\n'
    row={'play_start_qpc':10,'before':{'time-pos':5}}
    spec={'phase':'steady','barcode_y':710,'start':5,'source_fps':60}
    path.write_text(header+'10.02,301,1\n',encoding='utf8')
    runner().annotate_phase_evidence(row,tmp_path,spec)
    assert row['first_changed_video_frame']['measurement_valid'] is False
    path.write_text(header+'10.01,300,1\n10.03,301,1\n',encoding='utf8')
    runner().annotate_phase_evidence(row,tmp_path,spec)
    assert row['first_changed_video_frame']['delay_ms']==pytest.approx(30)
    assert row['first_changed_video_frame']['performance_pass'] is True


def test_first_frame_uses_the_declared_loop_counter_period(tmp_path):
    row={'play_start_qpc':10,'before':{'time-pos':35}}
    spec={'phase':'steady','barcode_y':710,'start':35,'source_fps':60,'frame_code_period':1800}
    (tmp_path/'desktop.csv').write_text('desktop_qpc_s,frame_code,copy_decode_ms\n9.99,300,1\n10.03,301,1\n',encoding='utf8')
    runner().annotate_phase_evidence(row,tmp_path,spec)
    assert row['first_changed_video_frame']['measurement_valid'] is True
    assert row['first_changed_video_frame']['delay_ms']==pytest.approx(30)


def test_same_file_cuts_use_project_progress_not_discontinuous_source_time():
    row={'functional_pass':False,'finished':True,'errors':[],
         'checks':{'initially_paused':True,'advanced_at_rate':False},
         'play_start_qpc':10,'play_end_qpc':30,'project_end_ms':39800,
         'telemetry':[{'preview_key':'primary','audio_request':{'clip_id':'a'}},
                      {'preview_key':'primary','audio_request':{'clip_id':'b'}}]}
    module=runner();spec={'phase':'steady','start':20,'rate':1}
    module.annotate_transport_evidence(row,spec)
    assert row['functional_pass'] is True
    assert row['source_progress_check_across_cuts'] is False
    assert row['project_progress']['error_ms']==-200
    row['project_end_ms']=30000
    module.annotate_transport_evidence(row,spec)
    assert row['functional_pass'] is False


def test_source_child_imports_its_own_version_after_pythonpath_is_sanitized(tmp_path,monkeypatch):
    import os,subprocess,sys
    current=tmp_path/'current';baseline=tmp_path/'baseline'
    for folder in (current,baseline):
        folder.mkdir();(folder/'worker_identity.py').write_text('VERSION='+repr(folder.name),encoding='utf8')
    module=runner();monkeypatch.setattr(module,'ROOT',current)
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    output=subprocess.check_output([sys.executable,'-c','import worker_identity; print(worker_identity.VERSION)'],
        cwd=module.entry_working_directory(baseline),env=env,text=True)
    assert output.strip()=='baseline'
    assert module.entry_working_directory(baseline,current/'app.exe')==current
