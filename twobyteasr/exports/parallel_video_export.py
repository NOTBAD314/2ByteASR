"""Opt-in NVENC video segments; concurrent continuous audio and atomic delivery.

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
import shutil
from pathlib import Path
import tempfile
import threading
import time


def requested_segments(job):
    raw = job.export_context.get('parallel_segments', os.environ.get('TWOBYTEASR_EXPORT_SEGMENTS', '0'))
    try:
        return 0 if str(raw).lower()=='auto' else max(0, min(2, int(raw)))
    except (ValueError, TypeError):
        return 1


def parallel_native_supported(job, ffmpeg_path=None):
    from .parallel_export_policy import parallel_decision
    decision = parallel_decision(job,ffmpeg_path)
    job.export_context['parallel_decision'] = decision
    job.completion_metadata['parallel_selection'] = decision
    job.completion_metadata['parallel_segments'] = decision['segments']
    from .export_run_log import note_export
    note_export('parallel_selection', decision)
    return decision['segments'] > 1


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


def release_private_media(path, role, reason):
    """Early release is optional; a transient Windows reader must not fail QA."""
    from .export_run_log import note_export
    try:
        size = path.stat().st_size
        path.unlink()
        note_export('temporary_media_released', dict(role=role, bytes=size, reason=reason))
        return True
    except OSError as error:
        note_export('temporary_media_release_deferred', dict(role=role,
            reason='private-directory cleanup will retry', error_type=type(error).__name__))
        return False


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
    from .studio_render import build_render_command, export_progress, media_has_audio, select_encoder
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
    parts = frame_partitions(job.duration_seconds, rate, int((job.export_context.get('parallel_decision') or {}).get('segments') or requested_segments(job) or 1))
    sources = ({str(Path(job.media_path).resolve())}
               if job.media_path and Path(job.media_path).is_file() else set())
    if job.direct_video_graph:
        # A project pool can retain offline/hidden/out-of-range assets. Recovery
        # depends only on the video inputs actually used by this output range.
        first_ms = float(job.start_seconds or 0)*1000
        last_ms = first_ms+float(job.duration_seconds)*1000
        used = {c['asset_id'] for t in job.direct_video_graph.get('video_tracks', [])
                if t.get('enabled', True) for c in t.get('clips', [])
                if c.get('enabled', True) and c['timeline_out_ms'] > first_ms
                and c['timeline_in_ms'] < last_ms}
        sources = {str(Path(a['canonical_source']).resolve())
            for a in job.direct_video_graph.get('media_pool', [])
            if a['asset_id'] in used and a.get('canonical_source')}
    def source_identity():
        records = []
        for path in sorted(sources):
            stat = Path(path).stat()
            records.append((path, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
        return records
    original_sources = source_identity()
    stopped = threading.Event()
    def stop_requested():
        return stopped.is_set() or bool(cancelled and cancelled())
    note_export('export_route', dict(route='parallel_native', segments=len(parts),
        reason=(job.export_context.get('parallel_decision') or {}).get('reason') or 'explicit selection; exact frame ranges; continuous audio overlaps video',
        frame_partitions=parts, live_preview='completion poster only'))
    if progress:
        progress({'notice':'并行编码已启用，完成后显示成片预览。'})
    # Warm the selected encoder's probe once before workers compete for it.
    select_encoder(ffmpeg, job.settings)
    with tempfile.TemporaryDirectory(prefix='.parallel-video-', dir=output.parent) as folder:
        folder = Path(folder)
        files = [folder/f'segment-{i:03}.mp4' for i in range(len(parts))]
        counts, lock = [0]*len(parts), threading.Lock()
        from .parallel_audio_export import continuous_audio_command, audio_source_staging_plan, staged_audio_matches
        audio = continuous_audio_command(ffmpeg, job, folder)
        staging, source_decision = audio_source_staging_plan(ffmpeg, job, audio, folder)
        note_export('parallel_audio_source_selection', source_decision)
        source_bytes = 0
        if staging:
            _check_cancelled(cancelled)
            if progress: progress(export_progress('prepare_project', message='准备独立连续音轨…', indeterminate=True))
            if trace: trace('parallel_audio_source_command', staging['command'])
            with export_phase('parallel_audio_source_staging', codec='AAC stream copy', overlaps='before video starts'):
                code, logs = _run_streaming_process(staging['command'], cancelled=stop_requested,
                    purpose='parallel export audio source staging')
                if code: raise ffmpeg_failure(code, logs, encoder=job.settings.encoder, fps=float(rate))
                _check_cancelled(cancelled)
                if staged_audio_matches(ffmpeg, staging):
                    audio['command'][audio['command'].index('-i')+1] = str(staging['path'])
                    source_bytes = staging['path'].stat().st_size
                else:
                    source_decision.update(enabled=False, reason='staged stream clock/format differs; retain original mix input')
                    staging['path'].unlink(missing_ok=True)
                    note_export('parallel_audio_source_fallback', source_decision)
            job.completion_metadata['parallel_audio_source'] = dict(source_decision, bytes=source_bytes)
        def encode_audio():
            if audio is None: return
            detail = dict(mode=audio['mode'], codec=audio['codec'], reason=audio['reason'])
            note_export('parallel_audio_selection', detail)
            if trace: trace('parallel_audio_command', audio['command'])
            with export_phase('parallel_continuous_audio', overlaps='video segment encoding', **detail):
                code, logs = _run_streaming_process(audio['command'], cancelled=stop_requested,
                    purpose='parallel export continuous audio')
            if code: raise ffmpeg_failure(code, logs, encoder=job.settings.encoder, fps=float(rate))
            if not audio['path'].is_file() or audio['path'].stat().st_size <= 0:
                raise RuntimeError('连续音频未生成，已停止发布')
            job.completion_metadata['parallel_audio'] = detail
            if staging and staging['path'].exists():
                release_private_media(staging['path'], 'audio_source',
                    'continuous audio closed; final mux reads only encoded audio')
        def encode(i, recovery=False):
            first, last = parts[i]
            part = replace(job, output_path=str(files[i]),
                start_seconds=float(Fraction(str(job.start_seconds or 0))+Fraction(first)/rate),
                duration_seconds=float(Fraction(last-first)/rate),
                settings=replace(job.settings, audio_codec='none', container='mp4'),
                completion_metadata={}, completion_preview_path='', preview_callback=None, preview_url='',
                export_context=dict(job.export_context, parallel_segments=1))
            command = build_render_command(ffmpeg, part)
            if job.export_context.get('diagnostic_filters'):
                command[command.index('-loglevel')+1] = 'level+verbose'
                command.insert(1, '-benchmark')
            # These private segments are read only after successful close.
            # Moving each segment's moov to its head wastes another full copy.
            if '-movflags' in command:
                at = command.index('-movflags')
                if command[at+1] == '+faststart':del command[at:at+2]
            def line(value):
                key, separator, raw = value.partition('=')
                if separator and key == 'frame':
                    with lock:counts[i] = min(last-first, max(counts[i], int(raw.strip() or 0)))
            if trace: trace('parallel_video_command', dict(segment=i, command=command))
            with export_phase('parallel_video_segment', segment=i, first_frame=first, last_frame=last,
                              recovery=recovery):
                code, logs = _run_streaming_process(command, on_line=line, cancelled=stop_requested,
                                                   purpose='ffmpeg studio render')
            if code:
                raise ffmpeg_failure(code, logs, encoder=job.settings.encoder, fps=float(rate))
            metadata = _segment_metadata(ffmpeg, files[i], last-first, rate, stop_requested)
            with lock:counts[i] = last-first
            return metadata
        encoding_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=len(parts)+1, thread_name_prefix='parallel-export') as executor:
            audio_future = executor.submit(copy_context().run, encode_audio)
            futures = [executor.submit(copy_context().run, encode, i) for i in range(len(parts))]
            all_futures = [*futures, audio_future]
            last_report = 0.
            try:
                with export_phase('parallel_video_encode', segments=len(parts),
                                  overlaps='video-only segments and separate continuous audio'):
                    while not all(f.done() for f in futures):
                        if cancelled and cancelled():stopped.set()
                        for future in all_futures:
                            if future.done() and future.exception() is not None:
                                stopped.set()
                        if shutil.disk_usage(folder).free < 512*1024**2:
                            raise OSError('临时磁盘空间不足，已停止导出并保留原成片')
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
                    errors = [f.exception() for f in all_futures if f.done() and f.exception() is not None]
                    if errors:
                        # A peer stopped because another encoder failed. Keep the
                        # original failure instead of reporting that peer as a user cancellation.
                        raise next((e for e in errors if not isinstance(e, InterruptedError)), errors[0])
                    metadata = [f.result() for f in futures]
                with export_phase('parallel_audio_wait', wait_only=True, overlaps='audio started before video'):
                    while not audio_future.done():
                        _check_cancelled(cancelled)
                        if shutil.disk_usage(folder).free < 512*1024**2:
                            raise OSError('临时磁盘空间不足，已停止连续音频处理并保留原成片')
                        time.sleep(.1)
                    audio_future.result()
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
        # Every audio sample has already been processed once on its continuous
        # timeline. The last process only remuxes compressed packets.
        if audio: command += ['-i', str(audio['path'])]
        command += ['-map','0:v:0','-c:v','copy']
        if audio:
            command += ['-map','1:a','-c:a','copy']
        else:command += ['-an']
        command += ['-t',f'{job.duration_seconds:.9f}']
        reserve = 0
        if job.settings.container in {'mp4','mov'}:
            # Graph audio is one mixed output. Legacy multi-audio input maps
            # retain faststart rather than guessing their sample-table budget.
            if job.direct_video_graph or not audio:
                reserve = reserved_moov_bytes(job.duration_seconds, float(rate),
                    job.settings.audio_sample_rate or 48000, int(bool(audio)))
            command += ['-moov_size',str(reserve)] if reserve else ['-movflags','+faststart']
        command += ['-progress','pipe:1','-nostats',str(partial)]
        if trace:trace('parallel_final_mux_command', command)
        if progress:progress(export_progress('encode', stage_label='封装文件', message='复制视频与连续音频流并封装…', percent=100, indeterminate=True))
        job.export_context['active_stage'] = 'mux'
        # Recheck with actual sizes: CQ estimates cannot predict every source,
        # and other applications can consume disk space during the encode.
        segment_sizes = [p.stat().st_size for p in files]
        segment_bytes = sum(segment_sizes)
        audio_bytes = audio['path'].stat().st_size if audio else 0
        available = shutil.disk_usage(folder).free
        needed = segment_bytes + audio_bytes + reserve + 512*1024**2
        note_export('parallel_mux_space', dict(free_bytes=available, required_bytes=needed,
            segment_bytes=segment_bytes, audio_bytes=audio_bytes))
        if available < needed:
            raise OSError('临时磁盘剩余空间不足以封装成片；原成片已保留，请释放空间后重试')
        released = set()
        def mux_progress(line):
            key, separator, raw = line.partition('=')
            if not separator or key != 'frame':return
            try:frames = int(raw.strip())
            except ValueError:return
            # The concat demuxer has moved beyond this file only after a video
            # packet from its successor was muxed. Audio/out_time can run ahead
            # and cannot prove consumption. Never delete the currently read file.
            for i, (_, last) in enumerate(parts[:-1]):
                if i not in released and frames > last:
                    if release_private_media(files[i], 'consumed_video_segment',
                            'mux video packet count passed segment end; next segment is being read'):
                        released.add(i)
        with export_phase('parallel_join_and_audio', video='stream copy', audio='prepared continuous stream copy',
                          segment_bytes=sum(p.stat().st_size for p in files), moov_reserved_bytes=reserve):
            code, logs = _run_streaming_process(command, on_line=mux_progress,
                cancelled=cancelled, purpose='parallel export final mux')
            if code and reserve and any(s in str(logs).lower() for s in (
                    'reserved_moov_size is too small', 'not enough room for moov atom')):
                _check_cancelled(cancelled)
                note_export('mux_retry', dict(reason='reserved moov space insufficient', layout='faststart'))
                partial.unlink(missing_ok=True)
                if released:
                    # Early release lowers the ordinary peak from two whole
                    # films toward 1.5. A rare undersized-header retry rebuilds
                    # only consumed private segments from the same immutable
                    # job, rather than retaining a whole-film backup normally.
                    needed = sum(segment_sizes[i] for i in released)+512*1024**2
                    if shutil.disk_usage(folder).free < needed:
                        raise OSError('封装回退所需空间不足，原成片已保留')
                    if source_identity() != original_sources:
                        raise RuntimeError('封装回退前源素材已改变，已停止发布并保留原成片')
                    stopped.clear()  # Original workers have all joined.
                    with export_phase('parallel_mux_recovery', segments=sorted(released)):
                        for i in sorted(released):
                            _check_cancelled(cancelled)
                            if encode(i, recovery=True) != metadata[i]:
                                raise RuntimeError('封装回退重建分段规格不一致，已停止发布')
                    job.completion_metadata['parallel_mux_rebuilt_segments'] = sorted(released)
                at = command.index('-moov_size')
                command[at:at+2] = ['-movflags','+faststart']
                code, logs = _run_streaming_process(command, cancelled=cancelled, purpose='parallel export final mux retry')
        if code:raise ffmpeg_failure(code, logs, encoder=job.settings.encoder, fps=float(rate))
        # The final staged file is complete and independently checkable. Keep
        # segments until mux/retry succeeds, then release them before QA/poster
        # decoding. A failed check still cannot touch the previous publication.
        for path in files + ([audio['path']] if audio else []):
            if not path.exists():continue
            release_private_media(path, 'encoded_segment' if path in files else 'continuous_audio',
                'final mux closed successfully; validation reads staged output')
        job.completion_metadata['parallel_mux_early_released_bytes'] = sum(segment_sizes[i] for i in released)
        if progress:progress(export_progress('validate', message='检查成片…'))
        options = output_validation_options(job)
        options['cut_points'] += [first/float(rate) for first, _ in parts[1:]]
        metadata = validate_output(ffmpeg, partial, duration=job.duration_seconds, fps=float(rate),
            cancelled=cancelled, preview_path=job.completion_preview_path, **options)
        metadata['parallel_temporary_media_bytes'] = segment_bytes+audio_bytes+partial.stat().st_size
        metadata['parallel_temporary_media_scope'] = 'mux-stage upper bound; actual sampled peak is in resource timeline'
        metadata['parallel_audio_source_bytes'] = source_bytes
        metadata['parallel_segments'] = len(parts)
        publish_output(partial, output, job, metadata, cancelled=cancelled)
        note_export('parallel_video_finished', dict(segments=len(parts), encoded_frames=sum(b-a for a,b in parts)))
        notify_after_publication(job, progress, export_progress('mux', message='导出完成', percent=100))
    return output
