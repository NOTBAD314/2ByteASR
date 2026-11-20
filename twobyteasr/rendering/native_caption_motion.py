"""Entrance/exit frames of held captions, derived natively from their browser still.

2026-11-19: with every caption animated, Chrome drew each entrance/exit frame
(~20 ms per 1080p frame, mostly fixed per-frame overhead) and exports stayed
near real time. A held cue's still already is its exact browser rendering,
so its entrance/exit frames are produced here by applying TrustedSubtitle's
own per-frame motion (opacity, offsets, punch scale, collapse, rotation,
wipe clip) to that still with QPainter. Approximations: letter-spacing
changes of soft entrances become a horizontal scale and the glow does not
re-settle. Anything else (type-on, per-letter, glitch, blur-out,
decorations) returns None and keeps rendering in the browser.
"""
from __future__ import annotations

import math

SOFT_TYPES = frozenset({'fade', 'slide', 'drop', 'scale', 'rotate', 'flip', 'wipe', 'mask_reveal',
                        'type_on', 'letter_stagger'})
PUNCH_TYPES = frozenset({'spring_pop', 'overshoot', 'slam', 'squash_stretch'})
UNSUPPORTED_ENTRANCES = frozenset({'type_on', 'letter_stagger', 'slam'})
UNSUPPORTED_EXITS = frozenset({'blur_out'})


def _js_round(value):
    return math.floor(value + .5)


def _number(part, key, fallback):
    value = part.get(key) if isinstance(part, dict) else None
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else float(fallback)


def _kind(part, fallback='none'):
    value = part.get('type') if isinstance(part, dict) else None
    return value if isinstance(value, str) and value else fallback


def _clamp(value, low=0., high=1.):
    return max(low, min(high, value))


def _direction(direction, amount):
    if direction == 'right':
        return amount, 0.
    if direction == 'up':
        return 0., -amount
    if direction == 'down':
        return 0., amount
    return -amount, 0.


def native_supported(visual):
    """True when every frame of this cue is a transform of its held still."""
    visual = visual or {}
    if visual.get('webTheme') or visual.get('visualGraph') or visual.get('decorations'):
        return False
    words = visual.get('wordAnimation') or {}
    if words.get('spans') or words.get('units') or words.get('marks'):
        return False
    motion = visual.get('motion') or {}
    entrance, exit_, hold = (motion.get(k) or {} for k in ('entrance', 'exit', 'hold'))
    entry = _kind(entrance, motion.get('entry') if isinstance(motion.get('entry'), str) else 'none')
    if _kind(hold) != 'none' or 'glitch' in entry or entry in UNSUPPORTED_ENTRANCES:
        return False
    return _kind(exit_) not in UNSUPPORTED_EXITS


def motion_state(visual, frame, duration_frames, fps):
    """TrustedSubtitle's per-frame motion (frame = cue-local frame)."""
    motion = (visual or {}).get('motion') or {}
    entrance, exit_ = motion.get('entrance') or {}, motion.get('exit') or {}
    entry = _kind(entrance, motion.get('entry') if isinstance(motion.get('entry'), str) else 'none')
    exit_type = _kind(exit_)
    enabled = motion.get('mode') == 'explicit' or (motion.get('mode') is None and (entry != 'none' or exit_type != 'none'))
    entering, exiting = enabled and entry != 'none', enabled and exit_type != 'none'
    duration = motion.get('duration') if isinstance(motion.get('duration'), (int, float)) else 240
    entrance_frames = max(1, _js_round(_number(entrance, 'duration_ms', duration)/1000*fps))
    exit_frames = max(1, _js_round(_number(exit_, 'duration_ms', 160)/1000*fps))
    progress = _clamp(frame/entrance_frames) if entering else 1.
    leaving = 0.
    if exiting:
        begin = max(0, duration_frames - exit_frames)
        span = duration_frames - begin
        leaving = _clamp((frame - begin)/span) if span > 0 else (1. if frame >= duration_frames else 0.)
    punch = entering and (entry in PUNCH_TYPES or any(word in entry for word in ('impact', 'punch', 'bounce')))
    soft = entering and (entry in SOFT_TYPES or any(word in entry for word in ('neon', 'fade_float', 'tracking')))
    scale = 1.
    if punch:
        if progress < .45:
            scale = .70 + (1.18-.70)*progress/.45
        elif progress < .72:
            scale = 1.18 + (.96-1.18)*(progress-.45)/.27
        else:
            scale = .96 + (1-.96)*(progress-.72)/.28
    direction = entrance.get('direction') if isinstance(entrance.get('direction'), str) else ('down' if entry == 'drop' else 'left')
    entry_x, entry_y = _direction(direction, (1-progress)*_number(entrance, 'amplitude', 28)) if entering else (0., 0.)
    exit_x, exit_y = _direction(exit_.get('direction') if isinstance(exit_.get('direction'), str) else 'down',
                                leaving*_number(exit_, 'amplitude', 34)) if exiting else (0., 0.)
    opacity = (progress if soft else min(1., progress*1.7)) if entering else 1.
    opacity *= (1-leaving) if exiting else 1.
    collapse = 1-leaving*.85 if exit_type == 'collapse' else 1.
    exit_scale = 1-leaving*.12 if exiting else 1.
    clip = (progress if entering and entry in ('wipe', 'mask_reveal') else 1.)
    clip *= 1 - (leaving if exiting and exit_type in ('wipe', 'mask_close') else 0.)
    return dict(
        opacity=_clamp(opacity), dx=entry_x + exit_x, dy=(entry_y if soft else 0.) + exit_y,
        scale_x=scale*collapse*exit_scale,
        scale_y=scale*(.92 if punch and progress < .45 else 1.)*collapse*exit_scale,
        rotation=(1-progress)*_number(entrance, 'rotation', -8) if entry in ('rotate', 'flip') else 0.,
        clip=_clamp(clip), tracking=(1-progress)*8 if soft else 0.)


