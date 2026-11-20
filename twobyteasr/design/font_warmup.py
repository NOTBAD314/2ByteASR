"""Register bundled Qt fonts while application modules load.

PySide releases the interpreter lock while registering font files. The first
fallback-font measurement holds that lock, so Qt fills its system font database
when the GUI first needs it. Registration is synchronized with the GUI thread.
"""
from __future__ import annotations

import os
import sys
import threading

# A Chinese character, a Latin letter, and characters of scripts no user-interface font covers, so
# the fallback list is asked for whatever the default font is.
SAMPLE = '字 A ก ع ●'
_STATE = {'thread': None, 'ms': None, 'registered': None}
_REGISTER = threading.Lock()


def bundled_font_files() -> list:
    """The font files shipped with the app, in the order they are registered."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    files = []
    for directory in (root / 'assets' / 'fonts', root / 'tools' / 'fonts'):
        if directory.is_dir():
            files += sorted(directory.glob('*.otf')) + sorted(directory.glob('*.ttf'))
    return files


def register_bundled_fonts() -> int:
    """Register the bundled fonts (once per process, whichever thread asks first; a second caller
    waits until they are in). Returns how many files were registered."""
    with _REGISTER:
        if _STATE['registered'] is None:
            from PySide6.QtGui import QFontDatabase
            found = 0
            for path in bundled_font_files():
                try:
                    QFontDatabase.addApplicationFont(str(path))
                    found += 1
                except Exception:  # noqa: BLE001 - one unreadable file does not stop the others
                    pass
            _STATE['registered'] = found
        return _STATE['registered']


def _measure() -> None:
    """Register the bundled font files (the part that really runs beside the main thread)."""
    import time
    began = time.perf_counter()
    try:
        register_bundled_fonts()
    except Exception:  # noqa: BLE001 - the GUI thread registers them itself then
        return
    _STATE['ms'] = round((time.perf_counter() - began) * 1000, 1)


def start() -> bool:
    """Begin (once) after QApplication exists. True when the thread was started."""
    if sys.platform != 'win32' or _STATE['thread'] is not None or os.environ.get('TWOBYTEASR_FONT_WARMUP', '1') == '0':
        return False
    thread = _STATE['thread'] = threading.Thread(target=_measure, name='font-database-warmup', daemon=True)
    thread.start()
    return True


def elapsed_ms():
    """How long it took (None while it runs, when it failed or was not started)."""
    return _STATE['ms']


__all__ = ['SAMPLE', 'bundled_font_files', 'elapsed_ms', 'register_bundled_fonts', 'start']
