import json
import os
import hashlib
import threading
from dataclasses import replace
from time import perf_counter
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.rendering.advanced_live_renderer import (
    composite_live_scene_layers,
    render_live_layers,
    render_live_scene_frame,
    render_live_snapshot,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.caption_style.style_recipe import StyleRecipe, StyleRecipeValidationError
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.caption_design.visual_design_graph import (
    CompiledLiveScene,
    VisualDesignGraph,
    VisualDesignGraphValidationError,
    clean_subtitle_graph,
    comic_burst_graph,
    glitch_graph,
    graph_from_style_recipe,
    streamer_gaming_graph,
    structural_signature,
    style_recipe_from_graph,
    validate_structural_variants,
)
from twobyteasr.rendering.visual_runtime import (
    CapabilitySupport,
    VisualCapability,
    VisualRenderer,
    VISUAL_CAPABILITY_MATRIX,
    renderer_capability_gaps,
)
from twobyteasr.caption_design.studio_ai import request_style_design
from twobyteasr.caption_design.art_direction import fallback_art_directions
from twobyteasr.rendering import studio_live_canvas
from twobyteasr.studio import studio_ui


_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_visual_design_graph_v1_roundtrip_rejects_renderer_code():
    graph = comic_burst_graph()
    payload = graph.to_dict()
    assert payload["schema"] == "2byte.visual-design-graph"
    assert payload["version"] == 1
    assert VisualDesignGraph.from_dict(payload).stable_hash() == graph.stable_hash()

    unsafe = json.loads(json.dumps(payload))
    unsafe["effectLayers"][0]["params"]["javascript"] = "alert(1)"
    with pytest.raises(VisualDesignGraphValidationError, match="renderer code"):
        VisualDesignGraph.from_dict(unsafe)


def test_legacy_recipe_compiles_to_graph_and_graph_survives_style_roundtrip():
    legacy = StyleRecipe.from_dict({
        "name": "Legacy",
        "engine": "native",
        "typography": {"fontFamily": "Arial", "fontSize": 52, "bold": True},
        "layout": {"alignment": 2, "marginV": 64},
        "colors": {"fill": "#FFFFFFFF", "outline": "#FF000000"},
        "outline": {"color": "#FF000000", "width": 4, "shadow": 2},
        "background": {"enabled": False},
        "motion": {"entrance": {"type": "scale", "duration_ms": 180}},
        "wordHighlight": {},
        "effects": {},
    })
    graph = graph_from_style_recipe(legacy)
    assert graph.text_layer.font["family"] == "Arial"
    assert any(track.target == "group" for track in graph.motion_graph.tracks)

    compiled = style_recipe_from_graph(comic_burst_graph())
    payload = compiled.to_dict()
    assert payload["visualGraph"]["panelLayer"]["primitive"] == "COMIC_BURST"
    restored = StyleRecipe.from_dict(payload)
    assert graph_from_style_recipe(restored).stable_hash() == comic_burst_graph().stable_hash()


def test_golden_graphs_are_deterministic_and_structurally_distinct():
    factories = (
        comic_burst_graph, glitch_graph, clean_subtitle_graph, streamer_gaming_graph,
    )
    first = [factory() for factory in factories]
    second = [factory() for factory in factories]
    assert [item.stable_hash() for item in first] == [item.stable_hash() for item in second]
    assert len({structural_signature(item) for item in first}) == 4
    assert validate_structural_variants(first[:3]) == tuple(first[:3])

    duplicate = [comic_burst_graph(), comic_burst_graph(), glitch_graph()]
    with pytest.raises(VisualDesignGraphValidationError, match="must differ"):
        validate_structural_variants(duplicate)


def test_comic_burst_and_glitch_have_required_layered_structure():
    comic = comic_burst_graph()
    assert comic.panel_layer.primitive == "COMIC_BURST"
    assert {item.primitive for item in comic.decoration_layers} >= {"IMPACT_RAYS", "HALFTONE"}
    assert {item.primitive for item in comic.effect_layers} == {"IMPACT"}
    assert {track.target for track in comic.motion_graph.tracks} >= {"panel", "text", "rays"}

    glitch = glitch_graph()
    assert {item.primitive for item in glitch.effect_layers} == {"GLITCH"}
    assert {track.property for track in glitch.motion_graph.tracks} >= {
        "rgb_offset", "slice_offset",
    }


def test_compiled_live_scene_samples_only_parameters_and_meets_startup_gates():
    timings = []
    for _index in range(40):
        started = perf_counter()
        scene = CompiledLiveScene.compile(comic_burst_graph())
        first = scene.sample(0)
        scene.sample(160)
        timings.append((perf_counter() - started) * 1000.0)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    assert p95 < 100.0
    assert first.value("group", "opacity") == 0
    active = scene.sample(160)
    assert active.value("panel", "burst_scale") > 0
    assert "impact" in active.values


def test_capability_matrix_claims_pixel_verified_fidelity_graph_features():
    recipe = style_recipe_from_graph(comic_burst_graph())
    live_gaps = renderer_capability_gaps(VisualRenderer.LIVE, recipe)
    fidelity_gaps = renderer_capability_gaps(VisualRenderer.FIDELITY, recipe)
    assert live_gaps == ()
    assert fidelity_gaps == ()
    assert renderer_capability_gaps(VisualRenderer.EXPORT, recipe) == ()
    assert VISUAL_CAPABILITY_MATRIX[VisualRenderer.FIDELITY][VisualCapability.COMIC_BURST] == CapabilitySupport.FULL
    assert VISUAL_CAPABILITY_MATRIX[VisualRenderer.FIDELITY][VisualCapability.MOTION_GRAPH] == CapabilitySupport.FULL
    assert VISUAL_CAPABILITY_MATRIX[VisualRenderer.LIVE][VisualCapability.GLITCH] == CapabilitySupport.FULL
    assert VISUAL_CAPABILITY_MATRIX[VisualRenderer.EXPORT][VisualCapability.GLITCH] == CapabilitySupport.FULL


def test_style_recipe_visual_graph_validation_still_rejects_code():
    payload = style_recipe_from_graph(glitch_graph()).to_dict()
    payload["visualGraph"]["effectLayers"][0]["params"]["code"] = "renderer()"
    with pytest.raises(StyleRecipeValidationError):
        StyleRecipe.from_dict(payload)


def _snapshot_for_graph(graph):
    _app()
    recipe = style_recipe_from_graph(graph)
    text = graph.text_layer
    first = text.strokes[0]
    style = SubtitleStyle(
        "graph", graph.name,
        font_family=str(text.font.get("family") or "Arial"),
        font_size=float(text.font.get("size", 56)),
        primary_color=str(text.fill.get("color") or "#FFFFFF"),
        outline_color=str(first.get("color") or "#000000"),
        outline_width=float(first.get("width", 4)),
        bold=True,
        alignment=5,
        position_x=960,
        position_y=540,
    )
    project = SubtitleProject(
        media=StudioMedia(path="D:/graph.mp4", duration_ms=2_400, width=1920, height=1080),
        styles=[style],
        cues=[StudioCue("graph-cue", 0, 2_400, "空中打拳", style_id="graph")],
        style_recipes={"graph": recipe.to_dict()},
    )
    return build_visual_cue_snapshot(project, "graph-cue", width=640, height=360, fps=30)


def _image_digest(image) -> str:
    return hashlib.sha256(bytes(image.constBits())[: image.sizeInBytes()]).hexdigest()


def test_live_renderer_draws_graph_pixels_and_deterministic_glitch_frames():
    clean_image = render_live_snapshot(_snapshot_for_graph(clean_subtitle_graph()), width=640, height=360)
    comic_image = render_live_snapshot(_snapshot_for_graph(comic_burst_graph()), width=640, height=360)
    assert _image_digest(clean_image) != _image_digest(comic_image)

    snapshot = _snapshot_for_graph(glitch_graph())
    source = render_live_snapshot(snapshot, width=640, height=360)
    scene = CompiledLiveScene.compile(glitch_graph())
    frame_a, sample_a = render_live_scene_frame(source, scene, 90)
    frame_b, _sample_b = render_live_scene_frame(source, scene, 90)
    stable, _sample_stable = render_live_scene_frame(source, scene, 900)
    assert _image_digest(frame_a) == _image_digest(frame_b)
    assert _image_digest(frame_a) != _image_digest(stable)
    assert sample_a.value("glitch", "rgb_offset") > 0


def test_actual_live_first_frame_render_meets_simple_and_complex_gates():
    timings = {}
    for key, graph, gate in (
        ("simple", clean_subtitle_graph(), 100.0),
        ("complex", comic_burst_graph(), 150.0),
    ):
        snapshot = _snapshot_for_graph(graph)
        started = perf_counter()
        source = render_live_snapshot(snapshot, width=640, height=360)
        scene = CompiledLiveScene.compile(graph)
        render_live_scene_frame(source, scene, 0)
        timings[key] = (perf_counter() - started) * 1000.0
        assert timings[key] < gate


def test_graph_live_layers_are_cached_as_independent_nonblank_rasters():
    snapshot = _snapshot_for_graph(comic_burst_graph())
    layers = render_live_layers(snapshot, width=640, height=360)
    assert set(layers) == {"rays", "panel", "dots", "effects", "text"}
    assert all(not image.isNull() for image in layers.values())
    digests = [_image_digest(image) for image in layers.values()]
    assert len(set(digests)) == len(digests)
    scene = CompiledLiveScene.compile(comic_burst_graph())
    frame_early, _ = composite_live_scene_layers(layers, scene, 40)
    frame_hold, _ = composite_live_scene_layers(layers, scene, 900)
    assert _image_digest(frame_early) != _image_digest(frame_hold)


def test_advanced_canvas_does_not_apply_device_pixel_ratio_twice(monkeypatch):
    snapshot = _snapshot_for_graph(comic_burst_graph())
    captured = {}
    ready = threading.Event()

    def capture_layers(_snapshot, *, width, height, device_pixel_ratio):
        captured.update({
            "width": width,
            "height": height,
            "device_pixel_ratio": device_pixel_ratio,
        })
        ready.set()
        return {}

    monkeypatch.setattr(studio_live_canvas, "render_live_layers", capture_layers)
    owner = QWidget()
    canvas = studio_ui.AdvancedLiveCanvas(owner)
    pixmap = QPixmap(2240, 1260)
    pixmap.setDevicePixelRatio(1.75)
    canvas.set_visual(pixmap, snapshot)

    assert ready.wait(1.0)
    assert captured == {
        "width": 1280,
        "height": 720,
        "device_pixel_ratio": 1.75,
    }
    canvas.deleteLater()
    owner.deleteLater()


def test_independent_layer_compositor_meets_30fps_p95_gate():
    snapshot = _snapshot_for_graph(comic_burst_graph())
    scene = CompiledLiveScene.compile(comic_burst_graph())
    layers = render_live_layers(snapshot, width=640, height=360)
    timings = []
    for frame_index in range(90):
        started = perf_counter()
        composite_live_scene_layers(layers, scene, frame_index * 33)
        timings.append((perf_counter() - started) * 1000.0)
    timings.sort()
    assert timings[int(len(timings) * 0.95) - 1] < 40.0


class _FidelitySink:
    def __init__(self):
        self.pixmap = None
        self.text = ""
        self.tooltip = ""

    def devicePixelRatioF(self):
        return 1.0

    def width(self):
        return 320

    def height(self):
        return 180

    def setPixmap(self, pixmap):
        self.pixmap = QPixmap(pixmap)

    def setText(self, text):
        self.text = str(text)

    def setToolTip(self, text):
        self.tooltip = str(text)


class _FidelityOverlay:
    def __init__(self):
        self.calls = []

    def set_visual(self, pixmap, snapshot, *, animate_graph=True):
        self.calls.append((QPixmap(pixmap), snapshot, bool(animate_graph)))


def _fidelity_page(snapshot, *, paused):
    preview = _FidelitySink()
    overlay = _FidelityOverlay()
    page = SimpleNamespace(
        advanced_preview_image=preview,
        advanced_style_status=_FidelitySink(),
        advanced_cue_overlay=overlay,
        _advanced_preview_state=SimpleNamespace(
            publish_ready=lambda *_args, **_kwargs: True,
        ),
        _advanced_frame_memory={},
        _advanced_frame_memory_limit=4,
        _advanced_preview_snapshot=snapshot,
        _advanced_preview_generation=1,
        _advanced_canvas_source_kind="live",
        project=SimpleNamespace(project_id=snapshot.project_id),
        _renderer_cue_at_playhead=lambda: SimpleNamespace(id=snapshot.cue_id),
        _studio_trace=lambda *_args, **_kwargs: None,
        _sync_advanced_cue_overlay=lambda: None,
        _web_live_is_fresh=lambda:False,
        _caption_snapshot_hash=lambda snapshot:snapshot.stable_hash(),
        _fidelity_stroke_parity_ok=lambda *_args: True,
        _fidelity_geometry_ok=lambda *_args: True,
        video=SimpleNamespace(
            playback_position_snapshot=lambda: SimpleNamespace(paused=paused),
        ),
    )
    page._fidelity_can_replace_live = lambda active: (
        studio_ui.SubtitleStudioPage._fidelity_can_replace_live(page, active)
    )
    return page, preview, overlay


def _publish_fidelity(page, snapshot):
    pixmap = QPixmap(640, 360)
    pixmap.fill()
    identity = SimpleNamespace(
        job_kind="production",
        job_id="fidelity-test",
        project_id=snapshot.project_id,
        cue_id=snapshot.cue_id,
        request_key="fidelity-ready",
        snapshot_hash=snapshot.stable_hash(),
        graph_hash=getattr(snapshot, "graph_hash", ""),
        appearance_generation=getattr(snapshot, "appearance_generation", 0),
    )
    page._advanced_preview_state.identity = identity
    page._advanced_preview_state.generation = 1
    studio_ui.SubtitleStudioPage._publish_advanced_frame(
        page, identity, 1, "", False, pixmap=pixmap,
    )


def test_playing_motion_keeps_live_when_fidelity_becomes_ready():
    snapshot = _snapshot_for_graph(comic_burst_graph())
    page, preview, overlay = _fidelity_page(snapshot, paused=False)

    _publish_fidelity(page, snapshot)

    assert page._advanced_canvas_source_kind == "live"
    assert overlay.calls == []
    assert preview.pixmap is not None
    assert "LIVE" in page.advanced_style_status.text


@pytest.mark.parametrize("paused, static", [(True, False), (False, True)])
def test_paused_or_static_visual_can_switch_to_fidelity(paused, static):
    snapshot = _snapshot_for_graph(comic_burst_graph())
    if static:
        recipe = dict(snapshot.style_recipe)
        recipe["visualGraph"] = {}
        snapshot = replace(
            snapshot,
            motion_recipe={"mode": "none", "origin": "none"},
            style_recipe=recipe,
        )
    page, _preview, overlay = _fidelity_page(snapshot, paused=paused)

    _publish_fidelity(page, snapshot)

    if static:
        assert page._advanced_canvas_source_kind == "fidelity"
        assert len(overlay.calls) == 1
        assert overlay.calls[0][2] is False
    else:
        # The current Graph Motion contract has one LIVE owner, even paused.
        assert page._advanced_canvas_source_kind == "live"
        assert overlay.calls == []


def test_ai_style_v4_requests_graphs_and_sends_complete_product_context(monkeypatch):
    captured = {}
    directions = (
        fallback_art_directions("美漫爆裂")[0],
        fallback_art_directions("赛博故障")[0],
        fallback_art_directions("游戏直播")[1],
    )

    class Provider:
        provider_id = "fixture"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(messages, schema, **kwargs):
            captured["messages"] = messages
            captured["schema"] = schema
            captured["max_tokens"] = kwargs.get("max_tokens")
            return {
                "design_intent": "layered",
                "visual_changes": ["panel", "decorations", "effect"],
                "motion_reason": "independent layer tracks",
                "art_directions": [item.to_dict() for item in directions],
                "variants": [
                    comic_burst_graph().to_dict(),
                    glitch_graph().to_dict(),
                    streamer_gaming_graph().to_dict(),
                ],
            }

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: Provider())
    project = SubtitleProject(
        media=StudioMedia(path="D:/graph.mp4", duration_ms=2_400, width=1920, height=1080),
        cues=[StudioCue("graph-cue", 0, 2_400, "空中打拳", speaker_id="host")],
    )
    suggestion = request_style_design(project, "graph-cue", "三份具有独立图层动作的字幕方向", {"models": {}})
    request = json.loads(captured["messages"][1]["content"])

    assert suggestion.provider_succeeded
    assert suggestion.recipe.visual_graph["schema"] == "2byte.visual-design-graph"
    assert captured["schema"]["properties"]["variants"]["items"]["properties"]["motionGraph"]
    assert captured["max_tokens"] == 8192
    assert "Exact key contract" in captured["messages"][0]["content"]
    assert request["cue_text"] == "空中打拳"
    assert request["speaker"]["id"] == "host"
    assert request["resolution"] == {"width": 1920, "height": 1080}
    assert request["visual_graph_schema"]["properties"]["variants"]["items"]["properties"]["motionGraph"]
    assert any(
        "corresponding ArtDirectionSpec primary family" in item
        for item in request["semantic_requirements"]
    )
    assert any(
        "allowed layers" in item
        for item in request["semantic_requirements"]
    )
    assert request["safe_area"]["bottom"] == 108
    assert request["available_fonts"]
    assert request["visual_capability_manifest"]["live"]["comic_burst"] == "FULL"
    assert request["project_profile"]["cue_count"] == 1


