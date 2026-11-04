"""Create the Montreal Forced Aligner runtime: ``<runtime root>\\mfa`` (2026-10-19).

MFA needs Kaldi, OpenFst and pynini, which only conda-forge builds for
Windows, so this runtime is a conda environment instead of a uv venv:

1. micromamba (conda-forge package ``micromamba``, pinned version and
   SHA-256 in ``dependencies.lock.json`` ``environments.mfa``);
2. ``micromamba create`` from the pinned explicit list
   ``scripts/mfa_runtime_win64.txt`` (every package checked against its md5);
3. three small pure-Python packages MFA's Chinese tokenizer needs, from PyPI
   with ``--require-hashes`` (not on conda-forge), and the two pkuseg models it
   loads (``<env>\\share\\pkuseg``, SHA-256 pinned; GitHub, then GitHub proxies,
   resumable and moving to a clearly faster source when one stays slow);
4. a smoke test (``montreal_forced_aligner version`` and the tokenizers);
5. the completion marker ``conda-meta/2byteasr-mfa-runtime.json``.

Sources: conda.anaconda.org first, then the USTC and NJU mirrors (measured
2026-10-19: both serve identical files; TUNA/BFSU refused). With
``2BYTEASR_RUNTIME_SOURCE=mirror`` (a mainland download source chosen in the
download window) the mirrors come first. The env is created in place (conda
writes its own path into files; micromamba refuses an existing folder), with
the pending marker ``mfa.install-pending.json`` next to it until it is complete.

usage: python -I scripts/install_mfa_runtime.py [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

OFFICIAL = "https://conda.anaconda.org/conda-forge"
MIRRORS = ("https://mirrors.ustc.edu.cn/anaconda/cloud/conda-forge",
           "https://mirrors.nju.edu.cn/anaconda/cloud/conda-forge")
MARKER = "2byteasr-mfa-runtime.json"
PENDING = "mfa.install-pending.json"  # next to the env folder"


def say(text: str) -> None:
    print(text, flush=True)


def phase(name: str) -> None:
    say('[2BYTEASR_PHASE] ' + json.dumps({"phase": name}))


def spec() -> dict:
    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    return lock["environments"]["mfa"]


def channel_order() -> list[str]:
    if os.environ.get("2BYTEASR_RUNTIME_SOURCE", "") == "mirror":
        return [*MIRRORS, OFFICIAL]
    return [OFFICIAL, *MIRRORS]


def prefix() -> Path:
    from twobyteasr.recognition.mfa_aligner import runtime_prefix
    return runtime_prefix()


def _download(url: str, target: Path, sha256: str) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "2ByteASR"})
        with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
    except Exception as exc:
        say(f"[运行库] 下载失败，换下一个来源：{url}（{type(exc).__name__}: {exc}）")
        return False
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != sha256:
        say(f"[运行库] 校验不符，换下一个来源：{url}")
        return False
    return True


def micromamba(work: Path, pinned: dict) -> Path:
    """micromamba.exe from the pinned conda-forge package (checked by SHA-256)."""
    exe = work / "micromamba.exe"
    if exe.is_file():
        return exe
    archive = work / pinned["file"].split("/")[-1]
    for base in channel_order():
        url = f"{base}/{pinned['file']}"
        say(f"[运行库] 获取 micromamba {pinned['version']}：{url}")
        if _download(url, archive, pinned["sha256"]):
            with tarfile.open(archive, "r:bz2") as package:
                member = package.getmember("Library/bin/micromamba.exe")
                with package.extractfile(member) as source, exe.open("wb") as out:
                    shutil.copyfileobj(source, out)
            archive.unlink()
            return exe
    raise RuntimeError("无法下载 micromamba（官方源与国内镜像都失败）。请检查网络后重试。")


def explicit_packages() -> list[tuple[str, str]]:
    """``(path under the channel, md5)`` of every pinned package, e.g. ``("win-64/kaldi-….conda", "…")``."""
    out = []
    for line in (ROOT / spec()["explicit"]).read_text(encoding="utf-8").splitlines():
        if line.startswith(OFFICIAL + "/"):
            url, _sep, md5 = line.partition("#")
            out.append((url[len(OFFICIAL) + 1:], md5.strip()))
    return out


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _fetch_one(item: tuple[str, str], pkgs: Path) -> tuple[str, int, str]:
    """One package into the cache from the first source that serves it with the pinned md5."""
    relative, md5 = item
    target = pkgs / relative.split("/")[-1]
    if target.is_file() and _md5(target) == md5:
        return relative, target.stat().st_size, "cache"
    errors = []
    for base in channel_order():
        part = target.with_suffix(target.suffix + ".part")
        try:
            request = urllib.request.Request(f"{base}/{relative}", headers={"User-Agent": "2ByteASR"})
            with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:
                shutil.copyfileobj(response, out, 1 << 20)
            if _md5(part) == md5:
                os.replace(part, target)
                return relative, target.stat().st_size, base
            errors.append(f"{base}: md5")
        except Exception as exc:
            errors.append(f"{base}: {type(exc).__name__}")
        part.unlink(missing_ok=True)
    raise RuntimeError(f"{relative} 下载失败（{'；'.join(errors)}）")


def fetch_packages(work: Path) -> dict:
    """Every pinned package into micromamba's cache, each from the first source that has it.

    Per file, not per channel: a mirror that has not synced the newest
    packages yet (2026-10-19: NJU/USTC lacked a package published the day
    before) only costs those files a second source.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    pkgs = work / "root" / "pkgs"
    pkgs.mkdir(parents=True, exist_ok=True)
    items = explicit_packages()
    done, total_bytes, used = 0, 0, {}
    say(f"[运行库] 下载 MFA 运行环境的 {len(items)} 个包（约 340 MB）")
    reported = time.monotonic()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in as_completed([pool.submit(_fetch_one, item, pkgs) for item in items]):
            _relative, size, source = future.result()
            done += 1
            total_bytes += size
            used[source] = used.get(source, 0) + 1
            # The download window shows these as progress (2026-10-21): often
            # enough to see it move, with the source the last package came from.
            if done % 10 == 0 or done == len(items) or time.monotonic() - reported >= 2:
                reported = time.monotonic()
                host = urllib.parse.urlparse(source).hostname or "本机缓存"
                say(f"[运行库] MFA 运行环境：{done}/{len(items)} 个包，{total_bytes / 1048576:.0f} MB（来源：{host}）")
    return used


