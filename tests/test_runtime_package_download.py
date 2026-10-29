"""The app's own download of locked runtime package files (2026-10-28).

No internet: every source is a folder on a local HTTP server that can be slow,
stall, refuse or serve wrong bytes; files live at the same ``packages/...``
path on every source, as on PyPI and its mirrors.
"""
import hashlib
import http.server
import json
from pathlib import Path
import re
import threading
import time
import urllib.request

import pytest

from twobyteasr.system import runtime_package_download as downloads

ROOT = Path(__file__).resolve().parents[1]
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({})).open  # never a system proxy


def payload(seed, size):
    return (hashlib.sha256(seed.encode()).digest() * (size // 32 + 1))[:size]


FILES = {f'packages/{index:02x}/aa/pkg{index}-1.0-py3-none-any.whl': payload(str(index), 60_000 + index * 9_000)
         for index in range(6)}


class Server:
    """Folders: name -> dict(rate=bytes/s, missing, wrong, stall_s, ignore_range)."""

    def __init__(self, folders):
        self.folders = folders
        self.requests = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                folder, _, path = self.path.strip('/').partition('/')
                rule = server.folders.get(folder)
                start = int(re.match(r'bytes=(\d+)-', self.headers.get('Range', 'bytes=0-')).group(1))
                server.requests.append((folder, path, start))
                if rule is None or rule.get('missing') or path not in FILES:
                    self.send_error(404)
                    return
                if rule.get('stall_s'):
                    time.sleep(rule['stall_s'])
                body = (b'\0' * len(FILES[path])) if rule.get('wrong') else FILES[path]
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(body) - start))
                self.end_headers()
                for offset in range(start, len(body), 4096):
                    try:
                        self.wfile.write(body[offset:offset + 4096])
                    except OSError:
                        return
                    if rule.get('rate'):
                        time.sleep(4096 / rule['rate'])

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
    for name, value in dict(WHEEL_BLOCK=4096, SPEED_GRACE_S=0.6, SPEED_CHECK_S=0.3, SPEED_WINDOW_S=1.0,
                            TRIAL_S=0.4, SLOW_BYTES_PER_SECOND=200_000, WORTH_SWITCHING_S=0.2,
                            WHEEL_READ_TIMEOUT_S=1.5).items():
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


def items(paths=None):
    return [dict(name=path.rsplit('/', 1)[1], path=path, sha256=[hashlib.sha256(FILES[path]).hexdigest()],
                 size=len(FILES[path])) for path in (paths or FILES)]


def markers(text):
    return [json.loads(line.split(' ', 1)[1]) for line in text.splitlines() if line.startswith('[2BYTEASR_RUNTIME_DOWNLOAD] ')]


def test_runtime_preference_follows_the_download_source_choice(monkeypatch):
    assert [downloads.preference_for_mode(mode) for mode in ('AUTO', 'MODELSCOPE', 'HF_MIRROR', 'HF_OFFICIAL', None)] == \
        ['auto', 'mirror', 'mirror', 'official', 'auto']
    monkeypatch.setenv(downloads.RUNTIME_SOURCE_ENV, 'mirror')
    assert downloads.runtime_preference() == 'mirror'
    monkeypatch.setenv(downloads.RUNTIME_SOURCE_ENV, 'something else')
    assert downloads.runtime_preference() == 'auto'


def test_pypi_mirrors_serve_files_below_their_pypi_root():
    mirrors = json.loads((ROOT/'scripts/runtime_sources.json').read_text('utf8'))['pypi_mirrors']
    sources = downloads.pypi_sources(mirrors)
    assert sources[0] == {'label': 'PyPI 官方', 'url': 'https://files.pythonhosted.org', 'official': True}
    assert [item['url'] for item in sources[1:]] == [item['url'][:-len('/simple')] for item in mirrors]
    assert 'https://pypi.tuna.tsinghua.edu.cn' in [item['url'] for item in sources]  # .../packages/xx/yy/<hash>/<file>
    assert [item['label'] for item in downloads.order_by_preference(sources, 'mirror')][-1] == 'PyPI 官方'


