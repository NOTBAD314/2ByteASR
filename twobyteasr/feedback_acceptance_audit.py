"""Fixed source/frozen checks for theme, fit, G gain and audible transport.

Only dispatched by studio_acceptance_audit after its tmp/config isolation gate.
PCM capture observes bytes submitted to QAudioSink, not a microphone recording.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time


def start_feedback_acceptance(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QDoubleSpinBox, QLineEdit
    from PySide6.QtTest import QTest
    from .audio_engine import _PcmRingDevice
    from .build_identity import load_build_identity
    from .studio_project import save_project, load_project
    from .studio_track_gain import track_gain_db
    from .theme_manager import apply_theme
    from .ui_theme import THEMES

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.results = dict(runtime='frozen' if getattr(sys, 'frozen', False) else 'source',
                                build=vars(load_build_identity()), checks={}, themes=[], playback=[])
            self.started = self.last_tick = time.perf_counter()
            self.waiting = 0.
            self.pcm, self.gaps, self.rows = [], [], []
            self.capturing = False
            self.original_read = _PcmRingDevice.readData
            def read(device, count):
                data = self.original_read(device, count)
                if data and self.capturing:
                    self.pcm.append(data)
                return data
            _PcmRingDevice.readData = read
            self.sequence = self.scenario()
            self.timer = QTimer(self)
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.setInterval(10)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def check(self, key, value):
            self.results['checks'][key] = bool(value)
            assert value, key

        def shot(self, name, native=False):
            window.grab().save(str(output / f'{name}.png'))
            if native:
                self.page.video.controller.screenshot_to_file(output / f'{name}-native.png')

        def tick(self):
            now = time.perf_counter()
            if self.capturing:
                self.gaps.append((now-self.last_tick)*1000)
                snap = self.page.audio_engine.telemetry_snapshot()
                self.rows.append({k: snap.get(k) for k in ('state', 'source_generation', 'startup_trim_ms',
                    'decoder_eof', 'decoded_bytes', 'sink_consumed_bytes', 'buffer_bytes', 'paused')})
            self.last_tick = now
            try:
                if now-self.started > 120:
                    raise TimeoutError('feedback acceptance timed out')
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif now < self.waiting:
                    return
                pending = next(self.sequence)
                self.results['phase_line'] = self.sequence.gi_frame.f_lineno
                self.waiting = pending if callable(pending) else time.perf_counter()+float(pending)
            except StopIteration:
                self.finish()
            except Exception:
                import traceback
                self.results['error'] = traceback.format_exc()
                self.finish()

        def scenario(self):
            page = self.page
            yield lambda: page.project is not None and len(page.project.video_tracks) == 3
            page._queue_advanced_preview_job = lambda *a, **kw: None
            window.resize(1600, 960)
            window.raise_(); window.activateWindow()
            page.video.set_paused(True)
            # Five palettes with the expensive Studio tree hidden, then shown.
            window._switch_page(0)
            for key in ('slate', 'plum', 'lavender', 'warm', 'grape'):
                start = time.perf_counter()
                apply_theme(key, QApplication.instance())
                self.results['themes'].append(dict(key=key, apply_ms=(time.perf_counter()-start)*1000))
                yield .1
                self.shot(f'home-{key}')
            window._switch_page(page)
            yield .2
            self.check('hidden_studio_theme', THEMES['grape'].app_background in page.styleSheet())
            page._seek(2.)
            comp = page.video_compositor
            yield lambda: len(comp._players) >= 2 and all(not p.image.isNull() for p in comp._players.values())
            self.shot('studio-grape', True)
            # Apply all three presets to the real 4:3 overlay on a 16:9 canvas.
            track = page.project.video_tracks[1]
            clip = track.clips[0]
            page._video_clip_selected(track.id, clip.id)
            hashes = []
            for mode in ('cover', 'contain', 'stretch'):
                combo = page.video_fit_mode
                combo.setFocus()
                combo.showPopup()
                index = combo.model().index(combo.findData(mode), 0)
                QTest.mouseClick(combo.view().viewport(), Qt.MouseButton.LeftButton,
                                 pos=combo.view().visualRect(index).center())
                yield .5
                clip = page.project.video_tracks[1].clips[0]
                self.check(f'fit_{mode}', clip.transform.fit_mode == mode and clip.transform.scale_x == 1.)
                self.shot(f'fit-{mode}', True)
                hashes.append(hashlib.sha256((output/f'fit-{mode}-native.png').read_bytes()).hexdigest())
            self.check('three_native_fit_images_differ', len(set(hashes)) == 3)
            page.undo_stack.undo()
            self.check('fit_undo', page.project.video_tracks[1].clips[0].transform.fit_mode == 'contain')
            page.undo_stack.redo()
            # Base transforms have to reach the image, not just the handles.
            for overlay_track in page.project.video_tracks[1:]:
                overlay_track.enabled = False
            base_track = page.project.video_tracks[0]
            base_track.locked = False
            base = base_track.clips[0]
            page._video_clip_selected(base_track.id, base.id)
            values = page._video_transform_values_from_controls()
            values.update(scale_x=.7, scale_y=.7)
            page._video_transform_committed(base_track.id, base.id, values)
            yield lambda: comp._composes_base and not comp._players[base.id].image.isNull()
            yield .1
            self.shot('base-scaled', True)
            self.check('base_geometry_composed', comp._composes_base)
            page.undo_stack.undo()
            for overlay_track in page.project.video_tracks[1:]:
                overlay_track.enabled = True
            # A real key event opens the gain dialog, and typing G stays text.
            page._video_clip_selected(track.id, clip.id)
            page.setFocus()
            QTest.keyClick(page, Qt.Key.Key_G)
            yield lambda: getattr(page, '_track_gain_dialog', None) is not None
            dialog = page._track_gain_dialog
            gain = dialog.findChild(QDoubleSpinBox, 'trackGainDb')
            gain.setValue(-12.)
            yield .15
            dialog.grab().save(str(output/'gain-dialog.png'))
            buttons = dialog.findChild(QDialogButtonBox)
            QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
            yield .1
            self.check('G_applies_selected_track', track_gain_db(page.project, track.id) == -12.)
            page.undo_stack.undo()
            self.check('gain_undo', track_gain_db(page.project, track.id) == 0.)
            page.undo_stack.redo()
            saved = save_project(page.project, output/'edited.2byteproj')
            restored = load_project(saved)
            self.check('gain_fit_save_reload', track_gain_db(restored, track.id) == -12.
                       and restored.video_tracks[1].clips[0].transform.fit_mode == 'stretch')
            editor = QLineEdit(page)
            editor.setGeometry(60, 65, 240, 40); editor.show(); editor.setFocus()
            window.activateWindow()
            yield .15
            editor.setFocus()
            QTest.keyClicks(editor, 'g')
            self.results['typing'] = dict(text=editor.text(), focus=QApplication.focusWidget() is editor,
                dialog_open=page._track_gain_dialog is not None)
            self.check('typing_G_not_intercepted', editor.text() == 'g' and page._track_gain_dialog is None)
            editor.hide(); editor.deleteLater(); page.setFocus()
            # Restore the smaller overlay for representative continuous playback.
            from .studio_project import VideoTransform
            clip = page.project.video_tracks[1].clips[0]
            clip.transform = VideoTransform(scale_x=.45, scale_y=.45, position_x=.3)
            page._sync_video_compositor(2000)
            for rate in (1., 2.):
                page.video.set_paused(True)
                page._seek(0.)
                page._set_speed(rate)
                capture_name=f'feedback-{rate:g}x'
                page.audio_engine.capture_pcm(capture_name,True)
                yield lambda:(output/f'{capture_name}.started').is_file()
                self.pcm, self.gaps, self.rows = [], [], []
                self.capturing = True
                self.last_tick = time.perf_counter()
                page._toggle_playback()  # no wait between seek and Play
                play_start = time.perf_counter()
                yield lambda: not page.video._paused
                startup_ms = (time.perf_counter()-play_start)*1000
                yield lambda: page.audio_engine.telemetry_snapshot().get('state') == 'DRAINED'
                self.capturing = False
                page.audio_engine.capture_pcm(capture_name,False)
                yield lambda:(output/f'{capture_name}.json').is_file()
                import numpy as np
                data = (output/f'{capture_name}.pcm').read_bytes()
                (output/f'audio-{rate:g}x.pcm').write_bytes(data)
                pcm = np.frombuffer(data, dtype='<i2')
                active = [r for r in self.rows if not r['paused'] and r['sink_consumed_bytes']]
                generations = sorted({r['source_generation'] for r in active})
                summary = dict(rate=rate, bytes=len(data), startup_ms=startup_ms,
                    gui_gap_p95_ms=sorted(self.gaps)[int(len(self.gaps)*.95)], gui_gap_max_ms=max(self.gaps),
                    generations=generations, trim_ms=max(r['startup_trim_ms'] or 0 for r in self.rows),
                    first_50ms_rms=float(np.sqrt(np.mean(pcm[:4800].astype(float)**2))),
                    tail_10ms_rms=float(np.sqrt(np.mean(pcm[-960:].astype(float)**2))))
                self.results['playback'].append(summary)
                self.check(f'pcm_full_duration_{rate:g}x', len(data) == round(6000/rate)*192)
                self.check(f'no_restart_or_trim_{rate:g}x', len(generations) == 1 and summary['trim_ms'] == 0)
                self.check(f'signal_first_tail_{rate:g}x', summary['first_50ms_rms'] > 50 and summary['tail_10ms_rms'] > 50)
            # Pause/resume and a hot speed change must use a fresh, ready buffer.
            page._seek(1.); page._set_speed(1.); page._toggle_playback()
            yield lambda: not page.video._paused
            yield .4
            page.video.set_paused(True)
            yield .1  # allow the asynchronous mpv pause acknowledgement
            at = page.timeline.playhead_ms
            yield .2
            self.check('pause_stationary', abs(page.timeline.playhead_ms-at) < 60)
            page._toggle_playback()
            yield lambda: not page.video._paused
            yield .3
            self.check('resume_advances', page.timeline.playhead_ms > at+100)
            page._set_speed(2.)
            yield lambda: not page.video._paused and page.audio_engine.telemetry_snapshot().get('effective_rate') == 2.
            self.check('hot_speed_resumes', page._shuttle_speed == 2.)
            page.video.set_paused(True)
            page._seek(1.)
            yield lambda: all(abs(comp._players[str(layer['clip_id'])].pts_ms-int(layer['source_ms'])) < 100
                              for layer in comp._layers)
            self.check('seek_settled', True)
            # Exercise the actual composition + final encoding path with gain.
            from .video_export import capture_video_graph
            from .studio_render import RenderJob, RenderSettings, run_render_job
            from .ass_compiler import compile_ass
            from .runtime_paths import get_runtime_paths
            from .processes import run_hidden_subprocess
            import threading
            ass = output/'export.ass'
            ass.write_text(compile_ass(page.project), encoding='utf-8-sig')
            job = RenderJob(page.project.media.path, str(ass), str(output/'gain-export.mp4'),
                RenderSettings(encoder='libx264', preset='ultrafast', width=320, height=180, fps=10),
                start_seconds=1., duration_seconds=1., video_graph=capture_video_graph(page.project))
            ffmpeg = get_runtime_paths().install_root/'tools/ffmpeg/bin/ffmpeg.exe'
            exported = {}
            def render():
                try:
                    run_render_job(ffmpeg, job)
                    raw = run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-i', job.output_path,
                        '-vn', '-f', 's16le', '-ac', '1', '-ar', '48000', 'pipe:1'],
                        purpose='acceptance gain export PCM', capture_output=True, check=True, timeout=20).stdout
                    import numpy as np
                    pcm = np.frombuffer(raw, dtype='<i2').astype(float)[:48000]
                    spectrum = np.abs(np.fft.rfft(pcm*np.hanning(len(pcm))))
                    strengths = [float(spectrum[round(f*len(pcm)/48000)]) for f in (440, 770, 1100)]
                    exported['ratio'] = strengths[1]/((strengths[0]+strengths[2])/2)
                    from .audio_graph_acceptance import verify_audio_graph_matrix
                    exported['graph_matrix']=verify_audio_graph_matrix(page.project,ffmpeg,output)
                except Exception:
                    import traceback
                    exported['error'] = traceback.format_exc()
                finally:
                    exported['done'] = True
            threading.Thread(target=render, daemon=True, name='feedback-export').start()
            yield lambda: exported.get('done')
            self.results['export'] = exported
            self.check('real_export_gain', not exported.get('error') and .20 < exported.get('ratio', 0) < .31)
            for mode in ('default','positive-negative','mute','solo','linked-trim'):
                self.check(f'graph_movie_matches_preview_{mode}',
                    exported.get('graph_matrix',{}).get(mode,{}).get('passed',False))

        def finish(self):
            self.timer.stop()
            self.capturing = False
            _PcmRingDevice.readData = self.original_read
            self.page.close_page()
            (output/'feedback-acceptance.json').write_text(json.dumps(self.results, ensure_ascii=False, indent=2), encoding='utf-8')
            window.hide()
            QTimer.singleShot(200, QApplication.instance().quit)

    window._acceptance_audit = Audit()