def mamba_env(work: Path) -> dict:
    env = dict(os.environ)
    env["MAMBA_ROOT_PREFIX"] = str(work / "root")
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("CONDA_PREFIX", None)
    return env


# The download script runs in the program folder, which in the packaged app holds PyInstaller's
# Python 3.10 .pyd files; `python -m` would put that folder first on sys.path and the env's 3.11
# loads the wrong _socket.pyd (2026-10-19). Every env python call: -I (3.11 adds no cwd) + a neutral cwd.
def create_env(exe: Path, work: Path, target: Path) -> dict:
    used = fetch_packages(work)
    say("[运行库] 正在组装 MFA 运行环境（不再联网）")
    result = subprocess.run([str(exe), "create", "-y", "--offline", "-p", str(target),
                             "--file", str(ROOT / spec()["explicit"])],
                            env=mamba_env(work), cwd=str(work), capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"MFA 运行环境组装失败：{(result.stderr or result.stdout or '')[-1200:]}")
    return used


def pip_install(target: Path, work: Path) -> None:
    from twobyteasr.download_sources import pip_index_urls
    lines = []
    for name, item in spec()["pip"].items():
        hashes = " ".join(f"--hash=sha256:{value}" for value in item["sha256"])
        lines.append(f"{name}=={item['version']} {hashes}")
    requirements = work / "mfa-pip.txt"
    requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")
    python = python_path(target)
    indexes = pip_index_urls()
    if os.environ.get("2BYTEASR_RUNTIME_SOURCE", "") == "mirror":
        indexes = indexes[1:] + indexes[:1]
    last = ""
    for index in indexes:
        result = subprocess.run([str(python), "-I", "-m", "pip", "install", "--no-deps", "--no-build-isolation",
                                 "--require-hashes", "--disable-pip-version-check", "--no-input", "--index-url", index,
                                 "-r", str(requirements)], env=activated(target), cwd=str(work), capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            return
        last = (result.stderr or result.stdout or "")[-800:]
        say(f"[运行库] PyPI 来源失败，换下一个：{index}")
    raise RuntimeError(f"MFA 中文分词依赖安装失败：{last}")


GITHUB_PROXIES = ("https://ghfast.top/", "https://ghproxy.net/", "https://gh-proxy.org/")  # as app/updater.py

# 2026-10-22 (mainland line): GitHub gave the pkuseg models 15-60 KB/s (postag about
# 45 minutes) while ghfast.top gave ~330 KB/s and gh-proxy.org ~470 KB/s at the same
# time, and the next source was only tried after a failure. As the PyTorch wheels
# (install_managed_backend.WheelDownload): a source that stays slow gets a short
# trial of the next one, and a clearly faster one goes on from the bytes already here.
SLOW_BYTES_PER_SECOND = 256 << 10
SPEED_GRACE_S = 20.0      # a source is judged once it has had this long,
SPEED_WINDOW_S = 30.0     # by its average over this window,
SPEED_CHECK_S = 20.0      # at most this often (doubled after a trial that was not faster),
WORTH_SWITCHING_S = 60.0  # and only while the rest would take longer than this
TRIAL_S = 8.0
SWITCH_FACTOR = 2.0
READ_TIMEOUT_S = 60
TRIAL_TIMEOUT_S = 15
READ_BLOCK = 256 << 10
PROGRESS_S = 2.0          # the download window shows these lines as speed and time left
MAX_RESUMES = 5           # reconnects to a source that broke off after sending bytes
CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+)", re.IGNORECASE)


