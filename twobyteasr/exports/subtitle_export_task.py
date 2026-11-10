"""Pure-data subtitle worker. The dialog polls and owns all Qt updates."""
from __future__ import annotations

import threading
import traceback
import hashlib
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import tempfile
import time

from ..diagnostics.subtitle_export_work import SubtitleExportWork, stage


class SubtitleExportTask:
    def __init__(self, snapshot, directory, stem, formats, layers, mode, translation_first,
                 export_artifacts, export_layers, snapshot_seconds=0):
        self.snapshot = snapshot
        self.project_id = snapshot.project_id
        self.revision = snapshot.revision
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.work = SubtitleExportWork(self.cancel)
        self.work.timings['snapshot'] = snapshot_seconds
        self.artifacts = ()
        self.layered = None
        self.error = None
        self.details = ''
        self.exception_type = ''
        self.cue_count = snapshot.cue_count
        self.formats = tuple(sorted(formats))
        self.snapshot_bytes = len(snapshot.data)
        self.validation_cache = {}
        self._arguments = (directory, stem, set(formats), tuple(layers), mode, translation_first,
                           export_artifacts, export_layers)

    def start(self):
        threading.Thread(target=self._run_process, name='subtitle-export-' + self.work.task_id[:8], daemon=True).start()

    def _run_process(self):
        from ..system.processes import popen_hidden_subprocess
        from ..diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE
        parameters = self._arguments[:6]
        target = Path(parameters[0]).resolve()
        process = job = None
        stage_name = 'worker_start'
        began = time.perf_counter()
        try:
            if self.cancel.is_set():
                from ..diagnostics.subtitle_export_work import SubtitleExportCancelled
                raise SubtitleExportCancelled()
            with tempfile.TemporaryDirectory(prefix='2byte-subtitle-' + self.work.task_id + '-') as control:
                cancel_path = Path(control) / 'cancel'
                request = dict(snapshot=self.snapshot, parameters=parameters,
                    task_id=self.work.task_id, cancel_path=str(cancel_path))
                self.snapshot_sha256 = hashlib.sha256(self.snapshot.data).hexdigest()
                data = pickle.dumps(request, protocol=5)
                command = ([sys.executable, '--subtitle-export-worker'] if getattr(sys, 'frozen', False)
                           else [sys.executable, '-B', str(Path(__file__).resolve().parents[2] / 'quick_start.py'),
                                 '--subtitle-export-worker'])
                process = popen_hidden_subprocess(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, purpose='data-only subtitle export',
                    log_command=['2ByteASR', '--subtitle-export-worker'],
                    creationflags=4 if sys.platform == 'win32' else 0)
                self.worker_pid = process.pid
                if sys.platform == 'win32':
                    from ..system.process_job import RequestProcessJob
                    job = RequestProcessJob(process)
                stage_name = 'worker_execute'
                pending = data
                while True:
                    if self.cancel.is_set():
                        cancel_path.touch(exist_ok=True)
                    try:
                        stdout, stderr = process.communicate(input=pending, timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        pending = None
                        if time.perf_counter() - began > 600:
                            raise TimeoutError('字幕导出工作进程超时')
                self.worker_exit = process.returncode
                if process.returncode != 0:
                    self.details = stderr.decode('utf-8', 'replace')[-16384:]
                    stage_name = 'worker_exit'
                    raise RuntimeError(f'字幕导出工作进程退出（{process.returncode}），当前工程仍可使用')
                reply = pickle.loads(stdout)
                self.artifacts, self.layered = reply['artifacts'], reply['layered']
                self.exception_type = reply['exception_type']
                self.error = RuntimeError(reply['error']) if reply['error'] else None
                self.details = reply['details']
                self.cue_count = reply['cue_count']
                self.validation_cache = reply.get('validation_cache', {})
                self.work.timings.update({key: value for key, value in reply['timings'].items() if key != 'snapshot'})
                self.work.peak_bytes = reply['peak_bytes']
                stage_name = reply['failed_stage']
        except Exception as exc:
            self.exception_type = type(exc).__name__
            self.error = RuntimeError(str(exc))
            self.details = self.details or traceback.format_exc()
        finally:
            try:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.communicate()
                if job is not None:
                    job.close(timeout=3)
                # Only paths tagged with this exact task ID belong to an abnormal
                # worker exit. Successful/cooperative cancellation cleans itself.
                self.cleanup_leftovers = []
                for prefix in ('.subtitle-export-', '.subtitle-layers-'):
                    for path in target.glob(prefix + self.work.task_id + '-*'):
                        if path.is_dir() and not path.is_symlink() and path.resolve().parent == target:
                            try:
                                shutil.rmtree(path)
                            except OSError:
                                self.cleanup_leftovers.append(path.name)
                self.work.timings['worker_total'] = time.perf_counter() - began
                GLOBAL_STUDIO_TRACE.emit('SUBTITLE_EXPORT_TASK_OWNER', dict(task_id=self.work.task_id,
                    project_id=self.project_id, revision=self.revision, formats=list(self.formats),
                    layers=list(parameters[3]), speaker_mode=parameters[4], cue_count=self.cue_count,
                    timings_ms={key: value * 1000 for key, value in self.work.timings.items()},
                    worker_peak_bytes=self.work.peak_bytes, worker_pid=getattr(self, 'worker_pid', None),
                    worker_exit=getattr(self, 'worker_exit', None), files=len(self.artifacts),
                    snapshot_builds=1, snapshot_bytes=self.snapshot_bytes,
                    snapshot_sha256=getattr(self, 'snapshot_sha256', ''), validation_cache=self.validation_cache,
                    exception_type=self.exception_type, failed_stage=stage_name,
                    cleanup_leftovers=self.cleanup_leftovers, preview_cache='unused'))
            except Exception as cleanup_error:
                if self.error is None:
                    self.exception_type = type(cleanup_error).__name__
                    self.error = RuntimeError(str(cleanup_error))
                    self.details = traceback.format_exc()
            finally:
                self.snapshot = None
                self._arguments = None
                self.done.set()

    def _run(self):
        from .studio_subtitle_export import SubtitleExportOptions
        from ..diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE
        directory, stem, formats, layers, mode, translation_first, export_artifacts, export_layers = self._arguments
        try:
            with self.work.activate():
                with stage('materialize'):
                    project = self.snapshot.materialize()
                    self.cue_count = len(project.cues)
                if layers and 'srt' in formats:
                    self.layered = export_layers(project, directory, stem,
                        layers + (('json',) if 'json' in formats else ()),
                        translation_first=translation_first, speaker_mode=mode)
                    formats -= {'srt', 'json'}
                self.artifacts = tuple(self.layered.artifacts) if self.layered is not None else ()
                if formats:
                    self.work.checkpoint(self.artifacts)
                    self.artifacts += export_artifacts(project, directory, stem,
                        SubtitleExportOptions(frozenset(formats), mode))
        except Exception as exc:
            self.details = exc.details() if callable(getattr(exc, 'details', None)) else traceback.format_exc()
            self.exception_type = type(exc).__name__
            self.error = RuntimeError(str(exc))
            self.artifacts += tuple(artifact for artifact in getattr(exc, 'published', ())
                                    if artifact not in self.artifacts)
        finally:
            GLOBAL_STUDIO_TRACE.emit('SUBTITLE_EXPORT_TASK', dict(
                task_id=self.work.task_id, project_id=self.project_id, revision=self.revision,
                formats=list(self.formats), layers=list(layers), speaker_mode=mode, cue_count=self.cue_count,
                timings_ms={key: round(value * 1000, 3) for key, value in self.work.timings.items()},
                process_peak_bytes=self.work.peak_bytes, files=len(self.artifacts),
                failed_stage=self.work.stage if self.error else '',
                exception_type=self.exception_type,
                cache='task_local_validation', preview_cache='unused'))
            self.snapshot = None
            self._arguments = None
            self.done.set()
