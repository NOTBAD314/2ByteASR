import json
from pathlib import Path
from types import SimpleNamespace

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


def test_cli_transport_gets_compact_context_and_trace_records_prompt_size(monkeypatch):
    """CLI transports must not carry the full manifests/schema that timed out."""
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
    captured = {}

    class Provider:
        provider_id = "fixture-cli"
        transport = "antigravity_cli"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(messages, schema, **_kwargs):
            captured["schema_passed"] = schema is not None
            captured["system_size"] = len(messages[0]["content"].encode("utf-8"))
            if "art_directions" in (schema.get("properties") or {}):
                captured["user"] = json.loads(messages[1]["content"])
                return {
                    "design_intent": "Readable, controlled, expressive",
                    "visual_changes": ["hierarchy", "composition", "temporal structure"],
                    "motion_reason": "Each direction uses a distinct layered rhythm",
                    "art_directions": [item.to_dict() for item in directions],
                }
            graphs = [
                comic_burst_graph(),
                glitch_graph(),
                streamer_gaming_graph(),
            ]
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
        project, "cue", "三套字幕方向",
        {"models": {"ai_design_timeout_seconds": 5}},
    )
    assert suggestion.provider_succeeded

    user = captured["user"]
    assert captured["schema_passed"] is True  # CLI adapter drops it downstream
    assert "visual_graph_schema" not in user
    assert "curated_art_direction_families" not in user
    families = {item["family_id"] for item in user["curated_family_vocabulary"]}
    assert {"AMERICAN_COMIC_BURST", "CRT_GLITCH", "CLEAN_EDITORIAL"} <= families
    assert user["art_direction_spec"]["required_keys"]
    assert "AMERICAN_COMIC_BURST" in user["art_direction_spec"]["primary_family"]
    assert "visual_capability_manifest" in user
    assert user["available_fonts"] == {"chinese_sans": ["Source Han Sans CN"]}

    telemetry = suggestion.raw_response["_studio_telemetry"]
    trace = json.loads(Path(telemetry["trace_path"]).read_text(encoding="utf-8"))
    sizes = trace["provider"]["prompt_size_bytes"]
    assert sizes["system"] == captured["system_size"]
    assert 0 < sizes["user"] < 12_000


def test_http_transport_keeps_the_full_request_context(monkeypatch):
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
    captured = {}

    class Provider:
        provider_id = "fixture-http"
        transport = "openai_compatible"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(messages, _schema, **_kwargs):
            captured["user"] = json.loads(messages[1]["content"])
            return {
                "design_intent": "Readable, controlled, expressive",
                "visual_changes": ["hierarchy", "composition", "temporal structure"],
                "motion_reason": "Each direction uses a distinct layered rhythm",
                "art_directions": [item.to_dict() for item in directions],
                "variants": [
                    comic_burst_graph().to_dict(),
                    glitch_graph().to_dict(),
                    streamer_gaming_graph().to_dict(),
                ],
            }

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
        project, "cue", "三套字幕方向",
        {"models": {"ai_design_timeout_seconds": 5}},
    )
    assert suggestion.provider_succeeded
    user = captured["user"]
    assert "visual_graph_schema" in user
    assert "curated_art_direction_families" in user
    assert "curated_family_vocabulary" not in user
