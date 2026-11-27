"""Read a frame-ready witness from the existing mpv actor, without doing IPC.

mpv 7b8915bc1 exposes no video-pts. Its playback-restart event follows seek
completion with video STATUS_READY, while video-frame-info queries the current
VO image. This proves an image is available for presentation, not scanout.
"""
from __future__ import annotations
import os


def same_media_path(left, right):
    return bool(left and right and
        os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right)))


# A clip edge is a millisecond in the source; pictures sit on the stream's frame grid. Without a
# measured tolerance a picture this close to an edge still belongs to it (the witness's minimum).
EDGE_TOLERANCE_S = 0.050


def frame_in_clip(witness, source_range):
    """The witnessed picture shows this clip (``source_range`` in source ms).

    2026-11-27 (user: a recognition result never opened, 准备播放器 timed out on every retry): the
    project was saved with the playhead at the timeline's end, inside the last clip
    [3391685, 3395858). The seek to 3395.857 landed on the picture at 3395.864 (after the clip:
    rightly refused), and the one fallback seek to the clip start landed on the picture at
    3391.681. That picture is on screen from 3391.681 until the next one, so it is what the
    clip shows at its first millisecond; the strict test called it outside, no picture ever
    counted and the open stalled until 准备超时. A picture is the clip's when the time it is on
    screen meets the clip: it may start up to one frame (the witness's landing tolerance,
    max(50 ms, 1.5 frames)) before the clip's first millisecond, but not at or after its end.
    """
    position = witness.get('position')
    if not (witness.get('ready') and isinstance(position, (int, float))):
        return False
    tolerance = witness.get('target_tolerance_seconds')
    if not isinstance(tolerance, (int, float)) or tolerance < 0:
        tolerance = EDGE_TOLERANCE_S
    tolerance_ms = min(float(tolerance), 0.5) * 1000.0
    start, end = float(source_range[0]), float(source_range[1])
    return start - tolerance_ms <= position * 1000 < end


def first_picture_seconds(project, media_path):
    """First video picture on mpv's clock, from the probe the project recorded.

    mpv counts from the container start; the probe saved the video stream's
    start and the container start. None when the source is not a recorded
    asset (a proxy, a project from before these fields) or has no video.
    """
    for asset in getattr(project, 'media_pool', None) or ():
        if not same_media_path(getattr(asset, 'canonical_source', ''), media_path):
            continue
        meta = getattr(asset, 'video_metadata', None) or {}
        first = meta.get('start_time_ms', meta.get('first_pts_ms'))
        if first is None or meta.get('has_video') is False:
            return None
        try:
            return max(0.0, (float(first) - float(meta.get('source_start_ms') or 0.0)) / 1000.0)
        except (TypeError, ValueError):
            return None
    return None


def video_frame_witness(video):
    controller = getattr(video, 'controller', None)
    reader = getattr(controller, 'observed_frame', None)
    if not callable(reader):
        return {'ready': False, 'status': 'unsupported',
                'measurement': 'backend has no mpv frame-ready witness'}
    result = dict(reader())
    result['ready'] = False
    alive = getattr(controller, 'source_alive', None)
    if callable(alive) and not alive():
        result['status'] = 'transport_unhealthy'
        return result
    instance = getattr(controller, 'instance_id', None)
    if instance is not None and result.get('instance_id') != instance:
        result['status'] = 'stale_instance'
        return result
    status = getattr(controller, 'actor_status', lambda: {})()
    connection = status.get('connection_generation')
    if connection is not None and result.get('connection_generation') != connection:
        result['status'] = 'stale_connection'
        return result
    clock = getattr(video, '_playback_clock', None)
    if clock is not None and clock.exact_seek_pending:
        result['status'] = 'seek_pending'
        return result
    generation = getattr(clock, 'generation', getattr(controller, 'source_epoch', None))
    media_epoch = getattr(controller, '_subtitle_binding_epoch', None)
    if result.get('source_generation') != generation:
        result['status'] = 'stale_generation'
    elif media_epoch is not None and result.get('media_epoch') != media_epoch:
        result['status'] = 'stale_media_epoch'
    elif not same_media_path(result.get('path'), getattr(video, '_media_path', '')):
        result['status'] = 'stale_source'
    elif result.get('status') == 'ready':
        result['ready'] = True
    return result
