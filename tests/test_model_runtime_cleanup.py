import json
import hashlib
from pathlib import Path

from twobyteasr.local_models import model_runtime_cleanup as cleanup


def fixture(tmp_path):
    managed=tmp_path/'data/runtimes';current=managed/'main/0123456789abcdef';old=managed/'main/fedcba9876543210'
    for path in (current,old):
        (path/'Scripts').mkdir(parents=True)
        (path/'Scripts/python.exe').write_bytes(b'interpreter')
        (path/'managed-runtime.json').write_text(json.dumps({'role':'main','models':['fixture']}))
        (path/'weights-are-not-here.txt').write_bytes(b'dependency-data')
        cleanup.write_runtime_inventory(path)
    (managed/'registry.json').write_text(json.dumps({'runtimes':{'main':{'python_executable':str(current/'Scripts/python.exe')}}}))
    return managed,current,old


def test_current_shared_runtime_protected_superseded_inventory_is_reviewable(tmp_path,monkeypatch):
    managed,current,old=fixture(tmp_path);monkeypatch.setattr(cleanup,'_running_paths',lambda:[])
    plans=cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data')
    by_path={plan.root:plan for plan in plans}
    assert by_path[current].protected_reason
    assert not by_path[old].protected_reason and by_path[old].removal.logical_bytes>0
    (old/'user-note.mp4').write_bytes(b'user media')
    plan=next(p for p in cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data') if p.root==old)
    assert old/'user-note.mp4' in plan.removal.retained


def test_uninventoried_and_running_old_environments_are_protected(tmp_path,monkeypatch):
    managed,current,old=fixture(tmp_path)
    monkeypatch.setattr(cleanup,'_running_paths',lambda:[old/'Scripts/python.exe'])
    plan=next(p for p in cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data') if p.root==old)
    assert '进程' in plan.protected_reason
    monkeypatch.setattr(cleanup,'_running_paths',lambda:[])
    (old/'installed-files.json').unlink()
    plan=next(p for p in cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data') if p.root==old)
    assert '归属清单' in plan.protected_reason and plan.removal is None


def test_dependency_change_and_busy_block_delete(tmp_path,monkeypatch):
    managed,current,old=fixture(tmp_path);monkeypatch.setattr(cleanup,'_running_paths',lambda:[])
    plan=next(p for p in cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data') if p.root==old)
    result=cleanup.remove_unused_model_runtime(plan,install_root=tmp_path,data_root=tmp_path/'data',busy=lambda:True)
    assert result.failures and (old/'Scripts/python.exe').exists()
    (managed/'registry.json').write_text(json.dumps({'runtimes':{'main':{'python_executable':str(old/'Scripts/python.exe')}}}))
    result=cleanup.remove_unused_model_runtime(plan,install_root=tmp_path,data_root=tmp_path/'data')
    assert result.failures and (old/'Scripts/python.exe').exists()


def test_superseded_environment_real_files_removed_after_offline_health(tmp_path,monkeypatch):
    managed,current,old=fixture(tmp_path);monkeypatch.setattr(cleanup,'_running_paths',lambda:[])
    (tmp_path/'dependencies.lock.json').write_text(json.dumps({'managed_bootstrap':{'uv_version':'0.11.7'}}))
    uv=managed/'tools/uv-0.11.7/uv.exe';uv.parent.mkdir(parents=True);uv.write_bytes(b'fixture')
    import twobyteasr.system.runtime_download_cache as cache
    health=[];monkeypatch.setattr(cache,'_healthy_runtimes',lambda *args:health.append(True))
    plan=next(p for p in cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data') if p.root==old)
    result=cleanup.remove_unused_model_runtime(plan,install_root=tmp_path,data_root=tmp_path/'data')
    assert health==[True] and result.completed and result.logical_bytes>0 and not old.exists()
    assert (current/'Scripts/python.exe').exists()


def test_legacy_runtime_recovers_owned_package_files_without_claiming_unknown_assets(tmp_path,monkeypatch):
    managed,current,_=fixture(tmp_path);monkeypatch.setattr(cleanup,'_running_paths',lambda:[])
    identity=dict(role='main',models=['fixture'],packages={'fixture':'1.0'},python='3.10.19',torch=None,tag='cpu',schema=1)
    signature=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    old=managed/'main'/signature;site=old/'Lib/site-packages';record=site/'fixture-1.0.dist-info/RECORD'
    record.parent.mkdir(parents=True)
    record.write_text('fixture.py,,\nfixture-1.0.dist-info/RECORD,,\n',encoding='utf8')
    (site/'fixture.py').write_bytes(b'package source')
    (old/'managed-runtime.json').write_text(json.dumps(dict(identity,prepared_at=0)))
    (old/'user-video.mp4').write_bytes(b'original user asset')
    plan=next(p for p in cleanup.scan_unused_model_runtimes(data_root=tmp_path/'data') if p.root==old)
    assert not plan.protected_reason and site/'fixture.py' in plan.removal.paths
    assert old/'user-video.mp4' in plan.removal.retained
