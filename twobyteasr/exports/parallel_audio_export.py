"""Prepare one continuous audio stream while native video segments are encoding."""
import json
import math
import os
from pathlib import Path


def _streams(ffmpeg, source):
    from ..system.processes import run_hidden_subprocess
    probe = Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    result = run_hidden_subprocess([str(probe), '-v', 'error', '-select_streams', 'a',
        '-show_streams', '-of', 'json', str(source)], purpose='parallel audio copy eligibility',
        capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout).get('streams', [])


def direct_audio_copy(ffmpeg, job):
    """Prove unchanged, continuous audio and an exact packet-aligned start.

    Arbitrary trims, gain, mixes, rates, fades and recorder content clocks retain
    the existing continuous PCM mix. Copy is used only when the user chose it.
    """
    if job.settings.audio_codec != 'copy' or not job.direct_video_graph:
        return None
    start = float(job.start_seconds or 0)
    end = start + float(job.duration_seconds)
    layers = [layer for layer in job.direct_video_graph['audio_mix']
              if layer['timeline_out_ms']/1000 > start and layer['timeline_in_ms']/1000 < end]
    if len(layers) != 1:
        return None
    layer = layers[0]
    if (abs(float(layer['gain_db'])) > 1e-9 or abs(float(layer['playback_rate'])-1) > 1e-9
            or layer.get('audio_envelopes') or abs(float(layer.get('stream_start_ms', 0))) > .001
            or layer['timeline_in_ms']/1000 > start or layer['timeline_out_ms']/1000 < end
            or Path(layer['source_path']).suffix.lower() not in {'.mp4', '.mov', '.mkv', '.m4a'}):
        return None
    streams = _streams(ffmpeg, layer['source_path'])
    index = int(layer.get('stream_index', 0))
    if index >= len(streams):
        return None
    stream = streams[index]
    codec = stream.get('codec_name')
    allowed = {'aac', 'mp3', 'ac3', 'eac3'} if job.settings.container in {'mp4', 'mov'} else {
        'aac', 'mp3', 'ac3', 'eac3', 'opus', 'vorbis', 'flac'}
    source_start = layer['source_in_ms']/1000 + start-layer['timeline_in_ms']/1000
    try:
        sample_rate = int(stream.get('sample_rate') or 0)
        source_duration = float(stream.get('duration') or 0)
        stream_start = float(stream.get('start_time') or 0)
    except (ValueError, TypeError):
        return None
    # AAC priming/edit lists are preserved in the audio-only MP4. Other codecs
    # currently qualify only at the original stream origin.
    block = 1024 if codec == 'aac' else 0
    if (codec not in allowed or abs(stream_start) > .001
            or sample_rate <= 0 or source_start < 0
            or source_duration < source_start+float(job.duration_seconds)-.001
            or (source_start > 0 and (not block or abs(source_start*sample_rate/block-round(source_start*sample_rate/block)) > 1e-7))
            or (job.settings.audio_sample_rate and job.settings.audio_sample_rate != sample_rate)
            or (job.settings.audio_channels and job.settings.audio_channels != int(stream.get('channels') or 0))):
        return None
    return dict(source=layer['source_path'], stream=index, start=source_start, codec=codec,
                sample_rate=sample_rate, channels=int(stream.get('channels') or 0))


def continuous_audio_command(ffmpeg, job, folder):
    from .audio_export import compile_audio_mix
    if not job.export_context.get('expected_output_audio', True) or job.settings.audio_codec == 'none':
        return None
    codec = job.settings.audio_codec
    copy = direct_audio_copy(ffmpeg, job)
    if copy:
        inputs = (['-ss', f"{copy['start']:.9f}"] if copy['start'] else []) + ['-i', copy['source']]
        filters, label, actual_codec = [], f"0:a:{copy['stream']}", copy['codec']
    elif job.direct_video_graph:
        inputs, filters, label = compile_audio_mix(ffmpeg, job, job.direct_video_graph['audio_mix'], input_offset=0)
        if codec == 'copy': codec = 'aac'
        actual_codec = codec
    else:
        inputs = (['-ss', f'{job.start_seconds:.9f}'] if job.start_seconds else []) + ['-i', job.media_path]
        filters, label = [], '0:a?'
        actual_codec = codec
    if not label:
        return None
    suffix = '.mp4' if actual_codec in {'aac', 'mp3', 'ac3', 'eac3', 'opus'} else '.mka'
    if codec == 'copy' and not copy:
        streams = _streams(ffmpeg, job.media_path)
        if streams and all(s.get('codec_name') in {'aac','mp3','ac3','eac3','opus'} for s in streams):
            suffix = '.mp4'
    path = Path(folder) / ('continuous-audio' + suffix)
    command = [str(ffmpeg), '-hide_banner', '-loglevel', 'level+info', '-xerror', '-y', *inputs]
    if filters: command += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters)]
    command += ['-map', label, '-vn', '-c:a', 'copy' if copy else 'libopus' if codec == 'opus' else codec]
    if not copy and codec != 'copy':
        command += ['-b:a', f'{job.settings.audio_bitrate_kbps}k']
        if job.settings.audio_sample_rate: command += ['-ar', str(job.settings.audio_sample_rate)]
        if job.settings.audio_channels: command += ['-ac', str(job.settings.audio_channels)]
    command += ['-t', f'{job.duration_seconds:.9f}', '-progress', 'pipe:1', '-nostats', str(path)]
    return dict(path=path, command=command, codec=actual_codec,
                mode='source_stream_copy' if copy or codec == 'copy' else 'continuous_encode',
                reason='unchanged compatible packet-aligned source' if copy else 'preserve continuous timeline mix and requested audio settings')