def test_measuring_orders_sources_by_speed_and_keeps_preference(server):
    host = server({'official': {'rate': 60_000}, 'slow': {'rate': 30_000}, 'fast': {}, 'gone': {'missing': True}})
    sources = [host.source('official', 'PyPI 官方', True), host.source('slow', '阿里云'), host.source('fast', '腾讯云'),
               host.source('gone', '中科大')]
    path = next(iter(FILES))
    ranked, measured = downloads.rank_sources(sources, path, 'auto', probe_bytes=40_000, budget_s=2.0, opener=DIRECT)
    assert [item['label'] for item in ranked] == ['腾讯云', 'PyPI 官方', '阿里云', '中科大']
    assert measured['中科大']['error'] == 'HTTP 404' and measured['腾讯云']['bytes'] == 40_000
    mirror_first, _ = downloads.rank_sources(sources, path, 'mirror', probe_bytes=40_000, budget_s=2.0, opener=DIRECT)
    assert [item['label'] for item in mirror_first] == ['腾讯云', '阿里云', '中科大', 'PyPI 官方']
    official_first, _ = downloads.rank_sources(sources, path, 'official', probe_bytes=40_000, budget_s=2.0, opener=DIRECT)
    assert official_first[0]['label'] == 'PyPI 官方' and official_first[1]['label'] == '腾讯云'
    assert '腾讯云 ' in downloads.describe_ranking(ranked, measured)


def test_measuring_a_stalled_source_ends_within_the_budget(server):
    host = server({'stuck': {'stall_s': 5}, 'fine': {}})
    started = time.monotonic()
    ranked, measured = downloads.rank_sources([host.source('stuck', 'PyPI 官方', True), host.source('fine', '中科大')],
                                              next(iter(FILES)), 'auto', budget_s=1.0, opener=DIRECT)
    assert time.monotonic() - started < 4.0
    assert ranked[0]['label'] == '中科大' and measured['PyPI 官方']['rate'] == 0


def test_measuring_survives_any_error_in_a_probe():
    def opener(request, timeout):
        raise RuntimeError('blocked by a test guard')
    ranked, measured = downloads.rank_sources([{'label': 'a', 'url': 'https://a.invalid', 'official': True},
                                               {'label': 'b', 'url': 'https://b.invalid'}], 'x', opener=opener)
    assert [item['label'] for item in ranked] == ['a', 'b'] and 'blocked' in measured['a']['error']


def test_batch_fetches_every_file_verified_with_one_progress_line(server, tmp_path, capsys):
    host = server({'mirror': {}})
    reasons = downloads.fetch_files(tmp_path, items(), [host.source('mirror', '腾讯云')], opener=DIRECT,
                                    sleep=lambda seconds: None)
    assert reasons == []
    for path, body in FILES.items():
        assert (tmp_path/path.rsplit('/', 1)[1]).read_bytes() == body
    assert not list(tmp_path.glob('*.partial*'))
    output = capsys.readouterr().out
    lines = markers(output)
    assert lines[-1]['phase'] == 'done' and lines[-1]['package'] == 'PyPI'
    assert lines[-1]['downloaded'] == lines[-1]['total'] == sum(map(len, FILES.values()))
    assert all(line['count'] == len(FILES) for line in lines)
    assert '需要 6 个文件' in output and '6 个文件已就绪' in output
    # Per-file chatter stays out of the log; the next run reuses verified files without a request.
    assert '从 腾讯云 下载' not in output
    host.requests.clear()
    downloads.fetch_files(tmp_path, items(), [host.source('mirror', '腾讯云')], opener=DIRECT)
    assert host.requests == []


def test_a_slow_source_is_left_mid_file_and_later_files_start_elsewhere(server, tmp_path, capsys):
    host = server({'slow': {'rate': 25_000}, 'fast': {}})
    big = max(FILES, key=lambda path: len(FILES[path]))
    downloads.fetch_files(tmp_path, items([big]), [host.source('slow', '阿里云'), host.source('fast', '腾讯云')],
                          opener=DIRECT, sleep=lambda seconds: None)
    assert (tmp_path/big.rsplit('/', 1)[1]).read_bytes() == FILES[big]
    fast_starts = [start for folder, _, start in host.requests if folder == 'fast']
    assert fast_starts and fast_starts[0] > 0  # continued at the offset the slow source reached
    output = capsys.readouterr().out
    assert '已改用 腾讯云' in output
    assert any(line.get('event', {}).get('kind') == 'switched' for line in markers(output))


