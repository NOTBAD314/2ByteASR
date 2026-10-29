import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from twobyteasr import runtime_paths as rp
from twobyteasr.local_models.model_root_settings import save_model_download_root


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv(rp.USER_DATA_ENV, str(tmp_path/'profile'))
    monkeypatch.delenv(rp.MODEL_ROOT_ENV, raising=False)
    old = tmp_path/'old'
    old.mkdir()
    rp.reset_runtime_paths()
    rp.set_model_root(old)
    yield tmp_path, old
    rp.reset_runtime_paths()


def test_root_save_restart_and_old_models_remain_discoverable(roots, monkeypatch):
    root, old = roots
    (old/'test-model').mkdir()
    (old/'test-model'/'weights').write_bytes(b'fixture')
    new = root/'other disk'/'Models'
    save_model_download_root(str(new))
    assert rp.get_runtime_paths().model_root == new
    assert (old/'test-model'/'weights').read_bytes() == b'fixture'
    monkeypatch.delenv(rp.MODEL_ROOT_ENV, raising=False)
    rp.reset_runtime_paths()
    assert rp.get_runtime_paths().model_root == new
    assert old/'test-model' in list(rp.iter_model_dir_candidates('test-model'))
    newer = root/'third disk'/'Models'
    save_model_download_root(str(newer))
    monkeypatch.delenv(rp.MODEL_ROOT_ENV, raising=False)
    rp.reset_runtime_paths()
    assert old/'test-model' in list(rp.iter_model_dir_candidates('test-model'))


@pytest.mark.parametrize('value', ['', 'relative/path'])
def test_invalid_root_keeps_configuration(roots, value):
    root, old = roots
    before = (rp.get_runtime_paths().config_root/'runtime_paths.json').read_bytes()
    with pytest.raises(ValueError): save_model_download_root(value)
    assert (rp.get_runtime_paths().config_root/'runtime_paths.json').read_bytes() == before
    assert rp.get_runtime_paths().model_root == old


def test_busy_and_file_destination_preserve_root(roots):
    root, old = roots
    with pytest.raises(ValueError): save_model_download_root(root/'new', owner=SimpleNamespace(_run_in_progress=True))
    assert not (root/'new').exists()
    bad = root/'file'; bad.write_bytes(b'x')
    with pytest.raises(OSError): save_model_download_root(bad)
    assert rp.get_runtime_paths().model_root == old
