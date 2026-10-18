"""Actual mpv pixels and PCM endpoint clock, with controlled display misreporting."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def run(output, *, baseline=False, display_fps=0, window=None):
    from ..test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from .. import studio_mpv
    from ..studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, hydrate_media_contract
    from ..studio_helpers import probe_media_identity
    from ..studio_ui import SubtitleStudioPage
    from ..processes import run_hidden_subprocess
    from ..blank_project_audit import _capture

    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    media = output/'variable-rate.mp4'
    # Real PTS run from 0 to 24s: 30 fps through 18s, then 60 fps. Both
    # sections have the same normal-speed clock, regardless of frame density.
    run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=60:d=24',
        '-f', 'lavfi', '-i', 'sine=frequency=600:duration=24:sample_rate=48000',
        '-vf', "select='if(lt(t,18),not(mod(n,2)),1)',drawtext=text='%{pts\\:hms}':x=20:y=20:fontsize=36:fontcolor=white:box=1:boxcolor=black",
        '-fps_mode', 'vfr', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(media)],
        purpose='preview clock VFR fixture', check=True, capture_output=True, timeout=30)
    production_arguments = studio_mpv.mpv_startup_arguments

    def controlled_arguments(*args, **kwargs):
        command = production_arguments(*args, **kwargs)
        if baseline:
            command = ['--video-sync=display-resample' if v.startswith('--video-sync=') else v for v in command]
        if display_fps:
            command.append(f'--display-fps-override={display_fps:g}')
        return command

    studio_mpv.mpv_startup_arguments = controlled_arguments
    app = QApplication.instance() or QApplication([])
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=24000, width=640, height=360),
        cues=[StudioCue(str(i), i*1000, (i+1)*1000, f'SYNC {i:02d}') for i in range(24)])
    hydrate_media_contract(project, probe_media_identity(str(media)))
    project.validate()
    path = output/'fixture.2byteproj'
    save_project(project, path)
    page = window.studio_page if window is not None else SubtitleStudioPage()
    surface = window if window is not None else page
    surface.resize(1440, 900)
    surface.show()
    from ..build_identity import load_build_identity
    result = dict(passed=False, baseline=baseline, display_fps_override=display_fps,
                  scope='real Studio/mpv/PCM; controlled display report; no user media or human listening',
                  entry='normal-window' if window is not None else 'standalone-page',
                  frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable, pid=os.getpid(),
                  identity=load_build_identity().to_dict(), cases=[])

    def wait(predicate, timeout=20):
        end = time.monotonic()+timeout
        while not predicate():
            if time.monotonic() > end:
                raise TimeoutError('Playback readiness: '+str(observe() if page.video.controller else 'no controller'))
            QTest.qWait(25)

    def observe():
        controller = page.video.controller
        audio = page.audio_engine.telemetry_snapshot()
        return dict(wall=time.monotonic(), timeline_ms=page.timeline.playhead_ms,
                    caption_ms=float(page._caption_sample_ms()),
                    video_ms=float(controller.observed_property('time-pos', 0) or 0)*1000,
                    speed=controller.observed_property('speed', None),
                    audio_ms=audio.get('estimated_source_ms'), audio_rate=audio.get('effective_rate'),
                    audio_state=audio.get('state'), sink_processed_us=audio.get('sink_processed_us'),
                    source_generation=audio.get('source_generation'))

    def sample(name, rate, seconds):
        samples = []
        began = time.monotonic()
        while time.monotonic()-began < seconds:
            samples.append(observe())
            QTest.qWait(100)
        # First second is the ordinary startup/telemetry settling interval.
        steady = [s for s in samples if s['wall']-began >= 1 and s['audio_ms'] is not None]
        if len(steady) < 8:
            raise AssertionError('No sustained real audio observations')
        a, b = steady[0], steady[-1]
        wall = b['wall']-a['wall']
        rates = {key: (b[key]-a[key])/1000/wall for key in ('video_ms', 'audio_ms', 'caption_ms')}
        max_drift = max(abs(s['video_ms']-s['audio_ms']) for s in steady)
        caption_drift = max(abs(s['caption_ms']-s['video_ms']) for s in steady)
        row = dict(name=name, requested_rate=rate, measured_rates=rates,
                   max_audio_video_drift_ms=max_drift, max_caption_video_drift_ms=caption_drift,
                   passed=all(abs(v-rate) < .10*rate for v in rates.values())
                          and max_drift < 300*rate and caption_drift < 150*rate,
                   samples=samples)
        result['cases'].append(row)
        page.video.set_paused(True)
        paused_at = time.monotonic()
        # Caption rasters are published asynchronously after the pause. Keep
        # measuring the running clocks above; inspect the settled paused image
        # independently instead of assuming its publication takes <200 ms.
        def pixels_ready():
            visibility = page.subtitle_visibility_trace(reason='preview_clock_pause')
            return bool(visibility.get('expected_cue_ids')) and (
                set(visibility.get('expected_cue_ids', ())) == set(visibility.get('rendered_cue_ids', ())))
        while not pixels_ready() and time.monotonic()-paused_at < 3:
            QTest.qWait(25)
        row['pause_settle_ms'] = (time.monotonic()-paused_at)*1000
        page.video.controller.screenshot_to_file(output/f'{name}-mpv.png')
        _capture(surface, output/f'{name}-studio.png')
        row['subtitle_visibility'] = page.subtitle_visibility_trace(reason='preview_clock_audit')
        row['paused_at_ms'] = page.timeline.playhead_ms
        # Check actual native subtitle raster publication at the paused frame.
        visibility = row['subtitle_visibility']
        row['pixels_passed'] = bool(visibility.get('expected_cue_ids')) and (
            set(visibility.get('expected_cue_ids', ())) == set(visibility.get('rendered_cue_ids', ())))
        row['passed'] = row['passed'] and row['pixels_passed']

    try:
        if window is None:
            page.open_project(path)
        else:
            window.open_studio_project(path, mode='edit', source='preview_clock_audit')
        wait(lambda:page.project is not None and page._readiness.ready and page.video.controller is not None
             and page.video.controller._subtitle_media_ready)
        controller = page.video.controller
        result['mpv'] = {key:controller.get_property(key) for key in ('mpv-version','video-sync','aid')}
        for name, start, rate, seconds in [('early',1,1,6), ('tail',18.5,1,3.5),
                                           ('double',1,2,3.5), ('rate-boundary',16,1,6)]:
            page.video.set_paused(True)
            page._set_speed(rate)
            page._seek(start)
            wait(lambda:not page.video._playback_clock.exact_seek_pending and page._playback_buffers_ready())
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            wait(lambda:not page.video._paused)
            sample(name, rate, seconds)
        # Switch 2x -> 1x without seeking or reopening the media.
        page._seek(1)
        page._set_speed(2)
        wait(lambda:not page.video._playback_clock.exact_seek_pending and page._playback_buffers_ready())
        QTest.mouseClick(page.play_button, Qt.LeftButton)
        wait(lambda:not page.video._paused)
        QTest.qWait(1200)
        page._set_speed(1)
        wait(lambda:not page.video._paused)
        sample('resume-normal', 1, 4)
        result['passed'] = all(c['passed'] for c in result['cases'])
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if window is None:
            page.close_page()
            page.close()
        else:
            page.undo_stack.setClean()
        QTest.qWait(200)
        result['shutdown'] = not bool(getattr(page, '_close_thread', None) and page._close_thread.is_alive())
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
        studio_mpv.mpv_startup_arguments = production_arguments
    return 0 if result['passed'] and result['shutdown'] else 1


def start(window, output):
    """Run inside the ordinary source/frozen application and close normally."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(output, display_fps=float(os.environ.get('TWOBYTEASR_PREVIEW_DISPLAY_FPS', '0')),
                       window=window)
        except Exception:
            (output/'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            receipt = output/'result.json'
            result = json.loads(receipt.read_text('utf8'))
            result['gui_shutdown'] = True
            receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()

    QTimer.singleShot(100, execute)