def test_ai_vision_frame_is_requested_only_for_declared_capability(tmp_path, monkeypatch):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fixture-frame")
    calls = []
    captured_content = []
    directions = (
        fallback_art_directions("美漫爆裂")[0],
        fallback_art_directions("赛博故障")[0],
        fallback_art_directions("游戏直播")[1],
    )

    class Provider:
        provider_id = "fixture"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=bool(calls), structured_output=True)

        @staticmethod
        def structured_complete(messages, _schema, **_kwargs):
            captured_content.append(messages[1]["content"])
            return {
                "design_intent": "layered",
                "visual_changes": ["panel", "decorations", "effect"],
                "motion_reason": "independent layer tracks",
                "art_directions": [item.to_dict() for item in directions],
                "variants": [
                    comic_burst_graph().to_dict(),
                    glitch_graph().to_dict(),
                    streamer_gaming_graph().to_dict(),
                ],
            }

    monkeypatch.setattr("twobyteasr.caption_design.studio_ai.provider_for_stage", lambda *_a, **_k: Provider())
    project = SubtitleProject(
        media=StudioMedia(path="D:/graph.mp4", duration_ms=2_400),
        cues=[StudioCue("graph-cue", 0, 2_400, "空中打拳")],
    )

    def supplier():
        calls.append("capture")
        return image_path

    request_style_design(
        project, "graph-cue", "故障", {"models": {}},
        vision_frame_supplier=supplier,
    )
    assert calls == []
    assert isinstance(captured_content[-1], str)

    calls.append("enable-vision")
    request_style_design(
        project, "graph-cue", "故障", {"models": {}},
        vision_frame_supplier=supplier,
    )
    assert calls[-1] == "capture"
    assert isinstance(captured_content[-1], list)
    assert captured_content[-1][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
