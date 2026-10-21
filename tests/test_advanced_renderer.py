import pytest

from twobyteasr.rendering.advanced_renderer import (
    TRUSTED_COMPONENTS,
    compile_composition_data,
    project_requires_advanced,
    recipe_payload_for_cue,
)
from twobyteasr.caption_style.style_recipe import recipe_payload_for_style
from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.caption_design.visual_design_graph import (
    comic_burst_graph,
    style_recipe_from_graph,
)


def _cyberpunk_recipe():
    return {
        "name": "Cyberpunk HUD",
        "engine": "remotion",
        "typography": {"fontFamily": "Microsoft YaHei UI", "fontSize": 64, "bold": True},
        "layout": {"alignment": 2, "marginV": 72},
        "colors": {"fill": {"type": "linear", "angle": 18, "stops": [
            {"color": "#20D6E8", "pos": 0.0}, {"color": "#FF4DB8", "pos": 1.0},
        ]}},
        "outline": {"layers": [
            {"color": "#090D12", "width": 6}, {"color": "#20D6E8", "width": 2},
        ], "shadow": {"color": "#AA120A08", "offsetX": 5, "offsetY": 3, "blur": 2}},
        "background": {"enabled": True, "color": "#D82A1A14", "marks": ["left_bracket", "right_bracket", "scanline"]},
        "motion": {"entry": {"type": "glitch_entrance", "duration": 260}},
        "wordHighlight": {},
        "effects": {"glow": {"color": "#20D6E8", "blur": 14, "opacity": 0.5}},
    }


def test_advanced_route_compiles_only_safe_composition_data():
    project = SubtitleProject(
        media=StudioMedia(path="D:/source.mp4", duration_ms=10_000, width=1920, height=1080),
        cues=[StudioCue(id="cue-1", start_ms=0, end_ms=10_000, text="ADVANCED RENDER", style_id="cyber", speaker_id="speaker-one")],
        speakers=[StudioSpeaker(id='speaker-one', name='说话人名称', style_id='cyber')],
    )
    project.style_recipes["cyber"] = _cyberpunk_recipe()
    assert project_requires_advanced(project)
    payload = compile_composition_data(project, width=1920, height=1080, fps=30, start_seconds=0, duration_seconds=10)
    assert payload["durationInFrames"] == 300
    assert payload['cues'][0]['speaker'] == '说话人名称'
    recipe = payload["recipes"]["cyber"]
    assert set(recipe["components"]) == TRUSTED_COMPONENTS
    assert len(recipe["strokes"]) == 2
    assert recipe["decorations"] == ["left_bracket", "right_bracket", "scanline"]
    assert recipe["background"]["enabled"] is True
    assert recipe["background"]["color"] == "#2A1A14D8"
    assert recipe["shadow"] == {
        "enabled": True,
        "color": "#120A08FF",
        "opacity": pytest.approx(0xAA / 255),
        "offsetX": 5.0,
        "offsetY": 3.0,
        "blur": 2.0,
        "spread": 0.0,
    }
    assert "code" not in str(payload).lower()


def test_first_advanced_visual_batch_routes_to_remotion():
    expected = {
        "Cyberpunk HUD": "赛博朋克 Cyberpunk HUD 多层描边 glow glitch",
        "Gaming Impact": "Gaming Impact punch 游戏冲击",
        "Soft Neon": "Soft Neon 柔光霓虹 tracking",
    }
    for name, prompt in expected.items():
        recipe = style_recipe_for_prompt(prompt)
        assert recipe.name == name
        assert recipe.engine == "remotion"


