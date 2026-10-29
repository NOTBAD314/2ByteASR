"""MFA's pkuseg models (2026-10-22): resume, move to a clearly faster source, SHA-256.

A mainland line gave GitHub 15-60 KB/s while ghfast.top gave ~330 KB/s, and
install_mfa_runtime only tried the next source after a failure. No internet
here: every source is its own local HTTP server (so each has its own host:port
label) that can be slow, drop the connection, ignore Range or send wrong bytes.
"""
import hashlib
import http.server
import importlib.util
import io
import re
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

from twobyteasr.local_models.download_activity import DownloadActivity

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('install_mfa_runtime_under_test', ROOT / 'scripts/install_mfa_runtime.py')
mfa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mfa)


def _archive(size):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as package:
        package.writestr('postag/features.pkl', (bytes(range(256)) * (size // 256 + 1))[:size])
    return buffer.getvalue()


PAYLOAD = _archive(300_000)
SHA = hashlib.sha256(PAYLOAD).hexdigest()
GITHUB = 'https://github.com/lancopku/pkuseg-python/releases/download/v0.0.16/postag.zip'
PROGRESS = re.compile(r'^\[运行库\] 中文分词模型 postag：([\d.]+)/([\d.]+) MB（来源：(\S+?)）$')


class Source:
    """One download source: rate (bytes/s), drop_after (bytes, once), missing, wrong, ignore_range."""

    def __init__(self, payload=PAYLOAD, **rule):
        self.rule, self.payload, self.requests = rule, payload, []
        source = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                rule = source.rule
                ranged = self.headers.get('Range')
                start = int(re.match(r'bytes=(\d+)-', ranged or 'bytes=0-').group(1))
                source.requests.append(start)
                if rule.get('missing') or not self.path.endswith('.zip'):
                    self.send_error(404)
                    return
                body = bytes(reversed(source.payload)) if rule.get('wrong') else source.payload
                if rule.get('ignore_range') or not ranged:
                    start = 0
                    self.send_response(200)
                else:
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(body) - start))
                self.end_headers()
                drop, sent = rule.pop('drop_after', None), 0
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
        self.host = f'127.0.0.1:{self.httpd.server_address[1]}'
        self.prefix = f'http://{self.host}/'  # a GitHub proxy: https://ghfast.top/<GitHub URL>

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def sources(monkeypatch):
    # Quick timings: speed is judged after 1.5 s over a 3 s window; a trial lasts 0.6 s.
    for name, value in dict(READ_BLOCK=4096, SPEED_GRACE_S=1.5, SPEED_CHECK_S=0.5, SPEED_WINDOW_S=3.0, TRIAL_S=0.6,
                            SLOW_BYTES_PER_SECOND=200_000, WORTH_SWITCHING_S=0.1, PROGRESS_S=0.2,
                            READ_TIMEOUT_S=10, TRIAL_TIMEOUT_S=10).items():
        monkeypatch.setattr(mfa, name, value)
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    started = []

    def start(**rule):
        started.append(Source(**rule))
        return started[-1]
    yield start
    for source in started:
        source.close()


DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({})).open  # never a system proxy


def fetch(tmp_path, *servers, partial=b''):
    home, work = tmp_path / 'env' / 'share' / 'pkuseg', tmp_path / 'mfa-install'
    home.mkdir(parents=True, exist_ok=True)
    item = {'url': GITHUB, 'sha256': SHA, 'bytes': len(PAYLOAD)}
    job = mfa.PkusegDownload('postag', item, home, work, [server.prefix for server in servers], opener=DIRECT)
    if partial:
        work.mkdir(parents=True, exist_ok=True)
        job.partial.write_bytes(partial)  # left by a killed or restarted installer
    job.fetch()
    return job


def assert_published(job):
    assert hashlib.sha256(job.target.read_bytes()).hexdigest() == SHA
    leftovers = [path.name for path in job.partial.parent.iterdir()]
    assert leftovers == [], leftovers


def progress(output):
    return [match.groups() for match in map(PROGRESS.match, output.splitlines()) if match]


def window_events(output):
    activity = DownloadActivity({})
    activity.reset(0.0, 1_800_000_000.0)
    for second, line in enumerate(output.splitlines()):
        activity.feed(line, float(second), 1_800_000_000.0 + second)
    return activity, [event.text for event in activity.events]


def test_a_slow_source_hands_over_to_a_clearly_faster_one_at_the_same_offset(sources, tmp_path, capsys):
    slow, fast = sources(rate=40_000), sources()
    job = fetch(tmp_path, slow, fast)
    assert_published(job)
    assert slow.requests == [0]                       # never asked again
    assert len(fast.requests) == 1 and fast.requests[0] > 0  # the trial went on at the slow source's offset
    output = capsys.readouterr().out
    assert f'中文分词模型 postag：{slow.host} 最近 3 秒平均' in output and f'，试用 {fast.host}' in output
    switched = next(line for line in output.splitlines() if '太慢，已改用' in line)
    assert f'已改用 {fast.host}（' in switched and f'从 {fast.requests[0] / 1048576:.1f} MB 处继续' in switched
    rows = progress(output)
    assert rows[0][2] == slow.host and rows[-1] == ('0.3', '0.3', fast.host)
    # The download window: the trial row turns into the switch, and the card follows the new source.
    activity, events = window_events(output)
    assert any(text.startswith(f'{slow.host} 只有 ') and f'已改用 {fast.host}（' in text for text in events), events
    assert not any('试用' in text for text in events)  # the trial's row became the outcome
    assert activity.task.source == fast.host


