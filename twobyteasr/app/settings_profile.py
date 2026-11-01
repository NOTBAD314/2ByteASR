"""Keep GUI Qt preferences with an explicitly selected application data root."""
from __future__ import annotations

import hashlib
import os
import re


def configure_gui_settings_profile() -> bool:
    """Redirect GUI QSettings only when a separate data root is explicitly set."""
    if not os.environ.get('2BYTEASR_USER_DATA_ROOT', '').strip() or os.environ.get('TWOBYTEASR_TEST_ROOT'):
        return False
    from pathlib import Path
    from PySide6 import QtCore
    from ..runtime_paths import user_data_root

    root = (user_data_root() / 'qsettings').resolve()
    original = QtCore.QSettings
    if getattr(original, '_twobyte_gui_profile_root', None) == root:
        return True
    original.setDefaultFormat(original.IniFormat)
    original.setPath(original.IniFormat, original.UserScope, str(root))

    # On Windows QSettings(org, app) still selects NativeFormat despite
    # setDefaultFormat. Route that constructor explicitly to Qt's INI backend.
    class ProfileSettings(original):
        _twobyte_gui_profile_root = root

        def __init__(self, *args, **kwargs):
            if ((len(args) >= 2 and isinstance(args[1], original.Format))
                    or (args and isinstance(args[0], (original.Format, original.Scope)))):
                super().__init__(*args, **kwargs)
                return
            strings = [value for value in args if isinstance(value, str)]
            org = kwargs.get('organization') or (strings[0] if strings else QtCore.QCoreApplication.organizationName()) or 'default'
            app = kwargs.get('application') or (strings[1] if len(strings) > 1 else QtCore.QCoreApplication.applicationName()) or 'default'
            identity = f'{org}/{app}'
            label = re.sub(r'[^\w.-]', '_', identity)[:90]
            digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:10]
            parent = kwargs.get('parent')
            if parent is None:
                parent = next((value for value in args if isinstance(value, QtCore.QObject)), None)
            filename = str(root / f'{label}-{digest}.ini')
            if parent is None:
                super().__init__(filename, original.IniFormat)
            else:
                super().__init__(filename, original.IniFormat, parent)
            self.setFallbacksEnabled(False)

    QtCore.QSettings = ProfileSettings
    return True
