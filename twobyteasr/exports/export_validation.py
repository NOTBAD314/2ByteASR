"""Validate staged production bytes before publishing an output filename."""
import json
import math
import os
import subprocess
import time
from functools import wraps
from inspect import signature
from pathlib import Path
from ..system.processes import popen_hidden_subprocess, run_hidden_subprocess


def positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def completion_statistics(path, metadata):
    """Cross-check the final container rate, never the encoder target/video rate."""
    container = metadata.get('format', {})
    size = Path(path).stat().st_size
    duration = positive_number(container.get('duration'))
    measured = size * 8 / duration if duration else None
    reported = positive_number(container.get('bit_rate'))
    difference = abs(reported - measured) / measured if reported and measured else None
    verified = difference is not None and difference <= .01
    return {
        'size_bytes': size, 'duration_seconds': duration,
        'average_bitrate_bps': reported if verified else measured,
        'metadata_bitrate_bps': reported, 'calculated_bitrate_bps': measured,
        'bitrate_relative_error': difference,
        'bitrate_source': ('ffprobe.format.bit_rate' if verified else
                           'file_bytes*8/container_duration' if measured else 'unavailable'),
    }


def record_completion(function):
    """Own one transient receipt across prepared jobs, route delegation and retry."""
    parameters = signature(function)
    @wraps(function)
    def run(*args, **kwargs):
        arguments=parameters.bind(*args,**kwargs).arguments
        job = arguments['job']
        receipt = job.completion_metadata
        nested = receipt.get('_receipt_active', False)
        if not nested:
            requested_start = receipt.get('requested_started_monotonic')
            receipt.clear()
            receipt.update(started_monotonic=requested_start if requested_start is not None else time.monotonic(),
                           _receipt_active=True)
            observer = kwargs.get('progress')
            def track_progress(payload):
                if payload.get('stage'):
                    job.export_context['active_stage'] = payload['stage']
                job.export_context['last_progress'] = dict(payload)
                if any(key in payload for key in ('out_time_us','out_time_ms','out_time','frame')):
                    job.export_context['media_progress'] = dict(payload)
                if observer:
                    observer(payload)
            if 'progress' in parameters.parameters:
                kwargs['progress'] = track_progress
        log = token = None
        error = None
        from .export_run_log import begin_export_log, end_export_log, note_export
        def event(name,**fields):
            if nested:return
            try:
                from ..diagnostics.event_log import emit
                project=arguments.get('project')
                emit(name,task_id=(getattr(job,'export_context',None) or {}).get('job_id'),
                     project_id=getattr(project,'project_id',None),backend=function.__name__,**fields)
            except Exception:pass
        try:
            graph = getattr(job, "direct_video_graph", None) or getattr(job, "video_graph", None)
            if graph and graph.get('audio_mix') is not None:
                job.export_context['expected_output_audio'] = bool(graph['audio_mix'])
            if not nested and 'ffmpeg_path' in parameters.parameters:
                ffmpeg = parameters.bind(*args, **kwargs).arguments['ffmpeg_path']
                log, token = begin_export_log(ffmpeg, job)
            elif not nested and 'ffmpeg' in parameters.parameters:
                ffmpeg = parameters.bind(*args, **kwargs).arguments['ffmpeg']
                log, token = begin_export_log(ffmpeg, job)
            if log is not None:
                receipt['diagnostics_path'] = str(log.path)
            note_export('render_backend', {'function': function.__name__, 'module': function.__module__})
            from contextlib import nullcontext
            from ..diagnostics.event_log import operation
            event('video.export.started',result='started')
            context=nullcontext() if nested else operation('video.export',task_id=(getattr(job,'export_context',None) or {}).get('job_id'),
                    project_id=getattr(arguments.get('project'),'project_id',None))
            with context:result=function(*args,**kwargs)
            event('video.export.completed',result='completed',stage='published')
            return result
        except BaseException as exc:
            error = exc
            # Once validated bytes have been committed, a late observer or
            # temporary-directory cleanup failure cannot undo that fact.
            published = published_output_path(job)
            from ..diagnostics.event_log import exception_info
            event('video.export.warning' if published is not None else 'video.export.failed',
                  level='WARN' if published is not None else 'ERROR',result='completed' if published is not None else 'failed',
                  stage='after_publication' if published is not None else function.__name__,
                  exception=exception_info(exc))
            if published is not None:
                if isinstance(exc, Exception):
                    _completion_warning(job, 'after_publication', exc)
                    return published
            elif not nested:
                receipt.clear()
            raise
        finally:
            try:
                if log is not None:
                    try:
                        end_export_log(log, token, error)
                    except Exception as exc:
                        if published_output_path(job) is not None:
                            _completion_warning(job, 'export_diagnostics', exc)
                        elif error is None:
                            raise
            finally:
                if not nested:
                    receipt.pop('_receipt_active', None)
    return run


