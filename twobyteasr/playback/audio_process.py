"""One process owns Studio PCM and WASAPI, isolated from the GUI GIL.

The private named pipe carries commands/observations, never a second clock.
"""
from __future__ import annotations

import json
import copy
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from multiprocessing.connection import Client, Listener
from .platform_audio import audio_endpoint, valid_audio_endpoint, cleanup_audio_endpoint, audio_backend

from PySide6.QtCore import QCoreApplication, QObject, QThread, QTimer, Signal, Slot


def _send(connection, payload):
    connection.send_bytes(json.dumps(payload, ensure_ascii=False).encode('utf8'))


def _receive(connection):
    return json.loads(connection.recv_bytes().decode('utf8'))


class AudioProcessBridge(QObject):
    telemetry = Signal(object)
    synchronize_complete = Signal()

    def __init__(self, ffmpeg):
        super().__init__()
        self.ffmpeg = Path(ffmpeg)
        self.process = self.connection = None
        self._stderr = None
        self._closed = False
        self._session = 0
        self._endpoint_generation = 0
        self._broken = False
        self._ack_pending = False
        self._sent_at = self._last_received_at = 0.
        self._attempts = deque(maxlen=3)
        from .audio_recovery import EndpointRecovery
        self._recovery = EndpointRecovery()
        self._failure_emitted = False
        self._watchdog = None
        self._control_epoch = 0
        self._cancel_io = threading.Event()

    def cancel_pending_io(self):
        """GUI-safe cancellation; never touch native Qt objects here."""
        self._control_epoch += 1
        self._cancel_io.set()

    def _diagnostic(self, phase, **fields):
        from ..diagnostics.event_log import emit
        emit('audio.endpoint.lifecycle', phase=phase, **dict(
            {'session_generation':self._session, 'endpoint_generation':self._endpoint_generation}, **fields))

    def _retire(self):
        connection,process = self.connection,self.process
        self.connection = self.process = None
        self._ack_pending = False
        if process is not None:
            self._diagnostic('exit', child_pid=process.pid, exit_code=process.poll(),
                termination='child_exit' if process.poll() is not None else 'parent_retire')
            from ..system.processes import stop_process_tree
            stop_process_tree(process)
        if connection is not None:connection.close()
        if self._stderr is not None:self._stderr.close();self._stderr=None
        if getattr(self, 'log_path', None):
            try:
                from ..providers.provider_diagnostics import redact_diagnostics
                with self.log_path.open('rb') as stream:
                    stream.seek(max(0, self.log_path.stat().st_size-4096))
                    tail = redact_diagnostics(stream.read().decode('utf8', errors='replace'))[-1200:]
                if tail:self._diagnostic('stderr_summary', summary=tail)
            except OSError:pass

    def _check_health(self):
        if self._closed or self.process is None:return
        if not self._failure_emitted and (self.process.poll() is not None or self._broken
                or (self._ack_pending and time.monotonic()-self._sent_at>3.)):
            self._broken=True
            self._failure_emitted=True
            self._ack_pending=False
            self.telemetry.emit({'state':'ENDPOINT_FAILED','session_generation':self._session,
                'endpoint_pid':self.process.pid,'endpoint_generation':self._endpoint_generation,
                'pipe_state':'failed','decoder_error':'音频端点无响应；将在当前播放位置受控恢复'})
            self.synchronize_complete.emit()

    def _ensure(self, control_epoch=None):
        epoch=self._control_epoch if control_epoch is None else control_epoch
        if epoch!=self._control_epoch:raise InterruptedError('音频准备已取消')
        if self.connection is not None:
            if not self._broken and self.process.poll() is None:return
            self._retire()
        now=time.monotonic()
        allowed, reason = self._recovery.begin(now)
        if not allowed:
            raise RuntimeError('音频端点恢复次数已用尽，请检查输出设备后显式重试' if reason=='exhausted'
                else '音频端点恢复退避中，等待有效恢复状态')
        self._broken=False
        self._failure_emitted=False
        self._endpoint_generation+=1
        generation=self._endpoint_generation
        if self._watchdog is None:
            self._watchdog=QTimer(self);self._watchdog.setInterval(500)
            self._watchdog.timeout.connect(self._check_health);self._watchdog.start()
        from ..system.processes import popen_hidden_subprocess
        address, family = audio_endpoint()
        key = secrets.token_bytes(32)
        try:
            listener = Listener(address, family=family, authkey=key)
        except BaseException:
            cleanup_audio_endpoint(address)
            raise
        connected = threading.Event()
        result = {}
        def accept():
            try: result['connection'] = listener.accept()
            except Exception as exc: result['error'] = str(exc)
            finally: connected.set()
        threading.Thread(target=accept, name='audio-pipe-accept', daemon=True).start()
        args = [address, key.hex(), str(self.ffmpeg)]
        command = ([sys.executable, '--studio-audio-worker', *args] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'twobyteasr.playback.audio_process', *args])
        log_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))/'2ByteASR'/'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir/f'audio-endpoint-{secrets.token_hex(6)}.log'
        self._stderr = self.log_path.open('wb')
        try:
            self.process = popen_hidden_subprocess(command, purpose='Studio audio endpoint',
                log_command=[*command[:-3], '<private-pipe>', '<ephemeral-key>', str(self.ffmpeg)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self._stderr,
                cwd=str(Path(sys.executable).parent) if getattr(sys,'frozen',False) else str(Path(__file__).parents[2]))
        except BaseException:
            listener.close()
            cleanup_audio_endpoint(address)
            raise
        self._diagnostic('process_created', child_pid=self.process.pid, cwd=str(Path(sys.executable).parent) if getattr(sys,'frozen',False) else str(Path(__file__).parents[2]))
        cancel=self._cancel_io
        def cancelled():return cancel.is_set() or epoch!=self._control_epoch
        deadline=time.monotonic()+8.
        while not connected.wait(.05) and time.monotonic()<deadline:
            if self._closed or cancelled() or self.process.poll() is not None:
                break
        if 'connection' not in result:
            exit_code=self.process.poll()
            reason=('parent_cancelled' if cancelled() else
                    'child_exited_before_handshake' if exit_code is not None else 'parent_handshake_timeout')
            from ..diagnostics.event_log import emit
            emit('audio.endpoint.failure', phase=reason, child_pid=self.process.pid,
                exit_code=exit_code, endpoint_generation=generation,
                recovery_attempt=self._recovery.attempts)
            self._retire()
            listener.close()
            cleanup_audio_endpoint(address)
            if cancelled():
                self._recovery.attempts=max(0,self._recovery.attempts-1)
                self._recovery.next_attempt_at=0.
                raise InterruptedError('音频准备已取消')
            raise RuntimeError(result.get('error', f'Audio endpoint {reason}; exit={exit_code}; {self.log_path}'))
        if cancelled():
            result['connection'].close()
            self._retire()
            listener.close()
            cleanup_audio_endpoint(address)
            raise InterruptedError('音频准备已取消')
        self.connection = result['connection']
        connection,process=self.connection,self.process
        listener.close()
        cleanup_audio_endpoint(address)
        self._diagnostic('ipc_connected', child_pid=process.pid)
        def receive():
            try:
                while not self._closed and connection is self.connection:
                    try:
                        message = _receive(connection)
                    except TypeError:
                        # Windows recv_bytes can reach PeekNamedPipe after the
                        # owning shutdown/_retire cleared its native handle.
                        # Only a provably retired receiver may end quietly;
                        # active-session TypeError still surfaces unchanged.
                        if (self._closed or connection is not self.connection
                                or generation != self._endpoint_generation):
                            return
                        raise
                    if connection is not self.connection or generation!=self._endpoint_generation:return
                    self._last_received_at=time.monotonic()
                    if message.get('kind') == 'telemetry':
                        state = message['payload']
                        state.setdefault('endpoint_pid', process.pid)
                        state['launcher_pid']=process.pid
                        state['endpoint_backend'] = audio_backend()
                        state['endpoint_generation']=generation
                        state['endpoint_alive']=process.poll() is None
                        state['pipe_state']='connected'
                        self.telemetry.emit(state)
                    elif message.get('kind') == 'ready':
                        self._diagnostic('ready_handshake', child_pid=process.pid,worker_pid=message.get('worker_pid'))
                    elif message.get('kind') == 'milestone':
                        self._diagnostic(str(message.get('phase', 'worker_progress')), **message.get('payload', {}))
                    elif message.get('kind') == 'ack':
                        self._ack_pending=False
                        self.synchronize_complete.emit()
            except (EOFError, OSError, ValueError):
                if not self._closed and connection is self.connection and generation==self._endpoint_generation:
                    self._broken=True
                    self._ack_pending=False
                    self.telemetry.emit({'state':'ENDPOINT_FAILED', 'windows_sink_count':0,
                        'session_generation':self._session,'endpoint_generation':generation,
                        'endpoint_pid':process.pid,'endpoint_alive':process.poll() is None,
                        'pipe_state':'disconnected','decoder_error':'Audio endpoint disconnected'})
                    self.synchronize_complete.emit()
        threading.Thread(target=receive, name='audio-pipe-receiver', daemon=True).start()

    @Slot(object)
    def synchronize(self, payload):
        if int(payload.get('control_epoch', self._control_epoch)) != self._control_epoch:
            self.synchronize_complete.emit()
            return
        self._cancel_io = threading.Event()
        session = int(payload.get('session_generation', 0))
        if session != self._session:
            self._recovery.reset()
            self._failure_emitted=False
        self._session = session
        if not payload.get('audible') and not payload.get('drain') and (self.connection is None or self._broken):
            if self._broken:self._retire()
            self.telemetry.emit({'state':'SILENT','source_path':'','windows_sink_count':0,
                                 'session_generation':self._session,'clock_sequence':1})
            self.synchronize_complete.emit()
            return
        try:
            previous_generation=self._endpoint_generation
            self._ensure(int(payload.get('control_epoch',self._control_epoch)))
            if previous_generation and previous_generation!=self._endpoint_generation and not payload.get('paused',True):
                # Recovery uses this request's clock sample plus elapsed time,
                # never zero or the failed decoder's original start position.
                payload=copy.deepcopy(payload)
                elapsed=max(0.,time.monotonic()-payload.get('submitted_monotonic',time.monotonic()))*1000.
                for layer in [payload,*payload.get('mix_layers',())]:
                    layer['source_ms']=int(layer.get('source_ms',0)+elapsed*float(layer.get('playback_rate',1.))*float(payload.get('transport_rate',1.)))
            self._sent_at=time.monotonic();self._ack_pending=True
            _send(self.connection, {'kind':'sync','payload':payload})
        except InterruptedError:
            self.synchronize_complete.emit()
        except Exception as exc:
            self._broken=True;self._ack_pending=False
            self.telemetry.emit({'state':'ENDPOINT_FAILED','windows_sink_count':0,
                                 'session_generation':self._session,'decoder_error':str(exc),
                                 'endpoint_generation':self._endpoint_generation,
                                 'recovery_attempts':self._recovery.attempts,
                                 'recovery_exhausted':self._recovery.attempts>=self._recovery.maximum,
                                 'retry_after_seconds':max(0.,self._recovery.next_attempt_at-time.monotonic())})
            self.synchronize_complete.emit()

    @Slot()
    def retry(self):
        if self._closed:return
        self._retire()
        self._recovery.reset()
        self._failure_emitted=False
        self._broken=False

    @Slot(object)
    def capture(self, payload):
        self._ensure()
        _send(self.connection, {'kind':'capture','payload':payload})

    def prepare_shutdown(self):
        self.cancel_pending_io()

    @Slot()
    def shutdown(self):
        self._closed = True
        if self._watchdog is not None:self._watchdog.stop()
        try:
            if self.connection is not None:
                _send(self.connection, {'kind':'shutdown'})
            if self.process is not None:
                try: self.process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    from ..system.processes import stop_process_tree
                    stop_process_tree(self.process)
        except (OSError, EOFError):
            pass
        finally:
            if self.connection is not None: self.connection.close()
            if self._stderr is not None: self._stderr.close()
            QThread.currentThread().quit()


def main(args=None):
    address, key, ffmpeg = list(args if args is not None else sys.argv[1:])
    if not valid_audio_endpoint(address):
        raise ValueError('Invalid private audio endpoint')
    os.environ['TWOBYTEASR_PROCESS_ROLE'] = 'studio-audio'
    faults=None
    if os.environ.get('TWOBYTEASR_TEST_ROOT') and os.environ.get('TWOBYTEASR_TEST_AUDIO_FAULT'):
        from ..acceptance import audio_endpoint_faults as faults
        faults.before_connect()
    connection = Client(address, family='AF_PIPE' if os.name=='nt' else 'AF_UNIX', authkey=bytes.fromhex(key))
    app = QCoreApplication([])
    if os.environ.get("TWOBYTEASR_STALL_WATCHDOG", "1").strip() not in {"0", "false", "off"}:
        # The endpoint's Qt thread services sync requests and the sink; a
        # blocked thread delays every pause/seek. Stacks go to this process's
        # own log (stderr = audio-endpoint-*.log), only when it is stuck.
        from ..diagnostics.gui_stall_watchdog import GuiStallWatchdog

        def write_stall(kind, record):
            sys.stderr.write(json.dumps({"event": "AUDIO_ENDPOINT_" + kind,
                                         "at": time.strftime("%H:%M:%S"), **record},
                                        ensure_ascii=False) + "\n")
            sys.stderr.flush()
        endpoint_watchdog = GuiStallWatchdog(app, sink=write_stall)
        endpoint_watchdog.start()
    from .audio_engine import _AudioEngineWorker
    if faults is not None:faults.configure_devices()
    worker = _AudioEngineWorker(Path(ffmpeg))
    if os.name=='nt':
        from .audio_session_status import AudioSessionStatus
        session_status=AudioSessionStatus()
    else:
        from types import SimpleNamespace
        # WASAPI/IAudioSessionManager is a Windows observation. Qt's native
        # sink remains the only audio owner on macOS/Linux; no fake Windows
        # session count is reported as a measured CoreAudio session count.
        session_status=SimpleNamespace(stop=threading.Event(),value={
            'endpoint_backend':audio_backend(),'native_session_observation':'not_available',
        })
    condition = threading.Condition()
    controls = deque()
    latest = [None]
    closed = threading.Event()
    def queue_control(value):
        with condition:
            controls.append(value)
            condition.notify()
    def telemetry(value):
        with condition:
            latest[0] = {'kind':'telemetry','payload':{**value,**session_status.value,'endpoint_pid':os.getpid()}}
            condition.notify()
        # One bounded event per generation/phase, no PCM or private paths.
        generation=(value.get('session_generation'), tuple(value.get('transport_generation') or ()))
        if generation != progress.get('generation'):
            progress.clear();progress['generation']=generation
        phases = {'media_open':bool(value.get('source_path')),
                  'first_pcm':int(value.get('decoded_bytes') or 0)>0,
                  'output_device_open':int(value.get('windows_sink_count') or 0)>0,
                  'first_consumption':int(value.get('sink_consumed_bytes') or 0)>0}
        for phase, ready in phases.items():
            if ready and not progress.get(phase):
                progress[phase]=True
                queue_control({'kind':'milestone','phase':phase,'payload':{
                    'session_generation':value.get('session_generation'),
                    'transport_generation':value.get('transport_generation')}})
    progress={}
    def writer():
        try:
            while not closed.is_set():
                with condition:
                    condition.wait_for(lambda: controls or latest[0] is not None or closed.is_set())
                    messages = list(controls); controls.clear()
                    if latest[0] is not None:
                        messages.insert(0, latest[0]); latest[0] = None
                for value in messages: _send(connection, value)
        except (OSError, EOFError):
            app.quit()
    threading.Thread(target=writer, name='audio-observation-writer', daemon=True).start()
    queue_control({'kind':'ready','worker_pid':os.getpid()})
    worker.telemetry.connect(telemetry)
    worker.synchronize_complete.connect(lambda: queue_control({'kind':'ack'}))

    class Receiver(QObject):
        message = Signal(object)
        def __init__(self):
            super().__init__(); self.recorder = None
            self.message.connect(self.dispatch)
        @Slot(object)
        def dispatch(self, message):
            kind = message.get('kind')
            if kind == 'sync': worker.synchronize(message['payload'])
            elif kind == 'capture':
                if self.recorder is None:
                    from ..acceptance.audio_pcm_audit import EndpointRecorder
                    self.recorder = EndpointRecorder()
                self.recorder.command(message['payload'])
            elif kind == 'shutdown': worker.shutdown()
    receiver = Receiver()
    def reader():
        try:
            while not closed.is_set(): receiver.message.emit(_receive(connection))
        except (EOFError, OSError, ValueError):
            try: receiver.message.emit({'kind':'shutdown'})
            except RuntimeError: pass
    threading.Thread(target=reader, name='audio-command-reader', daemon=True).start()
    # Scoped timer accuracy belongs to the endpoint's lifetime.
    import ctypes
    multimedia = ctypes.WinDLL('winmm') if os.name=='nt' else None
    if multimedia is not None: multimedia.timeBeginPeriod(1)
    try: return app.exec()
    finally:
        session_status.stop.set()
        closed.set()
        with condition: condition.notify_all()
        connection.close()
        if multimedia is not None: multimedia.timeEndPeriod(1)


if __name__ == '__main__':
    raise SystemExit(main())
