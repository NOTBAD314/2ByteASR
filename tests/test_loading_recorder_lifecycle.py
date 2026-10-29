import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest


def runner():
    path=Path(__file__).resolve().parents[1]/'scripts/verify_studio_loading.py'
    spec=importlib.util.spec_from_file_location('loading_recorder_runner',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def fixture(tmp_path,monkeypatch,*,gone=False,app_alive=False,mutation=None):
    executable=tmp_path/'tools/ffmpeg.exe';executable.parent.mkdir();executable.write_bytes(b'fixture')
    output=tmp_path/'loading-desktop-dda.mp4'
    command=[str(executable),'-f','lavfi','-i','ddagrab=output_idx=0',str(output)]
    receipt={'schema':1,'app_pid':92,'app_create_time':10.,'recorders':[{
        'role':'dda','pid':93,'parent_pid':92,'create_time':12.,'exe':str(executable),
        'output':str(output),'command':command}]}
    (tmp_path/'recorders.json').write_text(json.dumps(receipt),encoding='utf8')
    calls=[]
    class Process:
        def __init__(self,pid):self.pid=pid;self.stopped=False
        def create_time(self):return 10. if self.pid==92 else 14. if mutation=='created' else 12.
        def is_running(self):return True
        def exe(self):return str(tmp_path/'wrong.exe') if mutation=='exe' else str(executable)
        def ppid(self):return 91 if mutation=='parent' else 92
        def cmdline(self):return command[:-1]+[str(tmp_path/'other.mp4')] if mutation=='command' else command
        def terminate(self):self.stopped=True;calls.append(self.pid)
        def wait(self,timeout):
            if not self.stopped:raise psutil.TimeoutExpired(timeout,pid=self.pid)
            return 1
    processes={92:Process(92),93:Process(93)}
    def get(pid):
        if pid==92 and not app_alive or pid==93 and gone:raise psutil.NoSuchProcess(pid)
        return processes[pid]
    monkeypatch.setattr(psutil,'Process',get)
    return executable,calls


def test_only_matching_live_owned_orphan_is_terminated(tmp_path,monkeypatch):
    exe,calls=fixture(tmp_path,monkeypatch)
    result=runner().cleanup_owned_recorders(tmp_path,exe)
    assert calls==[93] and result['orphan_count']==1 and result['cleanup_complete']
    assert result['recorders'][0]['status']=='terminated_exact_owned_orphan'


def test_already_exited_recorder_is_not_touched(tmp_path,monkeypatch):
    exe,calls=fixture(tmp_path,monkeypatch,gone=True)
    result=runner().cleanup_owned_recorders(tmp_path,exe)
    assert not calls and result['orphan_count']==0
    assert result['recorders'][0]['status']=='already_exited'


@pytest.mark.parametrize('mutation',['created','exe','parent','command'])
def test_pid_reuse_or_identity_change_never_terminates_a_process(tmp_path,monkeypatch,mutation):
    exe,calls=fixture(tmp_path,monkeypatch,mutation=mutation)
    result=runner().cleanup_owned_recorders(tmp_path,exe)
    assert not calls and not result['cleanup_complete']
    assert result['recorders'][0]['status']=='not_touched_or_cleanup_failed'


def test_live_main_app_is_not_treated_as_crashed(tmp_path,monkeypatch):
    exe,calls=fixture(tmp_path,monkeypatch,app_alive=True)
    result=runner().cleanup_owned_recorders(tmp_path,exe)
    assert not calls and result['receipt_status']=='main_app_still_running'


def test_receipt_cannot_authorize_another_output_directory(tmp_path,monkeypatch):
    exe,calls=fixture(tmp_path,monkeypatch)
    path=tmp_path/'recorders.json';receipt=json.loads(path.read_text())
    receipt['recorders'][0]['output']=str(tmp_path.parent/'outside.mp4')
    path.write_text(json.dumps(receipt))
    result=runner().cleanup_owned_recorders(tmp_path,exe)
    assert not calls and not result['cleanup_complete']


def test_unfinalized_container_error_is_retained(tmp_path,monkeypatch):
    module=runner();(tmp_path/'loading-desktop-dda.mp4').write_bytes(b'partial')
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:SimpleNamespace(
        returncode=1,stdout='',stderr='moov atom not found'))
    result=module.validate_recordings(tmp_path,'ffprobe.exe',['loading-desktop-dda.mp4'])
    assert result[0]['container_readable'] is False
    assert result[0]['error']=='moov atom not found'
