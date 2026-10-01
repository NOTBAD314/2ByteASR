# SPDX-License-Identifier: GPL-3.0-only
"""Headed real-frame probe of the production embedded Qt canvas.

Actual host is recorded. A Windows Qt run is never native macOS evidence.
This is a video/transport/compositor gate, not ASR or listening acceptance.
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def main(output: str) -> int:
    folder = Path(output).resolve()
    if folder.exists():
        raise RuntimeError('Choose a new embedded-media-smoke output.')
    boundary = Path(os.environ.get('TWOBYTEASR_TEST_ROOT', folder)).resolve()
    if 'tmp' not in {part.casefold() for part in boundary.parts} or not folder.is_relative_to(boundary):
        raise RuntimeError('Media smoke requires an owned tmp test boundary.')
    folder.mkdir(parents=True)
    os.environ.setdefault('TWOBYTEASR_TEST_ROOT', str(boundary))
    from .test_isolation import install
    install()
    from PySide6.QtCore import QEventLoop, Qt, QRect
    from PySide6.QtGui import QImage, QColor, QFontDatabase, QKeySequence, QShortcut
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
    from .platform_media import ffmpeg_tool
    from .studio_video_canvas import MpvCanvas
    from .studio_qt_preview import QtEmbeddedVideoController
    from .studio_shortcuts import studio_default_shortcuts

    receipt = {'platform': sys.platform, 'architecture': platform.machine(),
               'packaged': bool(getattr(sys, 'frozen', False)), 'backend': 'qt-video-sink',
               'native_macos_evidence': sys.platform == 'darwin',
               'audio_listening_verified': False, 'pcm_audio_owner_verified': False,
               'studio_full_flow_verified': False, 'checks': {}}
    checks = receipt['checks']
    def check(name, passed, *, required=True, **details):
        checks[name] = {'passed': bool(passed), **details}
        if not passed and required:
            raise AssertionError(name)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(QEventLoop.AllEvents, 20)
            QTest.qWait(10)
    def wait(predicate, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(QEventLoop.AllEvents, 20)
            if predicate():
                return True
            QTest.qWait(10)
        return bool(predicate())
    def pixels(image):
        copy = image.convertToFormat(QImage.Format_RGBA8888)
        return hashlib.sha256(bytes(copy.constBits())).hexdigest()
    window = QWidget()
    window.setWindowTitle('2ByteASR — owned embedded preview verification')
    layout = QVBoxLayout(window)
    canvas = MpvCanvas(window)
    editor = QLineEdit(window)
    editor.setPlaceholderText('Owned focus fixture')
    layout.addWidget(canvas)
    layout.addWidget(editor)
    window.resize(660, 450)
    controller = QtEmbeddedVideoController(canvas)
    canvas.controller = controller
    errors = []
    canvas.error.connect(errors.append)
    controller.start()
    window.show()
    window.raise_()
    window.activateWindow()
    pump(.15)
    try:
        media = folder/'owned-中文-test-pattern.mp4'
        with (folder/'ffmpeg.log').open('wb') as log:
            result = subprocess.run([str(ffmpeg_tool()), '-v', 'warning', '-f', 'lavfi', '-i',
                'testsrc2=s=320x180:r=25:d=4', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(media)],
                stdout=log, stderr=subprocess.STDOUT, timeout=30)
        check('legal_owned_encoded_av_fixture', result.returncode == 0,
              source='FFmpeg lavfi testsrc2 + synthetic 440Hz sine; no private media',
              sha256=hashlib.sha256(media.read_bytes()).hexdigest() if media.exists() else None)
        canvas.load(str(media))
        canvas.set_paused(True)
        check('real_first_frame', wait(lambda: controller._frame_sequence > 0),
              error=controller.actor_status()['last_error'])
        pump(.25)
        check('initial_requested_pause_applied', wait(lambda: canvas._startup_state == 'READY'
              and controller.observed_property('pause') and not controller._seek_pending))
        check('embedded_child_painted', controller.surface.parentWidget() is canvas
              and not controller.surface.isWindow() and controller.surface.painted_frames > 0,
              visible_top_level_types=[type(w).__name__ for w in app.topLevelWidgets() if w.isVisible()],
              painted_frames=controller.surface.painted_frames)
        check('video_backend_has_no_audio_output', controller.player.audioOutput() is None,
              meaning='Only video ownership proven; PCM output/listening remains a separate gate')
        first_hash = pixels(controller.surface.frame)
        canvas.seek(1.2)
        check('paused_seek_real_target_frame', wait(lambda: not controller.observed_property('seeking')
              and abs(float(controller.observed_property('video-frame-info', {}).get('pts', -1))-1.2)<.085),
              applied=controller.applied_seek_state(), observed=controller.observed_position())
        pump(.15)
        check('seek_changes_actual_pixels', first_hash != pixels(controller.surface.frame))
        canvas.set_paused(True)
        pump(.15)
        check('pause_transition_completes', wait(lambda: not controller.observed_property('seeking')
              and controller.observed_property('pause')))
        paused_position = controller.player.position()
        paused_sequence = controller._frame_sequence
        pump(.35)
        check('pause_holds_transport_and_pixels', abs(controller.player.position()-paused_position)<=40
              and controller._frame_sequence == paused_sequence,
              position_ms=controller.player.position(), frame_sequence=controller._frame_sequence)
        # Synthetic compositor marker over actual decoded video, not ASR.
        overlay = QImage(80, 30, QImage.Format_ARGB32_Premultiplied)
        overlay.fill(QColor('#ffff00ff'))
        raw = folder/'synthetic-overlay.bgra'
        raw.write_bytes(bytes(overlay.constBits()))
        dpr = canvas.devicePixelRatioF()
        acknowledgements = []
        controller.post_raw_overlay(1, str(raw), x=20*dpr, y=20*dpr,
            width=80, height=30, stride=overlay.bytesPerLine(), display_width=80*dpr,
            display_height=30*dpr, on_applied=acknowledgements.append)
        check('overlay_completed_on_gui', wait(lambda: bool(acknowledgements)) and acknowledgements == [True])
        pump(.1)
        composed = controller.surface.grab().toImage()
        check('overlay_actual_widget_pixels', composed.pixelColor(round(30*dpr), round(30*dpr)).name() == '#ff00ff',
              device_pixel_ratio=dpr, capture_kind='owned QWidget paint, not physical display scanout')
        controller.screenshot_to_file(folder/'composed-paused.png')
        controller.remove_overlay(1)
        pump(.1)
        check('overlay_removed', 1 not in controller.surface.overlays and
              not controller.applied_visual_state()['overlays'][1]['visible'])
        # Use the existing ordinary-caption renderer and canvas publication,
        # with original Chinese fixture text. This does not stand in for ASR.
        from .runtime_paths import detect_install_root
        from .studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
        from .visual_snapshot import build_visual_cue_snapshot
        from .caption_playback_cache import PreparedCaption
        from .style_recipe import RecipeRoute
        from .caption_scene import SceneRasterizer
        font = detect_install_root()/'assets/fonts/SourceHanSansSC-Heavy.otf'
        font_id = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        check('licensed_chinese_font_loaded', font_id >= 0 and bool(families),
              family=families[0] if families else '', sha256=hashlib.sha256(font.read_bytes()).hexdigest())
        project = SubtitleProject(media=StudioMedia(str(media),width=320,height=180,duration_ms=4000),
            render_settings={'play_res_x':320,'play_res_y':180},
            cues=[StudioCue('owned-caption',0,4000,'兔白字幕，中文预览')],
            styles=[SubtitleStyle('default','Default',font_family=families[0],font_size=24,
                margin_l=10,margin_r=10,margin_v=15,outline_width=1,shadow=0)])
        snapshot = build_visual_cue_snapshot(project,'owned-caption',width=320,height=180)
        prepared = PreparedCaption(snapshot,snapshot.stable_hash(),RecipeRoute('native',()))
        renderer = SceneRasterizer()
        caption, rows = renderer.frame([('owned-caption',prepared)],1200,320,180)
        renderer.close()
        converted_caption = caption.convertToFormat(QImage.Format_RGBA8888)
        raw_caption = bytes(converted_caption.constBits())
        check('ordinary_chinese_caption_actual_raster', rows[0]['status']=='rendered'
              and sum(byte != 0 for byte in raw_caption[3::4]) > 100,
              cue_pixels=rows, text_source='original synthetic subtitle fixture; not recognition')
        baseline = pixels(controller.surface.grab().toImage())
        size = controller.surface.frame.size().scaled(canvas.size(),Qt.KeepAspectRatio)
        target = QRect((canvas.width()-size.width())//2,(canvas.height()-size.height())//2,
                       size.width(),size.height())
        accepted = canvas.publish_compositor_overlay(canvas.ADVANCED_OVERLAY_ID,caption,target,
            context={'caller':'CaptionSceneProbe','cue_id':'owned-caption'})
        check('ordinary_caption_production_canvas_published', accepted and
              wait(lambda: canvas.ADVANCED_OVERLAY_ID in controller.surface.overlays))
        pump(.1)
        check('ordinary_caption_changes_composed_pixels', baseline != pixels(controller.surface.grab().toImage()))
        controller.screenshot_to_file(folder/'ordinary-chinese-caption.png')
        canvas.remove_compositor_overlay(canvas.ADVANCED_OVERLAY_ID,force=True)
        pump(.1)
        window.resize(810, 520)
        pump(.2)
        check('resize_tracks_owned_canvas', controller.surface.geometry() == canvas.rect(),
              canvas_size=[canvas.width(), canvas.height()])
        # Native macOS activation is asynchronous. Exercise an actual owned
        # editor click after Qt acknowledges the active window, then type.
        window.raise_()
        window.activateWindow()
        QApplication.setActiveWindow(window)
        QTest.mouseClick(editor, Qt.LeftButton, pos=editor.rect().center())
        check('text_editor_focus_acquired', wait(lambda: editor.hasFocus(),2),required=False,
              active_window_type=type(app.activeWindow()).__name__)
        QTest.keyClicks(editor, 'QWE')
        check('text_editor_keeps_qwe', editor.text() == 'QWE' and editor.hasFocus(),required=False,
              text=editor.text(),focused=editor.hasFocus())
        QTest.mouseClick(canvas, Qt.LeftButton, pos=canvas.rect().center())
        pump(.1)
        check('video_click_returns_canvas_focus', canvas.hasFocus(),required=False)
        receipt['shortcut_defaults'] = studio_default_shortcuts()
        native_shortcuts = []
        actions = []
        for command, standard in (('save',QKeySequence.Save),('undo',QKeySequence.Undo),
                                  ('redo',QKeySequence.Redo),('find_replace',QKeySequence.Replace)):
            bindings = QKeySequence.keyBindings(standard)
            default = QKeySequence(receipt['shortcut_defaults'][command])
            if sys.platform == 'darwin':
                check(command+'_uses_qt_standard_binding',
                      default == bindings[0] if bindings else command=='find_replace' and default==QKeySequence('Ctrl+Alt+F'),
                      required=False,qt_bindings=[b.toString(QKeySequence.PortableText) for b in bindings],
                      fallback_when_standard_absent='Ctrl+Alt+F' if command=='find_replace' else None)
            shortcut = QShortcut(default,window)
            shortcut.activated.connect(lambda name=command:actions.append(name))
            native_shortcuts.append(shortcut)
            QTest.keySequence(canvas,default)
            pump(.06)
            check(command+'_native_qt_shortcut_activates', actions.count(command)==1,required=False,
                  portable=default.toString(QKeySequence.PortableText),
                  native_display=default.toString(QKeySequence.NativeText),
                  scope='owned QShortcut mechanism fixture; not a saved project/edit assertion')
        canvas.set_speed(2.0)
        pump(.1)
        check('rate_reaches_actual_qt_player', abs(controller.player.playbackRate()-2)<.001)
        before_position = controller.player.position()
        before_hash = pixels(controller.surface.frame)
        canvas.set_paused(False)
        pump(.5)
        advance = (controller.player.position()-before_position)/1000
        check('playing_advances_real_frames_at_rate', .65 < advance < 1.35 and
              pixels(controller.surface.frame) != before_hash, advance_seconds=advance,
              playback_snapshot=str(canvas.playback_position_snapshot()))
        check('end_of_media_is_paused', wait(lambda: controller.observed_property('eof-reached'), 5)
              and controller.observed_property('pause'), position=controller.player.position()/1000)
        canvas.set_paused(True)
        canvas.seek(.4)
        check('seek_after_eof_restores_paused_real_frame', wait(lambda: not controller.observed_property('seeking')
              and abs(float(controller.observed_property('video-frame-info', {}).get('pts', -1))-.4)<.085),
              applied=controller.applied_seek_state())
        controller.screenshot_to_file(folder/'after-eof.png')
        receipt['actor'] = controller.actor_status()
        receipt['canvas_errors'] = errors
        check('no_canvas_runtime_errors', not errors)
        receipt['passed'] = all(item['passed'] for item in checks.values())
    except Exception as exc:
        receipt.update(passed=False, error_type=type(exc).__name__, reason=str(exc),
                       actor=controller.actor_status(), canvas_errors=errors)
    finally:
        canvas._timer.stop()
        canvas._sync_timer.stop()
        controller.close()
        canvas.controller = None
        window.close()
        pump(.1)
    (folder/'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf8')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