def test_a_source_that_fails_is_moved_behind_the_others_for_the_rest_of_the_batch(server, tmp_path):
    host = server({'gone': {'missing': True}, 'fine': {}})
    downloads.fetch_files(tmp_path, items(), [host.source('gone', 'PyPI 官方', True), host.source('fine', '中科大')],
                          workers=1, opener=DIRECT, sleep=lambda seconds: None)
    assert all((tmp_path/path.rsplit('/', 1)[1]).is_file() for path in FILES)
    gone = [path for folder, path, _ in host.requests if folder == 'gone']
    assert len(gone) == 1  # only the first file asked the missing source



def test_leaving_a_source_is_reported_at_once_not_when_the_file_ends(server, tmp_path):
    """Other connections of a batch start their next file elsewhere while this one still runs."""
    host = server({'gone': {'missing': True}, 'fine': {'rate': 200_000}})
    path = next(iter(FILES))
    left = []
    job = downloads.WheelDownload(tmp_path, path.rsplit('/', 1)[1], items([path])[0]['sha256'],
                                  [host.source('gone', '阿里云'), host.source('fine', '中科大')], path=path,
                                  on_leave=lambda label: left.append((label, job.position)), opener=DIRECT,
                                  sleep=lambda seconds: None)
    job.fetch()
    assert left == [('阿里云', 0)]  # before a single byte came from the next source
    board = downloads.SourceBoard([{'label': '阿里云'}, {'label': '中科大'}])
    board.left(['阿里云'])
    assert [item['label'] for item in board.order()] == ['中科大', '阿里云']

def test_wrong_bytes_from_every_source_fail_the_batch(server, tmp_path):
    host = server({'bad': {'wrong': True}})
    with pytest.raises(RuntimeError, match='SHA-256 都与锁定值不符'):
        downloads.fetch_files(tmp_path, items(list(FILES)[:1]), [host.source('bad', '某镜像')], opener=DIRECT,
                              sleep=lambda seconds: None)
    assert not list(tmp_path.glob('*.whl'))


def test_every_source_failing_reports_exhaustion(server, tmp_path):
    host = server({})
    with pytest.raises(downloads.SourcesExhausted, match='PyPI 官方与国内镜像都没有成功'):
        downloads.fetch_files(tmp_path, items(list(FILES)[:2]), [host.source('a', 'PyPI 官方', True),
                              host.source('b', '中科大')], family='PyPI', opener=DIRECT, sleep=lambda seconds: None)


def test_file_table_lookup_needs_every_hash():
    table = {'files': {'a' * 64: ['x-1-py3-none-any.whl', 'packages/aa/x-1-py3-none-any.whl', 10]}}
    assert downloads.files_for_hashes(table, {'x': ['a' * 64]}) == [dict(
        name='x-1-py3-none-any.whl', path='packages/aa/x-1-py3-none-any.whl', sha256=['a' * 64], size=10, package='x')]
    assert downloads.files_for_hashes(table, {'x': ['a' * 64], 'y': ['b' * 64]}) is None
    assert downloads.files_for_hashes({}, {}) == []


def test_wheel_choice_follows_the_interpreter_tag_order():
    assert downloads.wheel_tags('numpy-2.2.6-cp310-cp310-macosx_14_0_arm64.whl') == {'cp310-cp310-macosx_14_0_arm64'}
    assert downloads.wheel_tags('six-1.17.0-py2.py3-none-any.whl') == {'py2-none-any', 'py3-none-any'}
    candidates = [('old', 'numpy-2.2.6-cp310-cp310-macosx_11_0_arm64.whl'),
                  ('new', 'numpy-2.2.6-cp310-cp310-macosx_14_0_arm64.whl'),
                  ('x86', 'numpy-2.2.6-cp310-cp310-macosx_14_0_x86_64.whl')]
    sonoma = ['cp310-cp310-macosx_14_0_arm64', 'cp310-cp310-macosx_13_0_arm64', 'cp310-cp310-macosx_11_0_arm64']
    assert downloads.choose_for_tags(candidates, sonoma) == 'new'
    assert downloads.choose_for_tags(candidates, sonoma[1:]) == 'old'  # macOS 13 cannot use the 14.0 build
    assert downloads.choose_for_tags(candidates, ['cp312-cp312-macosx_14_0_arm64']) is None
