"""What the model download window shows (2026-10-21): steps, live figures, stalls.

``ModelDownloadDialog`` passes every installer output line to ``feed`` and calls
``tick`` once a second with a sample of the installer's process tree. The
dialog's older parser still writes ``progress_status`` (failure wording and the
final message); this model drives the step track, the current-task card, the
activity graph and the "looks stuck" notice.

Heartbeats (``[2BYTEASR_DEPLOY]`` with ``state=waiting``, every 15 s from both
the PowerShell and the Python supervisor) only prove that a parent script is
alive. They never count as progress: the old "last log: 0 s ago" stayed fresh
while nothing moved (user report 2026-10-21). Progress is new bytes, a new file
or package, a new step, or new output from the working child.

Windows I/O counters do not include network receive (measured 2026-10-21: curl
fetching 100 MB showed only its disk writes), so the probe reports CPU and disk
read/write of the whole tree. Downloads land on disk, unpacking and hashing
read and write it, so a busy silent step (uv installing, a model loading) is
told apart from a hung one.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import re

from ..i18n import tr

STEPS = ('tools', 'runtime', 'weights', 'verify')
# Silent steps where another download source can help.
_SWITCHABLE = frozenset({'packages', 'python', 'tool', 'mfa', 'mfa_packages'})

# Installer phases ([2BYTEASR_PHASE] / [2BYTEASR_DEPLOY]) -> step. Runtime work
# repeats per environment (main, then moss: Python, packages, check, ...), so
# Python, packages and the environment check share one step and the track
# never moves backwards.
PHASE_STEP = {
    'preparing': 'tools', 'runtime_installing': 'tools', 'waiting_for_lock': 'tools', 'tools_preparing': 'tools',
    'interpreter_preparing': 'runtime', 'environment_building': 'runtime', 'dependencies_installing': 'runtime',
    'environment_checking': 'runtime', 'environment': 'runtime', 'runtime_ready': 'runtime',
    'weights_downloading': 'weights', 'downloading': 'weights', 'files_verifying': 'weights', 'weights_ready': 'weights',
    'model_loading': 'verify', 'loading': 'verify', 'model_forward': 'verify', 'inference_verifying': 'verify',
    'adapter_verifying': 'verify',
}

# Without new bytes for this long a download is "waiting for an answer", then "stuck".
NETWORK_QUIET_S = 20
NETWORK_STALL_S = 60
# Steps that report no bytes (installing, checking, loading): only judged when
# the process tree is also idle.
SILENT_QUIET_S = 60
SILENT_STALL_S = 150
LONG_STEP_S = 300
IDLE_CPU_PERCENT = 3.0
IDLE_IO_RATE = 256 * 1024
SLOW_RATE = 200 * 1024
GRAPH_SECONDS = 90

_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
_PATH = re.compile(r'[A-Za-z]:\\')
_SIZE = re.compile(r'([\d.]+)\s*([KMGT]?i?B)\b')
_UV_RESOLVED = re.compile(r'^Resolved (\d+) packages? in ')
_UV_AUDITED = re.compile(r'^Audited (\d+) packages? in ')
_UV_DOWNLOADING = re.compile(r'^Downloading (\S+)(?: \(download\))? \(([\d.]+\s*[KMGT]?i?B)\)\s*$')
_UV_DOWNLOADED = re.compile(r'^Downloaded (\S+)')
_UV_PREPARED = re.compile(r'^Prepared (\d+) packages? in (.+)$')
_UV_INSTALLED = re.compile(r'^Installed (\d+) packages? in (.+)$')
_UV_ADDED = re.compile(r'^[+-] \S+==')
_UV_BUILD = re.compile(r'^(Building|Built) (\S+)')
_UV_PYTHON_DONE = re.compile(r'^Installed Python (\S+) in (.+)$')
_UV_PYTHON_PRESENT = re.compile(r'^Python (\S+) is already installed')
_UV_CHECKED = re.compile(r'^Checked (\d+) packages? in ')
_CURL_METER = re.compile(r'^\s*\d+\s+[\d.]+[kMG]?\s+\d+\s+[\d.]+[kMG]?\s')
# The last line of a Python traceback or a uv/pip "error:" line: the real
# cause, which the dialog's failure text only reports as an exit code.
_ERROR_LINE = re.compile(r'^\s*(?:[A-Za-z_][\w.]*(?:Error|Exception)|error)\s*:\s*(\S.*)$')
# A failure another download source can fix mentions the network or a source
# (2026-10-22: a missing bundled source offered "改用 ModelScope 继续").
_NETWORK_FAILURE_WORDS = ('超时', '连接', '连不上', '网络', '下载失败', '来源', '镜像', 'dns', '代理', 'proxy',
                          'timed out', 'timeout', 'connect', 'fetch', 'ssl', '证书', '403', '404', '429',
                          '502', '503')
_MODEL_START = re.compile(r'^\[下载\] (\S+) @')
_MODEL_COUNT = re.compile(r'^- 需下载 (\d+) 个模型')
_MODEL_BYTES = re.compile(r'^- 预计下载约 ([\d.]+) GiB')
_MODEL_SKIPPED = re.compile(r'^\[跳过\] (\S+) 已是固定版本')
_TOOL_SOURCE = re.compile(r'^来源 (\d+)/(\d+)：(.+)$')
_PACKAGE_INDEX = re.compile(r'^(.+?)（(\d+)/(\d+)）；')
# MFA (experimental) has its own conda runtime: scripts/install_mfa_runtime.py prints these.
_MFA_MAMBA = re.compile(r'^获取 micromamba (\S+)：(\S+)')
_MFA_PACKAGES = re.compile(r'^下载 MFA 运行环境的 (\d+) 个包（约 ([\d.]+\s*[KMGT]?i?B)）')
_MFA_PROGRESS = re.compile(r'^MFA 运行环境：(\d+)/(\d+) 个包，([\d.]+) MB(?:（来源：(.+?)）)?')
_MFA_PKUSEG = re.compile(r'^下载中文分词模型 (\S+)（约 (\d+) MB）')
_MFA_FILE = re.compile(r'^中文分词模型 (\S+)：([\d.]+)/([\d.]+) MB(?:（来源：(.+?)）)?$')
_MFA_READY = re.compile(r'^MFA 运行环境就绪：.*（MFA ([^，）]+)')
_MFA_RETRY = re.compile(r'^(?:下载失败|校验不符|PyPI 来源失败)，换下一个(?:来源)?：(\S+)')
# Source changes while a pkuseg model downloads (2026-10-22, install_mfa_runtime.PkusegDownload).
_MFA_HOST = r'([^\s（），]+)'
_MFA_RATE = r'([\d.]+ [KM]B/s)'
_MFA_TRYING = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST} 最近 \d+ 秒平均 {_MFA_RATE}，试用 {_MFA_HOST}$')
_MFA_SWITCHED = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST}（{_MFA_RATE}）太慢，已改用 {_MFA_HOST}（{_MFA_RATE}），'
                           r'(?:从 ([\d.]+) MB 处继续|从头下载)')
_MFA_KEPT = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST} 试下 {_MFA_RATE}，不比 {_MFA_HOST} 明显更快')
_MFA_TRIAL_FAILED = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST} 没有成功（.*），继续使用 {_MFA_HOST}$')
_MFA_ALL_TRIED = re.compile(rf'^中文分词模型 (\S+?)：其他来源都不比 {_MFA_HOST} 明显更快')
_MFA_CONTINUE = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST} 从 ([\d.]+) MB 处继续$')
_MFA_RESTART = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST} 不支持断点续传，从头下载（已下载的 ([\d.]+) MB 先保留）')
_MFA_RECONNECT = re.compile(rf'^中文分词模型 (\S+?)：{_MFA_HOST} 连接中断（.*），重新连接$')
_URL = re.compile(r'https?://([^/\s：）]+)')
_UNC_OR_DRIVE_PATH = re.compile(r'(?:[A-Za-z]:\\|\\\\)[^\s"\'，。；）]*')

_DOMESTIC_HOSTS = ('modelscope.cn', 'aliyun.com', 'aliyuncs.com', 'tsinghua.edu.cn', 'sjtu.edu.cn', 'nju.edu.cn',
                   'ustc.edu.cn', 'hf-mirror.com', 'huaweicloud.com', 'tencent.com', 'bfsu.edu.cn', '163.com',
                   'gitcode.com', 'gitcode.net', 'npmmirror.com', 'ghfast.top', 'ghproxy.net', 'gh-proxy.org')
_FOREIGN_HOSTS = ('github.com', 'githubusercontent.com', 'astral.sh', 'pypi.org', 'pythonhosted.org',
                  'pytorch.org', 'huggingface.co', 'hf.co', 'xethub.hf.co', 'anaconda.org')


def display_line(line: str, limit: int = 180) -> str:
    """An output line for the window: paths shortened, one line, bounded."""
    text = _UNC_OR_DRIVE_PATH.sub('…', ' '.join(str(line).split()))
    return text if len(text) <= limit else text[:limit - 1] + '…'


def size_text(value: float) -> str:
    value = max(0.0, float(value or 0))
    if value >= 2 ** 30:
        return f'{value / 2 ** 30:.2f} GiB'
    if value >= 2 ** 20:
        return f'{value / 2 ** 20:.1f} MiB'
    return f'{value / 1024:.0f} KiB'


def rate_text(value: float) -> str:
    value = max(0.0, float(value or 0))
    if value >= 2 ** 20:
        return f'{value / 2 ** 20:.1f} MB/s'
    return f'{value / 1024:.0f} KB/s'


def duration_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return tr('{h} 小时 {m} 分', h=seconds // 3600, m=(seconds % 3600) // 60)
    if seconds >= 60:
        return tr('{m} 分 {s} 秒', m=seconds // 60, s=seconds % 60)
    return tr('{s} 秒', s=seconds)


def _parse_size(text: str) -> int:
    match = _SIZE.search(text or '')
    if not match:
        return 0
    unit = match.group(2).upper().replace('I', '')
    scale = {'B': 1, 'KB': 2 ** 10, 'MB': 2 ** 20, 'GB': 2 ** 30, 'TB': 2 ** 40}.get(unit, 1)
    return int(float(match.group(1)) * scale)


def host_region(host: str, label: str = '') -> str:
    """'domestic', 'foreign' or '' for a source host (mainland network view)."""
    host = (host or '').lower()
    if any(host == item or host.endswith('.' + item) for item in _DOMESTIC_HOSTS):
        return 'domestic'
    if any(host == item or host.endswith('.' + item) for item in _FOREIGN_HOSTS):
        return 'foreign'
    if '镜像' in label or 'ModelScope' in label:
        return 'domestic'
    if '官方' in label or 'GitHub' in label or 'Hugging Face' in label:
        return 'foreign'
    return ''


def step_label(step: str) -> str:
    return {'tools': tr('准备工具'), 'runtime': tr('运行环境'), 'weights': tr('模型文件'),
            'verify': tr('加载试跑')}.get(step, step)


@dataclass
class Task:
    """What the installer is doing right now, in figures the card can show."""
    kind: str = ''            # tool, python, packages, torch, torch_verify, env_check, weights, files_verify, load
    title: str = ''
    done: float = 0           # bytes
    total: float = 0
    items_done: int = 0
    items_total: int = 0
    speed: float = 0.0        # bytes/s as reported by the downloader
    speed_at: float = 0.0
    source: str = ''
    host: str = ''
    attempt: str = ''         # "2/3"
    network: bool = False     # bytes are expected to keep arriving
    started_at: float = 0.0


@dataclass
class Event:
    wall: float
    text: str
    tone: str = ''            # '', 'good', 'warn', 'bad'
    merge: str = ''           # consecutive events with the same key update one row


@dataclass
class Assessment:
    level: str                # idle, ok, busy, waiting, slow, quiet, stalled, paused, done, failed
    pill: str
    headline: str = ''
    where: str = ''
    why: str = ''
    actions: tuple = ()       # 'switch:<MODE>', 'pause', 'export', 'log'

    @property
    def tone(self) -> str:
        return {'ok': 'good', 'busy': 'good', 'done': 'good', 'waiting': 'warn', 'slow': 'warn',
                'quiet': 'warn', 'paused': 'muted', 'idle': 'muted', 'stalled': 'bad',
                'failed': 'bad'}.get(self.level, 'muted')

    @property
    def notice(self) -> bool:
        return bool(self.headline)


@dataclass
class _Packages:
    total: int = 0
    announced: dict = field(default_factory=dict)   # name -> bytes
    downloaded: set = field(default_factory=set)
    prepared: bool = False
    installed: int = 0


class DownloadActivity:
    """Parsed state of one installer run; pure Python, driven by the dialog."""

    def __init__(self, model_names: dict | None = None):
        self.model_names = dict(model_names or {})
        self.reset(0.0, 0.0)

    # ------------------------------------------------------------------ state
    def reset(self, now: float, wall: float) -> None:
        self.started_at = now
        self.started_wall = wall
        self.last_progress_at = now
        self.last_bytes_at = now
        self.last_output_at = now
        self.phase = ''
        self.step = ''
        self.step_state = {key: 'pending' for key in STEPS}
        self.step_started = {}
        self.step_finished = {}
        self.step_note = {}
        self.step_fraction = {}
        self.task = Task(started_at=now)
        self.events: deque[Event] = deque(maxlen=300)
        self.role = ''
        self.packages = _Packages()
        self.model_count = 0
        self.model_index = 0
        self.model_name = ''
        self.weights_total = 0
        self._weights_counted: dict = {}
        self._file_key = None
        self._file_size = 0
        self._file_done = 0
        self._tool_attempt = ''
        self._tool_source = ''
        self._torch_event = ''
        self._pythons: set = set()
        self._weights_failed: set = set()   # source modes that failed for the current model
        self._probe: deque = deque(maxlen=240)        # (t, cpu %, io bytes/s)
        self._graph: deque = deque(maxlen=GRAPH_SECONDS)
        self._bytes: deque = deque(maxlen=120)        # (t, task bytes)
        self.finished = ''                            # '', 'done', 'failed', 'paused'
        self.last_line = ''
        self.last_line_at = 0.0
        self.last_error = ''

    def _progress(self, now: float) -> None:
        self.last_progress_at = now

    def _bytes_moved(self, now: float) -> None:
        self.last_bytes_at = self.last_progress_at = now

    def _event(self, wall: float, text: str, tone: str = '', *, merge: str = '') -> None:
        if merge and self.events and self.events[-1].merge == merge:
            self.events[-1].text, self.events[-1].wall, self.events[-1].tone = str(text), wall, tone
            return
        event = Event(wall, str(text), tone, merge)
        if self.events and self.events[-1].text == event.text:
            return
        self.events.append(event)

    def _set_task(self, now: float, kind: str, title: str, **values) -> None:
        keep_source = values.pop('keep_source', False)
        source, host, attempt = self.task.source, self.task.host, self.task.attempt
        self.task = Task(kind=kind, title=str(title), started_at=now, **values)
        if keep_source:
            self.task.source = self.task.source or source
            self.task.host = self.task.host or host
            self.task.attempt = self.task.attempt or attempt
        self._bytes.clear()

    def _enter_step(self, step: str, now: float) -> None:
        if step not in STEPS:
            return
        index = STEPS.index(step)
        if self.step and STEPS.index(self.step) > index:
            return  # a later environment repeats an earlier phase: stay where the track is
        for earlier in STEPS[:index]:
            if self.step_state[earlier] in {'pending', 'active'}:
                self.step_state[earlier] = 'done'
                self.step_finished.setdefault(earlier, now)
                self.step_started.setdefault(earlier, now)
        if self.step != step:
            self.step = step
            self.step_started.setdefault(step, now)
        if self.step_state[step] != 'failed':
            self.step_state[step] = 'active'

    def _set_phase(self, phase: str, now: float) -> None:
        if not phase:
            return
        if phase != self.phase:
            self._progress(now)
        self.phase = phase
        step = PHASE_STEP.get(phase)
        if step:
            self._enter_step(step, now)

    def model_label(self, key: str) -> str:
        return str(self.model_names.get(key) or key)

    # ------------------------------------------------------------------- feed
    def feed(self, line: str, now: float, wall: float) -> None:
        line = _ANSI.sub('', str(line or '')).rstrip()
        if not line.strip():
            return
        for marker, handler in (
                ('[2BYTEASR_DEPLOY] ', self._deploy), ('[2BYTEASR_PHASE] ', self._phase_event),
                ('[2BYTEASR_RUNTIME_DOWNLOAD] ', self._runtime_download), ('[2BYTEASR_PROGRESS] ', self._file_progress),
                ('[2BYTEASR_FILE] ', self._file), ('[2BYTEASR_SOURCE] ', self._source), ('[2BYTEASR_CACHE] ', self._cache),
                ('[2BYTEASR_TOOL_HTTP] ', self._tool_http)):
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker):])
                except (TypeError, ValueError):
                    return
                if isinstance(payload, dict):
                    handler(payload, now, wall)
                return
        if line.startswith('[2BYTEASR_'):
            return  # isolation / error markers: the dialog's own handling covers them
        self.last_output_at = now
        if _CURL_METER.match(line) or line.lstrip().startswith(('% Total', 'Dload')):
            return  # curl's meter repeats itself while nothing moves
        self._progress(now)
        # The newest line from the working program, for steps nothing below
        # understands: the window shows it, so the raw log need not be opened.
        self.last_line, self.last_line_at = display_line(line), now
        error = _ERROR_LINE.match(line)
        if error and '子程序退出码' not in error.group(1):
            self.last_error = display_line(error.group(1), 160)
        if not self._mfa(line.strip(), now, wall):
            self._human(line.strip(), now, wall)

    def _mfa(self, line: str, now: float, wall: float) -> bool:
        """MFA (experimental): its own conda runtime from install_mfa_runtime.py."""
        if line.startswith('[错误] '):
            self._event(wall, display_line(line[5:], 140), 'bad')
            return True
        if line.startswith('[跳过] MFA 运行环境已就绪'):
            self._enter_step('runtime', now)
            self.step_note['runtime'] = 'reused'
            self._event(wall, tr('MFA 运行环境已就绪（沿用）'), 'good')
            return True
        if not line.startswith('[运行库] '):
            return False
        detail = line[6:].strip()
        if detail.startswith('正在准备 MFA'):
            self._enter_step('runtime', now)
            self._set_task(now, 'mfa', tr('准备 MFA（实验）运行环境'))
            return True
        if match := _MFA_MAMBA.match(detail):
            self._enter_step('runtime', now)
            host = _URL.search(match.group(2))
            self._set_task(now, 'mfa', tr('下载安装工具 micromamba {version}', version=match.group(1)),
                           source=host.group(1) if host else '', host='')
            return True
        if match := _MFA_PACKAGES.match(detail):
            self._enter_step('runtime', now)
            self._set_task(now, 'mfa_packages', tr('下载 MFA 运行环境（{count} 个包）', count=match.group(1)),
                           items_total=int(match.group(1)), total=float(_parse_size(match.group(2))))
            return True
        if match := _MFA_PROGRESS.match(detail):
            self._enter_step('runtime', now)
            done, count, size = int(match.group(1)), int(match.group(2)), float(match.group(3)) * 2 ** 20
            if self.task.kind != 'mfa_packages':
                self._set_task(now, 'mfa_packages', tr('下载 MFA 运行环境（{count} 个包）', count=count),
                               items_total=count, total=340.0 * 2 ** 20)
            task = self.task
            if done > task.items_done or size > task.done:
                self._bytes_moved(now)
            task.items_done, task.items_total = done, count
            task.done = size
            task.total = max(task.total, size)
            if match.group(4):
                task.source = match.group(4)
                task.host = match.group(4) if '.' in match.group(4) else ''
            self._bytes.append((now, task.done))
            return True
        if detail.startswith('正在组装 MFA 运行环境'):
            self._event(wall, tr('MFA 运行环境的包已下载'), 'good')
            self._set_task(now, 'mfa_build', tr('组装 MFA 运行环境（不联网）'))
            return True
        if detail.startswith('安装 MFA 中文分词依赖'):
            self._set_task(now, 'mfa', tr('安装 MFA 中文分词依赖'))
            return True
        if match := _MFA_PKUSEG.match(detail):
            # A network download with byte progress (2026-10-22): GitHub from a mainland
            # line trickles at ~50 KB/s and was reported as "可能卡住".
            self._set_task(now, 'mfa_file', tr('下载中文分词模型 {name}（约 {size}）', name=match.group(1),
                                               size=size_text(int(match.group(2)) * 2 ** 20)),
                           network=True, total=float(int(match.group(2)) * 2 ** 20))
            return True
        if match := _MFA_FILE.match(detail):
            done, total = float(match.group(2)) * 2 ** 20, float(match.group(3)) * 2 ** 20
            if self.task.kind != 'mfa_file':
                self._set_task(now, 'mfa_file', tr('下载中文分词模型 {name}（约 {size}）', name=match.group(1),
                                                   size=size_text(total)), network=True)
            task = self.task
            if done < task.done:
                self._bytes.clear()  # the next source starts from zero
            if done > task.done or not self._bytes:
                self._bytes_moved(now)
            task.done, task.total = done, total or task.total
            if match.group(4):
                task.source = task.host = match.group(4)
            self._bytes.append((now, task.done))
            return True
        if detail.startswith('中文分词模型 '):
            return self._mfa_source(detail, now, wall)
        if detail.startswith('检查 MFA 运行环境'):
            self._set_task(now, 'env_check', tr('检查 MFA 运行环境能否运行'))
            return True
        if match := _MFA_READY.match(detail):
            self._event(wall, tr('MFA 运行环境就绪（MFA {version}）', version=match.group(1)), 'good')
            return True
        if match := _MFA_RETRY.match(detail):
            host = _URL.search(match.group(1))
            self._event(wall, tr('{origin} 没有成功，换下一个来源', origin=host.group(1) if host else match.group(1)), 'warn',
                        merge='mfa-retry')
            return True
        if detail.startswith('清理上次未完成的 MFA 运行环境'):
            self._event(wall, tr('清理上次没装完的 MFA 运行环境'))
            return True
        return False

    def _mfa_source(self, detail: str, now: float, wall: float) -> bool:
        """A pkuseg model's source changes: a trial and its outcome share one row of 最近动态."""
        if match := _MFA_TRYING.match(detail):
            name, old, rate, new = match.groups()
            self._bytes_moved(now)  # the trial reads for a few seconds without progress lines
            self._event(wall, tr('{old} 只有 {rate}，试用 {new}', old=old, rate=rate, new=new), merge=f'mfa-trial:{name}:{new}')
        elif match := _MFA_SWITCHED.match(detail):
            name, old, old_rate, new, new_rate, offset = match.groups()
            if offset is None:
                text = tr('{old} 只有 {old_rate}，已改用 {new}（{new_rate}）；它不支持断点续传，从头下载',
                          old=old, old_rate=old_rate, new=new, new_rate=new_rate)
            else:
                text = tr('{old} 只有 {old_rate}，已改用 {new}（{new_rate}），从 {offset} 处继续', old=old,
                          old_rate=old_rate, new=new, new_rate=new_rate, offset=size_text(float(offset) * 2 ** 20))
            self._event(wall, text, 'warn', merge=f'mfa-trial:{name}:{new}')
            if self.task.kind == 'mfa_file':
                # The trial's speed until the new source's own progress lines give one.
                self._bytes.clear()
                self.task.speed, self.task.speed_at = float(_parse_size(new_rate)), now
                self.task.source = self.task.host = new
            self._bytes_moved(now)
        elif match := _MFA_KEPT.match(detail):
            name, new, rate, old = match.groups()
            self._event(wall, tr('{new} 试下 {rate}，不比 {old} 明显更快，继续使用 {old}', new=new, rate=rate, old=old),
                        merge=f'mfa-trial:{name}:{new}')
        elif match := _MFA_TRIAL_FAILED.match(detail):
            name, new, old = match.groups()
            self._event(wall, tr('{new} 没有成功，继续使用 {old}', new=new, old=old), 'warn', merge=f'mfa-trial:{name}:{new}')
        elif match := _MFA_ALL_TRIED.match(detail):
            self._event(wall, tr('其他来源都不比 {origin} 明显更快，继续使用它', origin=match.group(2)))
        elif match := _MFA_CONTINUE.match(detail):
            self._event(wall, tr('从 {origin} 的 {offset} 处继续下载', origin=match.group(2),
                                 offset=size_text(float(match.group(3)) * 2 ** 20)))
        elif match := _MFA_RESTART.match(detail):
            self._event(wall, tr('{origin} 不支持断点续传，从头下载（已下载的 {offset} 先保留）', origin=match.group(2),
                                 offset=size_text(float(match.group(3)) * 2 ** 20)), 'warn')
        elif match := _MFA_RECONNECT.match(detail):
            self._event(wall, tr('{origin} 连接中断，重新连接', origin=match.group(2)), 'warn')
        else:
            return False
        return True

    def _deploy(self, payload: dict, now: float, wall: float) -> None:
        phase, state = str(payload.get('phase') or ''), str(payload.get('state') or '')
        component = str(payload.get('component') or '')
        if state == 'waiting':
            downloaded = payload.get('downloaded')
            if isinstance(downloaded, (int, float)) and self.task.kind == 'tool' and downloaded > self.task.done:
                self.task.done = float(downloaded)
                self._bytes.append((now, self.task.done))
                # The supervisor reports every 15 s; it also says when the file last grew.
                age = payload.get('progress_age_s')
                moved = now - float(age) if isinstance(age, (int, float)) else now
                self.last_bytes_at = self.last_progress_at = max(self.last_bytes_at, moved)
            return  # a heartbeat: the parent lives; not progress
        if state == 'start' and not component:
            return  # the PowerShell supervisor starting its child; the child's own events follow
        self._set_phase(phase, now)
        self._progress(now)
        if state == 'start':
            if phase == 'tools_preparing':
                self._set_task(now, 'tool', tr('下载安装工具 uv'), network=True,
                               source=self._tool_source, attempt=self._tool_attempt)
            elif phase == 'environment_building':
                self.role = component
                self._event(wall, tr('新建 {role} 运行环境', role=component))
            elif phase == 'dependencies_installing' and payload.get('source'):
                self.role = component or self.role
                attempt = payload.get('attempt')
                self._set_task(now, 'packages', tr('安装依赖（{role} 环境）', role=self.role or 'main'),
                               source=str(payload['source']), attempt=str(attempt or ''))
                self.packages = _Packages()
                self._event(wall, tr('从 {origin} 安装依赖', origin=str(payload['source'])))
            elif phase == 'dependencies_installing' and component == '下载并安装依赖':
                if self.task.kind != 'packages':
                    self._set_task(now, 'packages', tr('安装依赖（{role} 环境）', role=self.role or 'main'))
                self.packages = _Packages()
            elif phase == 'dependencies_installing' and component == '创建运行环境':
                self._set_task(now, 'packages', tr('创建 {role} 运行环境', role=self.role or 'main'))
                # A new environment: the previous one's package counts no longer apply
                # (2026-10-22: "创建 moss 运行环境" showed main's "共 104 个依赖").
                self.packages = _Packages()
            elif phase == 'interpreter_preparing':
                self._set_task(now, 'python', tr('准备专用 Python'))
            elif phase == 'environment_checking':
                role = self.role if component in {'检查依赖', ''} or component.endswith('package inventory') else component
                self._set_task(now, 'env_check', tr('检查 {role} 运行环境', role=role or 'main'))
            elif phase == 'weights_downloading':
                self._set_task(now, 'weights', tr('下载 {model}', model=self.model_name or self.model_label(component)),
                               network=True)
            elif phase == 'model_loading':
                self._set_task(now, 'load', tr('加载 {model} 并用样本试跑', model=self.model_label(component)))
        elif state == 'failed' and component:
            # The PowerShell supervisor repeats its child's failure without a component.
            reason = str(payload.get('reason') or '').partition('\n')[0]
            if _PATH.search(reason) or len(reason) > 120:
                reason = ''
            what = self.task.title or self.model_label(component)
            self._event(wall, tr('{what} 未成功', what=what) + (f'：{reason}' if reason else ''), 'bad')

    def _phase_event(self, payload: dict, now: float, wall: float) -> None:
        phase = str(payload.get('phase') or '')
        model = str(payload.get('model') or '')
        if phase == 'ready' and model:
            self._event(wall, tr('{model} 加载与试跑通过', model=self.model_label(model)), 'good')
            self._progress(now)
            return
        self._set_phase(phase, now)
        if phase == 'waiting_for_lock':
            self._set_task(now, 'lock', tr('等待另一项环境准备完成'))
        elif phase == 'tools_preparing' and self.task.kind != 'tool':
            self._set_task(now, 'tool', tr('准备安装工具 uv'))
        elif phase == 'interpreter_preparing' and self.task.kind != 'python':
            self._set_task(now, 'python', tr('准备专用 Python'))
        elif phase == 'runtime_ready':
            if self.step_state['runtime'] == 'active':
                self.step_state['runtime'] = 'done'
                self.step_finished['runtime'] = now
            if self.task.kind in {'packages', 'env_check', 'python'}:
                self._set_task(now, 'idle', tr('运行环境已就绪'))
        elif phase == 'files_verifying':
            name = model or self.model_name
            self._set_task(now, 'files_verify', tr('校验 {model} 的文件', model=name) if name else tr('校验模型文件'))
        elif phase == 'weights_ready':
            self._finish_file(now)
            self._event(wall, tr('{model} 的文件已下载', model=self.model_name or tr('模型')), 'good')
        elif phase == 'model_loading' and model:
            self._set_task(now, 'load', tr('加载 {model} 并用样本试跑', model=self.model_label(model)))
        elif phase in {'weights_downloading', 'downloading'} and self.task.kind != 'weights':
            self._set_task(now, 'weights', tr('下载 {model}', model=self.model_name or tr('模型文件')), network=True)

    def _runtime_download(self, payload: dict, now: float, wall: float) -> None:
        package = str(payload.get('package') or 'torch')
        name = 'PyTorch' if package == 'torch' else package
        phase = str(payload.get('phase') or 'download')
        index, count = int(payload.get('index') or 1), int(payload.get('count') or 1)
        self._enter_step('runtime', now)
        self._progress(now)
        source, host = str(payload.get('source') or ''), str(payload.get('host') or '')
        if phase == 'verify':
            if self.task.kind != 'torch_verify':
                self._set_task(now, 'torch_verify', tr('校验 {name} 的 SHA-256', name=name), source=source, host=host)
            return
        if phase == 'done':
            self._set_task(now, 'packages', tr('安装依赖（{role} 环境）', role=self.role or 'main'), keep_source=False)
            return
        title = tr('下载 {name}（{index}/{count}）', name=name, index=index, count=count)
        if self.task.kind != 'torch' or self.task.title != title:
            self._set_task(now, 'torch', title, network=True)
        task = self.task
        if float(payload.get('downloaded') or 0) > task.done or not self._bytes:
            self._bytes_moved(now)
        task.done, task.total = float(payload.get('downloaded') or 0), float(payload.get('total') or 0)
        task.speed, task.speed_at = float(payload.get('speed') or 0), now
        task.source, task.host = source, host
        self._bytes.append((now, task.done))
        event = payload.get('event')
        if isinstance(event, dict) and event.get('kind') in {'switched', 'failed'}:
            key = f"{event.get('kind')}:{event.get('from')}:{event.get('to')}"
            if key != self._torch_event:
                self._torch_event = key
                self._event(wall, tr('{old} 太慢或未成功，已改用 {new} 并从断点继续',
                                     old=str(event.get('from') or ''), new=str(event.get('to') or '')), 'warn')

    def _file(self, payload: dict, now: float, wall: float) -> None:
        name = str(payload.get('file') or '').strip()
        if not name:
            return
        self._enter_step('weights', now)
        self._progress(now)
        if isinstance(payload.get('index'), int):
            # A retry or another source for the same file is not a fresh start: the
            # "no new data" clock keeps running (2026-10-22 real run: 0 KiB showed
            # 正常进行 again for 20 s after every retry).
            retry = self._file_key == (self.model_index, name) and self.task.kind == 'weights'
            started = self.task.started_at
            self._finish_file(now)
            self._file_key = (self.model_index, name)
            self._file_size, self._file_done = 0, 0
            title = tr('下载 {file}', file=name)
            self._set_task(now, 'weights', title, network=True, items_done=int(payload['index']),
                           items_total=int(payload.get('total') or 0), keep_source=True)
            if retry:
                self.task.started_at = started
        elif 'size' in payload:
            self._file_size = int(payload.get('size') or 0)
            if self.task.kind == 'weights':
                self.task.total = float(self._file_size)
            if self._file_size >= 64 << 20:
                self._event(wall, tr('开始下载 {file}（{size}）', file=name, size=size_text(self._file_size)))

    def _file_progress(self, payload: dict, now: float, wall: float) -> None:
        self._enter_step('weights', now)
        downloaded, total = float(payload.get('downloaded') or 0), float(payload.get('total') or 0)
        if payload.get('phase') == 'verify':
            if total:
                self._file_size = int(total)
            self._finish_file(now)
            return
        if self.task.kind != 'weights':
            self._set_task(now, 'weights', tr('下载 {model}', model=self.model_name or tr('模型文件')), network=True)
        task = self.task
        if downloaded > task.done or total != task.total:
            self._bytes_moved(now)
        task.done, task.total = downloaded, total or task.total
        task.speed, task.speed_at = float(payload.get('speed') or 0), now
        self._file_done = int(downloaded)
        if total:
            self._file_size = int(total)
        self._bytes.append((now, task.done))
        self._update_weights_fraction()

    def _finish_file(self, now: float) -> None:
        key = self._file_key
        if key is not None and key not in self._weights_counted and self._file_size:
            self._weights_counted[key] = self._file_size
        self._file_done = 0
        self._update_weights_fraction()

    def _cache(self, payload: dict, now: float, wall: float) -> None:
        name = str(payload.get('file') or '')
        self._enter_step('weights', now)
        self._progress(now)
        key = (self.model_index, name)
        if key not in self._weights_counted:
            self._weights_counted[key] = int(payload.get('bytes') or 0)
        reused = [size for (index, _name), size in self._weights_counted.items() if index == self.model_index]
        self._event(wall, tr('沿用已校验的文件 {count} 个（{size}），不重新下载', count=len(reused), size=size_text(sum(reused))),
                    'good', merge=f'cache:{self.model_index}')
        self._update_weights_fraction()

    def _update_weights_fraction(self) -> None:
        if not self.weights_total:
            return
        done = sum(self._weights_counted.values()) + self._file_done
        fraction = min(0.99, done / self.weights_total)
        self.step_fraction['weights'] = max(self.step_fraction.get('weights', 0.0), fraction)

    def weights_done(self) -> int:
        return int(sum(self._weights_counted.values()) + self._file_done)

    def _source(self, payload: dict, now: float, wall: float) -> None:
        label = str(payload.get('label') or payload.get('mode') or '')
        host = str(payload.get('host') or '')
        status = str(payload.get('status') or '')
        self._progress(now)
        if self.task.kind == 'weights':
            self.task.source, self.task.host = label, host
        if payload.get('url'):
            # Per-file attempts. "selected" = this file is downloaded and hashed; after
            # the last one the downloader checks the whole model without output.
            if status == 'selected':
                self._finish_file(now)
                task = self.task
                if task.kind == 'weights' and task.items_total and task.items_done >= task.items_total:
                    self._set_task(now, 'files_verify', tr('校验 {model} 的全部文件', model=self.model_name or tr('模型')),
                                   keep_source=True)
            return
        attempt, total = payload.get('attempt'), payload.get('total')
        if self.task.kind == 'weights' and attempt and total:
            self.task.attempt = f'{attempt}/{total}'
        if status in {'failed', 'unavailable'} and payload.get('mode'):
            self._weights_failed.add(str(payload['mode']).upper())
        if status == 'trying' and attempt and int(attempt) > 1:
            self._event(wall, tr('改试 {label}（第 {attempt}/{total} 个来源）', label=label, attempt=attempt, total=total), 'warn')
        elif status == 'failed':
            self._event(wall, tr('{label} 没有完成', label=label), 'warn')
        elif status == 'unavailable':
            self._event(wall, tr('{label} 没有这个文件', label=label), 'warn')

    def _tool_http(self, payload: dict, now: float, wall: float) -> None:
        self._progress(now)
        status = str(payload.get('http_status') or '')
        size = int(payload.get('downloaded') or 0)
        if status.startswith('2') and size:
            self._event(wall, tr('安装工具已下载（{size}）', size=size_text(size)), 'good')
            if self.task.kind == 'tool':
                self.task.done = max(self.task.done, size)

    def _human(self, line: str, now: float, wall: float) -> None:
        packages = self.packages
        if match := _UV_RESOLVED.match(line):
            packages.total = int(match.group(1))
            if self.task.kind == 'packages':
                self.task.items_total = packages.total
            return
        if match := _UV_AUDITED.match(line):
            self._event(wall, tr('依赖已齐全（{count} 个）', count=match.group(1)), 'good')
            return
        if match := _UV_DOWNLOADING.match(line):
            name, size = match.group(1), _parse_size(match.group(2))
            if name.startswith('cpython-'):
                version = name.split('-')[1] if '-' in name else ''
                self._set_task(now, 'python', tr('下载专用 Python {version}', version=version), total=size)
                return
            packages.announced[name] = size
            self._sync_packages()
            return
        if match := _UV_DOWNLOADED.match(line):
            name = match.group(1)
            if name.startswith('cpython-'):
                self._event(wall, tr('专用 Python 已下载'), 'good')
                if self.task.kind == 'python':
                    self.task.done = self.task.total
                return
            packages.downloaded.add(name)
            self._sync_packages()
            return
        if match := _UV_PREPARED.match(line):
            packages.prepared = True
            self._event(wall, tr('依赖下载完成（{count} 个）', count=match.group(1)), 'good')
            if self.task.kind == 'packages':
                self.task.title = tr('安装 {count} 个依赖（{role} 环境）', count=match.group(1), role=self.role or 'main')
            self._sync_packages()
            return
        if match := _UV_INSTALLED.match(line):
            self._event(wall, tr('已安装 {count} 个依赖', count=match.group(1)), 'good')
            packages.installed = int(match.group(1))
            return
        if _UV_ADDED.match(line) or _UV_BUILD.match(line):
            return
        if match := _UV_PYTHON_DONE.match(line):
            self._pythons.add(match.group(1))
            self._event(wall, tr('专用 Python {version} 已安装', version=match.group(1)), 'good')
            return
        if match := _UV_PYTHON_PRESENT.match(line):
            if match.group(1) not in self._pythons:
                self._pythons.add(match.group(1))
                self._event(wall, tr('专用 Python {version} 已就绪（沿用）', version=match.group(1)), 'good')
            return
        if match := _UV_CHECKED.match(line):
            self._event(wall, tr('依赖检查通过（{count} 个）', count=match.group(1)), 'good')
            return
        if match := _MODEL_COUNT.match(line):
            self.model_count = int(match.group(1))
            return
        if match := _MODEL_BYTES.match(line):
            self.weights_total = int(float(match.group(1)) * 2 ** 30)
            self._event(wall, tr('需要下载 {count} 个模型，约 {size}', count=self.model_count or '?',
                                 size=size_text(self.weights_total)))
            return
        if line.startswith('- 模型已全部就绪'):
            self._event(wall, tr('模型文件都已就绪，不需要下载'), 'good')
            return
        if match := _MODEL_START.match(line):
            self.model_index += 1
            self.model_name = match.group(1)
            self._weights_failed = set()
            self._enter_step('weights', now)
            count = max(self.model_count, self.model_index)
            self._set_task(now, 'weights', tr('下载 {model}', model=self.model_name), network=True)
            self._event(wall, tr('开始下载模型 {index}/{count}：{model}', index=self.model_index, count=count,
                                 model=self.model_name))
            return
        if match := _MODEL_SKIPPED.match(line):
            self._event(wall, tr('{model} 已就绪，跳过', model=match.group(1)), 'good')
            return
        if line.startswith('[运行库] 复用已验证环境'):
            self.step_note['runtime'] = 'reused'
            self._event(wall, tr('沿用已验证的运行环境'), 'good')
            return
        if line.startswith('[重试]') or '次中断（已有进展' in line or line.startswith('[恢复分片]'):
            self._event(wall, tr('网络中断，自动重试并从断点继续'), 'warn', merge='retry')
            return
        if line.startswith('[网络] 下载源：'):
            return
        if line.startswith('[工具] '):
            detail = line[5:].strip()
            if match := _TOOL_SOURCE.match(detail):
                self._tool_attempt = f'{match.group(1)}/{match.group(2)}'
                self._tool_source = match.group(3).strip()
                if self.task.kind == 'tool':
                    self.task.source, self.task.attempt = self._tool_source, self._tool_attempt
                    self.task.done = 0
                    self._bytes.clear()
                return
            if not _PATH.search(detail) and ('未成功' in detail or '已从' in detail):
                self._event(wall, detail, 'bad' if '未成功' in detail else 'good')
            return
        if line.startswith('[PyTorch] '):
            detail = line[10:].strip()
            if '下载完成' in detail:
                self._event(wall, detail, 'good')
            elif '试用' in detail:
                self._event(wall, detail, 'warn')
            return
        if line.startswith('[运行库] ') and (match := _PACKAGE_INDEX.match(line[6:].strip())):
            if self.task.kind == 'packages':
                self.task.source, self.task.attempt = match.group(1).strip(), f'{match.group(2)}/{match.group(3)}'
            return
        if line.startswith('[运行库] ') and '本次官方 PyTorch 来源不理想' in line:
            self._event(wall, line[6:].strip(), 'warn')

    def _sync_packages(self) -> None:
        if self.task.kind != 'packages':
            return
        packages = self.packages
        announced = sum(packages.announced.values())
        done = sum(size for name, size in packages.announced.items() if name in packages.downloaded)
        self.task.items_total = packages.total
        self.task.items_done = len(packages.downloaded)
        self.task.total = float(announced)
        self.task.done = float(announced if packages.prepared else done)

    # ------------------------------------------------------------------ probe
    def tick(self, now: float, sample: dict | None = None) -> None:
        """Once a second: record the process-tree sample and the graph value."""
        if sample is not None and not sample.get('warmup'):
            self._probe.append((now, float(sample.get('cpu') or 0), float(sample.get('io') or 0)))
        value, kind = 0.0, 'io'
        speed = self.current_rate(now)
        if self.task.network and speed is not None:
            value, kind = speed, 'net'
        elif sample is not None:
            value = float(sample.get('io') or 0)
        self._graph.append((now, value, kind))

    def activity(self, now: float, window: float = 30.0):
        """(cpu %, io bytes/s) averaged over the window, or None without samples."""
        recent = [(cpu, io) for t, cpu, io in self._probe if now - t <= window]
        if not recent:
            return None
        return sum(cpu for cpu, _io in recent) / len(recent), sum(io for _cpu, io in recent) / len(recent)

    def latest_activity(self):
        if not self._probe:
            return None
        _t, cpu, io = self._probe[-1]
        return cpu, io

    def current_rate(self, now: float):
        task = self.task
        if task.speed_at and now - task.speed_at <= 5 and task.speed > 0:
            return task.speed
        points = [(t, b) for t, b in self._bytes if now - t <= 30]
        if len(points) >= 2 and points[-1][0] > points[0][0]:
            # Between reported points, not up to now: uv's tool download reports
            # every ~15 s, and dividing by now made a steady 300 KB/s swing between
            # "速度较慢" and "正常进行" (2026-10-22 real run). A real stall is the
            # no-new-data check's job.
            return max(0.0, (points[-1][1] - points[0][1]) / (points[-1][0] - points[0][0]))
        if task.network and task.started_at and now - task.started_at > 10:
            return 0.0
        return None

    def graph(self):
        """Last GRAPH_SECONDS values and the kind of the newest one ('net' or 'io')."""
        values = [value for _t, value, _kind in self._graph]
        kind = self._graph[-1][2] if self._graph else 'io'
        return values, kind

    # --------------------------------------------------------------- outcome
    def mark_finished(self, outcome: str, now: float) -> None:
        self.finished = outcome
        if outcome == 'done':
            for step in STEPS:
                if self.step_state[step] != 'failed':
                    self.step_state[step] = 'done'
                    self.step_finished.setdefault(step, now)
                    self.step_started.setdefault(step, now)
            self.step_fraction['weights'] = 1.0
        elif outcome == 'failed':
            step = self.step or 'tools'
            self.step_state[step] = 'failed'
            self.step_finished[step] = now

    # ------------------------------------------------------------- display
    def step_rows(self, now: float):
        """[(key, label, state, note, fraction)] for the step track."""
        rows = []
        for step in STEPS:
            state = self.step_state[step]
            note = ''
            if state == 'done':
                if self.step_note.get(step) == 'reused':
                    note = tr('沿用')
                elif step in self.step_started and step in self.step_finished:
                    spent = self.step_finished[step] - self.step_started[step]
                    note = duration_text(spent) if spent >= 1 else tr('已就绪')
            elif state == 'active' and step in self.step_started:
                note = duration_text(now - self.step_started[step])
            elif state == 'failed':
                note = tr('未完成')
            fraction = 1.0 if state == 'done' else self.step_fraction.get(step) if state in {'active', 'failed'} else 0.0
            rows.append((step, step_label(step), state, note, fraction))
        return rows

    def step_position(self):
        """(1-based index of the current step, step count)."""
        if not self.step:
            return 1, len(STEPS)
        return STEPS.index(self.step) + 1, len(STEPS)

    def task_fraction(self):
        """Fraction of the current task when it is measured, else None (no fake progress)."""
        task = self.task
        if task.kind == 'mfa_packages' and task.items_total:
            return max(0.0, min(1.0, task.items_done / task.items_total))
        if task.total > 0 and task.kind in {'torch', 'weights', 'packages', 'tool', 'mfa_file'}:
            return max(0.0, min(1.0, task.done / task.total))
        return None

    def task_title(self) -> str:
        task = self.task
        if task.kind == 'weights' and self.model_name and self.model_count > 1:
            return tr('模型 {index}/{count} · {title}', index=self.model_index, count=self.model_count, title=task.title)
        return task.title or tr('正在准备…')

    def figures(self, now: float) -> str:
        """The numbers line of the current-task card."""
        task = self.task
        parts = []
        if task.kind == 'packages':
            packages = self.packages
            if not packages.total and not packages.announced and not packages.prepared:
                parts.append(tr('正在解析依赖版本…'))
            if packages.prepared:
                parts.append(tr('依赖已下载，正在解压安装'))
            elif packages.announced:
                parts.append(tr('已下载 {done}/{count} 个较大的依赖（{size} / {total}）',
                                done=len(packages.downloaded), count=len(packages.announced),
                                size=size_text(task.done), total=size_text(task.total)))
            if packages.total:
                parts.append(tr('共 {count} 个依赖', count=packages.total))
        elif task.kind == 'mfa_packages':
            parts.append(tr('已下载 {done}/{count} 个包（{size}，共约 {total}）', done=task.items_done,
                            count=task.items_total, size=size_text(task.done), total=size_text(task.total)))
            rate = self.current_rate(now)
            if rate:
                parts.append(rate_text(rate))
                if task.total > task.done:
                    parts.append(tr('剩余约 {time}', time=duration_text((task.total - task.done) / rate)))
        elif task.total > 0 and task.kind in {'torch', 'weights', 'tool', 'mfa_file'}:
            percent = int(task.done * 100 / task.total) if task.total else 0
            parts.append(f'{size_text(task.done)} / {size_text(task.total)}')
            parts.append(f'{min(percent, 100)}%')
        elif task.done > 0 and task.kind == 'tool':
            parts.append(tr('已下载 {size}', size=size_text(task.done)))
        elif task.kind == 'python' and task.total:
            parts.append(tr('大小 {size}', size=size_text(task.total)))
        if task.network:
            rate = self.current_rate(now)
            if rate is not None and (rate > 0 or task.done):
                parts.append(rate_text(rate))
            if rate and task.total > task.done:
                seconds = (task.total - task.done) / rate
                if seconds < 48 * 3600:
                    parts.append(tr('剩余约 {time}', time=duration_text(seconds)))
        if task.kind == 'weights' and task.items_total > 1:
            parts.append(tr('文件 {index}/{count}', index=task.items_done, count=task.items_total))
        return '  ·  '.join(str(part) for part in parts)

    def source_line(self) -> str:
        task = self.task
        if not task.source:
            return ''
        text = tr('来源：{label}', label=task.source)
        if task.host and task.host != task.source:
            text += f'（{task.host}）'
        if '/' in task.attempt and task.attempt != '1/1':
            text += '  ·  ' + tr('第 {attempt} 个来源', attempt=task.attempt)
        return text

    def weights_line(self) -> str:
        if not self.weights_total or self.step != 'weights':
            return ''
        done = min(self.weights_done(), self.weights_total)
        percent = 100 if done >= self.weights_total * 0.995 else int(done * 100 / self.weights_total)
        return tr('全部模型 {done} / {total}（{percent}%）', done=size_text(done), total=size_text(self.weights_total),
                  percent=percent)

    def activity_parts(self, now: float) -> list:
        """Live evidence beside the graph: last real progress and what the processes do."""
        age = now - self.last_progress_at
        parts = [tr('最后进展：{age}前', age=duration_text(age)) if age >= 1 else tr('最后进展：刚刚')]
        latest = self.latest_activity()
        if latest is not None:
            cpu, io = latest
            parts.append(tr('子程序 CPU {cpu}%', cpu=int(round(cpu))))
            parts.append(tr('磁盘读写 {rate}', rate=rate_text(io)))
        return parts

    def activity_line(self, now: float) -> str:
        return '  ·  '.join(str(part) for part in self.activity_parts(now))

    def events_tail(self, count: int = 5):
        return list(self.events)[-count:]

    # -------------------------------------------------------------- health
    def assess(self, now: float, *, running: bool, paused: bool = False, mode: str = 'AUTO',
               modelscope_ok: bool = True, failure: str = '') -> Assessment:
        """Is it moving, and if not: where, probably why, and what the user can do."""
        if self.finished == 'done':
            return Assessment('done', tr('已完成'))
        if self.finished == 'failed' or failure:
            where = self._where('failed')
            why = failure
            if self.last_error and self.last_error not in failure:
                why = (failure + '\n' if failure else '') + tr('子程序报错：{error}', error=self.last_error)
            return Assessment('failed', tr('未完成'), tr('没有完成：{step}', step=step_label(self.step or 'tools')),
                              where, why, self._failure_actions(mode, modelscope_ok, failure))
        if paused or self.finished == 'paused':
            return Assessment('paused', tr('已暂停'))
        if not running:
            return Assessment('idle', tr('未开始'))
        age = now - self.last_progress_at
        task = self.task
        where = self._where()
        if task.kind == 'lock':
            if age < 120:
                # Waiting or slow is not stuck: "当前：", not "卡在：" (2026-10-22 real run).
                return Assessment('waiting', tr('等待中'), tr('正在等待另一项环境准备'), self._where('busy'),
                                  tr('另一个下载窗口或程序正在准备同一个运行环境；它结束后这里会自动继续，最多等待 60 秒。'))
        activity = self.activity(now, 30)
        busy = activity is not None and (activity[0] >= IDLE_CPU_PERCENT or activity[1] >= IDLE_IO_RATE)
        switch = self.suggest_source(mode, modelscope_ok)
        actions = (*((f'switch:{switch}',) if switch else ()), 'export')
        if task.network and not self._finishing():
            age = now - max(self.last_bytes_at, task.started_at)
            if age >= NETWORK_QUIET_S:
                stalled = age >= NETWORK_STALL_S
                return Assessment('stalled' if stalled else 'quiet', tr('可能卡住') if stalled else tr('等待回应'),
                                  tr('已经 {age}没有收到新的数据', age=duration_text(age)), where,
                                  self._network_why(), actions)
            rate = self.current_rate(now)
            remaining = task.total - task.done if task.total else 0
            if (rate is not None and rate < SLOW_RATE and now - task.started_at >= 30
                    and (remaining > 32 << 20 or not task.total or remaining > rate * 180)):
                eta = tr('，按这个速度还要约 {time}', time=duration_text(remaining / rate)) if rate > 0 and remaining else ''
                if task.kind == 'mfa_file':
                    # install_mfa_runtime.PkusegDownload tries the other sources itself (2026-10-22); the
                    # partial file sits in mfa-install, which a restart with HF 镜像 keeps.
                    why = tr('{origin} 目前只有这个速度{eta}。程序会自动试用其他来源，明显更快就改用，并从已下载的地方继续；'
                             '也可以现在改用 HF 镜像继续（先用 GitHub 加速镜像），已下载的部分会保留。',
                             origin=task.source or tr('当前来源'), eta=eta)
                else:
                    why = tr('{origin} 目前只有这个速度{eta}。自动模式会自行改用更快的来源；也可以现在切换，已下载的部分会保留。',
                             origin=task.source or tr('当前来源'), eta=eta)
                return Assessment('slow', tr('速度较慢'), tr('下载速度很慢（{rate}）', rate=rate_text(rate)), self._where('busy'),
                                  why, actions)
            return Assessment('ok', tr('正常进行'))
        quiet_after = SILENT_QUIET_S if activity is not None else SILENT_QUIET_S * 2
        stall_after = SILENT_STALL_S if activity is not None else SILENT_STALL_S * 2
        if age < quiet_after:
            return Assessment('ok', tr('正常进行'))
        if busy:
            if age >= LONG_STEP_S:
                return Assessment('busy', tr('仍在工作'), tr('这一步已经 {age}没有新的输出，但子程序仍在工作', age=duration_text(age)),
                                  self._where('busy'), self._busy_why(), ('export',))
            return Assessment('busy', tr('仍在工作'))
        level = 'stalled' if age >= stall_after else 'quiet'
        return Assessment(level, tr('可能卡住') if level == 'stalled' else tr('等待回应'),
                          tr('已经 {age}没有进展，子程序也几乎没有活动', age=duration_text(age)), where,
                          self._silent_why(), actions if task.kind in _SWITCHABLE else ('export',))

    def _finishing(self) -> bool:
        """The last bytes of a file arrived: the downloader hashes it without output."""
        task = self.task
        if not task.total or task.done <= 0:
            return False
        return task.total - task.done <= max(task.total * 0.02, (task.speed or 0) * 3, 1 << 20)

    def _where(self, kind: str = 'stuck') -> str:
        step = step_label(self.step or 'tools')
        title = self.task.title
        label = {'failed': tr('停在：{step}', step=step), 'busy': tr('当前：{step}', step=step)}.get(kind) or tr('卡在：{step}', step=step)
        text = label + (f' · {title}' if title else '')
        source = self.source_line()
        return text + ('\n' + source if source else '')

    def _network_why(self) -> str:
        task = self.task
        region = host_region(task.host, task.source)
        source = task.source or tr('下载来源')
        if self.sources_exhausted():
            return tr('这个模型能用的下载来源都试过了，都没有连通（当前网络连不上 Hugging Face 与其镜像时很常见）。'
                      '请开启代理（例如代理工具的 TUN 模式），或设置 HTTPS_PROXY 后重启程序再试；已下载的部分会保留。')
        if region == 'foreign':
            return tr('{origin} 在当前网络下可能连不上或被限速：没有开代理，或代理没有接管这个程序时很常见。'
                      '自动模式会自行重试或改用其他来源；也可以现在改用国内来源，已下载的部分会保留。', origin=source)
        if region == 'domestic':
            return tr('{origin} 暂时没有响应，可能是网络中断或来源繁忙。程序会自动重试；也可以换一个来源继续，已下载的部分会保留。',
                      origin=source)
        return tr('下载来源暂时没有响应，可能是网络中断。程序会自动重试；已下载的部分会保留。')

    def _silent_why(self) -> str:
        kind = self.task.kind
        if kind in {'mfa', 'mfa_packages'}:
            return tr('MFA 运行环境正在从 {origin} 下载；某个来源没有回应时，每个请求最多等 60 秒就会换下一个来源。'
                      '一直这样时，改用国内来源（ModelScope 或 HF 镜像）通常能解决，已下载的包会保留。',
                      origin=self.task.source or tr('下载来源'))
        if kind == 'mfa_build':
            return tr('组装 MFA 运行环境时不联网，只解压和写入文件；磁盘几乎没有读写时，可能被安全软件拦截或磁盘很慢。')
        if kind in {'packages', 'python', 'tool'}:
            return tr('安装工具 uv 正在等待网络：连接 {origin} 可能没有回应。uv 每个请求最多等 30 秒后会重试或报错；'
                      '一直这样时，改用国内来源通常能解决。', origin=self.task.source or tr('依赖来源'))
        if kind in {'load', 'env_check'}:
            return tr('检查或加载卡住了：可能被安全软件拦截、磁盘响应很慢，或显卡驱动没有回应。'
                      '这一步有时间上限，到时会停止并说明原因；也可以导出诊断发给开发者。')
        if kind in {'files_verify', 'torch_verify'}:
            return tr('校验文件时磁盘几乎没有读写：可能是磁盘忙碌或被其他程序占用。')
        return tr('安装程序没有新的输出，也几乎没有活动。这一步有时间上限，到时会停止并说明原因。')

    def _busy_why(self) -> str:
        kind = self.task.kind
        if kind in {'mfa_build', 'mfa'}:
            return tr('MFA 运行环境要解压和写入几千个文件，可能需要几分钟。子程序仍在读写，请再等等。')
        if kind == 'load':
            return tr('首次加载大模型并用样本试跑可能需要几分钟（显卡、内存与磁盘速度都有影响）。子程序仍在读写或计算，请再等等。')
        if kind == 'packages':
            return tr('解压和安装大量依赖（PyTorch 等数 GB 文件）可能需要几分钟。子程序仍在读写，请再等等。')
        return tr('这一步不逐项报告进度，但子程序仍在读写或计算，请再等等。')

    def _failure_actions(self, mode: str, modelscope_ok: bool, failure: str = '') -> tuple:
        switch = self.suggest_source(mode, modelscope_ok)
        cause = f'{failure}\n{self.last_error}'.lower()
        if switch and failure and not any(word in cause for word in _NETWORK_FAILURE_WORDS):
            switch = ''  # not a network failure: another source would fail the same way
        return (*((f'switch:{switch}',) if switch else ()), 'export')

    def suggest_source(self, mode: str, modelscope_ok: bool = True) -> str:
        """Another download source worth trying for the current step, or ''."""
        mode = str(mode or 'AUTO').upper()
        step, task = self.step, self.task
        domestic = 'MODELSCOPE' if modelscope_ok else 'HF_MIRROR'
        if step in {'tools', 'runtime', ''}:
            # ModelScope / HF 镜像 also move uv, Python and packages to domestic mirrors.
            return domestic if mode in {'AUTO', 'HF_OFFICIAL'} else ''
        if step == 'weights':
            host = (task.host or '').lower()
            if 'modelscope' in host or mode == 'MODELSCOPE':
                current, order = 'MODELSCOPE', ('HF_MIRROR', 'HF_OFFICIAL')
            elif 'hf-mirror' in host or mode == 'HF_MIRROR':
                current, order = 'HF_MIRROR', ('MODELSCOPE', 'HF_OFFICIAL')
            elif 'huggingface' in host or mode == 'HF_OFFICIAL':
                current, order = 'HF_OFFICIAL', ('MODELSCOPE', 'HF_MIRROR')
            else:
                return ''
            # Never offer a source that already failed for this model, or the one in use
            # (2026-10-22: after HF and hf-mirror both failed it still offered HF 官方).
            for candidate in order:
                if candidate == 'MODELSCOPE' and not modelscope_ok:
                    continue
                if candidate not in self._weights_failed and candidate != current and candidate != mode:
                    return candidate
        return ''

    def sources_exhausted(self) -> bool:
        """Every source this model can come from has failed in this run."""
        return self.step == 'weights' and len(self._weights_failed) >= 2

    def background_summary(self, now: float, assessment: Assessment | None = None) -> str:
        """One line for the workshop page while the window is hidden."""
        index, count = self.step_position()
        text = tr('第 {index}/{count} 步 · {step}', index=index, count=count, step=step_label(self.step or 'tools'))
        fraction = self.task_fraction()
        if fraction is not None:
            text += f' · {int(fraction * 100)}%'
        if assessment is not None and assessment.level in {'quiet', 'stalled', 'slow'}:
            text += ' · ' + assessment.pill
        return text