def published_output_path(job):
    receipt = job.completion_metadata
    path = receipt.get('output_path')
    if ('published_monotonic' in receipt and path
            and path == str(Path(job.output_path).resolve())):
        return Path(path)
    return None


def _completion_warning(job, observer, error):
    # Do not store arbitrary callback messages in the successful file receipt.
    job.completion_metadata.setdefault('completion_warnings', []).append({
        'observer': observer, 'exception_type': type(error).__name__})


def notify_after_publication(job, callback, *args):
    """Notify an observer without turning an already-published file into failure."""
    if callback is None:
        return
    try:
        callback(*args)
    except Exception as exc:
        if published_output_path(job) is None:
            raise
        _completion_warning(job, getattr(callback, '__name__', type(callback).__name__), exc)


def publish_output(staged, output, job, metadata, *, cancelled=None):
    """Publish the validated bytes and freeze elapsed time before any UI callback."""
    from .export_run_log import note_export
    note_export('publication_started', {'stage':'publish'})
    publication_started = time.perf_counter()
    output = Path(output).resolve()
    statistics = completion_statistics(staged, metadata)
    frozen = dict(metadata)
    frozen.update(statistics)
    frozen['encoding_statistics'] = {k: getattr(job, 'export_context', {}).get('media_progress', {}).get(k)
        for k in ('frame', 'fps', 'speed', 'out_time_us', 'out_time_ms')}
    from .export_bitrate import target_comparison
    frozen.update(target_comparison(job, metadata))
    frozen.update(output_path=str(output), format=dict(metadata.get('format', {}), filename=str(output)))
    if cancelled and cancelled():
        raise InterruptedError('render cancelled before publication')
    overwrite = bool(job.overwrite_existing)
    if overwrite:
        os.replace(staged, output)
    elif os.name == 'nt':
        # On Windows rename fails atomically if another export created output.
        os.rename(staged, output)
    else:
        # POSIX rename replaces existing files. Same-filesystem hard-link
        # creation provides the required atomic create-if-absent commit instead.
        # All three render routes stage beside/under the output directory.
        os.link(staged, output)
    published = time.monotonic()
    receipt = job.completion_metadata
    receipt.update(frozen)
    receipt.update(published_monotonic=published,
                   elapsed_seconds=max(0.0, published - receipt.get('started_monotonic', published)))
    receipt['publication_seconds'] = time.perf_counter() - publication_started
    from .export_run_log import note_export
    note_export('output_published', dict(output_path=str(output), video_bitrate=frozen.get('video_bitrate'),
        audio_bitrate=frozen.get('audio_bitrate'), container_bitrate_bps=frozen.get('average_bitrate_bps'),
        requested_video_bitrate_bps=frozen.get('requested_video_bitrate_bps'),
        bitrate_target_met=frozen.get('bitrate_target_met')))
    if not overwrite and os.name != 'nt':
        notify_after_publication(job, Path(staged).unlink)


