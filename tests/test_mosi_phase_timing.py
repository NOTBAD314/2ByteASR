"""Phase timing is transport wall time, never a fabricated server stopwatch."""
import json
import numpy as np
import pytest

from tests.test_no_cuda_cloud_asr import MosiClient, mosi_endpoint
from twobyteasr.providers.mosi_asr import transcribe


def test_phase_counts_cached_resume_and_no_secrets(tmp_path):
    client, phases = MosiClient(), []
    audio = np.zeros(32000, dtype=np.float32)
    first = transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=lambda _: None, on_timing=phases.append)
    assert len(phases) == 1
    info = phases[0]
    assert info['submit_requests'] == 1 and info['poll_requests'] == 2
    assert info['remote_processing_seconds'] is None
    assert info['wall_seconds'] >= info['encode_upload_submit_seconds'] >= 0
    assert info['remote_wait_and_result_seconds'] >= info['poll_http_seconds'] >= 0
    assert 'sk-test' not in json.dumps(info) and 'Bearer' not in json.dumps(info)
    transcribe(audio, mosi_endpoint(), tmp_path, client=client, sleep=lambda _: None, on_timing=phases.append)
    assert phases[1]['cache_hit'] and phases[1]['submit_requests'] == phases[1]['poll_requests'] == 0
    assert len(client.posts) == 1


def test_failure_timing_is_retained_without_resubmission(tmp_path):
    client, phases = MosiClient(submit_status=402), []
    with pytest.raises(Exception):
        transcribe(np.zeros(32000, dtype=np.float32), mosi_endpoint(), tmp_path, client=client,
                   sleep=lambda _: None, on_timing=phases.append)
    assert phases[0]['outcome'] == 'failed' and phases[0]['submit_requests'] == 1
    assert phases[0]['poll_requests'] == 0
