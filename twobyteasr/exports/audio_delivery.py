"""Audio-only delivery from the same frozen timeline mix used by video export."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from ..system.processes import popen_hidden_subprocess, run_hidden_subprocess
from .export_validation import record_completion, publish_output, notify_after_publication

FORMATS = {
    'mp3': ('MP3', 'libmp3lame', 'mp3'),
    'wav': ('WAV / PCM', 'pcm_s16le', 'wav'),
    'm4a': ('M4A / AAC', 'aac', 'ipod'),
    'flac': ('FLAC', 'flac', 'flac'),
    'ogg': ('Ogg / Vorbis', 'libvorbis', 'ogg'),
    'opus': ('Ogg / Opus', 'libopus', 'opus'),
}


def validate_audio_settings(settings):
    if settings.container not in FORMATS:
        raise ValueError('不支持的音频格式')
    if settings.audio_sample_rate not in (0, 32000, 44100, 48000, 88200, 96000, 192000):
        raise ValueError('不支持的音频采样率')
    if settings.audio_channels not in (0, 1, 2):
        raise ValueError('音频输出声道必须为跟随混音、单声道或立体声')
    if settings.audio_bit_depth not in (16, 24, 32):
        raise ValueError('PCM 位深必须为 16、24 或 32')
    if settings.container == 'flac' and settings.audio_bit_depth == 32:
        raise ValueError('FLAC 请选择 16 或 24 位')
    if settings.audio_bitrate_kbps not in (64, 96, 128, 192, 256, 320):
        raise ValueError('不支持的音频码率')
    if settings.container in {'mp3','ogg'} and settings.audio_sample_rate > 48000:
        raise ValueError('此音频格式最高使用 48000 Hz')
    if settings.container == 'opus' and settings.audio_sample_rate not in (0, 48000):
        raise ValueError('Opus 输出固定使用 48000 Hz')


def encoding_arguments(settings):
    name = settings.container
    codec = FORMATS[name][1]
    if name == 'wav':
        codec = f'pcm_s{settings.audio_bit_depth}le'
    args = ['-c:a', codec]
    if name in {'mp3','m4a','ogg','opus'}:
        args += ['-b:a', f'{settings.audio_bitrate_kbps}k']
    if name == 'flac':
        args += ['-sample_fmt', 's16' if settings.audio_bit_depth == 16 else 's32',
                 '-bits_per_raw_sample', str(settings.audio_bit_depth)]
    if name == 'wav':
        args += ['-rf64', 'auto']  # RIFF for small files; RF64 beyond 4 GiB.
    if name == 'm4a':
        args += ['-movflags', '+faststart']
    return args + ['-f', FORMATS[name][2]]


def format_capabilities(ffmpeg):
    path = Path(ffmpeg).resolve()
    stat = path.stat()
    return dict(_format_capabilities(str(path), stat.st_size, stat.st_mtime_ns))


@lru_cache(maxsize=4)
def _format_capabilities(ffmpeg, size, mtime):
    """Actually encode and mux a small file with the exact shipped binary."""
    from .studio_render import RenderSettings
    rows = {}
    with tempfile.TemporaryDirectory(prefix='2byteasr-audio-probe-') as directory:
        for name, (label, codec, muxer) in FORMATS.items():
            target = Path(directory) / ('probe.'+name)
            settings = RenderSettings(output_kind='audio', container=name)
            try:
                result = run_hidden_subprocess([ffmpeg, '-v', 'error', '-nostdin', '-y',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '0.08',
                    '-vn', *encoding_arguments(settings), str(target)],
                    purpose='audio encoder and muxer probe', capture_output=True, timeout=8)
                ok = result.returncode == 0 and target.exists() and target.stat().st_size > 0
                reason = '' if ok else result.stderr.decode('utf8', 'replace')[-500:]
            except (OSError, subprocess.TimeoutExpired) as exc:
                ok, reason = False, str(exc)
            rows[name] = dict(label=label, encoder=codec, muxer=muxer, available=ok, reason=reason)
    return rows


def probe_audio(ffmpeg, source):
    result = run_hidden_subprocess([str(Path(ffmpeg).with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')),
        '-v', 'error', '-select_streams', 'a', '-show_streams', '-show_format', '-of', 'json', str(source)],
        purpose='audio stream metadata', capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout)


@lru_cache(maxsize=64)
def _source_audio_metadata(ffmpeg,source,size,mtime_ns):
    return probe_audio(ffmpeg,source)


def mix_format(ffmpeg, layers, settings):
    """Keep native rate/channels for one source; highest rate for a mixed bus."""
    metadata = {}
    rates, channels = [], []
    for layer in layers:
        source = layer['source_path']
        if source not in metadata:
            path=Path(source).resolve();stat=path.stat()
            metadata[source] = _source_audio_metadata(str(Path(ffmpeg).resolve()),str(path),stat.st_size,stat.st_mtime_ns)
        streams = metadata[source]['streams']
        index = int(layer.get('stream_index', 0))
        if index >= len(streams):
            raise ValueError('素材没有所选音轨：'+source)
        stream = streams[index]
        rates.append(int(stream['sample_rate']))
        channels.append(int(stream['channels']))
    if not rates:
        raise ValueError('所选范围没有可听音轨；请检查轨道启用、静音与导出范围。')
    rate = settings.audio_sample_rate or max(rates)
    if settings.container in {'mp3','ogg'}:
        rate = min(48000, rate)
    if settings.container == 'opus':
        rate = 48000
    count=settings.audio_channels or max(channels)
    if settings.container=='mp3':count=min(2,count)
    return rate,count


def build_audio_command(ffmpeg, job):
    from .audio_export import compile_audio_mix
    settings = job.settings
    validate_audio_settings(settings)
    start = float(job.start_seconds or 0)
    end = start + float(job.duration_seconds or 0)
    if end <= start:
        raise ValueError('导出范围为空，请重新设置入点和出点。')
    # Resolve only intersecting audible layers. No video graph, frames or ASS.
    layers = [dict(layer) for layer in (job.audio_graph or {}).get('segments', ())
              if layer['timeline_out_ms'] > start*1000 and layer['timeline_in_ms'] < end*1000]
    rate, channels = mix_format(ffmpeg, layers, settings)
    inputs, filters, label = compile_audio_mix(ffmpeg, job, layers, input_offset=0,
        sample_rate=rate,channels=channels,audio_only=True,audio_verified=True)
    if not label:
        raise ValueError('所选范围没有可听音轨。')
    command = [str(ffmpeg), '-hide_banner', '-nostdin', '-y', '-loglevel', 'warning',
        '-stats_period', '0.2', *inputs, '-filter_complex_threads', '1',
        '-filter_complex', ';'.join(filters), '-map', label, '-vn', '-sn', '-dn',
        '-ar', str(rate), '-ac', str(channels), *encoding_arguments(settings),
        '-progress', 'pipe:1', str(job.output_path)]
    return command, rate, channels


def run_audio_process(command, *, cancelled=None, progress=None, duration=0, stage='encode'):
    """Drain bounded streams off-thread; cancellation never waits for stdout."""
    if cancelled and cancelled():
        raise InterruptedError('audio export cancelled')
    process = popen_hidden_subprocess(command, purpose='timeline audio export',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf8', errors='replace')
    errors = deque(maxlen=80)
    latest = {}
    lock = threading.Lock()
    def stderr():
        for line in process.stderr:
            errors.append(line)
    def stdout():
        current = {}
        for line in process.stdout:
            key, sep, value = line.strip().partition('=')
            if sep:
                current[key] = value
                if key == 'progress':
                    with lock:
                        latest.clear(); latest.update(current)
                    current = {}
    readers = [threading.Thread(target=fn, daemon=True) for fn in (stderr, stdout)]
    for reader in readers: reader.start()
    try:
        while process.poll() is None:
            if cancelled and cancelled():
                raise InterruptedError('audio export cancelled')
            if progress:
                with lock:
                    payload = dict(latest); latest.clear()
                if payload:
                    payload.update(stage=stage, stage_label='音频编码' if stage=='encode' else '验证音频',
                        message='正在处理工程音轨…' if stage=='encode' else '正在校验完整音频…',
                        duration_seconds=str(duration), indeterminate='0')
                    progress(payload)
            time.sleep(.04)
        for reader in readers: reader.join(timeout=2)
        if cancelled and cancelled():
            raise InterruptedError('audio export cancelled')
        if process.returncode:
            raise RuntimeError('音频导出失败：'+''.join(errors)[-2500:])
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        for reader in readers: reader.join(timeout=2)
        process.stdout.close(); process.stderr.close()


def validate_audio_output(ffmpeg, path, job, *, rate, channels, cancelled=None, progress=None):
    metadata = probe_audio(ffmpeg, path)
    audio = metadata.get('streams', [])
    if len(audio) != 1:
        raise RuntimeError('音频验证失败：输出音轨数量不正确')
    stream = audio[0]
    duration = float(stream.get('duration') or metadata['format'].get('duration') or 0)
    # MP3/AAC/Vorbis frame padding; PCM/FLAC/Opus must match near a sample.
    tolerance = .10 if job.settings.container in {'mp3','m4a','ogg'} else .025
    if abs(duration-float(job.duration_seconds)) > tolerance:
        raise RuntimeError('音频验证失败：时长与工程范围不一致')
    if int(stream['sample_rate']) != rate or int(stream['channels']) != channels:
        raise RuntimeError('音频验证失败：采样率或声道与请求不一致')
    run_audio_process([str(ffmpeg), '-v','error','-xerror','-nostdin','-i', str(path),
        '-map','0:a:0','-vn','-f','null','-','-progress','pipe:1'],
        cancelled=cancelled, progress=progress, duration=job.duration_seconds, stage='mux')
    metadata['audio_bitrate'] = [dict(average_bitrate_bps=int(stream.get('bit_rate') or 0), reliable=True)]
    return metadata


@record_completion
def run_audio_job(ffmpeg, job, *, progress=None, cancelled=None, trace=None):
    from .studio_render import validate_export_config, export_progress
    validate_export_config(job)
    output = Path(job.output_path).resolve()
    if output.suffix.lower() != '.'+job.settings.container:
        raise ValueError('音频格式与副档名不一致')
    if output.exists() and not job.overwrite_existing:
        raise FileExistsError('输出文件已存在：'+str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    timings = {}
    began = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='.2byteasr-audio-', dir=output.parent) as folder:
        staged = Path(folder)/('audio.'+job.settings.container)
        if progress: progress(export_progress('prepare_project', message='正在准备工程音轨…'))
        if cancelled and cancelled(): raise InterruptedError('audio export cancelled')
        command, rate, channels = build_audio_command(ffmpeg, replace(job, output_path=str(staged)))
        timings['prepare_seconds'] = time.perf_counter()-began
        if trace: trace('audio_command', command)
        encoded = time.perf_counter()
        run_audio_process(command, cancelled=cancelled, progress=progress, duration=job.duration_seconds)
        timings['encode_and_mux_seconds'] = time.perf_counter()-encoded
        validating=time.perf_counter()
        if progress: progress(export_progress('mux', message='正在验证完整音频…'))
        metadata=validate_audio_output(ffmpeg, staged, job, rate=rate, channels=channels,
            cancelled=cancelled, progress=progress)
        timings['validation_seconds']=time.perf_counter()-validating
        metadata['audio_timings']=timings
        publish_output(staged, output, job, metadata, cancelled=cancelled)
    if trace: notify_after_publication(job, trace, 'audio_completed', dict(timings=timings,rate=rate,channels=channels))
    if progress: notify_after_publication(job, progress, export_progress('mux', message='音频导出完成', percent=100, indeterminate=False))
    return output
