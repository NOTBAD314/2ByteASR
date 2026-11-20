"""PySide's first-import check without reading each module's source (2026-11-19).

User report (daily 171e958e): GUI stalls with PySide's feature hook on the stack
(feature_imported -> _mod_uses_pyside -> inspect.getsource -> tokenize.open) under lazy imports
while a project opens, in the packaged app, which ships the .py files.
"""
from __future__ import annotations

import inspect
import sys


def test_a_first_import_reads_no_source_and_keeps_pyside_s_answer(tmp_path, monkeypatch):
    import PySide6.QtCore  # noqa: F401 - PySide's import hook is in place from here
    import shibokensupport.feature as feature
    from twobyteasr.system import pyside_import_check

    assert pyside_import_check.install()
    assert feature._mod_uses_pyside is pyside_import_check.uses_pyside
    assert pyside_import_check.install()                       # idempotent

    (tmp_path / 'probe_uses_qt_a1.py').write_text('from PySide6.QtCore import QTimer\nVALUE = 1\n', 'utf-8')
    (tmp_path / 'probe_plain_a1.py').write_text('import json\nVALUE = 2\n', 'utf-8')
    monkeypatch.syspath_prepend(str(tmp_path))
    read = []
    real = inspect.getsource
    monkeypatch.setattr(inspect, 'getsource', lambda obj, _real=real: read.append(obj) or _real(obj))
    try:
        import probe_uses_qt_a1  # noqa: F401
        import probe_plain_a1  # noqa: F401
        assert read == []
        assert feature.pyside_feature_dict.get('probe_uses_qt_a1') == 0     # PySide: default features
        assert feature.pyside_feature_dict.get('probe_plain_a1') == -1      # not PySide: ignored
    finally:
        for name in ('probe_uses_qt_a1', 'probe_plain_a1'):
            sys.modules.pop(name, None)
            feature.pyside_feature_dict.pop(name, None)


def test_the_app_selects_no_pyside_feature_set():
    """The check only matters for ``from __feature__ import ...``; the app must not start using it
    without bringing the source check back."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    statement = re.compile(r'^\s*from\s+__feature__\s+import\b', re.MULTILINE)
    users = [path for path in (root / 'twobyteasr').rglob('*.py')
             if statement.search(path.read_text('utf-8', errors='replace'))]
    assert users == []


def test_dialog_motion_install_puts_the_check_in_place():
    from PySide6.QtWidgets import QApplication
    import shibokensupport.feature as feature
    from twobyteasr.design import transitions
    from twobyteasr.system import pyside_import_check
    app = QApplication.instance() or QApplication([])
    transitions.install(app)
    assert feature._mod_uses_pyside is pyside_import_check.uses_pyside
