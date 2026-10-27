"""Opt-in normal-entry loading matrix with an independent WGC recording."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback


MATRIX_SESSION_NAMES = ('cold-video', 'rapid-latest', 'retried-video',
                        'audio', 'empty', 'silent-video', 'missing-media')
MATRIX_CHECK_NAMES = (
    'cold entry has no Studio', 'cancel during construction stays home',
    'cancelled generation cannot deliver', 'declined dirty open keeps editor',
    'hot resume does not re-deliver', 'rapid A B rejects old delivery',
    'cancel project load stays home', 'failure keeps same card',
    'missing media exposes recovery', 'one card for every phase',
    'loading is visible throughout preparing',
) + tuple(name + suffix for name in MATRIX_SESSION_NAMES
          for suffix in (': single delivery', ': no legacy loading page'))


def completion_errors(data, *, record_required=False, native_required=False,
                      foreground_required=False):
    """Reject partial evidence even when every check reached so far passed."""
    errors = []
    if not data.get('matrix_completed_at'):
        errors.append('loading matrix did not reach its final close scenario')
    if not data.get('shutdown_requested_by_audit'):
        errors.append('shutdown was not requested after the completed matrix')
    if not data.get('normal_shutdown'):
        errors.append('normal application shutdown was not observed')
    checks = data.get('checks') or []
    names = [row.get('name') for row in checks]
    missing = [name for name in MATRIX_CHECK_NAMES if names.count(name) != 1]
    if missing:
        errors.append('missing or repeated matrix checks: ' + ', '.join(missing))
    if any(not row.get('passed') for row in checks):
        errors.append('one or more matrix checks failed')
    sessions = [row.get('name') for row in data.get('sessions') or []]
    missing = [name for name in MATRIX_SESSION_NAMES if sessions.count(name) != 1]
    if missing:
        errors.append('missing or repeated matrix sessions: ' + ', '.join(missing))
    if not data.get('samples'):
        errors.append('no loading state samples were collected')
    if data.get('errors'):
        errors.append('loading audit raised an exception')
    if foreground_required and not (data.get('foreground_gate') or {}).get('accepted_at'):
        errors.append('foreground gate was not accepted')
    if record_required:
        if not data.get('record_ready_at'):
            errors.append('requested recording never became ready')
        roles = {row.get('role') for row in data.get('recorder_receipts') or []}
        if 'wgc' not in roles or data.get('capture_exit_code') != 0 or data.get('capture_error'):
            errors.append('WGC recording did not finish successfully')
        if native_required and ('dda' not in roles or data.get('dda_capture_exit_code') != 0
                                or data.get('dda_capture_error')):
            errors.append('DDA recording did not finish successfully')
    if native_required and (not data.get('capture_visibility_valid')
                            or not data.get('capture_visibility_samples')
                            or not data.get('native_samples')
                            or data.get('native_probe_errors')):
        errors.append('native recording visibility has no complete valid evidence')
    return errors


def fragmented_capture_options():
    # Write an initial moov and short independent fragments. A native parent
    # crash can lose the final fragment, but cannot erase the whole recording.
    return ['-g','60','-movflags','+empty_moov+frag_keyframe+default_base_moof']


def start(window, out):
    from PySide6.QtCore import QObject, QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    from ..diagnostics.build_identity import load_build_identity
    from ..system.processes import popen_hidden_subprocess

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.started = time.perf_counter()
            self.result = dict(passed=False, checks=[], samples=[], errors=[], sessions=[],
                build=load_build_identity().to_dict(), executable=sys.executable,
                frozen=bool(getattr(sys, 'frozen', False)), pid=os.getpid(),
                capture='WGC full native application window' if os.environ.get('TWOBYTEASR_LOADING_RECORD') == '1' else 'not requested')
            handle = window.windowHandle()  # Existing handle only; never create one for diagnostics.
            self.result['qt_graphics'] = {
                'rhi_requested': os.environ.get('QT_WIDGETS_RHI', ''),
                'rhi_backend_requested': os.environ.get('QT_WIDGETS_RHI_BACKEND', ''),
                'window_surface': handle.surfaceType().name if handle is not None else None,
                'swap_interval': handle.format().swapInterval() if handle is not None else None,
                'device_identity': 'not sampled',
            }
            self.recorder = None
            self.record_ready = threading.Event()
            self.record_log = None
            self.recorder_receipts = []
            self.dda_recorder = None
            self.dda_log = None
            self.capture_started = set()
            self.native_probe = None
            self.native_capture_active = False
            self.native_samples = []
            self.native_session = None
            self.native_frames = []
            self.native_frame_threads = []
            self.forensic_label = 'startup'
            self.awaiting_foreground = False
            self.result['forensic_phases'] = []
            self.result['capture_visibility_invalid_samples'] = 0
            self.result['capture_visibility_samples'] = 0
            self.skip_widget_grabs = os.environ.get('TWOBYTEASR_LOADING_SKIP_WIDGET_GRABS') == '1'
            if os.environ.get('TWOBYTEASR_LOADING_NATIVE_FORENSICS') == '1':
                from .loading_native_probe import NativeLoadingProbe
                self.native_probe = NativeLoadingProbe()
                self.native_timer = QTimer(self)
                self.native_timer.timeout.connect(lambda:self.native_sample('periodic'))
                self.native_timer.start(100)
            self.sequence = self.run()
            self.waiting = None
            self.deadline = time.perf_counter() + 120
            self.card = None
            self.capture_keys = set()
            self.closed = False
            self.closing = False
            self.finished = False
            self.timer = QTimer(self)
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.timeout.connect(self.tick)
            self.timer.start(20)
            QApplication.instance().aboutToQuit.connect(self.quit)

        def save(self):
            (out/'loading.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')

        def native_sample(self, reason):
            if self.native_probe is None or self.finished or self.closing or not self.native_capture_active:
                return
            if len(self.native_samples)>=2500:
                self.result['native_samples_truncated']=True
                return
            try:
                session=self.session()
                if session is not None and session is not self.native_session:
                    self.native_session=session
                    session.changed.connect(lambda:self.native_sample('loading.changed'))
                sample=self.native_probe.snapshot(window,session,self.forensic_label+':'+reason)
                cover_state = getattr(session, 'native_cover_state', None)
                if callable(cover_state):
                    sample['loading_cover'] = cover_state()
                card_commit = window.__dict__.get('_studio_cover_visibility')
                if card_commit is not None:
                    sample['card_visibility_commit'] = json.loads(json.dumps(card_commit.last_result))
                visibility = window.__dict__.get('_studio_native_visibility')
                if visibility is not None:
                    # Keep the receipt at this instant, not a mutable reference
                    # that a later native visibility transaction will replace.
                    sample['native_visibility_commit'] = json.loads(json.dumps(visibility.last_result))
                self.native_samples.append(sample)
                if self.result.get('record_ready_at') and not self.closing:
                    self.result['capture_visibility_samples'] += 1
                    coverage=sample['desktop_coverage']
                    if not coverage['foreground_owned'] or not coverage['all_points_owned']:
                        self.result['capture_visibility_invalid_samples']+=1
            except Exception:
                self.result.setdefault('native_probe_errors',[]).append(traceback.format_exc())

        def forensic_hold(self, label, *, preparing=False):
            if self.native_probe is None or os.environ.get('TWOBYTEASR_LOADING_NO_HOLDS') == '1':
                return
            self.forensic_label=label
            phase={'label':label,'start_qpc':time.perf_counter(),'start_utc':time.time(),
                   'diagnostic_hold':True,'preparing_timer_held':False}
            self.result['forensic_phases'].append(phase)
            page=window.built_page('studio')
            gate=getattr(page,'_readiness',None)
            epoch=getattr(gate,'generation',None)
            if preparing and gate is not None and gate.active and gate.timer.isActive():
                phase['preparing_timer_held']=True
                gate.timer.stop()
            self.native_sample('hold-start')
            controller=getattr(getattr(page,'video',None),'controller',None)
            if (controller is not None and controller.running and len(self.native_frame_threads)<12
                    and os.environ.get('TWOBYTEASR_LOADING_SKIP_NATIVE_FRAMES')!='1'):
                index=len(self.native_frame_threads)+1
                def capture_native():
                    row={'label':label,'file':f'mpv-frame-{index:02d}.png','started':time.perf_counter(),
                         'before':controller.observed_properties()}
                    try:
                        controller.screenshot_to_file(out/row['file'],mode='window')
                        row['after']=controller.observed_properties()
                        row['completed']=time.perf_counter()
                    except Exception:row['error']=traceback.format_exc()
                    self.native_frames.append(row)
                worker=threading.Thread(target=capture_native,daemon=True)
                self.native_frame_threads.append(worker);worker.start()
            yield 1.2
            self.native_sample('hold-end')
            phase['end_qpc']=time.perf_counter()
            phase['end_utc']=time.time()
            if phase['preparing_timer_held'] and gate.active and gate.generation==epoch:
                gate.timer.start()

        def check(self, name, value, **detail):
            self.result['checks'].append(dict(name=name, passed=bool(value), **detail))
            self.save()
            if not value:
                raise AssertionError(name + ': ' + str(detail))

        def session(self):
            return window.__dict__.get('_studio_loading_session')

        def ready(self, path):
            page = window.built_page('studio')
            return bool(page is not None and getattr(page, '_readiness', None) is not None
                and page._readiness.ready and str(page.project_path) == str(path.resolve()))

        def tick(self):
            if self.finished:
                return
            try:
                now = time.perf_counter()
                if self.recorder is not None and self.recorder.poll() is not None and not self.closing:
                    raise RuntimeError('WGC recorder exited before the loading sequence: ' + str(self.recorder.returncode))
                if self.dda_recorder is not None and self.dda_recorder.poll() is not None and not self.closing:
                    raise RuntimeError('DDA recorder exited before the loading sequence: ' + str(self.dda_recorder.returncode))
                if now > self.deadline:
                    raise TimeoutError('loading audit state deadline')
                session = self.session()
                if session is not None:
                    self.result['loading_presentation'] = {
                        'native_cover_requested': bool(getattr(session, 'native_cover_requested', False)),
                        'uses_native_cover': bool(getattr(session, 'uses_native_cover', False)),
                        'page_stack': bool(getattr(session.view, 'page_stack', False)),
                    }
                    view = session.view
                    point = view.card.mapTo(window, QPoint())
                    self.result['samples'].append(dict(at=now, generation=session.generation,
                        state=session.state, active=session.active, visible=view.isVisible(),
                        card=id(view.card), rect=[point.x(), point.y(), view.card.width(), view.card.height()],
                        status=view.label.text(), current_page=window.pages.currentWidget().objectName(),
                        deliveries=session.deliveries))
                    if self.card is None:
                        self.card = view.card
                    if view.card is not self.card:
                        raise AssertionError('loading card instance changed')
                    key = (session.generation, session.state, view.steps_view.current)
                    if not self.skip_widget_grabs and view.isVisible() and key not in self.capture_keys:
                        self.capture_keys.add(key)
                        view.grab().save(str(out/f'card-{len(self.capture_keys):03}.png'))
                if callable(self.waiting) and not self.waiting():
                    return
                if isinstance(self.waiting, float) and now < self.waiting:
                    return
                value = next(self.sequence)
                self.waiting = value if callable(value) else time.perf_counter() + float(value)
                self.deadline = time.perf_counter() + (300 if self.awaiting_foreground else 120)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['errors'].append(traceback.format_exc())
                self.finish()

        def capture_start(self):
            if os.environ.get('TWOBYTEASR_LOADING_RECORD') != '1':
                self.record_ready.set()
                return
            app_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
            ffmpeg = app_root/'tools/ffmpeg/bin/ffmpeg.exe'
            if not ffmpeg.is_file():
                ffmpeg = Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe'
            origin=None
            if self.native_probe is not None:
                from .loading_native_probe import dxgi_outputs,select_output
                native=self.native_probe.window(int(window.winId()))
                outputs=dxgi_outputs()
                layout=select_output(outputs,native.get('dwm_frame') or native['rect'])
                before=time.perf_counter();utc=time.time();after=time.perf_counter()
                origin={'utc':utc,'qpc':(before+after)/2,'sampling_uncertainty_ms':(after-before)*500}
                self.result['capture_common_origin']=origin
                self.result['dda_layout']=layout
                self.result['dxgi_outputs']=outputs
                self.result['capture_alignment']='both live inputs use wallclock packet timestamps with one output offset; this timestamps delivery, not DXGI scanout; held stages provide comparison windows'
                self.native_capture_active=True
                self.native_sample('capture-start')
                x,y,w,h=layout['crop']
                self.dda_log=(out/'capture-dda.log').open('wb')
                # This visual-flow recording repeats unchanged desktop frames
                # at 60 Hz so the input loop can consume the stop request on a
                # static page. It is not the distinct-frame cadence collector.
                dda=[str(ffmpeg),'-v','warning','-y','-copyts',
                    '-init_hw_device',f'd3d11va=dda:{layout["adapter_index"]}','-filter_hw_device','dda',
                    '-use_wallclock_as_timestamps','1','-f','lavfi','-i',
                    f'ddagrab=output_idx={layout["output_index"]}:framerate=60:draw_mouse=0:dup_frames=1:offset_x={x}:offset_y={y}:video_size={w}x{h}',
                    '-fps_mode','vfr','-c:v','h264_nvenc','-preset','p1','-cq','18',
                    *fragmented_capture_options(),
                    '-output_ts_offset',f'{-utc:.9f}','-stats_period','0.1','-progress','pipe:1',str(out/'loading-desktop-dda.mp4')]
                self.result['dda_command']=dda
                self.dda_recorder=popen_hidden_subprocess(dda,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=self.dda_log,purpose='paired desktop duplication loading evidence')
                self.record_recorder('dda',self.dda_recorder,dda,out/'loading-desktop-dda.mp4')
            self.record_log = (out/'capture.log').open('wb')
            wgc=[str(ffmpeg), '-v', 'warning', '-y',
                *(['-copyts','-use_wallclock_as_timestamps','1'] if origin else []),
                '-f', 'lavfi', '-i', f'gfxcapture=hwnd={int(window.winId())}:max_framerate=60:capture_cursor=0',
                *(['-fps_mode','vfr','-output_ts_offset',f'{-origin["utc"]:.9f}'] if origin else []),
                '-c:v', 'h264_nvenc', '-preset', 'p1', '-cq', '18', '-stats_period', '0.1',
                *fragmented_capture_options(),
                '-progress', 'pipe:1', str(out/'loading-continuous.mp4')]
            self.result['wgc_command']=wgc
            self.recorder = popen_hidden_subprocess(wgc, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.record_log, purpose='continuous native loading evidence')
            self.record_recorder('wgc',self.recorder,wgc,out/'loading-continuous.mp4')
            def progress(recorder,name):
                for row in iter(recorder.stdout.readline, b''):
                    if row.startswith(b'frame=') and int(row.split(b'=')[1].strip() or b'0') > 0:
                        self.capture_started.add(name)
                        if self.capture_started==({'wgc','dda'} if self.dda_recorder else {'wgc'}):
                            self.record_ready.set()
            threading.Thread(target=progress,args=(self.recorder,'wgc'),daemon=True).start()
            if self.dda_recorder:
                threading.Thread(target=progress,args=(self.dda_recorder,'dda'),daemon=True).start()

        def record_recorder(self, role, recorder, command, output):
            """Persist owned child identity before any loading/closing actions."""
            import psutil
            try:
                process=psutil.Process(recorder.pid)
                row={'role':role,'pid':recorder.pid,'parent_pid':os.getpid(),
                     'create_time':process.create_time(),'exe':process.exe(),
                     'command':list(map(str,command)),'output':str(output.resolve()),
                     'started_qpc':time.perf_counter()}
                self.recorder_receipts.append(row)
                payload={'schema':1,'app_pid':os.getpid(),
                         'app_create_time':psutil.Process(os.getpid()).create_time(),
                         'recorders':self.recorder_receipts}
                temporary=out/'recorders.json.tmp'
                temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf8')
                os.replace(temporary,out/'recorders.json')
                self.result['recorder_receipts']=self.recorder_receipts
            except Exception:
                # We still own this exact Popen handle. Do not leave an
                # unrecorded child that the external runner cannot identify.
                recorder.terminate()
                recorder.wait(timeout=5)
                raise

        def record_session(self, name):
            session = self.session()
            self.result['sessions'].append(dict(name=name, **session.snapshot()))
            self.check(name + ': single delivery', session.deliveries == 1)
            self.check(name + ': no legacy loading page', not any(
                '正在继续创建界面' in item.text() for item in window.findChildren(QLabel)))

        def run(self):
            window.resize(1440, 900)
            screen = QApplication.primaryScreen()
            window.move(screen.availableGeometry().topLeft() + QPoint(32, 32))
            if self.native_probe is not None:
                window.setWindowTitle('载入验证 · '+out.name)
            self.check('cold entry has no Studio', window.built_page('studio') is None)
            if os.environ.get('TWOBYTEASR_LOADING_FOREGROUND_GATE')=='1':
                self.awaiting_foreground=True
                request={'pid':os.getpid(),'hwnd':int(window.winId()),'title':window.windowTitle(),
                         'approval_file':str(out/'foreground-approved.json')}
                (out/'foreground-request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),'utf8')
                print('LOADING_FOREGROUND_GATE '+json.dumps(request,ensure_ascii=False),flush=True)
                def foreground_ready():
                    try:approved=json.loads((out/'foreground-approved.json').read_text('utf8'))
                    except (OSError,ValueError):return False
                    if approved.get('pid')!=request['pid'] or approved.get('hwnd')!=request['hwnd']:return False
                    coverage=self.native_probe.coverage(request['hwnd'])
                    return coverage['foreground_owned'] and coverage['all_points_owned']
                yield foreground_ready
                self.awaiting_foreground=False
                self.result['foreground_gate']=dict(request,accepted_at=time.perf_counter())
            self.capture_start()
            yield self.record_ready.is_set
            self.result['record_ready_at'] = time.perf_counter()
            project = out/'project.2byteproj'
            other = out/'other.2byteproj'
            window.open_studio_project(str(project))
            yield lambda: self.session() is not None and self.session().view.isVisible()
            first = self.session().generation
            QTest.mouseClick(self.session().view.back, Qt.MouseButton.LeftButton)
            yield .4
            self.check('cancel during construction stays home', window.pages.currentWidget() is window.settings_scroll)
            self.check('cancelled generation cannot deliver', not self.session().deliver(first))
            window.open_studio_project(str(project))
            yield lambda: self.ready(project)
            self.record_session('cold-video')
            yield from self.forensic_hold('cold-video-delivered')
            # Declining an actual dirty-project prompt must keep the old editor,
            # its modified text and the undo entry; it is not a library return.
            page = window.built_page('studio')
            from ..timeline.studio_commands import BatchReplaceTextCommand
            original_project = page.project
            cue = page.project.cues[0]
            original_text = cue.text
            page.undo_stack.push(BatchReplaceTextCommand(page.project, {cue.id: original_text + '（未保存）'}, changed=page._changed))
            before_index = page.undo_stack.index()
            cancel_prompt = QTimer(self)
            def reject_dirty():
                box = QApplication.activeModalWidget()
                if isinstance(box, QMessageBox):
                    button = box.button(QMessageBox.StandardButton.Cancel)
                    if button is not None:
                        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            cancel_prompt.timeout.connect(reject_dirty)
            self.timer.stop()
            self.forensic_label='dirty-open-prompt'
            cancel_prompt.start(900 if self.native_probe else 25)
            try:
                window.open_studio_project(str(other))
            finally:
                cancel_prompt.stop()
                self.timer.start(20)
            self.check('declined dirty open keeps editor', page.project is original_project
                and window.pages.currentWidget() is page and page.undo_stack.index() == before_index
                and page.project.cues[0].text == original_text + '（未保存）')
            yield from self.forensic_hold('dirty-open-declined')
            page.undo_stack.undo()
            before_deliveries = self.session().deliveries
            window._return_to_settings()
            yield .15
            yield from self.forensic_hold('home-after-dirty-decline')
            window.open_studio_project(str(project))
            yield lambda: self.ready(project)
            self.check('hot resume does not re-deliver', self.session().deliveries == before_deliveries)
            window.open_studio_project(str(other))
            old_generation = self.session().generation
            yield from self.forensic_hold('preparing-other-with-old-frame',preparing=True)
            window.open_studio_project(str(project))
            yield lambda: self.ready(project) and self.session().state == 'ready'
            self.check('rapid A B rejects old delivery', not self.session().deliver(old_generation))
            self.record_session('rapid-latest')
            yield from self.forensic_hold('rapid-latest-delivered')
            window._return_to_settings()
            window.open_studio_project(str(other))
            yield lambda: self.session().view.isVisible()
            QTest.mouseClick(self.session().view.back, Qt.MouseButton.LeftButton)
            yield .6
            self.check('cancel project load stays home', window.pages.currentWidget() is window.settings_scroll)
            yield from self.forensic_hold('home-after-cancel')
            missing = out/'repaired.2byteproj'
            window.open_studio_project(str(missing))
            yield lambda: self.session().state == 'failed'
            self.check('failure keeps same card', self.session().view.card is self.card and self.session().view.isVisible())
            if not self.skip_widget_grabs:
                self.session().view.grab().save(str(out/'failed-card.png'))
            missing.write_bytes(project.read_bytes())
            QTest.mouseClick(self.session().view.retry, Qt.MouseButton.LeftButton)
            yield lambda: self.ready(missing)
            self.record_session('retried-video')
            yield from self.forensic_hold('retried-video-delivered')
            for name in ('audio', 'empty', 'silent-video', 'missing-media'):
                target = out/f'{name}.2byteproj'
                window.open_studio_project(str(target))
                yield lambda target=target: self.ready(target)
                self.record_session(name)
                if name == 'missing-media':
                    self.check('missing media exposes recovery', window.built_page('studio').relink_button.isVisible())
            self.check('one card for every phase', len({s['card'] for s in self.result['samples']}) == 1)
            self.check('loading is visible throughout preparing', all(s['visible'] for s in self.result['samples'] if s['active']))
            window.open_studio_project(str(other))
            # aboutToQuit can run before this generator is resumed again. Mark
            # completion here, only after every scenario and final open ran.
            self.result['matrix_completed_at'] = time.perf_counter()
            self.closing = True
            if self.native_probe is not None:
                self.native_timer.stop()
                self.save_native_samples()
            # End desktop capture while the owned window still exists. Its
            # close/worker outcome is recorded separately below; no unrelated
            # desktop pixels or native promotion may follow its destruction.
            self.result['recording_end_reason'] = 'before closing the owned test window'
            self.stop_capture()
            self.result['shutdown_requested_by_audit'] = True
            self.save()
            window.close()
            yield lambda: self.closed

        def save_native_samples(self):
            (out/'native-windows.json').write_text(json.dumps(self.native_samples,ensure_ascii=False,indent=2),'utf8')
            self.result['native_samples']=len(self.native_samples)
            self.result['native_frames']=self.native_frames
            self.result['capture_visibility_valid']=bool(self.result['capture_visibility_samples'] > 0
                and self.result['capture_visibility_invalid_samples']==0
                and not self.result.get('native_samples_truncated')
                and not self.result.get('native_probe_errors'))

        def finish(self):
            if self.finished:
                return
            self.finished = True
            self.timer.stop()
            if self.native_probe is not None:
                self.native_timer.stop()
                self.save_native_samples()
            self.stop_capture()
            self.result['completion_errors'] = completion_errors(self.result,
                record_required=os.environ.get('TWOBYTEASR_LOADING_RECORD') == '1',
                native_required=self.native_probe is not None,
                foreground_required=os.environ.get('TWOBYTEASR_LOADING_FOREGROUND_GATE') == '1')
            self.result['passed'] = not self.result['completion_errors']
            self.save()
            if not self.closed:
                self.closing = True
                page = window.built_page('studio')
                if page is not None:
                    page.undo_stack.setClean()  # Only this audit's disposable fixture.
                window.close()

        def stop_capture(self):
            if self.recorder is not None:
                recorder, self.recorder = self.recorder, None
                try:
                    if recorder.poll() is None:
                        recorder.stdin.write(b'q\n')
                        recorder.stdin.flush()
                    recorder.wait(timeout=12)
                    self.result['capture_exit_code'] = recorder.returncode
                except Exception:
                    self.result['capture_error'] = traceback.format_exc()
                    recorder.kill()
                    recorder.wait(timeout=5)
                    self.result['capture_exit_code'] = recorder.returncode
                if self.record_log:
                    self.record_log.close()
                self.save()
            if self.dda_recorder is not None:
                recorder,self.dda_recorder=self.dda_recorder,None
                try:
                    if recorder.poll() is None:
                        recorder.stdin.write(b'q\n');recorder.stdin.flush()
                    recorder.wait(timeout=12)
                    self.result['dda_capture_exit_code']=recorder.returncode
                except Exception:
                    self.result['dda_capture_error']=traceback.format_exc()
                    recorder.kill();recorder.wait(timeout=5)
                    self.result['dda_capture_exit_code']=recorder.returncode
                if self.dda_log:self.dda_log.close()
                self.save()

        def quit(self):
            self.closed = True
            self.result['normal_shutdown'] = True
            self.result['shutdown_kind'] = ('completed_matrix' if self.result.get('shutdown_requested_by_audit')
                else 'failed_audit' if self.finished else 'external_or_early')
            self.finish()
            self.save()  # finish may already have run on a failure before close.

    window._studio_loading_audit = Audit()
