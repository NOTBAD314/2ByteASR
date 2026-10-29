"""Freeze track gain and audio routing into an export's timeline-local mix."""
from ..timeline.studio_track_gain import track_gain_db, gain_amplitude


def capture_audio_mix(project):
    from ..playback.audio_graph import capture_audio_graph
    return capture_audio_graph(project)['segments']


def audio_mix_arguments(ffmpeg, job, layers):
    inputs, filters, label = compile_audio_mix(ffmpeg, job, layers)
    if not label:
        return ['-an']
    return inputs+['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map',label,'-c:a','pcm_s16le']


def compile_audio_mix(ffmpeg, job, layers, *, input_offset=1, sample_rate=48000, channels=2,
                      audio_only=False, audio_verified=False):
    from .timeline_media import resolve_audio_layers
    if not audio_only:
        layers, _ = resolve_audio_layers(layers, ffmpeg)
    from ..playback.audio_engine import _atempo_chain
    from .studio_render import media_has_audio
    start = float(job.start_seconds or 0.)
    duration = float(job.duration_seconds or max(.001, job.video_graph['duration_ms']/1000-start))
    inputs, filters, labels = [], [], []
    checked = {}
    content_inputs = {}
    input_count = 0
    for layer in layers:
        a, b = max(start, layer['timeline_in_ms']/1000), min(start+duration, layer['timeline_out_ms']/1000)
        source = layer['source_path']
        if b <= a:
            continue
        if source not in checked:
            checked[source] = True if audio_verified else media_has_audio(ffmpeg, source)
        if not checked[source]:
            continue
        rate = layer['playback_rate']
        source_start = layer['source_in_ms']/1000 + (a-layer['timeline_in_ms']/1000)*rate
        # FLV project time is decoded audio-content time. Seeking its packet
        # timestamps can land beyond a recorder gap; trim the continuous PCM
        # clock instead. Reuse one audio decoder per FLV, no video proxy.
        content_clock=audio_only and source.lower().endswith('.flv')
        if content_clock and source in content_inputs:
            index=content_inputs[source]
        else:
            index=input_count+input_offset;input_count+=1
            if content_clock:
                inputs += ['-i',source];content_inputs[source]=index
            else:
                inputs += (['-ss', f'{source_start:.6f}'] if source_start >= .25 else [])
                inputs += ['-t', f'{(b-a)*rate+(source_start if source_start < .25 else 0):.6f}', '-i', source]
        head=(f'asetpts=N/SR/TB,atrim=start={source_start:.6f}:duration={(b-a)*rate:.6f},'
              if content_clock else f'atrim=start={source_start:.6f},' if 0 < source_start < .25 else '')
        # 2026-10-24 multi-track: a late further stream keeps its delay (never FLV).
        from ..playback.audio_engine import stream_lead_filter
        lead = '' if content_clock else stream_lead_filter(layer.get('stream_start_ms', 0.), source_start * 1000)
        label = f'gain{len(labels)+input_offset}'
        tempo_padding = 'apad=pad_dur=0.1,' if abs(rate-1.) > .001 else ''
        from ..playback.audio_envelope import envelope_filter
        envelope=envelope_filter(layer.get('audio_envelopes',()),origin_ms=a*1000,channels=channels)
        filters.append(f'[{index}:a:{int(layer.get("stream_index",0))}]{head}asetpts=PTS-STARTPTS,{lead}{tempo_padding}{_atempo_chain(rate)},'
            f'asetpts=N/SR/TB,atrim=duration={b-a:.6f},volume={gain_amplitude(layer["gain_db"]):.9f},aresample={sample_rate},'
            f'{envelope}apad=pad_dur=0.1,'
            f'adelay={round((a-start)*sample_rate)}S:all=1,asetpts=N/SR/TB[{label}]')
        labels.append(f'[{label}]')
    if not labels:
        return [], [], None
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,'
                   f'apad,asetpts=N/SR/TB,atrim=duration={duration:.6f}[audio]')
    return inputs, filters, '[audio]'
