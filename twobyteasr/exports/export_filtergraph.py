"""One final encode for proven simple video graphs, using the shared audio mix.

Clip boundaries are quantized once on the output frame lattice, not once per
clip duration. This retains gaps, reordering, repeats, rates and nonzero ranges.
Unsupported geometry/effects keep the raster compositor.
"""
from fractions import Fraction
import math
from pathlib import Path


def overlay_pts_shift(seconds, fps):
    """Use the output frame lattice when an overlay starts on that lattice."""
    rate = Fraction(str(fps)).limit_denominator(100100)
    frames = round(Fraction(str(seconds))*rate)
    if abs(float(Fraction(frames)/rate)-seconds) < 1e-7:
        return f'PTS+{frames}/({rate}*TB)'
    return f'PTS+{seconds:.9f}/TB'


def simple_video_clips(graph):
    if not graph or graph.get('audio_mix') is None or any(t.get('media') == 'video' for t in graph.get('clip_transitions', [])):
        return None
    clips = [c for t in graph.get('video_tracks', []) if t.get('enabled', True)
             for c in t.get('clips', []) if c.get('enabled', True)]
    defaults = dict(anchor_x=.5, anchor_y=.5, position_x=.5, position_y=.5,
                    scale_x=1., scale_y=1., rotation=0., opacity=1., fit_mode='contain')
    assets = {a['asset_id']: a for a in graph.get('media_pool', [])}
    for clip in clips:
        if str(assets.get(clip['asset_id'], {}).get('canonical_source', '')).lower().endswith('.gif'):
            return None
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


def compile_video_filtergraph(ffmpeg, job, ass_filter, *, caption_overlays=(), caption_filter=None, video_overlays=()):
    from .audio_export import compile_audio_mix
    from ..timeline.clip_time_mapper import project_to_source_exact
    from .timeline_media import resolve_video_graph
    from .studio_render import video_input_acceleration
    graph = resolve_video_graph(job.direct_video_graph, ffmpeg)
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
        from .video_seek_window import video_seek_window
        seek = Fraction(str(video_seek_window(ffmpeg, job, source_path, source)))
        trim = source - seek
        source_window = trim + (last-first)/fps*rate + 2/fps
        inputs += ['-threads', '4']
        inputs += video_input_acceleration(job)
        if seek > 0:
            inputs += ['-ss', f'{float(seek):.9f}']
        inputs += ['-t', f'{float(source_window):.9f}',
                   '-i', source_path]
        label = f'piece{len(pieces)}'
        # A container/clip can outlast its video stream while real audio and
        # captions remain. Hold this input's last decoded frame before trimming
        # so a range starting in that tail still has a frame. The finite window
        # and exact end_frame bound each isolated piece; no frame can spill into
        # a gap or the next source, and an input with no frames still fails.
        filters.append(f'[{input_count}:v:0]tpad=stop_mode=clone:stop_duration={float(source_window):.9f},'
                       f'trim=start={float(trim):.9f},setpts=(PTS-{float(trim):.9f}/TB)/({rate}),fps={fps}:round=up:start_time=0,'
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
        from .static_caption_timeline import caption_input, caption_filter
        inputs += caption_input(layer)
        x,y,*_=layer['bounds']
        pre,label=caption_filter(layer,f'[{image_offset+i}:v]',fps)
        enable='' if layer.get('sparse') else f":enable='gte(t,{layer['start']:.9f})*lt(t,{layer['end']:.9f})'"
        if pre: filters.append(pre.rstrip(';'))
        from .caption_composite_region import append_region_overlay
        video_label=append_region_overlay(filters,video_label,label,bounds=layer['bounds'],
            width=width,height=height,pixel_format=job.settings.pixel_format,tag=f'static{i}',enable=enable.lstrip(':'))
    for i, (start, end, path) in enumerate(video_overlays):
        index = inputs.count('-i')
        inputs += ['-i', str(path)]
        filters.append(f'[{index}:v]setpts={overlay_pts_shift(start, fps)}[movingpixels{i}]')
        from .caption_composite_region import append_region_overlay
        bounds=(job.export_context.get('overlay_alpha_bounds') or {}).get(str(path)) or (0,0,width,height)
        video_label=append_region_overlay(filters,video_label,f'[movingpixels{i}]',bounds=bounds,
            width=width,height=height,pixel_format=job.settings.pixel_format,tag=f'moving{i}',
            eof_action='pass',enable=f"enable='gte(t,{start:.9f})*lt(t,{end:.9f})'",full_canvas=True)
    if job.preview_url:
        filters.append(f'{video_label}split=2[vfinal][previewfull]')
        filters.append('[previewfull]fps=2:round=up:start_time=0:eof_action=pass,scale=640:-2[exportpreview]')
        video_label='[vfinal]'
    args = inputs + ['-filter_complex_threads', '2', '-filter_complex', ';'.join(filters), '-map', video_label]
    args += ['-map', audio_label] if audio_label else ['-an']
    return args + ['-t', f'{float(duration):.9f}']
