import json

import pytest

from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.caption_style.effect_dsl import (
    EffectValidationError,
    builtin_effects,
    compile_effect_override,
    compile_effect_text,
    compile_position_motion_segments,
    validate_effect,
)
from twobyteasr.caption_style.style_presets import BUILTIN_PRESETS, StylePresetStore
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle


def test_effect_dsl_validates_bounds_and_rejects_raw_fields():
    assert validate_effect({"type": "pop", "duration": 180})["entry"]["scale_from"] == 85
    with pytest.raises(EffectValidationError, match="between"):
        validate_effect({"type": "fade", "duration": 9000})
    with pytest.raises(EffectValidationError, match="unknown"):
        validate_effect({"type": "pop", "raw_ass": "{\\p1}"})


def test_effect_compiler_is_deterministic_and_clamps_to_cue_duration():
    override = compile_effect_override(
        {"entry": {"type": "pop", "duration": 500, "scale_from": 80}, "exit": {"type": "fade", "duration": 200}},
        cue_duration_ms=300,
        play_res_x=1920,
        play_res_y=1080,
    )
    assert "\\t(0,300," in override
    assert "\\fad(0,200)" in override


def test_ass_compiler_applies_effect_without_polluting_cue_text():
    project = SubtitleProject(
        media=StudioMedia(path="D:/game.mp4"),
        cues=[StudioCue("a", 0, 1000, "原文", effect_id="pop", original_text="原文")],
    )
    rendered = compile_ass(project)
    # Geometry/font-unit overrides now share this ASS override block.
    assert "\\fscx85\\fscy85\\t(0,180,\\fscx100\\fscy100)}原文" in rendered
    assert rendered.count('\\t(0,180,')==1
    assert project.cues[0].text == "原文"


def test_style_store_keeps_builtins_read_only_and_user_presets_isolated(tmp_path):
    store = StylePresetStore(tmp_path)
    user = SubtitleStyle("my-game", "我的游戏字幕", font_size=60)
    store.upsert(user)
    assert store.all()["my-game"].font_size == 60
    assert "default" in store.all()
    with pytest.raises(ValueError, match="read-only"):
        store.upsert(BUILTIN_PRESETS["default"])
    # Built-in presets are never deletable; deleting hides them instead and
    # the user preset file stays isolated from builtin definitions.
    store.delete("default")
    assert "default" not in store.all()
    store.restore_builtins(["default"])
    assert "default" in store.all()
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["presets"][0]["id"] == "my-game"


def test_p250_native_motion_catalog_is_complete_and_restrained():
    effects = builtin_effects()
    assert {
        "soft_fade", "soft_pop", "punch", "float_up", "drop_in",
        "slide_soft", "blur_reveal", "emphasis", "karaoke_highlight",
        "bounce_lite",
    } <= set(effects)
    assert effects["soft_pop"]["entry"]["scale_from"] == 95
    assert effects["soft_pop"]["entry"]["overshoot"] == 103
    assert effects["punch"]["entry"]["scale_from"] == 80
    assert effects["punch"]["entry"]["overshoot"] == 108
    assert effects["soft_fade"]["entry"]["easing"] != "linear"


def test_p250_soft_pop_and_bounce_compile_multistage_accelerated_curves():
    pop = compile_effect_override(
        builtin_effects()["soft_pop"], cue_duration_ms=1000,
        play_res_x=1920, play_res_y=1080,
    )
    bounce = compile_effect_override(
        builtin_effects()["bounce_lite"], cue_duration_ms=1000,
        play_res_x=1920, play_res_y=1080,
    )
    assert pop.startswith(r"\fscx95\fscy95")
    assert pop.count(r"\t(") >= 3  # two-stage entry plus restrained exit
    assert r"\fscx103\fscy103" in pop
    assert bounce.count(r"\t(") >= 4
    assert r",0.68,\fscx100\fscy100)" in bounce


def test_p250_slide_soft_uses_piecewise_eased_ass_events():
    segments = compile_position_motion_segments(
        builtin_effects()["slide_soft"],
        cue_duration_ms=1200,
        target_position=(960, 980),
    )
    assert len(segments) == 4
    assert segments[0][0] == 0
    assert segments[-1][1] == 240
    assert all(r"\move(" in override and r"\alpha" in override for _, _, override in segments)
    # Eased sampling produces unequal segment distances, not a full-duration
    # linear move disguised by a preset label.
    starts = [int(item[2].split("(", 1)[1].split(",", 1)[0]) for item in segments]
    assert len({starts[index + 1] - starts[index] for index in range(3)}) > 1


def test_p250_blur_emphasis_and_karaoke_are_audited_text_effects():
    blur = compile_effect_override(
        builtin_effects()["blur_reveal"], cue_duration_ms=900,
        play_res_x=1920, play_res_y=1080,
    )
    assert r"\blur6\alpha&HFF&" in blur
    assert r"\blur0\alpha&H00&" in blur

    emphasized = compile_effect_text(
        "普通 高能 文字",
        {"word_highlight": {"type": "emphasis", "terms": ["高能"], "color": "#FFD166"}},
        cue_duration_ms=1000,
    )
    karaoke = compile_effect_text(
        "逐词 强调",
        builtin_effects()["karaoke_highlight"],
        cue_duration_ms=1000,
    )
    assert r"\1c&H66D1FF&" in emphasized and r"\fscx112" in emphasized
    assert karaoke.count(r"\kf") == 2
    character = compile_effect_text(
        r"逐字\N强调",
        {"type": "karaoke_highlight", "granularity": "character"},
        cue_duration_ms=1000,
    )
    assert r"字\N{\kf" in character
