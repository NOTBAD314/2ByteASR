"""Qt's graphics-card check is done beside the imports instead of inside the first window (2026-11-19).

User (2026-11-19): opening the app takes five seconds. Showing the main window took 0.3-0.45 s
even when it was empty. Sampled from another process, all of it was Qt's Windows plugin creating
its first ordinary window: it asks Direct3D 9 which graphics card there is (to choose its OpenGL
backend), and creating the Direct3D 9 object makes the card's driver load and Windows verify the
driver's signature. A tool window, a dialog or a splash window does not trigger it.

The same object is created here on a thread of its own, started at the very beginning of the
process. ``ctypes`` releases the interpreter lock for the call, so it runs while the main thread
imports the application (measured: the main thread's work is not slowed, and Qt's first window
is created in 12-16 ms instead of 380-440 ms). It only helps while the object is alive (released
at once, Qt paid the full time again), so it is kept until the main window is up and then let go.

Windows only; any failure leaves Qt to do its own check exactly as before. No Qt and no
application imports: this runs before both.
"""
from __future__ import annotations

import os
import sys
import threading

D3D_SDK_VERSION = 32
_LOCK = threading.Lock()
_STATE = {'thread': None, 'handle': None, 'ms': None, 'released': False}


def _create() -> None:
    import ctypes
    import time
    from ctypes import wintypes
    began = time.perf_counter()
    try:
        d3d9 = ctypes.WinDLL('d3d9.dll', winmode=0x00000800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
        d3d9.Direct3DCreate9.restype = ctypes.c_void_p
        d3d9.Direct3DCreate9.argtypes = [wintypes.UINT]
        handle = d3d9.Direct3DCreate9(D3D_SDK_VERSION)
    except (OSError, AttributeError):
        handle = None
    with _LOCK:
        _STATE['ms'] = round((time.perf_counter() - began) * 1000, 1)
        if handle and _STATE['released']:
            _release_handle(handle)             # the window was up before this finished
        else:
            _STATE['handle'] = handle


def _release_handle(handle) -> None:
    import ctypes
    from ctypes import wintypes
    try:
        vtable = ctypes.cast(ctypes.cast(handle, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])(handle)      # IUnknown::Release
    except (OSError, ValueError):
        pass


def start() -> bool:
    """Begin the check on its own thread (once). True when it was started."""
    if sys.platform != 'win32' or os.environ.get('TWOBYTEASR_GPU_WARMUP', '1') == '0':
        return False
    with _LOCK:
        if _STATE['thread'] is not None or _STATE['released']:
            return False
        thread = _STATE['thread'] = threading.Thread(target=_create, name='gpu-probe-warmup', daemon=True)
    thread.start()
    return True


def release() -> None:
    """The main window exists: Qt has made (and remembers) its own check, the object can go."""
    with _LOCK:
        handle, _STATE['handle'] = _STATE['handle'], None
        _STATE['released'] = True
    if handle:
        _release_handle(handle)


def elapsed_ms():
    """How long the check took (None while it runs or when it was not started)."""
    return _STATE['ms']


__all__ = ['elapsed_ms', 'release', 'start']
