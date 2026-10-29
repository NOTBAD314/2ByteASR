import json
from types import SimpleNamespace

from twobyteasr.rendering.advanced_renderer import compile_composition_data
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_recipe import route_recipe
from twobyteasr.caption_design.studio_ai import (
    _recipe_signature,
    _semantic_richness,
    style_recipe_for_prompt,
    visual_design_variants,
)
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
    analysis_transcript_cues,
    create_studio_outputs,
    load_project,
    save_project,
)


def test_analysis_transcript_is_non_destructive_and_clip_readable(tmp_path, monkeypatch):
    media = tmp_path / "source.wav"
    media.write_bytes(b"media")
    target = tmp_path / "project.2byteproj"
    official = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=5000),
        cues=[StudioCue("official", 0, 1000, "正式字幕")],
    )
    save_project(official, target)
    txt = tmp_path / "analysis.txt"
    srt = tmp_path / "analysis-output.srt"
    txt.write_text("分析字幕", encoding="utf-8")
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n分析字幕\n", encoding="utf-8")
    monkeypatch.setattr("twobyteasr.projects.studio_project.register_recent_project", lambda *_a, **_k: None)

    create_studio_outputs(
        media,
        [SimpleNamespace(cue_id="analysis", start=1.0, end=2.0, text="分析字幕", speaker="S00")],
        txt_path=str(txt),
        srt_path=str(srt),
        generation_metadata={"recognition_purpose": "analysis", "analysis_transcript": True},
        target_project_path=target,
    )

    loaded = load_project(target)
    assert [(cue.id, cue.text) for cue in loaded.cues] == [("official", "正式字幕")]
    assert [(cue.id, cue.text) for cue in analysis_transcript_cues(loaded)] == [("analysis", "分析字幕")]
    assert (tmp_path / "subtitles" / "analysis.srt").is_file()
    assert not (tmp_path / "subtitles" / "master.srt").exists()


def test_1930s_recipe_has_real_card_texture_motion_and_semantic_evidence():
    recipe = style_recipe_for_prompt("1930s 橡皮管胶片动画风")
    score, hits = _semantic_richness(recipe, "1930s 橡皮管胶片动画风")
    assert route_recipe(recipe).engine == "remotion"
    assert recipe.background["enabled"] is True
    assert recipe.background["type"] == "film_card"
    assert recipe.background["texture"]["type"] == "film_grain"
    assert recipe.motion["entrance"]["type"] == "squash_stretch"
    assert score >= 3, hits


def test_local_abc_variants_differ_across_at_least_three_design_dimensions(monkeypatch):
    monkeypatch.setattr(
        "twobyteasr.caption_design.studio_ai.available_font_shortlist",
        lambda *_a, **_k: {
            "serif": ["SimSun"], "handwriting": ["KaiTi"],
            "chinese_sans": ["Microsoft YaHei UI"], "chinese_display": ["SimHei"],
            "pixel_game": ["SimHei"], "cartoon": ["Microsoft YaHei UI"],
        },
    )
    variants = visual_design_variants("1930s 橡皮管胶片动画风")
    signatures = [_recipe_signature(item.to_style_recipe()) for item in variants]
    varying_dimensions = sum(1 for values in zip(*signatures) if len(set(values)) > 1)
    assert len(variants) == 3
    assert varying_dimensions >= 3
    assert any(item.background.get("enabled") and item.background.get("texture") for item in variants)


def test_formal_background_schema_reaches_renderer_payload():
    recipe = style_recipe_for_prompt("1930s 橡皮管胶片动画风")
    project = SubtitleProject(
        media=StudioMedia(path="D:/source.mp4", duration_ms=3000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 3000, "精彩操作 Aa 123", style_id="retro")],
    )
    project.style_recipes["retro"] = recipe.to_dict()
    payload = compile_composition_data(
        project, width=1920, height=1080, fps=30, start_seconds=0, duration_seconds=3
    )
    background = payload["recipes"]["retro"]["background"]
    assert background["type"] == "film_card"
    assert background["texture"]["type"] == "film_grain"
    assert background["border"]["width"] == 2.0
    assert background["transform"]["rotation"] == -0.7


def test_style_preset_store_batch_manage_export_import(tmp_path):
    store = StylePresetStore(tmp_path / "a")
    ai = SubtitleStyle("ai-test", "AI Test")
    custom = SubtitleStyle("custom-test", "Custom Test")
    store.upsert(ai, style_recipe_for_prompt("1930s 橡皮管").to_dict(), source="ai")
    store.upsert(custom, source="custom")
    store.set_favorite("ai-test", True)
    store.rename("custom-test", "Renamed")
    exported = tmp_path / "presets.json"
    assert store.export_file(exported) == 2
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["kind"] == "2byteasr-style-presets"

    imported = StylePresetStore(tmp_path / "b")
    assert imported.import_file(exported) == 2
    assert len(imported.load_user()) == 2
    assert store.delete_all_ai(keep_favorites=False) == 1
    assert "ai-test" not in store.load_user()
