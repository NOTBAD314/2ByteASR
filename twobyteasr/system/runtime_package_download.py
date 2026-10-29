"""Locked runtime files fetched by the app itself: resume, measure, switch source, verify.

Standard library only: it runs inside the private Python before any package is
installed (scripts/install_managed_backend.py) and in the macOS app
(local_models/macos_model_prepare.py).

Every source serves the identical file (PyTorch's indexes and their mirrors;
PyPI and the domestic PyPI mirrors under the same ``packages/...`` path), so a
download continues at the same offset on another source and the locked SHA-256
decides before anything is used. uv / pip then install from the local folder.

Measured 2026-10-28 on a mainland line without proxy (2 MB range reads):
files.pythonhosted.org 0.3-3.4 MB/s with TLS/connect timeouts on 2 of 5
files, Aliyun ~0.08 MB/s on every file, Tsinghua 0.4-0.9, Tencent 11-17, USTC
3-22 MB/s. No fixed order works, so sources are measured before a batch and
again while it runs.
"""
from __future__ import annotations

import collections
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

RUNTIME_SOURCE_ENV = '2BYTEASR_RUNTIME_SOURCE'  # 'mirror' | 'official' | 'auto'
PYPI_FILES = 'https://files.pythonhosted.org'
WHEEL_USER_AGENT = '2ByteASR-runtime/1.0'
WHEEL_BLOCK = 1 << 20
WHEEL_READ_TIMEOUT_S = 30
# Below this the next source gets a trial. A trial keeps its bytes, so trying
# costs little; measured 2026-10-14 a mirror sat at ~5 MB/s for 8 minutes
# while the next one gave ~100 MB/s for the same file.
SLOW_BYTES_PER_SECOND = 8 << 20
SPEED_WINDOW_S = 30.0   # speed judged over this window...
SPEED_GRACE_S = 20.0    # ...once a source has had this long...
SPEED_CHECK_S = 30.0    # ...at most this often (doubled after a failed trial)
TRIAL_S = 8.0           # a trial reads the next source at the current offset; its bytes are kept
SWITCH_FACTOR = 2.0
WORTH_SWITCHING_S = 120.0
NO_PROGRESS_RETRIES = 3
MAX_RESUMES = 20
# Before a batch every source reads the same first bytes at once.
PROBE_BYTES = 512 << 10
PROBE_BUDGET_S = 5.0
# Small files are many: a few connections hide each request's latency.
BATCH_WORKERS = 4
CONTENT_RANGE = re.compile(r'bytes\s+(\d+)-(\d+)/(\d+)', re.IGNORECASE)
UNSATISFIED_RANGE = re.compile(r'bytes\s+\*/(\d+)', re.IGNORECASE)
_OUTPUT_LOCK = threading.Lock()


class SourcesExhausted(RuntimeError):
    """Official and fallback sources all failed (install_managed_backend exits with 75)."""


class SourceFailed(Exception):
    """One read from one source ended early; ``final`` sources are not retried."""

    def __init__(self, message, *, final=False, complete=False):
        super().__init__(message)
        self.final = final
        self.complete = complete  # the local partial already covers the whole file


def write_line(text):
    """One whole line on stdout; batch threads never interleave halves of lines."""
    with _OUTPUT_LOCK:
        sys.stdout.write(text + '\n')
        sys.stdout.flush()


def size_text(value):
    return f'{value / 2**30:.2f} GiB' if value >= 2**30 else f'{value / 2**20:.1f} MiB'


def rate_text(value):
    return f'{value / 2**20:.1f} MB/s'


def runtime_preference(value=None):
    """'mirror' (domestic first), 'official' (official first) or 'auto' (measure)."""
    value = str(os.environ.get(RUNTIME_SOURCE_ENV, '') if value is None else value).strip().lower()
    return value if value in ('mirror', 'official') else 'auto'


def preference_for_mode(mode):
    """The workshop's download source choice, applied to runtimes as well."""
    mode = str(mode or 'AUTO').strip().upper()
    if mode in ('MODELSCOPE', 'HF_MIRROR'):
        return 'mirror'
    if mode == 'HF_OFFICIAL':
        return 'official'
    return 'auto'


