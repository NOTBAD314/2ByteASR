"""Validate staged production bytes before publishing an output filename."""
import json
import math
import os
import subprocess
import time
from functools import wraps
from inspect import signature
from pathlib import Path
from .processes import popen_hidden_subprocess, run_hidden_subprocess


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
        job = parameters.bind(*args, **kwargs).arguments['job']
        receipt = job.completion_metadata
        nested = receipt.get('_receipt_active', False)
        if not nested:
            requested_start = receipt.get('requested_started_monotonic')
            receipt.clear()
            receipt.update(started_monotonic=requested_start if requested_start is not None else time.monotonic(),
                           _receipt_active=True)
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            # Once validated bytes have been committed, a late observer or
            # temporary-directory cleanup failure cannot undo that fact.
            published = published_output_path(job)
            if published is not None:
                if isinstance(exc, Exception):
                    _completion_warning(job, 'after_publication', exc)
                    return published
            elif not nested:
                receipt.clear()
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
    output = Path(output).resolve()
    statistics = completion_statistics(staged, metadata)
    frozen = dict(metadata)
    frozen.update(statistics)
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
    if not overwrite and os.name != 'nt':
        notify_after_publication(job, Path(staged).unlink)


def validate_output(ffmpeg, path, *, duration=None, fps=None, cancelled=None, preview_path=''):
    ffmpeg=Path(ffmpeg);path=Path(path)
    result=run_hidden_subprocess([str(ffmpeg.with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')),
        '-v','error','-show_format','-show_streams','-of','json',str(path)],
        purpose='validate staged export metadata',capture_output=True,check=True,timeout=15)
    data=json.loads(result.stdout);video=next(s for s in data['streams'] if s['codec_type']=='video')
    if duration and abs(float(video.get('duration',data['format']['duration']))-duration)>max(.05,2/(fps or 30)):
        raise RuntimeError('导出验证失败：视频时长与工程范围不一致')
    if duration and fps and video.get('nb_frames') not in (None, 'N/A'):
        expected = round(duration * fps)
        if abs(int(video['nb_frames']) - expected) > 1:
            raise RuntimeError(f'导出验证失败：帧数 {video["nb_frames"]} 与范围 {expected} 不一致')
    log=path.with_suffix(path.suffix+'.validation.log')
    try:
        with log.open('wb') as stderr:
            command=[str(ffmpeg),'-v','error','-xerror','-y','-i',str(path),
                '-map','0:v:0','-map','0:a?','-f','null','-']
            if preview_path:
                from fractions import Fraction
                try:rate=float(Fraction(video.get('avg_frame_rate') or '30'))
                except (ValueError,ZeroDivisionError):rate=float(fps or 30)
                if rate<=0:rate=float(fps or 30)
                try:total_frames=int(video.get('nb_frames'))
                except (TypeError,ValueError):total_frames=round(float(duration or data['format'].get('duration') or 1)*rate)
                frame=max(0,min(round(rate),total_frames-1))
                command += ['-map','0:v:0','-vf',f'select=gte(n\\,{frame}),scale=640:-2,blackframe=amount=0:threshold=24,metadata=mode=select:key=lavfi.blackframe.pblack:value=95:function=less',
                    '-frames:v','1','-c:v','mjpeg','-pix_fmt','yuvj420p','-q:v','3','-update','1',str(preview_path)]
            child=popen_hidden_subprocess(command,purpose='complete staged export decode',
                stdout=subprocess.DEVNULL,stderr=stderr)
            try:
                deadline=time.monotonic()+max(30,float(duration or 0)*2)
                while child.poll() is None:
                    if cancelled and cancelled():raise InterruptedError('render cancelled')
                    if time.monotonic()>deadline:raise RuntimeError('导出完整解码验证超时')
                    time.sleep(.05)
                if child.returncode:raise RuntimeError('导出完整解码验证失败：'+log.read_text(encoding='utf-8',errors='replace')[-1500:])
            finally:
                if child.poll() is None:child.kill();child.wait()
        return data
    finally:
        log.unlink(missing_ok=True)
