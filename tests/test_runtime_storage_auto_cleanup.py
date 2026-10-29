"""2026-10-16 (user: %LOCALAPPDATA%/2ByteASR/runtimes takes 17 GB on drive C).

Two CUDA runtimes (main, moss) are about 5 GB each; the PyTorch installers stayed
in the download cache after install (ADR 0118); an updated runtime left the old
version until someone found a button; a paused install left the cache marker at
"installing", which blocked automatic maintenance for good; and runtimes are hard
links into the cache, so Explorer adds the same files twice.
"""
import json
import os
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from twobyteasr.local_models import model_runtime_cleanup as cleanup
from twobyteasr.local_models.model_storage import format_bytes
from twobyteasr.storage.runtime_usage import runtime_disk_usage
from twobyteasr.storage.storage_ui import StoragePanel, maintain_registered_storage
from twobyteasr.system import runtime_download_cache as cache_module
from tests.test_model_runtime_cleanup import fixture as runtime_fixture
from tests.test_runtime_download_cache import fixture as cache_fixture, runner as cache_runner
from tests.test_storage_maintenance_ui import qapp, service  # noqa: F401  (fixtures)

MiB = 1024 * 1024


def test_runtime_usage_counts_each_hard_linked_file_once(tmp_path):
    managed = tmp_path / 'runtimes'
    env = managed / 'main' / '0123456789abcdef' / 'Lib'; env.mkdir(parents=True)
    archive = managed / 'download-cache' / 'archive-v0' / 'torch'; archive.mkdir(parents=True)
    (env / 'torch_cuda.dll').write_bytes(b'a' * 4096)
    os.link(env / 'torch_cuda.dll', archive / 'torch_cuda.dll')
    (env / 'only_env.py').write_bytes(b'b' * 1000)
    wheels = managed / 'download-cache' / '2byteasr-pytorch-wheels'; wheels.mkdir()
    (wheels / 'torch.whl').write_bytes(b'c' * 3000)
    usage = runtime_disk_usage(managed)
    assert usage.deduplicated and usage.complete and usage.file_count == 4
    assert usage.logical_bytes == 4096 * 2 + 1000 + 3000
    assert usage.unique_bytes == 4096 + 1000 + 3000
    assert usage.cache_only_bytes == 3000
    assert runtime_disk_usage(tmp_path / 'missing') is None


def test_runtime_usage_does_not_walk_into_linked_folders(tmp_path):
    from tests.test_model_removal import junction
    managed = tmp_path / 'runtimes'
    real = managed / 'python' / 'cpython-3.10.19'; real.mkdir(parents=True)
    (real / 'python.exe').write_bytes(b'p' * 500)
    junction(managed / 'python' / 'cpython-3.10', real)
    usage = runtime_disk_usage(managed)
    assert usage.file_count == 1 and usage.logical_bytes == usage.unique_bytes == 500


def test_installing_marker_without_installer_is_recorded_as_interrupted(tmp_path):
    install, data, cache, _ = cache_fixture(tmp_path); calls = []
    cache_module.mark_runtime_cache_state('installing', data_root=data)
    marker_path = cache.parent / 'download-cache-maintenance.json'
    result = cache_module.prune_runtime_download_cache(install, data_root=data, runner=cache_runner(cache, calls))
    marker = json.loads(marker_path.read_text('utf8'))
    assert result.status == 'skipped' and not calls and (cache / 'duplicate').exists()
    assert marker['state'] == 'paused' and '中断' in marker['last_result']
    marker['updated_at'] = time.time() - 15 * 86400
    marker_path.write_text(json.dumps(marker), encoding='utf8')
    result = cache_module.prune_runtime_download_cache(install, data_root=data, runner=cache_runner(cache, calls))
    assert result.status == 'removed' and not (cache / 'duplicate').exists()


def test_idle_maintenance_no_longer_waits_forever_on_an_interrupted_install(service, monkeypatch):
    runtimes = service.paths.user_data_root / 'runtimes'; runtimes.mkdir(parents=True)
    marker = runtimes / 'download-cache-maintenance.json'
    calls = []
    monkeypatch.setattr('twobyteasr.storage.storage_ui.run_uv_maintenance', lambda *a, **kw: calls.append('uv'))
    for state in ('installing', 'paused', 'failed', 'ready', 'maintained'):
        marker.write_text(json.dumps({'state': state, 'updated_at': time.time() - 30 * 86400}), encoding='utf8')
        maintain_registered_storage(service, Event())
    # The prune itself keeps resume data for the retention days; "maintained" has nothing new.
    assert calls == ['uv'] * 4


