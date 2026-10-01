"""One final encode for proven simple video graphs, using the shared audio mix.

Clip boundaries are quantized once on the output frame lattice, not once per
clip duration. This retains gaps, reordering, repeats, rates and nonzero ranges.
Unsupported geometry/effects keep the raster compositor.
"""
from fractions import Fraction
import math
from pathlib import Path


def simple_video_clips(graph):
    if not graph or graph.get('audio_mix') is None:
        return None
    clips = [c for t in graph.get('video_tracks', []) if t.get('enabled', True)
             for c in t.get('clips', []) if c.get('enabled', True)]
    defaults = dict(anchor_x=.5, anchor_y=.5, position_x=.5, position_y=.5,
                    scale_x=1., scale_y=1., rotation=0., opacity=1., fit_mode='contain')
    assets = {a['asset_id']: a for a in graph.get('media_pool', [])}
    for clip in clips:
        if any(clip.get('transform', {}).get(k, v) != v for k, v in defaults.items()):
            return None
        effects = clip.get('effects') or {}
        if effects.get('blendMode', 'normal') != 'normal' or (effects.get('chromaKey') or {}).get('enabled'):
            return None
        if effects.keys() - {'blendMode', 'chromaKey'}:
            return None
        if clip['asset_id'] not in assets or assets[clip['asset_id']].get('video_metadata', {}).get('has_video') is False:
            return None
        if float(clip.get('playback_rate', 1)) <= 0:
            return None
    clips.sort(key=lambda c: (c['timeline_in_ms'], c['id']))
    if any(a['timeline_out_ms'] > b['timeline_in_ms'] for a, b in zip(clips, clips[1:])):
        return None
    return clips


def compile_video_filtergraph(ffmpeg, job, ass_filter, *, caption_overlays=(), caption_filter=None):
    from .audio_export import compile_audio_mix
    from .clip_time_mapper import project_to_source_exact
    graph = job.direct_video_graph
    clips = simple_video_clips(graph)
    if clips is None:
        raise ValueError('Unsupported direct video graph')
    fps = Fraction(str(job.settings.fps or graph.get('fps') or 30)).limit_denominator(100100)
    start = Fraction(str(job.start_seconds or 0))
    duration = Fraction(str(job.duration_seconds or graph['duration_ms']/1000))
    count = math.ceil(duration * fps)
    width = int(job.settings.width or graph['width'])
    height = int(job.settings.height or graph['height'])
    assets = {a['asset_id']: a for a in graph['media_pool']}
    inputs, filters, pieces = [], [], []
    cursor = 0
    input_count = 0

    def blank(frames):
        label = f'piece{len(pieces)}'
        filters.append(f'color=c=black:s={width}x{height}:r={fps},trim=end_frame={frames},setpts=N/({fps}*TB)[{label}]')
        pieces.append(f'[{label}]')

    for clip in clips:
        first = max(0, math.ceil((Fraction(clip['timeline_in_ms'], 1000)-start)*fps))
        last = min(count, math.ceil((Fraction(clip['timeline_out_ms'], 1000)-start)*fps))
        if last <= first:
            continue
        if first > cursor:
            blank(first-cursor)
        source = project_to_source_exact(clip, start + first/fps)
        rate = Fraction(str(clip.get('playback_rate') or 1))
        # Decode preroll before the exact trim. In indexed FLV, seeking a few
        # milliseconds from zero can skip the first keyframe; fps would then
        # duplicate the next keyframe over the missing beginning. Omit zero
        # seeks, and retain timestamps relative to the common container origin.
        source_path = assets[clip['asset_id']]['canonical_source']
        # FLV keyframe indexes can land after the requested timestamp. Decode
        # from the head for this container, including late/range exports; this
        # trades extra decode for correct content instead of hiding lost frames.
        seek = Fraction(0) if Path(source_path).suffix.lower()=='.flv' else max(Fraction(0), source - 10)
        trim = source - seek
        inputs += ['-threads', '4']
        if seek > 0:
            inputs += ['-ss', f'{float(seek):.9f}']
        inputs += ['-t', f'{float(trim+(last-first)/fps*rate + 2/fps):.9f}',
                   '-i', source_path]
        label = f'piece{len(pieces)}'
        filters.append(f'[{input_count}:v:0]trim=start={float(trim):.9f},setpts=(PTS-{float(trim):.9f}/TB)/({rate}),fps={fps}:round=up:start_time=0,'
                       f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                       f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                       f'tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={last-first},'
                       f'settb=AVTB,setpts=N/({fps}*TB)[{label}]')
        pieces.append(f'[{label}]')
        cursor = last
        input_count += 1
    if cursor < count:
        blank(count-cursor)
    filters.append(''.join(pieces)+f'concat=n={len(pieces)}:v=1:a=0,settb=AVTB,setpts=N/({fps}*TB)[timeline]')
    filters.append(f'[timeline]setpts=PTS+{float(start):.9f}/TB,{ass_filter},setpts=PTS-{float(start):.9f}/TB[vout]')
    audio_label = None
    if job.settings.audio_codec != 'none':
        audio_inputs, audio_filters, audio_label = compile_audio_mix(
            ffmpeg, job, graph['audio_mix'], input_offset=input_count)
        inputs += audio_inputs
        filters += audio_filters
    video_label='[vout]'
    if caption_filter:
        filters.append(f'{video_label}{caption_filter}[captionnative]');video_label='[captionnative]'
    # Static caption rasters join the existing timeline/audio graph, so adding
    # one gradient does not force a full-film Python media raster pass.
    image_offset=inputs.count('-i')
    for i,layer in enumerate(caption_overlays):
        inputs += ['-i',str(layer['path'])]
        x,y,*_=layer['bounds']
        filters.append(f"{video_label}[{image_offset+i}:v]overlay=x={x}:y={y}:eof_action=repeat:format=auto:enable='gte(t,{layer['start']:.9f})*lt(t,{layer['end']:.9f})'[static{i}]")
        video_label=f'[static{i}]'
    if job.preview_url:
        filters.append(f'{video_label}split=2[vfinal][previewfull]')
        filters.append('[previewfull]fps=2:round=up:start_time=0:eof_action=pass,scale=640:-2[exportpreview]')
        video_label='[vfinal]'
    args = inputs + ['-filter_complex_threads', '2', '-filter_complex', ';'.join(filters), '-map', video_label]
    args += ['-map', audio_label] if audio_label else ['-an']
    return args + ['-t', f'{float(duration):.9f}']
