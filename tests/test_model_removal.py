import ctypes
import json
import os
import subprocess
from pathlib import Path

import pytest

from twobyteasr.local_models.model_removal import execute_removal, historical_model_removals, plan_model_removal


def managed(tmp_path, *, specs=None):
    specs=specs or {'test':{'path':'models/Test','required_files':['weights.bin','config.json']}}
    (tmp_path/'dependencies.lock.json').write_text(json.dumps({'models':specs}),'utf8')
    parent=tmp_path/'models';parent.mkdir(exist_ok=True)
    return parent


def model(parent):
    root=parent/'Test';root.mkdir(exist_ok=True)
    (root/'weights.bin').write_bytes(b'weights')
    (root/'config.json').write_bytes(b'{}')
    return root


def test_permanent_removal_releases_handles_and_keeps_unrelated_data(tmp_path):
    parent=managed(tmp_path);root=model(parent)
    (tmp_path/'video.mp4').write_bytes(b'original')
    (tmp_path/'.venv-main').mkdir();(tmp_path/'.venv-main'/'shared.dll').write_bytes(b'shared')
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    released=[]
    result=execute_removal(plan,release=lambda:released.append(True))
    assert released==[True] and result.completed and result.logical_bytes==9
    assert not root.exists() and not (tmp_path/'.bin').exists() and not (tmp_path/'model_trash').exists()
    assert (tmp_path/'video.mp4').read_bytes()==b'original' and (tmp_path/'.venv-main'/'shared.dll').exists()
    assert execute_removal(plan).completed  # repeated deletion is idempotent


def test_partial_failure_records_remaining_bytes_and_retries_only_remaining(tmp_path):
    parent=managed(tmp_path);root=model(parent)
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    def remove(path):
        if path.name=='weights.bin':raise PermissionError('occupied')
        path.unlink()
    result=execute_removal(plan,unlink=remove)
    assert not result.completed and result.logical_bytes==2 and len(result.failures)==1
    assert (root/'weights.bin').exists() and not (root/'config.json').exists()
    retry=execute_removal(plan)
    assert retry.completed and retry.logical_bytes==7 and not root.exists()


@pytest.mark.skipif(os.name!='nt',reason='Windows file share semantics')
def test_real_windows_file_handle_denies_delete_without_killing_owner(tmp_path):
    parent=managed(tmp_path);root=model(parent)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateFileW(str(root/'weights.bin'),0x80000000,1,None,3,0,None)
    assert handle!=ctypes.c_void_p(-1).value
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    try:
        result=execute_removal(plan)
        assert not result.completed and str(root/'weights.bin') in result.failures
        assert (root/'weights.bin').read_bytes()==b'weights'
    finally:kernel.CloseHandle(handle)
    assert execute_removal(plan).completed


def test_hardlink_does_not_claim_space_release_and_shared_inventory_retained(tmp_path):
    parent=managed(tmp_path,specs={'test':{'path':'models/Test','required_files':['weights.bin','config.json']},
        'other':{'path':'models/Test','required_files':['config.json']}})
    root=model(parent);external=tmp_path/'shared-cache.bin'
    os.link(root/'weights.bin',external)
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    assert plan.logical_bytes==7 and plan.exclusive_bytes==0
    result=execute_removal(plan)
    assert not result.completed and result.exclusive_bytes==0
    assert external.read_bytes()==b'weights' and (root/'config.json').exists()


def test_unknown_files_and_nested_directory_links_are_not_removed(tmp_path):
    parent=managed(tmp_path);root=model(parent)
    (root/'my-subtitles.srt').write_bytes(b'user')
    result=execute_removal(plan_model_removal(tmp_path,'test',model_root=parent))
    assert not result.completed and (root/'my-subtitles.srt').read_bytes()==b'user'


def junction(link,target):
    if os.name=='nt':
        command=f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' | Out-Null"
        subprocess.run(['powershell','-NoProfile','-Command',command],check=True,capture_output=True)
    else:link.symlink_to(target,target_is_directory=True)


