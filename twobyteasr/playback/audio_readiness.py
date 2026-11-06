"""Audio readiness is an owned PCM observation, never a timeout or failure."""
from dataclasses import dataclass


FAILURE_STATES = frozenset({'ENDPOINT_FAILED', 'DECODER_FAILED', 'NO_OUTPUT_DEVICE', 'UNSUPPORTED_OUTPUT_FORMAT'})


@dataclass(frozen=True)
class AudioReadiness:
    ready: bool
    failed: bool
    reason: str


def audio_readiness(request, observation, *, sync_inflight=False, default_bps=192000, prebuffer_seconds=.08):
    if not request.get('audible'):
        return AudioReadiness(True, False, 'no_audio_requested')
    if observation.get('session_generation') != request.get('session_generation'):
        return AudioReadiness(False, False, 'old_observation')
    observed_transport = observation.get('transport_generation')
    if observed_transport is not None and tuple(observed_transport) != tuple(request.get('transport_generation') or ()):
        return AudioReadiness(False, False, 'old_observation')
    state = str(observation.get('state') or '').upper()
    if state in FAILURE_STATES:
        return AudioReadiness(False, True, state)
    if request.get('paused', True) and sync_inflight:
        return AudioReadiness(False, False, 'control_pending')
    if (observation.get('source_path') != request.get('source_path')
            or tuple(observation.get('transport_generation') or ()) != tuple(request.get('transport_generation') or ())):
        return AudioReadiness(False, False, 'old_observation')
    rate = float(request.get('clip_rate', 1.)) * float(request.get('transport_rate', 1.))
    if abs(float(observation.get('effective_rate', 1.)) - rate) > .001:
        return AudioReadiness(False, False, 'old_rate')
    bps = float((observation.get('output_format') or {}).get('bytes_per_second') or default_bps)
    buffered = int(observation.get('buffer_bytes') or 0)
    short_complete = bool(observation.get('decoder_eof') and (
        buffered > 0 or int(observation.get('decoded_bytes') or 0) > 0
        or int(observation.get('sink_consumed_bytes') or 0) > 0))
    ready = buffered >= bps * prebuffer_seconds or short_complete
    return AudioReadiness(ready, False, 'pcm_ready' if ready else 'waiting_pcm')
