"""Opt-in, inherited configuration boundary for source, spawn and frozen audits."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import tempfile
import sys


def isolation_root():
    value = os.environ.get('TWOBYTEASR_TEST_ROOT', '')
    if not value and getattr(sys, 'frozen', False):
        install_root = Path(sys.executable).resolve().parent
        if (install_root / '2byteasr-qa-profile.marker').is_file():
            value = str(install_root / 'tmp' / 'qa-profile')
            os.environ['TWOBYTEASR_TEST_ROOT'] = value
    if not value:
        return None
    root = Path(value).resolve()
    if not Path(value).is_absolute() or 'tmp' not in (part.lower() for part in root.parts):
        raise ValueError('TWOBYTEASR_TEST_ROOT must be an absolute path within a tmp directory')
    return root


def install():
    root = isolation_root()
    if root is None:
        return
    for folder in ('local', 'roaming', 'temp', 'config', 'qsettings'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'),
                      TEMP=str(root/'temp'), TMP=str(root/'temp'),
                      **{'2BYTEASR_USER_DATA_ROOT': str(root/'local')})
    tempfile.tempdir = str(root/'temp')
    # Do not discover the operator's Python/model caches via HOME or registry.
    for folder in ('profile', 'models', 'hf-cache', 'modelscope-cache', 'torch-cache'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    os.environ.update(USERPROFILE=str(root/'profile'), HF_HOME=str(root/'hf-cache'),
                      MODELSCOPE_CACHE=str(root/'modelscope-cache'), TORCH_HOME=str(root/'torch-cache'),
                      **{'2BYTEASR_MODEL_ROOT': str(root/'models')})
    for key in tuple(os.environ):
        if key.endswith(('_API_KEY', '_ACCESS_TOKEN', '_AUTH_TOKEN')):
            os.environ.pop(key, None)
    try:
        from PySide6 import QtCore
    except ImportError:
        # Headless role environments may not install Qt. They still inherit
        # the filesystem/config boundary and cannot construct QSettings.
        return
    if getattr(QtCore.QSettings, '_twobyte_isolation_root', None) == root:
        return
    original = getattr(QtCore.QSettings, '_twobyte_original', QtCore.QSettings)

    class IsolatedSettings(original):
        _twobyte_isolated = True
        _twobyte_original = original
        _twobyte_isolation_root = root

        def __init__(self, *args, **kwargs):
            if len(args) >= 2 and isinstance(args[1], original.Format):
                path = Path(str(args[0])).resolve()
                if not path.is_relative_to(root):
                    digest = hashlib.sha256(str(path).encode()).hexdigest()[:20]
                    path = root/'qsettings'/f'explicit-{digest}.ini'
                super().__init__(str(path), original.IniFormat)
                return
            strings = [value for value in args if isinstance(value, str)]
            org = kwargs.get('organization') or (strings[0] if strings else QtCore.QCoreApplication.organizationName()) or 'default'
            app = kwargs.get('application') or (strings[1] if len(strings) > 1 else QtCore.QCoreApplication.applicationName()) or 'default'
            identity = f'{org}/{app}'
            label = re.sub(r'[^\w.-]', '_', identity)[:90]
            digest = hashlib.sha256(identity.encode()).hexdigest()[:10]
            super().__init__(str(root/'qsettings'/f'{label}-{digest}.ini'), original.IniFormat)
            self.setFallbacksEnabled(False)

    QtCore.QSettings = IsolatedSettings
