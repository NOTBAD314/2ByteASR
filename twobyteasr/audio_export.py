"""Freeze track gain and audio routing into an export's timeline-local mix."""
from .studio_track_gain import track_gain_db, gain_amplitude


def capture_audio_mix(project):
    from .audio_graph import capture_audio_graph
    return capture_audio_graph(project)['segments']


def audio_mix_arguments(ffmpeg, job, layers):
    inputs, filters, label = compile_audio_mix(ffmpeg, job, layers)
    if not label:
        return ['-an']
    return inputs+['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map',label,'-c:a','pcm_s16le']


def compile_audio_mix(ffmpeg, job, layers, *, input_offset=1):
    from .audio_engine import _atempo_chain
    from .studio_render import media_has_audio
    start = float(job.start_seconds or 0.)
    duration = float(job.duration_seconds or max(.001, job.video_graph['duration_ms']/1000-start))
    inputs, filters, labels = [], [], []
    checked = {}
    for layer in layers:
        a, b = max(start, layer['timeline_in_ms']/1000), min(start+duration, layer['timeline_out_ms']/1000)
        source = layer['source_path']
        if b <= a:
            continue
        if source not in checked:
            checked[source] = media_has_audio(ffmpeg, source)
        if not checked[source]:
            continue
        rate = layer['playback_rate']
        source_start = layer['source_in_ms']/1000 + (a-layer['timeline_in_ms']/1000)*rate
        index = len(labels)+input_offset
        inputs += (['-ss', f'{source_start:.6f}'] if source_start >= .25 else [])
        inputs += ['-t', f'{(b-a)*rate+(source_start if source_start < .25 else 0):.6f}', '-i', source]
        head = f'atrim=start={source_start:.6f},' if 0 < source_start < .25 else ''
        label = f'gain{index}'
        tempo_padding = 'apad=pad_dur=0.1,' if abs(rate-1.) > .001 else ''
        filters.append(f'[{index}:a:0]{head}asetpts=PTS-STARTPTS,{tempo_padding}{_atempo_chain(rate)},'
            f'asetpts=N/SR/TB,atrim=duration={b-a:.6f},volume={gain_amplitude(layer["gain_db"]):.9f},aresample=48000,'
            'apad=pad_dur=0.1,'
            f'adelay={round((a-start)*48000)}S:all=1,asetpts=N/SR/TB[{label}]')
        labels.append(f'[{label}]')
    if not labels:
        return [], [], None
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,'
                   f'apad,asetpts=N/SR/TB,atrim=duration={duration:.6f}[audio]')
    return inputs, filters, '[audio]'
