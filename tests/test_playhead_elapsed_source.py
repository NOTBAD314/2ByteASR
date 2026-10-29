from types import SimpleNamespace

from twobyteasr.playback.playback_clock import PlaybackClock
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin


def test_flush_uses_same_elapsed_source_as_visual_tick(monkeypatch):
    # Windows Python 3.10 monotonic uses 15.625ms GetTickCount64. The Qt
    # elapsed clock already drives visual_tick, so a newer flush must consume
    # that same elapsed value rather than sampling the coarse clock again.
    monkeypatch.setattr('twobyteasr.playback.playback_clock.time.monotonic', lambda: .016)
    clock = PlaybackClock(now=0.)
    clock.force_position(500., paused=False, now=0.)
    clock.sample_presentation(now=.015, elapsed_ms=15.)
    elapsed = [20]
    received = []
    page = SimpleNamespace(
        _playhead_ui_pending=(.5, False, clock.generation, 'source'),
        video=SimpleNamespace(_playback_clock=clock, _paused=False,
                              _clock=SimpleNamespace(elapsed=lambda: elapsed[0])),
        _position_changed=lambda seconds, **kwargs: received.append(seconds*1000))
    StudioPlaybackFlowMixin._flush_pending_playhead(page)
    elapsed[0] = 24
    page._playhead_ui_pending=(.5, False, clock.generation, 'source')
    StudioPlaybackFlowMixin._flush_pending_playhead(page)
    assert received == [520., 524.]
    assert clock.generation == 0


def test_paused_flush_keeps_exact_pending_position():
    received = []
    page = SimpleNamespace(_playhead_ui_pending=(1.125, True, 0, 'source'),
        video=SimpleNamespace(_playback_clock=PlaybackClock(now=0.), _paused=True),
        _position_changed=lambda seconds, **kwargs: received.append((seconds,kwargs)))
    StudioPlaybackFlowMixin._flush_pending_playhead(page)
    assert received == [(1.125,dict(defer_follow=True,_bypass_throttle=True))]


def test_stale_generation_flush_does_not_move_playhead():
    received=[]
    page=SimpleNamespace(_playhead_ui_pending=(1.125,True,-1,'source'),
        video=SimpleNamespace(_playback_clock=PlaybackClock(now=0.),_paused=True),
        _position_changed=lambda *args,**kwargs:received.append(args))
    StudioPlaybackFlowMixin._flush_pending_playhead(page)
    assert not received
