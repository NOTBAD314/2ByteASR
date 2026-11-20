"""PySide's first-import check without reading each module's source file (2026-11-19).

PySide6 wraps ``builtins.__import__``. The first time an import statement returns a module it asks
``shibokensupport.feature._mod_uses_pyside(module)``, which runs ``inspect.getsource(module)``
(linecache + tokenize of the whole file, kept in linecache afterwards) only to look for the text
"PySide6". The packaged app ships every twobyteasr ``.py`` beside the EXE for the external workers,
so the EXE does this too, on the GUI thread, under every lazy import: report-043c214b's GUI_STALL
stacks show it inside caption_scene.py:446, scoped_style.py:62 and studio_review_ui.py:833 while a
project opens, and source runs pay it for every module.

The answer only decides which ``from __feature__ import snake_case/true_property`` selection a
module runs under. Nothing in the app or its libraries selects one, so every module gets Qt's
default set either way. The check now looks at the module's globals for PySide objects instead.
"""
import sys
from types import ModuleType

_PREFIXES = ('PySide6', 'shiboken6')


def uses_pyside(module) -> bool:
    """True when ``module`` holds a PySide module, class, function or object at module level."""
    try:
        values = list(vars(module).values())
    except TypeError:
        return False
    for value in values:
        try:
            name = value.__name__ if isinstance(value, ModuleType) else getattr(value, '__module__', None)
        except Exception:  # noqa: BLE001 - an odd global (lazy proxy) is simply not PySide
            continue
        if isinstance(name, str) and name.startswith(_PREFIXES):
            return True
    return False


uses_pyside.twobyteasr = True


def install() -> bool:
    """Replace PySide's source-reading check (once PySide is imported). True when it is in place."""
    feature = sys.modules.get('shibokensupport.feature')
    current = getattr(feature, '_mod_uses_pyside', None)
    if not callable(current):
        return False
    if not getattr(current, 'twobyteasr', False):
        feature._mod_uses_pyside = uses_pyside
    return True
