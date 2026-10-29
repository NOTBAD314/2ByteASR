from pathlib import Path
import pytest
from twobyteasr.storage.atomic_files import write_text_atomic

def test_transient_reader_lock_keeps_previous_file_until_replace(tmp_path,monkeypatch):
    path=tmp_path/'ledger.json';path.write_text('old')
    original=Path.replace;attempts=[]
    def replace(self,target):
        attempts.append(1)
        if len(attempts)<3:
            assert path.read_text()=='old'
            error=PermissionError('share lock');error.winerror=32;raise error
        return original(self,target)
    monkeypatch.setattr(Path,'replace',replace)
    write_text_atomic(path,'new')
    assert path.read_text()=='new' and len(attempts)==3

def test_persistent_lock_retains_last_good_record_and_staged_recovery(tmp_path,monkeypatch):
    path=tmp_path/'ledger.json';path.write_text('old')
    def replace(self,target):
        error=PermissionError('share lock');error.winerror=5;raise error
    monkeypatch.setattr(Path,'replace',replace)
    with pytest.raises(PermissionError):write_text_atomic(path,'new')
    assert path.read_text()=='old'
    assert next(tmp_path.glob('*.tmp')).read_text()=='new'