def pypi_sources(mirrors):
    """PyPI's file host plus the mirrors serving the same ``packages/...`` paths.

    ``mirrors`` are runtime_sources.json ``pypi_mirrors`` rows (simple-index URLs).
    """
    sources = [dict(label='PyPI 官方', url=PYPI_FILES, official=True)]
    for item in mirrors:
        url = str(item.get('url') or '').rstrip('/')
        if url.endswith('/simple'):
            url = url[:-len('/simple')]
        if url.startswith('https://') and all(url != source['url'] for source in sources):
            sources.append(dict(label=str(item.get('label') or urlparse(url).hostname), url=url, official=False))
    return sources


def order_by_preference(sources, preference):
    """Fixed order without measuring: official first, or last for 'mirror'."""
    official = [item for item in sources if item.get('official')]
    others = [item for item in sources if not item.get('official')]
    return [*others, *official] if preference == 'mirror' else [*official, *others]


def _source_url(source, path):
    base = str(source['url'])
    return base.rstrip('/') + '/' + path.lstrip('/') if path else base


class WheelDownload:
    """One locked file: resumable ``.partial``, progress lines and source switching.

    Every source serves the identical file, so a download resumes at the same
    offset on another source; the locked SHA-256 decides before anything is
    published. ``path`` is the file's location below each source (default: its
    name). Progress goes to stdout as ``[2BYTEASR_RUNTIME_DOWNLOAD]`` lines
    (about once a second) plus readable ``[<family>]`` lines for the log, or to
    ``reporter`` when a batch shows one line for many files.
    """

    def __init__(self, folder, name, sha256, sources, *, index=1, count=1, path=None, family='PyTorch',
                 reporter=None, quiet=False, on_leave=None, opener=urllib.request.urlopen, clock=time.monotonic,
                 sleep=time.sleep):
        self.folder = Path(folder)
        self.name = name
        self.path = quote(name, safe='') if path is None else path
        self.hashes = {value.lower() for value in sha256}
        self.sources = list(sources)
        self.index, self.count = index, count
        self.family, self.reporter, self.quiet = family, reporter, quiet
        self.on_leave = on_leave  # told at once when this file gives up a source (a batch reorders the rest)
        self.opener, self.clock, self.sleep = opener, clock, sleep
        self.target = self.folder / name
        self.partial = self.folder / (name + '.partial')
        self.sidecar = self.folder / (name + '.partial.json')
        self.package = name.split('-', 1)[0]
        self.total = None
        self.current = 0
        self.reading = 0
        self.position = 0   # bytes on disk while reading, for a batch's progress line
        self.reason = ''  # why the official source was left, if it was
        self.event = None  # the last source change, for the workshop to word in its language
        self.left = set()  # sources this file gave up on (slow or failing)
        self.strikes = [0] * len(self.sources)
        self.resumes = [0] * len(self.sources)
        self.samples = collections.deque()  # (time, offset) on the current source
        self.recent = collections.deque()   # (time, offset) for the displayed speed
        self.check_gap = SPEED_CHECK_S
        self.last_trial = None  # trials rotate through the other sources
        self.since = self.next_check = 0.0
        self.last_emit = 0.0
        self.last_tenth = -1

    def say(self, text, *, always=False):
        if always or not self.quiet:
            write_line(f'[{self.family}] ' + text)

    def emit(self, phase, downloaded, speed=0.0):
        self.position = int(downloaded)
        if self.reporter is not None:
            self.reporter(self, phase, downloaded, speed)
            return
        source = self.sources[self.reading]
        payload = dict(file=self.name, package=self.package, index=self.index, count=self.count,
                       downloaded=int(downloaded), total=int(self.total or 0), speed=round(speed, 1),
                       source=source['label'], host=urlparse(source['url']).hostname or '', phase=phase)
        if self.event:
            payload['event'] = self.event
        write_line('[2BYTEASR_RUNTIME_DOWNLOAD] ' + json.dumps(payload, ensure_ascii=False))

    def fetch(self):
        """Download (or reuse) the verified file; return why the official source was left."""
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.target.is_file():
            self.total = self.target.stat().st_size
            if self._verified(self.target):
                self.emit('done', self.total)
                self.say(f'{self.name} 已在本机并通过 SHA-256 校验，直接使用')
                return ''
            self.target.unlink()
            self.total = None
        self._load_sidecar()
        for attempt in (1, 2):
            self._download()
            if self._verified(self.partial):
                os.replace(self.partial, self.target)
                self.sidecar.unlink(missing_ok=True)
                self.emit('done', self.total)
                self.say(f'{self.name} 下载完成，SHA-256 与锁定值一致')
                return self.reason
            self.partial.unlink(missing_ok=True)
            self.sidecar.unlink(missing_ok=True)
            self.total = None
            # Which source served the bad bytes is unknown: start again from the first.
            self.current = 0
            self.strikes = [0] * len(self.sources)
            self.resumes = [0] * len(self.sources)
            self.last_tenth = -1
            self.say(f'{self.name} 的 SHA-256 与锁定值不符，已丢弃' + ('，重新下载' if attempt == 1 else ''), always=True)
        message = f'{self.name} 两次下载的 SHA-256 都与锁定值不符，没有安装'
        write_line('[运行库] ' + message)
        raise RuntimeError(message)

    def _verified(self, path):
        self.emit('verify', path.stat().st_size)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(WHEEL_BLOCK * 8), b''):
                digest.update(block)
        return digest.hexdigest() in self.hashes

    def _load_sidecar(self):
        # The total size saved with a partial lets a resumed run show progress at once.
        try:
            saved = json.loads(self.sidecar.read_text('utf8'))
            if set(saved.get('sha256', [])) == self.hashes and int(saved['total']) > 0:
                self.total = int(saved['total'])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _offset(self):
        return self.partial.stat().st_size if self.partial.is_file() else 0

    def _download(self):
        self._restart_clock()
        while True:
            offset = self._offset()
            if self.total is not None and offset >= self.total:
                if offset == self.total:
                    return
                self.partial.unlink()  # longer than the file: never trusted
                continue
            try:
                outcome = self._read(self.current, offset)
            except SourceFailed as failure:
                if failure.complete:
                    continue
                self._failed(self.current, failure, self._offset() > offset)
                continue
            if outcome == 'slow':
                self._try_faster()

    def _failed(self, index, failure, gained):
        label = self.sources[index]['label']
        if gained:
            self.resumes[index] += 1
            self.strikes[index] = 0
        else:
            self.strikes[index] += 1
        if failure.final or self.resumes[index] > MAX_RESUMES:
            self.strikes[index] = NO_PROGRESS_RETRIES
        if self.strikes[index] < NO_PROGRESS_RETRIES:
            self.say(f'{label} 连接中断（{failure}），' + ('从断点继续' if gained else '稍后重试'))
            self.sleep(2 if gained else 5)
            return
        self._leave(index)
        following = self._next()
        if following is None:
            raise SourcesExhausted(f'{self.name} 下载失败：{self.family} 官方与国内镜像都没有成功（最后：{label}，{failure}）')
        if self.sources[index].get('official') and not self.reason:
            self.reason = f'官方 {self.family} 来源未成功（{failure}）'
        offset = self._offset()
        self.event = {'kind': 'failed', 'from': label, 'to': self.sources[following]['label'], 'offset': offset}
        self.say(f"{label} 未成功，改用 {self.sources[following]['label']}" + (f'，从 {size_text(offset)} 处继续' if offset else ''),
                 always=True)
        self.current = following
        self._restart_clock()

    def _leave(self, index):
        self.left.add(index)
        if self.on_leave is not None:
            self.on_leave(self.sources[index]['label'])

    def _next(self):
        """The next usable source after the current one, or None."""
        for step in range(1, len(self.sources)):
            index = (self.current + step) % len(self.sources)
            if self.strikes[index] < NO_PROGRESS_RETRIES:
                return index
        return None

    def _trial_candidate(self):
        """The source after the last one tried (not the current one), or None."""
        start = self.current if self.last_trial is None else self.last_trial
        for step in range(1, len(self.sources) + 1):
            index = (start + step) % len(self.sources)
            if index != self.current and self.strikes[index] < NO_PROGRESS_RETRIES:
                return index
        return None

    def _restart_clock(self):
        now = self.clock()
        self.samples.clear()
        self.since = now
        self.next_check = now + SPEED_GRACE_S

    def _try_faster(self):
        now = self.clock()
        rate = self._rate(self.samples, now, SPEED_WINDOW_S)
        candidate = self._trial_candidate()
        if candidate is None:
            return
        self.last_trial = candidate
        old, new = self.sources[self.current]['label'], self.sources[candidate]['label']
        self.say(f'{old} 最近 {int(SPEED_WINDOW_S)} 秒只有 {rate_text(rate)}，试用 {new}', always=True)
        offset = self._offset()
        before = self.event
        self.event = {'kind': 'trying', 'from': old, 'to': new, 'from_rate': round(rate, 1), 'offset': offset}
        self.reading = candidate
        self.emit('download', offset)  # the window says why the source line changed
        self.reading = self.current
        try:
            trial = self._read(candidate, offset, trial_s=TRIAL_S)
        except SourceFailed as failure:
            self.event = before
            if not failure.complete:
                self._count_trial_failure(candidate, failure, self._offset() > offset)
                self.say(f'{new} 未成功（{failure}），继续使用 {old}', always=True)
            self.check_gap *= 2
            self._restart_clock()
            return
        self.event = before
        if trial >= SWITCH_FACTOR * max(rate, 1.0):
            if self.sources[self.current].get('official') and not self.reason:
                self.reason = f'官方 {self.family} 来源只有 {rate_text(rate)}，{new} {rate_text(trial)}'
            self.event = {'kind': 'switched', 'from': old, 'to': new, 'from_rate': round(rate, 1),
                          'to_rate': round(trial, 1), 'offset': offset}
            self.say(f'{old} 只有 {rate_text(rate)}，已改用 {new}（{rate_text(trial)}），从 {size_text(offset)} 处继续',
                     always=True)
            self._leave(self.current)
            self.current = candidate
            self.last_trial = None
            self.check_gap = SPEED_CHECK_S
        elif self.total is None or self._offset() < self.total:
            self.say(f'{new} 试下 {rate_text(trial)}，不比 {old} 快，继续使用 {old}', always=True)
            self.check_gap *= 2
        self._restart_clock()

    def _count_trial_failure(self, index, failure, gained):
        if failure.final:
            self.strikes[index] = NO_PROGRESS_RETRIES
        elif not gained:
            self.strikes[index] += 1

    @staticmethod
    def _rate(samples, now, window):
        while samples and now - samples[0][0] > window:
            samples.popleft()
        if len(samples) < 2 or samples[-1][0] - samples[0][0] < 1.0:
            return 0.0
        return (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])

    def _open(self, index, offset):
        url = _source_url(self.sources[index], self.path)
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-', 'User-Agent': WHEEL_USER_AGENT,
                                                       'Accept-Encoding': 'identity'})
        try:
            response = self.opener(request, timeout=WHEEL_READ_TIMEOUT_S)
        except urllib.error.HTTPError as error:
            stated = UNSATISFIED_RANGE.fullmatch(str(error.headers.get('Content-Range', '')).strip()) if error.headers else None
            try:
                error.close()
            except Exception:  # noqa: BLE001 - an error without a body has nothing to close
                pass
            if error.code == 416 and offset and stated and offset >= int(stated.group(1)):
                self.total = int(stated.group(1))  # the partial already holds the whole file
                raise SourceFailed('本地文件已完整', complete=True) from error
            raise SourceFailed(f'HTTP {error.code}', final=error.code in (401, 403, 404, 410, 416)) from error
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise SourceFailed(str(getattr(error, 'reason', None) or error) or type(error).__name__) from error
        status = getattr(response, 'status', None) or response.getcode()
        match = CONTENT_RANGE.fullmatch(str(response.headers.get('Content-Range', '')).strip())
        length = str(response.headers.get('Content-Length', '')).strip()
        kind = str(response.headers.get('Content-Type', '')).split(';')[0].strip().lower()
        if status == 206 and match and int(match.group(1)) == offset:
            total = int(match.group(3))
        elif status == 200 and offset == 0 and length.isdigit():
            total = int(length)
        else:
            response.close()
            raise SourceFailed('来源不支持断点续传' if status == 200 else f'HTTP {status} 返回范围不符', final=True)
        if kind in ('text/html', 'application/json') or total <= 0:
            response.close()
            raise SourceFailed('来源返回网页而不是安装包', final=True)
        if self.total is None:
            self.total = total
            self.sidecar.write_text(json.dumps({'total': total, 'sha256': sorted(self.hashes)}), 'utf8')
        elif total != self.total:
            response.close()
            raise SourceFailed(f'文件大小 {total} 与已知的 {self.total} 不一致', final=True)
        free = shutil.disk_usage(self.folder).free
        if free < self.total - offset + (512 << 20):
            response.close()
            message = (f'磁盘空间不足：下载 {self.name} 还需要约 {size_text(self.total - offset)}，'
                       f'安装时解压还要更多空间（当前可用 {size_text(free)}）')
            write_line('[运行库] ' + message)  # the workshop reads stdout only
            raise RuntimeError(message)
        return response

    def _read(self, index, offset, trial_s=None):
        """Append ``sources[index]`` to the partial file from ``offset``.

        Returns 'done' when the file is complete, 'slow' when the speed check
        wants a faster source, or for a trial the measured bytes per second.
        """
        response = self._open(index, offset)
        self.reading = index
        label = self.sources[index]['label']
        if trial_s is None:
            self.say(f'从 {label} 下载 {self.name}（{size_text(self.total)}）' +
                     (f'，从 {size_text(offset)} 处继续' if offset else ''))
        position = offset
        started = self.clock()
        try:
            with response, self.partial.open('ab') as handle:
                if handle.tell() != offset:
                    raise SourceFailed('本地续传文件在下载时被改动', final=True)
                while True:
                    try:
                        block = response.read1(WHEEL_BLOCK) if hasattr(response, 'read1') else response.read(WHEEL_BLOCK)
                    except (OSError, http.client.HTTPException, ValueError) as error:
                        raise SourceFailed(str(error) or type(error).__name__) from error
                    if not block:
                        break
                    if position + len(block) > self.total:
                        raise SourceFailed('响应长度超过文件大小', final=True)
                    handle.write(block)
                    position += len(block)
                    now = self.clock()
                    self._progress(now, position, sample=trial_s is None)
                    if position == self.total:
                        break  # every byte is here; do not wait for the server to close
                    if trial_s is not None and now - started >= trial_s:
                        return (position - offset) / max(now - started, 1e-3)
                    if trial_s is None and self._too_slow(now, position):
                        return 'slow'
        finally:
            self.reading = self.current
        if position < self.total:
            raise SourceFailed('连接提前结束')
        return 'done' if trial_s is None else (position - offset) / max(self.clock() - started, 1e-3)

    def _progress(self, now, position, *, sample):
        self.position = position
        if sample and (not self.samples or now - self.samples[-1][0] >= .5):
            self.samples.append((now, position))
        if not self.recent or now - self.recent[-1][0] >= .25:
            self.recent.append((now, position))
        if now - self.last_emit >= 1.0:
            self.emit('download', position, self._rate(self.recent, now, 5.0))
            self.last_emit = now
        tenth = position * 10 // self.total
        if tenth != self.last_tenth:
            if self.last_tenth >= 0 and tenth < 10:
                self.say(f'{self.package} 已下载 {tenth * 10}%（{size_text(position)} / {size_text(self.total)}）')
            self.last_tenth = tenth

    def _too_slow(self, now, position):
        if now < self.next_check or self._trial_candidate() is None:
            return False
        self.next_check = now + self.check_gap
        rate = self._rate(self.samples, now, SPEED_WINDOW_S)
        if rate >= SLOW_BYTES_PER_SECOND:
            return False
        return not rate or (self.total - position) / rate > WORTH_SWITCHING_S