def test_model_directory_link_is_unlinked_without_deleting_target(tmp_path):
    parent=managed(tmp_path);target=tmp_path/'user-original';target.mkdir()
    (target/'weights.bin').write_bytes(b'original')
    link=parent/'Test';junction(link,target)
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    assert plan.paths==(link,) and plan.logical_bytes==0
    result=execute_removal(plan)
    assert result.completed and not link.exists() and (target/'weights.bin').read_bytes()==b'original'


def test_linked_model_parent_refuses_recursive_delete(tmp_path):
    real=tmp_path/'real';real.mkdir();root=model(real)
    parent=managed(tmp_path);parent.rmdir();junction(parent,real)
    try:
        with pytest.raises(ValueError,match='链接'):
            plan_model_removal(tmp_path,'test',model_root=parent)
        assert (root/'weights.bin').read_bytes()==b'weights'
    finally:
        if parent.is_symlink():parent.unlink()
        else:parent.rmdir()


def test_historical_cleanup_only_scans_explicit_app_buckets(tmp_path):
    parent=managed(tmp_path);trash=tmp_path/'.bin';trash.mkdir()
    root=model(trash);unknown=trash/'unrelated';unknown.mkdir();(unknown/'weights.bin').write_bytes(b'user')
    outside=tmp_path/'project'/'.bin'/'Test';outside.mkdir(parents=True);(outside/'weights.bin').write_bytes(b'project')
    plans=historical_model_removals(tmp_path,model_root=parent)
    assert len(plans)==1 and plans[0].root==root
    assert execute_removal(plans[0]).completed and not root.exists()
    assert (unknown/'weights.bin').read_bytes()==b'user' and (outside/'weights.bin').read_bytes()==b'project'


def test_lock_cannot_grant_ownership_outside_model_directory(tmp_path):
    parent=managed(tmp_path,specs={'test':{'path':'models/Test','required_files':['../original.mp4']}})
    (parent/'original.mp4').write_bytes(b'user')
    with pytest.raises(ValueError,match='越界'):
        plan_model_removal(tmp_path,'test',model_root=parent)
    assert (parent/'original.mp4').read_bytes()==b'user'


def test_busy_is_rechecked_before_release_and_each_deletion(tmp_path):
    parent=managed(tmp_path); root=model(parent); released=[]
    result=execute_removal(plan_model_removal(tmp_path,'test',model_root=parent),
                           busy_check=lambda:True,release=lambda:released.append(True))
    assert result.failures and not released and (root/'weights.bin').exists()


def test_confirmation_inventory_identity_changed_is_not_deleted(tmp_path):
    parent=managed(tmp_path); root=model(parent)
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    (root/'weights.bin').write_bytes(b'replacement-new-model')
    result=execute_removal(plan)
    assert str(root/'weights.bin') in result.failures
    assert (root/'weights.bin').read_bytes()==b'replacement-new-model'


def test_confirmation_ownership_changed_requires_new_confirmation(tmp_path):
    parent=managed(tmp_path); root=model(parent)
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    lock=tmp_path/'dependencies.lock.json'
    lock.write_text(lock.read_text()+'\n')
    result=execute_removal(plan)
    assert result.failures and (root/'weights.bin').exists()


def test_external_model_detaches_then_explicit_delete_respects_user_assets(tmp_path,monkeypatch):
    from twobyteasr import runtime_paths
    from twobyteasr.local_models.model_associations import is_model_detached
    parent=managed(tmp_path); external=tmp_path/'user-external';external.mkdir();root=model(external)
    monkeypatch.setenv(runtime_paths.USER_DATA_ENV,str(tmp_path/'local'))
    monkeypatch.setenv(runtime_paths.MODEL_ROOT_ENV,str(external))
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT',str(tmp_path));runtime_paths.reset_runtime_paths()
    try:
        plan=plan_model_removal(tmp_path,'test',model_root=external)
        assert plan.mode=='detach' and plan.external
        result=execute_removal(plan)
        assert result.completed and result.logical_bytes==0 and result.detached==[str(root)]
        assert is_model_detached(root) and (root/'weights.bin').exists()
        from twobyteasr.local_models.model_registry import scan_model_registry
        assert not scan_model_registry(install_root=tmp_path,model_root=external).installed_keys()
        assert runtime_paths.resolve_model_dir('Test',install_root=tmp_path)!=root
        explicit=plan_model_removal(tmp_path,'test',model_root=external,allow_external_delete=True)
        assert execute_removal(explicit).completed and not root.exists()
    finally:runtime_paths.reset_runtime_paths()


