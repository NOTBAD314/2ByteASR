"""Opt-in, inherited configuration boundary for source, spawn and frozen audits."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import tempfile
import sys


def _keep_icon_fonts_in_process():
    """Skip qtawesome's Windows-wide install only in isolated processes.

    Its bundled-font loader already uses addApplicationFontFromData. Keep
    the import lazy so headless workers do not load QtWidgets for this hook.
    """
    if os.name != "nt":
        return
    import importlib.abc

    def patch(module):
        def private_directory(self, fonts_directory, system_wide=False):
            return fonts_directory
        module.IconicFont._install_fonts = private_directory

    loaded = sys.modules.get("qtawesome.iconic_font")
    if loaded is not None:
        patch(loaded)
    if any(getattr(finder, "_twobyte_private_icon_fonts", False) for finder in sys.meta_path):
        return

    class PrivateFontLoader:
        def __init__(self, loader):
            self.loader = loader

        def __getattr__(self, name):
            return getattr(self.loader, name)

        def create_module(self, spec):
            create = getattr(self.loader, "create_module", None)
            return create(spec) if create is not None else None

        def exec_module(self, module):
            self.loader.exec_module(module)
            patch(module)

    class PrivateFontFinder(importlib.abc.MetaPathFinder):
        _twobyte_private_icon_fonts = True

        def find_spec(self, fullname, path, target=None):
            if fullname != "qtawesome.iconic_font":
                return None
            # Include PyInstaller's importer; PathFinder alone may miss PYZ.
            for finder in tuple(sys.meta_path):
                if finder is self or not hasattr(finder, "find_spec"):
                    continue
                spec = finder.find_spec(fullname, path, target)
                if spec is not None:
                    if spec.loader is not None:
                        spec.loader = PrivateFontLoader(spec.loader)
                    return spec
            return None

    sys.meta_path.insert(0, PrivateFontFinder())


def install_pytest_network_guard():
    """Give both pytest entries the same Python TCP loopback-only boundary.

    Qt networking and native subprocesses do not use these wrappers: this is
    not an OS firewall. They need explicit local fixtures; the separate real
    account-CLI guard remains in conftest.py. Ordinary application launches
    and authorized network audits do not call this function just because
    their data profile is isolated.
    """
    import ipaddress
    import socket

    def check(address):
        if not isinstance(address, tuple):
            return  # AF_UNIX paths are local strings/bytes, not IP tuples.
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="replace")
        try:
            local = ipaddress.ip_address(str(host)).is_loopback
        except ValueError:
            local = str(host).lower() == "localhost"
        if not local:
            raise RuntimeError("Offline regression blocked external connection")

    def protect(method, *, socket_method):
        if getattr(method, "_twobyte_offline_guard", False):
            return method
        if socket_method:
            def guarded(sock, address, *args, **kwargs):
                check(address)
                return method(sock, address, *args, **kwargs)
        else:
            def guarded(address, *args, **kwargs):
                # Block external names before create_connection performs DNS.
                check(address)
                return method(address, *args, **kwargs)
        guarded._twobyte_offline_guard = True
        return guarded

    socket.socket.connect = protect(socket.socket.connect, socket_method=True)
    socket.socket.connect_ex = protect(socket.socket.connect_ex, socket_method=True)
    socket.create_connection = protect(socket.create_connection, socket_method=False)


def real_local_app_data() -> Path | None:
    """The account's LocalAppData from the shell, ignoring environment overrides."""
    if os.name != 'nt':
        return None
    # SHGetKnownFolderPath expands %USERPROFILE% from this process's (isolated)
    # environment, so read the already-expanded shell folder, then the profile.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders') as key:
            value, _kind = winreg.QueryValueEx(key, 'Local AppData')
        if value and '%' not in value:
            return Path(value).resolve()
    except OSError:
        pass
    try:
        import ctypes
        from ctypes import wintypes
        token = wintypes.HANDLE()
        if not ctypes.windll.advapi32.OpenProcessToken(ctypes.windll.kernel32.GetCurrentProcess(), 0x0008,
                                                       ctypes.byref(token)):
            return None
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not ctypes.windll.userenv.GetUserProfileDirectoryW(token, buffer, ctypes.byref(size)):
                return None
            return (Path(buffer.value) / 'AppData' / 'Local').resolve()
        finally:
            ctypes.windll.kernel32.CloseHandle(token)
    except Exception:
        return None


