"""Read-only discovery and application-owned GIMP workspace configuration.

Discovery never executes GIMP, writes preferences or touches personal profiles.
Only the user's explicit editor choice grants permission to launch a runtime.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil

from .cover_psd import atomic_bytes

DOWNLOAD_URL = 'https://www.gimp.org/downloads/'
COVER_TOOLS = ('move', 'scale', 'unified-transform', 'crop', 'text')


@dataclass(frozen=True)
class GimpRuntime:
    root: Path
    version: str

    @property
    def executable(self):
        return self.root / 'bin/gimp-3.exe'


def file_version(executable):
    """Read the Windows PE version resource without starting the executable."""
    if os.name != 'nt':
        raise ValueError('此接入需要 Windows 版 GIMP')
    from ctypes import wintypes
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    api.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(executable), None)
    if not size:
        raise ValueError('无法读取 GIMP 版本，请选择官方 Windows 安装中的 gimp-3.exe')
    data = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.GetFileVersionInfoW(str(executable), 0, size, data) or not api.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)):
        raise ValueError('GIMP 版本资源不可读')
    values = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if length.value < 52 or values[0] != 0xFEEF04BD:
        raise ValueError('GIMP 版本资源无效')
    return f'{values[2] >> 16}.{values[2] & 65535}.{values[3] >> 16}'


def inspect_runtime(path):
    selected = Path(path).expanduser().resolve()
    if selected.is_file():
        if selected.name.lower() != 'gimp-3.exe':
            raise ValueError('请选择安装目录 bin 下的 gimp-3.exe')
        root = selected.parent.parent
    elif selected.name.lower() == 'bin':
        root = selected.parent
    else:
        root = selected
    required = ('bin/gimp-3.exe', 'bin/python.exe', 'lib/girepository-1.0/Gimp-3.0.typelib',
                'etc/gimp/3.0/sessionrc', 'etc/gimp/3.0/toolrc')
    if any(not (root / name).is_file() for name in required):
        raise ValueError('位置不存在或安装不完整；需包含 Python 与 GIMP 3 工作区资源')
    version = file_version(root / 'bin/gimp-3.exe')
    numbers = tuple(int(n) for n in version.split('.'))
    # Bridge uses text-outline APIs introduced in 3.2. Do not guess support
    # for GIMP 2 / 3.0 or a future incompatible minor release.
    if numbers[:2] != (3, 2) or numbers < (3, 2, 6):
        raise ValueError(f'检测到 GIMP {version}；此桥接支持 3.2.6 及更新的 3.2.x 版本')
    return GimpRuntime(root, version)


def discover_runtimes():
    resource = Path(__file__).resolve().parents[1]
    candidates = [resource / 'tools/gimp-3.2.6']  # existing optional deployment, never selected implicitly
    for key in ('ProgramFiles', 'ProgramW6432', 'LOCALAPPDATA'):
        value = os.environ.get(key)
        if value:
            base = Path(value) / 'Programs' if key == 'LOCALAPPDATA' else Path(value)
            candidates.extend(base / name for name in ('GIMP 3', 'GIMP 3.2'))
    found, seen = [], set()
    for candidate in candidates:
        try:
            runtime = inspect_runtime(candidate)
            key = os.path.normcase(str(runtime.root))
            if key not in seen:
                found.append(runtime)
                seen.add(key)
        except (OSError, ValueError):
            continue
    return found


def profile_path(workspace, runtime):
    identity = hashlib.sha256(os.path.normcase(str(runtime.root)).encode('utf8')).hexdigest()[:12]
    return Path(workspace) / ('gimp-profile-cover-' + identity)


def compact_toolrc(default):
    # The official file format permits flat GimpToolInfo entries. Retain every
    # tool, hiding all except cover tools; native menus/shortcuts remain intact.
    entries = re.findall(r'\(GimpToolInfo "([^"]+)"\s*\(icon-name "([^"]+)"\)\s*\(visible (?:yes|no)\)\)', default)
    by_name = dict(entries)
    visible = ['gimp-' + tool + '-tool' for tool in COVER_TOOLS]
    if not set(visible).issubset(by_name):
        raise ValueError('GIMP 工具配置不兼容，未改写工作区')
    order = visible + [name for name in by_name if name not in visible]
    return '(file-version 1)\n' + ''.join(
        f'(GimpToolInfo "{name}" (icon-name "{by_name[name]}") (visible {"yes" if name in visible else "no"}))\n'
        for name in order)


def seed_profile(workspace, runtime, *, mode='cover', dark=True):
    """Called only before starting our own process; never on a live profile."""
    if mode not in ('cover', 'full'):
        mode = 'cover'
    workspace = Path(workspace).resolve()
    profile = profile_path(workspace, runtime).resolve()
    if not profile.is_relative_to(workspace):
        raise ValueError('GIMP 配置必须位于应用封面工作区')
    profile.mkdir(parents=True, exist_ok=True)
    resource = Path(__file__).resolve().parents[1]
    marker = profile / '2byte-workspace-mode'
    replace = not marker.exists() or marker.read_text(encoding='utf8') != mode
    if replace:
        defaults = runtime.root / 'etc/gimp/3.0'
        toolrc = (defaults / 'toolrc').read_text(encoding='utf8')
        sessionrc = (defaults / 'sessionrc').read_text(encoding='utf8')
        if mode == 'cover':
            toolrc = compact_toolrc(toolrc)
            sessionrc = (resource / 'assets/gimp/cover-sessionrc').read_text(encoding='utf8')
        for name, value in (('toolrc', toolrc), ('sessionrc', sessionrc)):
            target = profile / name
            if target.exists():
                shutil.copy2(target, profile / (name + '.previous'))
            atomic_bytes(target, value.encode('utf8'))
        atomic_bytes(marker, mode.encode('utf8'))
    rc = profile / 'gimprc'
    content = rc.read_text(encoding='utf8') if rc.exists() else ''
    properties = {'language': '"zh_CN"', 'check-updates': 'no', 'show-welcome-dialog': 'no',
                  'theme-color-scheme': 'dark' if dark else 'light', 'devices-share-tool': 'yes'}
    if replace:
        properties.update({'toolbox-groups': 'no' if mode == 'cover' else 'yes',
                           'toolbox-wilber': 'no' if mode == 'cover' else 'yes',
                           'toolbox-color-area': 'no' if mode == 'cover' else 'yes',
                           'toolbox-foo-area': 'no', 'icon-theme': '"Symbolic"'})
    for name, value in properties.items():
        content = re.sub(r'\(' + re.escape(name) + r'\s+[^)]*\)\s*', '', content)
        content += f'({name} {value})\n'
    atomic_bytes(rc, content.encode('utf8'))
    if not (profile / 'contextrc').exists():
        atomic_bytes(profile / 'contextrc', b'(tool "gimp-move-tool")\n')
    options = profile / 'tool-options'
    options.mkdir(exist_ok=True)
    if not (options / 'gimp-move-tool').exists():
        atomic_bytes(options / 'gimp-move-tool', b'(move-current yes)\n')
    fonts = profile / 'fonts'
    fonts.mkdir(exist_ok=True)
    for name in ('SourceHanSansSC-Heavy.otf', 'LICENSE.txt'):
        source, target = resource / 'assets/fonts' / name, fonts / name
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copy2(source, target)
    plugin = profile / 'plug-ins/2byte-cover-bridge'
    plugin.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resource / 'assets/gimp/2byte-cover-bridge.py', plugin / '2byte-cover-bridge.py')
    return profile
