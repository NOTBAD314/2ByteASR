"""Move runtimes and models to a folder the user picks (2026-10-17, ADR 0129).

Users with a small C: drive asked to move what the app downloads. A virtual
environment is not "copy it and it works": ``pyvenv.cfg`` names its base
Python by absolute path, uv links each minor-version Python folder to the
full version with a junction, and ``registry.json`` records every
interpreter. One move:

1. plans: sizes (a hard-linked file counted once), free space, file system,
   containment and long-path checks, nothing running from the runtimes;
2. moves: renames on the same volume, otherwise copies file by file, keeping
   hard links and internal junctions; cancellable until step 5;
3. rewrites absolute paths in the new copy (the old copy is never edited
   while a copy is made; a rename records each original for undo);
4. checks each moved interpreter starts from the new folder and, where the
   environment probe passed before the move, that it still passes;
5. registers the new folder, then deletes the old copy.

A failure before step 5 removes what was created at the target and leaves
the old copy and the configuration as they were. Runtimes and models are
committed separately, so one can succeed while the other is rolled back.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

GiB = 1024 ** 3
RESERVE_BYTES = GiB  # left free on the target drive
RUNTIMES = 'runtimes'
MODELS = 'models'
MODEL_MANIFEST = '.twobyteasr-models.json'
MODEL_STAGING = '.downloads'
MFA_RUNTIME = 'mfa'  # check key of MFA's conda env (no registry.json entry)
_CHUNK = 8 * 1024 * 1024
_REPARSE = 0x400
_READONLY = 0x1
_TAG_JUNCTION = 0xA0000003
_TAG_SYMLINK = 0xA000000C
_GUARD_FILE = 'bootstrap.lock'   # held by our own guard; recreated empty at the target
_TEXT_SUFFIXES = {'', '.bat', '.ps1', '.sh', '.fish', '.csh', '.nu', '.py', '.cfg', '.pth', '.txt'}
_RUNNING = threading.Event()
# Progress texts: a part is cancellable while moving, not once it is registered.
MOVING_PHASES = ('正在复制', '正在移动', '检查移动前')
COMMITTED_PHASES = ('正在登记', '正在删除')


class RelocationError(Exception):
    """A step failed; the message is shown to the user."""


class RelocationCancelled(Exception):
    pass


def relocation_running() -> bool:
    """True while a move holds models/runtimes (storage maintenance and downloads wait)."""
    return _RUNNING.is_set()


# ----------------------------------------------------------------- file helpers

def _ext(path) -> str:
    """Extended-length form, so deep site-packages paths survive a longer target."""
    text = os.path.abspath(str(path))
    if os.name != 'nt' or text.startswith('\\\\?\\'):
        return text
    if text.startswith('\\\\'):
        return '\\\\?\\UNC\\' + text[2:]
    return '\\\\?\\' + text


def _plain(text: str) -> str:
    if text.startswith('\\\\?\\UNC\\'):
        return '\\\\' + text[8:]
    if text.startswith('\\\\?\\') or text.startswith('\\??\\'):
        return text[4:]
    return text


def _lstat(path):
    return os.lstat(_ext(path))


def _is_reparse(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & _REPARSE)


def _link_kind(info) -> str:
    """'junction', 'symlink', '' (a plain file/dir, including dedup/cloud files)."""
    tag = getattr(info, 'st_reparse_tag', 0)
    if tag == _TAG_JUNCTION:
        return 'junction'
    if tag == _TAG_SYMLINK or stat.S_ISLNK(info.st_mode):
        return 'symlink'
    return ''


def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _inside(path, root) -> bool:
    """Lexically ``path`` is ``root`` or below it."""
    path, root = _key(path), _key(root)
    return path == root or path.startswith(root.rstrip('\\/') + os.sep)


def _swap_root(value: str, old: Path, new: Path) -> str:
    if not value or not _inside(value, old):
        return value
    rest = os.path.abspath(value)[len(os.path.abspath(str(old))):].lstrip('\\/')
    return str(Path(new) / rest) if rest else str(new)


def _check(cancel):
    if cancel is not None and cancel():
        raise RelocationCancelled()


def _write_atomic(path: Path, data: bytes) -> None:
    """New file then replace: never edits a file another hard link shares."""
    temporary = Path(str(path) + '.relocate-tmp')
    with open(_ext(temporary), 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(_ext(temporary), _ext(path))


def _junction_target(path) -> str:
    return _plain(os.readlink(_ext(path)))


def _make_junction(target, link) -> None:
    import _winapi
    _winapi.CreateJunction(str(target), _plain(_ext(link)))


def _set_attributes(path, attributes: int) -> None:
    if os.name != 'nt':
        return
    import ctypes
    keep = attributes & (0x1 | 0x2 | 0x4 | 0x20 | 0x2000)  # readonly hidden system archive not-indexed
    if keep and not ctypes.windll.kernel32.SetFileAttributesW(_ext(path), keep):
        raise OSError(ctypes.GetLastError(), '无法设置文件属性', str(path))


def _remove_file(path) -> None:
    info = _lstat(path)
    if getattr(info, 'st_file_attributes', 0) & _READONLY:
        os.chmod(_ext(path), stat.S_IWRITE)
    os.unlink(_ext(path))


def _remove_tree(path, failures: list[str], *, root) -> None:
    """Delete ``path`` without following links; only ever inside ``root``."""
    if not _inside(path, root):
        raise RelocationError(f'拒绝删除旧位置以外的路径：{path}')
    try:
        info = _lstat(path)
    except FileNotFoundError:
        return
    if _is_reparse(info) and _link_kind(info):
        # A link is removed as a link; its target is never visited.
        directory = stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x10
        for attempt in range(3):
            try:
                (os.rmdir if directory else os.unlink)(_ext(path))
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                if attempt == 2:
                    failures.append(f'{path}：{exc}')
                time.sleep(.3)
        return
    if stat.S_ISDIR(info.st_mode):
        try:
            with os.scandir(_ext(path)) as entries:
                names = [entry.name for entry in entries]
        except OSError as exc:
            failures.append(f'{path}：{exc}')
            return
        for name in names:
            _remove_tree(Path(path) / name, failures, root=root)
        for attempt in range(3):
            try:
                os.rmdir(_ext(path))
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                if attempt == 2:
                    failures.append(f'{path}：{exc}')
                time.sleep(.3)
        return
    for attempt in range(3):
        try:
            _remove_file(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            if attempt == 2:
                failures.append(f'{path}：{exc}')
            time.sleep(.3)


# ------------------------------------------------------------------ inventory

@dataclass
class _Inventory:
    files: int = 0
    unique_bytes: int = 0
    logical_bytes: int = 0
    longest: int = 0  # characters below the part root


def _inventory(root: Path, entries, cancel=None) -> _Inventory:
    seen: set = set()
    result = _Inventory()
    base = len(os.path.abspath(str(root)))
    stack = [Path(root) / name for name in entries]
    while stack:
        _check(cancel)
        path = stack.pop()
        result.longest = max(result.longest, len(os.path.abspath(str(path))) - base)
        info = _lstat(path)
        if _is_reparse(info) and _link_kind(info):
            continue
        if stat.S_ISDIR(info.st_mode):
            if _is_reparse(info):
                raise RelocationError(f'无法识别的特殊文件夹（可能是云盘占位），请手动处理：{path}')
            with os.scandir(_ext(path)) as children:
                stack.extend(Path(path) / child.name for child in children)
            continue
        result.files += 1
        result.logical_bytes += info.st_size
        key = (info.st_dev, info.st_ino) if info.st_ino else ('path', _key(path))
        if key not in seen:
            seen.add(key)
            result.unique_bytes += info.st_size
    return result


def _existing_ancestor(path: Path) -> Path:
    path = Path(os.path.abspath(str(path)))
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _linked_ancestor(path: Path) -> Path | None:
    """First existing component of ``path`` that is a junction or symbolic link."""
    path = Path(os.path.abspath(str(path)))
    for part in (path, *path.parents):
        try:
            if _is_reparse(os.lstat(part)):
                return part
        except FileNotFoundError:
            continue
        except OSError:
            return part
    return None


def _volume_info(path: Path) -> tuple[str, int]:
    """(file system name, drive type) of the volume holding ``path``."""
    if os.name != 'nt':
        return 'posix', 3
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    volume = ctypes.create_unicode_buffer(1024)
    if not kernel.GetVolumePathNameW(str(_existing_ancestor(path)), volume, 1024):
        return '', 0
    name = ctypes.create_unicode_buffer(64)
    serial, length, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    if not kernel.GetVolumeInformationW(volume.value, None, 0, ctypes.byref(serial), ctypes.byref(length),
                                        ctypes.byref(flags), name, 64):
        return '', kernel.GetDriveTypeW(volume.value)
    return name.value, kernel.GetDriveTypeW(volume.value)


def _same_volume(first: Path, second: Path) -> bool:
    return os.stat(_existing_ancestor(first)).st_dev == os.stat(_existing_ancestor(second)).st_dev


def _free_bytes(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _long_paths_enabled() -> bool:
    if os.name != 'nt':
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:
            return int(winreg.QueryValueEx(key, 'LongPathsEnabled')[0]) == 1
    except OSError:
        return False


def _processes_inside(root: Path) -> list[str]:
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for process in psutil.process_iter(['exe', 'pid', 'name']):
        try:
            executable = process.info.get('exe')
            if executable and _inside(executable, root):
                found.append(f"{process.info.get('name') or Path(executable).name}（进程 {process.info.get('pid')}）")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return found


_RENAME_WAIT_S = 15.0


def _wait_until_unused(root: Path, cancel) -> None:
    """Let probe interpreters that just ran from ``root`` finish exiting."""
    deadline = time.monotonic() + _RENAME_WAIT_S
    while _processes_inside(root) and time.monotonic() < deadline:
        _check(cancel)
        time.sleep(.25)


def _rename(source: Path, target: Path, cancel) -> None:
    """Rename a folder on one volume, retrying while something still has a file in it open.

    Windows refuses to rename a folder while any file inside is open; right
    after a check ran its interpreter, or while a virus scanner reads freshly
    written files, that lasts a few seconds (seen 2026-10-17 on H:).
    """
    delay, deadline = .25, time.monotonic() + _RENAME_WAIT_S
    while True:
        try:
            os.rename(_ext(source), _ext(target))
            return
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise RelocationError(f'{source} 里有文件正被其他程序使用（例如杀毒软件正在扫描，或刚结束的程序还没退出），'
                                      '无法改名。请稍等一会儿再试。') from exc
        except OSError as exc:
            raise RelocationError(f'{source} 无法移动：{exc.strerror or exc}') from exc
        _check(cancel)
        time.sleep(delay)
        delay = min(delay * 2, 2.0)


def _model_preparation_running(staging: Path) -> bool:
    """A model download holds its ``.prepare.lock``; try each without waiting."""
    if not staging.is_dir():
        return False
    from ..repository_download import preparation_lock
    for lock in staging.glob('*/.prepare.lock'):
        try:
            with preparation_lock(lock, timeout=0):
                pass
        except (TimeoutError, OSError):
            return True
    return False


def format_size(value: int) -> str:
    if value >= GiB:
        return f'{value / GiB:.1f} GB'
    return f'{value / 1024 ** 2:.0f} MB'


# ----------------------------------------------------------------------- plan

@dataclass
class RelocationPart:
    kind: str                       # RUNTIMES | MODELS
    source: Path
    target: Path
    entries: tuple[str, ...] = ()   # names under ``source`` that move
    files: int = 0
    unique_bytes: int = 0
    longest: int = 0
    same_volume: bool = False
    left_behind: tuple[str, ...] = ()
    runtimes: tuple[tuple[str, str], ...] = ()  # (registry key, python) inside source

    @property
    def empty(self) -> bool:
        return not self.entries


@dataclass
class RelocationPlan:
    destination: Path
    parts: list[RelocationPart] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    free_bytes: int | None = None
    required_bytes: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.parts)


def _model_entries(model_root: Path, install_root: Path) -> tuple[list[str], list[str]]:
    """App-owned names in the model root, and everything else (which stays)."""
    from ..runtime_paths import _load_lock_models, model_folder_name
    owned = {model_folder_name(str(spec.get('path') or '')).casefold()
             for spec in _load_lock_models(install_root).values() if isinstance(spec, dict)}
    owned.update({MODEL_MANIFEST.casefold(), MODEL_STAGING.casefold()})
    ours, others = [], []
    try:
        names = sorted(entry.name for entry in os.scandir(_ext(model_root)))
    except FileNotFoundError:
        return [], []
    for name in names:
        (ours if name.casefold() in owned else others).append(name)
    return ours, others


def _registered_runtimes(runtime_root: Path) -> list[tuple[str, str]]:
    try:
        payload = json.loads((runtime_root / 'registry.json').read_text('utf-8-sig'))
    except (OSError, ValueError):
        payload = {}
    found = []
    for key, record in (payload.get('runtimes') or {}).items():
        python = str((record or {}).get('python_executable') or '') if isinstance(record, dict) else ''
        if python and _inside(python, runtime_root):
            found.append((str(key), python))
    # MFA's conda env (2026-10-19, ADR 0133) is not in registry.json but moves
    # with the folder: check it before and after like the others.
    from ..recognition.mfa_aligner import RUNTIME_DIR_NAME, runtime_python
    python = runtime_python(runtime_root / RUNTIME_DIR_NAME)
    if python:
        found.append((MFA_RUNTIME, python))
    return found


def plan_relocation(destination, *, paths=None, kinds=(RUNTIMES, MODELS), busy=None, cancel=None) -> RelocationPlan:
    """What a move to ``destination`` would do, and every reason it cannot start."""
    from ..runtime_paths import RUNTIME_ROOT_ENV, get_runtime_paths
    text = str(destination or '').strip()
    plan = RelocationPlan(Path(os.path.abspath(text)) if text else Path())
    if os.name != 'nt':
        plan.problems.append('只能在 Windows 上移动模型和运行环境。')
        return plan
    if not text or not Path(text).is_absolute():
        plan.problems.append('请选择一个完整路径的文件夹。')
        return plan
    destination = plan.destination
    if not destination.is_dir():
        plan.problems.append(f'文件夹不存在：{destination}')
        return plan
    if busy is not None and busy():
        plan.problems.append('请等识别、模型下载、安装、修复或导出结束后再移动。')
    paths = paths or get_runtime_paths()
    linked = _linked_ancestor(destination)
    if linked is not None:
        plan.problems.append(f'目标位置经过链接（junction 或符号链接）：{linked}。请直接选择真实的文件夹。')
    file_system, drive_type = _volume_info(destination)
    if drive_type not in (2, 3):
        plan.problems.append('目标需要是这台电脑上的本地磁盘（不能是网络位置或光驱）。')
    elif file_system.upper() != 'NTFS':
        plan.problems.append(f'目标磁盘是 {file_system or "未知"} 格式，需要 NTFS（运行环境里有目录链接，模型文件可能超过 4 GB）。')
    try:
        import tempfile
        with tempfile.TemporaryFile(dir=destination):
            pass
    except OSError as exc:
        plan.problems.append(f'这个文件夹不能写入：{exc}')

    candidates = []
    if RUNTIMES in kinds:
        if os.environ.get(RUNTIME_ROOT_ENV, '').strip() or paths.runtime_root_source == 'environment':
            plan.notes.append('运行环境位置由环境变量 2BYTEASR_RUNTIME_ROOT 指定，这次不移动运行环境。')
        else:
            candidates.append((RUNTIMES, Path(os.path.abspath(str(paths.managed_runtime_root)))))
    if MODELS in kinds:
        candidates.append((MODELS, Path(os.path.abspath(str(paths.model_root)))))
    for kind, source in candidates:
        target = destination / kind
        label = '运行环境' if kind == RUNTIMES else '模型'
        if _key(source) == _key(target):
            plan.notes.append(f'{label}已经在 {target}。')
            continue
        part = RelocationPart(kind, source, target)
        if source.is_dir():
            if kind == RUNTIMES:
                part.entries = tuple(sorted(entry.name for entry in os.scandir(_ext(source))))
                part.runtimes = tuple(_registered_runtimes(source))
            else:
                ours, others = _model_entries(source, paths.install_root)
                part.entries, part.left_behind = tuple(ours), tuple(others)
        if part.entries:
            linked = _linked_ancestor(source)
            if linked is not None:
                plan.problems.append(f'{label}现在的位置经过链接（{linked}），不能自动移动。')
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            plan.problems.append(f'{target} 已经有内容。请选一个空文件夹，或先把里面的东西移走。')
        for _other_kind, other in candidates:
            if _inside(target, other) or _inside(other, target):
                plan.problems.append(f'新位置不能在{label}现在的位置里面，也不能把它包含在内：{target}')
                break
        plan.parts.append(part)
    if not plan.parts and not plan.problems:
        plan.problems.append('模型和运行环境都已经在这个位置。')
        return plan

    try:
        for part in plan.parts:
            if part.empty:
                continue
            inventory = _inventory(part.source, part.entries, cancel)
            part.files, part.unique_bytes, part.longest = inventory.files, inventory.unique_bytes, inventory.longest
            part.same_volume = _same_volume(part.source, destination)
    except RelocationCancelled:
        plan.problems.append('已取消统计。')
        return plan
    except (OSError, RelocationError) as exc:
        plan.problems.append(f'统计现有文件时出错：{exc}')
        return plan

    if not _long_paths_enabled():
        for part in plan.parts:
            if part.longest and len(str(part.target)) + part.longest > 259:
                plan.problems.append(f'新位置的路径太长：{part.target} 下最深的文件会超过 Windows 的 260 字符限制。请选一个更短的路径，例如 D:\\2ByteASR。')
    plan.required_bytes = sum(part.unique_bytes for part in plan.parts if not part.same_volume and not part.empty)
    if plan.required_bytes:
        plan.required_bytes += RESERVE_BYTES
    plan.free_bytes = _free_bytes(destination)
    if plan.required_bytes and plan.free_bytes is not None and plan.free_bytes < plan.required_bytes:
        plan.problems.append(f'{destination.anchor} 剩余 {format_size(plan.free_bytes)}，需要 {format_size(plan.required_bytes)}（含 1 GB 余量）。')
    for part in plan.parts:
        if part.kind == RUNTIMES and part.entries:
            users = _processes_inside(part.source)
            if users:
                plan.problems.append('有程序正在使用运行环境：' + '、'.join(users[:3]) + '。请等它结束（或关闭对应窗口）后再移动。')
        if part.kind == MODELS and part.entries and _model_preparation_running(part.source / MODEL_STAGING):
            plan.problems.append('有模型正在下载或准备，请等它完成后再移动。')
        if part.left_behind:
            shown = '、'.join(part.left_behind[:5]) + ('…' if len(part.left_behind) > 5 else '')
            plan.notes.append(f'模型文件夹里另有 {len(part.left_behind)} 项不是兔白字幕下载的，留在原处：{shown}')
    return plan


# ---------------------------------------------------------------- move steps

@dataclass
class RelocationResult:
    status: str = 'moved'                     # moved | partial | rolled_back | cancelled | failed
    moved: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


class _Progress:
    def __init__(self, callback, total: int):
        self.callback, self.total, self.done, self.last = callback, max(0, total), 0, 0.0

    def phase(self, text: str) -> None:
        if self.callback:
            self.callback(text, self.done, self.total)

    def add(self, amount: int, text: str) -> None:
        self.done += amount
        now = time.monotonic()
        if self.callback and (now - self.last > .2 or self.done >= self.total):
            self.last = now
            self.callback(text, self.done, self.total)


class _Undo:
    """What a same-volume move changed in place, so a failure can put it back.

    Restoring happens in two halves around renaming the folders back: file
    contents and relinked junctions are undone in the new place first, then
    each junction is recreated at its old place, whose target exists again.
    """

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.junctions: list[tuple[Path, str]] = []

    def write(self, path: Path, data: bytes) -> None:
        if str(path) not in self.files:
            self.files[str(path)] = Path(_ext(path)).read_bytes()
        _write_atomic(path, data)

    def relink(self, link: Path, target) -> None:
        self.junctions.append((link, _junction_target(link)))
        os.rmdir(_ext(link))
        _make_junction(target, link)

    def undo_in_place(self) -> None:
        for path, data in self.files.items():
            _write_atomic(Path(path), data)
        for link, _target in reversed(self.junctions):
            try:
                os.rmdir(_ext(link))
            except FileNotFoundError:
                pass

    def relink_at(self, old: Path, new: Path) -> None:
        for link, target in self.junctions:
            _make_junction(target, Path(_swap_root(str(link), new, old)))


def _copy_file(source: Path, target: Path, info, cancel, progress: _Progress) -> None:
    try:
        reader = open(_ext(source), 'rb')
    except PermissionError as exc:
        raise RelocationError(f'{source} 正被其他程序占用，无法读取。请关闭用到它的程序后再试。') from exc
    except OSError as exc:
        raise RelocationError(f'无法读取 {source}：{exc.strerror or exc}') from exc
    try:
        with reader, open(_ext(target), 'xb') as writer:
            while True:
                _check(cancel)
                chunk = reader.read(_CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
                progress.add(len(chunk), f'正在复制 {source.name}')
    except OSError as exc:
        raise RelocationError(f'复制 {source} 时出错：{exc.strerror or exc}') from exc
    if os.stat(_ext(target)).st_size != info.st_size:
        raise RelocationError(f'复制后大小不一致：{source}')
    os.utime(_ext(target), ns=(info.st_atime_ns, info.st_mtime_ns))
    _set_attributes(target, getattr(info, 'st_file_attributes', 0))


def _copy_entries(part: RelocationPart, cancel, progress: _Progress) -> list[str]:
    """Copy ``part.entries`` into ``part.target``: hard links and internal junctions kept.

    Junctions are created last (Windows needs their target to exist); a
    junction whose target is already gone in the old place is left out and
    reported.
    """
    linked: dict = {}
    junctions: list[tuple[Path, str]] = []
    skipped: list[str] = []
    stack = [(part.source / name, part.target / name) for name in reversed(part.entries)]
    while stack:
        _check(cancel)
        source, target = stack.pop()
        if part.kind == RUNTIMES and source.parent == part.source and source.name == _GUARD_FILE:
            open(_ext(target), 'xb').close()
            continue
        info = _lstat(source)
        kind = _link_kind(info) if _is_reparse(info) else ''
        if kind:
            destination = _junction_target(source) if kind == 'junction' else _plain(os.readlink(_ext(source)))
            destination = _swap_root(destination, part.source, part.target)
            if kind == 'junction':
                junctions.append((target, destination))
            else:
                try:
                    os.symlink(destination, _ext(target), target_is_directory=stat.S_ISDIR(info.st_mode))
                except OSError as exc:
                    raise RelocationError(f'无法重建符号链接 {source}：{exc}') from exc
            continue
        if stat.S_ISDIR(info.st_mode):
            os.mkdir(_ext(target))
            with os.scandir(_ext(source)) as children:
                names = sorted(child.name for child in children)
            stack.extend((source / name, target / name) for name in reversed(names))
            continue
        key = (info.st_dev, info.st_ino) if info.st_nlink > 1 and info.st_ino else None
        if key is not None and key in linked:
            os.link(_ext(linked[key]), _ext(target))
            continue
        _copy_file(source, target, info, cancel, progress)
        if key is not None:
            linked[key] = target
    for link, destination in junctions:
        _check(cancel)
        if not os.path.isdir(_ext(destination)):
            skipped.append(f'{link}（原链接指向的 {destination} 已不存在）')
            continue
        _make_junction(destination, link)
    return skipped


def _replace_root_bytes(data: bytes, old: Path, new: Path) -> bytes:
    for old_text, new_text in ((str(old), str(new)), (str(old).replace('\\', '/'), str(new).replace('\\', '/'))):
        pattern = re.compile(re.escape(old_text.encode('utf-8')) + rb'(?=[\\/"\'\s;,:)\]]|$)', re.IGNORECASE)
        replacement = new_text.encode('utf-8')
        data = pattern.sub(lambda _match: replacement, data)
    return data


def _venv_roots(root: Path) -> list[Path]:
    """Environments (folders with pyvenv.cfg) up to three levels below the runtime root."""
    found, stack = [], [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            with os.scandir(_ext(folder)) as children:
                entries = [(child.name, child.is_dir(follow_symlinks=False)) for child in children]
        except OSError:
            continue
        if any(name.lower() == 'pyvenv.cfg' for name, _ in entries):
            found.append(folder)
            continue
        if depth >= 3:
            continue
        for name, is_dir in entries:
            if is_dir and not (depth == 0 and name in {'download-cache', 'python', 'tools'}):
                stack.append((folder / name, depth + 1))
    return found


_RT_RCDATA = 10
_LAUNCHER_PATH = 'UV_PYTHON_PATH'


def _kernel32():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    kernel.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel.FindResourceExW.restype = wintypes.HRSRC
    kernel.FindResourceExW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.WORD]
    kernel.LoadResource.restype = wintypes.HGLOBAL
    kernel.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    kernel.LockResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [wintypes.HGLOBAL]
    kernel.SizeofResource.restype = wintypes.DWORD
    kernel.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    kernel.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.WORD,
                                       ctypes.c_void_p, wintypes.DWORD]
    kernel.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    return kernel


def launcher_python_path(path) -> str | None:
    """The interpreter a uv launcher starts (its ``UV_PYTHON_PATH`` resource), or None.

    uv 0.11 makes a venv's ``Scripts\\python.exe``/``pythonw.exe`` and every
    console script a small launcher that stores an absolute path in this
    resource: the base Python for ``python.exe``, the venv's ``python.exe``
    for console scripts. pyvenv.cfg is not consulted for it (found
    2026-10-17 in a packaged-build check).
    """
    if os.name != 'nt':
        return None
    import ctypes
    kernel = _kernel32()
    module = kernel.LoadLibraryExW(str(path), None, 0x2 | 0x20)  # as data file + image resource
    if not module:
        return None
    try:
        handle = kernel.FindResourceExW(module, ctypes.c_void_p(_RT_RCDATA), _LAUNCHER_PATH, 0)
        if not handle:
            return None
        size = kernel.SizeofResource(module, handle)
        data = ctypes.string_at(kernel.LockResource(kernel.LoadResource(module, handle)), size)
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None
    finally:
        kernel.FreeLibrary(module)


def _relinked_launcher(path: Path, value: str) -> bytes:
    """The bytes of ``path`` with ``UV_PYTHON_PATH`` set to ``value``; ``path`` itself is untouched."""
    import ctypes
    kernel = _kernel32()
    scratch = Path(str(path) + '.relocate-res')
    shutil.copyfile(_ext(path), _ext(scratch))
    try:
        data = value.encode('utf-8')
        buffer = ctypes.create_string_buffer(data, len(data))
        handle = kernel.BeginUpdateResourceW(_plain(_ext(scratch)), False)
        if not handle:
            raise OSError(ctypes.get_last_error(), '无法改写启动器', str(path))
        if not kernel.UpdateResourceW(handle, ctypes.c_void_p(_RT_RCDATA), _LAUNCHER_PATH, 0, buffer, len(data)):
            error = ctypes.get_last_error()
            kernel.EndUpdateResourceW(handle, True)
            raise OSError(error, '无法改写启动器', str(path))
        if not kernel.EndUpdateResourceW(handle, False):
            raise OSError(ctypes.get_last_error(), '无法改写启动器', str(path))
        if launcher_python_path(scratch) != value:
            raise RelocationError(f'启动器改写后核对不符：{path}')
        return Path(_ext(scratch)).read_bytes()
    finally:
        try:
            os.unlink(_ext(scratch))
        except FileNotFoundError:
            pass


def _launcher_files(venv: Path) -> list[Path]:
    scripts = venv / 'Scripts'
    try:
        return sorted(path for path in scripts.glob('*.exe') if not _is_reparse(_lstat(path)))
    except OSError:
        return []


def _text_fixup_files(venv: Path) -> list[Path]:
    files = [venv / 'pyvenv.cfg']
    scripts = venv / ('Scripts' if os.name == 'nt' else 'bin')
    for folder, pattern in ((scripts, '*'), (venv / 'Lib' / 'site-packages', '*.pth')):
        try:
            for path in folder.glob(pattern):
                info = _lstat(path)
                if (stat.S_ISREG(info.st_mode) and not _is_reparse(info) and info.st_size < 1024 * 1024
                        and path.suffix.lower() in _TEXT_SUFFIXES):
                    files.append(path)
        except OSError:
            continue
    return files


def _rewrite_runtime_tree(part: RelocationPart, undo: _Undo | None, cancel) -> None:
    """Point the copy at itself: junctions (rename only), venv configs and scripts, registry."""
    old, new = part.source, part.target
    write = undo.write if undo is not None else _write_atomic
    if undo is not None:
        # A copy recreated its junctions already; a renamed tree still points at the old folder.
        stack = [new / name for name in part.entries if name != _GUARD_FILE]
        while stack:
            _check(cancel)
            path = stack.pop()
            try:
                info = _lstat(path)
            except FileNotFoundError:
                continue
            kind = _link_kind(info) if _is_reparse(info) else ''
            if kind == 'junction':
                target = _junction_target(path)
                moved = _swap_root(target, old, new)
                if moved != target and os.path.isdir(_ext(moved)):
                    undo.relink(path, moved)
            elif kind == 'symlink':
                raise RelocationError(f'运行环境里有符号链接，不能自动移动：{path}')
            elif stat.S_ISDIR(info.st_mode):
                with os.scandir(_ext(path)) as children:
                    stack.extend(path / child.name for child in children)
    for venv in _venv_roots(new):
        for path in _text_fixup_files(venv):
            _check(cancel)
            try:
                data = Path(_ext(path)).read_bytes()
            except OSError:
                continue
            changed = _replace_root_bytes(data, old, new)
            if changed != data:
                write(path, changed)
        # uv launchers keep their interpreter in a PE resource, not in pyvenv.cfg.
        for path in _launcher_files(venv):
            _check(cancel)
            target = launcher_python_path(path)
            moved = _swap_root(target, old, new) if target else target
            if target and moved != target:
                write(path, _relinked_launcher(path, moved))
    registry = new / 'registry.json'
    if registry.is_file():
        payload = json.loads(Path(_ext(registry)).read_text('utf-8-sig'))
        moved = _map_strings(payload, old, new)
        if moved != payload:
            write(registry, (json.dumps(moved, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _map_strings(value, old: Path, new: Path):
    if isinstance(value, dict):
        return {key: _map_strings(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_strings(item, old, new) for item in value]
    if isinstance(value, str) and len(value) > 2 and value[1:3] in (':\\', ':/'):
        return _swap_root(value, old, new)
    return value


# The process image and python DLL that really run. sys.prefix/base_prefix come
# from pyvenv.cfg, so they name the new folder even when a launcher still
# starts the old interpreter (2026-10-17, packaged-build check).
_START_CHECK = (
    'import json,sys\n'
    'def where(handle):\n'
    '    import ctypes\n'
    '    buffer = ctypes.create_unicode_buffer(32768)\n'
    '    ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(handle), buffer, 32768)\n'
    '    return buffer.value\n'
    "image = where(None) if sys.platform == 'win32' else sys.executable\n"
    "dll = where(getattr(sys, 'dllhandle', 0) or None) if sys.platform == 'win32' else ''\n"
    'print(json.dumps([sys.prefix, sys.base_prefix, image, dll]))\n')


def _probe_interpreter(key: str, python: str, root: Path) -> dict:
    """Start the interpreter; for roles with a deployment contract run the environment probe."""
    if key != MFA_RUNTIME:
        return _probe_started(key, python, root)
    # Importing MFA writes its root folder (config, joblib cache), by default Documents\MFA:
    # give it a throwaway one, as the worker and the installer do (2026-10-19).
    import tempfile
    scratch = tempfile.mkdtemp(prefix='2byteasr-mfa-check-')
    try:
        return _probe_started(key, python, root, mfa_root=scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _probe_started(key: str, python: str, root: Path, *, mfa_root: str = '') -> dict:
    from ..system.processes import python_utf8_command, run_hidden_subprocess, sanitized_child_environment
    report = {'key': key, 'python': python, 'starts': False, 'probe': None, 'problems': []}
    env, where = sanitized_child_environment(), {}
    try:
        if key == MFA_RUNTIME:
            # Its own folder as cwd, like every MFA-env call: the packaged app's folder holds 3.10 .pyd files.
            from ..recognition.mfa_aligner import runtime_environment
            env, where = runtime_environment(Path(python).parent, env), {'cwd': str(Path(python).parent)}
            env['MFA_ROOT_DIR'] = mfa_root
        completed = run_hidden_subprocess(
            python_utf8_command([python, '-I', '-c', _START_CHECK]),
            purpose='runtime relocation start check', capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=120, env=env, **where)
        prefix, base, image, dll = json.loads((completed.stdout or '').strip().splitlines()[-1])
        report['starts'] = completed.returncode == 0 and _inside(prefix, root)
        report['prefix'], report['base_prefix'], report['image'], report['dll'] = prefix, base, image, dll
        if not report['starts']:
            report['problems'].append(f'{key} 解释器启动后的位置是 {prefix}')
    except Exception as exc:  # any failure to start is reported, not raised
        report['problems'].append(f'{key} 解释器无法启动：{exc}')
        return report
    if key == MFA_RUNTIME:
        # No deployment contract: MFA's Kaldi/OpenFst and tokenizer imports are its check.
        from ..recognition.mfa_aligner import CHECK_IMPORTS
        try:
            checked = run_hidden_subprocess(
                python_utf8_command([python, '-I', '-c', CHECK_IMPORTS]), purpose='MFA runtime relocation check',
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, env=env, **where)
            report['probe'] = checked.returncode == 0
            if not report['probe']:
                report['problems'].append('MFA 组件无法加载：' + (checked.stderr or checked.stdout or '')[-400:])
        except Exception as exc:
            report['probe'] = False
            report['problems'].append(f'MFA 组件检查失败：{exc}')
        return report
    try:
        from ..system.environment import deep_preflight, environments_contract
        environments_contract(key)
    except Exception:
        return report  # no deployment contract for this entry: the start check is the check
    result = deep_preflight(key, interpreter=python, use_cache=False)
    report['probe'] = bool(result.ok)
    if not result.ok:
        report['problems'].extend(str(item) for item in result.problems[:4])
    return report


def _rewrite_user_records(old: Path, new: Path) -> None:
    """Paths recorded outside the moved folder: readiness receipts and model detach records."""
    from ..runtime_paths import user_data_root
    data = user_data_root()
    for receipt in sorted((data / 'model-readiness').glob('*.json')):
        try:
            payload = json.loads(receipt.read_text('utf-8'))
        except (OSError, ValueError):
            continue
        moved = _map_strings(payload, old, new)
        if moved != payload:
            _write_atomic(receipt, (json.dumps(moved, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    record = data / 'model-associations.json'
    try:
        payload = json.loads(record.read_text('utf-8-sig'))
    except (OSError, ValueError):
        return
    detached = payload.get('detached') if isinstance(payload, dict) else None
    if not isinstance(detached, dict):
        return
    changed = {}
    for key, item in detached.items():
        path = str((item or {}).get('path') or key) if isinstance(item, dict) else key
        moved = _swap_root(path, old, new)
        if moved != path:
            changed[key] = (os.path.normcase(moved), {**item, 'path': moved} if isinstance(item, dict) else item)
    if changed:
        for key, (new_key, item) in changed.items():
            detached.pop(key)
            detached[new_key] = item
        _write_atomic(record, json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))


def _reset_caches() -> None:
    from ..runtime_paths import reset_runtime_paths
    from ..system.runtime_registry import reset_runtime_registry_cache
    from ..system.environment import reset_preflight_cache
    reset_runtime_paths()
    reset_runtime_registry_cache()
    reset_preflight_cache()


def _move_part(part: RelocationPart, cancel, progress: _Progress, probe, result: RelocationResult) -> None:
    from ..runtime_paths import complete_model_count, get_runtime_paths, set_model_root, set_runtime_root
    label = '运行环境' if part.kind == RUNTIMES else '模型'
    created_target = not part.target.exists()
    part.target.mkdir(parents=True, exist_ok=True)
    renamed: list[str] = []
    undo = _Undo() if part.same_volume else None
    guard = None
    try:
        if part.kind == RUNTIMES and part.entries:
            from contextlib import ExitStack
            from ..system.runtime_download_cache import bootstrap_guard
            guard = ExitStack()
            try:
                guard.enter_context(bootstrap_guard(part.source))
            except BlockingIOError as exc:
                raise RelocationError('运行环境正在安装或维护，请稍后再试。') from exc
        before = {}
        for key, python in part.runtimes:
            progress.phase(f'检查移动前的运行环境 {key}…')
            _check(cancel)
            before[key] = probe(key, python, part.source)
        if part.entries:
            if part.same_volume:
                progress.phase(f'正在移动{label}（同一磁盘，直接改名）…')
                if part.kind == RUNTIMES:
                    _wait_until_unused(part.source, cancel)
                for name in part.entries:
                    _check(cancel)
                    if part.kind == RUNTIMES and name == _GUARD_FILE:
                        continue
                    _rename(part.source / name, part.target / name, cancel)
                    renamed.append(name)
                if part.kind == RUNTIMES and _GUARD_FILE in part.entries:
                    open(_ext(part.target / _GUARD_FILE), 'xb').close()
            else:
                progress.phase(f'正在复制{label}…')
                for item in _copy_entries(part, cancel, progress):
                    result.messages.append('没有复制失效的目录链接：' + item)
        if part.kind == RUNTIMES:
            progress.phase('正在更新运行环境里记录的位置…')
            _rewrite_runtime_tree(part, undo, cancel)
            for key, python in part.runtimes:
                _check(cancel)
                progress.phase(f'检查移动后的运行环境 {key}…')
                after = probe(key, _swap_root(python, part.source, part.target), part.target)
                was = before.get(key) or {}
                if was.get('starts') and not after.get('starts'):
                    raise RelocationError(f'{key} 移动后无法启动：' + '；'.join(after.get('problems') or ['原因未知']))
                # While the old copy still exists, a venv whose pyvenv.cfg kept the
                # old base Python would start fine and break once it is deleted.
                for field in ('base_prefix', 'image', 'dll'):
                    if (was.get(field) and _inside(was[field], part.source)
                            and not _inside(after.get(field) or '', part.target)):
                        raise RelocationError(f'{key} 移动后仍在使用旧位置的 Python：{after.get(field)}')
                if was.get('probe') and not after.get('probe'):
                    raise RelocationError(f'{key} 移动后没有通过环境检查：' + '；'.join(after.get('problems') or ['原因未知']))
                if not was.get('starts') or was.get('probe') is False:
                    result.messages.append(f'{key} 在移动前就不完整，已一并移动；需要时请在模型工坊修复。')
        else:
            install_root = get_runtime_paths().install_root
            if not part.same_volume and complete_model_count(part.target, install_root) < complete_model_count(part.source, install_root):
                raise RelocationError('复制后的完整模型数量比原位置少。')
        _check(cancel)
        # Commit: runtime_paths.json is replaced atomically, so a failure here
        # leaves the old registration and is rolled back like any other.
        progress.phase(f'正在登记{label}的新位置…')
        if part.kind == RUNTIMES:
            set_runtime_root(part.target)
        else:
            set_model_root(part.target)
    except BaseException as exc:
        progress.phase(f'正在还原{label}…')
        problems = _rollback(part, renamed, undo, created_target)
        if guard is not None:
            guard.close()
        _reset_caches()
        if problems:
            result.leftovers.extend(problems)
        raise exc
    # From here on the new location is in use; cancel no longer applies.
    try:
        _rewrite_user_records(part.source, part.target)
    except (OSError, ValueError) as exc:
        result.messages.append(f'记录里的旧路径没有全部更新（不影响使用）：{exc}')
    finally:
        _reset_caches()
        if guard is not None:
            guard.close()
    result.moved.append(part.kind)
    progress.phase(f'正在删除{label}的旧位置…')
    failures: list[str] = []
    if part.entries and not part.same_volume:
        for name in part.entries:
            _remove_tree(part.source / name, failures, root=part.source)
    elif part.kind == RUNTIMES and _GUARD_FILE in part.entries:
        _remove_tree(part.source / _GUARD_FILE, failures, root=part.source)
    try:
        if not any(part.source.iterdir()):
            part.source.rmdir()
    except OSError:
        pass
    if failures:
        result.leftovers.extend(failures)
        result.messages.append(f'{label}旧位置有 {len(failures)} 项暂时删不掉（可能正被占用），可以稍后手动删除：{part.source}')


def _rollback(part: RelocationPart, renamed: list[str], undo: _Undo | None, created_target: bool) -> list[str]:
    """Put the old location back exactly; remove what the move created."""
    problems: list[str] = []
    if part.same_volume:
        try:
            if undo is not None:
                undo.undo_in_place()
        except OSError as exc:
            problems.append(f'还原改写的文件失败：{exc}')
        for name in reversed(renamed):
            try:
                os.rename(_ext(part.target / name), _ext(part.source / name))
            except OSError as exc:
                problems.append(f'{part.target / name} 无法移回：{exc}')
        try:
            if undo is not None:
                undo.relink_at(part.source, part.target)
        except OSError as exc:
            problems.append(f'还原目录链接失败：{exc}')
        guard_copy = part.target / _GUARD_FILE
        if part.kind == RUNTIMES and guard_copy.exists() and (part.source / _GUARD_FILE).exists():
            _remove_tree(guard_copy, problems, root=part.target)
    else:
        for name in part.entries:
            _remove_tree(part.target / name, problems, root=part.target)
    if created_target:
        try:
            part.target.rmdir()
        except OSError:
            pass
    return problems


def execute_relocation(plan: RelocationPlan, *, cancel=None, progress=None, probe=None, busy=None) -> RelocationResult:
    """Run a checked plan. ``progress(text, done_bytes, total_bytes)`` may be called from this thread."""
    if not plan.ok:
        raise RelocationError('；'.join(plan.problems) or '没有需要移动的内容。')
    if busy is not None and busy():
        raise RelocationError('请等识别、模型下载、安装、修复或导出结束后再移动。')
    if _RUNNING.is_set():
        raise RelocationError('另一项移动正在进行。')
    probe = probe or _probe_interpreter
    tracker = _Progress(progress, sum(part.unique_bytes for part in plan.parts if not part.same_volume))
    result = RelocationResult()
    _RUNNING.set()
    try:
        for part in plan.parts:
            label = '运行环境' if part.kind == RUNTIMES else '模型'
            try:
                _move_part(part, cancel, tracker, probe, result)
            except RelocationCancelled:
                result.status = 'cancelled'
                result.messages.append(f'{label}已还原，仍在 {part.source}。')
                break
            except Exception as exc:
                result.status = 'failed'
                result.messages.append(f'{label}移动失败，已还原，仍在 {part.source}：{exc}')
                break
        if result.status in {'cancelled', 'failed'} and result.moved:
            result.status = 'partial'
        if result.leftovers and result.status == 'moved':
            result.messages.append('移动已完成，但有旧文件没删掉，详情见上。')
    finally:
        _RUNNING.clear()
    return result


__all__ = [
    'RelocationError', 'RelocationPart', 'RelocationPlan', 'RelocationResult',
    'execute_relocation', 'format_size', 'plan_relocation', 'relocation_running',
]
