"""The app's own PyTorch wheel download: resume, progress, source switching, SHA-256.

No internet: every source is a folder on a local HTTP server that can be slow,
drop the connection, refuse ranges or serve wrong bytes.
"""
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('install_managed_backend_wheels', ROOT/'scripts/install_managed_backend.py')
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)
# The downloader itself is shared with the macOS preparer since 2026-10-28.
from twobyteasr.system import runtime_package_download as downloads  # noqa: E402
NAME = 'torch-2.11.0+cu126-cp310-cp310-win_amd64.whl'
PAYLOAD = bytes(range(256)) * 1600  # 400 KiB
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class Server:
    """Folders: name -> dict(rate=bytes/s or None, drop_after=bytes, missing, wrong, ignore_range)."""

    def __init__(self, folders):
        self.folders = folders
        self.requests = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                folder, _, name = self.path.strip('/').partition('/')
                rule = server.folders.get(folder)
                start = int(re.match(r'bytes=(\d+)-', self.headers.get('Range', 'bytes=0-')).group(1))
                server.requests.append((folder, name, start))
                if rule is None or rule.get('missing') or name != NAME.replace('+', '%2B'):
                    self.send_error(404)
                    return
                body = (b'\0' * len(PAYLOAD)) if rule.get('wrong') else PAYLOAD
                if start >= len(body):
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{len(body)}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                if rule.get('ignore_range') or not self.headers.get('Range'):
                    start = 0
                    self.send_response(200)
                else:
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(body) - start))
                self.end_headers()
                sent = 0
                drop = rule.pop('drop_after', None)
                for offset in range(start, len(body), 4096):
                    block = body[offset:offset + 4096]
                    if drop is not None and sent + len(block) > drop:
                        self.wfile.write(block[:max(0, drop - sent)])
                        self.wfile.flush()
                        self.close_connection = True
                        return
                    try:
                        self.wfile.write(block)
                    except OSError:
                        return
                    sent += len(block)
                    if rule.get('rate'):
                        time.sleep(len(block) / rule['rate'])

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def source(self, folder, label, official=False):
        return {'label': label, 'url': f'{self.base}/{folder}', 'official': official}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(monkeypatch):
    # Quick timings: speed is judged after 1.5 s over a 3 s window; a trial lasts 0.6 s.
    for name, value in dict(WHEEL_BLOCK=4096, SPEED_GRACE_S=1.5, SPEED_CHECK_S=0.5, SPEED_WINDOW_S=3.0,
                            TRIAL_S=0.6, SLOW_BYTES_PER_SECOND=200_000, WORTH_SWITCHING_S=0.5).items():
        monkeypatch.setattr(downloads, name, value)
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    instances = []

    def start(folders):
        instance = Server(folders)
        instances.append(instance)
        return instance
    yield start
    for instance in instances:
        instance.close()


DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({})).open  # never a system proxy


def download(folder, sources):
    job = installer.WheelDownload(folder, NAME, [SHA], sources, opener=DIRECT, sleep=lambda seconds: None)
    return job, job.fetch()


def markers(text):
    return [json.loads(line.split(' ', 1)[1]) for line in text.splitlines() if line.startswith('[2BYTEASR_RUNTIME_DOWNLOAD] ')]


def test_wheel_names_and_sources_follow_the_lock(monkeypatch):
    assert installer.pytorch_wheel_name('torch==2.11.0+cu128', '3.10.19') == 'torch-2.11.0+cu128-cp310-cp310-win_amd64.whl'
    assert installer.pytorch_wheel_name('torchaudio==2.11.0+cu126', '3.12.13') == 'torchaudio-2.11.0+cu126-cp312-cp312-win_amd64.whl'
    mirrors = json.loads((ROOT/'scripts/runtime_sources.json').read_text('utf8'))['pytorch_mirrors']
    official_first = installer.pytorch_sources(ROOT, 'cu128', False)
    assert official_first[0] == {'label': 'PyTorch 官方', 'url': 'https://download.pytorch.org/whl/cu128', 'official': True}
    assert [item['url'] for item in official_first[1:]] == [item['url'].format(tag='cu128') for item in mirrors]
    mirror_first = installer.pytorch_sources(ROOT, 'cu128', True)
    assert mirror_first[-1]['official'] and not any(item['official'] for item in mirror_first[:-1])
    table = json.loads((ROOT/'scripts/runtime_package_hashes.json').read_text('utf8'))['environments']
    for key, entry in table.items():
        if not key.endswith('|cpu'):
            for name in ('torch', 'torchaudio'):
                if name in entry['packages']:
                    assert len(entry['packages'][name]['sha256']) == 1, key  # one file per environment