def measure_sources(sources, path, *, probe_bytes=PROBE_BYTES, budget_s=PROBE_BUDGET_S,
                    opener=urllib.request.urlopen, clock=time.monotonic):
    """Read the same first bytes of ``path`` from every source at once.

    Returns one dict per source (same order): ``rate`` in bytes/s (0 when it
    failed), ``bytes`` read, ``error`` text. Nothing is kept on disk.
    """
    results = [dict(rate=0.0, bytes=0, error='') for _ in sources]

    def probe(index):
        source = sources[index]
        request = urllib.request.Request(_source_url(source, path), headers={
            'Range': f'bytes=0-{probe_bytes - 1}', 'User-Agent': WHEEL_USER_AGENT, 'Accept-Encoding': 'identity'})
        started = clock()
        got = 0
        try:
            with opener(request, timeout=budget_s) as response:
                kind = str(response.headers.get('Content-Type', '')).split(';')[0].strip().lower()
                if kind in ('text/html', 'application/json'):
                    raise ValueError('returned a web page')
                while got < probe_bytes and clock() - started < budget_s:
                    want = min(64 << 10, probe_bytes - got)  # a server may ignore the range's end
                    block = response.read1(want) if hasattr(response, 'read1') else response.read(want)
                    if not block:
                        break
                    got += len(block)
        except urllib.error.HTTPError as error:
            results[index]['error'] = f'HTTP {error.code}'
        except Exception as error:  # noqa: BLE001 - a probe only ranks; any failure means "last"
            results[index]['error'] = str(getattr(error, 'reason', None) or error) or type(error).__name__
        elapsed = max(clock() - started, 1e-3)
        results[index].update(bytes=got, rate=got / elapsed if got else 0.0)

    threads = [threading.Thread(target=probe, args=(index,), daemon=True) for index in range(len(sources))]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + budget_s + 2.0
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    for index, thread in enumerate(threads):
        if thread.is_alive() and not results[index]['error']:
            results[index]['error'] = 'no answer'
    return results


