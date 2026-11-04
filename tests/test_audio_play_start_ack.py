from types import SimpleNamespace
import pytest
from twobyteasr.playback.audio_engine import StudioAudioEngine, BYTES_PER_SECOND


def engine(*, paused=True, inflight=True, audible=True, state='PREBUFFERED', eof=False):
    request=dict(audible=audible,paused=paused,source_path='owned.mp4',transport_generation=(7,2),clip_rate=1.,transport_rate=1.)
    telemetry=dict(source_path='owned.mp4',transport_generation=(7,2),effective_rate=1.,state=state,
                   buffer_bytes=0 if eof else BYTES_PER_SECOND,decoder_eof=eof)
    return SimpleNamespace(_last_payload=request,_telemetry=telemetry,_sync_inflight=inflight)


@pytest.mark.parametrize('eof',[False,True])
def test_prebuffer_does_not_release_video_before_paused_control_ack(eof):
    e=engine(eof=eof)
    assert not StudioAudioEngine.ready_for_playback(e)
    e._sync_inflight=False
    assert StudioAudioEngine.ready_for_playback(e)


def test_ongoing_playback_does_not_wait_for_redundant_sync():
    assert StudioAudioEngine.ready_for_playback(engine(paused=False))


@pytest.mark.parametrize('e',[engine(audible=False),engine(state='NO_OUTPUT_DEVICE'),engine(state='UNSUPPORTED_OUTPUT_FORMAT')])
def test_no_audible_output_does_not_block_video(e):
    assert StudioAudioEngine.ready_for_playback(e)
