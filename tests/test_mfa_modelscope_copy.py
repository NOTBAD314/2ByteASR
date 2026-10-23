"""2026-10-22: a maintainer-owned ModelScope copy gives the MFA models a mainland source.

huggingface.co and hf-mirror.com are unreachable on a mainland line without a
proxy, and neither ModelScope nor the MFA GitHub releases carry the locked 3.4.3
files (docs/exec-plans/active/2026-10-22-mfa-models-mainland-source.md).

All offline: a local HTTP server stands in for ModelScope and Hugging Face. The
files keep the MFA layout but have synthetic bytes (the real ones are ~145 MB).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlparse

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr import repository_download as repo

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'dependencies.lock.json').read_text('utf-8-sig'))['models']
COPY = 'maintainer/mandarin_mfa'
COPY_REVISION = 'd' * 40


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _synthetic(key: str) -> tuple[dict, dict[str, bytes]]:
    """The locked MFA entry with the same files, but small bytes and their hashes."""
    spec = json.loads(json.dumps(LOCK[key]))
    payloads = {name: f'{key}:{name}:'.encode() * (64 + index) for index, name in enumerate(spec['required_files'])}
    spec['sha256'] = {name: _digest(body) for name, body in payloads.items()}
    return spec, payloads


def _pins(key='mfa_aligner'):
    return {'schema': 1, 'modelscope': {key: {'repository': COPY, 'revision': COPY_REVISION}}}


def test_mfa_models_only_have_hugging_face_until_a_copy_is_pinned():
    for key in ('mfa_aligner', 'mfa_aligner_ja'):
        plans = repo.planned_sources(repo.effective_spec(key, LOCK[key], {}), 'AUTO')
        assert [p.mode for p in plans] == ['HF_OFFICIAL', 'HF_MIRROR'], key


def test_the_shipped_sources_file_pins_both_mfa_copies():
    # Uploaded and checked on 2026-10-22 (verify_model_download_sources.py: 12/12 hashes each).
    for key, name in (('mfa_aligner', 'mandarin_mfa'), ('mfa_aligner_ja', 'japanese_mfa')):
        plans = repo.planned_sources(repo.effective_spec(key, LOCK[key]), 'AUTO')
        assert [p.mode for p in plans] == ['MODELSCOPE', 'HF_OFFICIAL', 'HF_MIRROR'], key
        assert plans[0].repository == f'Tubai2Byte/{name}' and re.fullmatch(r'[0-9a-f]{40}', plans[0].revision)


def test_pinned_copy_comes_first_and_keeps_the_locked_files_and_hashes():
    spec = LOCK['mfa_aligner']
    merged = repo.effective_spec('mfa_aligner', spec, _pins())
    plans = repo.planned_sources(merged, 'AUTO')
    assert [p.mode for p in plans] == ['MODELSCOPE', 'HF_OFFICIAL', 'HF_MIRROR']
    assert (plans[0].repository, plans[0].revision) == (COPY, COPY_REVISION)
    assert plans[1].repository == 'MontrealCorpusTools/mandarin_mfa' and plans[1].revision == spec['revision']
    locked = {k: v.lower() for k, v in spec['sha256'].items()}
    assert all(p.files == tuple(spec['required_files']) and p.sha256 == locked for p in plans)
    assert repo._artifact_url(plans[0], 'acoustic/final.mdl') == (
        f'https://modelscope.cn/api/v1/models/{COPY}/repo?Revision={COPY_REVISION}&FilePath=acoustic/final.mdl')
    # A chosen source is never widened.
    assert [p.mode for p in repo.planned_sources(merged, 'MODELSCOPE')] == ['MODELSCOPE']
    assert [p.mode for p in repo.planned_sources(merged, 'HF_OFFICIAL')] == ['HF_OFFICIAL']


class _Routes(BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    requests: list[str] = []
    remote: dict[str, dict] = {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        type(self).requests.append(path)
        api = re.fullmatch(r'/api/(.+?/.+?)/(commits|repo/files)', path)
        if api:
            copy = type(self).remote.get(api.group(1))
            if api.group(2) == 'commits':
                body = {'Data': {'Commit': [{'Id': copy['revision']}] if copy else []}}
            else:
                revision = parse_qs(parsed.query).get('Revision', [''])[0]
                rows = [] if not copy or revision != copy['revision'] else [
                    {'Path': name, 'Sha256': digest, 'InCheck': False} for name, digest in copy['files'].items()]
                body = {'Data': {'Files': rows}}
            self._send(json.dumps(body).encode(), 'application/json')
            return
        body = type(self).files.get(path)
        if body is None:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self._send(body, 'application/octet-stream')

    def _send(self, body: bytes, kind: str):
        start, end = 0, len(body) - 1
        if self.headers.get('Range'):
            low, high = self.headers['Range'].removeprefix('bytes=').split('-')
            start, end = int(low), min(int(high) if high else end, end)
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(body)}')
        else:
            self.send_response(200)
        chunk = body[start:end + 1]
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(chunk)))
        self.end_headers()
        try:
            self.wfile.write(chunk)
        except OSError:
            pass

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    _Routes.files, _Routes.requests, _Routes.remote = {}, [], {}
    service = ThreadingHTTPServer(('127.0.0.1', 0), _Routes)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Routes, f'http://127.0.0.1:{service.server_port}'
    finally:
        service.shutdown()
        service.server_close()
        thread.join(3)


def _route_sources(monkeypatch, host):
    monkeypatch.setenv('TWOBYTEASR_DOWNLOAD_PYTHON', sys.executable)
    monkeypatch.setattr(repo, 'load_model_sources', lambda path=None: _pins())
    monkeypatch.setattr(repo, '_artifact_url', lambda manifest, name: host + (
        f'/ms/{manifest.repository}/' if manifest.mode == 'MODELSCOPE' else f'/hf/{manifest.repository}/') + name)


def test_auto_installs_the_mfa_files_from_the_pinned_copy(server, tmp_path, monkeypatch):
    routes, host = server
    spec, payloads = _synthetic('mfa_aligner')
    routes.files = {f'/ms/{COPY}/{name}': body for name, body in payloads.items()}
    _route_sources(monkeypatch, host)
    destination = tmp_path / 'models' / 'MFA-mandarin'
    selected = repo.download_model(model_key='mfa_aligner', spec=spec, destination=destination, mode='AUTO',
                                   staging_root=tmp_path / 'models' / '.downloads')
    assert selected == 'MODELSCOPE'
    assert all((destination / name).read_bytes() == body for name, body in payloads.items())
    assert not [path for path in routes.requests if path.startswith('/hf/')]
    receipt = json.loads((destination / '.2byteasr-source.json').read_text('utf-8'))
    assert (receipt['source_mode'], receipt['repository'], receipt['revision']) == ('MODELSCOPE', COPY, COPY_REVISION)
    assert all(item['verification'] == 'locked_sha256' for item in receipt['files'])


def test_a_file_that_differs_on_the_copy_is_refused_and_taken_from_hugging_face(server, tmp_path, monkeypatch):
    routes, host = server
    spec, payloads = _synthetic('mfa_aligner')
    last = spec['required_files'][-1]
    routes.files = {f'/ms/{COPY}/{name}': (b'tampered' * 50 if name == last else body) for name, body in payloads.items()}
    routes.files[f'/hf/{spec["repository"]}/{last}'] = payloads[last]
    _route_sources(monkeypatch, host)
    monkeypatch.setattr(repo.time, 'sleep', lambda s: None)
    destination = tmp_path / 'models' / 'MFA-mandarin'
    selected = repo.download_model(model_key='mfa_aligner', spec=spec, destination=destination, mode='AUTO',
                                   staging_root=tmp_path / 'models' / '.downloads')
    assert selected == 'HF_OFFICIAL'
    assert (destination / last).read_bytes() == payloads[last]
    assert all((destination / name).read_bytes() == body for name, body in payloads.items())
    # The eleven files the copy delivered intact are reused, not fetched again.
    assert {path for path in routes.requests if path.startswith('/hf/')} == {f'/hf/{spec["repository"]}/{last}'}


def test_download_window_sees_the_same_modelscope_pins_as_the_downloader(tmp_path):
    from twobyteasr.local_models.model_workshop import ModelDownloadDialog
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'dependencies.lock.json').write_text(json.dumps({'models': LOCK}), 'utf-8')
    sources = tmp_path / 'scripts' / 'model_download_sources.json'

    def judged(keys):
        return ModelDownloadDialog._modelscope_ok(SimpleNamespace(root=tmp_path, download_keys=keys))

    sources.write_text(json.dumps({'schema': 1, 'modelscope': {}}), 'utf-8')
    assert judged(('mfa_aligner', 'mfa_aligner_ja')) is False
    sources.write_text(json.dumps({'schema': 1, 'modelscope': {
        'mfa_aligner': {'repository': COPY, 'revision': COPY_REVISION},
        'mfa_aligner_ja': {'repository': 'maintainer/japanese_mfa', 'revision': 'e' * 40}}}), 'utf-8')
    assert judged(('mfa_aligner', 'mfa_aligner_ja')) is True
    assert judged(('mfa_aligner', 'funasr_nano')) is False  # the lock's incompatibility still wins
    # The tokenizer is on ModelScope only through the real sources file; the window used to miss it.
    (tmp_path / 'scripts' / 'model_download_sources.json').write_bytes(
        (ROOT / 'scripts' / 'model_download_sources.json').read_bytes())
    assert judged(('canary_qwen_tokenizer',)) is True


def _mirror_script():
    spec = importlib.util.spec_from_file_location('mirror_models_to_modelscope',
                                                  ROOT / 'scripts' / 'mirror_models_to_modelscope.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeHub:
    """Records calls; an upload publishes the folder's hashes as the copy's newest commit."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def create_repo(self, repo_id, **kwargs):
        self.calls.append(('create_repo', repo_id, kwargs))

    def upload_folder(self, *, repo_id, folder_path, **kwargs):
        self.calls.append(('upload_folder', repo_id, kwargs))
        folder = Path(folder_path)
        files = {path.relative_to(folder).as_posix(): _digest(path.read_bytes())
                 for path in folder.rglob('*') if path.is_file()}
        self.routes.remote[repo_id] = {'revision': hashlib.sha1(json.dumps(files).encode()).hexdigest(), 'files': files}


