"""Owned recognition process: native failures cannot terminate the main window."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .task_journal import TaskJournal, FileLease, read_record, write_text_atomic


def _command():
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--recognition-queue-worker']
    return [sys.executable, '-X', 'utf8', str(Path(__file__).resolve().parents[2]/'quick_start.py'),
            '--recognition-queue-worker']


def install_settings_snapshot(snapshot_json):
    """Initialize legacy model/switch/performance globals from this task only.

    This runs before importing subtitle_core in the dedicated worker. It does
    not save or migrate settings, and cannot change the main window's profile.
    """
    if not snapshot_json:return lambda:None
    if 'subtitle_core' in sys.modules:
        raise RuntimeError('识别配置快照必须先于流水线加载。')
    import copy
    from ..storage import settings
    frozen,warnings=settings._merge_known_settings(settings.DEFAULT_SETTINGS,json.loads(snapshot_json))
    original=settings.load_runtime_settings
    settings.load_runtime_settings=lambda *a,**k:(copy.deepcopy(frozen),'本次任务配置快照',list(warnings))
    return lambda:setattr(settings,'load_runtime_settings',original)


def supervise(media_paths, options, token, event_sink, console_sink):
    """Bounded pipe reader; the GUI owns only this supervisor thread and PID."""
    from ..system.processes import popen_hidden_subprocess, stop_process_tree
    from .service import MediaResult,PipelineEvent,QueueResult
    journal = TaskJournal(options.job_id).create(media_paths, options)
    from .native_supervision import QueueDiagnostics
    diagnostics=QueueDiagnostics(journal.directory)
    cancel_path = journal.directory / ('cancel-' + __import__('uuid').uuid4().hex)
    messages = queue.Queue(maxsize=64)
    env = dict(os.environ, TWOBYTEASR_PROCESS_ROLE='recognition-queue', QT_QPA_PLATFORM='offscreen')
    try:
        process = popen_hidden_subprocess(_command(), purpose='recognition queue', own_process_tree=True,
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1)
    except BaseException as exc:
        with FileLease(journal.directory/'executor.lock'):
            journal.record=read_record(journal.path)
            journal.finish(status='failed',error=f'工作进程未能启动：{type(exc).__name__}: {exc}')
        raise
    stopping = threading.Event()
    def read():
        try:
            for line in process.stdout:
                while not stopping.is_set():
                    try:
                        messages.put(line, timeout=.1); break
                    except queue.Full:
                        continue
        finally:
            while not stopping.is_set():
                try:
                    messages.put(None, timeout=.1); break
                except queue.Full:
                    continue
    reader = threading.Thread(target=read, name='recognition-process-reader', daemon=True)
    reader.start()
    result = None
    error_text = ''
    cancelled_at = None
    eof = False
    try:
        # Resolved credentials remain in an anonymous pipe, not a task file.
        process.stdin.write(json.dumps({'paths':list(media_paths), 'options':asdict(options),
            'cancel_path':str(cancel_path)},ensure_ascii=True)+'\n')
        process.stdin.flush(); process.stdin.close()
        while not eof:
            diagnostics.sample()
            if token.is_cancelled and cancelled_at is None:
                write_text_atomic(cancel_path, 'cancelled by user')
                cancelled_at = time.monotonic()
            if cancelled_at is not None and time.monotonic()-cancelled_at > 15 and process.poll() is None:
                stop_process_tree(process)
            try:
                line = messages.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                eof = True; continue
            try:
                message = json.loads(line)
            except ValueError:
                console_sink(line.rstrip(), 'stderr'); continue
            kind, value = message.get('kind'), message.get('value')
            if kind == 'identity':
                try:diagnostics.identify(value)
                except Exception as exc:console_sink(f'原生诊断附加失败：{type(exc).__name__}','stderr')
            elif kind == 'event':
                event_sink(PipelineEvent(**value))
            elif kind == 'console':
                console_sink(str(value), str(message.get('level') or 'stdout'))
            elif kind == 'result':
                result = QueueResult(tuple(MediaResult(**r) for r in value['results']),
                    value['elapsed_seconds'],value.get('log_path',''),value.get('job_id',''))
            elif kind == 'error':
                error_text = str(value)
                console_sink(str(value), 'stderr')
        code = process.wait(timeout=10)
        if result is not None and code == 0:
            return result
        previous=read_record(journal.path)
        if result is not None and previous['status'] in {'completed','partial'}:
            console_sink(f'识别结果已保存；工作进程清理退出码 0x{code & 0xffffffff:08X}。','stderr')
            return result
        if error_text and previous['status']=='failed':
            raise RuntimeError(error_text)
        if options.preview_only:
            raise RuntimeError(error_text or f'结果读取进程退出（0x{code & 0xffffffff:08X}），原任务保持不变。')
        reason = error_text or f'识别工作进程异常退出（0x{code & 0xffffffff:08X}）；已保存结果保留。'
        status = 'cancelled' if token.is_cancelled else 'failed' if error_text else 'interrupted'
        # Child is gone; acquire ownership before recording its termination.
        with FileLease(journal.directory/'executor.lock'):
            journal.record=read_record(journal.path)
            journal.record['task']['worker_exit_code']=code
            journal.record['task']['fault_log']=str(journal.directory/'worker-fault.log')
            journal.finish(status=status,error=reason)
        if token.is_cancelled:
            return QueueResult(tuple(MediaResult(path,'cancelled',error='任务已取消。',job_id=options.job_id)
                for path in media_paths),0.,job_id=options.job_id)
        raise RuntimeError(reason)
    except BaseException as exc:
        if process.poll() is None:stop_process_tree(process)
        from .task_journal import TaskBusy
        try:
            with FileLease(journal.directory/'executor.lock'):
                journal.record=read_record(journal.path)
                if journal.record['status'] in {'queued','running'}:
                    journal.finish(status='failed',error=f'工作进程通信失败：{type(exc).__name__}: {exc}')
        except TaskBusy:pass
        raise
    finally:
        stopping.set()
        if process.poll() is None:
            stop_process_tree(process)
        reader.join(3)
        process.stdout.close()
        try:diagnostics.close()
        except OSError:pass


def main():
    """Early frozen/source entry; no MainWindow or single-instance mutex."""
    import faulthandler
    from contextlib import redirect_stdout, redirect_stderr
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if stream is not None and hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='strict')
    restore_settings=lambda:None
    try:
        request = json.loads(sys.stdin.readline())
        restore_settings=install_settings_snapshot(request['options'].get('settings_snapshot_json',''))
        from .service import RunOptions,CancellationToken
        options = RunOptions(**request['options'])
        journal = TaskJournal(options.job_id)
        journal.directory.mkdir(parents=True,exist_ok=True)
    except Exception as exc:
        restore_settings()
        if sys.stdout is not None:
            sys.stdout.write(json.dumps({'kind':'error','value':f'无法读取工作进程请求：{type(exc).__name__}: {exc}'},ensure_ascii=True)+'\n')
            sys.stdout.flush()
        return 2  # Never leave a windowed bootloader error dialog waiting.
    fault_file = (journal.directory/'worker-fault.log').open('a',encoding='utf-8')
    fault_file.write(json.dumps({'job_id':options.job_id,'pid':os.getpid(),'started_epoch':time.time(),
        'executable':sys.executable},ensure_ascii=False)+'\n');fault_file.flush()
    faulthandler.enable(file=fault_file, all_threads=True)
    output = sys.stdout
    lock = threading.RLock()
    def emit(kind,value,**fields):
        with lock:
            output.write(json.dumps({'kind':kind,'value':value,**fields},ensure_ascii=True,default=str)+'\n')
            output.flush()
    class Console:
        encoding = 'utf-8'
        def __init__(self,level):
            self.level=level
        def write(self,text):
            if text and text.strip():emit('console',text.rstrip(),level=self.level)
            return len(text)
        def flush(self):pass
    class Token(CancellationToken):
        @property
        def is_cancelled(self):
            return super().is_cancelled or Path(request['cancel_path']).exists()
    emit('identity',{'pid':os.getpid(),'parent_pid':os.getppid(),'job_id':options.job_id,
        'executable':sys.executable,'python':sys.version,'role':'recognition-queue','started_epoch':time.time()})
    try:
        with redirect_stdout(Console('stdout')), redirect_stderr(Console('stderr')):
            if (os.environ.get('TWOBYTEASR_TEST_ROOT') and os.environ.get('TWOBYTEASR_LIVE_BORROWED_RESOURCES')
                    and os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') in {'perf-recognition','recognition-recovery'}):
                from ..acceptance.glossary_live_resources import install
                install(Path(os.environ['TWOBYTEASR_TEST_ROOT']))
            # Text measurement for generated layout belongs to this process's
            # main thread, with its own offscreen application/font database.
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
            if (os.environ.get('TWOBYTEASR_TEST_ROOT') and os.environ.get('TWOBYTEASR_QUEUE_AUDIT_MODE')
                    and os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO')=='recognition-recovery'):
                from ..acceptance.recognition_recovery_audit import worker_fixture
                return worker_fixture(request,emit)
            from .service import run_media_queue
            if options.preview_only:
                from .partial_result import build
                result=build(options.job_id)
            else:
                result = run_media_queue(request['paths'],options,
                    event_sink=lambda event:emit('event',asdict(event)),cancel_token=Token())
            emit('result',asdict(result))
        return 0
    except BaseException as exc:
        __import__('traceback').print_exc(file=fault_file);fault_file.flush()
        emit('error',f'{type(exc).__name__}: {exc}')
        return 1
    finally:
        faulthandler.disable()
        fault_file.close()
        restore_settings()
