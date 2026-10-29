"""Per-user project registration; Windows keeps ownership of UserChoice."""
from __future__ import annotations

import os
from pathlib import Path
import sys

PROG_ID = '2ByteASR.Project'


def stable_launch_entry() -> Path:
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).resolve()
        # A checkout's root launcher is stable across onedir promotions.
        if executable.parent.name == '2ByteASR' and executable.parent.parent.name == 'dist':
            launcher = executable.parents[2] / '2ByteASR.exe'
            if launcher.is_file():
                return launcher
        return executable  # Setup installs the GUI directly at {app}.
    return Path(__file__).resolve().parents[2] / '2ByteASR.exe'


def repair_project_association(*, entry=None, registry=None, notify=True) -> Path:
    if os.name != 'nt' and registry is None:
        raise OSError('工程文件关联只适用于 Windows。')
    if registry is None:
        import winreg as registry
    executable = Path(entry or stable_launch_entry()).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f'工程启动入口不存在：{executable}')
    base = 'Software\\Classes\\'
    values = {
        PROG_ID: ('', '兔白字幕工程'),
        PROG_ID+'\\DefaultIcon': ('', f'"{executable}",0'),
        PROG_ID+'\\shell\\open\\command': ('', f'"{executable}" "%1"'),
        '.2byteproj\\OpenWithProgids': (PROG_ID, ''),
        'Applications\\2ByteASR.exe\\shell\\open\\command': ('', f'"{executable}" "%1"'),
        'Applications\\2ByteASR.exe\\SupportedTypes': ('.2byteproj', ''),
    }
    for key, (name, value) in values.items():
        with registry.CreateKey(registry.HKEY_CURRENT_USER, base+key) as handle:
            registry.SetValueEx(handle, name, 0, registry.REG_SZ, value)
    # Blank defaults may be filled. Existing defaults and protected UserChoice
    # are never overwritten; Open With remains available in either case.
    with registry.CreateKey(registry.HKEY_CURRENT_USER, base+'.2byteproj') as handle:
        try:
            default = registry.QueryValueEx(handle, '')[0]
        except FileNotFoundError:
            default = ''
        if not default:
            registry.SetValueEx(handle, '', 0, registry.REG_SZ, PROG_ID)
    if notify and os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    return executable