@pytest.fixture
def mirror(server, tmp_path, monkeypatch):
    routes, host = server
    script = _mirror_script()
    spec, payloads = _synthetic('mfa_aligner')
    lock = tmp_path / 'lock.json'
    lock.write_text(json.dumps({'models': {'mfa_aligner': spec}}), 'utf-8')
    sources = tmp_path / 'model_download_sources.json'
    # The real file without its MFA pins, so the script has to add a line first.
    lines = [line for line in (ROOT / 'scripts' / 'model_download_sources.json').read_text('utf-8').splitlines()
             if not line.strip().startswith('"mfa_aligner')]
    start = lines.index('  "modelscope": {')
    close = next(i for i in range(start, len(lines)) if lines[i].strip() == '},')
    lines[close - 1] = lines[close - 1].rstrip(',')
    assert 'mfa_aligner' not in json.loads('\n'.join(lines))['modelscope']
    sources.write_bytes('\r\n'.join(lines).encode('utf-8') + b'\r\n')  # as a Windows checkout has it
    for name, body in payloads.items():
        routes.files[f'/hf/{spec["repository"]}/resolve/{spec["revision"]}/{name}'] = body
    routes.files[f'/hf/{spec["repository"]}/resolve/{spec["revision"]}/README.md'] = b'---\nlicense: cc-by-4.0\n---\n# card\n'
    monkeypatch.setattr(script, 'HF_ENDPOINT', host + '/hf')
    monkeypatch.setattr(script, 'MODELSCOPE_API', host + '/api')
    monkeypatch.setattr(script, 'REMOTE_DELAY_S', 0)
    monkeypatch.setenv('MODELSCOPE_API_TOKEN', 'fixture-token')
    hub = _FakeHub(routes)
    monkeypatch.setattr(script, '_hub_api', lambda token: hub)
    args = ['--namespace', 'maintainer', '--model', 'mfa_aligner', '--lock', str(lock), '--sources', str(sources),
            '--work', str(tmp_path / 'work')]
    return SimpleNamespace(script=script, routes=routes, spec=spec, payloads=payloads, hub=hub,
                           sources=sources, original=sources.read_bytes(), args=args, work=tmp_path / 'work')