def rank_sources(sources, path, preference='auto', *, measure=None, **options):
    """Sources in trial order plus the measurements behind it.

    'auto' sorts by measured speed (sources that failed keep their order at the
    end); 'mirror' keeps the official source last and 'official' keeps it
    first, measuring only to order the rest.
    """
    results = (measure or measure_sources)(sources, path, **options)
    order = sorted(range(len(sources)), key=lambda index: (-results[index]['rate'], index))
    ranked = [sources[index] for index in order]
    if preference in ('mirror', 'official'):
        ranked = order_by_preference(ranked, preference)
    return ranked, {sources[index]['label']: results[index] for index in range(len(sources))}


def describe_ranking(ranked, measured):
    parts = []
    for source in ranked:
        result = measured.get(source['label']) or {}
        parts.append(source['label'] + (f" {rate_text(result['rate'])}" if result.get('rate') else
                                        f" {result.get('error') or '没有数据'}"))
    return '、'.join(parts)


class SourceBoard:
    """Shared order for one batch: a source a file had to leave moves behind the others."""

    def __init__(self, sources):
        self.sources = list(sources)
        self.demerits = {source['label']: 0 for source in self.sources}
        self.lock = threading.Lock()

    def order(self):
        with self.lock:
            position = {source['label']: index for index, source in enumerate(self.sources)}
            return sorted(self.sources, key=lambda source: (self.demerits[source['label']], position[source['label']]))

    def left(self, labels):
        with self.lock:
            for label in labels:
                if label in self.demerits:
                    self.demerits[label] += 1


