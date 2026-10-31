"""Media editing stays in project milliseconds, with each asset's own frame grid.

The editable endpoints (including legacy non-frame-aligned endpoints) own the
affine source map. No render FPS or another lane's FPS is substituted for a
missing source rate. This module never modifies a project.
"""
from fractions import Fraction


def asset_frame_rate(asset):
    metadata = getattr(asset, 'video_metadata', {}) or {}
    for key in ('frame_rate', 'avg_frame_rate', 'fps'):
        try:
            rate = Fraction(str(metadata.get(key, 0))).limit_denominator(100_100)
            if 0 < rate <= 1000:
                return rate
        except (ValueError, ZeroDivisionError, TypeError):
            pass
    return None


def source_at(clip, time_ms):
    return Fraction(clip.source_in_ms) + Fraction(
        (int(time_ms) - clip.timeline_in_ms) * (clip.source_out_ms - clip.source_in_ms),
        clip.timeline_out_ms - clip.timeline_in_ms)


def frame_time(clip, time_ms, rate, *, origin=None, extending=False):
    """Nearest representable project ms on this source grid, plus frame index.

    A continuous ancestor may own the map after repeated razors. Outward trims
    use the requested playback rate, just like studio_clip_edit._trim.
    """
    mapping = origin or clip
    if extending and int(time_ms) < clip.timeline_in_ms:
        anchor, source = clip.timeline_in_ms, clip.source_in_ms
        slope = Fraction(str(clip.playback_rate or 1))
    elif extending and int(time_ms) > clip.timeline_out_ms:
        anchor, source = clip.timeline_out_ms, clip.source_out_ms
        slope = Fraction(str(clip.playback_rate or 1))
    else:
        anchor, source = mapping.timeline_in_ms, mapping.source_in_ms
        slope = Fraction(mapping.source_out_ms - mapping.source_in_ms,
                         mapping.timeline_out_ms - mapping.timeline_in_ms)
    exact_source = Fraction(source) + (int(time_ms) - anchor) * slope
    if rate is None:
        return int(time_ms), None
    index = round(exact_source * rate / 1000)
    project_ms = round(Fraction(anchor) + (Fraction(index * 1000, 1) / rate - source) / slope)
    return int(project_ms), int(index)


def range_point(points, index, value, duration):
    """I and O keep their identities and stop at the opposite endpoint."""
    result = list(points)
    value = min(max(0, int(value)), max(0, int(duration)))
    other = result[1 - index]
    if other is not None:
        value = min(value, max(0, int(other) - 1)) if index == 0 else max(value, min(duration, int(other) + 1))
    result[index] = value
    return tuple(result)