def output_validation_options(job):
    """Transient job controls; no saved project/settings contract changes."""
    context = job.export_context
    graph = job.direct_video_graph or job.video_graph
    audio = context.get('expected_output_audio')
    if graph and graph.get('audio_mix') is not None:
        audio = bool(graph['audio_mix'])
    cuts = []
    if graph:
        origin = float(job.start_seconds or 0)
        cuts = [float(c[k])/1000-origin for t in graph.get('video_tracks', []) if t.get('enabled', True)
                for c in t.get('clips', []) if c.get('enabled', True)
                for k in ('timeline_in_ms', 'timeline_out_ms')]
    return dict(mode=context.get('validation_mode') or os.environ.get('TWOBYTEASR_EXPORT_VALIDATION', 'quick'),
        expected_audio=False if job.settings.audio_codec == 'none' else audio,
        cut_points=cuts)


def _check_cancelled(cancelled):
    if cancelled and cancelled():
        raise InterruptedError('render cancelled before publication')


def _checked_decode(command, path, *, cancelled, timeout, purpose, require_frames=True):
    """No unread pipes, cancellable bounded child lifetime, retained error context."""
    from .export_run_log import note_export
    from ..system.processes import stop_process_tree
    log = path.with_suffix(path.suffix + '.validation.log')
    progress = path.with_suffix(path.suffix + '.validation.progress')
    _check_cancelled(cancelled)
    try:
        with log.open('wb') as stderr, progress.open('wb') as stdout:
            child = popen_hidden_subprocess(command, purpose=purpose, stdout=stdout, stderr=stderr)
            try:
                deadline = time.monotonic() + timeout
                while child.poll() is None:
                    _check_cancelled(cancelled)
                    if time.monotonic() > deadline:
                        raise RuntimeError('导出成片检查超时')
                    time.sleep(.02)
                _check_cancelled(cancelled)
                if child.returncode:
                    raise RuntimeError('导出成片解码检查失败：' + log.read_text(encoding='utf-8', errors='replace')[-1500:])
            finally:
                if child.poll() is None:
                    stop_process_tree(child)
        frames = [int(line.partition('=')[2]) for line in progress.read_text('utf-8', errors='replace').splitlines()
                  if line.startswith('frame=') and line.partition('=')[2].strip().isdigit()]
        if require_frames and not max(frames, default=0):
            raise RuntimeError('导出验证失败：视频检查区间没有可解码帧（可能已截断）')
        return max(frames, default=0)
    finally:
        log.unlink(missing_ok=True)
        progress.unlink(missing_ok=True)


def validation_windows(duration, fps=30, cut_points=()):
    """At most 24 short output intervals; each input gets a real demuxer seek."""
    length = min(.25, duration)
    points = {0., max(0., duration-length), *(duration*f for f in (.25, .5, .75))}
    cuts = sorted({float(p) for p in cut_points if 0 < float(p) < duration})
    # Keep both sides of representative cuts without O(number-of-clips) decodes.
    if len(cuts) > 9:
        cuts = [cuts[round(i*(len(cuts)-1)/8)] for i in range(9)]
    for cut in cuts:
        points.update((max(0., cut-length), cut))
    windows = []
    for start in sorted(points):
        start = min(max(0., start), max(0., duration-length))
        end = min(duration, start+length)
        if windows and start <= windows[-1][1] + 1e-6:
            windows[-1] = (windows[-1][0], max(end, windows[-1][1]))
        else:
            windows.append((start, end))
    return windows


