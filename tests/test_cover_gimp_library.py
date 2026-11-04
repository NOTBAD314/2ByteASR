import json
import struct
from pathlib import Path
import pytest
from twobyteasr.cover.cover_gimp_library import GimpCoverLibrary,check_xcf
from twobyteasr.cover.cover_library import CoverLibrary


def xcf(extra=b''):
    # Storage failure tests only; actual GIMP opens are in the runtime audit.
    return b'gimp xcf v013\0'+struct.pack('>III',1280,720,0)+extra


def png():return b'\x89PNG\r\n\x1a\nfixture'


def test_migration_backup_and_failed_pointer_keep_old_master(tmp_path,monkeypatch):
    old=CoverLibrary(tmp_path);entry=old.entries()[0]
    entry['favorite']=True;entry['used']=12345;old.metadata(entry)
    old.save_draft(old.asset(entry,'psd').read_bytes(),document='legacy')
    original=old.asset(entry,'psd').read_bytes()
    library=GimpCoverLibrary(tmp_path)
    receipt=json.loads((tmp_path/'gimp-migration-backup.json').read_text(encoding='utf8'))
    backup=Path(receipt['backup'])
    assert (backup/'templates'/entry['psd']).read_bytes()==original
    assert (backup/'draft.json').exists() and library.draft()['document']=='legacy'
    migrated=library.save_xcf('migrated',xcf(),png(),key=entry['id'],slots={'title':'stable-id'})
    assert migrated['favorite'] and migrated['used']==12345
    assert library.asset(migrated,'psd').read_bytes()==original
    import twobyteasr.cover.cover_gimp_library as module
    write=module.atomic_bytes
    def fail(path,data):
        if path.suffix=='.json':raise PermissionError('unwritable pointer')
        write(path,data)
    monkeypatch.setattr(module,'atomic_bytes',fail)
    import twobyteasr.cover.cover_library as base
    monkeypatch.setattr(base,'atomic_bytes',fail)
    with pytest.raises(PermissionError):library.save_xcf('bad update',xcf(b'changed'),png(),key=entry['id'])
    assert library.get(entry['id'])==migrated
    assert library.asset(migrated,'xcf').read_bytes()==xcf()


def test_drafts_are_independent_and_do_not_mutate_templates(tmp_path):
    library=GimpCoverLibrary(tmp_path)
    entry=library.save_xcf('master',xcf(),png())
    for index in range(4):library.save_xcf_draft('a'*32,xcf(bytes([index])),template=entry['id'])
    library.save_xcf_draft('b'*32,xcf(b'other'))
    assert len(library.drafts())==2
    assert len(list(library.recovery.glob('a' *32+'-*.xcf')))==2
    assert library.asset(entry,'xcf').read_bytes()==xcf()
    library.dismiss_xcf_draft('a'*32)
    assert [row['document'] for row in library.drafts()]==['b'*32]
    duplicate=library.duplicate(entry)
    assert duplicate['id']!=entry['id'] and duplicate['xcf']!=entry['xcf']
    with pytest.raises(ValueError):library.save_xcf_draft('../foreign',xcf())
    with pytest.raises(ValueError):check_xcf(b'PNG renamed as XCF')
