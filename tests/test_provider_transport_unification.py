"""One provider transport truth: Settings Test and AI Design must resolve
the same transport from the same active-service source of truth."""

from __future__ import annotations

import copy

from twobyteasr.providers.ai_providers import AITransport, transport_for_stage
from twobyteasr.providers.llm_config import (
    activate_ai_service,
    endpoint_from_settings,
    get_active_service,
)


def test_active_service_spec_wins_over_stale_flat_transport():
    """The stored state that produced 'Test READY but Generate transport failed'.

    The endpoint editor tested Antigravity (spec transport), while the saved
    settings still carried a stale flat ``polish_transport``. Generate must
    follow the active service, not the stale flat key.
    """
    settings = {
        "models": {
            "ai_service": "antigravity",
            "polish_transport": "openai_compatible",  # stale editor leftover
            "polish_provider": "google_antigravity",
        }
    }
    assert transport_for_stage(settings, "polish") is AITransport.ANTIGRAVITY_CLI
    assert endpoint_from_settings(copy.deepcopy(settings), "polish")["provider"] == "google_antigravity"


def test_legacy_unactivated_settings_migrate_consistently():
    settings = {
        "models": {
            "ai_service": "",
            "polish_provider": "gemini",
            "polish_transport": "openai_compatible",
        }
    }
    assert get_active_service(settings) == "gemini"
    assert transport_for_stage(settings, "polish") is AITransport.OPENAI_COMPATIBLE


def test_custom_service_keeps_flat_transport_authority():
    settings = {"models": {"ai_service":"custom","polish_transport": "grok_cli"}}
    assert get_active_service(settings) == "custom"
    assert transport_for_stage(settings, "polish") is AITransport.GROK_CLI


def test_saved_overlay_resolution_matches_post_save_generate():
    """The endpoint editor tests an overlay of live settings + activation.

    After activating antigravity on a copy of the saved settings, Test and
    (post-save) Generate resolve the identical provider/transport pair.
    """
    base = {
        "models": {
            "ai_service": "gemini",
            "polish_provider": "gemini",
            "polish_transport": "openai_compatible",
            "polish_model": "gemini-3.7-flash-high",
        },
        "switches": {"unified_glm_processing": True},
    }
    overlay = copy.deepcopy(base)
    activate_ai_service(overlay, "antigravity", stage="polish")
    overlay["models"]["polish_model"] = "gemini-3.7-flash-high"

    assert transport_for_stage(overlay, "polish") is AITransport.ANTIGRAVITY_CLI
    endpoint = endpoint_from_settings(copy.deepcopy(overlay), "polish")
    assert endpoint["provider"] == "google_antigravity"


def test_cli_transport_never_attaches_vision_frame_to_argv(monkeypatch):
    """CLI prompts travel through ``-p`` argv; a base64 frame would exceed the
    Windows command-line budget and die as a generic transport error."""
    import json

    from twobyteasr.caption_design import studio_ai
    from twobyteasr.caption_design.art_direction import fallback_art_directions
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
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
    supplier_calls: list[int] = []

    class Provider:
        provider_id = "fixture-agy"
        transport = "antigravity_cli"

        @staticmethod
        def capabilities():
            # Vision-capable manifest must NOT convince the CLI path to embed
            # a frame into argv.
            from types import SimpleNamespace

            return SimpleNamespace(vision=True, structured_output=True)

        @staticmethod
        def structured_complete(messages, schema, **_kwargs):
            if "art_directions" in (schema.get("properties") or {}):
                return {
                    "design_intent": "Readable",
                    "visual_changes": ["hierarchy"],
                    "motion_reason": "layered rhythm",
                    "art_directions": [item.to_dict() for item in directions],
                }
            graphs = [comic_burst_graph(), glitch_graph(), streamer_gaming_graph()]
            user = json.loads(messages[1]["content"])
            slot = "ABC".index(str(user.get("variant_slot") or "A"))
            return {"variant": graphs[slot % len(graphs)].to_dict()}

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider())
    monkeypatch.setattr(
        studio_ai,
        "available_font_shortlist",
        lambda **_kwargs: {"chinese_sans": ["Source Han Sans CN"]},
    )
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=3_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 3_000, "高能时刻")],
    )
    suggestion = studio_ai.request_style_design(
        project,
        "cue",
        "三套字幕方向",
        {"models": {"ai_design_timeout_seconds": 5}},
        vision_frame_supplier=lambda: supplier_calls.append(1),
    )
    assert suggestion.provider_succeeded
    assert supplier_calls == [], "CLI transports must stay text-only (argv budget)"