def audio_source_staging_plan(ffmpeg, job, audio, folder):
    """Detach a long, origin-based AAC source before concurrent video reads.

    Only compressed packets are copied. The existing continuous mix/seek/gain,
    rate, envelopes, padding and user audio settings still run afterwards.
    Arbitrary late seeks and recorder clocks retain their established route.
    """
    choice = job.export_context.get('audio_source_staging', 'auto')
    decision = dict(enabled=False, requested=choice, reason='not a long origin-based single AAC video source')
    if not audio or choice == 'off' or not job.direct_video_graph:
        return None, decision
    if choice != 'force' and float(job.duration_seconds or 0) < 600:
        decision['reason'] = 'short export; avoid full-source staging overhead'
        return None, decision
    command = audio['command']
    if command.count('-i') != 1 or '-ss' in command:
        decision['reason'] = 'multiple inputs or late seek need original source timing'
        return None, decision
    source = Path(command[command.index('-i')+1])
    if source.suffix.lower() not in {'.mp4','.mov'} or source.resolve() != Path(job.media_path).resolve():
        return None, decision
    start = float(job.start_seconds or 0)
    end = start+float(job.duration_seconds)
    layers = [layer for layer in job.direct_video_graph['audio_mix']
        if layer['timeline_out_ms']/1000 > start and layer['timeline_in_ms']/1000 < end]
    if len(layers) != 1 or int(layers[0].get('stream_index', 0)) != 0:
        return None, decision
    streams = _streams(ffmpeg, source)
    if not streams or streams[0].get('codec_name') != 'aac':
        return None, decision
    stream = streams[0]
    try:
        source_duration = float(stream.get('duration') or 0)
        source_start = float(stream.get('start_time') or 0)
    except (ValueError, TypeError):
        return None, decision
    if not math.isfinite(source_duration) or not math.isfinite(source_start) or source_duration <= 0 or abs(source_start) > .001:
        return None, decision
    covered = float(job.duration_seconds)*float(layers[0].get('playback_rate', 1))
    if choice != 'force' and source_duration > 2*covered:
        decision['reason'] = 'export covers less than half the source audio'
        return None, decision
    target = Path(folder)/'audio-source.mp4'
    staged_command = [str(ffmpeg),'-hide_banner','-loglevel','level+info','-xerror','-y','-i',str(source),
        '-map','0:a:0','-vn','-sn','-dn','-c:a','copy','-map_metadata','-1',
        '-progress','pipe:1','-nostats',str(target)]
    decision.update(enabled=True, reason='copy AAC once to avoid a third reader seeking through the video container',
        source_duration_seconds=source_duration)
    return dict(path=target,command=staged_command,source_stream=stream), decision


def staged_audio_matches(ffmpeg, staging):
    """Verify the source clock and format before replacing the mix's input."""
    streams = _streams(ffmpeg, staging['path'])
    if len(streams) != 1: return False
    actual, source = streams[0], staging['source_stream']
    try:
        return (actual.get('codec_name') == source.get('codec_name') == 'aac'
            and int(actual.get('sample_rate') or 0) == int(source.get('sample_rate') or 0)
            and int(actual.get('channels') or 0) == int(source.get('channels') or 0)
            and abs(float(actual.get('start_time') or 0)-float(source.get('start_time') or 0)) <= .001
            and abs(float(actual.get('duration') or 0)-float(source.get('duration') or 0)) <= .05)
    except (ValueError, TypeError): return False
