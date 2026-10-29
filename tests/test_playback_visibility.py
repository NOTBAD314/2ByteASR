import importlib.util
import json
import os
from pathlib import Path

import pytest

from twobyteasr.acceptance.playback_visibility import PlaybackVisibility, visible_sample, visibility_summary


def coverage(root=44):
    return {'foreground':root,'foreground_owned':True,'all_points_owned':True,
            'points':[{'root':root,'owned':True} for _ in range(9)]}


def test_other_app_and_owned_modal_cannot_certify_the_video_roi():
    value=coverage()
    assert visible_sample(44,value)
    value['foreground']=99
    assert not visible_sample(44,value)
    value['foreground']=44
    value['points'][4]['root']=99
    assert not visible_sample(44,value)


def test_visibility_requires_complete_continuous_observation_coverage():
    rows=[{'at':index/10,'valid':True} for index in range(11)]
    assert visibility_summary(rows,0,1)['measurement_valid']
    rows[5]['valid']=False
    assert not visibility_summary(rows,0,1)['measurement_valid']
    assert visibility_summary(rows,0,1)['invalid_samples']==1
    assert not visibility_summary(rows[3:],0,1)['measurement_valid']
    assert not visibility_summary([{'at':0,'valid':True},{'at':1,'valid':True}],0,1)['measurement_valid']


def gate(tmp_path,monkeypatch,*,manual=False,fixed=True):
    from twobyteasr.acceptance import loading_native_probe
    class Probe:
        def coverage(self,root,bounds):
            assert list(bounds)==[10,20,330,200] or list(bounds)==[10,20,430,200]
            return coverage(root)
    monkeypatch.setattr(loading_native_probe,'NativeLoadingProbe',Probe)
    class Window:
        def winId(self):return 44
        def setWindowTitle(self,title):self.title=title
    rect=[10,20,320,180]
    result=PlaybackVisibility(Window(),tmp_path,lambda:list(rect),manual=manual,fixed_roi=fixed)
    return result,rect


def test_manual_gate_checks_pid_hwnd_and_does_not_fill_samples_while_waiting(tmp_path,monkeypatch):
    guard,_=gate(tmp_path,monkeypatch,manual=True)
    assert (tmp_path/'foreground-request.json').is_file()
    for _ in range(10):assert not guard.ready()
    assert guard.samples==[]
    path=tmp_path/'foreground-approved.json'
    path.write_text(json.dumps({'pid':os.getpid(),'hwnd':45}),encoding='utf8')
    assert not guard.ready()
    path.write_text(json.dumps({'pid':os.getpid(),'hwnd':44}),encoding='utf8')
    assert guard.ready()
    guard.sample()
    assert guard.samples[-1]['valid']


@pytest.mark.parametrize('fixed,expected',[(True,False),(False,True)])
def test_real_roi_change_is_invalid_except_in_explicit_resize_capture(tmp_path,monkeypatch,fixed,expected):
    guard,rect=gate(tmp_path,monkeypatch,fixed=fixed)
    assert guard.ready()  # Ordinary one-click mode needs no approval file.
    rect[2]=420
    guard.sample()
    assert guard.samples[-1]['valid'] is expected


def test_runner_cannot_overwrite_occlusion_with_good_frame_rate_or_resize_result():
    path=Path(__file__).resolve().parents[1]/'scripts/verify_playback_cadence.py'
    spec=importlib.util.spec_from_file_location('cadence_visibility_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result={'functional_pass':True,'measurement_valid':True,'performance_pass':True,
            'visibility':{'measurement_valid':False,'invalid_reasons':['occluded']}}
    module.require_visible_capture(result,{'desktop':'foreground','phase':'resize'})
    assert result['functional_pass'] is True
    assert result['measurement_valid'] is False and result['performance_pass']=='UNVERIFIED'
    result={'measurement_valid':True,'performance_pass':True}
    module.require_visible_capture(result,{'desktop':'foreground'})
    assert result['measurement_valid'] is False
