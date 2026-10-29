"""P9A-R3 root-cause tests: playback loop, motion hold persistence, diversity.

These target the human-reported failures, not synthetic smoke:

* packaged-EXE 0.5 s replay loop  -> seek-ack generation desync + pinning
* applied AI art disappearing     -> graph duration != cue span / tail fade
* converging A/B/C designs        -> structural distance gate
* Antigravity REQUESTING->timeout -> two-phase generation + CLI budget
* audio replay loop               -> decoder restart hysteresis
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

from twobyteasr.playback.audio_engine import decoder_restart_required
from twobyteasr.playback.playback_clock import (
    PlaybackClock,
    backward_replay_windows,
)
from twobyteasr.caption_design.visual_design_graph import (
    MotionGraph,
    MotionKeyframe,
    MotionTrack,
    VisualDesignGraph,
    VisualDesignGraphValidationError,
    comic_burst_graph,
    compile_live_scene,
    cue_motion_phase,
    glitch_graph,
    normalize_motion_graph_to_cue,
    structural_distance,
    streamer_gaming_graph,
    validate_structural_variants,
)


# ---------------------------------------------------------------------------
# Part B: the packaged-EXE 0.5 s backward replay loop
# ---------------------------------------------------------------------------


def _observe(clock, position_ms, *, generation, now, paused=False):
    return clock.observe(
        position_ms,
        source_generation=generation,
        actor_sequence=generation * 100 + 1,
        observed_monotonic_ts=now,
        playback_rate=1.0,
        paused=paused,
        seeking=False,
        source="mpv_property_change",
        now=now,
    )


def test_seek_ack_survives_actor_epoch_desync_via_timeout():
    """Project B's fresh clock vs the monotonic actor epoch must not pin forever.

    Pre-fix behavior: every observation is rejected as seek_generation_not_ready,
    exact_seek_pending stays true, and the playhead is forced back to the seek
    target on every tick (the 0.5 s replay loop).
    """
    clock = PlaybackClock()
    start = time.monotonic()
    clock.begin_seek(2_000.0, now=start)
    assert clock.exact_seek_pending

    # Actor epoch is far ahead (seeks from the previous project).
    snapshot, accepted, reason = _observe(clock, 2_100.0, generation=57, now=start + 0.2)
    assert not accepted
    assert reason == "seek_generation_not_ready"
    assert clock.exact_seek_pending

    # After SEEK_ACK_TIMEOUT_MS the next fresh observation is adopted instead
    # of pinning the playhead to the seek target forever.
    snapshot, accepted, reason = _observe(
        clock, 2_600.0, generation=57, now=start + 3.0
    )
    assert accepted
    assert reason == "seek_ack_timeout"
    assert not clock.exact_seek_pending
    assert snapshot.presentation_media_ms == 2_600.0


def test_advance_generation_to_realigns_replacement_clock_with_actor_epoch():
    clock = PlaybackClock()
    clock.advance_generation_to(57)
    start = time.monotonic()
    clock.begin_seek(5_000.0, now=start)
    assert clock.generation == 58

    snapshot, accepted, reason = _observe(clock, 5_040.0, generation=58, now=start + 0.1)
    assert accepted
    assert reason == "seek_acknowledged"
    assert not clock.exact_seek_pending


def test_presentation_position_never_moves_backward_while_playing():
    clock = PlaybackClock()
    start = time.monotonic()
    clock.force_position(1_000.0, paused=False, now=start, reason="play")
    positions = [
        clock.sample_presentation(now=start + elapsed).presentation_media_ms
        for elapsed in (0.0, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0)
    ]
    assert not backward_replay_windows(positions, tolerance_ms=1.0)
    assert positions == sorted(positions)


def test_backward_replay_windows_detects_the_half_second_loop_shape():
    healthy = [0.0, 100.0, 200.0, 300.0, 400.0, 520.0, 640.0]
    assert backward_replay_windows(healthy) == []

    looping = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 30.0, 130.0, 230.0, 30.0]
    windows = backward_replay_windows(looping, tolerance_ms=150.0)
    assert len(windows) == 2
    assert windows[0] == (6, 500.0, 30.0)
    assert windows[1] == (9, 230.0, 30.0)


# ---------------------------------------------------------------------------
# Part C: applied AI art disappears after a few frames
# ---------------------------------------------------------------------------


def _graph_with_tracks(duration_ms: int, tracks: list[MotionTrack]) -> VisualDesignGraph:
    graph = comic_burst_graph()
    graph.motion_graph = MotionGraph(duration_ms, tracks)
    return graph


def test_short_graph_with_exit_holds_visible_until_real_cue_end():
    """The real provider shape: graph 3000ms with a tail fade, cue 4200ms.

    Pre-fix behavior: sampled opacity hit 0 at t=3000 and stayed there —
    the applied subtitle vanished for the last 1.2 s of the cue.
    """
    graph = _graph_with_tracks(3_000, [
        MotionTrack("text", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"),
            MotionKeyframe(300, 1.0, "ease-out"),
            MotionKeyframe(2_800, 1.0, "linear"),
            MotionKeyframe(3_000, 0.0, "ease-in"),
        ]),
    ])
    scene = compile_live_scene(graph, cue_duration_ms=4_200)

    samples = {moment: scene.sample(moment).value("text", "opacity")
               for moment in (0, 50, 200, 500, 1_500, 2_800, 3_100, 3_500, 4_100, 4_200)}
    # Spec #31: every hold sample stays visible.
    for moment in (500, 1_500, 2_800, 3_100, 3_500):
        assert samples[moment] >= 0.99, f"t={moment} faded: {samples[moment]}"
    # The designed exit now runs at the very end of the real cue.
    assert samples[4_100] >= 0.4
    assert samples[4_200] == 0.0


def test_entrance_only_graph_holds_until_cue_end_without_exit():
    graph = _graph_with_tracks(1_200, [
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"),
            MotionKeyframe(240, 1.0, "ease-out"),
        ]),
        MotionTrack("group", "scale", [
            MotionKeyframe(0, 0.6, "overshoot"),
            MotionKeyframe(240, 1.0, "overshoot"),
        ]),
    ])
    scene = compile_live_scene(graph, cue_duration_ms=6_000)
    for moment in (240, 1_000, 3_000, 5_900):
        assert scene.sample(moment).value("group", "opacity") >= 0.99
    # "Entrance completed" means HOLD, never hidden.
    assert scene.sample(5_999).value("group", "opacity") >= 0.99


def test_early_tail_fade_is_reanchored_to_cue_end():
    """A fade-out placed before the graph tail is still an exit: it must be
    anchored to the cue end instead of blanking the cue's second half."""
    graph = _graph_with_tracks(2_000, [
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"),
            MotionKeyframe(300, 1.0, "ease-out"),
            MotionKeyframe(1_800, 1.0, "linear"),
            MotionKeyframe(2_000, 0.0, "ease-in"),
        ]),
    ])
    scene = compile_live_scene(graph, cue_duration_ms=6_000)
    assert scene.sample(1_000).value("group", "opacity") >= 0.99
    assert scene.sample(4_500).value("group", "opacity") >= 0.99
    assert scene.sample(6_000).value("group", "opacity") == 0.0


