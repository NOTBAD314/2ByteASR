"""Permanent removal of explicitly owned model files, with no recycle fallback.

The deployment lock is the ownership inventory. Shared runtimes and global
caches are never part of a model removal. Links are unlinked, never followed.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path


def _link(path: Path) -> bool:
    try:
        attrs = getattr(path.lstat(), 'st_file_attributes', 0)
        return path.is_symlink() or bool(attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))
    except FileNotFoundError:
        return False


def _lexical(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _inside(path: Path, root: Path) -> bool:
    try:
        _lexical(path).relative_to(_lexical(root))
        return _lexical(path) != _lexical(root)
    except ValueError:
        return False


@dataclass(frozen=True)
class RemovalPlan:
    model_key: str
    root: Path
    paths: tuple[Path, ...]
    logical_bytes: int
    exclusive_bytes: int
    retained: tuple[Path, ...] = ()
    manifest_path: Path | None = None
    mode: str = 'delete'
    external: bool = False
    association_file: Path | None = None
    identities: tuple[tuple[str, int, int, int, int], ...] = ()
    installed_bytes: int = 0
    ownership_lock: Path | None = None
    ownership_bytes: bytes | None = None
    transaction_lock: Path | None = None


@dataclass
class RemovalResult:
    removed: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    logical_bytes: int = 0
    exclusive_bytes: int = 0
    disk_free_delta: int | None = None
    retained: list[str] = field(default_factory=list)
    detached: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return not self.failures and not self.retained


def plan_model_removal(install_root: Path, model_key: str, *, model_root: Path | None = None,
                       allow_external_delete: bool = False) -> RemovalPlan:
    from .model_registry import scan_model_registry
    from ..runtime_paths import get_runtime_paths, model_folder_name
    install_root = _lexical(install_root)
    lock = json.loads((install_root / 'dependencies.lock.json').read_text('utf-8-sig'))
    specs = lock['models']
    spec = specs.get(model_key)
    if not isinstance(spec, dict):
        raise ValueError('模型未登记于当前管理清单，不能确定删除归属。')
    parent = _lexical(model_root or get_runtime_paths().model_root)
    logical = parent / model_folder_name(str(spec['path']))
    # Preserve lexical link identity: registry discovery deliberately resolves
    # paths for reads, which must not grant permission to delete a link target.
    if not logical.exists() and not _link(logical):
        legacy = install_root / str(spec['path'])
        record = scan_model_registry(install_root=install_root, model_root=parent).record(model_key)
        if legacy.exists() or _link(legacy):
            logical = legacy
        elif record and record.installation_path.exists():
            raise ValueError('模型位于旧发现目录；请先明确模型存储位置再删除，不能猜测归属。')
    if not (_inside(logical, parent) or _inside(logical, install_root / 'models')):
        raise ValueError('删除目标不在已登记的模型目录内。')
    logical = _lexical(logical)
    if any(_link(p) for p in logical.parents if p == parent or _inside(p,parent)):
        raise ValueError('模型管理目录的祖先为链接；请明确真实管理位置后删除，不能递归进入链接目标。')
    if _link(logical):
        return RemovalPlan(model_key, logical, (logical,), 0, 0, mode='unlink', external=True)
    runtime = get_runtime_paths()
    managed = (_inside(logical, install_root / 'models') or
               _inside(logical, runtime.user_data_root / 'Models') or
               _inside(logical, runtime.user_data_root / 'models'))
    if not managed:
        try:
            deployed = json.loads((parent / '.twobyteasr-models.json').read_text('utf-8-sig'))
            managed = model_key in (deployed.get('models') or {})
        except (OSError, ValueError, TypeError): pass
    external = not managed
    from .model_associations import association_path
    association_file = association_path()
    # Another model using this directory or one of its children owns a shared
    # dependency. Its paths cannot be included in this removal.
    shared = set()
    own_names = set(str(x) for x in spec.get('required_files', ())) | set(spec.get('sha256', {}))
    # Exact metadata filename produced by this app's repository publisher.
    if (logical / '.2byteasr-source.json').is_file():
        own_names.add('.2byteasr-source.json')
    for key, other in specs.items():
        if key != model_key and isinstance(other, dict) and model_folder_name(str(other.get('path', ''))) == logical.name:
            shared.update(str(x) for x in other.get('required_files', ()))
            shared.update(other.get('sha256', {}))
    owned, retained, total, exclusive = [], [], 0, 0
    for name in sorted(own_names):
        path = logical / name
        if not _inside(path, logical) or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('模型管理清单包含越界路径。')
        if any(_link(p) for p in path.parents if p != logical and _inside(p, logical)):
            retained.append(path)
            continue
        if name in shared:
            if path.exists() or _link(path): retained.append(path)
            continue
        if path.exists() or _link(path):
            owned.append(path)
            info = path.lstat()
            if not _link(path) and stat.S_ISREG(info.st_mode):
                total += info.st_size
                if info.st_nlink == 1: exclusive += info.st_size
    # Unknown user files remain visible in the result; .bin is only a weight
    # extension here and is handled exactly like any other locked filename.
    if logical.is_dir():
        for directory, dirs, files in os.walk(logical, followlinks=False):
            base = Path(directory)
            for name in list(dirs):
                if _link(base / name):
                    dirs.remove(name)
                    retained.append(base / name)
            for name in files:
                path = base / name
                if path not in owned and path not in retained:
                    retained.append(path)
    identities = tuple((str(p), p.lstat().st_dev, p.lstat().st_ino, p.lstat().st_size,
                        p.lstat().st_mtime_ns) for p in owned)
    retained = tuple(dict.fromkeys(retained))
    installed_bytes = total + sum(p.lstat().st_size for p in retained if p.is_file() and not _link(p))
    return RemovalPlan(model_key, logical, tuple(owned), total, exclusive, retained,
                       parent / '.twobyteasr-models.json',
                       'detach' if external and not allow_external_delete else 'delete',
                       external, association_file, identities, installed_bytes,
                       install_root / 'dependencies.lock.json',
                       (install_root / 'dependencies.lock.json').read_bytes(),
                       parent / '.downloads' / model_key / '.prepare.lock')


def execute_removal(plan: RemovalPlan, *, release=lambda: None, unlink=None,
                    busy_check=lambda: False) -> RemovalResult:
    if plan.transaction_lock:
        if any(_link(p) for p in (plan.transaction_lock, *plan.transaction_lock.parents)):
            return RemovalResult(failures={str(plan.root): '下载事务锁路径为链接，未删除'})
        from ..repository_download import preparation_lock
        try:
            with preparation_lock(plan.transaction_lock, timeout=0):
                return _execute_removal(plan, release=release, unlink=unlink, busy_check=busy_check)
        except (OSError, TimeoutError) as exc:
            return RemovalResult(failures={str(plan.root): '下载或安装正在使用模型；等待占用释放：' + str(exc)})
    return _execute_removal(plan, release=release, unlink=unlink, busy_check=busy_check)


def _execute_removal(plan: RemovalPlan, *, release, unlink, busy_check) -> RemovalResult:
    import shutil
    if plan.ownership_lock and plan.ownership_lock.read_bytes() != plan.ownership_bytes:
        return RemovalResult(failures={str(plan.root): '管理清单已改变；重新扫描并确认删除范围'})
    if busy_check():
        return RemovalResult(failures={str(plan.root): '模型正在推理、下载、安装或修复；等待占用释放'})
    if plan.mode == 'detach':
        from .model_associations import detach_model
        try:
            detach_model(plan.root, plan.model_key, record_path=plan.association_file)
            return RemovalResult(detached=[str(plan.root)], disk_free_delta=0)
        except (OSError, ValueError) as exc:
            return RemovalResult(failures={str(plan.root): str(exc)})
    release()  # caller rejects active tasks before releasing idle models
    result = RemovalResult(retained=[str(p) for p in plan.retained])
    try: free_before = shutil.disk_usage(plan.root.parent).free
    except OSError: free_before = None
    identities = {item[0]: item[1:] for item in plan.identities}
    for path in plan.paths:
        if path != plan.root and not _inside(path, plan.root):
            result.failures[str(path)] = '路径越界，未删除'
            continue
        try:
            if busy_check():
                raise BlockingIOError('模型任务重新开始；等待占用释放')
            if not path.exists() and not _link(path): continue
            # Recheck all ancestors immediately before mutation; a swapped
            # junction cannot expand a previously approved file inventory.
            if any(_link(p) for p in plan.root.parents):
                raise OSError('管理目录的祖先已变为链接，停止删除')
            if path != plan.root and (_link(plan.root) or any(_link(p) for p in path.parents if _inside(p, plan.root))):
                raise OSError('目录已变为链接，停止删除该文件')
            info = path.lstat()
            fingerprint = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if str(path) in identities and fingerprint != identities[str(path)]:
                raise OSError('文件在确认后已改变；重新扫描并确认后再删除')
            is_link = _link(path)
            if unlink:
                unlink(path)
            elif is_link and path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
            result.removed.append(str(path))
            if not is_link and stat.S_ISREG(info.st_mode):
                result.logical_bytes += info.st_size
                if info.st_nlink == 1: result.exclusive_bytes += info.st_size
        except OSError as exc:
            result.failures[str(path)] = str(exc)
    if plan.root.is_dir() and not _link(plan.root) and not any(_link(p) for p in plan.root.parents):
        directories={plan.root}
        for path in plan.paths:
            directories.update(p for p in path.parents if _inside(p,plan.root))
        for directory in sorted(directories,key=lambda p:len(p.parts),reverse=True):
            if _link(directory) or any(_link(p) for p in directory.parents):continue
            try: directory.rmdir()
            except OSError: pass
    if plan.manifest_path and not result.failures:
        try:
            if _link(plan.manifest_path) or any(_link(p) for p in plan.manifest_path.parents):
                raise OSError('模型登记路径为链接，未更新登记')
            payload = json.loads(plan.manifest_path.read_text('utf-8-sig'))
            payload.get('models', {}).pop(plan.model_key, None)
            from ..storage.atomic_files import write_text_atomic
            write_text_atomic(plan.manifest_path, json.dumps(payload, ensure_ascii=False, indent=2))
        except FileNotFoundError: pass
        except (OSError, ValueError, TypeError) as exc:
            result.failures[str(plan.manifest_path)] = str(exc)
    if free_before is not None:
        try: result.disk_free_delta = shutil.disk_usage(plan.root.parent).free - free_before
        except OSError: pass
    return result


def historical_model_removals(install_root: Path, *, model_root: Path | None = None) -> list[RemovalPlan]:
    """Only known model buckets in this app's former trash roots are eligible."""
    from ..runtime_paths import get_runtime_paths, model_folder_name
    install_root = _lexical(install_root)
    lock = json.loads((install_root / 'dependencies.lock.json').read_text('utf-8-sig'))
    specs = dict(lock['models'])
    # Retired model ownership is only for old residues, never a live registry.
    specs['nemotron'] = {'path': 'models/Nemotron-3-Diarization',
                         'required_files': ['config.json', 'processor_config.json', 'model.safetensors']}
    parent = _lexical(model_root or get_runtime_paths().model_root)
    plans = []
    runtime = get_runtime_paths()
    known_parent = (parent == install_root / 'models' or parent == runtime.user_data_root / 'Models' or
                    parent == runtime.user_data_root / 'models')
    if not known_parent:
        try:
            payload = json.loads((parent / '.twobyteasr-models.json').read_text('utf-8-sig'))
            known_parent = bool(payload.get('models'))
        except (OSError, ValueError, TypeError): pass
    trash_roots = [install_root / 'model_trash', install_root / '.bin']
    if known_parent: trash_roots.append(parent / '.bin')
    for trash in dict.fromkeys(trash_roots):
        if not trash.is_dir() or _link(trash) or any(_link(p) for p in trash.parents): continue
        for child in trash.iterdir():
            matched = next(((key, spec) for key, spec in specs.items()
                            if child.name == model_folder_name(str(spec['path'])) or
                            child.name.startswith(key + '-')), None)
            if matched is None: continue
            key, spec = matched
            if _link(child):
                plans.append(RemovalPlan(key, child, (child,), 0, 0)); continue
            owned, retained, total, exclusive = [], [], 0, 0
            names = set(spec.get('required_files', ())) | set(spec.get('sha256', {}))
            for directory, dirs, files in os.walk(child, followlinks=False):
                base = Path(directory)
                for name in list(dirs):
                    if _link(base / name): dirs.remove(name); retained.append(base / name)
                for name in files:
                    path = base / name
                    if path.relative_to(child).as_posix() not in names:
                        retained.append(path); continue
                    owned.append(path)
                    info = path.lstat()
                    if not _link(path):
                        total += info.st_size
                        if info.st_nlink == 1: exclusive += info.st_size
            plans.append(RemovalPlan(key, child, tuple(owned), total, exclusive, tuple(retained)))
    return plans
