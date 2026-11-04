"""Execute the single-worker patch installer in disposable installation folders."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINNED = 'a84ebbfeed5197b5a900c80343c1866d9d3006d1d774d5c3eeca7783fbab850c'
ORIGINAL = b'# synthetic original worker\r\n'
PATCHED = b'# synthetic corrected worker\r\n'
BACKUP = 'moss_worker.py.before-long-audio-20261017'
pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows patch installer')


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / '安装位置 with spaces'
    workers = root / 'workers'
    workers.mkdir(parents=True)
    (root / '2ByteASR.exe').write_bytes(b'fixture, not executed')
    (root / '2byteasr_version.json').write_text(json.dumps({'version': '0.7.5'}), 'utf8')
    (workers / 'moss_worker.py').write_bytes(ORIGINAL)
    patch = tmp_path / '补丁'
    patch.mkdir()
    (patch / 'moss_worker.py').write_bytes(PATCHED)
    (patch / 'patch.json').write_text(json.dumps({'original_sha256': digest(ORIGINAL), 'patched_sha256': digest(PATCHED)}), 'utf8')
    # Only the exact original hash is substituted for the synthetic fixture.
    script = (ROOT / 'scripts/apply_moss_long_audio_hotfix.ps1').read_text('utf-8-sig').replace(PINNED, digest(ORIGINAL))
    (patch / 'apply.ps1').write_text(script, 'utf-8-sig')
    return root, workers, patch


def apply(installation, restore=False):
    root, _, patch = installation
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                           str(patch / 'apply.ps1'), '-InstallDir', str(root), *(['-Restore'] if restore else [])],
                          capture_output=True, encoding='utf8', errors='replace', timeout=30)


def test_installs_idempotently_and_restores_exact_bytes(installation):
    _, workers, _ = installation
    for _ in range(2):
        result = apply(installation)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (workers / 'moss_worker.py').read_bytes() == PATCHED
        assert (workers / BACKUP).read_bytes() == ORIGINAL
    for _ in range(2):
        result = apply(installation, restore=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (workers / 'moss_worker.py').read_bytes() == ORIGINAL
    assert not list(workers.glob('*.tmp'))


@pytest.mark.parametrize('fault', ['version', 'worker', 'payload', 'backup', 'manifest'])
def test_rejects_unexpected_version_or_hash_before_replacing(installation, fault):
    root, workers, patch = installation
    if fault == 'version':
        (root / '2byteasr_version.json').write_text('{"version":"0.7.6"}', 'utf8')
    elif fault == 'manifest':
        (patch / 'patch.json').write_text('{"patched_sha256":"bad"}', 'utf8')
    else:
        path = {'worker': workers / 'moss_worker.py', 'payload': patch / 'moss_worker.py',
                'backup': workers / BACKUP, 'manifest': patch / 'patch.json'}[fault]
        path.write_bytes(b'unexpected content')
    before = (workers / 'moss_worker.py').read_bytes()
    result = apply(installation)
    assert result.returncode == 1, result.stdout + result.stderr
    expected = {'version': '仅适用 0.7.5', 'worker': '当前 worker 与发布',
                'payload': '补丁文件校验失败', 'backup': '已有备份与原版不一致', 'manifest': '补丁清单无效'}
    assert expected[fault] in result.stdout
    assert (workers / 'moss_worker.py').read_bytes() == before
    assert not list(workers.glob('*.tmp'))


def test_restore_rejects_modified_worker_and_bad_backup(installation):
    _, workers, _ = installation
    assert apply(installation).returncode == 0
    (workers / BACKUP).write_bytes(b'corrupt backup')
    assert apply(installation, restore=True).returncode == 1
    assert (workers / 'moss_worker.py').read_bytes() == PATCHED
    (workers / BACKUP).write_bytes(ORIGINAL)
    (workers / 'moss_worker.py').write_bytes(b'newer worker')
    assert apply(installation, restore=True).returncode == 1
    assert (workers / 'moss_worker.py').read_bytes() == b'newer worker'


def test_builder_preserves_version_in_zip_name_and_rejects_other_edits(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('moss_hotfix_builder', ROOT / 'scripts/build_moss_long_audio_hotfix.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    original = tmp_path / 'original.py'
    patched = tmp_path / 'patched.py'
    old = ('def prompt_inputs():\n    pass\n\ndef run():\n'
           '    full_inputs, full_prompt = prompt_inputs(processor, audio, messages, context_limit)\n'
           '    first_inputs = full_inputs if plan["count"] == 1 else None\n    del full_inputs\n'
           '    chunks, windows, attempts, splits = [], [], 0, 0\n')
    new = ('def planning_prompt_length():\n    pass\n\n' + old).replace(
        'full_inputs, full_prompt = prompt_inputs(processor, audio, messages, context_limit)',
        'full_prompt = planning_prompt_length(processor, len(audio), messages)').replace(
        '    first_inputs = full_inputs if plan["count"] == 1 else None\n    del full_inputs\n', '    first_inputs = None\n')
    original.write_bytes(old.encode())
    patched.write_bytes(new.encode())
    monkeypatch.setattr(builder, 'ORIGINAL_SHA256', digest(original.read_bytes()))
    archive = builder.build(original, patched, tmp_path / '2ByteASR-0.7.5-patch')
    assert archive.name == '2ByteASR-0.7.5-patch.zip'
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read('2ByteASR-0.7.5-patch/moss_worker.py') == new.encode()
        assert bundle.read('2ByteASR-0.7.5-patch/apply.ps1').startswith(b'\xef\xbb\xbf')
    patched.write_text(new + '\n# unrelated edit\n', 'utf8')
    with pytest.raises(ValueError, match='beyond this fix'):
        builder.build(original, patched, tmp_path / 'rejected')