def test_detached_external_folder_is_not_production_discovered_again(tmp_path,monkeypatch):
    from twobyteasr import runtime_paths
    from twobyteasr.local_models.model_associations import detach_model
    from twobyteasr.local_models.model_registry import scan_model_registry
    parent=managed(tmp_path);external=tmp_path/'external';external.mkdir();root=model(external)
    monkeypatch.setenv(runtime_paths.USER_DATA_ENV,str(tmp_path/'local'))
    monkeypatch.setenv(runtime_paths.MODEL_ROOT_ENV,str(external))
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT',raising=False);runtime_paths.reset_runtime_paths()
    try:
        detach_model(root,'test')
        registry=scan_model_registry(install_root=tmp_path,model_root=external)
        assert 'test' not in registry.installed_keys()
        assert registry.record('test').installation_path!=root
        assert root.exists()
    finally:runtime_paths.reset_runtime_paths()


def test_model_download_transaction_lock_blocks_permanent_delete(tmp_path):
    from twobyteasr.repository_download import preparation_lock
    parent=managed(tmp_path);root=model(parent);plan=plan_model_removal(tmp_path,'test',model_root=parent)
    with preparation_lock(plan.transaction_lock):
        result=execute_removal(plan)
    assert result.failures and (root/'weights.bin').exists()


def test_external_parent_bin_is_not_assumed_to_be_app_trash(tmp_path):
    managed(tmp_path);external=tmp_path/'user-associated';external.mkdir()
    trash=external/'.bin';trash.mkdir();root=model(trash)
    assert historical_model_removals(tmp_path,model_root=external)==[]
    assert (root/'weights.bin').read_bytes()==b'weights'


@pytest.mark.skipif(os.name!='nt',reason='Windows sparse-file allocation evidence')
def test_sparse_larger_than_four_gib_counts_logical_size_without_claiming_physical_release(tmp_path):
    import msvcrt
    parent=managed(tmp_path);root=model(parent);path=root/'weights.bin'
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.DeviceIoControl.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,
                                    ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32),ctypes.c_void_p]
    kernel.SetFilePointerEx.argtypes=[ctypes.c_void_p,ctypes.c_int64,ctypes.POINTER(ctypes.c_int64),ctypes.c_uint32]
    kernel.SetEndOfFile.argtypes=[ctypes.c_void_p]
    logical=4*1024**3+4096
    with path.open('w+b') as stream:
        returned=ctypes.c_uint32()
        assert kernel.DeviceIoControl(msvcrt.get_osfhandle(stream.fileno()),0x900C4,None,0,None,0,ctypes.byref(returned),None)
        # Python/CRT truncate can explicitly zero-fill a sparse file on Windows.
        # NTFS SetEndOfFile extends its sparse logical range without that I/O.
        handle=msvcrt.get_osfhandle(stream.fileno())
        assert kernel.SetFilePointerEx(handle,logical,None,0)
        assert kernel.SetEndOfFile(handle)
    kernel.GetCompressedFileSizeW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint32)]
    kernel.GetCompressedFileSizeW.restype=ctypes.c_uint32
    high=ctypes.c_uint32();low=kernel.GetCompressedFileSizeW(str(path),ctypes.byref(high))
    allocated=(high.value<<32)|low
    assert allocated<1024**2  # sparse fixture; this is NOT a real 4GiB weight
    plan=plan_model_removal(tmp_path,'test',model_root=parent)
    assert plan.logical_bytes==logical+2
    result=execute_removal(plan)
    assert result.completed and result.logical_bytes==logical+2 and not root.exists()
    (tmp_path/'sparse-evidence.json').write_text(json.dumps({'fixture_logical_bytes':logical,
        'fixture_allocated_bytes':allocated,'removed_logical_bytes':result.logical_bytes,
        'disk_free_delta':result.disk_free_delta,'claims_four_gib_physical_release':False}),encoding='utf8')