def test_mirror_script_uploads_an_exact_copy_and_writes_a_checked_pin(mirror):
    assert mirror.script.main(mirror.args + ['--write-pin']) == 0
    assert [call[0] for call in mirror.hub.calls] == ['create_repo', 'upload_folder']
    assert mirror.hub.calls[0][2]['visibility'] == 'public' and mirror.hub.calls[0][2]['license'] == 'CC-BY-4.0'
    folder = next((mirror.work / 'mfa_aligner').iterdir())
    assert all((folder / name).read_bytes() == body for name, body in mirror.payloads.items())
    notice = (folder / 'MIRROR_NOTICE.md').read_text('utf-8')
    assert mirror.spec['repository'] in notice and mirror.spec['revision'] in notice and 'CC-BY-4.0' in notice
    assert all(digest in notice for digest in mirror.spec['sha256'].values())
    assert (folder / 'README.md').read_bytes().startswith(b'---\nlicense')
    raw = mirror.sources.read_bytes()
    assert raw.count(b'\r\n') == raw.count(b'\n')  # line endings kept
    pins = json.loads(raw)['modelscope']
    copy = mirror.routes.remote['maintainer/mandarin_mfa']
    assert pins['mfa_aligner'] == {'repository': 'maintainer/mandarin_mfa', 'revision': copy['revision']}
    assert re.fullmatch(r'[0-9a-f]{40}', pins['mfa_aligner']['revision'])
    before = json.loads(mirror.original)['modelscope']
    assert 'mfa_aligner' not in before and {k: v for k, v in pins.items() if k != 'mfa_aligner'} == before
    # Running again replaces the line instead of adding a second one.
    assert mirror.script.main(mirror.args + ['--write-pin']) == 0
    assert mirror.sources.read_bytes().count(b'"mfa_aligner"') == 1


