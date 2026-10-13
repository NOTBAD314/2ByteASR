"""Keep every test run away from the operator's real 2ByteASR data.

Plain ``pytest`` used to resolve %LOCALAPPDATA%\\2ByteASR like the app does,
so tests appended fixture rows to the real logs, rewrote settings/glossaries
and read the DPAPI-protected API keys. The redirect below runs when pytest
imports this file, before any test module (and so before module-level path
constants such as ``subtitle_core.LEARNED_TERMS_PATH``) is imported.

It reuses the app's own opt-in boundary (``TWOBYTEASR_TEST_ROOT`` +
``twobyteasr.test_isolation.install``): LOCALAPPDATA, APPDATA, TEMP,
USERPROFILE, ``2BYTEASR_USER_DATA_ROOT``, the model root and QSettings all
point into a fresh ``tmp/pytest-user-data/user-data-N`` (the last few runs are
kept) and ``*_API_KEY`` variables are dropped, so no saved key is visible.
Runners that already set ``TWOBYTEASR_TEST_ROOT`` keep their own root.
``grok``/``codex``/``agy`` on PATH resolve to failing fakes in that root.
qtawesome loads its icon fonts privately instead of registering them with
Windows through the same boundary used by source/frozen audits. Python TCP
connections are restricted to loopback in both pytest entries; Qt/native
subprocess networking is outside this Python guard.

An audit hook then refuses, and fails the test for, any file access under the
real user-data folders and any launch of a real account CLI. Tests that need
a credential must supply a fixture value themselves.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_DATA_FOLDERS = ("2ByteASR", "QwenASR")  # QwenASR: pre-rename store, still migrated from
ACCOUNT_CLIS = frozenset({"grok", "codex", "agy", "antigravity"})
_RETAINED_ROOTS = 3


def _real_local_app_data_dirs():
    """Every spelling of the real LocalAppData, captured before redirecting."""
    found = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                found.append(winreg.QueryValueEx(key, "Local AppData")[0])
        except OSError:
            pass
        found.append(os.environ.get("LOCALAPPDATA", ""))
        found.append(os.path.join(os.path.expanduser("~"), "AppData", "Local"))
    elif sys.platform == "darwin":
        found.append(os.path.join(os.path.expanduser("~"), "Library", "Application Support"))
    return [Path(item) for item in found if item]


def _new_isolation_root() -> Path:
    # Same place as scripts/isolated_pytest.py: some tests require tmp_path
    # (which follows TEMP into the root) to sit under the repository's tmp/.
    parent = ROOT / "tmp" / "pytest-user-data"
    parent.mkdir(parents=True, exist_ok=True)
    try:
        import atexit
        from _pytest.pathlib import LOCK_TIMEOUT, make_numbered_dir_with_cleanup
        # Same retention as pytest's own tmp_path: the last few runs survive.
        return make_numbered_dir_with_cleanup(root=parent, prefix="user-data-", mode=0o700,
                                              keep=_RETAINED_ROOTS, lock_timeout=LOCK_TIMEOUT,
                                              register=atexit.register)
    except (ImportError, TypeError):
        return Path(tempfile.mkdtemp(prefix="user-data-", dir=parent))


def _install_isolation():
    if "twobyteasr" in sys.modules and not os.environ.get("TWOBYTEASR_TEST_ROOT"):
        raise RuntimeError("twobyteasr was imported before tests/conftest.py could isolate user data")
    real = _real_local_app_data_dirs()
    if not os.environ.get("TWOBYTEASR_TEST_ROOT"):
        os.environ["TWOBYTEASR_TEST_ROOT"] = str(_new_isolation_root())
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from twobyteasr.test_isolation import install, isolation_root, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    root = isolation_root()
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        pass
    else:
        # Qt's own (C++) QSettings would otherwise default to the registry.
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root / "qsettings"))
    protected = []
    for base in real:
        for folder in APP_DATA_FOLDERS:
            path = os.path.normcase(os.path.abspath(base / folder))
            if path not in protected and not Path(path).is_relative_to(os.path.normcase(str(root))):
                protected.append(path)
    return root, tuple(protected)


ISOLATION_ROOT, PROTECTED_DIRS = _install_isolation()
FAKE_CLI_DIR = ISOLATION_ROOT / "fake-account-cli"


def _use_fake_account_clis():
    """Showing a Studio page probes the selected AI CLI; it must find a fake, not the operator's login."""
    FAKE_CLI_DIR.mkdir(exist_ok=True)
    for name in sorted(ACCOUNT_CLIS):
        if os.name == "nt":
            (FAKE_CLI_DIR / f"{name}.cmd").write_text(
                "@echo off\r\necho %~n0: 2ByteASR test fake, no account CLI in tests 1>&2\r\nexit /b 1\r\n",
                encoding="ascii")
        else:
            script = FAKE_CLI_DIR / name
            script.write_text('#!/bin/sh\necho "${0##*/}: 2ByteASR test fake, no account CLI in tests" >&2\nexit 1\n')
            script.chmod(0o755)
    entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    if os.name == "nt":
        # Discovery asks for "codex.exe"/"agy.exe" before bare names, so a real
        # .exe later on PATH would still beat the .cmd fakes.
        entries = [entry for entry in entries
                   if not any(os.path.isfile(os.path.join(entry, f"{name}.exe")) for name in ACCOUNT_CLIS)]
    os.environ["PATH"] = os.pathsep.join([str(FAKE_CLI_DIR), *entries])