def test_progress_lines_and_verified_publication(server, tmp_path, capsys):
    host = server({'official': {}})
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True)])
    assert reason == '' and (tmp_path/NAME).read_bytes() == PAYLOAD
    assert not (tmp_path/(NAME + '.partial')).exists() and not (tmp_path/(NAME + '.partial.json')).exists()
    output = capsys.readouterr().out
    phases = [item['phase'] for item in markers(output)]
    assert phases[-2:] == ['verify', 'done']
    done = markers(output)[-1]
    assert done['downloaded'] == done['total'] == len(PAYLOAD) and done['package'] == 'torch' and done['source'] == 'PyTorch 官方'
    assert f'[PyTorch] 从 PyTorch 官方 下载 {NAME}' in output and 'SHA-256 与锁定值一致' in output


def test_a_paused_download_resumes_from_the_partial_file(server, tmp_path, capsys):
    host = server({'official': {}})
    (tmp_path/(NAME + '.partial')).write_bytes(PAYLOAD[:150_000])  # left by a killed process
    download(tmp_path, [host.source('official', 'PyTorch 官方', True)])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD
    assert host.requests == [('official', NAME.replace('+', '%2B'), 150_000)]
    assert f'从 PyTorch 官方 下载 {NAME}（0.4 MiB），从 0.1 MiB 处继续' in capsys.readouterr().out
    # The finished file is reused next time without any request.
    host.requests.clear()
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True)])
    assert host.requests == [] and reason == ''


def test_a_complete_partial_without_size_record_is_verified_not_redownloaded(server, tmp_path):
    host = server({'official': {}})
    (tmp_path/(NAME + '.partial')).write_bytes(PAYLOAD)
    download(tmp_path, [host.source('official', 'PyTorch 官方', True)])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD
    assert [start for _, _, start in host.requests] == [len(PAYLOAD)]  # one 416 answer, no body


def test_dropped_connection_resumes_on_the_same_source(server, tmp_path, capsys):
    host = server({'official': {'drop_after': 100_000}})
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True)])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD and reason == ''
    starts = [start for _, _, start in host.requests]
    assert starts[0] == 0 and 0 < starts[1] <= 100_000
    assert '从断点继续' in capsys.readouterr().out


def test_slow_official_switches_mid_download_and_keeps_the_bytes(server, tmp_path, capsys):
    host = server({'official': {'rate': 40_000}, 'sjtu': {}})
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True), host.source('sjtu', '上海交大 PyTorch 镜像')])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD
    assert reason.startswith('官方 PyTorch 来源只有') and '上海交大 PyTorch 镜像' in reason
    mirror_starts = [start for folder, _, start in host.requests if folder == 'sjtu']
    assert mirror_starts and mirror_starts[0] > 0  # continued where the official source stopped
    output = capsys.readouterr().out
    assert '试用 上海交大 PyTorch 镜像' in output and '已改用 上海交大 PyTorch 镜像' in output
    events = [item['event'] for item in markers(output) if 'event' in item]
    assert events[0]['kind'] == 'trying' and events[0]['to'] == '上海交大 PyTorch 镜像'  # shown during the trial
    assert events and events[-1]['kind'] == 'switched' and events[-1]['from'] == 'PyTorch 官方'
    assert events[-1]['to'] == '上海交大 PyTorch 镜像' and events[-1]['offset'] == mirror_starts[0]
    assert events[-1]['to_rate'] >= 2 * events[-1]['from_rate']


def test_a_mirror_that_is_not_faster_hands_back_to_official(server, tmp_path, capsys):
    host = server({'official': {'rate': 60_000}, 'nju': {'rate': 60_000}})
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True), host.source('nju', '南京大学 PyTorch 镜像')])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD and reason == ''
    output = capsys.readouterr().out
    assert '不比 PyTorch 官方 快，继续使用 PyTorch 官方' in output
    assert job.check_gap > downloads.SPEED_CHECK_S  # the next check waits longer


