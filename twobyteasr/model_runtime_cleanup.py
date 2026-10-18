"""Reviewable removal of superseded, inventoried application runtimes."""
from __future__ import annotations
import json
import csv
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .model_removal import RemovalPlan, RemovalResult, _inside, _lexical, _link, execute_removal


def write_runtime_inventory(runtime: Path) -> None:
    """Installer records exactly the files it created after successful health."""
    from .theme_persistence import write_text_atomic
    paths = []
    for directory, dirs, files in os.walk(runtime, followlinks=False):
        dirs[:] = [name for name in dirs if not _link(Path(directory) / name)]
        paths.extend((Path(directory) / name).relative_to(runtime).as_posix()
                     for name in files if name != 'installed-files.json')
    write_text_atomic(runtime / 'installed-files.json', json.dumps({
        'schema_version': 1, 'owner': '2ByteASR.managed-runtime', 'files': sorted(paths)
    }, ensure_ascii=False, indent=2))


@dataclass(frozen=True)
class RuntimeRemovalPlan:
    role: str
    root: Path
    current_python: Path | None
    removal: RemovalPlan | None
    protected_reason: str = ''


def _registry(managed):
    return json.loads((managed / 'registry.json').read_text('utf-8-sig')).get('runtimes', {})


def _running_paths():
    import psutil
    paths = []
    for process in psutil.process_iter(['exe']):
        try:
            executable = process.info.get('exe')
            if executable: paths.append(_lexical(Path(executable)))
        except (psutil.AccessDenied, psutil.NoSuchProcess): continue
    return paths


def _legacy_runtime_files(runtime: Path, receipt: dict) -> list[str]:
    """Recover old ownership from immutable identity and wheel RECORD lists.

    Unknown files remain outside the plan. This permits useful cleanup of
    legacy app runtimes without granting ownership of an entire old tree.
    """
    fields = ('role','models','packages','python','torch','tag','schema')
    identity = {key: receipt[key] for key in fields}
    signature = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    if signature != runtime.name or identity['schema'] != 1:
        raise ValueError('旧环境的不可变身份与目录签名不匹配')
    owned = {'pyvenv.cfg','.gitignore','CACHEDIR.TAG','constraints.txt','installed.lock.txt','managed-runtime.json',
        'Scripts/python.exe','Scripts/pythonw.exe','Scripts/activate','Scripts/activate.bat','Scripts/activate.ps1',
        'Scripts/deactivate.bat','Lib/site-packages/_virtualenv.py','Lib/site-packages/_virtualenv.pth'}
    site = runtime/'Lib/site-packages'
    if site.is_dir() and not _link(site):
        for record in site.glob('*.dist-info/RECORD'):
            if _link(record) or any(_link(p) for p in record.parents): continue
            with record.open(encoding='utf8',newline='') as stream:
                for row in csv.reader(stream):
                    if not row: continue
                    name=row[0]
                    if Path(name).is_absolute(): raise ValueError('旧包RECORD包含绝对路径')
                    candidate=_lexical(site/name)
                    if not _inside(candidate,runtime): raise ValueError('旧包RECORD包含越界路径')
                    if any(_link(p) for p in candidate.parents): continue
                    owned.add(candidate.relative_to(runtime).as_posix())
    # CPython caches are generated from these authenticated package sources.
    for name in list(owned):
        source=runtime/name
        if source.suffix!='.py' or not source.is_file(): continue
        cache=source.parent/'__pycache__'
        if not cache.is_dir() or _link(cache): continue
        for path in cache.glob(source.stem+'.cpython-*.pyc'):
            if re.fullmatch(re.escape(source.stem)+r'\.cpython-\d+(?:\.opt-[12])?\.pyc',path.name) and not _link(path):
                owned.add(path.relative_to(runtime).as_posix())
    return sorted(owned)