def fetch_files(folder, files, sources, *, family='PyPI', workers=BATCH_WORKERS, opener=urllib.request.urlopen,
                clock=time.monotonic, sleep=time.sleep, display='PyPI'):
    """Fetch ``files`` (dicts: name, path, sha256 list, size) into ``folder``.

    Files already there with a locked hash are reused. One progress line covers
    the whole batch. Returns the reasons the official source was left. Raises
    SourcesExhausted / RuntimeError when a file cannot be fetched.
    """
    folder = Path(folder)
    files = sorted(files, key=lambda item: -int(item.get('size') or 0))  # big files first overlap best
    total = sum(int(item.get('size') or 0) for item in files)
    board = SourceBoard(sources)
    state = dict(done=0, completed=0, jobs={}, event=None, event_at=0.0, last_emit=0.0, last_tenth=-1,
                 samples=collections.deque(), reasons=[], error=None)
    lock = threading.Lock()

    def downloaded():
        return state['done'] + sum(job.position for job in state['jobs'].values())

    def report(job, phase, _downloaded, _speed):
        now = clock()
        with lock:
            if job.event and job.event is not state['event']:
                state['event'], state['event_at'] = job.event, now
            if now - state['last_emit'] < 1.0 and phase == 'download':
                return
            state['last_emit'] = now
            bytes_now = downloaded()
            samples = state['samples']
            samples.append((now, bytes_now))
            while samples and now - samples[0][0] > 5.0:
                samples.popleft()
            # A window under 2 s (the batch's first second) gave 106 MB/s for 37 MB/s in a real window.
            span = samples[-1][0] - samples[0][0]
            speed = (samples[-1][1] - samples[0][1]) / span if span >= 2.0 else 0.0
            source = job.sources[job.reading]
            payload = dict(file=job.name, package=display, index=min(state['completed'] + 1, len(files)),
                           count=len(files), downloaded=int(bytes_now), total=int(total), speed=round(speed, 1),
                           source=source['label'], host=urlparse(source['url']).hostname or '', phase='download')
            if state['event'] and now - state['event_at'] < 15.0:
                payload['event'] = state['event']
            lines = ['[2BYTEASR_RUNTIME_DOWNLOAD] ' + json.dumps(payload, ensure_ascii=False)]
            tenth = bytes_now * 10 // total if total else 0
            if tenth > state['last_tenth'] and 0 < tenth < 10:
                state['last_tenth'] = tenth
                lines.append(f'[{family}] 已下载 {tenth * 10}%（{size_text(bytes_now)} / {size_text(total)}，'
                             f'{state["completed"]}/{len(files)} 个文件）')
        for line in lines:
            write_line(line)

    def one(position, item):
        if state['error'] is not None:
            return
        job = WheelDownload(folder, item['name'], item['sha256'], board.order(), index=position, count=len(files),
                            path=item.get('path'), family=family, reporter=report, quiet=True,
                            on_leave=lambda label: board.left([label]), opener=opener, clock=clock, sleep=sleep)
        with lock:
            state['jobs'][id(job)] = job
        try:
            reason = job.fetch()
        except BaseException as error:  # noqa: BLE001 - stop the rest, report the first
            with lock:
                state['jobs'].pop(id(job), None)
                if state['error'] is None:
                    state['error'] = error
            return
        with lock:
            state['jobs'].pop(id(job), None)
            state['done'] += int(job.total or item.get('size') or 0)
            state['completed'] += 1
            if reason:
                state['reasons'].append(reason)

    if files:
        write_line(f'[{family}] 需要 {len(files)} 个文件（{size_text(total)}），每个都按锁定 SHA-256 校验；'
                   f'来源顺序：{"、".join(source["label"] for source in sources)}')
    queue = collections.deque(enumerate(files, 1))
    queue_lock = threading.Lock()

    def worker():
        while True:
            with queue_lock:
                if not queue or state['error'] is not None:
                    return
                position, item = queue.popleft()
            one(position, item)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(workers, len(files))))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if state['error'] is not None:
        raise state['error']
    if files:
        write_line(f'[{family}] {len(files)} 个文件已就绪（{size_text(total)}），都与锁定的 SHA-256 一致')
        write_line('[2BYTEASR_RUNTIME_DOWNLOAD] ' + json.dumps(dict(
            file='', package=display, index=len(files), count=len(files), downloaded=total, total=total,
            speed=0, source=board.order()[0]['label'], host=urlparse(board.order()[0]['url']).hostname or '',
            phase='done'), ensure_ascii=False))
    return state['reasons']


