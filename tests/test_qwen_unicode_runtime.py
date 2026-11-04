"""The native reader receives an ASCII basename; no copies or changed weights."""
import os
from pathlib import Path
import pytest

from twobyteasr.recognition.qwen_runtime_compat import populate_native


@pytest.mark.skipif(os.name!='nt',reason='Windows native filename boundary')
def test_unicode_native_parameter_load_preserves_bytes_and_restores_directory(tmp_path):
    folder=tmp_path/'中文 环境';folder.mkdir()
    path=folder/'nagisa_v001.model';path.write_bytes(b'unchanged model bytes')
    cwd=Path.cwd()
    def native_reader(name):
        assert name.isascii() and name==path.name
        assert Path.cwd()==folder
        return Path(name).read_bytes()
    assert populate_native(native_reader,path)==b'unchanged model bytes'
    assert Path.cwd()==cwd and path.read_bytes()==b'unchanged model bytes'


@pytest.mark.skipif(os.name!='nt',reason='Windows native filename boundary')
def test_native_failure_restores_directory(tmp_path):
    folder=tmp_path/'中文';folder.mkdir()
    cwd=Path.cwd()
    def fail(name):raise RuntimeError('native failure')
    with pytest.raises(RuntimeError,match='native failure'):
        populate_native(fail,folder/'model.dat')
    assert Path.cwd()==cwd
