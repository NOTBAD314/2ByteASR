import json

import pytest

from twobyteasr.caption_style.style_recipe import (
    MotionRecipe,
    NativeRecipeUnsupportedError,
    StyleRecipe,
    StyleRecipeValidationError,
    VisualStyleRecipe,
    compile_native_recipe,
    load_recipe,
    route_recipe,
    save_recipe,
)
from twobyteasr.projects.studio_project import (
    ProjectValidationError,
    StudioMedia,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.rendering.visual_runtime import (
    CapabilitySupport,
    VisualCapability,
    VisualOwner,
    VisualOwnershipStateMachine,
    VisualRenderer,
    VISUAL_CAPABILITY_MATRIX,
    renderer_capability_gaps,
)


def _native_recipe():
    return StyleRecipe.from_dict({
        "name": "未来科技游戏字幕",
        "engine": "native",
        "typography": {"fontFamily": "Microsoft YaHei UI", "fontSize": 58, "bold": True},
        "layout": {"alignment": 2, "marginV": 54},
        "colors": {"fill": "#FFFFFF"},
        "outline": {"color": "#9B8AFB", "width": 3.5},
        "background": {"enabled": False},
        "motion": {"preset": "soft_pop", "duration": 220, "strength": "medium", "curve": "soft"},
        "wordHighlight": {"mode": "emphasis", "terms": ["高能"], "color": "#72D7FF", "scale": 110},
        "effects": {},
    })


def test_p252_recipe_has_stable_json_shape_and_compiles_to_native_plan(tmp_path):
    recipe = _native_recipe()
    assert tuple(recipe.to_dict()) == (
        "name", "engine", "typography", "layout", "colors", "outline",
        "background", "motion", "wordHighlight", "effects", "ass",
    )
    assert route_recipe(recipe).engine == "native"
    plan = compile_native_recipe(recipe, style_id="future-tech")
    assert (plan.style.id, plan.style.font_size, plan.style.outline_color) == (
        "future-tech", 58, "#9B8AFB",
    )
    assert plan.effect["entry"]["type"] == "soft_pop"
    assert plan.effect["word_highlight"]["terms"] == ["高能"]

    path = save_recipe(recipe, tmp_path / "motion" / "recipe.json")
    assert load_recipe(path).to_dict() == recipe.to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["engine"] == "native"


def test_p252_advanced_visuals_route_to_remotion_without_accepting_code():
    payload = _native_recipe().to_dict()
    payload["effects"] = {"gradientText": {"from": "#00F", "to": "#F0F"}, "glow": 12}
    route = route_recipe(payload)
    assert route.engine == "remotion"
    assert any("gradientText" in reason for reason in route.reasons)
    with pytest.raises(NativeRecipeUnsupportedError):
        compile_native_recipe(payload)

    payload = _native_recipe().to_dict()
    payload["effects"] = {"code": "export default function Subtitle() {}"}
    with pytest.raises(StyleRecipeValidationError, match="renderer code"):
        StyleRecipe.from_dict(payload)


def test_p252_explicit_remotion_recipe_never_falls_through_to_native():
    payload = _native_recipe().to_dict()
    payload["engine"] = "remotion"
    assert route_recipe(payload).engine == "remotion"
    with pytest.raises(NativeRecipeUnsupportedError):
        compile_native_recipe(payload)


def test_visual_capability_router_keeps_simple_native_and_escalates_effects():
    simple = _native_recipe().to_dict()
    simple["motion"] = {"preset": "none"}
    simple["wordHighlight"] = {"mode": "none"}
    assert route_recipe(simple).engine == "native"

    shadow = json.loads(json.dumps(simple))
    shadow["outline"]["shadow"] = {
        "enabled": True, "strength": 1.0, "opacity": 0.4,
        "offset_x": 2.0, "offset_y": 2.0, "blur": 3.0,
    }
    shadow_gaps = renderer_capability_gaps(VisualRenderer.NATIVE, shadow)
    assert [gap.capability for gap in shadow_gaps] == [VisualCapability.SHADOW]
    assert route_recipe(shadow).engine == "remotion"

    glow = json.loads(json.dumps(simple))
    glow["effects"]["glow"] = {
        "enabled": True, "color": "#FF00FFFF", "radius": 8.0,
        "opacity": 0.6, "intensity": 1.0,
    }
    assert route_recipe(glow).engine == "remotion"
    assert renderer_capability_gaps(VisualRenderer.LIVE, glow) == ()
    assert VISUAL_CAPABILITY_MATRIX[VisualRenderer.LIVE][VisualCapability.GLOW] == CapabilitySupport.FULL

    visual_simple = VisualStyleRecipe(name="Simple", strokes=[{
        "color": "#FF000000", "width": 3,
    }])
    assert route_recipe(visual_simple).engine == "native"

    visual_glow = VisualStyleRecipe(
        name="Glow",
        strokes=[{"color": "#FF000000", "width": 3}],
        glow={
            "enabled": True, "color": "#FF00FFFF", "radius": 8.0,
            "opacity": 0.6, "intensity": 1.0,
        },
    )
    assert route_recipe(visual_glow).engine == "remotion"
    assert [
        gap.capability
        for gap in renderer_capability_gaps(VisualRenderer.NATIVE, visual_glow)
    ] == [VisualCapability.GLOW]


def test_visual_owner_state_machine_never_reports_multiple_foregrounds():
    machine = VisualOwnershipStateMachine()
    previous, live = machine.commit(
        VisualOwner.ADVANCED_LIVE,
        cue_id="cue", snapshot_hash="live", request_key="request",
    )
    assert previous.foreground_owner_count == 0
    assert live.foreground_owner_count == 1

    previous, fidelity = machine.commit(
        VisualOwner.ADVANCED_FIDELITY,
        cue_id="cue", snapshot_hash="live", request_key="request",
    )
    assert previous.owner == VisualOwner.ADVANCED_LIVE
    assert fidelity.owner == VisualOwner.ADVANCED_FIDELITY
    assert fidelity.foreground_owner_count == 1

    _previous, none = machine.commit(VisualOwner.NONE)
    assert none.foreground_owner_count == 0


def test_p252_project_round_trip_preserves_validated_recipes(tmp_path):
    project = SubtitleProject(media=StudioMedia(path="D:/game.mp4"))
    project.style_recipes["future-tech"] = _native_recipe().to_dict()
    path = save_project(project, tmp_path / "recipe-project.2byteproj")
    loaded = load_project(path)
    assert loaded.style_recipes["future-tech"]["motion"]["preset"] == "soft_pop"

    before = path.read_bytes()
    loaded.style_recipes["unsafe"] = {"name": "unsafe", "engine": "native", "effects": {"raw_ass": "{\\p1}"}}
    with pytest.raises(ProjectValidationError, match="invalid style recipe unsafe"):
        save_project(loaded, path)
    assert path.read_bytes() == before


def test_p2513_visual_recipe_validates_and_converts_without_code():
    visual = VisualStyleRecipe(
        name="Cyberpunk HUD",
        engine_requirement="advanced",
        typography={"font_family": "Microsoft YaHei UI", "font_size": 56, "weight": 700},
        fill={"type": "linear-gradient", "angle": 18, "stops": [
            {"position": 0.0, "color": "#FFFFE45E"},
            {"position": 1.0, "color": "#FF20D9FF"},
        ]},
        strokes=[
            {"color": "#FF000000", "width": 4},
            {"color": "#FF20D9FF", "width": 1, "opacity": 0.55},
        ],
        glow={"color": "#FF20D9FF", "radius": 5, "strength": 0.4, "opacity": 0.35},
        decorations=[{"type": "corner_brackets", "color": "#FF20D9FF", "opacity": 0.65, "size": 14}],
        motion=MotionRecipe(entrance={"keyframes": [{"t": 0, "opacity": 0}, {"t": 180, "opacity": 1}]}, hold={}, exit={}),
    )
    visual.validate()
    payload = visual.to_dict()
    assert payload["engine_requirement"] == "advanced"
    assert len(payload["strokes"]) == 2
    assert payload["fill"]["stops"][1]["color"] == "#FF20D9FF"
    converted = visual.to_style_recipe()
    assert route_recipe(converted).engine == "remotion"
    with pytest.raises(StyleRecipeValidationError):
        VisualStyleRecipe(name="bad", decorations=[{"type": "x", "code": "alert(1)"}]).validate()