def _mb(value: float) -> str:
    return f"{value / 1048576:.1f}"


def _rate(value: float) -> str:
    return f"{value / 1048576:.1f} MB/s" if value >= 1048576 else f"{value / 1024:.0f} KB/s"


def _size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


class SourceFailed(Exception):
    def __init__(self, reason: str, gained: bool = False):
        super().__init__(reason)
        self.gained = gained  # bytes arrived on this connection before it failed


class _Answer:
    """One open response and the file its bytes go to (from absolute offset ``start``)."""

    def __init__(self, index: int, response, start: int, path: Path, mode: str):
        self.index, self.response, self.start, self.position = index, response, start, start
        self.path, self.out = path, path.open(mode)

    def close(self) -> None:
        self.out.close()
        self.response.close()


class PkusegDownload:
    """One pinned pkuseg archive into ``<home>/<name>.zip``, checked against its SHA-256.

    The bytes collect in ``<work>/pkuseg-<name>-<sha>.zip.part``. The work folder
    outlives the env, so a restart with another download source (the window's
    "改用 HF 镜像继续") continues them; a verified archive is never replaced by
    anything unverified. Every request asks for the rest from the current offset.
    A source that ignores Range sends the whole file, into a ``.fresh`` file that
    replaces the partial only once it holds more. When the current source stays
    below SLOW_BYTES_PER_SECOND, the next untried source reads into a ``.trial``
    file for TRIAL_S while the current answer waits: SWITCH_FACTOR times faster
    takes over with those bytes, otherwise they go and the current answer goes
    on. Each source gets one trial per file, so slow sources never alternate.
    """

    def __init__(self, name: str, item: dict, home: Path, work: Path, prefixes, *,
                 opener=urllib.request.urlopen, clock=time.monotonic):
        self.label = f"中文分词模型 {name}"
        self.urls = [prefix + item["url"] for prefix in prefixes]
        self.hosts = [urllib.parse.urlsplit(url).netloc or url for url in self.urls]
        self.sha256 = item["sha256"]
        self.total = int(item.get("bytes") or 0)
        self.target = home / f"{name}.zip"
        self.partial = work / f"pkuseg-{name}-{self.sha256[:12]}.zip.part"
        self.fresh = self.partial.with_name(self.partial.name + ".fresh")
        self.trial = self.partial.with_name(self.partial.name + ".trial")
        self.opener, self.clock = opener, clock
        self.current = 0
        self.dead: set[int] = set()               # failed, or sent bytes that did not match
        self.measured: dict[int, float] = {}      # judged or tried: no further trial
        self.ranges: dict[int, bool] = {}
        self.resumes = [0] * len(self.urls)
        self.served: set[int] = set()             # whose bytes are in the partial file
        self.samples: deque = deque()             # (time, offset) on the current source
        self.check_gap = SPEED_CHECK_S
        self.next_check = self.reported = 0.0

    def fetch(self) -> None:
        self.partial.parent.mkdir(parents=True, exist_ok=True)
        try:
            while True:
                self._download()
                if hashlib.sha256(self.partial.read_bytes()).hexdigest() == self.sha256:
                    os.replace(self.partial, self.target)
                    return
                say(f"[运行库] 校验不符，换下一个来源：{self.urls[self.current]}")
                self.partial.unlink()
                # Which source sent the wrong bytes is unknown: none that sent some is used again.
                self.dead |= self.served
                self.served.clear()
                self.measured.clear()
        finally:
            self.trial.unlink(missing_ok=True)
            self.fresh.unlink(missing_ok=True)

    def _download(self) -> None:
        current = self._alive(self.current - 1)
        if current is None:
            raise RuntimeError(f"{self.label} 下载失败（GitHub 与镜像都失败）。请检查网络后重试。")
        self.current = current
        self._restart_clock()
        while True:
            have = _size(self.partial)
            if self.total and have >= self.total:
                if have == self.total:
                    return
                self.partial.unlink()  # longer than the file: never trusted
                continue
            try:
                self._pump(self._connect(self.current, have))
            except SourceFailed as failure:
                self._failed(failure)

    def _alive(self, after: int) -> int | None:
        """The first usable source after ``after`` (in order, wrapping round), or None."""
        for step in range(1, len(self.urls) + 1):
            index = (after + step) % len(self.urls)
            if index not in self.dead:
                return index
        return None

    def _candidate(self) -> int | None:
        """The next source after the current one that has not been judged or tried yet."""
        for step in range(1, len(self.urls)):
            index = (self.current + step) % len(self.urls)
            if index not in self.dead and index not in self.measured:
                return index
        return None

    def _connect(self, index: int, have: int, trial: bool = False) -> _Answer:
        request = urllib.request.Request(self.urls[index], headers={
            "User-Agent": "2ByteASR", "Range": f"bytes={have}-", "Accept-Encoding": "identity"})
        try:
            response = self.opener(request, timeout=TRIAL_TIMEOUT_S if trial else READ_TIMEOUT_S)
        except urllib.error.HTTPError as error:
            error.close()
            raise SourceFailed(f"HTTP {error.code}") from error
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise SourceFailed(str(getattr(error, "reason", None) or error) or type(error).__name__) from error
        status = getattr(response, "status", None) or response.getcode()
        match = CONTENT_RANGE.fullmatch(str(response.headers.get("Content-Range", "")).strip())
        length = str(response.headers.get("Content-Length", "")).strip()
        kind = str(response.headers.get("Content-Type", "")).split(";")[0].strip().lower()
        if status == 206 and match and int(match.group(1)) == have:
            start, total = have, int(match.group(3))
        elif status == 200:
            start, total = 0, int(length) if length.isdigit() else self.total
        else:
            response.close()
            raise SourceFailed(f"HTTP {status}，返回的范围不符")
        webpage = kind in ("text/html", "application/json")  # a proxy's error or notice page
        if webpage or not total or (self.total and total != self.total):
            response.close()
            raise SourceFailed("返回网页而不是文件" if webpage else "返回的不是这个文件")
        self.total = total
        if status == 206 or have:  # a 200 to "bytes=0-" does not tell
            self.ranges[index] = status == 206
        host = self.hosts[index]
        if trial:
            return _Answer(index, response, start, self.trial, "wb")
        if start == have:
            if have:
                say(f"[运行库] {self.label}：{host} 从 {_mb(have)} MB 处继续")
            return _Answer(index, response, start, self.partial, "ab")
        say(f"[运行库] {self.label}：{host} 不支持断点续传，从头下载（已下载的 {_mb(have)} MB 先保留）")
        return _Answer(index, response, start, self.fresh, "wb")

    def _block(self, answer: _Answer) -> bytes:
        try:
            block = answer.response.read1(READ_BLOCK)  # what has arrived, even a trickle
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise SourceFailed(str(error) or type(error).__name__, answer.position > answer.start) from error
        if not block:
            raise SourceFailed("连接提前结束", answer.position > answer.start)
        if answer.position + len(block) > self.total:
            raise SourceFailed("返回的数据比文件长")
        return block

    def _write(self, answer: _Answer, block: bytes) -> None:
        answer.out.write(block)
        answer.position += len(block)
        self._settle(answer)

    def _settle(self, answer: _Answer) -> None:
        if answer.path == self.partial:
            self.served.add(answer.index)
        elif answer.path == self.fresh and answer.position > _size(self.partial):
            # The whole-file answer has passed the bytes kept from before: it is the partial now.
            answer.out.close()
            os.replace(self.fresh, self.partial)
            self.served = {answer.index}
            answer.path, answer.out = self.partial, self.partial.open("ab")

    def _pump(self, answer: _Answer) -> None:
        """Read the current answer (or, after a switch, the faster source's) until the file is complete."""
        try:
            while answer.position < self.total:
                self._write(answer, self._block(answer))
                now = self.clock()
                if not self.samples or now - self.samples[-1][0] >= 0.5:
                    self.samples.append((now, answer.position))
                self._report(answer, now)
                if answer.position < self.total and self._too_slow(now, answer.position):
                    waiting = answer
                    answer = self._try_faster(answer)
                    if answer is not waiting:
                        self._report(answer, self.clock(), True)
        finally:
            answer.close()

    def _report(self, answer: _Answer, now: float, force: bool = False) -> None:
        if force or now - self.reported >= PROGRESS_S or answer.position == self.total:
            self.reported = now
            say(f"[运行库] {self.label}：{_mb(answer.position)}/{_mb(self.total)} MB（来源：{self.hosts[answer.index]}）")

    def _failed(self, failure: SourceFailed) -> None:
        index = self.current
        self.fresh.unlink(missing_ok=True)  # shorter than the partial, or it would have replaced it
        if failure.gained and self.ranges.get(index, True) and self.resumes[index] < MAX_RESUMES:
            self.resumes[index] += 1
            say(f"[运行库] {self.label}：{self.hosts[index]} 连接中断（{failure}），重新连接")
        else:
            self.dead.add(index)
            say(f"[运行库] 下载失败，换下一个来源：{self.urls[index]}（{failure}）")
            following = self._alive(index)
            if following is None:
                raise RuntimeError(f"{self.label} 下载失败（GitHub 与镜像都失败）。请检查网络后重试。")
            self.current = following
        self._restart_clock()

    def _restart_clock(self, wait: float | None = None) -> None:
        self.samples.clear()
        self.next_check = self.clock() + (SPEED_GRACE_S if wait is None else wait)

    def _speed(self, now: float) -> float:
        while self.samples and now - self.samples[0][0] > SPEED_WINDOW_S:
            self.samples.popleft()
        if len(self.samples) < 2 or self.samples[-1][0] - self.samples[0][0] < 1.0:
            return 0.0
        return (self.samples[-1][1] - self.samples[0][1]) / (self.samples[-1][0] - self.samples[0][0])

    def _too_slow(self, now: float, position: int) -> bool:
        if now < self.next_check or self._candidate() is None:
            return False
        self.next_check = now + self.check_gap
        rate = self._speed(now)
        if rate >= SLOW_BYTES_PER_SECOND:
            return False
        return not rate or (self.total - position) / rate > WORTH_SWITCHING_S

    def _try_faster(self, answer: _Answer) -> _Answer:
        """Try the next source while ``answer`` waits; return whichever goes on."""
        rate = self._speed(self.clock())
        self.measured[answer.index] = rate
        candidate = self._candidate()
        old, new = self.hosts[answer.index], self.hosts[candidate]
        say(f"[运行库] {self.label}：{old} 最近 {int(SPEED_WINDOW_S)} 秒平均 {_rate(rate)}，试用 {new}")
        answer.out.flush()
        trial = None
        try:
            trial = self._connect(candidate, _size(self.partial), trial=True)
            started = self.clock()
            while trial.position < self.total and self.clock() - started < TRIAL_S:
                self._write(trial, self._block(trial))
            trial_rate = (trial.position - trial.start) / max(self.clock() - started, 1e-3)
        except SourceFailed as failure:
            if trial:
                trial.close()
            self.trial.unlink(missing_ok=True)
            self.measured[candidate] = 0.0
            say(f"[运行库] {self.label}：{new} 没有成功（{failure}），继续使用 {old}")
            return self._stay(answer)
        self.measured[candidate] = trial_rate
        left_here = (self.total - answer.position) / max(rate, 1.0)
        left_there = (self.total - trial.position) / trial_rate if trial_rate else float("inf")
        if trial_rate < SWITCH_FACTOR * max(rate, 1.0) or left_there >= left_here:
            trial.close()
            self.trial.unlink()
            say(f"[运行库] {self.label}：{new} 试下 {_rate(trial_rate)}，不比 {old} 明显更快，继续使用 {old}")
            return self._stay(answer)
        answer.close()
        self.fresh.unlink(missing_ok=True)
        trial.out.close()
        if trial.start == _size(self.partial):
            with self.partial.open("ab") as out, self.trial.open("rb") as source:
                shutil.copyfileobj(source, out, 1 << 20)
            self.trial.unlink()
            trial.path = self.partial
            how = f"从 {_mb(trial.start)} MB 处继续"
        else:  # the whole file from a source that ignores Range: kept apart until it passes the partial
            os.replace(self.trial, self.fresh)
            trial.path = self.fresh
            how = f"从头下载（它不支持断点续传，已下载的 {_mb(_size(self.partial))} MB 先保留）"
        trial.out = trial.path.open("ab")
        self._settle(trial)
        say(f"[运行库] {self.label}：{old}（{_rate(rate)}）太慢，已改用 {new}（{_rate(trial_rate)}），{how}")
        self.current = candidate
        self.check_gap = SPEED_CHECK_S
        self._restart_clock()
        return trial

    def _stay(self, answer: _Answer) -> _Answer:
        self.check_gap *= 2
        self._restart_clock(max(SPEED_GRACE_S, self.check_gap))
        if self._candidate() is None:
            say(f"[运行库] {self.label}：其他来源都不比 {self.hosts[answer.index]} 明显更快，继续使用它")
        return answer


