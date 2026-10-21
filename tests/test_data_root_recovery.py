import json
from pathlib import Path
import pytest


def test_all_user_roots_follow_override(tmp_path, monkeypatch):
    from twobyteasr import runtime_paths as rp
    from twobyteasr.storage import settings
    from twobyteasr.projects.studio_project import studio_data_root, project_library_root
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT', raising=False)
    monkeypatch.setenv(rp.USER_DATA_ENV, str(tmp_path/'chosen'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'other'))
    monkeypatch.setenv(rp.MODEL_ROOT_ENV, str(tmp_path/'models'))
    paths=rp.build_runtime_paths()
    assert settings.stable_settings_root()==paths.config_root
    assert studio_data_root()==paths.user_data_root/'SubtitleStudioPreview'
    assert project_library_root()==paths.project_root==paths.user_data_root/'Projects'


def test_corrupt_path_registration_preserved(tmp_path,monkeypatch):
    from twobyteasr import runtime_paths as rp
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT',raising=False)
    monkeypatch.delenv(rp.MODEL_ROOT_ENV,raising=False)
    monkeypatch.setenv(rp.USER_DATA_ENV,str(tmp_path))
    data=tmp_path/'2ByteASR';data.mkdir();f=data/'runtime_paths.json';f.write_text('{broken')
    with pytest.raises(RuntimeError,match='路径登记'):
        rp.bootstrap_runtime_paths(persist=True)
    assert f.read_text()=='{broken'


def test_partial_preferred_does_not_hide_complete_legacy(tmp_path,monkeypatch):
    from twobyteasr import runtime_paths as rp
    from twobyteasr.local_models.model_registry import scan_model_registry
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT',raising=False)
    monkeypatch.setenv('USERPROFILE',str(tmp_path))
    monkeypatch.setenv(rp.USER_DATA_ENV,str(tmp_path/'data'))
    repo=tmp_path/'repo';repo.mkdir();chosen=tmp_path/'chosen';(chosen/'M').mkdir(parents=True)
    (chosen/'M/a.bin').write_bytes(b'')
    (repo/'models/M').mkdir(parents=True);(repo/'models/M/a.bin').write_bytes(b'weights')
    (repo/'dependencies.lock.json').write_text(json.dumps({'models':{'m':{'path':'models/M','required_files':['a.bin']}}}))
    monkeypatch.setenv(rp.MODEL_ROOT_ENV,str(chosen));rp.reset_runtime_paths()
    monkeypatch.setenv(rp.INSTALL_ROOT_ENV,str(repo))
    registry=scan_model_registry(install_root=repo)
    assert registry.record('m').installation_path==repo/'models/M'
    assert rp.resolve_model_dir('M')==repo/'models/M'
    rp.reset_runtime_paths()


def test_empty_weights_not_installed(tmp_path):
    from twobyteasr.local_models.model_registry import _health_for, ModelHealth
    (tmp_path/'model.bin').touch()
    assert _health_for(tmp_path,('model.bin',),{},True)[0]==ModelHealth.PARTIAL


def test_bad_model_catalog_has_explicit_error(tmp_path):
    from twobyteasr.local_models.model_registry import scan_model_registry
    (tmp_path/'dependencies.lock.json').write_text('{broken')
    registry=scan_model_registry(install_root=tmp_path)
    assert '清单读取失败' in registry.error


def test_index_failure_reported_and_preserved(tmp_path):
    from twobyteasr.projects.studio_project import load_library_index
    f=tmp_path/'library-index.json';f.write_text('{broken');warnings=[]
    assert load_library_index(tmp_path,diagnostics=warnings)=={}
    assert warnings and '读取失败' in warnings[0]
    assert f.read_text()=='{broken'


def test_isolation_can_rebind_without_writing_previous_profile(tmp_path,monkeypatch):
    from twobyteasr.test_isolation import install
    from PySide6 import QtCore
    old=QtCore.QSettings
    try:
        for name in ('first','second'):
            monkeypatch.setenv('TWOBYTEASR_TEST_ROOT',str(tmp_path/'tmp'/name))
            install();s=QtCore.QSettings('2ByteASR','2ByteASR');s.setValue('test',name);s.sync()
            assert name in s.fileName()
        first=next((tmp_path/'tmp/first/qsettings').glob('*.ini'))
        assert 'first' in first.read_text() and 'second' not in first.read_text()
    finally:
        QtCore.QSettings=old


def test_unreadable_library_is_not_empty(tmp_path,monkeypatch):
    from twobyteasr.studio.studio_hub import StudioHubMixin
    import twobyteasr.studio.studio_hub as hub
    monkeypatch.setattr(hub,'project_library_root',lambda:tmp_path/'unavailable')
    monkeypatch.setattr(hub,'load_library_index',lambda **kwargs:{})
    class Reader:
        recent_project_records=lambda self:[]
    with pytest.raises(OSError,match='unavailable'):
        StudioHubMixin._project_library_records(Reader())
