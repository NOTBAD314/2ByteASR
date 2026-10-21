from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import time
import pytest
from twobyteasr.runtime_paths import RuntimePaths
from twobyteasr.storage.storage_service import StorageService, safe_path, GiB


@pytest.fixture
def service(tmp_path):
    data=tmp_path/'data';cache=data/'cache';cache.mkdir(parents=True)
    models=data/'models';models.mkdir()
    paths=RuntimePaths(tmp_path,data,models,cache,data/'projects',data,data/'logs',tmp_path/'renderer',data/'tmp')
    return StorageService(paths,roots=[cache],state_root=data/'storage')


def add(service,name='a.bin',category='preview',**kw):
    path=service.roots[0]/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'abcd'*1024)
    assert service.register(path,category,producer='isolated_fixture',**kw)
    return path


def test_unknown_and_evidence_protected_and_scan_does_not_touch(service):
    path=add(service);add(service,'raw.json','evidence',rebuild='remote')
    (service.roots[0]/'user.mp4').write_bytes(b'user')
    first=service.scan(include_models=False);second=service.scan(include_models=False)
    assert {i.path:i.last_used for i in first.items}=={i.path:i.last_used for i in second.items}
    result=service.clean(first.items)
    assert [i['path'] for i in result.deleted]==[str(path)]
    assert len(result.skipped)==2 and result.logical_removed_bytes==4096


def test_active_lease_and_recheck_protect(service):
    path=add(service)
    before=service.scan(include_models=False)
    with service.lease(path):
        assert not service.scan(include_models=False).items[0].cleanable
        assert service.clean(before.items).skipped
    assert service.clean(service.scan(include_models=False).items).deleted


def test_changed_file_and_source_missing_protect(service,tmp_path):
    source=tmp_path/'source.flv';source.write_bytes(b'original')
    path=add(service,'proxy.mp4','media',source=str(source))
    scan=service.scan(include_models=False);source.unlink()
    assert service.clean(scan.items).skipped and path.exists()
    source.write_bytes(b'original');scan=service.scan(include_models=False);path.write_bytes(b'changed')
    assert service.clean(scan.items).skipped and path.exists()


def test_cancel_partial_failure_retry_and_repeat(service,monkeypatch):
    a=add(service,'a.png');b=add(service,'b.png');scan=service.scan(include_models=False)
    cancel=threading.Event();cancel.set()
    assert service.scan(cancel).cancelled
    assert service.clean(scan.items,cancel).cancelled
    unlink=Path.unlink
    def controlled(self,*args,**kwargs):
        if self==a:raise PermissionError('controlled occupied file')
        return unlink(self,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',controlled)
    result=service.clean(scan.items)
    assert len(result.pending)==1 and len(result.deleted)==1 and a.exists() and not b.exists()
    monkeypatch.setattr(Path,'unlink',unlink)
    assert service.clean(service.scan(include_models=False).items).deleted
    assert service.clean(scan.items).skipped and service.clean(scan.items).logical_removed_bytes==0


def test_budget_age_and_actual_access(service):
    a=add(service,'old.png');b=add(service,'recent.png');c=add(service,'protected.png','evidence')
    with service._db() as db:db.execute('UPDATE entries SET used=? WHERE path=?',(time.time()-8*86400,str(a)))
    service.save_policy(dict(budget_bytes=4096,retention_days=7))
    scan=service.scan(include_models=False)
    assert [i.path for i in service.recommended(scan)]==[str(a)]
    service.touch(a)
    assert len(service.recommended(service.scan(include_models=False)))==1  # budget eviction, never evidence
    service.save_policy(dict(budget_bytes=10*GiB))
    assert not service.recommended(service.scan(include_models=False))


def test_link_and_hardlink_protection(service,tmp_path):
    external=tmp_path/'external.bin';external.write_bytes(b'keep')
    linked=service.roots[0]/'shared.bin';os.link(external,linked)
    assert service.register(linked,'preview',producer='fixture')
    assert service.clean(service.scan(include_models=False).items).skipped
    assert external.read_bytes()==b'keep'
    try:(service.roots[0]/'junction').symlink_to(tmp_path,target_is_directory=True)
    except OSError:return
    assert not safe_path(service.roots[0]/'junction'/'external.bin',service.roots)
    assert not service.register(service.roots[0]/'junction'/'external.bin','preview',producer='fixture')


def test_dead_process_lease_and_no_remote_regeneration(service):
    path=add(service)
    with service._db() as db:db.execute('INSERT INTO leases VALUES(?,?,?)',(str(path),'99999999:0','crashed'))
    assert service.scan(include_models=False).items[0].cleanable
    add(service,'cloud.json','preview',rebuild='remote')
    result=service.clean(service.scan(include_models=False).items)
    assert len(result.deleted)==1 and len(result.skipped)==1


def test_busy_rechecked_and_sparse_logical_statistics(service):
    path=add(service,'large.bin')
    with path.open('r+b') as stream:
        if os.name=='nt':
            import ctypes, msvcrt
            returned=ctypes.c_ulong()
            assert ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno())),0x900C4,None,0,None,0,ctypes.byref(returned),None)
            kernel=ctypes.windll.kernel32
            kernel.SetFilePointerEx.argtypes=[ctypes.c_void_p,ctypes.c_int64,ctypes.c_void_p,ctypes.c_uint32]
            kernel.SetEndOfFile.argtypes=[ctypes.c_void_p]
            assert kernel.SetFilePointerEx(msvcrt.get_osfhandle(stream.fileno()),4*GiB+17,None,0)
            assert kernel.SetEndOfFile(msvcrt.get_osfhandle(stream.fileno()))
        else:stream.truncate(4*GiB+17)
    scan=service.scan(include_models=False)
    assert scan.items[0].size==4*GiB+17
    service.busy=lambda:True
    assert service.clean(scan.items).skipped and path.exists()
    service.busy=lambda:False
    result=service.clean(scan.items)
    assert result.logical_removed_bytes==4*GiB+17
    assert '逻辑' in result.note  # Not a claim of 4GiB physical release.