def _superseded_runtimes(tmp_path, monkeypatch):
    managed, current, old = runtime_fixture(tmp_path)
    in_use = managed / 'main' / 'aaaaaaaaaaaaaaaa'
    (in_use / 'Scripts').mkdir(parents=True); (in_use / 'Scripts/python.exe').write_bytes(b'interpreter')
    (in_use / 'managed-runtime.json').write_text(json.dumps({'role': 'main'}))
    cleanup.write_runtime_inventory(in_use)
    monkeypatch.setattr(cleanup, '_running_paths', lambda: [in_use / 'Scripts/python.exe'])
    (tmp_path / 'dependencies.lock.json').write_text(json.dumps({'managed_bootstrap': {'uv_version': '0.11.7'}}))
    uv = managed / 'tools/uv-0.11.7/uv.exe'; uv.parent.mkdir(parents=True); uv.write_bytes(b'fixture')
    health = []
    monkeypatch.setattr(cache_module, '_healthy_runtimes', lambda *args: health.append(True))
    return current, old, in_use, health


def test_idle_maintenance_removes_superseded_runtime_but_not_one_in_use(service, tmp_path, monkeypatch):
    current, old, in_use, health = _superseded_runtimes(tmp_path, monkeypatch)
    maintain_registered_storage(service, Event())
    assert not old.exists() and in_use.exists() and (current / 'Scripts/python.exe').exists() and health
    receipt = json.loads((service.state_root / 'last-runtime-cleanup.json').read_text('utf8'))
    assert [Path(path) for path in receipt['removed']] == [old] and receipt['logical_removed_bytes'] > 0
    assert [Path(row['path']) for row in receipt['kept']] == [in_use] and '进程' in receipt['kept'][0]['reason']


def test_automatic_cleanup_switch_off_keeps_old_runtimes(service, tmp_path, monkeypatch):
    current, old, in_use, health = _superseded_runtimes(tmp_path, monkeypatch)
    service.save_policy({'enabled': False})
    maintain_registered_storage(service, Event())
    assert old.exists() and not health


def test_successful_install_asks_the_main_window_to_maintain_now():
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    requests = []
    window = SimpleNamespace(_storage_maintenance=SimpleNamespace(request_soon=lambda: requests.append(True)))
    page = SimpleNamespace(refresh=lambda: None, _sync_download_activity=lambda: None, window=lambda: window)
    ModelWorkshopPage._download_completed(page, None, False, 'failed')
    assert not requests
    ModelWorkshopPage._download_completed(page, None, True, 'done')
    assert requests == [True]


def test_request_soon_runs_the_six_hourly_check_now(qapp, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QWidget
    from twobyteasr.storage.storage_ui import IdleStorageMaintenance
    owner = QWidget()
    maintenance = IdleStorageMaintenance(owner)
    maintenance.last_attempt = time.time()
    checks = []
    monkeypatch.setattr(maintenance, 'check', lambda: checks.append(maintenance.last_attempt))
    maintenance.request_soon(delay_ms=0)
    deadline = time.monotonic() + 5
    while not checks and time.monotonic() < deadline:
        qapp.processEvents(); time.sleep(.01)
    assert checks == [0]
    maintenance.stop(); owner.deleteLater(); qapp.processEvents()


def test_six_hours_hold_across_launches(service, qapp, monkeypatch):  # noqa: F811
    # 2026-10-22: every launch ran the whole pass a minute later (~2 min of a core in the GUI process).
    from PySide6.QtWidgets import QWidget
    from twobyteasr.storage import storage_ui
    started = []
    monkeypatch.setattr(storage_ui, 'StorageService', lambda **kwargs: service)
    monkeypatch.setattr(storage_ui.StorageWorker, 'start', lambda self: started.append(self))

    def launch():
        owner = QWidget()
        maintenance = storage_ui.IdleStorageMaintenance(owner)
        maintenance.check()
        maintenance.stop(); owner.deleteLater(); qapp.processEvents()

    launch()
    assert len(started) == 1
    state = json.loads((service.state_root / storage_ui.IdleStorageMaintenance.STATE).read_text('utf8'))
    assert abs(state['last_attempt'] - time.time()) < 60
    launch()  # restarted within six hours: nothing runs
    assert len(started) == 1
    service.write_state_json(storage_ui.IdleStorageMaintenance.STATE, {'last_attempt': time.time() - 7 * 3600})
    launch()
    assert len(started) == 2


def test_storage_summary_shows_real_runtime_use(service, qapp):  # noqa: F811
    managed = service.paths.user_data_root / 'runtimes'
    env = managed / 'main' / '0123456789abcdef'; env.mkdir(parents=True)
    (env / 'torch_cuda.dll').write_bytes(b'a' * 3 * MiB)
    archive = managed / 'download-cache' / 'archive-v0'; archive.mkdir(parents=True)
    os.link(env / 'torch_cuda.dll', archive / 'torch_cuda.dll')
    (managed / 'download-cache' / 'torch.whl').write_bytes(b'w' * MiB)
    result = service.scan(Event())
    assert (result.runtime_usage.unique_bytes, result.runtime_usage.logical_bytes) == (4 * MiB, 7 * MiB)
    panel = StoragePanel(service=service)
    panel._scanned(result)
    text = panel.summary.text()
    assert '运行环境实际占用 ' + format_bytes(4 * MiB) in text
    assert format_bytes(7 * MiB) in text and '只有下载缓存在用 ' + format_bytes(MiB) in text
    panel.deleteLater(); qapp.processEvents()
