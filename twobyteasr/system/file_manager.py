"""Open a visible system file manager for a completed output."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys


def _windows_reveal(path: Path) -> bool:
    """Ask Explorer to select a file without inheriting worker SW_HIDE flags."""
    # cidl=0 selects the fully specified item and opens its parent folder:
    # https://learn.microsoft.com/windows/win32/api/shlobj_core/nf-shlobj_core-shopenfolderandselectitems
    ole = ctypes.WinDLL('ole32')
    shell = ctypes.WinDLL('shell32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32, ctypes.c_void_p]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32]
    shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    # Qt may already have initialized this thread with a different COM model.
    if initialized < 0 and (initialized & 0xffffffff) != 0x80010106:
        return False
    item = ctypes.c_void_p()
    try:
        if shell.SHParseDisplayName(str(path), None, ctypes.byref(item), 0, None) < 0:
            return False
        return shell.SHOpenFolderAndSelectItems(item, 0, None, 0) >= 0
    finally:
        if item.value:
            ole.CoTaskMemFree(item)
        if initialized >= 0:
            ole.CoUninitialize()


def reveal_file(path: str | Path) -> bool:
    """Select an existing file, falling back to opening its containing folder."""
    output = Path(path).resolve()
    if not output.is_file():
        return False
    if sys.platform == 'win32':
        try:
            if _windows_reveal(output):
                return True
        except (OSError, AttributeError):
            pass
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent)))