def test_partial_access_not_complete(service,monkeypatch):
    add(service);original=os.scandir
    def denied(path):
        if Path(path)==service.roots[0]:raise PermissionError('fixture denial')
        return original(path)
    monkeypatch.setattr(os,'scandir',denied)
    scan=service.scan(include_models=False)
    assert not scan.complete and scan.errors


def test_access_denied_lease_is_not_a_crash(service,monkeypatch):
    import psutil
    path=add(service)
    with service._db() as db:db.execute('INSERT INTO leases VALUES(?,?,?)',(str(path),'54321:1','denied'))
    real_process=psutil.Process
    def denied(pid):
        if pid==54321:raise psutil.AccessDenied(pid)
        return real_process(pid)
    monkeypatch.setattr(psutil,'Process',denied)
    # AccessDenied is a live-but-uninspectable PID. A PID absent from the fresh
    # process inventory is instead positive evidence that this lease is stale.
    monkeypatch.setattr(psutil,'pids',lambda:[54321])
    result=service.clean(service.scan(include_models=False).items)
    assert result.skipped and path.exists()


def test_linked_state_and_scan_root_refused(service,tmp_path):
    outside=tmp_path/'outside';outside.mkdir();(outside/'sentinel.bin').write_bytes(b'keep')
    link=tmp_path/'linked-state'
    if os.name=='nt':
        import _winapi
        _winapi.CreateJunction(str(outside),str(link))
    else:link.symlink_to(outside,target_is_directory=True)
    linked=StorageService(service.paths,state_root=link,roots=[link])
    with pytest.raises(OSError):linked.save_policy({'enabled':False})
    assert not (outside/'cache.sqlite3').exists() and not (outside/'policy.json').exists()
    scan=linked.scan(include_models=False)
    assert not scan.complete and scan.errors
    assert (outside/'sentinel.bin').read_bytes()==b'keep'


def test_receipt_counts_bounded_and_missing_registry_pruned(service):
    paths=[add(service,f'bounded/{index}.bin') for index in range(205)]
    result=service.clean(service.scan(include_models=False).items)
    receipt=json.loads((service.state_root/'last-cleanup.json').read_text('utf8'))
    assert len(result.deleted)==205 and receipt['counts']['deleted']==205
    assert len(receipt['deleted'])==200 and receipt['details_truncated']
    missing=add(service,'missing.bin');missing.unlink()
    assert service.forget_missing()==1 and service.forget_missing()==0


def test_database_failure_consumer_still_protected(service,monkeypatch):
    from twobyteasr.storage import storage_service
    path=add(service);scan=service.scan(include_models=False)
    class Unavailable:
        def lease(self,path):
            from contextlib import contextmanager
            @contextmanager
            def fail():
                raise OSError('controlled state unavailable')
                yield
            return fail()
    monkeypatch.setattr(storage_service,'StorageService',Unavailable)
    with storage_service.cache_lease(path):
        assert service.clean(scan.items).skipped and path.exists()
    assert service.clean(service.scan(include_models=False).items).deleted


def test_local_audio_and_waveform_need_accessible_original(service,tmp_path):
    missing=tmp_path/'unavailable.flv'
    for category in ('audio','waveform','thumbnail'):
        add(service,category+'.bin',category,source=str(missing))
    scan=service.scan(include_models=False)
    assert all(not item.cleanable for item in scan.items)
    assert len(service.clean(scan.items).skipped)==3


def test_historical_log_needs_contract_and_explicit_adoption(service,monkeypatch):
    from twobyteasr.storage import storage_legacy
    root=service.paths.log_root;root.mkdir(parents=True)
    good=root/'auto_asr_20261006_123000_99999999_abcdef.jsonl'
    row=dict(event='run_started',pid=99999999,time='2026-10-06T12:30:00+0800',
        pipeline_build='fixture',core_path='fixture/cache.py',startup_self_test='fixture')
    good.write_text(json.dumps(row)+'\n','utf8')
    unknown=root/'auto_asr_20261006_123000_99999999_123456.jsonl';unknown.write_text('[]\n','utf8')
    logs=StorageService(service.paths,roots=[root],state_root=service.state_root)
    scan=logs.scan(include_models=False)
    known=next(item for item in scan.items if item.path==str(good))
    assert not known.cleanable and known.producer=='cache_run_event_log_legacy'
    assert logs.clean([known]).skipped and good.exists()
    monkeypatch.setattr(storage_legacy,'legacy_consumers',lambda:[])
    assert storage_legacy.adopt(logs,[known])['registered']==1
    expected=good.stat().st_size
    assert logs.clean(logs.scan(include_models=False).items).logical_removed_bytes==expected
    assert not good.exists() and unknown.exists()
