import pytest
from twobyteasr.playback.playback_clock import PlaybackClock


def test_forward_frame_age_uses_qpc_not_quantized_windows_uptime(monkeypatch):
    # The sample crosses one 15.625ms GetTickCount64 boundary, but only 2ms
    # actually passed. Forward-only correction must not turn it into a jump.
    monkeypatch.setattr('twobyteasr.playback.playback_clock.time.monotonic',lambda:.03125)
    monkeypatch.setattr('twobyteasr.playback.playback_clock.time.perf_counter',lambda:100.002)
    clock=PlaybackClock(now=.015625)
    clock.force_position(1000,paused=False,now=.015625)
    sample,accepted,_=clock.observe(1000,source_generation=0,actor_sequence=1,
        observed_monotonic_ts=.015625,observed_perf_counter_ts=100.,
        playback_rate=1.,paused=False,seeking=False,align_forward=True,presentation_media_ms=1001)
    assert accepted and sample.presentation_media_ms==pytest.approx(1002)
    assert sample.playback_generation==0


def test_explicit_test_clock_does_not_mix_with_live_qpc():
    clock=PlaybackClock(now=0.)
    clock.force_position(1000,paused=False,now=0.)
    sample,accepted,_=clock.observe(1000,source_generation=0,actor_sequence=1,
        observed_monotonic_ts=.1,observed_perf_counter_ts=100.,now=.103,
        playback_rate=1.,paused=False,seeking=False,align_forward=True,presentation_media_ms=1001)
    assert accepted and sample.presentation_media_ms==pytest.approx(1003)
