"""The pinning hook must retain the clean producer of a detached build snapshot."""
import json
from pathlib import Path

import pytest
from twobyteasr.diagnostics import build_identity


def execute_hook(tmp_path, monkeypatch, *, local=False, fingerprint=('sealed', 2126)):
    root = tmp_path/'source'
    root.mkdir()
    metadata = root/'tmp/build.json' if local else tmp_path/'evidence/build.json'
    metadata.parent.mkdir(parents=True)
    record = dict(git_sha='a'*40, git_dirty=False, source_sha256='sealed', source_file_count=2126)
    metadata.write_text(json.dumps(record), 'utf8')
    writes = []
    monkeypatch.setattr(build_identity, 'source_snapshot_sha256', lambda directory: fingerprint)
    monkeypatch.setattr(build_identity, 'write_build_metadata', lambda *args, **kwargs: writes.append(args))
    spec = (Path(__file__).resolve().parents[1]/'packaging/2byteasr_main.spec').read_text('utf8')
    start = spec.index('    from twobyteasr.diagnostics.build_identity import source_snapshot_sha256')
    end = spec.index("    print('Validated native/Tcl inputs pinned", start)
    import textwrap
    exec(textwrap.dedent(spec[start:end]), dict(ROOT=root, build_metadata=metadata, json=json, os=__import__('os')))
    return json.loads(metadata.read_text('utf8')), writes


def test_external_snapshot_keeps_the_clean_producing_commit(tmp_path, monkeypatch):
    record, writes = execute_hook(tmp_path, monkeypatch)
    assert record['git_sha'] == 'a'*40 and not record['git_dirty']
    assert not writes


def test_local_build_refreshes_its_actual_checkout_identity(tmp_path, monkeypatch):
    _, writes = execute_hook(tmp_path, monkeypatch, local=True)
    assert len(writes) == 1


def test_external_snapshot_rejects_changed_runtime_bytes(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match='differs'):
        execute_hook(tmp_path, monkeypatch, fingerprint=('different', 2126))