def test_cue_motion_phase_state_machine_only_hides_outside_cue():
    assert cue_motion_phase(
        -1, entrance_end_ms=300, exit_start_ms=3_800, cue_duration_ms=4_000
    ) == "BEFORE_CUE"
    assert cue_motion_phase(
        4_000, entrance_end_ms=300, exit_start_ms=3_800, cue_duration_ms=4_000
    ) == "AFTER_CUE"
    assert cue_motion_phase(
        150, entrance_end_ms=300, exit_start_ms=3_800, cue_duration_ms=4_000
    ) == "ENTRANCE"
    assert cue_motion_phase(
        1_500, entrance_end_ms=300, exit_start_ms=3_800, cue_duration_ms=4_000
    ) == "HOLD"
    assert cue_motion_phase(
        3_900, entrance_end_ms=300, exit_start_ms=3_800, cue_duration_ms=4_000
    ) == "EXIT"


def test_normalize_does_not_mutate_the_source_graph():
    graph = _graph_with_tracks(1_000, [
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"),
            MotionKeyframe(200, 1.0, "ease-out"),
        ]),
    ])
    normalized = normalize_motion_graph_to_cue(graph, 5_000)
    assert normalized is not graph
    assert graph.motion_graph.duration_ms == 1_000
    assert normalized.motion_graph.duration_ms == 5_000