def validate_output(ffmpeg, path, *, duration=None, fps=None, cancelled=None, preview_path='',
                    mode='quick', expected_audio=None, cut_points=()):
    """Inspect staged bytes before publication; quick sampling is never full proof."""
    from .export_run_log import note_export
    from fractions import Fraction
    if mode not in {'quick', 'full'}:
        raise ValueError('validation mode must be quick or full')
    started = time.monotonic()
    note_export('validation_started', {'stage': 'validate', 'mode': mode})
    ffmpeg, path = Path(ffmpeg), Path(path)
    _check_cancelled(cancelled)
    result = run_hidden_subprocess([str(ffmpeg.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')),
        '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
        purpose='validate staged export metadata', capture_output=True, check=True, timeout=15)
    _check_cancelled(cancelled)
    data = json.loads(result.stdout)
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if video is None:
        raise RuntimeError('导出验证失败：缺少视频流')
    audio = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']
    if expected_audio is True and not audio:
        raise RuntimeError('导出验证失败：缺少应有的音频流')
    if expected_audio is False and audio:
        raise RuntimeError('导出验证失败：禁用音频的成片仍含音频流')
    try:
        rate = positive_number(fps) or positive_number(Fraction(video.get('avg_frame_rate') or '0')) or 30
    except (ValueError, ZeroDivisionError, TypeError):
        rate = positive_number(fps) or 30
    tolerance = max(.05, 2/rate)
    stream_duration = positive_number(video.get('duration'))
    if duration and stream_duration and abs(stream_duration-duration) > tolerance:
        raise RuntimeError('导出验证失败：视频时长与工程范围不一致')
    if duration and fps and video.get('nb_frames') not in (None, 'N/A'):
        expected = round(duration*fps)
        if abs(int(video['nb_frames'])-expected) > 1:
            raise RuntimeError(f'导出验证失败：帧数 {video["nb_frames"]} 与范围 {expected} 不一致')
    # The fallback packet extent remains mandatory when stream metadata is absent.
    # Never substitute a longer audio/container duration for video presentation.
    from .export_bitrate import export_bitrate_measurements
    data.update(export_bitrate_measurements(ffmpeg, path, data, cancelled=cancelled, full_scan=mode == 'full'))
    measured = data.get('video_bitrate') or {}
    video_duration = positive_number(measured.get('duration_seconds')) or stream_duration
    if duration and video_duration and abs(video_duration-duration) > tolerance:
        raise RuntimeError(f'导出验证失败：视频实际时间轴时长 {video_duration:.3f} 秒，'
                           f'与工程范围 {duration:.3f} 秒不一致（可能存在速度异常），已停止发布')
    if video_duration is None:
        raise RuntimeError('导出验证失败：无法确认独立视频时间轴时长')
    decode_started = time.monotonic()
    decoded = []
    windows = [(0., video_duration)] if mode == 'full' else validation_windows(video_duration, rate, cut_points)
    for start, end in windows:
        command = [str(ffmpeg), '-v', 'error', '-xerror', '-nostdin']
        if mode == 'quick':
            command += ['-ss', f'{start:.9f}']
        command += ['-i', str(path)]
        if mode == 'quick':
            command += ['-t', f'{end-start:.9f}']
        command += ['-map', '0:v:0', '-map', '0:a?', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
        frames = _checked_decode(command, path, cancelled=cancelled,
            timeout=max(30, video_duration*2) if mode == 'full' else 30,
            purpose='complete staged export decode' if mode == 'full' else 'bounded staged export decode')
        decoded.append(dict(start_seconds=start, end_seconds=end, decoded_video_frames=frames))
    decode_seconds = time.monotonic() - decode_started
    # A poster is independent of integrity checking and has its own bounded input.
    preview_seconds = 0.
    if preview_path:
        at = time.monotonic()
        command = [str(ffmpeg), '-v', 'error', '-nostdin', '-y', '-ss', '0', '-t', f'{min(3., video_duration):.9f}',
            '-i', str(path), '-map', '0:v:0', '-an', '-vf',
            r'scale=w=min(iw\,3840):h=-2:flags=lanczos,blackframe=amount=0:threshold=24,metadata=mode=select:key=lavfi.blackframe.pblack:value=95:function=less',
            '-frames:v', '1', '-c:v', 'mjpeg', '-pix_fmt', 'yuvj420p', '-q:v', '2', '-update', '1',
            '-progress', 'pipe:1', '-nostats', str(preview_path)]
        _checked_decode(command, path, cancelled=cancelled, timeout=30,
            purpose='bounded export completion poster', require_frames=False)
        preview_seconds = time.monotonic() - at
    data['validation'] = dict(mode=mode, full_decode=mode == 'full',
        coverage='complete_video_and_audio_decode' if mode == 'full' else 'metadata_and_bounded_samples',
        windows=decoded, decode_seconds=decode_seconds, preview_seconds=preview_seconds,
        bitrate_seconds=data.get('bitrate_measurement_seconds', 0.), seconds=time.monotonic()-started)
    note_export('validation_finished', data['validation'])
    return data
