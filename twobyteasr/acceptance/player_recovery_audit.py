"""Actual Windows player lifecycle; fault injection touches only tracked children."""
import hashlib
import json
import os
import sys
import time
import traceback


def start(window, output):
    import faulthandler
    from PIL import Image
    import psutil
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..playback.studio_mpv import MpvIPCTimeoutError, _MpvCommandActor, MpvController
    from ..studio.studio_video_canvas import MpvCanvas
    import threading
    from ..playback.frame_readiness import video_frame_witness

    app = QApplication.instance()
    spec = json.loads((output/'input.json').read_text('utf8'))
    result = dict(passed=False, checks=[], resources=[], pictures=[], faults=[], gui_gaps_ms=[],
        pid=os.getpid(), executable=sys.executable, frozen=bool(getattr(sys,'frozen',False)),
        measurement='private Windows desktop, native mpv screenshots and PCM telemetry; no physical scanout/listening')
    state = dict(condition=None, deadline=0., until=0., last=time.perf_counter(), phase='cold open', busy=False)
    hang_log = (output/'audit-wait-stacks.txt').open('w')
    faulthandler.dump_traceback_later(10, repeat=True, file=hang_log)
    result.update(gui_ipc_calls=[], load_calls_ms=[])
    original_send, original_load = MpvController._send, MpvCanvas.load
    def send(controller, command, *args, **kwargs):
        if threading.current_thread() is threading.main_thread() and command[0] != 'screenshot-to-file':
            result['gui_ipc_calls'].append(dict(command_id=command[0], phase=state['phase']))
        return original_send(controller, command, *args, **kwargs)
    def load(video, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_load(video, *args, **kwargs)
        finally:
            result['load_calls_ms'].append((time.perf_counter()-started)*1000)
    MpvController._send, MpvCanvas.load = send, load
    def write():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        write()
        if not value:
            raise AssertionError(name)
    def page():
        return window.built_page('studio')
    def ready():
        p = page()
        return bool(p is not None and p.project is not None and p._readiness.ready
                    and p.video._startup_state == 'READY' and video_frame_witness(p.video)['ready'])
    def resource(label):
        p = page()
        child = p.video.controller._process
        row = dict(label=label, instance=p.video.controller.instance_id, pid=child.pid)
        for name, pid in [('gui', os.getpid()), ('mpv', child.pid)]:
            process = psutil.Process(pid)
            row[name] = dict(threads=process.num_threads(), handles=process.num_handles(), rss=process.memory_info().rss)
        row['children'] = len(psutil.Process().children(recursive=True))
        result['resources'].append(row)
        write()
    def picture(label, expected):
        path = output/(label+'.png')
        p = page()
        p.video.controller.screenshot_to_file(path, mode='video')
        with Image.open(path) as image:
            dims = image.size
            digest = hashlib.sha256(image.tobytes()).hexdigest()
        result['pictures'].append(dict(label=label, size=dims, digest=digest,
            frame=video_frame_witness(p.video), actor=p.video.controller.actor_status()))
        check(label+' is actual current source picture', dims == expected, dims)
        return digest
    def close_project():
        p = page()
        p.video.set_paused(True)
        p.undo_stack.setClean()
        p._request_return_library()
    def open_project(path):
        window.open_studio_project(path, mode='edit', source='player_recovery_acceptance')
    def capture_tone(name, expected):
        import numpy as np
        p = page()
        p.audio_engine.capture_pcm(name, True)
        yield lambda: (output/(name+'.started')).exists()
        yield .4
        p.audio_engine.capture_pcm(name, False)
        yield lambda: (output/(name+'.json')).exists()
        samples = np.frombuffer((output/(name+'.pcm')).read_bytes(),dtype='<i2').astype(float)
        samples = samples[:len(samples)//2*2].reshape(-1,2).mean(axis=1)
        spectrum = abs(np.fft.rfft(samples*np.hanning(len(samples))))
        peak = float(np.fft.rfftfreq(len(samples),1/48000)[int(np.argmax(spectrum))]) if len(samples) else 0.
        rms = float(np.sqrt(np.mean(samples*samples))) if len(samples) else 0.
        check(name+' actual PCM tone', rms > 50 and abs(peak-expected) < 8.,
              dict(samples=len(samples),rms=rms,peak_hz=peak,expected_hz=expected))
    def steps():
        yield ready
        p = page()
        p.volume_slider.setValue(10)
        picture('cold-A', (640,360))
        p.video.set_paused(False)
        yield .7
        check('cold play advances', not p.video._paused and p.video.visual_position() > .15,
              p.audio_engine.telemetry_snapshot())
        telemetry = p.audio_engine.telemetry_snapshot()
        result['audio_first_play'] = telemetry
        yield from capture_tone('cold-A-tone',440)
        p.video.set_paused(True)
        yield .25
        first = picture('paused-A-1', (640,360))
        yield .3
        check('paused image remains stationary', first == picture('paused-A-2',(640,360)))
        p.save()
        close_project()
        yield .2
        open_project(spec['projects'][0])
        yield ready
        check('saved A reopens', True)
        for index in range(spec['cycles']):
            state['phase'] = f'normal round {index}'
            for project_index, size in [(1,(360,640)), (0,(640,360))]:
                close_project()
                yield .12
                open_project(spec['projects'][project_index])
                yield ready
                p = page()
                p._seek(2.)
                yield lambda: not p.video._playback_clock.exact_seek_pending
                yield .1
                picture(f'round-{index}-{project_index}', size)
                check(f'round {index}/{project_index} seek', abs(p.video.visual_position()-2.) < .15)
                p.video.set_paused(False)
                yield .25
                p.video.set_paused(True)
            resource(f'round-{index}-A')
        if spec['cycles'] >= 5:
            first, last = result['resources'][1], result['resources'][-1]
            check('normal mpv threads/handles remain bounded',
                last['mpv']['threads'] <= first['mpv']['threads']+8
                and last['mpv']['handles'] <= first['mpv']['handles']+64,
                dict(first=first,last=last))
        if spec['faults']:
            for kind in ('disconnect','no_reply','process_exit','restore_failure','playing_exit'):
                state['phase'] = kind
                p = page()
                if kind == 'playing_exit':
                    p.video.set_speed(1.5)
                    p.video.set_paused(False)
                    yield .4
                old = p.video.controller
                old_process = old._process
                old_position = p.video.visual_position()
                old_id, connection = old.instance_id, old.actor_status()['connection_generation']
                actor = old._actor
                before = time.perf_counter()
                if kind == 'disconnect':
                    actor.call(lambda: actor._pipe.close(), 1)
                elif kind == 'no_reply':
                    psutil.Process(old._process.pid).suspend()
                elif kind in {'process_exit','playing_exit'}:
                    old._process.kill()
                else:
                    def fail_restore(*args, **kwargs):
                        raise MpvIPCTimeoutError('injected desired-state failure')
                    old._restore_desired_state = fail_restore
                    actor.call(lambda: actor._pipe.close(), 1)
                yield lambda: (p.video.controller is not None and ready()
                    and (p.video.controller.instance_id != old_id
                         or p.video.controller.actor_status()['connection_generation'] > connection))
                elapsed = time.perf_counter()-before
                result['faults'].append(dict(kind=kind,elapsed=elapsed,old_instance=old_id,
                    current_instance=p.video.controller.instance_id,actor=p.video.controller.actor_status()))
                check(kind+' recovers within budget', elapsed < 18., result['faults'][-1])
                if kind != 'disconnect':
                    check(kind+' retires the exact old child', old_process.poll() is not None)
                picture('recovered-'+kind,(640,360))
                p.video.controller.screenshot_to_file(output/('composed-'+kind+'.png'),mode='window')
                if kind == 'playing_exit':
                    yield lambda: not p.video._paused
                    check('playing recovery preserves rate and position',
                          abs(p.video._playback_rate-1.5)<.01 and p.video.visual_position() >= old_position-.2)
                    yield from capture_tone('recovered-A-tone',440)
                p._seek(3.)
                yield lambda: not p.video._playback_clock.exact_seek_pending
                p.video.set_paused(False)
                yield .35
                check(kind+' can play after recovery', not p.video._paused)
                p.video.set_paused(True)
                if kind == 'playing_exit':
                    p.video.set_speed(1.)
                resource(kind)
            state['phase'] = 'recovery budget exhausted'
            close_project()
            yield .2
            original = _MpvCommandActor._readline_with_timeout
            def no_response(*args, **kwargs):
                raise MpvIPCTimeoutError('injected repeated outage across replacement instances')
            _MpvCommandActor._readline_with_timeout = no_response
            try:
                open_project(spec['projects'][0])
                yield lambda: window._studio_loading_session.state == 'failed'
                check('persistent failure terminates attempt', page().video._recovery_attempts <= 2,
                      page().video._last_load_error)
                view = window._studio_loading_session.view
                check('failure exposes retry and return',view.retry.isVisible() and view.back.isVisible())
                _capture(window,output/'failure-actions.png')
            finally:
                _MpvCommandActor._readline_with_timeout = original
            window._studio_loading_session.view.retry.click()
            yield ready
            check('retry after exhausted budget succeeds',True)
            close_project()
            yield .2
            open_project(spec['projects'][1])
            yield ready
            picture('next-project-after-failure',(360,640))
            page().video.controller.screenshot_to_file(output/'composed-next-B.png',mode='window')
            check('next project has independent recovery opportunity', True)
            page().video.set_paused(False)
            yield .3
            yield from capture_tone('next-B-tone',880)
            page().video.set_paused(True)
            close_project()
            yield .2
            state['phase'] = 'cancel and switch'
            old = page().video.controller
            close_owned = old.close
            close_calls = []
            def slow_close():
                close_calls.append(1)
                time.sleep(.7)  # This explicit fixture wait runs only in the shutdown worker.
                close_owned()
            old.close = slow_close
            psutil.Process(old._process.pid).suspend()
            open_project(spec['projects'][0])
            yield lambda: page().video._recovery_request is not None
            loading = window._studio_loading_session
            cancelled = loading.generation
            loading.request_cancel()
            open_project(spec['projects'][1])
            yield ready
            yield .4
            check('cancelled load cannot overwrite next project',
                  page().project_path.resolve() == __import__('pathlib').Path(spec['projects'][1]).resolve()
                  and window._studio_loading_session.generation > cancelled)
            check('project switch shares one owned recovery worker',len(close_calls)==1)
            picture('after-cancel-B',(360,640))
        _capture(window, output/'final-window.png')
        check('load never waits synchronously for IPC on GUI', not result['gui_ipc_calls'], result['gui_ipc_calls'])
        check('load calls remain below the old 2.5s wait',
              not result['load_calls_ms'] or max(result['load_calls_ms']) < 500., result['load_calls_ms'])
        result['passed'] = all(row['passed'] for row in result['checks'])

    iterator = steps()
    timer = QTimer(window)
    timer.setInterval(15)
    def finish(error=None):
        timer.stop()
        faulthandler.cancel_dump_traceback_later()
        MpvController._send, MpvCanvas.load = original_send, original_load
        if error:
            result['error'] = error
            result['phase'] = state['phase']
            result['passed'] = False
            p = page()
            if p is not None:
                result['failure_health'] = p.video.playback_health()
                result['failure_witness'] = video_frame_witness(p.video)
            try:
                _capture(window, output/'failure-window.png')
            except Exception:
                pass
        write()
        if page() is not None:
            page().undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, app.quit)
    def tick():
        now = time.perf_counter()
        if len(result['gui_gaps_ms']) < 30000:
            result['gui_gaps_ms'].append(dict(phase=state['phase'], ms=round((now-state['last'])*1000,3)))
        state['last'] = now
        if state['busy']:
            return
        state['busy'] = True
        try:
            if state['condition'] is not None:
                if state['condition']():
                    state['condition'] = None
                elif now >= state['deadline']:
                    raise TimeoutError(state['phase'])
                else:
                    return
            if now < state['until']:
                return
            value = next(iterator)
            if callable(value):
                state.update(condition=value, deadline=now+55)
            else:
                state['until'] = now+float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            finish(traceback.format_exc())
        finally:
            state['busy'] = False
    def shutdown():
        result['gui_shutdown'] = True
        write()
    app.aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    write()
    timer.start()
