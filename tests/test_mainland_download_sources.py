"""2026-10-14 mainland download round: source pins, AUTO fallback order,
cross-source reuse of verified files and progress-aware resume.

All offline: a local HTTP server stands in for unreliable lines.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from twobyteasr import repository_download as repo

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'dependencies.lock.json').read_text('utf-8-sig'))['models']
SOURCES = json.loads((ROOT / 'scripts' / 'model_download_sources.json').read_text('utf-8'))


def test_source_pins_only_name_a_repository_and_commit_for_known_models():
    assert SOURCES['schema'] == 1
    assert SOURCES['hf_mirror']['official'] is False
    for key, pin in SOURCES['modelscope'].items():
        assert key in LOCK, key
        assert set(pin) == {'repository', 'revision'}, key  # never files or hashes
        assert re.fullmatch(r'[0-9a-f]{40}', pin['revision']), key
        spec = LOCK[key]
        declared = (spec.get('source_manifests') or {}).get('modelscope') or {}
        assert declared.get('compatible') is not False, key
        locked_repository = declared.get('repository') or spec.get('modelscope_repository')
        assert not locked_repository or locked_repository == pin['repository'], key
        # A commit already pinned in the lock is not overridden from here.
        assert (spec.get('modelscope_revision') or 'master') == 'master', key


def test_effective_spec_applies_pin_without_touching_files_or_hashes():
    spec = LOCK['whisper_turbo']
    merged = repo.effective_spec('whisper_turbo', spec)
    assert merged['modelscope_revision'] == SOURCES['modelscope']['whisper_turbo']['revision']
    assert merged['required_files'] == spec['required_files'] and merged['sha256'] == spec['sha256']
    assert spec.get('modelscope_revision') == 'master'  # the lock dict itself is unchanged
    plans = repo.planned_sources(merged, 'AUTO')
    assert [p.mode for p in plans] == ['MODELSCOPE', 'HF_OFFICIAL', 'HF_MIRROR']
    assert plans[0].revision == SOURCES['modelscope']['whisper_turbo']['revision']
    assert all(p.sha256 == {k: v.lower() for k, v in spec['sha256'].items()} for p in plans)


def test_lock_pins_and_incompatibility_win_over_the_source_file():
    pins = {'modelscope': {'x': {'repository': 'org/x', 'revision': 'b' * 40}}}
    pinned = dict(repository='o/x', revision='r', modelscope_repository='org/x', modelscope_revision='a' * 40)
    assert repo.effective_spec('x', pinned, pins)['modelscope_revision'] == 'a' * 40
    incompatible = dict(repository='o/x', revision='r', source_manifests={'modelscope': {'compatible': False}})
    assert [p.mode for p in repo.planned_sources(repo.effective_spec('x', incompatible, pins), 'AUTO')] == [
        'HF_OFFICIAL', 'HF_MIRROR']
    other_repo = dict(repository='o/x', revision='r', modelscope_repository='someone/else')
    assert repo.effective_spec('x', other_repo, pins)['modelscope_repository'] == 'someone/else'


def test_hugging_face_only_models_now_have_a_mainland_path():
    tokenizer = repo.planned_sources(repo.effective_spec('canary_qwen_tokenizer', LOCK['canary_qwen_tokenizer']), 'AUTO')
    assert [p.mode for p in tokenizer] == ['MODELSCOPE', 'HF_OFFICIAL', 'HF_MIRROR']
    assert tokenizer[0].repository == 'Qwen/Qwen3-1.7B'
    nano = repo.planned_sources(repo.effective_spec('funasr_nano', LOCK['funasr_nano']), 'AUTO')
    assert [p.mode for p in nano] == ['HF_OFFICIAL', 'HF_MIRROR']  # ModelScope copy differs from the lock
    url = repo._artifact_url(nano[1], 'model.pt')
    assert url == 'https://hf-mirror.com/FunAudioLLM/Fun-ASR-Nano-2512/resolve/272c57b82523ada6fd87095e955f8e29100979ab/model.pt'


def test_explicit_source_still_never_adds_another():
    assert [p.mode for p in repo.planned_sources(LOCK['moss'], 'HF_OFFICIAL')] == ['HF_OFFICIAL']
    assert [p.mode for p in repo.planned_sources(LOCK['moss'], 'MODELSCOPE')] == ['MODELSCOPE']


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_switching_source_reuses_files_the_failed_source_already_verified(tmp_path, monkeypatch):
    big, small = b'big-verified-weight' * 4096, b'tokenizer'
    spec = dict(repository='org/m', revision='r1', modelscope_repository='org/m', modelscope_revision='c' * 40,
                required_files=['weights.bin', 'tok.json'], sha256={'weights.bin': _digest(big), 'tok.json': _digest(small)})
    calls = []

    def fake_direct(manifest, staging, relative):
        calls.append((manifest.mode, relative))
        if manifest.mode == 'MODELSCOPE' and relative == 'tok.json':
            raise repo.SourceAttemptError('404 Not Found', download_category='source_unavailable')
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(big if relative == 'weights.bin' else small)
        return target

    monkeypatch.setattr(repo, '_download_direct', fake_direct)
    destination, stage = tmp_path / 'models' / 'm', tmp_path / 'models' / '.downloads'
    selected = repo.download_model(model_key='m', spec=spec, destination=destination, mode='AUTO', staging_root=stage)
    assert selected == 'HF_OFFICIAL'
    assert calls == [('MODELSCOPE', 'weights.bin'), ('MODELSCOPE', 'tok.json'), ('HF_OFFICIAL', 'tok.json')]
    assert (destination / 'weights.bin').read_bytes() == big
    receipt = json.loads((destination / '.2byteasr-source.json').read_text('utf-8'))
    assert receipt['source_mode'] == 'HF_OFFICIAL'


def test_corrupt_file_from_another_source_is_not_reused(tmp_path, monkeypatch):
    good = b'good' * 1000
    spec = dict(repository='org/m', revision='r1', required_files=['w.bin'], sha256={'w.bin': _digest(good)})
    bad_stage = tmp_path / 'stage' / 'm' / 'modelscope' / 'old'
    bad_stage.mkdir(parents=True)
    (bad_stage / 'w.bin').write_bytes(b'tampered' * 500)
    calls = []

    def fake_direct(manifest, staging, relative):
        calls.append(manifest.mode)
        (staging / relative).write_bytes(good)
        return staging / relative

    monkeypatch.setattr(repo, '_download_direct', fake_direct)
    repo.download_model(model_key='m', spec=spec, destination=tmp_path / 'dest', mode='AUTO', staging_root=tmp_path / 'stage')
    assert calls == ['HF_OFFICIAL']
    assert (tmp_path / 'dest' / 'w.bin').read_bytes() == good


def _load_fast():
    path = ROOT / 'scripts' / 'download_file_fast.py'
    spec = importlib.util.spec_from_file_location('mainland_fast_downloader', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def flaky_server():
    payload = bytes(range(256)) * 4096 * 8  # 8 MiB; the reader writes 1 MiB blocks

    class Handler(BaseHTTPRequestHandler):
        cut_first = 0        # how many requests are cut after 2.5 MiB
        refuse_all = False
        requests = []

        def log_message(self, *args):
            pass

        def do_GET(self):
            type(self).requests.append(self.headers.get('Range', ''))
            if type(self).refuse_all:
                self.send_response(503)
                self.send_header('Retry-After', '1')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            start = 0
            match = re.fullmatch(r'bytes=(\d+)-', self.headers.get('Range', ''))
            if match:
                start = int(match.group(1))
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{len(payload) - 1}/{len(payload)}')
            else:
                self.send_response(200)
            body = payload[start:]
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if type(self).cut_first > 0:
                type(self).cut_first -= 1
                self.wfile.write(body[:5 * 512 * 1024])
                self.wfile.flush()
                self.connection.shutdown(2)
                return
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, Handler, payload
    server.shutdown()


def test_interrupted_transfer_resumes_past_the_no_progress_retry_limit(tmp_path, flaky_server, monkeypatch):
    server, handler, payload = flaky_server
    handler.cut_first = 4  # more interruptions than RETRIES, each after real progress
    fast = _load_fast()
    monkeypatch.setattr(fast, '_retry_delay', lambda exc, n: 0)
    out = tmp_path / 'w.bin'
    url = f'http://127.0.0.1:{server.server_address[1]}/w.bin'
    assert fast.stream_download(url, out, len(payload), _digest(payload)) == 0
    assert out.read_bytes() == payload
    # Three cuts after real progress, each resumed from the break point.
    assert handler.requests == ['', 'bytes=2097152-', 'bytes=4194304-', 'bytes=6291456-']
    assert len(handler.requests) > fast.RETRIES


def test_source_without_progress_still_gives_up_after_one_retry(tmp_path, flaky_server, monkeypatch):
    server, handler, payload = flaky_server
    handler.refuse_all = True
    fast = _load_fast()
    delays = []
    monkeypatch.setattr(fast.time, 'sleep', delays.append)
    url = f'http://127.0.0.1:{server.server_address[1]}/w.bin'
    assert fast.stream_download(url, tmp_path / 'w.bin', len(payload), _digest(payload)) == 1
    assert len(handler.requests) == fast.RETRIES
    assert delays == [1.0]  # Retry-After honoured (bounded)


def test_bootstrap_urls_for_macos_keep_the_same_file_and_official_first():
    from twobyteasr.download_sources import bootstrap_urls, pip_index_urls
    lock = json.loads((ROOT / 'packaging' / 'macos' / 'bootstrap.lock.json').read_text('utf-8'))
    uv = bootstrap_urls(lock['uv']['url'])
    assert uv == [lock['uv']['url'],
                  'https://releases.astral.sh/github/uv/releases/download/0.11.7/uv-aarch64-apple-darwin.tar.gz']
    python = bootstrap_urls(lock['python']['url'])
    tail = '20260211/cpython-3.10.19%2B20260211-aarch64-apple-darwin-install_only_stripped.tar.gz'
    assert python[0] == lock['python']['url']
    assert python[1:] == ['https://releases.astral.sh/github/python-build-standalone/releases/download/' + tail,
                          'https://registry.npmmirror.com/-/binary/python-build-standalone/' + tail,
                          'https://mirrors.ustc.edu.cn/github-release/astral-sh/python-build-standalone/' + tail]
    pip = bootstrap_urls(lock['pip']['url'])
    path = lock['pip']['url'].split('files.pythonhosted.org', 1)[1]
    assert pip[0] == lock['pip']['url'] and pip[1] == 'https://mirrors.aliyun.com/pypi' + path
    assert len(pip) == 5 and all(u.endswith(path) for u in pip)
    assert pip_index_urls()[0] == 'https://pypi.org/simple' and len(pip_index_urls()) == 5
    assert bootstrap_urls('https://example.com/x.tar.gz') == ['https://example.com/x.tar.gz']


def _spec_two_files(a: bytes, b: bytes):
    return dict(repository='org/m', revision='r1', required_files=['a.json', 'b.bin'],
                sha256={'a.json': _digest(a), 'b.bin': _digest(b)})


def test_reachable_source_retries_a_file_that_times_out_instead_of_failing(tmp_path, monkeypatch):
    a, b = b'{"a":1}', b'weights' * 1000
    calls = []
    hiccups = iter([True, True, False])  # b.bin times out twice, then arrives

    def fake_direct(manifest, staging, relative):
        calls.append((manifest.mode, relative))
        if relative == 'b.bin' and next(hiccups):
            raise repo.SourceAttemptError('Read timed out', download_category='network_timeout')
        (staging / relative).write_bytes(a if relative == 'a.json' else b)
        return staging / relative

    monkeypatch.setattr(repo, '_download_direct', fake_direct)
    monkeypatch.setattr(repo.time, 'sleep', lambda s: None)
    selected = repo.download_model(model_key='m', spec=_spec_two_files(a, b), destination=tmp_path / 'd',
                                   mode='HF_MIRROR', staging_root=tmp_path / 's')
    assert selected == 'HF_MIRROR'
    assert calls == [('HF_MIRROR', 'a.json')] + [('HF_MIRROR', 'b.bin')] * 3


def test_blocked_first_file_still_fails_fast_without_extra_retries(tmp_path, monkeypatch):
    calls = []

    def fake_direct(manifest, staging, relative):
        calls.append((manifest.mode, relative))
        raise repo.SourceAttemptError('Read timed out', download_category='network_timeout')

    monkeypatch.setattr(repo, '_download_direct', fake_direct)
    monkeypatch.setattr(repo.time, 'sleep', lambda s: pytest.fail('no wait for a source that never answered'))
    with pytest.raises(RuntimeError):
        repo.download_model(model_key='m', spec=_spec_two_files(b'a', b'b'), destination=tmp_path / 'd',
                            mode='HF_OFFICIAL', staging_root=tmp_path / 's')
    assert calls == [('HF_OFFICIAL', 'a.json')]


def test_auto_gives_flaky_sources_a_second_round_and_keeps_their_files(tmp_path, monkeypatch, capsys):
    a, b = b'{"a":1}', b'weights' * 1000
    calls = []
    mirror_b = iter(['timeout'] * 4 + ['ok'])  # 1 try + 3 in-source retries fail; second round succeeds

    def fake_direct(manifest, staging, relative):
        calls.append((manifest.mode, relative))
        if manifest.mode == 'HF_OFFICIAL':
            raise repo.SourceAttemptError('Read timed out', download_category='network_timeout')
        if relative == 'b.bin' and next(mirror_b) == 'timeout':
            raise repo.SourceAttemptError('Read timed out', download_category='network_timeout')
        (staging / relative).write_bytes(a if relative == 'a.json' else b)
        return staging / relative

    monkeypatch.setattr(repo, '_download_direct', fake_direct)
    monkeypatch.setattr(repo.time, 'sleep', lambda s: None)
    selected = repo.download_model(model_key='m', spec=_spec_two_files(a, b), destination=tmp_path / 'd',
                                   mode='AUTO', staging_root=tmp_path / 's')
    assert selected == 'HF_MIRROR'
    second_round = calls[calls.index(('HF_MIRROR', 'b.bin')) + 4:]
    assert ('HF_MIRROR', 'a.json') not in second_round  # verified file kept from the first round
    # Round two: the official host starts from the mirror's verified a.json and fails on b.bin.
    assert [c for c in calls if c[0] == 'HF_OFFICIAL'] == [('HF_OFFICIAL', 'a.json'), ('HF_OFFICIAL', 'b.bin')]
    events = [json.loads(line.split(' ', 1)[1]) for line in capsys.readouterr().out.splitlines()
              if line.startswith('[2BYTEASR_SOURCE] ')]
    assert [(e['mode'], e['attempt'], e['total']) for e in events if e.get('status') == 'trying'] == [
        ('HF_OFFICIAL', 1, 2), ('HF_MIRROR', 2, 2), ('HF_OFFICIAL', 3, 4), ('HF_MIRROR', 4, 4)]


def test_redirect_that_states_the_size_allows_a_lengthless_body(tmp_path):
    # hf-mirror.com / huggingface.co for a small git-stored file (2026-10-14):
    # 307 with "Content-Range: bytes 0-0/N", then a 200 body without length or ranges.
    body = b'merges ' * 50000

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/resolve/merges.txt':
                self.send_response(307)
                self.send_header('Content-Range', f'bytes 0-0/{len(body)}')
                self.send_header('Location', '/api/resolve-cache/merges.txt')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()  # no Content-Length; HTTP/1.0 body ends when the connection closes
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        fast = _load_fast()
        url = f'http://127.0.0.1:{server.server_address[1]}/resolve/merges.txt'
        size, ranged = fast.fetch_size(url)
        assert (size, ranged) == (len(body), False)
        out = tmp_path / 'merges.txt'
        assert fast.download_from_source(url, out, size, ranged, 4, _digest(body), 8 << 20, 90) == 0
        assert out.read_bytes() == body
    finally:
        server.shutdown()


def test_parallel_download_uses_more_pieces_than_connections(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 4096 * 8  # 8 MiB
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            match = re.fullmatch(r'bytes=(\d+)-(\d+)', self.headers.get('Range', ''))
            start, end = (int(match.group(1)), int(match.group(2))) if match else (0, len(payload) - 1)
            seen.append((start, end))
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(payload)}')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            self.wfile.write(payload[start:end + 1])

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        fast = _load_fast()
        monkeypatch.setattr(fast, 'MIN_PIECE_BYTES', 1 << 20)
        out = tmp_path / 'w.bin'
        url = f'http://127.0.0.1:{server.server_address[1]}/w.bin'
        assert fast.download_from_source(url, out, len(payload), True, 4, _digest(payload), 1 << 20, 90) == 0
        assert out.read_bytes() == payload
        pieces = sorted(r for r in seen if r != (0, 0))
        assert len(pieces) == 8 and pieces[0][0] == 0 and pieces[-1][1] == len(payload) - 1
    finally:
        server.shutdown()


def test_partial_modelscope_copy_supplies_only_identical_files():
    manifest = repo.partial_source_manifest('funasr_nano', LOCK['funasr_nano'])
    assert manifest is not None and manifest.mode == 'MODELSCOPE'
    assert 'model.pt' not in manifest.files and len(manifest.files) == 9
    assert all(manifest.sha256[f] == LOCK['funasr_nano']['sha256'][f].lower() for f in manifest.files)
    assert repo.partial_source_manifest('funasr_nano', LOCK['funasr_nano'],
                                        {'modelscope_partial': {'funasr_nano': {'repository': 'r', 'revision': 'c',
                                                                                 'files': ['not-locked.bin']}}}) is None


def test_auto_takes_shared_files_from_partial_copy_and_only_the_rest_elsewhere(tmp_path, monkeypatch):
    small, weight = b'{"tok":1}', b'weight' * 5000
    spec = dict(repository='org/nano', revision='r1', required_files=['tok.json', 'model.pt'],
                sha256={'tok.json': _digest(small), 'model.pt': _digest(weight)},
                source_manifests={'modelscope': {'compatible': False}})
    monkeypatch.setattr(repo, 'load_model_sources', lambda path=None: {
        'modelscope_partial': {'nano': {'repository': 'org/nano', 'revision': 'c' * 40, 'files': ['tok.json']}}})
    calls = []

    def fake_direct(manifest, staging, relative):
        calls.append((manifest.mode, relative))
        if manifest.mode == 'HF_OFFICIAL':
            raise repo.SourceAttemptError('Read timed out', download_category='network_timeout')
        (staging / relative).parent.mkdir(parents=True, exist_ok=True)
        (staging / relative).write_bytes(small if relative == 'tok.json' else weight)
        return staging / relative

    monkeypatch.setattr(repo, '_download_direct', fake_direct)
    monkeypatch.setattr(repo.time, 'sleep', lambda s: None)
    selected = repo.download_model(model_key='nano', spec=spec, destination=tmp_path / 'd', mode='AUTO',
                                   staging_root=tmp_path / 's')
    assert selected == 'HF_MIRROR'
    assert ('MODELSCOPE', 'tok.json') in calls and ('MODELSCOPE', 'model.pt') not in calls
    assert ('HF_MIRROR', 'tok.json') not in calls and ('HF_OFFICIAL', 'tok.json') not in calls
    assert (tmp_path / 'd' / 'model.pt').read_bytes() == weight


def _installer():
    path = ROOT / 'scripts' / 'install_managed_backend.py'
    spec = importlib.util.spec_from_file_location('mainland_installer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slow_official_pytorch_prefers_the_hashed_mirror_but_fast_official_stays(monkeypatch):
    installer = _installer()
    pins = ['torch==2.11.0+cu128', 'torchaudio==2.11.0+cu128']
    probed = []

    def rates(official, mirror):
        def probe(url, limit_s=10.0):
            probed.append(url)
            return official if 'download.pytorch.org' in url else mirror
        return probe

    monkeypatch.setattr(installer, 'probe_rate', rates(1.0 * 2**20, 17.0 * 2**20))
    reason = installer.slow_official_pytorch(ROOT, 'cu128', '3.10.19', pins)
    assert reason and '1.0 MB/s' in reason
    assert probed[0] == 'https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp310-cp310-win_amd64.whl'
    assert probed[1].endswith('/cu128/torch-2.11.0%2Bcu128-cp310-cp310-win_amd64.whl')
    probed.clear()
    monkeypatch.setattr(installer, 'probe_rate', rates(30.0 * 2**20, 17.0 * 2**20))
    assert installer.slow_official_pytorch(ROOT, 'cu128', '3.10.19', pins) is None
    assert len(probed) == 1  # a fast official host is not compared with mirrors at all
    monkeypatch.setattr(installer, 'probe_rate', rates(1.0 * 2**20, 1.5 * 2**20))
    assert installer.slow_official_pytorch(ROOT, 'cu128', '3.10.19', pins) is None  # mirror not clearly faster
    assert installer.slow_official_pytorch(ROOT, 'cpu', '3.10.19', ['torch==2.11.0+cpu']) is None


def test_hash_table_closure_includes_requirement_extras():
    # nemo_toolkit[asr] needs datasets, lhotse, ...; a closure locked without the
    # extra made the canary mirror install unsatisfiable (found 2026-10-14).
    table = json.loads((ROOT / 'scripts' / 'runtime_package_hashes.json').read_text('utf-8'))
    for tag in ('cpu', 'cu126', 'cu128'):
        packages = table['environments'][f'canary|3.12.13|{tag}']['packages']
        assert {'datasets', 'lhotse', 'nemo-toolkit'} <= set(packages), tag
    source = (ROOT / 'scripts' / 'build_runtime_package_hashes.py').read_text('utf-8')
    assert 'dependencies = {quoted([*requirements, *extra])}' in source


def test_pieces_reuse_the_redirect_target_and_re_resolve_when_it_expires(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 4096 * 4  # 4 MiB
    hits = {'redirector': 0, 'cdn': 0, 'expired': 0}
    expired = {'signed-1'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/resolve/w.bin':
                hits['redirector'] += 1
                token = 'signed-1' if hits['redirector'] == 1 else 'signed-2'
                self.send_response(302)
                self.send_header('Location', f'/cdn/w.bin?sig={token}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if 'sig=signed-1' in self.path and hits['cdn'] >= 2:
                hits['expired'] += 1  # the first signature expires after two uses
                self.send_response(403)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            hits['cdn'] += 1
            match = re.fullmatch(r'bytes=(\d+)-(\d+)', self.headers.get('Range', ''))
            start, end = (int(match.group(1)), int(match.group(2))) if match else (0, len(payload) - 1)
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(payload)}')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Type', 'application/octet-stream')
            self.end_headers()
            self.wfile.write(payload[start:end + 1])

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        fast = _load_fast()
        monkeypatch.setattr(fast, 'MIN_PIECE_BYTES', 1 << 20)
        url = f'http://127.0.0.1:{server.server_address[1]}/resolve/w.bin'
        size, ranged = fast.fetch_size(url)
        assert fast._resolved_urls[url].endswith('sig=signed-1')
        out = tmp_path / 'w.bin'
        assert fast.download_from_source(url, out, size, ranged, 1, _digest(payload), 1 << 20, 90) == 0
        assert out.read_bytes() == payload
        # 4 pieces: probe + 1 piece on signed-1, refused once, then one re-resolve for the rest
        assert hits['redirector'] == 2 and hits['expired'] == 1
        assert fast._resolved_urls[url].endswith('sig=signed-2')
    finally:
        server.shutdown()