class ProcessTreeProbe:
    """CPU and disk read/write of a process and all its descendants, per second.

    Per-process deltas, so a child that exits between samples does not make
    the totals jump backwards; a process seen for the first time contributes
    from the second sample on.
    """

    def __init__(self):
        self._last: dict[int, tuple[float, float, float]] = {}
        self._cores = 1

    def sample(self, pid: int, now: float) -> dict | None:
        if not pid:
            return None
        try:
            import psutil
            root = psutil.Process(int(pid))
            processes = [root, *root.children(recursive=True)]
            self._cores = psutil.cpu_count() or 1
        except Exception:
            self._last.clear()
            return None
        cpu_seconds = io_bytes = 0.0
        elapsed = []
        current = {}
        for process in processes:
            try:
                with process.oneshot():
                    times = process.cpu_times()
                    counters = process.io_counters()
                cpu = float(times.user + times.system)
                io = float(counters.read_bytes + counters.write_bytes)
            except Exception:
                continue
            current[process.pid] = (now, cpu, io)
            previous = self._last.get(process.pid)
            if previous is None:
                continue
            seconds = now - previous[0]
            if seconds <= 0:
                continue
            elapsed.append(seconds)
            cpu_seconds += max(0.0, cpu - previous[1])
            io_bytes += max(0.0, io - previous[2])
        self._last = current
        if not elapsed:
            return {'cpu': 0.0, 'io': 0.0, 'processes': len(current), 'warmup': True}
        seconds = max(elapsed)
        return {'cpu': cpu_seconds * 100.0 / seconds, 'io': io_bytes / seconds, 'processes': len(current)}