def install_pkuseg(target: Path, work: Path) -> None:
    """spacy_ontonotes (segmentation) and postag: pkuseg would fetch them from GitHub on first use."""
    import zipfile
    home = target / "share" / "pkuseg"
    home.mkdir(parents=True, exist_ok=True)
    for name, item in spec()["pkuseg"].items():
        archive = home / f"{name}.zip"
        if not (archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == item["sha256"]):
            say(f"[运行库] 下载中文分词模型 {name}（约 {item['bytes'] // 1048576} MB）")
            # The mirror source ("改用 HF 镜像继续") tries the GitHub proxies first, as channel_order() does.
            prefixes = (*GITHUB_PROXIES, "") if os.environ.get("2BYTEASR_RUNTIME_SOURCE", "") == "mirror" else ("", *GITHUB_PROXIES)
            PkusegDownload(name, item, home, work, prefixes).fetch()
        with zipfile.ZipFile(archive) as package:
            package.extractall(home / name)


def python_path(target: Path) -> Path:
    return target / ("python.exe" if os.name == "nt" else "bin/python")


def activated(target: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    from mfa_aligner_worker import activated_environment
    env = activated_environment(target)
    env["MFA_ROOT_DIR"] = str(Path(tempfile.gettempdir()) / "2byteasr-mfa-check")
    return env


def smoke(target: Path) -> str:
    env = activated(target)
    python = str(python_path(target))
    version = subprocess.run([python, "-I", "-m", "montreal_forced_aligner", "version"], env=env, cwd=str(target),
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    found = (version.stdout or "").strip().splitlines()[-1:] or [""]
    if version.returncode != 0 or found[0].strip() != spec()["packages"]["montreal-forced-aligner"]:
        raise RuntimeError(f"MFA 运行环境自检失败：{(version.stderr or version.stdout)[-800:]}")
    imports = subprocess.run([python, "-I", "-c", "import sudachipy, dragonmapper.hanzi, hanziconv, pynini, _kalpy, spacy_pkuseg; "
                              "assert spacy_pkuseg.pkuseg(postag=True).cut('今天天气很好')"],
                             env=env, cwd=str(target), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=300)
    if imports.returncode != 0:
        raise RuntimeError(f"MFA 分词组件自检失败：{imports.stderr[-800:]}")
    return found[0].strip()


def ready(target: Path) -> bool:
    return (python_path(target).is_file() and (target / "conda-meta" / MARKER).is_file()
            and not (target.parent / PENDING).exists())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only report whether the runtime is complete")
    args = parser.parse_args()
    target = prefix()
    if args.check:
        say(json.dumps({"ready": ready(target), "prefix": str(target)}, ensure_ascii=False))
        return 0 if ready(target) else 1
    if os.name != "nt":
        raise SystemExit("MFA 运行环境目前只为 Windows 准备。")
    if ready(target):
        say(f"[跳过] MFA 运行环境已就绪：{target}")
        return 0
    phase("runtime_installing")
    pending = target.parent / PENDING
    if target.exists():
        if not (pending.exists() or (target / "conda-meta").is_dir()):
            raise RuntimeError(f"{target} 已存在且不是 MFA 运行环境，未改动。")
        say(f"[运行库] 清理上次未完成的 MFA 运行环境：{target}")
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pinned = spec()
    pending.write_text(json.dumps({"started": time.time()}), encoding="utf-8")
    work = target.parent / "mfa-install"
    work.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    exe = micromamba(work, pinned["micromamba"])
    sources = create_env(exe, work, target)
    say("[运行库] 安装 MFA 中文分词依赖")
    pip_install(target, work)
    install_pkuseg(target, work)
    say("[运行库] 检查 MFA 运行环境能否运行（首次可能要一两分钟）")
    version = smoke(target)
    (target / "conda-meta" / MARKER).write_text(json.dumps({
        "montreal_forced_aligner": version, "explicit": pinned["explicit"],
        "explicit_sha256": hashlib.sha256((ROOT / pinned["explicit"]).read_bytes()).hexdigest(),
        "package_sources": sources, "micromamba": pinned["micromamba"]["version"],
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=1), encoding="utf-8")
    pending.unlink()
    shutil.rmtree(work / "root", ignore_errors=True)  # package cache: the env keeps its own copies
    say(f"[运行库] MFA 运行环境就绪：{target}（MFA {version}，{time.perf_counter() - started:.0f} 秒）")
    phase("runtime_ready")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        say(f"[错误] {exc}")
        raise SystemExit(1)
