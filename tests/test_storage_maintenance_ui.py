"""Idle/model/uv integration in owned, tiny offline fixtures."""
import json
import os
from pathlib import Path
from threading import Event
import time
from types import SimpleNamespace

import pytest
from twobyteasr.runtime_paths import RuntimePaths
from twobyteasr.storage.storage_service import StorageService
from twobyteasr.storage.storage_ui import (StoragePanel, app_busy, maintain_registered_storage,
    run_uv_maintenance, _uv_result_text)
from twobyteasr.local_models.model_download_cache import MARKER, write_transaction
from twobyteasr.system.runtime_download_cache import RuntimeCacheResult


@pytest.fixture
def service(tmp_path):
    data = tmp_path / 'data'; cache = data / 'cache'; cache.mkdir(parents=True)
    models = data / 'models'; models.mkdir()
    paths = RuntimePaths(tmp_path, data, models, cache, data / 'projects', data,
        data / 'logs', tmp_path / 'renderer', data / 'tmp')
    return StorageService(paths, roots=[cache], state_root=data / 'storage')


def stage(service, key, *, age_days=0, state='paused'):
    path = service.paths.model_root / '.downloads' / key / 'hf_official' / 'abcdef'
    path.mkdir(parents=True)
    (path / 'weights.bin.part.fixture.000').write_bytes(b'resumable')
    write_transaction(path, model_key=key, destination=service.paths.model_root / key,
        files=['weights.bin'], state=state)
    marker = path / MARKER; data = json.loads(marker.read_text('utf8'))
    data['updated_at'] = time.time() - age_days * 86400
    marker.write_text(json.dumps(data), encoding='utf8')
    return path


def test_idle_expires_only_receipted_model_downloads_without_open_workshop(service):
    old = stage(service, 'old', age_days=15)
    fresh = stage(service, 'fresh', age_days=3)
    unknown = old / 'user.mp4'; unknown.write_bytes(b'original')
    installed = service.paths.model_root / 'model.pt'; installed.write_bytes(b'model')
    developer = service.paths.temp_root / 'developer.part'; developer.parent.mkdir(); developer.write_bytes(b'keep')
    historical = service.paths.model_root / '.trash' / 'old-model.pt'
    historical.parent.mkdir(); historical.write_bytes(b'old model remains explicit')
    maintain_registered_storage(service, Event())
    assert not (old / 'weights.bin.part.fixture.000').exists()
    assert (fresh / 'weights.bin.part.fixture.000').read_bytes() == b'resumable'
    assert unknown.read_bytes() == b'original' and installed.read_bytes() == b'model'
    assert developer.read_bytes() == b'keep' and historical.exists()
    receipt = json.loads((service.state_root / 'last-model-download-cleanup.json').read_text('utf8'))
    assert receipt['counts']['deleted'] == 1 and receipt['counts']['skipped'] == 1
    assert receipt['logical_removed_bytes'] == 9
    service.save_policy({'resume_days': 2})
    maintain_registered_storage(service, Event())
    assert not fresh.exists()


def test_idle_bootstrap_scope_os_model_lock_and_failure_retry(service, monkeypatch):
    from twobyteasr.repository_download import preparation_lock
    owned = stage(service, 'locked', age_days=15)
    with preparation_lock(service.paths.model_root / '.downloads' / 'locked' / '.prepare.lock'):
        maintain_registered_storage(service, Event())
    assert (owned / MARKER).exists() and (owned / 'weights.bin.part.fixture.000').exists()
    original = Path.unlink
    def occupied(path, *args, **kwargs):
        if path.name == 'weights.bin.part.fixture.000': raise PermissionError('controlled occupied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', occupied)
    maintain_registered_storage(service, Event())
    assert (owned / MARKER).exists()
    receipt = json.loads((service.state_root / 'last-model-download-cleanup.json').read_text('utf8'))
    assert receipt['counts']['failed'] == 1 and receipt['logical_removed_bytes'] == 0
    monkeypatch.setattr(Path, 'unlink', original)
    maintain_registered_storage(service, Event())
    assert not owned.exists()


@pytest.mark.parametrize('reason', ['busy', 'cancelled', 'disabled'])
def test_idle_never_starts_work_when_protected(service, reason):
    owned = stage(service, 'fixture', age_days=15)
    event = Event()
    if reason == 'busy': service.busy = lambda: True
    if reason == 'cancelled': event.set()
    if reason == 'disabled': service.save_policy({'enabled': False})
    assert maintain_registered_storage(service, event) is None
    assert (owned / MARKER).exists() and (owned / 'weights.bin.part.fixture.000').exists()


def test_idle_refuses_linked_model_staging_root(service, tmp_path):
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'original.part').write_bytes(b'original')
    from tests.test_model_removal import junction
    junction(service.paths.model_root / '.downloads', outside)
    maintain_registered_storage(service, Event())
    assert (outside / 'original.part').read_bytes() == b'original'


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_last_counts_not_truncated_and_uv_cancel_is_unmeasured(service, monkeypatch, qapp):
    service.state_root.mkdir(parents=True)
    (service.state_root / 'last-cleanup.json').write_text(json.dumps(dict(time=time.time(),
        logical_removed_bytes=123, deleted=[{}], skipped=[], failed=[], pending=[],
        counts=dict(deleted=301, skipped=402, failed=503, pending=604))), encoding='utf8')
    monkeypatch.setattr('twobyteasr.system.runtime_download_cache.prune_runtime_download_cache',
        lambda *a, **kw: RuntimeCacheResult('cancelled', 'controlled partial cancellation'))
    result = run_uv_maintenance(service, Event())
    payload = json.loads((service.state_root / 'last-uv-cleanup.json').read_text('utf8'))
    assert payload['status'] == 'cancelled' and not payload['measurement_complete']
    panel = StoragePanel(service=service)
    for number in ('301', '402', '503', '604'): assert number in panel.last.text()
    panel._uv_cleaned(result)
    assert '未完成测量' in panel.summary.text() and '未完成测量' in panel.last.text()
    assert '0 B' not in panel.summary.text()
    panel.deleteLater(); qapp.processEvents()


def test_uv_free_delta_is_signed_and_separate_from_logical():
    text = _uv_result_text(dict(status='removed', measurement_complete=True,
        logical_removed_bytes=2048, disk_free_delta=-1024))
    assert '2.00 KiB' in text and '-1.00 KiB' in text


def test_uv_record_refuses_state_directory_junction(service, tmp_path, monkeypatch):
    outside = tmp_path / 'outside'; outside.mkdir()
    from tests.test_model_removal import junction
    junction(service.state_root, outside)
    monkeypatch.setattr('twobyteasr.system.runtime_download_cache.prune_runtime_download_cache',
        lambda *a, **kw: RuntimeCacheResult('skipped', 'busy'))
    result = run_uv_maintenance(service, Event())
    assert not list(outside.iterdir()) and '未保存' in result.detail


def test_hidden_download_and_open_studio_project_are_busy(qapp):
    from PySide6.QtCore import QProcess
    process = SimpleNamespace(state=lambda: QProcess.ProcessState.Running)
    workshop = SimpleNamespace(_download_dialogs=[SimpleNamespace(process=process)])
    assert app_busy(SimpleNamespace(workshop_page=workshop))
    studio = SimpleNamespace(project=SimpleNamespace(media=SimpleNamespace(path='fixture.mp4')))
    assert app_busy(SimpleNamespace(studio_page=studio))
    studio._close_requested = True
    assert not app_busy(SimpleNamespace(studio_page=studio))