def test_missing_official_file_moves_to_the_mirror_at_once(server, tmp_path):
    host = server({'official': {'missing': True}, 'sjtu': {}})
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True), host.source('sjtu', '上海交大 PyTorch 镜像')])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD
    assert reason == '官方 PyTorch 来源未成功（HTTP 404）'
    assert [folder for folder, _, _ in host.requests] == ['official', 'sjtu']
    assert job.event == {'kind': 'failed', 'from': 'PyTorch 官方', 'to': '上海交大 PyTorch 镜像', 'offset': 0}


def test_mirror_preferred_order_ends_with_official(server, tmp_path):
    host = server({'sjtu': {'missing': True}, 'official': {}})
    job, reason = download(tmp_path, [host.source('sjtu', '上海交大 PyTorch 镜像'), host.source('official', 'PyTorch 官方', True)])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD and reason == ''
    assert [folder for folder, _, _ in host.requests] == ['sjtu', 'official']


def test_source_without_range_support_is_left_for_resuming(server, tmp_path):
    host = server({'plain': {'ignore_range': True}, 'official': {}})
    (tmp_path/(NAME + '.partial')).write_bytes(PAYLOAD[:50_000])
    job, reason = download(tmp_path, [host.source('plain', '某镜像'), host.source('official', 'PyTorch 官方', True)])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD
    assert [folder for folder, _, _ in host.requests] == ['plain', 'official']


def test_wrong_bytes_are_never_published(server, tmp_path, capsys):
    host = server({'bad': {'wrong': True}})
    with pytest.raises(RuntimeError, match='SHA-256 都与锁定值不符'):
        download(tmp_path, [host.source('bad', '某镜像')])
    assert not (tmp_path/NAME).exists() and not (tmp_path/(NAME + '.partial')).exists()
    assert capsys.readouterr().out.count('SHA-256 与锁定值不符，已丢弃') == 2


def test_every_source_failing_is_reported_as_network_exhaustion(server, tmp_path):
    host = server({})
    with pytest.raises(installer.SourcesExhausted, match='PyTorch 官方与国内镜像都没有成功'):
        download(tmp_path, [host.source('official', 'PyTorch 官方', True), host.source('sjtu', '上海交大 PyTorch 镜像')])


def test_fetch_uses_the_locked_hash_and_reorders_after_leaving_official(server, tmp_path, monkeypatch):
    seen = []

    class Recorder:
        def __init__(self, folder, name, hashes, sources, **kwargs):
            seen.append((name, list(hashes), [item['official'] for item in sources]))

        def fetch(self):
            return '官方 PyTorch 来源只有 0.5 MB/s，镜像 20.0 MB/s' if len(seen) == 1 else ''
    monkeypatch.setattr(installer, 'WheelDownload', Recorder)
    entry = {'packages': {'torch': {'sha256': ['a' * 64]}, 'torchaudio': {'sha256': ['b' * 64]}}}
    reason = installer.fetch_pytorch_wheels(tmp_path, ['torch==2.11.0+cu126', 'torchaudio==2.11.0+cu126'], '3.10.19',
                                            entry, [{'official': True}, {'official': False}])
    assert reason.startswith('官方 PyTorch 来源只有 0.5 MB/s')
    assert seen == [(NAME, ['a' * 64], [True, False]),
                    ('torchaudio-2.11.0+cu126-cp310-cp310-win_amd64.whl', ['b' * 64], [False, True])]


def test_trials_rotate_until_a_faster_source_is_found(server, tmp_path, capsys):
    host = server({'official': {'rate': 40_000}, 'sjtu': {'rate': 40_000}, 'nju': {}})
    job, reason = download(tmp_path, [host.source('official', 'PyTorch 官方', True),
                                      host.source('sjtu', '上海交大 PyTorch 镜像'), host.source('nju', '南京大学 PyTorch 镜像')])
    assert (tmp_path/NAME).read_bytes() == PAYLOAD
    output = capsys.readouterr().out
    assert output.index('试用 上海交大 PyTorch 镜像') < output.index('试用 南京大学 PyTorch 镜像')
    assert '已改用 南京大学 PyTorch 镜像' in output and reason.startswith('官方 PyTorch 来源只有')
