import pytest
from twobyteasr.playback.audio_readiness import audio_readiness


def inputs():
    request=dict(audible=True, paused=True, source_path='clip', transport_generation=(2,3), session_generation=4, clip_rate=1., transport_rate=1.)
    state=dict(state='PAUSED', source_path='clip', transport_generation=(2,3), session_generation=4, effective_rate=1., buffer_bytes=19200)
    return request,state


@pytest.mark.parametrize('failure', ['ENDPOINT_FAILED','DECODER_FAILED','NO_OUTPUT_DEVICE','UNSUPPORTED_OUTPUT_FORMAT'])
def test_failure_is_not_ready_even_with_stale_pcm_or_eof(failure):
    request,state=inputs();state.update(state=failure,decoder_eof=True,decoded_bytes=96000)
    result=audio_readiness(request,state)
    assert result.failed and not result.ready


@pytest.mark.parametrize('field,value', [('source_path','other'),('transport_generation',(1,3)),('session_generation',3),('effective_rate',2.)])
def test_old_owner_observation_cannot_release_play(field,value):
    request,state=inputs();state[field]=value
    assert not audio_readiness(request,state).ready


def test_no_audio_request_needs_no_device_and_no_fake_pcm():
    assert audio_readiness({'audible':False},{'state':'ENDPOINT_FAILED'}).ready


def test_real_prebuffer_and_short_eof_require_current_owned_pcm():
    request,state=inputs()
    assert audio_readiness(request,state).ready
    assert not audio_readiness(request,state,sync_inflight=True).ready
    state.update(buffer_bytes=0,decoder_eof=True,decoded_bytes=0)
    assert not audio_readiness(request,state).ready
    state['buffer_bytes']=4
    assert audio_readiness(request,state).ready


def test_late_failure_from_retired_project_does_not_fail_current_request():
    request,state=inputs();state.update(state='ENDPOINT_FAILED',session_generation=3)
    result=audio_readiness(request,state)
    assert not result.failed and not result.ready and result.reason=='old_observation'