def resolved_data_paths() -> dict[str, Path]:
    """Mutable data locations as the product resolves them in this process."""
    from . import runtime_paths
    paths = {'user_data_root': runtime_paths.user_data_root(), 'temp': Path(tempfile.gettempdir())}
    probes = (
        ('settings_root', 'twobyteasr.settings', 'stable_settings_root'),
        ('project_library', 'twobyteasr.studio_project', 'project_library_root'),
        ('studio_data', 'twobyteasr.studio_project', 'studio_data_root'),
        ('recognition_history_index', 'twobyteasr.recognition_history', 'default_history_index_path'),
        ('reports', 'twobyteasr.reporting', '_default_report_root'),
        ('secrets', 'twobyteasr.llm_config', 'secrets_path'),
        ('project_profiles', 'twobyteasr.project_profiles', 'project_profiles_path'),
        ('process_log', 'twobyteasr.process_diagnostics', 'process_log_path'),
        ('startup_trace', 'twobyteasr.startup_trace', '_trace_path'),
    )
    import importlib
    for name, module_name, attr in probes:
        try:
            paths[name] = Path(getattr(importlib.import_module(module_name), attr)())
        except Exception as exc:  # a broken resolver is reported, not hidden
            paths[name] = Path(f'<unresolved {type(exc).__name__}>')
    reporting = sys.modules.get('twobyteasr.reporting')
    if reporting is not None:
        paths['reporting.REPORT_ROOT'] = Path(reporting.REPORT_ROOT)
    legacy = sys.modules.get('subtitle_core')
    for attr in ('LEARNED_TERMS_PATH', 'PROFILE_HISTORY_PATH', 'HOST_VOICEPRINT_DIR', 'RUN_LOG_ROOT', 'CACHE_ROOT'):
        if legacy is not None and getattr(legacy, attr, None):
            paths[f'subtitle_core.{attr}'] = Path(getattr(legacy, attr))
    for key in ('LOCALAPPDATA', 'APPDATA', '2BYTEASR_USER_DATA_ROOT', 'USERPROFILE', 'HF_HOME'):
        if os.environ.get(key):
            paths[f'env.{key}'] = Path(os.environ[key])
    return paths


def require_isolated_paths(label: str = '', *, emit=print) -> dict[str, Path]:
    """Print every resolved mutable path and abort if one is real user data.

    For audits and evidence scripts: call after setting TWOBYTEASR_TEST_ROOT
    and importing twobyteasr, before any product work. Read-only model or
    media inputs are not mutable data and are not listed here.
    """
    root = isolation_root()
    if root is None:
        raise SystemExit('ISOLATION ABORT: TWOBYTEASR_TEST_ROOT is not set')
    real = real_local_app_data()
    real_data = real / '2ByteASR' if real else None
    paths = resolved_data_paths()
    leaks = []
    for name, path in paths.items():
        text = str(path)
        if text.startswith('<unresolved'):
            emit(f'ISOLATION {label} {name}={text}')
            continue
        resolved = path.resolve()
        emit(f'ISOLATION {label} {name}={resolved}')
        if real_data is not None and (resolved == real_data or resolved.is_relative_to(real_data)
                                      or (name.startswith('env.') and resolved == real)):
            leaks.append(f'{name}={resolved}')
        elif not resolved.is_relative_to(root):
            leaks.append(f'{name}={resolved} (outside {root})')
    if leaks:
        raise SystemExit('ISOLATION ABORT: ' + '; '.join(leaks))
    return paths


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
    _keep_icon_fonts_in_process()
    for folder in ('local', 'roaming', 'temp', 'config', 'qsettings'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    os.environ.update(LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'),
                      TEMP=str(root/'temp'), TMP=str(root/'temp'),
                      **{'2BYTEASR_USER_DATA_ROOT': str(root/'local')})
    tempfile.tempdir = str(root/'temp')
    # Do not discover the operator's Python/model caches via HOME or registry.
    for folder in ('profile', 'models', 'hf-cache', 'modelscope-cache', 'torch-cache'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    configured_models = os.environ.get('2BYTEASR_MODEL_ROOT', '').strip()
    model_root = root/'models'
    if configured_models:
        candidate = Path(configured_models).expanduser().resolve()
        if candidate.is_relative_to(root):
            model_root = candidate
    model_root.mkdir(parents=True, exist_ok=True)
    os.environ.update(USERPROFILE=str(root/'profile'), HF_HOME=str(root/'hf-cache'),
                      MODELSCOPE_CACHE=str(root/'modelscope-cache'), TORCH_HOME=str(root/'torch-cache'),
                      **{'2BYTEASR_MODEL_ROOT': str(model_root)})
    # SDKs often prefer their specific cache/token paths over HF_HOME. These
    # must be set before a spawned worker imports any Hub/Xet/Transformers code.
    os.environ.update(HOME=str(root/'profile'), XDG_CACHE_HOME=str(root/'xdg-cache'),
        HF_HUB_CACHE=str(root/'hf-cache/hub'), HUGGINGFACE_HUB_CACHE=str(root/'hf-cache/hub'),
        HF_XET_CACHE=str(root/'hf-cache/xet'), TRANSFORMERS_CACHE=str(root/'hf-cache/transformers'),
        HF_TOKEN_PATH=str(root/'hf-cache/absent-token'), NETRC=str(root/'profile/absent-netrc'),
        HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
    for key in tuple(os.environ):
        if key.upper() in {'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'MODELSCOPE_API_TOKEN'} or key.endswith(('_API_KEY', '_ACCESS_TOKEN', '_AUTH_TOKEN')):
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
