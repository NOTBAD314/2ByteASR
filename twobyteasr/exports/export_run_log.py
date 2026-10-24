"""Durable, job-owned evidence captured at actual child-process boundaries."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
import json
import hashlib
import os
import subprocess
from pathlib import Path
import threading
import uuid
import time

_CURRENT = ContextVar('studio_export_log', default=None)


def current_export_log():
    return _CURRENT.get()


@lru_cache(maxsize=16)
def _version(binary, size, mtime_ns):
    from ..system.processes import run_hidden_subprocess
    try:
        result = run_hidden_subprocess([binary, '-version'], purpose='export FFmpeg version',
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
        return str(result.stdout or '').splitlines()[0] if result.returncode == 0 else 'unavailable'
    except (OSError, RuntimeError, IndexError, TimeoutError):
        return 'unavailable'
    except subprocess.TimeoutExpired:
        return 'unavailable'


class ExportRunLog:
    def __init__(self, ffmpeg, job):
        from ..projects.studio_project import studio_data_root
        context = job.export_context
        context.setdefault('job_id', uuid.uuid4().hex)
        context.setdefault('requested_encoder', job.settings.encoder)
        context.setdefault('requested_settings', asdict(job.settings))
        if 'project_revision' not in context:
            import hashlib
            context['project_revision'] = ('sha256:' + hashlib.sha256(json.dumps(job.export_project_data,
                ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
                if job.export_project_data else 'unavailable')
        # A log name is an internal identifier, never an arbitrary user path.
        identity = ''.join(c for c in str(context['job_id']) if c.isalnum() or c in '-_')[:100]
        root = Path(os.environ.get('TWOBYTEASR_EXPORT_LOG_ROOT') or studio_data_root() / 'logs' / 'exports')
        self.path = root / (identity or uuid.uuid4().hex) / uuid.uuid4().hex
        self.path.mkdir(parents=True, exist_ok=True)
        context['diagnostics_path'] = str(self.path)
        self._lock = threading.RLock()
        self._serial = 0
        self._process_logs = []
        self.job = job
        binary = Path(ffmpeg).resolve()
        try:
            stat = binary.stat()
            version = _version(str(binary), stat.st_size, stat.st_mtime_ns)
        except OSError:
            version = 'unavailable'
        self.manifest = dict(context, ffmpeg_path=str(binary), ffmpeg_version=version,
            input_path=str(job.media_path), output_path=str(Path(job.output_path).resolve()),
            settings=asdict(job.settings), target_video_bitrate_bps=(int(job.settings.bitrate_kbps) * 1000
                if job.settings.quality_mode in {'target', 'limited', 'vbr', 'cbr'} else None),
            max_video_bitrate_bps=(int(job.settings.max_bitrate_kbps) * 1000
                if job.settings.quality_mode in {'limited', 'vbr'} else None))
        import sys
        runtime = dict(executable_path=sys.executable, argv0=sys.argv[0],
            packaged=bool(getattr(sys, 'frozen', False)), module_path=__file__)
        if runtime['packaged']:
            try:
                runtime.update(json.loads((Path(sys.executable).parent/'2byteasr_build.json').read_text(encoding='utf-8')))
            except (OSError, ValueError): runtime['build_metadata'] = 'unavailable'
        self.manifest.update(runtime=runtime, worker_pid=os.getpid(), worker_thread=threading.current_thread().name,
            burn_in=dict(enabled=bool(job.ass_path), cue_count=len((job.export_project_data or {}).get('cues', [])),
                visibility=(job.export_project_data or {}).get('studio_state', {}).get('subtitle_track_visibility', {})))
        self.note('job_started', self.manifest)
        self._save_manifest()

    def _save_manifest(self):
        with self._lock:
            from ..providers.provider_diagnostics import redact_diagnostics
            (self.path / 'manifest.json').write_text(json.dumps(redact_diagnostics(self.manifest),
                ensure_ascii=False, indent=2), encoding='utf-8')

    def note(self, event, payload):
        from ..providers.provider_diagnostics import redact_diagnostics
        record = dict(timestamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            job_id=self.job.export_context['job_id'], event=event, payload=payload)
        with self._lock, (self.path / 'processes.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(redact_diagnostics(record), ensure_ascii=False) + '\n')
            stream.flush()

    def process_started(self, command, purpose, process, cwd=None, redirected=None,
                        capture_stdout=True, stderr_merged=False):
        from ..diagnostics.process_diagnostics import _safe_command
        with self._lock:
            self._serial += 1
            identity = f'{self._serial:03d}'
        argv = [str(x) for x in command]
        filter_scripts = self._capture_filter_scripts(argv, identity, getattr(process, 'pid', None), cwd)
        # This receives the exact list passed to Popen, after preview/script rewrites.
        encoder = argv[argv.index('-c:v') + 1] if '-c:v' in argv else None
        encoding = dict(actual_encoder=encoder,
            rate_control=('crf' if '-crf' in argv else 'cq' if any(x in argv for x in ('-cq', '-qp_i', '-global_quality'))
                          else self.job.settings.quality_mode if '-b:v' in argv else None),
            bitrate_argument=(argv[argv.index('-b:v') + 1] if '-b:v' in argv else None),
            maxrate_argument=(argv[argv.index('-maxrate') + 1] if '-maxrate' in argv else None),
            bufsize_argument=(argv[argv.index('-bufsize') + 1] if '-bufsize' in argv else None),
            encoder_rate_control=(argv[argv.index('-rc') + 1] if '-rc' in argv else None))
        self.note('process_started', dict(process_id=identity, phase='start', pid=getattr(process, 'pid', None),
            purpose=purpose, argv=_safe_command(argv), command=_safe_command(argv), cwd=str(cwd or Path.cwd()),
            stdout_payload_logged=capture_stdout, stderr_merged_with_stdout=stderr_merged,
            stdout_log=f'{identity}.stdout.log' if capture_stdout else None,
            stderr_log=f'{identity}.stdout.log' if stderr_merged else f'{identity}.stderr.log',
            filter_scripts=filter_scripts, **encoding))
        final_encoders = {'libx264', 'libx265', 'libaom-av1', 'libsvtav1', 'h264_nvenc', 'hevc_nvenc',
            'av1_nvenc', 'h264_qsv', 'hevc_qsv', 'av1_qsv', 'h264_amf', 'hevc_amf', 'av1_amf'}
        if encoder in final_encoders and purpose in {'ffmpeg studio render', 'advanced preview/render child'}:
            self.manifest['last_encoding'] = dict(purpose=purpose, **encoding)
            self.job.completion_metadata.update(actual_encoder=encoder, actual_rate_control=encoding['rate_control'])
            self._save_manifest()
        log=ProcessLog(self, identity, redirected or {}, capture_stdout)
        if encoder in final_encoders and '-progress' in argv:
            from .encoding_observer import EncodingObserver
            from fractions import Fraction
            fps = float(Fraction(argv[argv.index('-r')+1])) if '-r' in argv else self.job.settings.fps
            log.observer = EncodingObserver(self.path/f'{identity}.encoding.jsonl', process.pid,
                fps=fps, duration=self.job.duration_seconds, encoder=encoder,
                context=dict(project=self.job.export_project_data, start_seconds=self.job.start_seconds))
        self._process_logs.append(log)
        return log

    def _capture_filter_scripts(self, argv, identity, pid, cwd):
        """Retain only files referenced by the actual FFmpeg launch arguments."""
        from ..providers.provider_diagnostics import redact_diagnostics
        evidence = []
        for index, option in enumerate(argv):
            if option not in {'-/filter_complex', '-filter_complex_script'}:
                continue
            argument = argv[index + 1] if index + 1 < len(argv) else None
            record = dict(option=option, argument=argument)
            evidence.append(record)
            if argument is None:
                record['read_error'] = 'Missing filter script argument'
                continue
            try:
                source = Path(argument)
                if not source.is_absolute():
                    source = Path(cwd or Path.cwd()) / source
                source = source.resolve()
                record['resolved_path'] = str(source)
                raw = source.read_bytes()
                record.update(source_sha256=hashlib.sha256(raw).hexdigest(), source_bytes=len(raw))
                saved = redact_diagnostics(raw.decode('utf-8', errors='replace')).encode('utf-8')
                # All writes stay in the job-owned diagnostics directory, regardless of argv paths.
                stem = str(pid) if isinstance(pid, int) and pid >= 0 else f'process-{identity}'
                suffix = '' if len(evidence) == 1 else f'.{len(evidence)}'
                destination = self.path / f'{stem}{suffix}.filter_complex.txt'
                if destination.exists():
                    destination = self.path / f'{stem}.{identity}{suffix}.filter_complex.txt'
                destination.write_bytes(saved)
                record.update(saved_path=str(destination), saved_sha256=hashlib.sha256(saved).hexdigest(),
                    saved_bytes=len(saved), text_encoding='utf-8', redacted=True)
            except (OSError, ValueError) as error:
                record['read_error'] = f'{type(error).__name__}: {error}'
        return evidence

    def finish(self, error=None):
        for log in self._process_logs:log.finish()
        self.note('job_finished', dict(error_type=type(error).__name__ if error else None,
            published=bool(self.job.completion_metadata.get('output_path'))))


class ProcessLog:
    def __init__(self, owner, identity, redirected, capture_stdout=True):
        self.owner, self.identity, self.redirected = owner, identity, redirected
        self.capture_stdout = capture_stdout
        self._buffers = {}
        self._sizes = {}
        self._last_flush = 0.
        self._exited = False
        self.observer = None
        import queue
        self._queue = queue.Queue(maxsize=1024)
        self._done = threading.Event()
        self._drained = threading.Event()
        self.dropped_chunks = 0
        self.write_error = None
        self._writer = threading.Thread(target=self._write_loop, daemon=True, name='export-log-writer')
        self._writer.start()

    def _write_loop(self):
        import queue
        from ..providers.provider_diagnostics import redact_diagnostics
        while not self._done.is_set() or not self._queue.empty():
            try:
                channel, text = self._queue.get(timeout=.1)
            except queue.Empty:
                self._drained.set()
                continue
            try:
                text = redact_diagnostics(text)
                self._buffers.setdefault(channel, []).append(text)
                self._sizes[channel] = self._sizes.get(channel, 0)+len(text)
                if self._sizes[channel] >= 32768 or self._queue.empty(): self._write_buffers()
            except Exception as exc:
                self.write_error = f'{type(exc).__name__}: {exc}'
            finally:
                self._queue.task_done()
                if self._queue.empty(): self._drained.set()
        self._write_buffers()

    def _write_buffers(self):
        for channel, chunks in self._buffers.items():
            if chunks:
                with (self.owner.path/f'{self.identity}.{channel}.log').open('a', encoding='utf8') as stream:
                    stream.write(''.join(chunks))
                chunks.clear();self._sizes[channel]=0

    def finish(self):
        if self.observer: self.observer.close()
        self.flush()
        self._done.set();self._writer.join(timeout=2)
        if self.dropped_chunks or self.write_error:
            self.owner.note('diagnostics_incomplete', dict(process_id=self.identity,
                dropped_chunks=self.dropped_chunks, write_error=self.write_error))

    def flush(self):
        if self._queue.unfinished_tasks:
            self._drained.wait(timeout=2)

    def output(self, channel, value):
        if not value:
            return
        if channel == 'stdout' and not self.capture_stdout:
            return  # Raw video/PCM/image pixels are media payload, never diagnostics.
        text = value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value)
        if channel == 'stdout' and self.observer: self.observer.feed(text)
        import queue
        for offset in range(0, len(text), 32768):
            self._drained.clear()
            try: self._queue.put_nowait((channel, text[offset:offset+32768]))
            except queue.Full: self.dropped_chunks += 1

    def exited(self, code):
        self._exited=True
        if self.observer: self.observer.close()
        # File redirects (FFV1/decode) are copied before their temp directories disappear.
        for channel, filename in self.redirected.items():
            try:
                self.output(channel, Path(filename).read_bytes())
            except (OSError, TypeError):
                pass
        self.flush()
        self.owner.note('process_exited', dict(process_id=self.identity, phase='exit', returncode=code))


class LoggedPipe:
    """Transparent pipe reader; its logger is captured before drain threads start."""
    def __init__(self, stream, log, channel):
        self.stream, self.log, self.channel = stream, log, channel

    def __iter__(self):
        return self

    def __next__(self):
        value = next(self.stream)
        self.log.output(self.channel, value)
        return value

    def readline(self, *args, **kwargs):
        value = self.stream.readline(*args, **kwargs)
        self.log.output(self.channel, value)
        return value

    def read(self, *args, **kwargs):
        value = self.stream.read(*args, **kwargs)
        self.log.output(self.channel, value)
        return value

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)


def begin_export_log(ffmpeg, job):
    logger = ExportRunLog(ffmpeg, job)
    return logger, _CURRENT.set(logger)


def end_export_log(logger, token, error=None):
    try:
        logger.finish(error)
    finally:
        _CURRENT.reset(token)


def note_export(event, payload):
    logger = current_export_log()
    if logger is not None:
        logger.note(event, payload)
        if event == 'render_backend':
            logger.manifest['render_backend'] = payload
            logger._save_manifest()
