"""Real registry publications and controlled cross-process generation races."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from twobyteasr.system import runtime_registry as registry

ROOT=Path(__file__).resolve().parents[1]


def entry(root, role, generation):
    folder=root/role/generation
    python=registry.runtime_python_path(folder)
    python.parent.mkdir(parents=True)
    python.write_bytes(b'inert test interpreter; never executed')
    (folder/'pyvenv.cfg').write_text('home = fixture\n','utf8')
    return python


@pytest.fixture
def managed(tmp_path,monkeypatch):
    root=tmp_path/'managed'
    monkeypatch.setattr(registry,'runtimes_root',lambda:root)
    for values in registry._ROLE_ENV_OVERRIDES.values():
        for name in values:monkeypatch.delenv(name,raising=False)
    monkeypatch.delenv('TWOBYTEASR_DEVELOPER_RUNTIMES',raising=False)
    registry.reset_runtime_registry_cache()
    return root


@pytest.mark.parametrize('explicit_registration',[False,True])
def test_old_resolution_cannot_overwrite_new_publication(managed,monkeypatch,explicit_registration):
    old=entry(managed,'main','old');new=entry(managed,'main','new')
    registry.register_runtime('main',str(old))
    original=registry._candidate_pythons
    def interleave(role):
        candidates=original(role)
        registry.register_runtime(role,str(new))
        return candidates
    monkeypatch.setattr(registry,'_candidate_pythons',interleave)
    kwargs={'register':True} if explicit_registration else {}
    assert registry.resolve_runtime_python('main',**kwargs)==str(old)
    assert registry.load_registry()['main']['python_executable']==str(new)
    assert old.is_file() and new.is_file()


def test_ordinary_discovery_does_not_create_registry_or_lock(managed):
    python=entry(managed,'main','generation')
    # An explicit runtime override can select a candidate without publishing it.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('TWOBYTEASR_MAIN_PYTHON',str(python))
        assert registry.resolve_runtime_python('main')==str(python)
    assert not registry.registry_path().exists()
    assert not registry.registry_path().with_suffix('.lock').exists()


CHILD=r'''
import os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from twobyteasr.system import runtime_registry as registry
root=Path(sys.argv[2]);registry.runtimes_root=lambda:root
role,python,marker=sys.argv[3],sys.argv[4],Path(sys.argv[5])
if role=='crash':
    with registry._publication_lock():
        marker.write_text('locked','ascii')
        os._exit(23)
if role=='main':
    original=registry._save_registry
    def slow(entries):
        marker.write_text('main read the registry','ascii')
        time.sleep(.5)
        original(entries)
    registry._save_registry=slow
registry.register_runtime(role,python)
'''


def launch(tmp_path,managed,role,python,marker):
    script=tmp_path/'publish-child.py';script.write_text(CHILD,'utf8')
    return subprocess.Popen([sys.executable,'-B',str(script),str(ROOT),str(managed),role,str(python),str(marker)],
        cwd=tmp_path,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def finish(process):
    try:
        out,err=process.communicate(timeout=15)
        assert process.returncode==0,(out,err)
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)


def test_main_and_moss_publish_without_losing_each_other(managed,tmp_path):
    main=entry(managed,'main','new');moss=entry(managed,'moss','new')
    marker=tmp_path/'main-entered'
    first=launch(tmp_path,managed,'main',main,marker)
    second=None
    try:
        deadline=time.monotonic()+10
        while not marker.exists() and time.monotonic()<deadline and first.poll() is None:time.sleep(.02)
        assert marker.exists()
        second=launch(tmp_path,managed,'moss',moss,tmp_path/'moss-marker')
        finish(first);finish(second)
    finally:
        for process in (first,second):
            if process is not None and process.poll() is None:process.kill();process.wait(timeout=5)
    values=registry.load_registry()
    assert values['main']['python_executable']==str(main)
    assert values['moss']['python_executable']==str(moss)


def test_crashed_publisher_releases_os_lock(managed,tmp_path):
    python=entry(managed,'main','new')
    process=launch(tmp_path,managed,'crash',python,tmp_path/'locked')
    try:
        process.communicate(timeout=10)
        assert process.returncode==23
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
    registry.register_runtime('main',str(python))
    assert registry.load_registry()['main']['python_executable']==str(python)


def test_failed_publication_retains_previous_registration(managed,monkeypatch):
    old=entry(managed,'main','old');new=entry(managed,'main','new')
    registry.register_runtime('main',str(old));before=registry.registry_path().read_bytes()
    def fail(entries):raise OSError('injected publication failure')
    with monkeypatch.context() as patch:
        patch.setattr(registry,'_save_registry',fail)
        with pytest.raises(OSError,match='injected'):registry.register_runtime('main',str(new))
    assert registry.registry_path().read_bytes()==before
    registry.register_runtime('main',str(new))
    assert registry.load_registry()['main']['python_executable']==str(new)
