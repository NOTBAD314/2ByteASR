"""Reviewable removal of superseded, inventoried application runtimes."""
from __future__ import annotations
import json
import csv
import hashlib
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .model_removal import RemovalPlan, RemovalResult, _inside, _lexical, _link, execute_removal


def write_runtime_inventory(runtime: Path) -> None:
    """Installer records exactly the files it created after successful health."""
    from ..storage.atomic_files import write_text_atomic
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
    from ..runtime_paths import managed_runtime_root
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
        rollback_root = None
        if current_root and _inside(current_root, managed):
            try:
                saved = json.loads((current_root/'managed-runtime.json').read_text('utf8'))
                previous = saved.get('previous_runtime')
                if previous:
                    candidate = _lexical(Path(previous)).parent.parent
                    if _inside(candidate, managed): rollback_root = candidate
            except (OSError, ValueError, TypeError):
                pass
        for runtime in parent.iterdir():
            if not runtime.is_dir() or _link(runtime) or not re.fullmatch(r'[0-9a-f]{16}(?:-[0-9a-f]{8})?', runtime.name): continue
            reason = process_error
            if runtime == current_root: reason = '当前角色已登记使用的共享运行环境'
            elif runtime == rollback_root: reason = '上一次已登记环境，保留用于回复'
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
    from ..runtime_paths import managed_runtime_root
    from ..system.runtime_download_cache import bootstrap_guard, _healthy_runtimes, _run
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


# ── MFA's conda runtime (2026-10-19, ADR 0133) ──────────────────────────────
# The experimental Montreal Forced Aligner runs in <runtime root>\mfa, a conda
# env that scripts/install_mfa_runtime.py creates from nothing (micromamba
# refuses an existing folder) next to its working folder mfa-install. It is
# not in registry.json and has no installed-files.json: the whole folder is
# the app's once it has conda-meta (the installer's own rule for cleaning up
# an unfinished env). Links inside are unlinked, never followed.

@dataclass(frozen=True)
class MfaRuntimePlan:
    root: Path                          # the env folder
    ready: bool                         # complete (mfa_aligner.runtime_python)
    files: int
    logical_bytes: int
    removals: tuple[RemovalPlan, ...]   # env folder, then mfa-install when present
    pending: Path | None = None         # mfa.install-pending.json beside the env
    protected_reason: str = ''

    @property
    def total_bytes(self) -> int:
        return sum(plan.logical_bytes for plan in self.removals) or self.logical_bytes


def _owned_tree(root: Path) -> tuple[RemovalPlan, int]:
    """Every file and link under ``root`` (conda-meta last), without following links; and the file count."""
    paths, markers, infos, logical, exclusive, files = [], [], {}, 0, 0, 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirs):
            if _link(base / name):
                dirs.remove(name)
                paths.append(base / name)
                infos[paths[-1]] = paths[-1].lstat()
        for name in names:
            path = base / name
            info = infos[path] = path.lstat()
            if not _link(path) and stat.S_ISREG(info.st_mode):
                files += 1
                logical += info.st_size
                if info.st_nlink == 1:
                    exclusive += info.st_size
            # conda-meta says "this folder is the MFA env": it goes last, so an
            # interrupted removal is still recognized and can be finished.
            (markers if base == root / 'conda-meta' else paths).append(path)
    ordered = tuple(paths + markers)
    identities = tuple((str(p), infos[p].st_dev, infos[p].st_ino, infos[p].st_size, infos[p].st_mtime_ns)
                       for p in ordered)
    return RemovalPlan('mfa_runtime', root, ordered, logical, exclusive, identities=identities), files


def plan_mfa_runtime_removal() -> MfaRuntimePlan | None:
    """What deleting MFA's runtime would remove, or None when nothing of it is on disk."""
    from ..recognition import mfa_aligner
    prefix = _lexical(mfa_aligner.runtime_prefix())
    parent = prefix.parent
    work = parent / mfa_aligner.INSTALL_DIR_NAME
    pending = parent / mfa_aligner.RUNTIME_PENDING
    if not (prefix.exists() or _link(prefix) or work.exists() or pending.exists()):
        return None
    reason = ''
    if os.environ.get(mfa_aligner.PREFIX_ENV, '').strip():
        reason = '位置由环境变量 TWOBYTEASR_MFA_PREFIX 指定，应用不删除。'
    elif any(_link(p) for p in (prefix, work, parent, *parent.parents)):
        reason = '运行环境位置经过目录链接，不能自动删除；请手动整理。'
    elif prefix.exists() and not ((prefix / 'conda-meta').is_dir() or pending.exists()):
        reason = '这个文件夹不是兔白字幕安装的 MFA 运行环境，未改动。'
    removals, files, logical = [], 0, 0
    if not reason:
        try:
            for folder in (prefix, work):
                if folder.is_dir():
                    removal, count = _owned_tree(folder)
                    removals.append(removal)
                    if folder == prefix:
                        files, logical = count, removal.logical_bytes
        except OSError as exc:
            reason, removals = f'统计运行环境文件失败：{exc}', []
    if reason and prefix.is_dir() and not _link(prefix):
        try:  # shown, not offered for deletion
            shown, files = _owned_tree(prefix)
            logical = shown.logical_bytes
        except OSError:
            pass
    return MfaRuntimePlan(prefix, bool(mfa_aligner.runtime_python(prefix)), files, logical, tuple(removals),
                          pending if pending.exists() else None, reason)


