# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.macos_desktop_evidence import preserve_owned_project, studio_snapshot
from scripts.macos_collect_artifacts import selected_files


@pytest.mark.parametrize('windows', [False, True])
def test_export_workspace_probes_tool_from_relocated_install_root(tmp_path, monkeypatch, windows):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from twobyteasr import platform_media, runtime_paths, studio_export_ui, studio_render
    from twobyteasr.studio_project import StudioMedia, SubtitleProject
    app = QApplication.instance() or QApplication([])
    install = tmp_path/'兔白 移動.app/Contents/Frameworks'
    executable = install/'tools/ffmpeg/bin'/('ffmpeg.exe' if windows else 'ffmpeg')
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'owned probe fixture')
    monkeypatch.setattr(runtime_paths, 'get_runtime_paths', lambda: SimpleNamespace(install_root=install))
    native_name = platform_media.executable_name
    monkeypatch.setattr(platform_media, 'executable_name', lambda name: native_name(name, windows=windows))
    settings = QSettings(str(tmp_path/'settings.ini'), QSettings.IniFormat)
    monkeypatch.setattr(studio_export_ui, 'QSettings', lambda *args: settings)
    monkeypatch.setattr(studio_export_ui, 'load_user_presets', lambda: [])
    monkeypatch.setattr(studio_render, 'load_encoder_capabilities', lambda path: None)
    seen = []
    def encoders(path):
        assert Path(path) == executable and Path(path).is_file()
        seen.append(Path(path))
        return {'libx264'}
    monkeypatch.setattr(studio_render, 'available_encoders', encoders)
    monkeypatch.setattr(studio_render, 'probe_encoder', lambda *args: True)
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path/'video.mp4'), duration_ms=1000))
    workspace = studio_export_ui.StudioExportWorkspace(project, str(tmp_path/'preview.ass'))
    try:
        assert workspace.ffmpeg == executable
        assert seen and all(path == executable for path in seen)
        assert workspace.preset.findData('recommended') >= 0
    finally:
        workspace.close(); workspace.deleteLater(); app.processEvents()


@pytest.mark.parametrize('role', ['audio', 'video'])
def test_frozen_native_worker_dispatch_precedes_inherited_gui_audit(monkeypatch, tmp_path, role):
    import sys
    from PySide6 import QtWidgets
    from scripts import macos_launch as launch
    from twobyteasr import platform_macos, runtime_paths, settings, studio_acceptance_audit
    seen = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(sys, 'argv', ['App', '--studio-'+role+'-worker', 'owned-argument'])
    monkeypatch.setenv('TWOBYTEASR_ACCEPTANCE_SCENARIO', 'macos-desktop')
    monkeypatch.setattr(platform_macos, 'configure_macos_paths', lambda root: seen.append('resources'))
    monkeypatch.setattr(runtime_paths, 'user_data_root', lambda: tmp_path/'tmp/profile')
    monkeypatch.setattr(studio_acceptance_audit, 'audit_directory', lambda: tmp_path/'tmp/profile')
    def forbidden(*args, **kwargs):
        raise AssertionError('A native worker must not enter GUI audit/default setup')
    monkeypatch.setattr(QtWidgets, 'QApplication', forbidden)
    monkeypatch.setattr(settings, 'project_settings_path', forbidden)
    def worker(*args):
        seen.append(('worker', args)); return 17
    module = 'twobyteasr.audio_process' if role == 'audio' else 'twobyteasr.video_decode_worker'
    monkeypatch.setitem(sys.modules, module, SimpleNamespace(main=worker))
    assert launch.main() == 17
    assert seen == ['resources', ('worker', (['owned-argument'],) if role == 'audio' else ())]


def test_failure_snapshot_retains_real_substage_and_endpoint_error():
    page = SimpleNamespace(
        _readiness=SimpleNamespace(active=False, ready=False, completed={'读取工程'},
                                  profile={'error': {'stage': '准备音频', 'message': 'endpoint exited'}}),
        project=SimpleNamespace(project_id='owned'),
        video=SimpleNamespace(_startup_state='READY'),
        audio_engine=SimpleNamespace(telemetry_snapshot=lambda: {'state': 'ENDPOINT_FAILED'}),
        _playback_buffers_ready=lambda: False,
    )
    result = studio_snapshot(page)
    assert result['readiness']['profile']['error']['stage'] == '准备音频'
    assert result['readiness']['completed'] == ['读取工程']
    assert result['audio']['state'] == 'ENDPOINT_FAILED'
    assert result['playback_buffers_ready'] is False
    json.dumps(result)


def test_original_project_bytes_are_preserved_but_profile_and_other_projects_are_excluded(tmp_path):
    root = tmp_path/'tmp/qa'
    output = root/'desktop-flow'
    project = output/'projects/中文/中文.2byteproj'
    project.parent.mkdir(parents=True)
    payload = '{"cues":[{"text":"实际识别原件"}]}'.encode('utf8')
    project.write_bytes(payload)
    record = preserve_owned_project(project, output, 'recognized')
    assert Path(record['path']).read_bytes() == payload
    private = output/'local/private.2byteproj'
    private.parent.mkdir(); private.write_bytes(payload)
    with pytest.raises(ValueError): preserve_owned_project(private, output, 'final')
    unrelated = output/'owned-projects/other.2byteproj'
    unrelated.write_bytes(payload)
    assert [p.relative_to(root).as_posix() for p in selected_files(root)] == [
        'desktop-flow/owned-projects/recognized.2byteproj']
