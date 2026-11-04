import hashlib
import json
from pathlib import Path

import pytest
from twobyteasr import repository_download as downloader
from twobyteasr.local_models.model_download_cache import (MARKER, cleanup_download_transaction,
    scan_download_transactions, write_transaction)


def setup_stage(tmp_path, state='paused'):
    staging_root = tmp_path / 'downloads'
    stage = staging_root / 'fixture/hf_official/abcdef'
    stage.mkdir(parents=True)
    (stage / 'weights.bin.part.fixture.000').write_bytes(b'x' * 1024)
    write_transaction(stage, model_key='fixture', destination=tmp_path / 'model',
                      files=['weights.bin'], state=state)
    return staging_root, stage


def test_confirmed_publication_cleans_staging_after_installed_validation(tmp_path, monkeypatch):
    weight = b'weight'; config = b'{}'
    spec = dict(repository='fixture/Own', revision='fixed', required_files=['weight.bin','config.json'],
        sha256={'weight.bin':hashlib.sha256(weight).hexdigest(),'config.json':hashlib.sha256(config).hexdigest()})
    target = tmp_path / 'model'; target.mkdir(); (target / 'weight.bin').write_bytes(weight)
    requested = []
    def fetch(manifest, staging, relative):
        requested.append(relative)
        assert relative == 'config.json'
        assert not (staging / 'weight.bin').exists(), 'Healthy large files must not be copied to staging'
        path = staging / relative; path.write_bytes(config)
        (staging / (relative + '.download.json')).write_text('{}')
        return path
    monkeypatch.setattr(downloader, '_download_direct', fetch)
    downloader.download_model(model_key='fixture', spec=spec, destination=target,
                               mode='HF_OFFICIAL', staging_root=tmp_path / 'downloads')
    assert requested == ['config.json']
    assert (target / 'weight.bin').read_bytes() == weight and (target / 'config.json').read_bytes() == config
    assert not list((tmp_path / 'downloads').rglob(MARKER))
    assert not list((tmp_path / 'downloads').rglob('config.json*'))


def test_failed_download_receipt_preserves_resume_and_expires_by_policy(tmp_path, monkeypatch):
    spec = dict(repository='fixture/Own', revision='fixed', required_files=['weights.bin'])
    def fail(manifest, staging, relative):
        (staging / 'weights.bin.part.origin.000').write_bytes(b'resumable')
        raise OSError('offline controlled failure')
    monkeypatch.setattr(downloader, '_download_direct', fail)
    with pytest.raises(RuntimeError):
        downloader.download_model(model_key='fixture', spec=spec, destination=tmp_path/'model',
                                   mode='HF_OFFICIAL', staging_root=tmp_path/'downloads')
    transaction = scan_download_transactions(tmp_path/'downloads')[0]
    assert transaction.state == 'paused' and transaction.logical_bytes == 9
    assert cleanup_download_transaction(transaction, staging_root=tmp_path/'downloads')['skipped']
    result = cleanup_download_transaction(transaction, staging_root=tmp_path/'downloads',
                                         now=transaction.updated_at + 3 * 86400, resume_days=2)
    assert result['logical_bytes'] == 9 and not result['failures']
    assert not transaction.root.exists()


def test_active_transaction_and_os_lock_are_not_deleted(tmp_path):
    root, stage = setup_stage(tmp_path, 'published'); transaction = scan_download_transactions(root)[0]
    assert cleanup_download_transaction(transaction, staging_root=root, active_keys=['fixture'])['skipped']
    with downloader.preparation_lock(root/'fixture/.prepare.lock'):
        result = cleanup_download_transaction(transaction, staging_root=root)
    assert result['failures'] and transaction.paths[0].exists()


def test_unknown_files_and_development_tmp_never_enter_receipted_inventory(tmp_path):
    root, stage = setup_stage(tmp_path, 'published')
    (stage/'user.mp4').write_bytes(b'user')
    (tmp_path/'developer.tmp').write_bytes(b'keep')
    transaction = scan_download_transactions(root)[0]
    result = cleanup_download_transaction(transaction, staging_root=root)
    assert len(result['removed']) == 1 and (stage/'user.mp4').read_bytes() == b'user'
    assert (tmp_path/'developer.tmp').exists()


def test_ownership_rechecked_after_resume_or_receipt_replacement(tmp_path):
    root, stage = setup_stage(tmp_path, 'published'); transaction = scan_download_transactions(root)[0]
    write_transaction(stage, model_key='fixture', destination=tmp_path/'model', files=['weights.bin'], state='downloading')
    result = cleanup_download_transaction(transaction, staging_root=root)
    assert result['skipped'] and transaction.paths[0].exists()


def test_cross_root_junction_is_not_scanned_or_deleted(tmp_path):
    root, stage = setup_stage(tmp_path, 'published')
    outside = tmp_path/'user'; outside.mkdir(); (outside/'secret.part').write_bytes(b'original')
    from tests.test_model_removal import junction
    junction(stage/'linked', outside)
    transaction = scan_download_transactions(root)[0]
    assert all('linked' not in path.parts for path in transaction.paths)
    cleanup_download_transaction(transaction, staging_root=root)
    assert (outside/'secret.part').read_bytes()==b'original'


def test_partial_failure_keeps_receipt_and_repeat_is_truthful(tmp_path, monkeypatch):
    root, stage = setup_stage(tmp_path, 'published'); transaction = scan_download_transactions(root)[0]
    real = Path.unlink
    def unlink(path, *args, **kwargs):
        if path.name.startswith('weights.bin.part'): raise PermissionError('occupied')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', unlink)
    result = cleanup_download_transaction(transaction, staging_root=root)
    assert result['failures'] and result['logical_bytes']==0 and (stage/MARKER).exists()
    monkeypatch.setattr(Path, 'unlink', real)
    result = cleanup_download_transaction(transaction, staging_root=root)
    assert result['logical_bytes']==1024 and not stage.exists()
    assert cleanup_download_transaction(transaction, staging_root=root)['skipped']


def test_cancel_during_cleanup_keeps_remaining_receipt_and_files(tmp_path, monkeypatch):
    from threading import Event
    root, stage = setup_stage(tmp_path, 'published')
    (stage / 'weights.bin.download.json').write_text('{}')
    transaction = scan_download_transactions(root)[0]
    event = Event(); original = Path.unlink
    def stop_after_first(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path in transaction.paths: event.set()
        return result
    monkeypatch.setattr(Path, 'unlink', stop_after_first)
    result = cleanup_download_transaction(transaction, staging_root=root, cancel=event)
    assert len(result['removed']) == 1 and result['skipped'] and (stage / MARKER).exists()
    assert sum(path.exists() for path in transaction.paths) == 1
    monkeypatch.setattr(Path, 'unlink', original)
    event.clear()
    assert cleanup_download_transaction(transaction, staging_root=root, cancel=event)['removed']
    assert not stage.exists()


@pytest.mark.parametrize('broken', [[], {'state':'unrecognized'}, {'updated_at':float('nan')}, {'files':'weights.bin'}])
def test_malformed_transaction_is_protected_without_aborting_scan(tmp_path, broken):
    root, stage = setup_stage(tmp_path, 'published')
    marker = stage / MARKER
    payload = json.loads(marker.read_text('utf8'))
    if isinstance(broken, dict): payload.update(broken)
    else: payload = broken
    marker.write_text(json.dumps(payload), encoding='utf8')
    assert not scan_download_transactions(root)
    assert (stage / 'weights.bin.part.fixture.000').exists()