def scan_unused_model_runtimes(*, data_root: Path | None = None) -> list[RuntimeRemovalPlan]:
    from .runtime_paths import managed_runtime_root
    managed = _lexical(managed_runtime_root(data_root))
    if not managed.is_dir() or any(_link(p) for p in (managed, *managed.parents)): return []
    registry = _registry(managed)
    try: running = _running_paths(); process_error = ''
    except ImportError: running = []; process_error = '无法检查运行进程；保留运行环境'
    found = []
    for role in ('main', 'moss', 'firered_llm', 'glm_asr', 'canary'):
        parent = managed / role
        if not parent.is_dir() or _link(parent): continue
        record = registry.get(role) or {}
        current = _lexical(Path(record['python_executable'])) if record.get('python_executable') else None
        current_root = current.parent.parent if current else None
        for runtime in parent.iterdir():
            if not runtime.is_dir() or _link(runtime) or not re.fullmatch(r'[0-9a-f]{16}', runtime.name): continue
            reason = process_error
            if runtime == current_root: reason = '当前角色已登记使用的共享运行环境'
            elif current is None or not current.is_file() or not _inside(current, managed):
                reason = '没有已登记的受管替代运行环境，可能仍承担离线识别'
            elif any(_inside(path, runtime) for path in running): reason = '运行中的进程仍使用此环境'
            receipt = runtime / 'managed-runtime.json'
            inventory = runtime / 'installed-files.json'
            try:
                payload = json.loads(receipt.read_text('utf-8-sig'))
                try: files = json.loads(inventory.read_text('utf-8-sig'))
                except FileNotFoundError:
                    files = {'owner':'2ByteASR.managed-runtime','files':_legacy_runtime_files(runtime,payload)}
                if payload.get('role') != role or files.get('owner') != '2ByteASR.managed-runtime':
                    raise ValueError('运行环境登记不匹配')
                paths = []
                for name in (*files['files'], 'installed-files.json'):
                    path = runtime / str(name)
                    if not _inside(path, runtime) or Path(name).is_absolute() or '..' in Path(name).parts:
                        raise ValueError('运行环境文件清单越界')
                    if any(_link(p) for p in path.parents): raise ValueError('运行环境清单经过目录链接')
                    if path.is_file() or _link(path): paths.append(path)
                known = set(paths); retained = []
                for directory, dirs, names in os.walk(runtime, followlinks=False):
                    retained.extend(Path(directory) / name for name in dirs if _link(Path(directory) / name))
                    dirs[:] = [name for name in dirs if not _link(Path(directory) / name)]
                    retained.extend(Path(directory) / name for name in names if Path(directory) / name not in known)
                logical = sum(p.lstat().st_size for p in paths if not _link(p))
                exclusive = sum(p.lstat().st_size for p in paths if not _link(p) and p.lstat().st_nlink == 1)
                identities = tuple((str(p), p.lstat().st_dev, p.lstat().st_ino, p.lstat().st_size, p.lstat().st_mtime_ns) for p in paths)
                removal = RemovalPlan(role, runtime, tuple(paths), logical, exclusive,
                                      tuple(retained), identities=identities)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                removal = None
                if not reason: reason = '旧运行环境缺少可信完整文件归属清单；请人工整理：' + str(exc)
            found.append(RuntimeRemovalPlan(role, runtime, current, removal, reason))
    return found


def remove_unused_model_runtime(plan: RuntimeRemovalPlan, *, install_root: Path,
                                data_root: Path | None = None, busy=lambda: False) -> RemovalResult:
    from .runtime_paths import managed_runtime_root
    from .runtime_download_cache import bootstrap_guard, _healthy_runtimes, _run
    managed = _lexical(managed_runtime_root(data_root))
    if plan.protected_reason or plan.removal is None:
        return RemovalResult(failures={str(plan.root): plan.protected_reason or '归属未确认'})
    if busy(): return RemovalResult(failures={str(plan.root): '模型任务正在运行；等待占用释放'})
    try:
        with bootstrap_guard(managed):
            current = next((p for p in scan_unused_model_runtimes(data_root=data_root) if p.root == plan.root), None)
            if current is None or current.protected_reason or current.current_python != plan.current_python:
                return RemovalResult(failures={str(plan.root): '依赖或占用在确认后已改变；请重新扫描'})
            contract = json.loads((install_root / 'dependencies.lock.json').read_text('utf-8-sig'))
            version = str(contract['managed_bootstrap']['uv_version'])
            uv = managed / 'tools' / ('uv-' + version) / ('uv.exe' if os.name == 'nt' else 'uv')
            if not uv.is_file() or _link(uv) or any(_link(p) for p in uv.parents):
                raise ValueError('固定uv工具不可用，不能验证替代运行环境')
            _healthy_runtimes(managed, managed / 'download-cache', uv, lambda: busy(), _run)
            return execute_removal(plan.removal, busy_check=busy)
    except Exception as exc: return RemovalResult(failures={str(plan.root): str(exc)})


def remove_superseded_runtimes(*, install_root: Path, data_root: Path | None = None,
                               busy=lambda: False, cancel=lambda: False) -> dict | None:
    """Automatic pass over what「清理不再使用的模型运行环境」would offer.

    2026-10-16 (user: runtimes 17 GB): an updated runtime left the old version
    (about 5 GB) until someone found that button. Only plans without a
    protection reason are removed, each through remove_unused_model_runtime
    (rescan, current runtimes healthy, files on the inventory only). Returns a
    receipt, or None when there was nothing but current runtimes.
    """
    import time
    plans = scan_unused_model_runtimes(data_root=data_root)
    current = {plan.current_python.parent.parent for plan in plans if plan.current_python}
    others = [plan for plan in plans if plan.root not in current]
    if not others:
        return None
    receipt = dict(time=time.time(), removed=[], kept=[], failures={}, retained=0,
                   logical_removed_bytes=0, cancelled=False)
    for plan in others:
        if cancel() or busy():
            receipt['cancelled'] = True
            break
        if plan.protected_reason or plan.removal is None:
            receipt['kept'].append(dict(path=str(plan.root)[:512], reason=(plan.protected_reason or '归属未确认')[:512]))
            continue
        result = remove_unused_model_runtime(plan, install_root=install_root, data_root=data_root, busy=busy)
        receipt['logical_removed_bytes'] += result.logical_bytes
        receipt['retained'] += len(result.retained)
        if result.removed:
            receipt['removed'].append(str(plan.root)[:512])
        receipt['failures'].update({path[:512]: reason[:512] for path, reason in result.failures.items()})
    return receipt
