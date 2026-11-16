"""Data-only .app children dispatch before the normal GUI and retain real pipes."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import pytest


def entry():
    path=Path(__file__).resolve().parents[1]/'scripts/macos_launch.py'
    spec=importlib.util.spec_from_file_location('owned_macos_worker_entry',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('flag,worker',[
    ('--asr-api-worker','twobyteasr.providers.cloud_api_worker'),
    ('--subtitle-export-worker','twobyteasr.exports.subtitle_export_process'),
    ('--glossary-summary-worker','twobyteasr.glossary.summary_process'),
    ('--studio-qc-worker','twobyteasr.subtitle_rules.qc_process')])
def test_data_worker_reaches_protocol_without_normal_gui(tmp_path,monkeypatch,flag,worker):
    launch=entry()
    from twobyteasr.system import platform_macos,macos_compatibility
    from twobyteasr import runtime_paths
    calls=[]
    fake=ModuleType(worker);fake.main=lambda:calls.append(flag) or 0
    monkeypatch.setitem(sys.modules,worker,fake)
    ui=ModuleType('twobyteasr.app.ui')
    def forbidden_gui(*_args,**_kwargs):raise AssertionError('Data worker entered normal GUI')
    ui.run_desktop_app=forbidden_gui
    monkeypatch.setitem(sys.modules,'twobyteasr.app.ui',ui)
    monkeypatch.setattr(launch,'sys',SimpleNamespace(platform='darwin',argv=['2ByteASR',flag],
        stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr))
    monkeypatch.setattr(platform_macos,'configure_macos_paths',lambda _root:None)
    monkeypatch.setattr(runtime_paths,'user_data_root',lambda:tmp_path/'worker-data')
    monkeypatch.setattr(macos_compatibility,'write_startup_diagnostics',lambda *_args,**_kwargs:None)
    monkeypatch.setattr(macos_compatibility,'require_compatible',lambda *_args,**_kwargs:None)
    monkeypatch.chdir(tmp_path)
    assert launch.main()==0 and calls==[flag]


def test_windowed_worker_restores_parent_pipe_descriptors(monkeypatch):
    launch=entry();streams={};opened=[]
    monkeypatch.setattr(launch,'sys',SimpleNamespace(stdin=None,stdout=None,stderr=None))
    def fdopen(fd,mode,**kwargs):
        opened.append((fd,mode));streams[fd]=object();return streams[fd]
    monkeypatch.setattr(launch,'os',SimpleNamespace(dup=lambda fd:fd+100,fdopen=fdopen))
    fake=ModuleType('twobyteasr.glossary.summary_process');fake.main=lambda:0
    monkeypatch.setitem(sys.modules,fake.__name__,fake)
    assert launch.dispatch_pipe_worker(['app','--glossary-summary-worker'])==0
    assert set(opened)=={(100,'r'),(101,'w'),(102,'w')}
    assert launch.sys.stdin is streams[100] and launch.sys.stdout is streams[101] and launch.sys.stderr is streams[102]


def test_ordinary_and_malformed_arguments_do_not_enter_worker():
    launch=entry()
    for argv in (['app'],['app','movie.mp4'],['app','--glossary-summary-worker','extra']):
        assert launch.dispatch_pipe_worker(argv) is None