def _unlink_owned(path: Path) -> None:
    """Delete one planned file or link; a read-only file loses that flag first."""
    if _link(path):
        try:
            os.unlink(path)
        except (IsADirectoryError, PermissionError):
            os.rmdir(path)  # directory junction / symlink: removes the link, not the target
        return
    if getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_READONLY', 1):
        os.chmod(path, stat.S_IWRITE)
    os.unlink(path)


def _prune_empty_directories(root: Path) -> None:
    """Remove the folders the deletion emptied (and ones that were empty), deepest first."""
    if not root.is_dir() or _link(root):
        return
    for directory, dirs, _names in os.walk(root, topdown=False, followlinks=False):
        for name in dirs:
            path = Path(directory) / name
            if _link(path):
                continue
            try:
                path.rmdir()
            except OSError:
                try:
                    os.chmod(path, stat.S_IWRITE)
                    path.rmdir()
                except OSError:
                    pass
    try:
        root.rmdir()
    except OSError:
        pass


def remove_mfa_runtime(plan: MfaRuntimePlan, *, busy=lambda: False) -> RemovalResult:
    """Delete MFA's runtime: rescan, refuse while anything runs from it, then the files.

    The env is marked unfinished (the installer's pending marker) before the
    first file goes, so a deletion stopped halfway leaves a runtime the card
    offers to repair and the installer cleans up, never one that looks
    complete. The marker goes last, once both folders are gone.
    """
    from ..recognition import mfa_aligner
    if plan.protected_reason or not plan.removals:
        return RemovalResult(failures={str(plan.root): plan.protected_reason or '没有可删除的文件'})
    if busy():
        return RemovalResult(failures={str(plan.root): '模型任务正在运行；等待占用释放'})
    # Rescan: files written after the confirmation (Python caches of a later
    # MFA run) belong to the same env and must not keep its folder alive.
    current = plan_mfa_runtime_removal()
    if current is None or current.root != plan.root or current.protected_reason or not current.removals:
        return RemovalResult(failures={str(plan.root): (current.protected_reason if current else '') or
                                       '运行环境在确认后已改变；请重新扫描'})
    try:
        running = _running_paths()
    except ImportError:
        return RemovalResult(failures={str(plan.root): '无法检查运行进程；保留运行环境'})
    users = [path for path in running if any(_inside(path, removal.root) for removal in current.removals)]
    if users:
        return RemovalResult(failures={str(plan.root): '运行中的进程仍使用此环境：' + '、'.join(str(p) for p in users[:3])})
    pending = plan.root.parent / mfa_aligner.RUNTIME_PENDING
    from ..storage.atomic_files import write_text_atomic
    try:
        write_text_atomic(pending, json.dumps({'removing': time.time()}))
    except OSError as exc:
        return RemovalResult(failures={str(pending): str(exc)})
    result = RemovalResult()
    for removal in current.removals:
        part = execute_removal(removal, unlink=_unlink_owned, busy_check=busy)
        _prune_empty_directories(removal.root)
        result.removed.extend(part.removed)
        result.failures.update(part.failures)
        result.retained.extend(part.retained)
        result.logical_bytes += part.logical_bytes
        result.exclusive_bytes += part.exclusive_bytes
        if part.disk_free_delta is not None:
            result.disk_free_delta = (result.disk_free_delta or 0) + part.disk_free_delta
        if removal.root.exists() and not part.failures:
            result.failures[str(removal.root)] = '文件夹里有确认后新出现的文件，未全部删除；请重新扫描后再删'
        if result.failures:
            break
    if not result.failures:
        try:
            pending.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            result.failures[str(pending)] = str(exc)
    return result
