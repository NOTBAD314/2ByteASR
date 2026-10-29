import json
import os
from pathlib import Path
from threading import Event

from twobyteasr.system.runtime_download_cache import (bootstrap_guard, mark_runtime_cache_ready,
    mark_runtime_cache_state, prune_runtime_download_cache)


def fixture(tmp_path):
    install = tmp_path / 'install'; install.mkdir()
    (install / 'dependencies.lock.json').write_text(json.dumps({'managed_bootstrap': {'uv_version': '0.11.7'}}))
    data = tmp_path / 'data'; managed = data / 'runtimes'
    cache = managed / 'download-cache'; cache.mkdir(parents=True)
    (cache / 'duplicate').write_bytes(b'x' * 2048)
    env = managed / 'main' / 'fixture'; python = env / 'Scripts/python.exe'
    python.parent.mkdir(parents=True); python.write_bytes(b'interpreter fixture')
    (env / 'managed-runtime.json').write_text('{}')
    (managed / 'registry.json').write_text(json.dumps({'runtimes': {'main': {'python_executable': str(python)}}}))
    uv = managed / 'tools/uv-0.11.7' / ('uv.exe' if os.name == 'nt' else 'uv')
    uv.parent.mkdir(parents=True); uv.write_bytes(b'uv fixture')
    return install, data, cache, python


def runner(cache, calls):
    def run(argv, cancel):
        args = [str(x) for x in argv]; calls.append(args)
        if '--version' in args: return 'uv 0.11.7 (fixture)'
        if 'prune' in args:
            (cache / 'duplicate').unlink()
            return 'Pruned disposable objects'
        return 'Checked installed dependencies'
    return run


def test_prune_private_cache_offline_after_health_and_keeps_environment(tmp_path):
    install, data, cache, python = fixture(tmp_path); calls = []
    mark_runtime_cache_ready(data_root=data)
    result = prune_runtime_download_cache(install, data_root=data, runner=runner(cache, calls))
    assert result.status == 'removed' and result.logical_removed_bytes == 2048
    assert result.measurement_complete
    assert python.read_bytes() == b'interpreter fixture'
    assert calls[-1][-3:] == ['cache', 'prune', '--ci']
    assert '--cache-dir' in calls[-1] and str(cache) in calls[-1]
    assert '--offline' in calls[-1] and '--force' not in calls[-1]
    assert any('check' in call for call in calls[:-1])
    marker = json.loads((cache.parent / 'download-cache-maintenance.json').read_text())
    assert marker['state'] == 'maintained'


def test_busy_and_cancel_keep_files_and_never_launch_uv(tmp_path):
    install, data, cache, _ = fixture(tmp_path); calls = []
    result = prune_runtime_download_cache(install, data_root=data, busy=lambda: True, runner=runner(cache, calls))
    assert result.status == 'skipped' and not calls
    event = Event(); event.set()
    result = prune_runtime_download_cache(install, data_root=data, cancel=event, runner=runner(cache, calls))
    assert result.status == 'cancelled' and not calls and (cache / 'duplicate').exists()
    assert not result.measurement_complete and result.disk_free_delta is None


def test_bootstrap_lock_occupied_skips_without_force(tmp_path):
    install, data, cache, _ = fixture(tmp_path); calls = []
    with bootstrap_guard(cache.parent):
        result = prune_runtime_download_cache(install, data_root=data, runner=runner(cache, calls))
    assert result.status == 'skipped' and not calls and (cache / 'duplicate').exists()


def test_paused_transaction_retained_for_policy_days(tmp_path):
    install, data, cache, _ = fixture(tmp_path); calls = []
    mark_runtime_cache_state('paused', data_root=data)
    result = prune_runtime_download_cache(install, data_root=data, runner=runner(cache, calls))
    assert result.status == 'skipped' and '14天' in result.detail and not calls


def test_failed_health_does_not_prune(tmp_path):
    install, data, cache, _ = fixture(tmp_path)
    def bad(argv, cancel):
        if '--version' in [str(x) for x in argv]: return 'uv 0.11.7 (fixture)'
        raise RuntimeError('dependency check failed')
    result = prune_runtime_download_cache(install, data_root=data, runner=bad)
    assert result.status == 'failed' and (cache / 'duplicate').exists()


def test_repeat_prune_zero_logical_removal(tmp_path):
    install, data, cache, _ = fixture(tmp_path); calls = []
    action = runner(cache, calls)
    assert prune_runtime_download_cache(install, data_root=data, runner=action).logical_removed_bytes == 2048
    def again(argv, cancel):
        return 'uv 0.11.7 (fixture)' if '--version' in [str(x) for x in argv] else 'Nothing to prune'
    result = prune_runtime_download_cache(install, data_root=data, runner=again)
    assert result.status == 'removed' and result.logical_removed_bytes == 0
    assert result.measurement_complete


def test_cancel_after_uv_partial_deletion_does_not_report_measured_zero(tmp_path):
    install, data, cache, _ = fixture(tmp_path)
    def action(argv, cancel):
        args = [str(x) for x in argv]
        if '--version' in args: return 'uv 0.11.7 (fixture)'
        if 'prune' in args:
            (cache / 'duplicate').unlink()
            raise InterruptedError('维护已取消')
        return 'Checked installed dependencies'
    result = prune_runtime_download_cache(install, data_root=data, runner=action)
    assert result.status == 'cancelled' and not (cache / 'duplicate').exists()
    assert not result.measurement_complete and result.disk_free_delta is None


def test_cache_junction_is_not_followed(tmp_path):
    install, data, cache, _ = fixture(tmp_path)
    outside = tmp_path / 'user-assets'; outside.mkdir()
    (outside / 'original').write_bytes(b'original')
    from tests.test_model_removal import junction
    junction(cache / 'cross-root', outside)
    result = prune_runtime_download_cache(install, data_root=data, runner=runner(cache, []))
    assert result.status == 'failed' and (outside / 'original').read_bytes() == b'original'


def test_installed_environment_path_configuration_dependent_on_cache_is_protected(tmp_path):
    install,data,cache,python=fixture(tmp_path);calls=[]
    site=python.parent.parent/'Lib/site-packages';site.mkdir(parents=True)
    (site/'cache-dependency.pth').write_text(str(cache/'archive-v0'),encoding='utf8')
    result=prune_runtime_download_cache(install,data_root=data,runner=runner(cache,calls))
    assert result.status=='failed' and '仍引用' in result.detail
    assert not any('prune' in call for call in calls) and (cache/'duplicate').exists()