def load_package_files(root):
    """scripts/runtime_package_files.json, or {} when this build has none."""
    try:
        return json.loads((Path(root) / 'scripts/runtime_package_files.json').read_text('utf8'))
    except (OSError, ValueError):
        return {}


def files_for_hashes(table, hashes_by_package):
    """Batch items for ``{package: [sha256, ...]}``; None when the table lacks any of them."""
    rows = (table or {}).get('files') or {}
    items = []
    for package, hashes in sorted(hashes_by_package.items()):
        for digest in hashes:
            row = rows.get(digest)
            if not row:
                return None
            filename, path, size = row
            items.append(dict(name=filename, path=path, sha256=[digest], size=int(size), package=package))
    return items


def wheel_tags(filename):
    """``{'cp310-cp310-macosx_14_0_arm64', ...}`` for a wheel name (compressed tag sets expanded)."""
    stem = str(filename)[:-len('.whl')] if str(filename).endswith('.whl') else ''
    parts = stem.split('-')
    if len(parts) < 5:
        return set()
    pythons, abis, platforms = (part.split('.') for part in parts[-3:])
    return {f'{python}-{abi}-{platform}' for python in pythons for abi in abis for platform in platforms}


def choose_for_tags(candidates, supported):
    """The candidate pip would prefer: the best (earliest) supported tag wins; None if none fits.

    ``candidates`` are (sha256, filename) pairs; ``supported`` is the target
    interpreter's tag list in priority order (``packaging.tags.sys_tags()``).
    """
    rank = {tag: index for index, tag in enumerate(supported)}
    best = None
    for digest, filename in candidates:
        scores = [rank[tag] for tag in wheel_tags(filename) if tag in rank]
        if scores and (best is None or min(scores) < best[0]):
            best = (min(scores), digest)
    return best[1] if best else None