def test_overlong_graph_is_compressed_onto_a_short_cue():
    graph = _graph_with_tracks(8_000, [
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"),
            MotionKeyframe(400, 1.0, "ease-out"),
            MotionKeyframe(7_400, 1.0, "linear"),
            MotionKeyframe(8_000, 0.0, "ease-in"),
        ]),
    ])
    scene = compile_live_scene(graph, cue_duration_ms=1_500)
    assert scene.sample(600).value("group", "opacity") >= 0.99
    assert scene.sample(1_500).value("group", "opacity") == 0.0


# ---------------------------------------------------------------------------
# Part D: A/B/C structural diversity
# ---------------------------------------------------------------------------


def test_structural_distance_counts_dimensions_and_ignores_names():
    base = comic_burst_graph()
    clone = comic_burst_graph()
    clone.name = "a different name"
    assert structural_distance(base, clone) == 0

    retyped = comic_burst_graph()
    retyped.panel_layer.primitive = "BADGE"
    assert structural_distance(base, retyped) == 1


def test_validate_structural_variants_rejects_one_dimension_difference():
    def variant(motion_property: str) -> VisualDesignGraph:
        graph = comic_burst_graph()
        graph.motion_graph = MotionGraph(1_200, [
            MotionTrack("group", motion_property, [
                MotionKeyframe(0, 0.0, "ease-out"),
                MotionKeyframe(200, 1.0, "ease-out"),
            ]),
        ])
        return graph

    try:
        validate_structural_variants([variant("opacity"), variant("scale"), variant("x")])
    except VisualDesignGraphValidationError as exc:
        assert "at least two structural dimensions" in str(exc)
    else:
        raise AssertionError("one-dimension variants must be rejected")


def test_validate_structural_variants_accepts_distinct_fallback_family():
    graphs = (comic_burst_graph(), glitch_graph(), streamer_gaming_graph())
    values = validate_structural_variants(graphs)
    assert len(values) == 3


# ---------------------------------------------------------------------------
# Part E: Antigravity two-phase generation + CLI budget
# ---------------------------------------------------------------------------


def _design_project():
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject

    return SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=4_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 4_000, "高能时刻")],
    )


def test_cli_transport_generates_in_two_phases_with_300s_budget(monkeypatch):
    from types import SimpleNamespace

    from twobyteasr.caption_design import studio_ai
    from twobyteasr.caption_design.art_direction import fallback_art_directions
    from twobyteasr.caption_design.visual_design_graph import (
        comic_burst_graph,
        glitch_graph,
        streamer_gaming_graph,
    )

    directions = (
        fallback_art_directions("美漫爆裂")[0],
        fallback_art_directions("赛博故障")[0],
        fallback_art_directions("游戏直播")[1],
    )
    calls: list[dict] = []

    class Provider:
        provider_id = "fixture-agy"
        transport = "antigravity_cli"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(messages, schema, **kwargs):
            calls.append({
                "schema": schema,
                "user": messages[1]["content"],
                "timeout": kwargs.get("timeout"),
            })
            if "art_directions" in (schema.get("properties") or {}):
                return {
                    "design_intent": "three directions",
                    "visual_changes": ["a", "b", "c"],
                    "motion_reason": "layered",
                    "art_directions": [item.to_dict() for item in directions],
                }
            user = __import__("json").loads(messages[1]["content"])
            slot = "ABC".index(str(user.get("variant_slot") or "A"))
            graphs = (comic_burst_graph(), glitch_graph(), streamer_gaming_graph())
            return {"variant": graphs[slot].to_dict()}

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider())
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_kwargs: {"chinese_sans": ["Source Han Sans CN"]},
    )

    suggestion = studio_ai.request_style_design(
        _design_project(), "cue", "三套方向",
        {"models": {"ai_design_timeout_seconds": 5}},
    )
    assert suggestion.provider_succeeded
    # 1 directions request + 3 compile requests, never one giant payload.
    assert len(calls) == 4
    assert "art_directions" in calls[0]["schema"]["properties"]
    compile_slots = [
        __import__("json").loads(call["user"]).get("variant_slot")
        for call in calls[1:]
    ]
    assert compile_slots == ["A", "B", "C"]
    # CLI budget defaults to 300s even when the HTTP budget is 5s.
    assert calls[0]["timeout"] >= 295.0
    assert suggestion.provider_error_category == ""