_use_fake_account_clis()


# Fake CLIs written by tests live in tmp_path (inside the root unless --basetemp moves it).
_SAFE_EXECUTABLE_DIRS = [os.path.normcase(str(ISOLATION_ROOT)), os.path.normcase(str(ROOT / "tmp"))]
GUARD_VIOLATIONS = []

_PATH_EVENTS = {
    "open": 1, "os.listdir": 1, "os.scandir": 1, "os.mkdir": 1, "os.remove": 1, "os.rmdir": 1,
    "os.truncate": 1, "os.chmod": 1, "os.utime": 1, "shutil.rmtree": 1,
    "os.rename": 2, "os.replace": 2, "os.link": 2, "os.symlink": 2,
    "shutil.copyfile": 2, "shutil.copytree": 2, "shutil.move": 2,
}


def _under(path, roots):
    if isinstance(path, int) or path is None:
        return False
    try:
        text = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    except (TypeError, ValueError):
        return False
    return any(text == root or text.startswith(root + os.sep) for root in roots)


def _launched_programs(executable, args):
    """Program names in a Popen call; Windows passes one command-line string."""
    if executable is not None:
        yield os.fsdecode(executable)
    if isinstance(args, (str, bytes)):
        import shlex
        try:
            words = [word.strip('"') for word in shlex.split(os.fsdecode(args), posix=False)]
        except ValueError:
            words = os.fsdecode(args).split()
    else:
        words = [os.fsdecode(word) for word in (args or ())]
    if not words:
        return
    yield words[0]
    if Path(words[0]).stem.lower() in {"cmd", "powershell", "pwsh", "sh", "bash"}:
        # Shell launches (cmd /c "...") are rare here; check every following word.
        yield from words[1:]


def _account_cli(executable, args):
    import shutil
    try:
        programs = [program for program in _launched_programs(executable, args) if program]
    except (TypeError, ValueError):
        return None
    for program in programs:
        if Path(program).stem.lower() not in ACCOUNT_CLIS:
            continue
        resolved = program if os.path.dirname(program) else shutil.which(program) or program
        # A made-up path (e.g. C:\tools\agy.exe in a unit test) cannot start anything.
        if os.path.isfile(resolved) and not _under(resolved, _SAFE_EXECUTABLE_DIRS):
            return resolved
    return None


def _guard(event, args):
    count = _PATH_EVENTS.get(event)
    if count:
        for path in args[:count]:
            if _under(path, PROTECTED_DIRS):
                message = f"test touched real user data: {event} {os.fsdecode(path)}"
                break
        else:
            return
    elif event == "subprocess.Popen":
        program = _account_cli(args[0], args[1])
        if program is None:
            return
        message = f"test launched a real account CLI: {program}"
    else:
        return
    GUARD_VIOLATIONS.append((os.environ.get("PYTEST_CURRENT_TEST", "<collection>"), message))
    raise PermissionError(message)


sys.addaudithook(_guard)


@pytest.fixture(scope="session", autouse=True)
def isolated_user_data_root():
    """The temp root standing in for %LOCALAPPDATA% during this session."""
    for name in ("2BYTEASR_USER_DATA_ROOT", "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        assert Path(os.environ[name]).resolve().is_relative_to(ISOLATION_ROOT), name
    yield ISOLATION_ROOT


_SEEN_VIOLATIONS = pytest.StashKey[int]()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    item.stash[_SEEN_VIOLATIONS] = len(GUARD_VIOLATIONS)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # App code often swallows OSError; a blocked access must still fail the test.
    report = (yield).get_result()
    seen = item.stash.get(_SEEN_VIOLATIONS, len(GUARD_VIOLATIONS))
    item.stash[_SEEN_VIOLATIONS] = len(GUARD_VIOLATIONS)
    if report.passed and len(GUARD_VIOLATIONS) > seen:
        report.outcome = "failed"
        report.longrepr = "\n".join(message for _test, message in GUARD_VIOLATIONS[seen:])


def pytest_configure(config):
    if config.option.basetemp:
        _SAFE_EXECUTABLE_DIRS.append(os.path.normcase(os.path.abspath(config.option.basetemp)))


def pytest_report_header(config):
    return f"2ByteASR user data isolated in {ISOLATION_ROOT}"


def pytest_terminal_summary(terminalreporter):
    if GUARD_VIOLATIONS:
        terminalreporter.section("real user data / account CLI access blocked")
        for test, message in GUARD_VIOLATIONS:
            terminalreporter.line(f"{test}: {message}")
