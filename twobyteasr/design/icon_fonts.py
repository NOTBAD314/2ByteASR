"""qtawesome loads the two icon fonts the app uses, the other ten only if something asks (2026-11-19).

The first icon of a start (the window's own buttons) made qtawesome read and check all twelve of
its bundled font files and load every one with its glyph table: 0.18-0.22 s of the main window's
construction (profiled: ``window_chrome_widgets`` 218 ms, of which ``qtawesome._instance`` 184 ms).
The app's icons are all ``fa5s.*`` and ``ph.*``.

``install`` builds qtawesome's own ``IconicFont`` with those two sets (checked as qtawesome checks
them) and hands it to qtawesome as its instance. A name from another set still works: the set is
checked and loaded the first time it is looked up. Where qtawesome's internals are not as
expected nothing is changed and qtawesome loads everything as it always did.
"""
from __future__ import annotations

USED = ('fa5s', 'ph')


class _OnDemand(dict):
    """A per-prefix table that loads a font set the first time its prefix is looked up."""

    def __init__(self, load, values):
        super().__init__(values)
        self._load = load

    def __missing__(self, prefix):
        self._load(prefix)
        return dict.__getitem__(self, prefix)          # KeyError for a prefix that is no font set

    def __contains__(self, prefix):
        if not dict.__contains__(self, prefix):
            self._load(prefix)
        return dict.__contains__(self, prefix)


def _check(qta, fargs) -> None:
    """qtawesome's own check of a bundled font file, for one set."""
    import hashlib
    import os
    if getattr(qta, '_SYSTEM_FONTS', False):
        return
    expected = qta._MD5_HASHES.get(fargs[1])
    if expected is None:
        return
    path = os.path.join(os.path.dirname(os.path.realpath(qta.__file__)), 'fonts', fargs[1])
    with open(path, 'rb') as stream:
        if hashlib.md5(stream.read()).hexdigest() != expected:   # noqa: S324 - qtawesome's integrity check
            raise qta.FontError(f"Font is corrupt at: '{path}'")


def install(used=USED) -> bool:
    """Give qtawesome an instance with only ``used`` loaded. True when done; never raises."""
    try:
        import qtawesome as qta
        from qtawesome.iconic_font import IconicFont
        if qta._resource.get('iconic') is not None:
            return False                               # qtawesome is already up
        bundled = tuple(qta._BUNDLED_FONTS)
        first = [fargs for fargs in bundled if fargs[0] in used]
        pending = {fargs[0]: fargs for fargs in bundled if fargs[0] not in used}
        if len(first) != len(used):
            return False
        for fargs in first:
            _check(qta, fargs)
        instance = IconicFont(*first)

        def load(prefix):
            fargs = pending.pop(prefix, None)
            if fargs is not None:
                _check(qta, fargs)
                instance.load_font(*fargs)

        instance.charmap = _OnDemand(load, instance.charmap)
        instance.fontname = _OnDemand(load, instance.fontname)
        qta._resource['iconic'] = instance
        return True
    except Exception:  # noqa: BLE001 - qtawesome then loads everything itself, as before
        return False


__all__ = ['USED', 'install']
