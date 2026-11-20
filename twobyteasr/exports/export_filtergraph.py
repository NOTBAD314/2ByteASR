"""One final encode for proven video graphs, using the shared audio mix.

Clip boundaries are quantized once on the output frame lattice, not once per
clip duration. This retains gaps, reordering, repeats, rates and nonzero ranges.

Default-geometry clips that never overlap join one concatenated timeline. Since
2026-11-19 transformed and stacked clips (picture-in-picture, scale, position,
anchor, fit mode, opacity, rotation about the centre) are composited by FFmpeg
overlays in the same paint order as the preview's QPainter compositor, instead
of a full Python raster pass plus a lossless intermediate. Blend modes, keys,
transitions and frame images keep the raster compositor.
"""
from fractions import Fraction
import math

# Each overlay clip is one more simultaneously open input and decoder.
DIRECT_LAYER_LIMIT = 32
_DEFAULTS = dict(anchor_x=.5, anchor_y=.5, position_x=.5, position_y=.5,
                 scale_x=1., scale_y=1., rotation=0., opacity=1., fit_mode='contain')


def overlay_pts_shift(seconds, fps, path=None):
    """Use the output frame lattice when an overlay starts on that lattice.

    A merged ``.ffconcat`` overlay is re-stamped by frame number first: its
    gap clips end half a frame early (exact frame counts), so container
    timestamps drift while frame order stays exact.
    """
    rate = Fraction(str(fps)).limit_denominator(100100)
    base = f'N/({rate}*TB)' if path is not None and str(path).endswith('.ffconcat') else 'PTS'
    frames = round(Fraction(str(seconds))*rate)
    if abs(float(Fraction(frames)/rate)-seconds) < 1e-7:
        return f'{base}+{frames}/({rate}*TB)'
    return f'{base}+{seconds:.9f}/TB'


def overlay_timing_filter(seconds, fps, path=None):
    """Timestamp filter placing an overlay input on the output frame lattice.

    Overlay times are rebuilt exactly as the timeline's ``N/(fps*TB)`` in
    AVTB is (a double, truncated): a rescaled timestamp rounds to nearest and
    can land a microsecond after its frame, showing the previous overlay.
    """
    rate = Fraction(str(fps)).limit_denominator(100100)
    frames = round(Fraction(str(seconds))*rate)
    if abs(float(Fraction(frames)/rate) - float(seconds)) >= 1e-7:
        return f'setpts={overlay_pts_shift(seconds, fps, path)}'
    # The same for every overlay on the lattice: a rescaled first frame (an
    # RLE window at 1/90000) used to land just after its output frame, so
    # each animated window lost its first frame in media-graph exports.
    index = 'N' if str(path).endswith('.ffconcat') else f'round(T*{rate})'
    return f'settb=AVTB,setpts=({index}+{frames})/({rate}*TB)'


def overlay_input_args(path):
    """Input options for an overlay file (a merged concat list needs its demuxer)."""
    return ['-f', 'concat', '-safe', '0', '-i', str(path)] if str(path).endswith('.ffconcat') else ['-i', str(path)]


def _transform(clip):
    return dict(_DEFAULTS, **(clip.get('transform') or {}))


def _default_geometry(clip):
    transform = clip.get('transform') or {}
    return all(transform.get(k, v) == v for k, v in _DEFAULTS.items())


def _overlaps(clips):
    ordered = sorted(clips, key=lambda c: (c['timeline_in_ms'], c['id']))
    return any(a['timeline_out_ms'] > b['timeline_in_ms'] for a, b in zip(ordered, ordered[1:]))


