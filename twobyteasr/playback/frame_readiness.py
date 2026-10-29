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
