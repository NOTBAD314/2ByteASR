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