def direct_video_layout(graph):
    """{'base': clips concatenated on black, 'layers': overlay clips} or None.

    Layers are listed in the raster compositor's paint order: tracks by
    (z_index, id), clips in track order.
    """
    if not graph or graph.get('audio_mix') is None or any(t.get('media') == 'video' for t in graph.get('clip_transitions', [])):
        return None
    assets = {a['asset_id']: a for a in graph.get('media_pool', [])}
    from ..media.animated_gif import is_frame_image
    tracks = sorted(((i, t) for i, t in enumerate(graph.get('video_tracks', [])) if t.get('enabled', True)),
                    key=lambda item: (item[1].get('z_index', 0), str(item[1].get('id', '')), item[0]))
    ordered = []
    for track_index, track in tracks:
        for clip in track.get('clips', []):
            if not clip.get('enabled', True):
                continue
            asset = assets.get(clip['asset_id'])
            if asset is None or is_frame_image(asset.get('canonical_source', '')):
                return None
            if (asset.get('video_metadata') or {}).get('has_video') is False:
                return None
            effects = clip.get('effects') or {}
            if effects.get('blendMode', 'normal') != 'normal' or (effects.get('chromaKey') or {}).get('enabled'):
                return None
            if effects.keys() - {'blendMode', 'chromaKey'}:
                return None
            if float(clip.get('playback_rate', 1)) <= 0:
                return None
            transform = _transform(clip)
            if transform['fit_mode'] not in {'contain', 'cover', 'stretch'}:
                return None
            if float(transform['rotation']) % 360 and (transform['anchor_x'] != .5 or transform['anchor_y'] != .5):
                # FFmpeg rotates about the picture centre; QPainter about the anchor.
                return None
            ordered.append((track_index, clip))
    clips = [clip for _, clip in ordered]
    if all(_default_geometry(c) for c in clips) and not _overlaps(clips):
        return dict(base=sorted(clips, key=lambda c: (c['timeline_in_ms'], c['id'])), layers=[])
    lowest = ordered[0][0] if ordered else None
    base = [c for track, c in ordered if track == lowest]
    if not all(_default_geometry(c) for c in base) or _overlaps(base):
        base = []
    layers = [c for c in clips if not any(c is b for b in base)]
    if len(layers) > DIRECT_LAYER_LIMIT:
        return None
    return dict(base=sorted(base, key=lambda c: (c['timeline_in_ms'], c['id'])), layers=layers)


def simple_video_clips(graph):
    """Clips of a graph the direct FFmpeg route can render, else None.

    Kept as the single route gate for callers (and tests that force the
    raster compositor by replacing it).
    """
    layout = direct_video_layout(graph)
    return None if layout is None else layout['base'] + layout['layers']


def _scale_expression(transform, width, height):
    sx = max(.01, float(transform['scale_x']))
    sy = max(.01, float(transform['scale_y']))
    source_w = 'iw*sar'
    if transform['fit_mode'] == 'stretch':
        w, h = f'{width}*{sx:.9g}', f'{height}*{sy:.9g}'
    else:
        pick = 'max' if transform['fit_mode'] == 'cover' else 'min'
        factor = f'{pick}({width}/({source_w}),{height}/ih)'
        w, h = f'{source_w}*{factor}*{sx:.9g}', f'ih*{factor}*{sy:.9g}'
    # Quoted: the expressions contain commas.
    return f"scale=w='max(2,round({w}))':h='max(2,round({h}))':eval=init"


