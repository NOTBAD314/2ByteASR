"""A video EOF may hand off only to its current, physical audio transport."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
import os


def same_source(first, second):
    return bool(first and second) and os.path.normcase(os.path.abspath(str(first))) == os.path.normcase(os.path.abspath(str(second)))


def owned_audio_sample(payload, request, *, generation, session, source, paused, rate):
    """Reject stale PCM, unrelated/mixed sources and unavailable endpoints."""
    if not isinstance(payload, Mapping) or not isinstance(request, Mapping):
        return False
    transport = tuple(payload.get('transport_generation') or ())
    expected = tuple(request.get('transport_generation') or ())
    if (not transport or transport != expected or int(transport[0]) != generation
            or payload.get('session_generation') != session
            or request.get('session_generation') != session
            or not same_source(payload.get('source_path'), source)
            or not same_source(request.get('source_path'), source)
            or not request.get('audible') or request.get('mix_layers')
            or bool(payload.get('paused')) != bool(paused)
            or not payload.get('engine_thread_alive')):
        return False
    state = str(payload.get('state') or '').upper()
    sink = str(payload.get('sink_state') or '')
    if state not in ({'PAUSED', 'BUFFERED'} if paused else {'PLAYING', 'SYNCED', 'DRAINING'}):
        return False
    if sink not in ({'SuspendedState', 'StoppedState', 'ActiveState', 'IdleState'} if paused else {'ActiveState', 'IdleState'}):
        return False
    if payload.get('sink_error') not in (None, 'NoError') or not payload.get('output_device_id'):
        return False
    try:
        return (int(payload.get('decoded_bytes') or 0) > 0
                and math.isfinite(float(payload.get('estimated_source_ms')))
                and abs(float(payload.get('effective_rate')) - rate) < .001)
    except (TypeError, ValueError):
        return False


def audio_pcm_drained(payload):
    """Producer EOF alone cannot stop PCM still in the ring or native sink."""
    if not payload.get('decoder_eof') or int(payload.get('buffer_bytes') or 0):
        return False
    decoded = int(payload.get('decoded_bytes') or 0)
    consumed = int(payload.get('sink_consumed_bytes') or 0)
    bps = int((payload.get('output_format') or {}).get('bytes_per_second') or 0)
    if decoded <= 0 or consumed < decoded or bps <= 0:
        return False
    return (payload.get('sink_state') == 'IdleState'
            or float(payload.get('processed_us') or 0) >= decoded * 1_000_000 / bps)


def held_video_frame_ready(tail, *, generation, attached, running, frame, properties):
    """Reopen at an audio tail still requires the current real video actor."""
    params = properties.get('video-out-params') or {}
    decoded = properties.get('video-frame-info') or {}
    has_frame = bool(decoded.get('pts') is not None
        or decoded.get('estimated-frame-number') is not None
        or decoded.get('picture-type'))
    return bool(tail is not None and attached and running
        and has_frame
        and frame.get('position') is not None
        and int(frame.get('source_generation', -1)) == generation
        and same_source(properties.get('path'), tail.source)
        and int(params.get('dw') or params.get('w') or 0) > 0
        and int(params.get('dh') or params.get('h') or 0) > 0)


@dataclass(frozen=True)
class OwnedAudioTail:
    project_identity: int
    preview_key: str
    clip_id: str
    source: str
    generation: int
    session: int
    transport: tuple
    audio_generation: int
    boundary_ms: int
    paused: bool
    rate: float

    def matches(self, *, project, key, clip, generation, payload):
        return (id(project) == self.project_identity and key == self.preview_key
                and clip == self.clip_id and generation == self.generation
                and payload.get('session_generation') == self.session
                and same_source(payload.get('source_path'), self.source)
                and bool(payload.get('paused')) == self.paused
                and abs(float(payload.get('effective_rate') or 0) - self.rate) < .001
                and tuple(payload.get('transport_generation') or ()) == self.transport
                and int(payload.get('source_generation') or 0) == self.audio_generation)


@dataclass(frozen=True)
class AudioTailWait:
    """A pending seek is not audio ownership; a prior PCM receipt may hold its image."""
    project_identity: int
    preview_key: str
    clip_id: str
    source: str
    generation: int
    session: int
    rate: float
    project_ms: int
    source_ms: float
    visual_receipt: OwnedAudioTail | None = None

    def matches(self, *, project, key, clip, source, generation, session, rate):
        return (id(project) == self.project_identity and key == self.preview_key
                and clip == self.clip_id and same_source(source, self.source)
                and generation == self.generation and session == self.session
                and abs(rate - self.rate) < .001)

    def may_hold_visual(self, request):
        receipt = self.visual_receipt
        return bool(receipt is not None
            and request.get('session_generation') == self.session
            and tuple(request.get('transport_generation') or ()) == receipt.transport
            and same_source(request.get('source_path'), self.source)
            and request.get('audible') and not request.get('mix_layers')
            and abs(float(request.get('transport_rate') or 1.)
                    * float(request.get('clip_rate') or 1.) - self.rate) < .001)


def tail_caption_publication_ready(scene, *, project, generation, expected, publications):
    """Startup waits for the current bitmap to reach the physical video actor."""
    if not expected:
        return True
    token = getattr(scene, 'token', None)
    trace = getattr(scene, 'trace', lambda:{})()
    return bool(scene is not None and scene.project is project
        and getattr(scene, 'active', False) and not getattr(scene, 'closed', False)
        and getattr(scene, 'published', None) is not None
        and token is not None and token[0] == id(project) and token[3] == generation
        and tuple(token[4]) == tuple(expected)
        and trace.get('visible') and tuple(trace.get('rendered_cue_ids', ())) == tuple(expected)
        and any(row.get('applied') and row.get('scene_token') == token for row in publications))
