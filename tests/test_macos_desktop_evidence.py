# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.macos_desktop_evidence import (preserve_owned_project, studio_snapshot,
                                            image_colour_observation)


def test_preview_measure_rejects_black_canvas_despite_coloured_bottom_handles():
    from PySide6.QtGui import QImage, QColor, QPainter
    raster = QImage(180, 120, QImage.Format_ARGB32_Premultiplied)
    raster.fill(QColor('black'))
    painter = QPainter(raster)
    painter.fillRect(0, 90, 180, 30, QColor('magenta')); painter.end()
    assert image_colour_observation(raster)['colour_fraction'] == 0
    raster.fill(QColor('green'))
    assert image_colour_observation(raster)['colour_fraction'] == 1


def test_preview_requires_composed_pixels_even_when_decoder_is_ready(tmp_path):
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtWidgets import QApplication, QWidget, QLabel
    from twobyteasr.studio_qt_preview import QtEmbeddedVideoController
    from twobyteasr.macos_desktop_evidence import preserve_studio_preview
    app = QApplication.instance() or QApplication([])
    canvas = QWidget(); canvas.resize(180, 120)
    controller = QtEmbeddedVideoController(canvas); controller.start()
    canvas.controller = controller
    controller.surface.frame = QImage(180, 120, QImage.Format_ARGB32_Premultiplied)
    controller.surface.frame.fill(QColor('green'))
    cover = QLabel(canvas); cover.setGeometry(canvas.rect())
    cover.setStyleSheet('background: black'); cover.show(); cover.raise_()
    canvas.show(); app.processEvents()
    page = SimpleNamespace(video=canvas)
    try:
        blocked = preserve_studio_preview(page, tmp_path, 'ready')
        assert blocked['decoded']['colour_fraction'] == 1
        assert blocked['composed']['colour_fraction'] == 0
        assert not blocked['passed']
        cover.hide(); app.processEvents()
        visible = preserve_studio_preview(page, tmp_path, 'reopened')
        assert visible['passed']
        assert (tmp_path/'preview-ready.json').is_file()
        assert (tmp_path/'preview-reopened-composed.png').is_file()
    finally:
        controller.close(); canvas.close(); app.processEvents()


def test_actual_transform_child_preserves_qt_video_under_show_update_and_hide():
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.studio_qt_preview import QtEmbeddedVideoController
    from twobyteasr.studio_position_overlay import SubtitlePositionOverlay
    app = QApplication.instance() or QApplication([])
    canvas = QWidget(); canvas.resize(320, 240); canvas.setStyleSheet('background: black')
    controller = QtEmbeddedVideoController(canvas); controller.start()
    canvas.controller = controller
    controller.surface.frame = QImage(320, 180, QImage.Format_ARGB32_Premultiplied)
    controller.surface.frame.fill(QColor('green'))
    canvas.show(); app.processEvents()
    baseline = image_colour_observation(canvas.grab().toImage())['colour_fraction']
    overlay = SubtitlePositionOverlay(canvas); overlay.sync_to_video(canvas)
    try:
        overlay.show(); app.processEvents()
        assert image_colour_observation(canvas.grab().toImage())['colour_fraction'] > baseline-.02
        overlay.set_video_position(600, 700, 1920, 1080); overlay.update(); app.processEvents()
        assert image_colour_observation(canvas.grab().toImage())['colour_fraction'] > baseline-.02
        overlay.hide(); app.processEvents()
        assert image_colour_observation(canvas.grab().toImage())['colour_fraction'] == baseline
        # The Windows native-mpv clearing branch remains unchanged.
        controller.backend = 'native-mpv-fixture'
        overlay.show(); app.processEvents()
        native_overlay = canvas.grab().toImage()
        assert native_overlay.pixelColor(5, 40).red() == 0
        assert native_overlay.pixelColor(5, 40).green() == 0
        assert native_overlay.pixelColor(5, 40).blue() == 0
        assert image_colour_observation(native_overlay)['colour_fraction'] < .05  # visible handles only
    finally:
        controller.close(); canvas.close(); app.processEvents()
from scripts.macos_collect_artifacts import selected_files


def test_paused_native_frame_survives_stdout_backpressure_and_heartbeats(tmp_path):
    import os, queue, shutil, struct, subprocess, sys, threading, time
    from twobyteasr.platform_media import ffmpeg_tool
    from twobyteasr.video_decode_pipe import _read_exact
    ffmpeg = ffmpeg_tool()
    if not ffmpeg.is_file():
        available = shutil.which('ffmpeg')
        if not available:
            pytest.skip('native FFmpeg required for owned video fixture')
        ffmpeg = Path(available)
    media = tmp_path/'帧队列.mp4'
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=s=640x360:r=30:d=2', '-c:v', 'libx264', str(media)],
                   check=True, capture_output=True, timeout=20)
    child = subprocess.Popen([sys.executable, '-c',
                              'from twobyteasr.video_decode_worker import main; main()'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(os.environ, TWOBYTEASR_VIDEO_DECODE_BACKEND='cpu'))
    first_header, release, frames = threading.Event(), threading.Event(), queue.Queue()
    def receive():
        try:
            first = True
            while True:
                size = struct.unpack('!I', _read_exact(child.stdout, 4))[0]
                header = json.loads(_read_exact(child.stdout, size))
                if first and header.get('pixel_bytes'):
                    first = False
                    first_header.set()
                    release.wait(5)  # Hold the old raster in the writer's real pipe.
                _read_exact(child.stdout, header.get('pixel_bytes', 0))
                frames.put(header)
        except (EOFError, OSError):
            pass
    def demand(epoch, milliseconds):
        payload = dict(epoch=epoch, path=str(media), source_ms=milliseconds,
                       generation=epoch, paused=True, rate=1, max_size=[640, 360])
        child.stdin.write((json.dumps(payload)+'\n').encode('utf8')); child.stdin.flush()
    receiver = threading.Thread(target=receive, daemon=True)
    receiver.start()
    try:
        demand(1, 0)
        assert first_header.wait(5), 'production worker did not decode first frame'
        demand(2, 466)
        time.sleep(1.2)  # At least two heartbeat opportunities before pipe draining.
        release.set()
        deadline = time.monotonic()+3
        current = None
        while time.monotonic() < deadline:
            try:
                header = frames.get(timeout=.1)
            except queue.Empty:
                continue
            if header.get('pixel_bytes') and header['epoch'] == 2:
                current = header; break
        assert current is not None, 'heartbeat replaced the final paused raster'
        assert abs(current['pts_ms']-466) <= 50
        assert current['generation'] == 2
    finally:
        release.set(); child.kill(); child.wait(timeout=3); receiver.join(timeout=2)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


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
