"""Advanced subtitle LIVE layer cache: replay must reuse rasterized layers.

The cache is bbox-local (never a full-frame RGBA mirror per cue), keyed by
content identity, and a miss falls back to the normal asynchronous pipeline.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
import pytest

from twobyteasr.rendering.advanced_live_renderer import (
    composite_live_scene_layers,
    render_live_layers,
)
from twobyteasr.rendering.live_layer_cache import (
    GLOBAL_LIVE_LAYER_CACHE,
    LiveLayerCache,
    live_layer_cache_key,
)
from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.caption_design.visual_design_graph import (
    compile_live_scene,
    compile_live_scene_cached,
    glitch_graph,
)
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


def _advanced_project():
    recipe = style_recipe_for_prompt("赛博故障 glitch")
    recipe.visual_graph = glitch_graph().to_dict()
    style = SubtitleStyle(
        id="advanced", name="glitch", font_family="Microsoft YaHei",
        font_size=58.0, position_x=820, position_y=910,
    )
    return SubtitleProject(
        media=StudioMedia(path="source.mp4", duration_ms=8_000, width=1920, height=1080),
        cues=[StudioCue("cue", 500, 5_000, "权威字幕", style_id="advanced")],
        styles=[SubtitleStyle(id="default", name="Default"), style],
        style_recipes={"advanced": recipe.to_dict()},
    )


def _snapshot(width=320, height=180):
    return build_visual_cue_snapshot(
        _advanced_project(), "cue", width=width, height=height, fps=30.0,
    )


def test_cache_round_trip_preserves_composite_pixels():
    _app()
    GLOBAL_LIVE_LAYER_CACHE.clear()
    snapshot = _snapshot()
    scene = compile_live_scene(snapshot.style_recipe["visualGraph"], cue_duration_ms=4_500)
    pivot = None

    fresh = render_live_layers(snapshot, width=320, height=180, device_pixel_ratio=1.0)
    key = live_layer_cache_key(snapshot, width=320, height=180, device_pixel_ratio=1.0)
    assert GLOBAL_LIVE_LAYER_CACHE.store(key, fresh)

    materialized = GLOBAL_LIVE_LAYER_CACHE.materialize(key, snapshot=snapshot)
    assert materialized is not None
    assert set(materialized.keys()) == set(fresh.keys())

    fresh_frame, _ = composite_live_scene_layers(fresh, scene, 600, pivot=pivot)
    cached_frame, _ = composite_live_scene_layers(materialized, scene, 600, pivot=pivot)
    assert not cached_frame.isNull()
    assert cached_frame.size() == fresh_frame.size()
    assert QImage(cached_frame) == QImage(fresh_frame), (
        "materialized layers must composite to the same pixels as fresh rasters"
    )
    stats = GLOBAL_LIVE_LAYER_CACHE.stats()
    assert stats["entries"] == 1 and stats["hits"] == 1


@pytest.mark.parametrize('dpr',[1.25,1.5,1.75,2.0])
def test_hidpi_cache_preserves_every_layer_at_physical_origin(dpr):
    _app()
    snapshot=_snapshot(width=600,height=338)
    layers=render_live_layers(snapshot,width=600,height=338,device_pixel_ratio=dpr)
    cache=LiveLayerCache()
    assert cache.store('hidpi',layers)
    restored=cache.materialize('hidpi',snapshot=snapshot)
    # Compare effects separately; a tracking redraw used to repair only text
    # and hide the doubled-origin loss of its cached shadow/glow.
    for key in layers:
        assert restored[key]==layers[key],key


def test_cache_is_bbox_local_not_full_frame_mirror():
    _app()
    cache = LiveLayerCache(max_entries=4, max_bytes=64 * 1024 * 1024)
    snapshot = _snapshot()
    fresh = render_live_layers(snapshot, width=320, height=180, device_pixel_ratio=1.0)
    canvas_bytes = sum(image.sizeInBytes() for image in fresh.values())
    key = live_layer_cache_key(snapshot, width=320, height=180, device_pixel_ratio=1.0)
    assert cache.store(key, fresh)
    stats = cache.stats()
    assert 0 < stats["bytes"] <= canvas_bytes
    # A subtitle band never spans the whole canvas; the cropped entry must be
    # meaningfully smaller than the full-canvas raster set.
    assert stats["bytes"] < canvas_bytes


def test_key_changes_with_cue_content_and_geometry():
    _app()
    base = _snapshot()
    other_size = live_layer_cache_key(base, width=640, height=360, device_pixel_ratio=1.0)
    same = live_layer_cache_key(base, width=320, height=180, device_pixel_ratio=1.0)
    assert same != other_size

    edited_project = _advanced_project()
    edited_project.cues[0].text = "完全不同的字幕内容"
    edited = build_visual_cue_snapshot(edited_project, "cue", width=320, height=180, fps=30.0)
    assert live_layer_cache_key(edited, width=320, height=180, device_pixel_ratio=1.0) != same


def test_miss_returns_none_and_stats_counted():
    _app()
    cache = LiveLayerCache()
    assert cache.materialize("missing-key") is None
    assert cache.stats()["misses"] == 1


def test_lru_eviction_respects_entry_and_byte_budgets():
    _app()
    cache = LiveLayerCache(max_entries=2, max_bytes=10**9)
    snapshot = _snapshot()
    layers = render_live_layers(snapshot, width=320, height=180, device_pixel_ratio=1.0)
    for salt in range(4):
        key = f"key-{salt}"
        assert cache.store(key, layers)
        cache.materialize(key)
    assert cache.stats()["entries"] == 2

    tight = LiveLayerCache(max_entries=8, max_bytes=1)
    assert not tight.store("never", layers)


def test_compile_scene_cached_returns_identical_scene():
    _app()
    payload = glitch_graph().to_dict()
    first = compile_live_scene_cached(payload, cue_duration_ms=4_500)
    second = compile_live_scene_cached(payload, cue_duration_ms=4_500)
    assert first is second
    assert first.graph_hash == second.graph_hash
    other = compile_live_scene_cached(payload, cue_duration_ms=9_000)
    assert other is not first, "cue duration is part of the compile identity"
