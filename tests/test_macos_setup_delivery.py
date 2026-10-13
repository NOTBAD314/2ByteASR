"""Delivery failure boundaries; fake native commands are not macOS acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import macos_package_dmg as dmg
from scripts import verify_blank_project_macos as blank


def built_app(root):
    app = root/'2ByteASR.app'
    (app/'Contents/MacOS').mkdir(parents=True)
    (app/'Contents/Resources').mkdir()
    (app/'Contents/MacOS/2ByteASR').write_bytes(b'owned fake bootloader')
    identity = dict(app_version=dmg.product_version(), git_sha='a'*40, source_sha256='b'*64,
                    source_file_count=42, build_channel='test', git_dirty=False)
    (app/'Contents/Resources/2byteasr_build.json').write_text(json.dumps(identity), 'utf8')
    return app


@pytest.mark.parametrize('tool', [dmg, blank])
def test_non_native_host_rejects_without_creating_deliverable(tmp_path, monkeypatch, tool):
    monkeypatch.setattr(sys, 'platform', 'win32')
    output = tmp_path/'tmp/not-created'
    with pytest.raises(SystemExit, match='Native Apple Silicon'):
        tool.main(['--app', str(tmp_path/'absent.app'), '--output', str(output)])
    assert not output.exists()


def test_app_metadata_disagreement_cannot_be_adopted_as_exact_source(tmp_path):
    app = built_app(tmp_path)
    other = app/'Contents/Frameworks'
    other.mkdir()
    (other/'2byteasr_build.json').write_text('{}', 'utf8')
    with pytest.raises(ValueError, match='disagree'):
        dmg.app_identity(app)


def test_disposable_output_rejects_user_install_path_and_existing_target(tmp_path):
    with pytest.raises(ValueError, match='tmp'):
        dmg.isolated_output(Path(tmp_path.anchor)/'Applications/2byte-audit-never-created')
    output = tmp_path/'tmp/existing'; output.mkdir(parents=True)
    with pytest.raises(ValueError, match='fresh'):
        dmg.isolated_output(output)


@pytest.mark.parametrize('failure', [None, 'installed-copy', 'source-drift', 'partial-attach', 'detach-failure'])
def test_dmg_delivery_preserves_archive_and_enforces_mount_cleanup(tmp_path, monkeypatch, failure):
    app = built_app(tmp_path/'build')
    original = dmg.inventory(app)
    output = tmp_path/'tmp/package'
    commands = []
    state = {'mounted': False}
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(dmg.platform, 'machine', lambda: 'arm64')
    # Windows test hosts may not permit symlink creation. Emulate only the
    # outer Applications link; the app inventory remains real file hashes.
    original_link = Path.is_symlink
    original_readlink = os.readlink
    monkeypatch.setattr(dmg.os, 'symlink', lambda target, link: Path(link).write_text(target))
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path.name == 'Applications' or original_link(path))
    monkeypatch.setattr(dmg.os, 'readlink', lambda path: '/Applications' if Path(path).name == 'Applications' else original_readlink(path))
    monkeypatch.setattr(dmg.os.path, 'ismount', lambda path: state['mounted'] and Path(path) == output/'mounted')

    def native_command(command, **kwargs):
        commands.append(command)
        code, stdout = 0, b''
        tool = Path(command[0]).name
        if tool == 'ditto':
            shutil.copytree(command[1], command[2])
            if 'installed' in Path(command[2]).parts:
                if failure == 'installed-copy':
                    code = 1
                elif failure == 'source-drift':
                    (app/'Contents/MacOS/2ByteASR').write_bytes(b'changed after image creation')
        elif tool == 'hdiutil' and command[1] == 'create':
            Path(command[-1]).write_bytes(b'owned simulated real artifact')
        elif tool == 'hdiutil' and command[1] == 'attach':
            state['mounted'] = True
            mount = Path(command[command.index('-mountpoint')+1])
            shutil.copytree(output/'image-root/2ByteASR.app', mount/'2ByteASR.app')
            (mount/'Applications').write_text('/Applications')
            stdout = plistlib.dumps({'system-entities': [{'mount-point': str(mount)}]})
            if failure == 'partial-attach':
                code = 1
        elif tool == 'hdiutil' and command[1] == 'detach':
            if failure == 'detach-failure':
                code = 1
            else:
                state['mounted'] = False
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=b'')

    monkeypatch.setattr(dmg.subprocess, 'run', native_command)
    assert dmg.main(['--app', str(app), '--output', str(output)]) == (1 if failure else 0)
    record = json.loads((output/'dmg-result.json').read_text('utf8'))
    assert record['passed'] is (failure is None)
    if failure:
        assert record.get('error') or record.get('detach_error')
    assert isinstance(record['artifact'], dict)
    assert (output/record['artifact']['file']).is_file()
    assert dmg.sha256(output/record['artifact']['file']) == record['artifact']['sha256']
    attach = next(cmd for cmd in commands if cmd[:2] == ['/usr/bin/hdiutil', 'attach'])
    assert '-readonly' in attach and '-nobrowse' in attach and '-noautoopen' in attach
    detach = [cmd for cmd in commands if cmd[:2] == ['/usr/bin/hdiutil', 'detach']]
    assert detach == [['/usr/bin/hdiutil', 'detach', str(output/'mounted')]]
    assert record['validation'].get('detached_normally', False) is (failure != 'detach-failure')
    assert record['real_applications_modified'] is False
    assert dmg.inventory(app) == original or failure == 'source-drift'
    assert state['mounted'] is (failure == 'detach-failure')


def test_normal_mac_launch_drops_host_keys_and_build_overrides(tmp_path, monkeypatch):
    for key, value in {'PATH': '/opt/homebrew/bin:/build/venv/bin',
                       'PYTHONPATH': '/host/private', 'TMPDIR': '/host/private-temp',
                       'DEEPSEEK_API_KEY': 'fake-host-secret',
                       'TWOBYTEASR_MAIN_PYTHON': '/host/venv/bin/python',
                       'TWOBYTEASR_MAC_SOURCE': '/host/source',
                       '2BYTEASR_USER_DATA_ROOT': '/host/private-data'}.items():
        monkeypatch.setenv(key, value)
    output = tmp_path/'tmp/blank'
    env = blank.blank_environment(output, tmp_path, output/'projects/guard.2byteproj')
    assert env['PATH'] == '/usr/bin:/bin:/usr/sbin:/sbin'
    assert not {'DEEPSEEK_API_KEY', 'PYTHONPATH', 'TWOBYTEASR_MAIN_PYTHON',
                'TWOBYTEASR_MAC_SOURCE', '2BYTEASR_USER_DATA_ROOT'} & env.keys()
    for key in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'TMPDIR'):
        assert Path(env[key]).is_relative_to(output)


@pytest.mark.parametrize('bad_outcome', ['back-return', 'shutdown', 'process-exit', 'identity'])
def test_blank_controls_or_exit_failure_never_becomes_passed(tmp_path, monkeypatch, bad_outcome):
    app = built_app(tmp_path/'installed')
    output = tmp_path/'tmp/blank'
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(blank.platform, 'machine', lambda: 'arm64')
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path/'tmp/prior'))
    isolation = ModuleType('twobyteasr.test_isolation'); isolation.install = lambda: None
    project = ModuleType('twobyteasr.studio_project')
    project.StudioMedia = lambda **kw: kw
    project.SubtitleProject = lambda **kw: kw
    project.save_project = lambda value, path: path.write_text('{}', 'utf8')
    monkeypatch.setitem(sys.modules, isolation.__name__, isolation)
    monkeypatch.setitem(sys.modules, project.__name__, project)
    executable = app/'Contents/MacOS/2ByteASR'
    identity = dict(packaged=True, executable_path=str(executable), git_sha='a'*40,
                    source_sha256='b'*64, source_file_count=42)
    checks = [{'name': f'control-{index}', 'passed': True} for index in range(36)]
    result = dict(passed=True, gui_shutdown=True, provider_calls=0, checks=checks,
                  external_connections_blocked=[], identity=identity, executable=str(executable))
    if bad_outcome == 'back-return':
        checks[20] = dict(name='ordinary back returns to project library', passed=False)
    if bad_outcome == 'shutdown':
        result['gui_shutdown'] = False
    if bad_outcome == 'identity':
        identity['executable_path'] = '/other/app/Contents/MacOS/2ByteASR'

    class Process:
        pid = 42
        returncode = 1 if bad_outcome == 'process-exit' else 0

        def __init__(self, command, **kwargs):
            assert command == [str(executable)] and kwargs['start_new_session'] is True
            (output/'result.json').write_text(json.dumps(result), 'utf8')

        def wait(self, timeout):
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(blank.subprocess, 'Popen', Process)
    assert blank.main(['--app', str(app), '--output', str(output)]) == 1
    summary = json.loads((output/'blank-project-summary.json').read_text('utf8'))
    assert summary['passed'] is False
    assert summary['application_result'] == result
    assert summary['identity'] == identity
    assert summary['normal_exit'] is (bad_outcome != 'process-exit')
