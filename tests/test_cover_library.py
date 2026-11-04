import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import struct
import pytest
from twobyteasr.cover.cover_library import CoverLibrary


def psd():
    return b'8BPS\x00\x01'+bytes(6)+struct.pack('>HIIHH',3,720,1280,8,3)+bytes(20)


def test_template_master_revisions_and_drafts_separate(tmp_path,monkeypatch):
    library=CoverLibrary(tmp_path)
    first=library.save('系列 A',psd(),b'\x89PNG fixture',slots={'title':25,'background':1})
    original=library.asset(first,'psd').read_bytes()
    library.save_draft(psd()+b'draft',template=first['id'])
    assert library.asset(library.get(first['id']),'psd').read_bytes()==original
    second=library.save('系列 A 改版',psd()+b'revision',b'\x89PNG newer',key=first['id'])
    assert first['psd']!=second['psd'] and library.asset(first,'psd').read_bytes()==original
    copy=library.duplicate(second)
    assert copy['id']!=second['id']
    assert library.draft()['template']==first['id']
    import twobyteasr.cover.cover_library as module
    atomic=module.atomic_bytes
    def fail_pointer(path,data):
        if str(path).endswith('.json'):raise PermissionError('readonly')
        return atomic(path,data)
    monkeypatch.setattr(module,'atomic_bytes',fail_pointer)
    with pytest.raises(PermissionError):library.save('失败更新',psd()+b'bad',b'\x89PNG bad',key=first['id'])
    assert library.get(first['id'])==second


def test_draft_recovery_and_metadata_paths(tmp_path):
    library=CoverLibrary(tmp_path)
    for index in range(4):library.save_draft(psd()+bytes([index]),document='document')
    assert len(list(tmp_path.glob('draft-*.*')))==2
    assert CoverLibrary(tmp_path).draft()['document']=='document'
    library.dismiss_draft();assert library.draft() is None
    with pytest.raises(ValueError):library.get('../outside')
    with pytest.raises(ValueError):library.asset({'psd':'../outside'},'psd')
    with pytest.raises(ValueError):library.save('不是PSD',b'PNG',b'\x89PNG')