def test_glyph_motion_uses_bundled_render_browser_on_a_cold_export(monkeypatch,tmp_path):
    from twobyteasr.acceptance.letter_motion_audit import make_project
    from twobyteasr.rendering import platform_browser
    from twobyteasr.rendering.advanced_renderer import _composition_browser
    bundled=tmp_path/'headless.exe';bundled.touch()
    system=tmp_path/'chrome.exe';system.touch()
    monkeypatch.setattr(platform_browser,'bundled_browser',lambda root:bundled)
    monkeypatch.setattr(platform_browser,'system_browser',lambda:system)
    project=make_project('none.mp4')
    project.style_recipes['default']=_cyberpunk_recipe()
    props=compile_composition_data(project,width=960,height=540,fps=30,start_seconds=0,duration_seconds=36)
    assert _composition_browser(tmp_path,props)==bundled
    for cue in project.cues:cue.effect_id='none'
    static=compile_composition_data(project,width=960,height=540,fps=30,start_seconds=0,duration_seconds=36)
    assert _composition_browser(tmp_path,static)==bundled
    bundled.unlink()
    assert _composition_browser(tmp_path,props)==system


def test_derived_fill_style_id_still_routes_advanced():
    project = SubtitleProject(
        media=StudioMedia(path="D:/source.mp4", duration_ms=10_000, width=1920, height=1080),
        cues=[
            StudioCue(id="native", start_ms=0, end_ms=2000, text="NATIVE", style_id="default"),
            StudioCue(id="adv", start_ms=2000, end_ms=8000, text="ADV", style_id="cyber-fill-abc123"),
        ],
    )
    project.style_recipes["cyber"] = _cyberpunk_recipe()
    cue = project.cues[1]
    assert recipe_payload_for_style(project.style_recipes, cue.style_id) is not None
    assert recipe_payload_for_cue(project, cue) is not None
    assert project_requires_advanced(project)
    payload = compile_composition_data(project, width=1920, height=1080, fps=30, start_seconds=0, duration_seconds=10)
    assert [item["id"] for item in payload["cues"]] == ["adv"]


def test_generated_no_motion_id_uses_shared_static_pixels():
    from twobyteasr.exports.static_caption_export import static_graph_project
    p=SubtitleProject(media=StudioMedia('sample.mp4',duration_ms=2000),
        cues=[StudioCue('a',0,2000,'STATIC',style_id='cyber-scope-example',effect_id='generated-motion')])
    recipe=_cyberpunk_recipe();recipe['motion']={};recipe['background']={'enabled':False};recipe['effects']={}
    p.style_recipes['cyber']=recipe
    p.effects['generated-motion']={'entry':{'type':'none'},'exit':{'type':'none'}}
    assert static_graph_project(p)
    p.effects['generated-motion']['entry']={'type':'fade','duration':200}
    assert not static_graph_project(p)


def test_visual_design_graph_survives_into_remotion_composition_props():
    graph = comic_burst_graph()
    recipe = style_recipe_from_graph(graph)
    project = SubtitleProject(
        media=StudioMedia(
            path="D:/source.mp4", duration_ms=2_400, width=1920, height=1080,
        ),
        cues=[
            StudioCue(
                id="graph-cue", start_ms=0, end_ms=2_400,
                text="COMIC GRAPH", style_id="comic",
            ),
        ],
        style_recipes={"comic": recipe.to_dict()},
    )

    # Pin an actual bundled face; a headless QFontDatabase fallback is not
    # the authored input this graph propagation test intends to exercise.
    project.styles[0].font_family = 'Source Han Sans SC Heavy'
    project.styles[0].font_weight = 900

    payload = compile_composition_data(
        project, width=1920, height=1080, fps=30,
        start_seconds=0, duration_seconds=2.4,
    )

    compiled = payload["recipes"]["comic"]
    compiled_graph = compiled["visualGraph"]
    cue_graph = payload["cues"][0]["visual"]["visualGraph"]
    assert cue_graph == compiled_graph
    assert compiled_graph["panelLayer"] == graph.to_dict()["panelLayer"]
    assert compiled_graph["motionGraph"] == graph.to_dict()["motionGraph"]
    assert compiled_graph["textLayer"]["font"]["family"] == "Source Han Sans SC Heavy"
    assert compiled_graph["textLayer"]["font"]["weight"] == 900
    assert compiled_graph["textLayer"]["font"]["size"] == 56
    assert compiled_graph["panelLayer"]["primitive"] == "COMIC_BURST"
    assert {item["primitive"] for item in compiled_graph["decorationLayers"]} >= {
        "IMPACT_RAYS", "HALFTONE",
    }
    assert compiled_graph["motionGraph"]["tracks"]