def compile_video_filtergraph(ffmpeg, job, ass_filter, *, caption_overlays=(), caption_filter=None, video_overlays=()):
    from .audio_export import compile_audio_mix
    from ..timeline.clip_time_mapper import project_to_source_exact
    from .timeline_media import resolve_video_graph
    from .studio_render import video_input_acceleration
    graph = resolve_video_graph(job.direct_video_graph, ffmpeg)
    layout = direct_video_layout(graph)
    if layout is None:
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

    def frame_window(clip):
        first = max(0, math.ceil((Fraction(clip['timeline_in_ms'], 1000)-start)*fps))
        last = min(count, math.ceil((Fraction(clip['timeline_out_ms'], 1000)-start)*fps))
        return first, last

    def clip_input(clip, first, last):
        """Add one exact source window; return the timed filter prefix."""
        nonlocal input_count
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
        inputs.extend(['-threads', '4'])
        inputs.extend(video_input_acceleration(job))
        if seek > 0:
            inputs.extend(['-ss', f'{float(seek):.9f}'])
        inputs.extend(['-t', f'{float(source_window):.9f}', '-i', source_path])
        index = input_count
        input_count += 1
        # A container/clip can outlast its video stream while real audio and
        # captions remain. Hold this input's last decoded frame before trimming
        # so a range starting in that tail still has a frame. The finite window
        # and exact end_frame bound each isolated piece; no frame can spill into
        # a gap or the next source, and an input with no frames still fails.
        return (f'[{index}:v:0]tpad=stop_mode=clone:stop_duration={float(source_window):.9f},'
                f'trim=start={float(trim):.9f},setpts=(PTS-{float(trim):.9f}/TB)/({rate}),fps={fps}:round=up:start_time=0')

    for clip in layout['base']:
        first, last = frame_window(clip)
        if last <= first:
            continue
        if first > cursor:
            blank(first-cursor)
        label = f'piece{len(pieces)}'
        filters.append(clip_input(clip, first, last) + ','
                       f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                       f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                       f'tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={last-first},'
                       f'settb=AVTB,setpts=N/({fps}*TB)[{label}]')
        pieces.append(f'[{label}]')
        cursor = last
    if cursor < count:
        blank(count-cursor)
    filters.append(''.join(pieces)+f'concat=n={len(pieces)}:v=1:a=0,settb=AVTB,setpts=N/({fps}*TB)[timeline0]')
    timeline = '[timeline0]'
    for i, clip in enumerate(layout['layers']):
        first, last = frame_window(clip)
        if last <= first:
            continue
        transform = _transform(clip)
        steps = [clip_input(clip, first, last), _scale_expression(transform, width, height), 'setsar=1', 'format=yuva420p']
        opacity = max(0., min(1., float(transform['opacity'])))
        if opacity < 1:
            steps.append(f"lut=a='val*{opacity:.6f}'")
        rotation = float(transform['rotation']) % 360
        if rotation:
            radians = f'{math.radians(rotation):.12f}'
            steps.append(f"rotate=a={radians}:ow='rotw({radians})':oh='roth({radians})':c=none")
        steps.append(f'tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={last-first},'
                     f'settb=AVTB,setpts=(N+{first})/({fps}*TB)')
        filters.append(','.join(steps) + f'[layer{i}]')
        # Anchor point lands on the position (rotation only about the centre).
        x = f"{float(transform['position_x']):.9g}*W-{float(transform['anchor_x']):.9g}*w"
        y = f"{float(transform['position_y']):.9g}*H-{float(transform['anchor_y']):.9g}*h"
        # AVTB rounds fractional frame timestamps to microseconds. Use the frame
        # number to preserve the exact first and excluded last frame.
        filters.append(f"{timeline}[layer{i}]overlay=x='{x}':y='{y}':eof_action=pass:format=auto:"
                       f"enable='gte(n,{first})*lt(n,{last})'[stack{i}]")
        timeline = f'[stack{i}]'
    filters.append(f'{timeline}setpts=PTS+{float(start):.9f}/TB,{ass_filter},setpts=PTS-{float(start):.9f}/TB[vout]')
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
        # Half a frame of margin: output frame times are truncated microseconds.
        half = .5/float(fps)
        window = f'gte(t,{start-half:.9f})*lt(t,{end-half:.9f})'
        index = inputs.count('-i')
        inputs += overlay_input_args(path)
        filters.append(f'[{index}:v]{overlay_timing_filter(start, fps, path)}[movingpixels{i}]')
        from .caption_composite_region import append_region_overlay
        bounds=(job.export_context.get('overlay_alpha_bounds') or {}).get(str(path)) or (0,0,width,height)
        video_label=append_region_overlay(filters,video_label,f'[movingpixels{i}]',bounds=bounds,
            width=width,height=height,pixel_format=job.settings.pixel_format,tag=f'moving{i}',
            eof_action='pass',enable=f"enable='{window}'",full_canvas=True)
    if job.preview_url:
        filters.append(f'{video_label}split=2[vfinal][previewfull]')
        filters.append('[previewfull]fps=2:round=up:start_time=0:eof_action=pass,scale=640:-2[exportpreview]')
        video_label='[vfinal]'
    args = inputs + ['-filter_complex_threads', '2', '-filter_complex', ';'.join(filters), '-map', video_label]
    args += ['-map', audio_label] if audio_label else ['-an']
    return args + ['-t', f'{float(duration):.9f}']