def test_mirror_script_uploads_nothing_when_a_fetched_file_differs_from_the_lock(mirror):
    first = mirror.spec['required_files'][0]
    mirror.routes.files[f'/hf/{mirror.spec["repository"]}/resolve/{mirror.spec["revision"]}/{first}'] = b'other version'
    assert mirror.script.main(mirror.args + ['--write-pin']) == 1
    assert mirror.hub.calls == []
    assert mirror.sources.read_bytes() == mirror.original


def test_mirror_script_writes_no_pin_when_the_uploaded_copy_does_not_match(mirror, monkeypatch):
    monkeypatch.setattr(mirror.script, 'REMOTE_ATTEMPTS', 2)
    real_upload = mirror.hub.upload_folder

    def lossy_upload(**kwargs):
        real_upload(**kwargs)
        copy = mirror.routes.remote[kwargs['repo_id']]
        copy['files'].pop(mirror.spec['required_files'][-1])  # e.g. one file still missing remotely

    mirror.hub.upload_folder = lossy_upload
    assert mirror.script.main(mirror.args + ['--write-pin']) == 1
    assert mirror.sources.read_bytes() == mirror.original


def test_mirror_script_dry_run_needs_no_token_and_uploads_nothing(mirror, monkeypatch):
    monkeypatch.delenv('MODELSCOPE_API_TOKEN')
    assert mirror.script.main(mirror.args + ['--dry-run', '--write-pin']) == 0
    assert mirror.hub.calls == []
    assert mirror.sources.read_bytes() == mirror.original
    assert mirror.script.main(mirror.args) == 2  # a real upload still asks for the token


def test_mirror_script_refuses_models_without_a_full_hash_table():
    script = _mirror_script()
    with pytest.raises(script.MirrorError):
        script.locked_files('x', {'required_files': ['a.bin', 'b.bin'], 'sha256': {'a.bin': 'f' * 64}})
