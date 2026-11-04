"""Opt-in NVENC video segments; one continuous audio encode and atomic delivery.

Only the existing native ASS/direct-video graph is partitioned. Every boundary
is on its exact output frame grid. Subtitle timestamps stay in project time.
No persisted project/settings field or automatic hardware concurrency change.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time


def requested_segments(job):
    raw = job.export_context.get('parallel_segments', os.environ.get('TWOBYTEASR_EXPORT_SEGMENTS', '1'))
    try:
        return max(1, min(2, int(raw)))
    except (ValueError, TypeError):
        return 1


def parallel_native_supported(job):
    return (requested_segments(job) > 1 and job.settings.encoder.endswith('_nvenc')
            and job.settings.container in {'mp4', 'mov', 'mkv'}
            and job.settings.fps > 0 and (job.duration_seconds or 0) > 0
            and not job.composition_resolved and not job.edit_segments)


def frame_partitions(duration, fps, count=2):
    rate = Fraction(str(fps)).limit_denominator(100100)
    frames = math.ceil(Fraction(str(duration))*rate)
    count = min(count, frames)
    return [(i*frames//count, (i+1)*frames//count) for i in range(count)]


def reserved_moov_bytes(duration, fps, sample_rate=48000, audio_streams=1):
    """Bounded room for sample tables at the front, without rewriting the mdat.

    64 bytes per possible video/audio packet plus 1 MiB metadata headroom is
    conservative for our single mixed audio stream. Very large jobs keep the
    established faststart path. A rare undersized header retries faststart.
    """
    packets = math.ceil(duration*fps) + math.ceil(duration*sample_rate/960)*audio_streams + 16
    size = math.ceil((packets*64 + 1024**2)/1024**2)*1024**2
    return size if duration >= 60 and size <= 128*1024**2 else 0


def _segment_metadata(ffmpeg, path, frames, rate, cancelled):
    from .export_validation import _check_cancelled
    from ..system.processes import run_hidden_subprocess
    _check_cancelled(cancelled)
    result = run_hidden_subprocess([str(Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')),
        '-v','error','-select_streams','v:0','-show_streams','-of','json',str(path)],
        purpose='parallel encoded segment metadata', capture_output=True, check=True, timeout=15)
    _check_cancelled(cancelled)
    streams = json.loads(result.stdout).get('streams', [])
    if not streams or int(streams[0].get('nb_frames') or 0) != frames:
        raise RuntimeError('并行导出分段帧数不完整，已停止发布')
    stream = streams[0]
    if abs(float(stream.get('duration') or 0)-float(Fraction(frames)/rate)) > max(.05, 1/float(rate)):
        raise RuntimeError('并行导出分段时长不正确，已停止发布')
    return {k: stream.get(k) for k in ('codec_name','profile','level','pix_fmt','width','height',
        'sample_aspect_ratio','avg_frame_rate','time_base','color_range','color_space',
        'color_transfer','color_primaries','chroma_location')}


def render_parallel_native(ffmpeg, job, *, progress=None, cancelled=None, trace=None):
    from .studio_render import build_render_command, export_progress, media_has_audio
    from ..rendering.advanced_renderer import _run_streaming_process
    from .export_validation import (validate_output, output_validation_options, publish_output,
                                    notify_after_publication, _check_cancelled)
    from .export_failure import ffmpeg_failure
    from .export_run_log import note_export
    from .export_performance import export_phase
    if 'expected_output_audio' not in job.export_context:
        job.export_context['expected_output_audio'] = job.settings.audio_codec != 'none' and (
            bool(job.direct_video_graph['audio_mix']) if job.direct_video_graph else media_has_audio(ffmpeg, job.media_path))
    output = Path(job.output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    rate = Fraction(str(job.settings.fps)).limit_denominator(100100)
    parts = frame_partitions(job.duration_seconds, rate, requested_segments(job))
    stopped = threading.Event()
    def stop_requested():
        return stopped.is_set() or bool(cancelled and cancelled())
    note_export('export_route', dict(route='parallel_native', segments=len(parts),
        reason='explicit opt-in; exact frame ranges; continuous audio in final mux',
        frame_partitions=parts, live_preview='completion poster only'))
    if progress:
        progress({'notice':'并行编码已启用，完成后显示成片预览。'})
    with tempfile.TemporaryDirectory(prefix='.parallel-video-', dir=output.parent) as folder:
        folder = Path(folder)
        files = [folder/f'segment-{i:03}.mp4' for i in range(len(parts))]
        counts, lock = [0]*len(parts), threading.Lock()
        def encode(i):
            first, last = parts[i]
            part = replace(job, output_path=str(files[i]),
                start_seconds=float(Fraction(str(job.start_seconds or 0))+Fraction(first)/rate),
                duration_seconds=float(Fraction(last-first)/rate),
                settings=replace(job.settings, audio_codec='none', container='mp4'),
                completion_metadata={}, completion_preview_path='', preview_callback=None, preview_url='',
                export_context=dict(job.export_context, parallel_segments=1))
            command = build_render_command(ffmpeg, part)
            # These private segments are read only after successful close.
            # Moving each segment's moov to its head wastes another full copy.
            if '-movflags' in command:
                at = command.index('-movflags')
                if command[at+1] == '+faststart':del command[at:at+2]
            def line(value):
                key, separator, raw = value.partition('=')
                if separator and key == 'frame':
                    with lock:counts[i] = min(last-first, max(counts[i], int(raw.strip() or 0)))
            code, logs = _run_streaming_process(command, on_line=line, cancelled=stop_requested,
                                               purpose='ffmpeg studio render')
            if code:
                raise ffmpeg_failure(code, logs, encoder=job.settings.encoder, fps=float(rate))
            metadata = _segment_metadata(ffmpeg, files[i], last-first, rate, stop_requested)
            with lock:counts[i] = last-first
            return metadata
        encoding_started = time.monotonic()
        with export_phase('parallel_video_encode', segments=len(parts),
                          overlaps='each segment decode+ASS+encode+mux; video-only segments'):
            with ThreadPoolExecutor(max_workers=len(parts), thread_name_prefix='parallel-export') as executor:
                futures = [executor.submit(copy_context().run, encode, i) for i in range(len(parts))]
                last_report = 0.
                try:
                    while not all(f.done() for f in futures):
                        if cancelled and cancelled():stopped.set()
                        for future in futures:
                            if future.done() and future.exception() is not None:
                                stopped.set()
                        with lock:done = sum(counts)
                        elapsed = max(.001, time.monotonic()-encoding_started)
                        if progress and time.monotonic()-last_report >= .5:
                            last_report = time.monotonic()
                            progress(export_progress('encode', message='并行合成与编码…',
                                out_time_us=round(done/float(rate)*1e6), frame=str(done),
                                fps=f'{done/elapsed:.2f}', speed=f'{done/float(rate)/elapsed:.3f}x',
                                duration_seconds=job.duration_seconds, indeterminate=False))
                        time.sleep(.1)
                    _check_cancelled(cancelled)
                    errors = [f.exception() for f in futures if f.exception() is not None]
                    if errors:
                        # A peer stopped because another encoder failed. Keep the
                        # original failure instead of reporting that peer as a user cancellation.
                        raise next((e for e in errors if not isinstance(e, InterruptedError)), errors[0])
                    metadata = [f.result() for f in futures]
                finally:
                    stopped.set()
        encode_elapsed = max(.001, time.monotonic()-encoding_started)
        if progress:
            progress(export_progress('encode', message='并行视频编码完成',
                out_time_us=round(job.duration_seconds*1e6), frame=str(sum(b-a for a,b in parts)),
                fps=f'{sum(b-a for a,b in parts)/encode_elapsed:.2f}',
                speed=f'{job.duration_seconds/encode_elapsed:.3f}x',
                duration_seconds=job.duration_seconds, indeterminate=False))
        if any(m != metadata[0] for m in metadata[1:]):
            raise RuntimeError('并行导出分段的编码规格不一致，已停止发布')
        _check_cancelled(cancelled)
        playlist = folder/'video.ffconcat'
        playlist.write_text('ffconcat version 1.0\n'+''.join(f"file '{p.name}'\n" for p in files), encoding='utf8')
        partial = folder/('output.partial'+output.suffix)
        command = [str(ffmpeg),'-hide_banner','-loglevel','level+info','-xerror','-y',
                   '-f','concat','-safe','0','-i',str(playlist)]
        audio_label, audio_filters, audio_inputs = None, [], []
        audio_codec = job.settings.audio_codec
        if audio_codec != 'none':
            if job.direct_video_graph:
                from .audio_export import compile_audio_mix
                audio_inputs, audio_filters, audio_label = compile_audio_mix(ffmpeg, job,
                    job.direct_video_graph['audio_mix'], input_offset=1)
                if audio_codec == 'copy':audio_codec = 'opus' if job.settings.container == 'webm' else 'aac'
            else:
                if job.start_seconds:audio_inputs += ['-ss',f'{job.start_seconds:.9f}']
                audio_inputs += ['-i',job.media_path]
                audio_label = '1:a?'
        command += audio_inputs
        if audio_filters:command += ['-filter_complex',';'.join(audio_filters)]
        command += ['-map','0:v:0','-c:v','copy']
        if audio_label:
            command += ['-map',audio_label,'-c:a','libopus' if audio_codec == 'opus' else audio_codec]
            if audio_codec != 'copy':
                command += ['-b:a',f'{job.settings.audio_bitrate_kbps}k']
                if job.settings.audio_sample_rate:command += ['-ar',str(job.settings.audio_sample_rate)]
                if job.settings.audio_channels:command += ['-ac',str(job.settings.audio_channels)]
        else:command += ['-an']
        command += ['-t',f'{job.duration_seconds:.9f}']
        reserve = 0
        if job.settings.container in {'mp4','mov'}:
            # Graph audio is one mixed output. Legacy multi-audio input maps
            # retain faststart rather than guessing their sample-table budget.
            if job.direct_video_graph or not audio_label:
                reserve = reserved_moov_bytes(job.duration_seconds, float(rate),
                    job.settings.audio_sample_rate or 48000, int(bool(audio_label)))
            command += ['-moov_size',str(reserve)] if reserve else ['-movflags','+faststart']
        command += ['-progress','pipe:1','-nostats',str(partial)]
        if trace:trace('parallel_final_mux_command', command)
        if progress:progress(export_progress('encode', stage_label='封装文件', message='拼接视频并连续处理音频…', percent=100, indeterminate=True))
        job.export_context['active_stage'] = 'mux'
        with export_phase('parallel_join_and_audio', video='stream copy', audio='one continuous pass',
                          segment_bytes=sum(p.stat().st_size for p in files), moov_reserved_bytes=reserve):
            code, logs = _run_streaming_process(command, cancelled=cancelled, purpose='parallel export final mux')
            if code and reserve and any(s in str(logs).lower() for s in (
                    'reserved_moov_size is too small', 'not enough room for moov atom')):
                _check_cancelled(cancelled)
                note_export('mux_retry', dict(reason='reserved moov space insufficient', layout='faststart'))
                partial.unlink(missing_ok=True)
                at = command.index('-moov_size')
                command[at:at+2] = ['-movflags','+faststart']
                code, logs = _run_streaming_process(command, cancelled=cancelled, purpose='parallel export final mux retry')
        if code:raise ffmpeg_failure(code, logs, encoder=job.settings.encoder, fps=float(rate))
        if progress:progress(export_progress('validate', message='检查成片…'))
        options = output_validation_options(job)
        options['cut_points'] += [first/float(rate) for first, _ in parts[1:]]
        metadata = validate_output(ffmpeg, partial, duration=job.duration_seconds, fps=float(rate),
            cancelled=cancelled, preview_path=job.completion_preview_path, **options)
        metadata['parallel_temporary_media_bytes'] = sum(p.stat().st_size for p in files)+partial.stat().st_size
        publish_output(partial, output, job, metadata, cancelled=cancelled)
        note_export('parallel_video_finished', dict(segments=len(parts), encoded_frames=sum(b-a for a,b in parts)))
        notify_after_publication(job, progress, export_progress('mux', message='导出完成', percent=100))
    return output
