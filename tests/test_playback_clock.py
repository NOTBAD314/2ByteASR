from twobyteasr.playback.playback_clock import PlaybackClock


def test_debug_write_audit_records_source_old_new_and_stack(monkeypatch):
    monkeypatch.setenv("TWOBYTEASR_PROJECT_CLOCK_AUDIT", "1")
    clock = PlaybackClock(now=1.0)
    clock.begin_seek(10_000, now=2.0)
    writes = clock.write_audit()
    assert writes[-1]["source"] == "user_project_seek"
    assert writes[-1]["old_ms"] == 0.0
    assert writes[-1]["new_ms"] == 10_000.0
    assert writes[-1]["stack"]


def test_late_observation_cannot_snap_forward_playback_backward():
    clock = PlaybackClock(now=0.0)
    clock.force_position(21_900.0, paused=False, now=0.0, reason="fixture")

    before = clock.sample_presentation(now=0.15)
    observed, accepted, reason = clock.observe(
        21_310.0,
        source_generation=0,
        actor_sequence=1,
        observed_monotonic_ts=0.15,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=0.15,
        presentation_media_ms=before.presentation_media_ms,
    )
    after = clock.sample_presentation(now=0.30)

    assert accepted
    assert reason == "backward_absorbed"
    assert observed.presentation_media_ms >= before.presentation_media_ms
    assert after.presentation_media_ms >= observed.presentation_media_ms


def test_seek_generation_rejects_old_and_pre_ack_positions():
    clock = PlaybackClock(now=0.0)
    clock.force_position(20_000.0, paused=False, now=0.0, reason="fixture")
    optimistic = clock.begin_seek(31_500.0, now=1.0)

    stale, accepted, reason = clock.observe(
        20_200.0,
        source_generation=0,
        actor_sequence=10,
        observed_monotonic_ts=1.01,
        playback_rate=1.0,
        paused=False,
        seeking=True,
        now=1.01,
    )
    assert not accepted
    assert reason == "stale_generation"
    assert stale.presentation_media_ms >= optimistic.presentation_media_ms

    early, accepted, reason = clock.observe(
        30_900.0,
        source_generation=1,
        actor_sequence=11,
        observed_monotonic_ts=1.02,
        playback_rate=1.0,
        paused=False,
        seeking=True,
        now=1.02,
    )
    assert not accepted
    assert reason == "seek_target_not_acknowledged"
    assert early.presentation_media_ms >= 31_500.0

    acknowledged, accepted, reason = clock.observe(
        31_492.0,
        source_generation=1,
        actor_sequence=12,
        observed_monotonic_ts=1.03,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=1.03,
    )
    assert accepted
    assert reason == "seek_acknowledged"
    assert not acknowledged.exact_seek_pending


def test_seek_ack_allows_matching_playback_progress_after_poll_interval():
    clock = PlaybackClock(now=0.0)
    clock.force_position(20_000.0, paused=True, now=0.0, reason="fixture")
    clock.begin_seek(31_500.0, now=1.0)

    too_far, accepted, reason = clock.observe(
        32_500.0,
        source_generation=1,
        actor_sequence=1,
        observed_monotonic_ts=1.15,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=1.15,
    )
    assert not accepted
    assert reason == "seek_target_not_acknowledged"
    assert too_far.exact_seek_pending

    progressed, accepted, reason = clock.observe(
        31_650.0,
        source_generation=1,
        actor_sequence=2,
        observed_monotonic_ts=1.2,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=1.2,
    )
    assert accepted
    assert reason == "seek_acknowledged"
    assert not progressed.exact_seek_pending


def test_actor_sequence_is_monotonic_within_generation():
    clock = PlaybackClock(now=0.0)
    clock.force_position(1_000.0, paused=False, now=0.0, reason="fixture")
    first, accepted, _reason = clock.observe(
        1_100.0,
        source_generation=0,
        actor_sequence=4,
        observed_monotonic_ts=0.1,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=0.1,
    )
    assert accepted

    repeated, accepted, reason = clock.observe(
        900.0,
        source_generation=0,
        actor_sequence=4,
        observed_monotonic_ts=0.2,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=0.2,
    )
    assert not accepted
    assert reason == "stale_actor_sequence"
    assert repeated.presentation_media_ms >= first.presentation_media_ms


def test_pause_observation_does_not_create_visible_backward_jump():
    clock = PlaybackClock(now=0.0)
    clock.force_position(10_000.0, paused=False, now=0.0, reason="fixture")
    current = clock.sample_presentation(now=0.2)
    paused, accepted, reason = clock.observe(
        9_800.0,
        source_generation=0,
        actor_sequence=1,
        observed_monotonic_ts=0.2,
        playback_rate=1.0,
        paused=True,
        seeking=False,
        now=0.2,
        presentation_media_ms=current.presentation_media_ms,
    )
    assert accepted
    assert reason == "paused_backward_suppressed"
    assert paused.presentation_media_ms >= current.presentation_media_ms


def test_local_pause_state_rejects_old_property_until_acknowledged():
    clock = PlaybackClock(now=0.0)
    clock.force_position(10_000.0, paused=False, now=0.0, reason="fixture")
    optimistic = clock.set_local_state(
        10_200.0,
        paused=True,
        now=0.2,
        reason="local_pause_state",
    )

    stale, accepted, reason = clock.observe(
        10_210.0,
        source_generation=0,
        actor_sequence=1,
        observed_monotonic_ts=0.21,
        playback_rate=1.0,
        paused=False,
        seeking=False,
        now=0.21,
        presentation_media_ms=optimistic.presentation_media_ms,
    )
    assert not accepted
    assert reason == "pause_target_not_acknowledged"
    assert stale.paused

    acknowledged, accepted, reason = clock.observe(
        10_205.0,
        source_generation=0,
        actor_sequence=2,
        observed_monotonic_ts=0.22,
        playback_rate=1.0,
        paused=True,
        seeking=False,
        now=0.22,
        presentation_media_ms=stale.presentation_media_ms,
    )
    assert accepted
    assert reason == "pause_acknowledged"
    assert acknowledged.paused


def test_local_pause_stays_at_requested_anchor_across_late_heartbeats():
    clock = PlaybackClock()
    clock.force_position(1000, paused=False, now=0, reason='fixture')
    clock.set_local_state(1200, paused=True, now=.2, reason='pause')
    for sequence, (position, paused) in enumerate(((1254, True), (1300, False), (1254, True)), 1):
        snap, accepted, _ = clock.observe(position, source_generation=clock.generation,
            actor_sequence=sequence, observed_monotonic_ts=.2+sequence*.1,
            playback_rate=1, paused=paused, seeking=False, source='mpv', now=.2+sequence*.1)
        assert snap.paused and snap.presentation_media_ms == 1200
        assert accepted == paused