def test_sources_that_are_all_slow_keep_the_current_one_without_alternating(sources, tmp_path, capsys):
    first, second, third = sources(rate=60_000), sources(rate=60_000), sources(rate=60_000)
    job = fetch(tmp_path, first, second, third)
    assert_published(job)
    assert first.requests == [0]                      # its answer waited during the trials, never reopened
    assert len(second.requests) == 1 and len(third.requests) == 1  # one trial each
    output = capsys.readouterr().out
    assert '已改用' not in output
    assert output.index(f'试用 {second.host}') < output.index(f'试用 {third.host}')
    assert output.count(f'不比 {first.host} 明显更快，继续使用 {first.host}') == 2
    assert output.count(f'其他来源都不比 {first.host} 明显更快，继续使用它') == 1
    assert {host for _done, _total, host in progress(output)} == {first.host}
    _activity, events = window_events(output)
    assert f'其他来源都不比 {first.host} 明显更快，继续使用它' in events
    assert sum(' 试下 ' in text and f'继续使用 {first.host}' in text for text in events) == 2  # one row per trial


def test_a_faster_source_without_range_support_starts_over_and_takes_over(sources, tmp_path, capsys):
    slow, plain = sources(rate=40_000), sources(ignore_range=True)
    job = fetch(tmp_path, slow, plain)
    assert_published(job)
    assert plain.requests and len(plain.requests) == 1
    output = capsys.readouterr().out
    assert f'已改用 {plain.host}' in output and '从头下载（它不支持断点续传' in output
    _activity, events = window_events(output)
    assert any('它不支持断点续传，从头下载' in text for text in events), events


def test_a_source_without_range_support_keeps_the_bytes_already_here_until_it_passes_them(sources, tmp_path, capsys):
    # The whole-file answer drops at 40 KB, short of the 100 KB kept from before:
    # those 100 KB stay and the next source continues from them.
    plain, mirror = sources(ignore_range=True, drop_after=40_000), sources()
    job = fetch(tmp_path, plain, mirror, partial=PAYLOAD[:100_000])
    assert_published(job)
    assert mirror.requests == [100_000]
    output = capsys.readouterr().out
    assert f'{plain.host} 不支持断点续传，从头下载（已下载的 0.1 MB 先保留）' in output
    assert f'下载失败，换下一个来源：{plain.prefix}{GITHUB}' in output
    assert f'{mirror.host} 从 0.1 MB 处继续' in output


def test_a_healthy_source_without_range_support_replaces_the_shorter_partial(sources, tmp_path):
    plain, mirror = sources(ignore_range=True), sources()
    job = fetch(tmp_path, plain, mirror, partial=PAYLOAD[:100_000])
    assert_published(job)
    assert plain.requests == [100_000] and mirror.requests == []


def test_a_restart_continues_the_partial_file_and_a_dropped_connection_resumes(sources, tmp_path, capsys):
    server = sources(drop_after=50_000)
    job = fetch(tmp_path, server, partial=PAYLOAD[:20_000])
    assert_published(job)
    assert server.requests[0] == 20_000 and 20_000 < server.requests[1] <= 70_000
    output = capsys.readouterr().out
    assert f'{server.host} 从 0.0 MB 处继续' in output and f'{server.host} 连接中断（' in output
    _activity, events = window_events(output)
    assert f'{server.host} 连接中断，重新连接' in events
    assert any(text.startswith(f'从 {server.host} 的 ') for text in events), events


def test_wrong_bytes_are_never_published_and_their_source_is_not_used_again(sources, tmp_path, capsys):
    bad, good = sources(wrong=True), sources()
    job = fetch(tmp_path, bad, good)
    assert_published(job)
    assert bad.requests == [0] and good.requests == [0]  # the good source starts again from zero
    assert f'校验不符，换下一个来源：{bad.prefix}{GITHUB}' in capsys.readouterr().out


def test_every_source_failing_keeps_the_old_message(sources, tmp_path):
    with pytest.raises(RuntimeError, match=r'^中文分词模型 postag 下载失败（GitHub 与镜像都失败）'):
        fetch(tmp_path, sources(missing=True), sources(missing=True))


def test_install_keeps_a_verified_archive_and_puts_the_proxies_first_for_mirror(sources, tmp_path, monkeypatch):
    direct, proxy = sources(), sources()
    ready = _archive(1000)
    lock = {'pkuseg': {'spacy_ontonotes': {'url': direct.prefix + 'spacy_ontonotes.zip',
                                           'sha256': hashlib.sha256(ready).hexdigest(), 'bytes': len(ready)},
                       'postag': {'url': direct.prefix + 'postag.zip', 'sha256': SHA, 'bytes': len(PAYLOAD)}}}
    monkeypatch.setattr(mfa, 'spec', lambda: lock)
    monkeypatch.setattr(mfa, 'GITHUB_PROXIES', (proxy.prefix,))
    target, work = tmp_path / 'mfa', tmp_path / 'mfa-install'
    home = target / 'share' / 'pkuseg'
    home.mkdir(parents=True)
    (home / 'spacy_ontonotes.zip').write_bytes(ready)
    monkeypatch.setenv('2BYTEASR_RUNTIME_SOURCE', 'mirror')
    original = mfa.PkusegDownload.__init__

    def direct_opener(self, *args, **kwargs):
        original(self, *args, **{**kwargs, 'opener': DIRECT})
    monkeypatch.setattr(mfa.PkusegDownload, '__init__', direct_opener)
    mfa.install_pkuseg(target, work)
    assert (home / 'spacy_ontonotes.zip').read_bytes() == ready  # verified: not downloaded again
    assert (home / 'postag.zip').read_bytes() == PAYLOAD and (home / 'postag' / 'postag' / 'features.pkl').is_file()
    assert proxy.requests == [0] and direct.requests == []  # mirror: the GitHub proxy first
