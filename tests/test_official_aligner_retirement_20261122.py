"""2026-11-22 (user): the old official Qwen3 aligner is removed once Ultra runs."""
import json
from pathlib import Path

import pytest

from twobyteasr.local_models import official_aligner_retirement as retirement
from twobyteasr.recognition import alignment_backend

ULTRA = {'models': {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'ultra-v5'}}
READY = {'status': 'PASS'}


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A managed model root holding the old official weights plus one user file."""
    install = tmp_path / 'install'
    lock_root = Path(__file__).resolve().parents[1]
    install.mkdir()
    (install / 'dependencies.lock.json').write_bytes((lock_root / 'dependencies.lock.json').read_bytes())
    spec = json.loads((install / 'dependencies.lock.json').read_text('utf-8-sig'))['models']['qwen_aligner']
    folder = install / 'models' / Path(spec['path']).name
    folder.mkdir(parents=True)
    names = sorted(set(spec.get('required_files', ())) | set(spec.get('sha256', {})))
    for name in names:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b'weights')
    (folder / 'my-notes.txt').write_text('mine', encoding='utf-8')
    data = tmp_path / 'data'
    from dataclasses import replace
    from twobyteasr import runtime_paths
    fake = replace(runtime_paths.get_runtime_paths(), model_root=install / 'models', user_data_root=data)
    monkeypatch.setattr(runtime_paths, 'get_runtime_paths', lambda *a, **k: fake)
    monkeypatch.setattr(runtime_paths, 'user_data_root', lambda: data)
    monkeypatch.setattr(alignment_backend, 'official_compat_directory',
                        lambda: str(folder) if (folder / 'config.json').is_file() else '')
    monkeypatch.delenv('2BYTEASR_QWEN3_ALIGNER_DIR', raising=False)
    monkeypatch.delenv(retirement.KEEP_ENV, raising=False)
    events = []
    from twobyteasr.local_models import model_state_events
    monkeypatch.setattr(model_state_events, 'notify', lambda keys, reason='changed': events.append((tuple(keys), reason)))
    return install, folder, names, data, events


def test_verified_ultra_removes_only_the_locked_official_files(installed):
    install, folder, names, data, events = installed
    result = retirement.retire_official_aligner(ULTRA, install_root=install, readiness=READY)
    assert result['status'] == 'removed', result
    assert not any((folder / name).exists() for name in names)
    assert (folder / 'my-notes.txt').read_text(encoding='utf-8') == 'mine'   # unknown files stay
    assert result['freed_bytes'] == len(b'weights') * len(names)
    assert json.loads((data / retirement.RECORD).read_text('utf-8'))['status'] == 'removed'
    assert events == [(('qwen_aligner',), 'removed')]
    # Nothing left to do on the next start.
    assert retirement.retire_official_aligner(ULTRA, install_root=install, readiness=READY)['status'] == 'absent'


@pytest.mark.parametrize(('settings', 'readiness', 'reason'), [
    ({'models': {'firered_asr_backend': 'qwen_aligner', 'qwen_alignment_profile': 'official-v1'}}, READY,
     'official_profile_in_use'),
    ({'models': {'firered_asr_backend': 'qwen_aligner'}}, READY, 'official_profile_in_use'),
    (ULTRA, {}, 'ultra_not_verified'),
])
def test_official_weights_stay_while_they_may_still_run(installed, settings, readiness, reason, monkeypatch):
    install, folder, names, *_ = installed
    from twobyteasr.recognition import qwen_upgrade
    monkeypatch.setattr(qwen_upgrade, 'current_readiness', lambda *a, **k: None)
    result = retirement.retire_official_aligner(settings, install_root=install, readiness=readiness or None)
    assert (result['status'], result['reason']) == ('kept', reason)
    assert all((folder / name).exists() for name in names)


def test_custom_folder_opt_out_and_busy_keep_the_files(installed, monkeypatch):
    install, folder, names, *_ = installed
    assert retirement.retire_official_aligner(ULTRA, install_root=install, readiness=READY,
                                              busy_check=lambda: True)['reason'] == 'busy'
    monkeypatch.setenv(retirement.KEEP_ENV, '1')
    assert retirement.retire_official_aligner(ULTRA, install_root=install, readiness=READY)['reason'] == 'kept_by_environment'
    monkeypatch.delenv(retirement.KEEP_ENV)
    monkeypatch.setenv('2BYTEASR_QWEN3_ALIGNER_DIR', str(folder))
    assert retirement.retire_official_aligner(ULTRA, install_root=install, readiness=READY)['reason'] == 'custom_directory'
    assert all((folder / name).exists() for name in names)


def test_incomplete_managed_weights_can_be_retired_on_next_start(installed):
    install, folder, names, *_ = installed
    (folder / 'config.json').unlink()
    result = retirement.retire_official_aligner(ULTRA, install_root=install, readiness=READY)
    assert result['status'] == 'removed'
    assert not any((folder / name).exists() for name in names)