def test_http_transport_keeps_one_shot_budget(monkeypatch):
    from types import SimpleNamespace

    from twobyteasr.caption_design import studio_ai
    from twobyteasr.caption_design.art_direction import fallback_art_directions
    from twobyteasr.caption_design.visual_design_graph import (
        comic_burst_graph,
        glitch_graph,
        streamer_gaming_graph,
    )

    calls: list[dict] = []

    class Provider:
        provider_id = "fixture-http"
        transport = "openai_compatible"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(messages, schema, **kwargs):
            calls.append({"timeout": kwargs.get("timeout")})
            return {
                "design_intent": "d",
                "visual_changes": ["a", "b", "c"],
                "motion_reason": "m",
                "art_directions": [
                    item.to_dict()
                    for item in (fallback_art_directions("美漫爆裂")[0],
                                 fallback_art_directions("赛博故障")[0],
                                 fallback_art_directions("游戏直播")[1])
                ],
                "variants": [
                    comic_burst_graph().to_dict(),
                    glitch_graph().to_dict(),
                    streamer_gaming_graph().to_dict(),
                ],
            }

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider())
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_kwargs: {"chinese_sans": ["Source Han Sans CN"]},
    )
    suggestion = studio_ai.request_style_design(
        _design_project(), "cue", "方向",
        {"models": {"ai_design_timeout_seconds": 90}},
    )
    assert suggestion.provider_succeeded
    assert len(calls) == 1
    # HTTP keeps its own budget (90s here, not the CLI 300s).
    assert calls[0]["timeout"] <= 90.0


# ---------------------------------------------------------------------------
# Audio decoder restart hysteresis
# ---------------------------------------------------------------------------


def test_single_drift_spike_does_not_restart_decoder():
    healthy = dict(process_alive=True, same_source=True, same_rate=True)
    assert decoder_restart_required(
        **healthy, drift_ms=0.0, paused=False, previous_drift_ms=0.0,
    ) is False
    # One buffered-sink mis-measurement alone must not respawn the decoder.
    assert decoder_restart_required(
        **healthy, drift_ms=-400.0, paused=False, previous_drift_ms=5.0,
    ) is False
    # Sustained desynchronization does restart.
    assert decoder_restart_required(
        **healthy, drift_ms=400.0, paused=False, previous_drift_ms=350.0,
    ) is True


def test_hard_restart_conditions_apply_immediately():
    assert decoder_restart_required(
        process_alive=False, same_source=True, same_rate=True,
        drift_ms=0.0, paused=False, previous_drift_ms=0.0,
    ) is True
    assert decoder_restart_required(
        process_alive=True, same_source=False, same_rate=True,
        drift_ms=0.0, paused=False, previous_drift_ms=0.0,
    ) is True
    assert decoder_restart_required(
        process_alive=True, same_source=True, same_rate=False,
        drift_ms=0.0, paused=False, previous_drift_ms=0.0,
    ) is True