def render_window(still_path, bounds, visual, text, frames, sink, *, width, height, cancelled=None):
    """Write BGRA canvas frames for ``frames`` [(local_frame, duration_frames, fps)]."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QTransform
    still = QImage(str(still_path)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if still.isNull():
        raise ValueError('The caption still could not be read')
    x0, y0, x1, y1 = (float(v) for v in bounds)
    layout = (visual or {}).get('layout') or {}
    anchor_x = float(layout.get('anchorX', .5) if isinstance(layout.get('anchorX', .5), (int, float)) else .5)
    anchor_y = float(layout.get('anchorY', 1.) if isinstance(layout.get('anchorY', 1.), (int, float)) else 1.)
    # Transform origin: the caption's anchor, estimated on its visible still.
    origin = QPointF(x0 + anchor_x*(x1-x0), y0 + anchor_y*(y1-y0))
    glyphs = max(1, len(str(text or '').replace('\n', '')))
    canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    for local, duration_frames, fps in frames:
        if cancelled and cancelled():
            raise InterruptedError('render cancelled')
        state = motion_state(visual, local, duration_frames, fps)
        canvas.fill(Qt.GlobalColor.transparent)
        if state['opacity'] > 0 and state['clip'] > 0 and state['scale_x'] > 0 and state['scale_y'] > 0:
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setOpacity(state['opacity'])
            spread = (x1-x0 + glyphs*state['tracking'])/max(1., x1-x0)
            transform = QTransform()
            transform.translate(origin.x() + state['dx'], origin.y() + state['dy'])
            transform.rotate(state['rotation'])
            transform.scale(state['scale_x']*spread, state['scale_y'])
            transform.translate(-origin.x(), -origin.y())
            painter.setTransform(transform)
            source = QRectF(0, 0, still.width()*state['clip'], still.height())
            painter.drawImage(QRectF(x0, y0, source.width(), source.height()), still, source)
            painter.end()
        # Overlays carry straight alpha (like the browser's PNG frames). Keep
        # the converted image referenced: constBits() is only a view into it.
        straight = canvas.convertToFormat(QImage.Format.Format_ARGB32)
        sink(straight.constBits())
        del straight


def render_native_windows(windows, ffmpeg, folder, *, width, height, cancelled=None):
    """windows: [(start, end, still_path, bounds, visual, text, frames, fps)].

    Returns ([(start, end, path)], [(start, end, error)]); a failed window is
    reported for the browser to render instead of failing the export.
    """
    from concurrent.futures import ThreadPoolExecutor
    # Each window is a short encoder process; starting them one by one cost
    # ~0.1 s per caption. QPainter on separate images is thread-safe.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='native-caption') as pool:
        results = list(pool.map(lambda window: _render_one(window, ffmpeg, folder, width, height, cancelled), windows))
    specs = [spec for spec, _ in results if spec]
    failed = [error for _, error in results if error]
    return specs, failed


def _render_one(window, ffmpeg, folder, width, height, cancelled):
    """((start, end, path), None) or (None, (start, end, error))."""
    from pathlib import Path
    from tempfile import TemporaryFile
    from ..system.processes import popen_hidden_subprocess
    import subprocess
    start, end, still_path, bounds, visual, text, frames, fps = window
    if cancelled and cancelled():
        raise InterruptedError('render cancelled')
    target = Path(folder) / f'overlay-native-{start}-{end}.mov'
    try:
        with TemporaryFile() as log:
            process = popen_hidden_subprocess([
                str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-nostdin',
                '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', f'{width}x{height}',
                '-framerate', f'{float(fps):.9f}', '-i', 'pipe:0',
                '-frames:v', str(len(frames)), '-c:v', 'qtrle', '-pix_fmt', 'argb', '-threads', '2',
                '-video_track_timescale', '90000', str(target),
            ], purpose='native caption entrance/exit',
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
            try:
                render_window(still_path, bounds, visual, text, frames, process.stdin.write,
                              width=width, height=height, cancelled=cancelled)
                process.stdin.close()
                if process.wait(timeout=120) != 0 or not target.is_file() or target.stat().st_size == 0:
                    log.seek(0, 2)
                    log.seek(max(0, log.tell() - 800))
                    error = log.read().decode('utf-8', 'replace')
                    raise RuntimeError(f'native caption window encode failed: {error}')
                return (start, end, target), None
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                try:
                    process.stdin.close()
                except OSError:
                    pass
    except InterruptedError:
        raise
    except Exception as exc:
        return None, (start, end, f'{type(exc).__name__}: {exc}'[:400])
