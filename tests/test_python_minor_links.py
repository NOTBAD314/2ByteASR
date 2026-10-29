"""uv python install with minor-version links that cannot be replaced in place, and "in use" retries (2026-10-21).

On one PC Windows reported folders under the data folder as in use (os error 32) whenever uv deleted them: every
`uv python install` failed re-creating cpython-3.10-windows-x86_64-none and left an empty folder in its place. The
installers now remove the links first and let uv create them, and retry a uv command that failed only because of
os error 32. No network: real junctions in a temporary folder, a fake uv, and the PowerShell functions run as-is.
"""
import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_runtime_download_fallback import ROOT, FakeUv, installer, run_installer, table_freeze  # noqa: F401

windows_only = pytest.mark.skipif(os.name != 'nt', reason='junctions are Windows only')


def junction(target, link):
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def is_junction(path):
    return os.path.lexists(path) and bool(os.lstat(path).st_file_attributes & 0x400)


def python_folder(tmp_path):
    """A uv install dir: a full-version folder with a file, its minor link, a leftover empty folder, a kept folder."""
    folder = tmp_path / 'python'
    full = folder / 'cpython-3.10.19-windows-x86_64-none'
    full.mkdir(parents=True)
    (full / 'python.exe').write_bytes(b'interpreter stays')
    junction(full, folder / 'cpython-3.10-windows-x86_64-none')
    (folder / 'cpython-3.12-windows-x86_64-none').mkdir()  # what a failed re-creation leaves behind
    kept = folder / 'cpython-3.11-windows-x86_64-none'
    kept.mkdir()
    (kept / 'keep.txt').write_text('not a link, not empty')
    return folder, full


def test_python_install_dir_only_for_python_install():
    assert installer.python_install_dir(['uv', '--no-config', 'python', 'install', '3.10.19', '--install-dir', 'X',
                                         '--no-bin']) == Path('X')
    assert installer.python_install_dir(['uv', 'pip', 'install', '--python', 'p', 'torch']) is None
    assert installer.python_install_dir(['uv', 'venv', '--python', 'p', 'X']) is None


@windows_only
def test_minor_links_are_removed_without_touching_targets_and_restored(tmp_path):
    folder, full = python_folder(tmp_path)
    removed = installer.remove_minor_version_links(folder)
    assert list(removed) == [folder / 'cpython-3.10-windows-x86_64-none']
    assert not os.path.lexists(folder / 'cpython-3.10-windows-x86_64-none')
    assert not os.path.lexists(folder / 'cpython-3.12-windows-x86_64-none')  # empty leftover cleared
    assert (folder / 'cpython-3.11-windows-x86_64-none' / 'keep.txt').is_file()  # a real folder is left alone
    assert (full / 'python.exe').read_bytes() == b'interpreter stays'
    installer.restore_minor_version_links(removed)
    link = folder / 'cpython-3.10-windows-x86_64-none'
    assert is_junction(link) and (link / 'python.exe').read_bytes() == b'interpreter stays'
    installer.restore_minor_version_links(removed)  # already back: nothing to do
    assert installer.remove_minor_version_links(tmp_path / 'missing') == {}


def test_only_in_use_failures_are_retried(monkeypatch):
    waits = []
    monkeypatch.setattr(installer.time, 'sleep', waits.append)
    calls = []

    def flaky(outputs):
        def call():
            calls.append(1)
            output = outputs.pop(0)
            if output is None:
                return 'done'
            raise subprocess.CalledProcessError(2, ['uv'], output=output)
        return call

    in_use = 'error: failed to remove directory `x`: 另一个程序正在使用此文件，进程无法访问。 (os error 32)\n'
    assert installer.retry_when_in_use(flaky([in_use, in_use, None]), 'step') == 'done'
    assert waits == list(installer.IN_USE_WAITS_S[:2])
    waits.clear()
    with pytest.raises(subprocess.CalledProcessError):
        installer.retry_when_in_use(flaky(['error: No solution found\n']), 'step')
    assert waits == []
    with pytest.raises(subprocess.CalledProcessError):
        installer.retry_when_in_use(flaky([in_use] * (len(installer.IN_USE_WAITS_S) + 1)), 'step')
    assert waits == list(installer.IN_USE_WAITS_S)


def test_installer_retries_an_in_use_python_install(run_installer, monkeypatch, capsys):
    monkeypatch.setattr(installer.time, 'sleep', lambda seconds: None)
    original = FakeUv.popen
    state = {'python_installs': 0}

    def popen(self, arguments, **kwargs):
        if 'python' in arguments and 'install' in arguments and 'pip' not in arguments:
            state['python_installs'] += 1
            if state['python_installs'] == 1:
                self.commands.append(arguments)
                output = 'error: Failed to create Python minor version link directory\n  Caused by: (os error 32)\n'
                return type('Process', (), {'stdout': io.StringIO(output), 'pid': 123456, 'returncode': 2,
                                            'poll': lambda self: 2, 'wait': lambda self, timeout=None: 2})()
        return original(self, arguments, **kwargs)
    monkeypatch.setattr(FakeUv, 'popen', popen)
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'))
    python_installs = [c for c in fake.commands if 'python' in c and 'install' in c and 'pip' not in c]
    assert len(python_installs) == 2 and '--mirror' not in python_installs[1]  # same source again, not the next
    assert '正在被使用' in capsys.readouterr().out


def powershell_functions():
    script = (ROOT / 'scripts/setup_managed_backend.ps1').read_text('utf-8-sig')
    start = script.index('function Remove-MinorVersionLinks')
    return script[start:script.index('function Invoke-PythonInstall')]


def test_powershell_python_install_removes_links_first_and_retries_in_use_only():
    script = (ROOT / 'scripts/setup_managed_backend.ps1').read_text('utf-8-sig')
    install = script[script.index('function Install-ManagedPython'):script.index('$guard=$null')]
    assert 'Invoke-PythonInstall ($arguments+$extra)' in install and 'RunUv' not in install
    invoke = script[script.index('function Invoke-PythonInstall'):script.index('function Install-ManagedPython')]
    assert invoke.index('Remove-MinorVersionLinks') < invoke.index('RunUv $arguments')
    assert 'finally { Restore-MinorVersionLinks $links }' in invoke
    assert "if ($line -match '\\(os error 32\\)') { $script:inUseSeen=$true }" in script


@windows_only
def test_powershell_link_functions_on_real_junctions(tmp_path):
    folder, full = python_folder(tmp_path)
    test = tmp_path / 'links.ps1'
    test.write_text(powershell_functions() + f'''
$removed = Remove-MinorVersionLinks '{folder}'
Write-Output ('removed=' + (@($removed.Keys | ForEach-Object {{ Split-Path $_ -Leaf }}) -join ','))
Write-Output ('gone=' + (-not (Test-Path -LiteralPath '{folder}\\cpython-3.10-windows-x86_64-none')))
Restore-MinorVersionLinks $removed
''', encoding='utf-8-sig')
    done = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(test)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'removed=cpython-3.10-windows-x86_64-none' in done.stdout and 'gone=True' in done.stdout
    assert not os.path.lexists(folder / 'cpython-3.12-windows-x86_64-none')
    assert (folder / 'cpython-3.11-windows-x86_64-none' / 'keep.txt').is_file()
    link = folder / 'cpython-3.10-windows-x86_64-none'
    assert is_junction(link) and (link / 'python.exe').read_bytes() == b'interpreter stays'
    assert (full / 'python.exe').read_bytes() == b'interpreter stays'
