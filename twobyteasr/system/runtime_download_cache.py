"""Maintain only the application's private uv cache through uv's own API.

Installed environments stay outside this cache. We share the bootstrap's OS
lock, check published environments offline, and never use uv's --force flag.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


def _linked(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) &
                                    getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))


def _safe(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.exists() and _linked(part):
            raise ValueError(f'目录为链接，不能维护其目标：{part}')
    return path


@contextmanager
def bootstrap_guard(managed: Path):
    """Nonblocking lock, interoperable with setup_managed_backend.ps1."""
    path = _safe(managed) / 'bootstrap.lock'
    if path.exists() and _linked(path):
        raise ValueError('运行库锁为链接，停止维护')
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise BlockingIOError('下载或安装正在使用运行库缓存；等待占用释放')
        try:
            yield
        finally:
            kernel.CloseHandle(handle)
    else:
        import fcntl
        with path.open('a+b') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BlockingIOError('下载或安装正在使用运行库缓存；等待占用释放') from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


@dataclass(frozen=True)
class RuntimeCacheResult:
    status: str
    detail: str
    logical_removed_bytes: int = 0
    disk_free_delta: int | None = None
    measurement_complete: bool = False


def runtime_cache_path(data_root: Path | None = None) -> Path:
    from ..runtime_paths import managed_runtime_root
    return managed_runtime_root(data_root) / 'download-cache'


def mark_runtime_cache_state(state: str, *, data_root: Path | None = None) -> None:
    """Called only after every requested runtime passed pip check/publication."""
    cache = runtime_cache_path(data_root)
    managed = _safe(cache.parent)
    from ..storage.atomic_files import write_text_atomic
    write_text_atomic(managed / 'download-cache-maintenance.json', json.dumps({
        'schema_version': 1, 'state': state, 'updated_at': time.time(),
        'health_checked_at': time.time() if state == 'ready' else None,
        'last_result': '等待下次空闲维护' if state == 'ready' else '安装中或可续传；按续传保留期限保护',
    }, ensure_ascii=False, indent=2))


def mark_runtime_cache_ready(*, data_root: Path | None = None) -> None:
    mark_runtime_cache_state('ready', data_root=data_root)


def _size(cache: Path, cancel) -> int:
    total = 0
    for directory, dirs, files in os.walk(cache, followlinks=False):
        if cancel():
            raise InterruptedError('维护已取消')
        for name in list(dirs):
            if _linked(Path(directory) / name):
                raise ValueError('缓存内部存在目录链接；交由人工检查')
        for name in files:
            path = Path(directory) / name
            if _linked(path):
                raise ValueError('缓存内部存在文件链接；交由人工检查')
            total += path.stat().st_size
    return total


def _run(argv, cancel, *, timeout=120):
    # No stdin prompts, inherited project configuration, or network requests.
    import tempfile
    with tempfile.TemporaryFile(mode='w+b') as output:
        process = subprocess.Popen([str(x) for x in argv], stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel() or time.monotonic() >= deadline:
                process.terminate()  # only this maintenance child, never a user task
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
                raise InterruptedError('维护已取消' if cancel() else '离线维护超时')
            time.sleep(.05)
        output.seek(0)
        detail = output.read(8192).decode('utf8', errors='replace')
        if process.returncode:
            raise RuntimeError(detail or f'uv退出码 {process.returncode}')
        return detail.strip()


def _healthy_runtimes(managed: Path, cache: Path, uv: Path, cancel, runner) -> None:
    registry = managed / 'registry.json'
    payload = json.loads(registry.read_text('utf-8-sig'))
    owned = []
    for record in (payload.get('runtimes') or {}).values():
        python = Path(record.get('python_executable') or '')
        if not python.is_absolute() or not python.resolve().is_relative_to(managed):
            continue  # explicitly registered external environments remain untouched
        environment = python.parent.parent
        receipt = environment / 'managed-runtime.json'
        if not python.is_file() or not receipt.is_file():
            raise ValueError(f'运行库尚未完成安装与健康登记：{environment}')
        _safe(environment)
        for directory, dirs, files in os.walk(environment, followlinks=False):
            if cancel(): raise InterruptedError('维护已取消')
            for name in (*dirs, *files):
                path = Path(directory) / name
                if _linked(path) and path.resolve().is_relative_to(cache):
                    raise ValueError(f'运行环境通过符号链接依赖缓存，不能清理：{path}')
                if path.is_file() and (path.suffix == '.pth' or name == 'pyvenv.cfg'):
                    with path.open(encoding='utf8', errors='replace') as stream:
                        text = stream.read(65536)
                    if str(cache).replace('\\','/').lower() in text.replace('\\','/').lower():
                        raise ValueError(f'运行环境配置仍引用下载缓存，不能清理：{path}')
                    if path.suffix == '.pth':
                        for line in text.splitlines():
                            if line.strip() and not line.startswith(('#','import ')) and (path.parent/line.strip()).resolve().is_relative_to(cache):
                                raise ValueError(f'运行环境路径文件仍引用下载缓存，不能清理：{path}')
            dirs[:] = [name for name in dirs if not _linked(Path(directory) / name)]
        runner([uv, '--no-config', '--offline', '--cache-dir', cache,
                'pip', 'check', '--python', python], cancel)
        owned.append(environment)
    if not owned:
        raise ValueError('没有已发布并通过健康检查的受管运行库，保留下载缓存')


def prune_runtime_download_cache(install_root: Path, *, data_root: Path | None = None,
                                 cancel=None, busy=lambda: False, runner=None, resume_days=14, mode='prune') -> RuntimeCacheResult:
    """Run offline uv cache prune --ci in the private cache after health checks.

    Call on a worker. cancel may be threading.Event or a callable; status is
    removed/skipped/failed/cancelled. A free-space delta includes other activity.
    """
    is_cancelled = cancel.is_set if hasattr(cancel, 'is_set') else (cancel or (lambda: False))
    if mode not in {'prune','clean'}:return RuntimeCacheResult('failed','未知的官方缓存维护操作')
    runner = runner or _run
    cache = runtime_cache_path(data_root)
    if not cache.exists():
        return RuntimeCacheResult('skipped', '应用专属运行库下载缓存不存在')
    if busy():
        return RuntimeCacheResult('skipped', '任务正在使用模型或运行库；等待空闲')
    try:
        cache = _safe(cache)
        managed = cache.parent
        with bootstrap_guard(managed):
            if busy(): raise BlockingIOError('模型任务仍在运行；等待占用释放')
            if is_cancelled(): raise InterruptedError('维护已取消')
            marker = managed / 'download-cache-maintenance.json'
            if marker.is_file():
                state = json.loads(marker.read_text('utf-8-sig'))
                if state.get('state') == 'installing':
                    # 2026-10-16 (user: runtimes 17 GB): we hold the install lock, so no
                    # installer runs. Pausing kills the installer tree before it can mark
                    # itself, which left "installing" for good; record it as interrupted
                    # and keep its time, so resume retention counts from the interruption.
                    state = {**state, 'state': 'paused', 'last_result': '安装已中断；按续传保留期限保护'}
                    from ..storage.atomic_files import write_text_atomic
                    write_text_atomic(marker, json.dumps(state, ensure_ascii=False, indent=2))
                if mode=='prune' and state.get('state') in {'installing', 'paused', 'failed'} and time.time() - float(state.get('updated_at', 0)) < max(1, int(resume_days)) * 86400:
                    return RuntimeCacheResult('skipped', f'未完成安装的可续传缓存保留{max(1, int(resume_days))}天；请完成或重试安装')
            lock = json.loads((Path(install_root) / 'dependencies.lock.json').read_text('utf-8-sig'))
            version = str(lock['managed_bootstrap']['uv_version'])
            uv = _safe(managed / 'tools' / ('uv-' + version)) / ('uv.exe' if os.name == 'nt' else 'uv')
            if not uv.is_file() or _linked(uv):
                raise ValueError('当前固定版本uv不可用，保留下载缓存')
            actual = runner([uv, '--version'], is_cancelled)
            if not actual.startswith('uv ' + version + ' '):
                raise ValueError('uv实际版本与应用清单不一致')
            _healthy_runtimes(managed, cache, uv, is_cancelled, runner)
            _safe(cache)  # recheck immediately before handing the path to uv
            try:before = _size(cache, is_cancelled)
            except OSError:
                if mode!='clean':raise
                before=None  # Unknown size is not zero and does not disable uv.
            free_before = shutil.disk_usage(managed).free
            detail = runner([uv, '--no-config', '--offline', '--cache-dir', cache,
                             'cache', *(['prune','--ci'] if mode=='prune' else ['clean'])], is_cancelled)
            health_error=''
            if mode=='clean':
                try:_healthy_runtimes(managed,cache,uv,is_cancelled,runner)
                except Exception as exc:health_error='官方清理已执行；清理后环境健康复核失败：'+str(exc)
            try:after = _size(cache, is_cancelled) if cache.exists() else 0
            except OSError:after=None
            delta = shutil.disk_usage(managed).free - free_before
            measured=before is not None and after is not None
            result = RuntimeCacheResult('removed' if mode=='prune' or not measured or before!=after else 'unchanged',
                detail or 'uv专属缓存维护完成', max(0,before-after) if measured else 0, delta, measured)
            if health_error:result=RuntimeCacheResult('failed',health_error,result.logical_removed_bytes,delta,measured)
            from ..storage.atomic_files import write_text_atomic
            write_text_atomic(managed / 'download-cache-maintenance.json', json.dumps({
                'schema_version': 1, 'state': 'maintained', 'last_cleaned_at': time.time(),
                'last_result': result.detail, 'logical_removed_bytes': result.logical_removed_bytes,
                'disk_free_delta': delta,
                'measurement_complete': measured,
                'status': result.status,
                'operation': mode,
            }, ensure_ascii=False, indent=2))
            return result
    except BlockingIOError as exc:
        return RuntimeCacheResult('skipped', str(exc))
    except InterruptedError as exc:
        return RuntimeCacheResult('cancelled', str(exc))
    except Exception as exc:
        return RuntimeCacheResult('failed', str(exc))


def clean_runtime_download_cache(install_root: Path, **kwargs) -> RuntimeCacheResult:
    """Explicit manual cache clean; ignores only auto retention, never OS locks."""
    return prune_runtime_download_cache(install_root,mode='clean',**kwargs)
