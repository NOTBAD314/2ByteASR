import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot, render_live_layers
from twobyteasr.caption_design.studio_ai import style_recipe_for_prompt
from twobyteasr.rendering.studio_live_canvas import AdvancedLiveCanvas
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.caption_design.visual_design_graph import MotionGraph, glitch_graph
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _snapshot(*, moving=False, effects=False):
    graph = glitch_graph()
    if not moving:
        graph.motion_graph = MotionGraph(4500, [])
    if not effects:
        graph.effect_layers = []
    recipe = style_recipe_for_prompt('赛博故障 glitch')
    recipe.visual_graph = graph.to_dict()
    project = SubtitleProject(media=StudioMedia('source.mp4', duration_ms=8000, width=1920, height=1080),
        cues=[StudioCue('cue', 500, 5000, '完整材质字幕', style_id='advanced')],
        styles=[SubtitleStyle(id='default',name='Default'), SubtitleStyle(id='advanced',name='Advanced',
            font_family='Microsoft YaHei', font_size=78, position_x=960, position_y=900)],
        style_recipes={'advanced':recipe.to_dict()})
    return build_visual_cue_snapshot(project, 'cue', width=640, height=360, fps=60)


def _visible_canvas():
    owner = QWidget()
    owner.resize(640,360)
    canvas = AdvancedLiveCanvas(owner)
    canvas.set_base_geometry(QRect(0, 0, 640, 360))
    owner.show()
    canvas.show()
    return owner,canvas


@pytest.mark.parametrize('dpr', [1.25, 1.5, 2.0])
def test_static_composite_keeps_all_pixels_without_second_raster(monkeypatch, dpr):
    app = QApplication.instance() or QApplication([])
    snapshot = _snapshot()
    complete = render_live_snapshot(snapshot, width=640, height=360, device_pixel_ratio=dpr)
    # These reference rasters prove the complete image contains the real
    # typography AND material/effects; a plain text-only replacement fails.
    text = render_live_snapshot(snapshot, width=640, height=360,
        device_pixel_ratio=dpr, layers=frozenset({'text'}))
    material = render_live_snapshot(snapshot, width=640, height=360,
        device_pixel_ratio=dpr, layers=frozenset({'backdrop','effects'}))
    assert complete != text and complete != material
    assert not complete.isNull()
    # Exercise the original visible, settled layer acceptance, including its
    # compositing and bounds updates, as the pixel reference.
    reference_owner, reference = _visible_canvas()
    reference.set_visual(QPixmap.fromImage(complete), snapshot, animate_graph=False)
    layers = render_live_layers(snapshot, width=640, height=360, device_pixel_ratio=dpr)
    reference._accept_live_layers(reference._layer_generation, snapshot.stable_hash(), layers)
    expected = reference._source_image.copy()
    assert reference._layer_images
    owner, canvas = _visible_canvas()
    def unexpected_raster(*args, **kwargs):
        pytest.fail('A static complete composite must not be rasterized again as layers')
    monkeypatch.setattr('twobyteasr.rendering.studio_live_canvas.render_live_layers', unexpected_raster)
    canvas.set_visual(QPixmap.fromImage(complete), snapshot)
    assert canvas._compiled_scene is not None and not canvas._compiled_scene.tracks
    for milliseconds, paused in [(600,False), (1800,False), (3000,True), (4100,False)]:
        canvas.sync_time(milliseconds, paused=paused)
        assert canvas._source_image.size() == expected.size()
        assert canvas._source_image.devicePixelRatio() == expected.devicePixelRatio()
        import numpy as np
        left=np.frombuffer(canvas._source_image.constBits(),dtype=np.uint8).astype(np.int16)
        right=np.frombuffer(expected.constBits(),dtype=np.uint8).astype(np.int16)
        # Direct drawing and compositing premultiplied intermediate layers
        # round alpha in a different order: at most 2/255 per RGBA channel.
        assert np.abs(left-right).max() <= 2
        assert canvas._display_source.toImage() == canvas._source_image
        assert not canvas._layer_images
    owner.close()
    owner.deleteLater()
    reference_owner.close()
    reference_owner.deleteLater()


def test_real_motion_resumes_after_fidelity_takeover():
    app = QApplication.instance() or QApplication([])
    snapshot = _snapshot(moving=True,effects=True)
    complete = render_live_snapshot(snapshot, width=640, height=360)
    owner,canvas = _visible_canvas()
    canvas.set_visual(QPixmap.fromImage(complete), snapshot, animate_graph=False)
    assert canvas._compiled_scene.tracks and not canvas._layer_images
    canvas.sync_time(520, paused=False)
    entrance = canvas._source_image.copy()
    assert canvas._layer_images
    canvas.sync_time(1600, paused=False)
    assert canvas._source_image != entrance
    owner.close()
    owner.deleteLater()


def test_implicit_effects_without_tracks_keep_original_layer_pipeline():
    app = QApplication.instance() or QApplication([])
    snapshot = _snapshot(effects=True)
    complete = render_live_snapshot(snapshot, width=640, height=360)
    owner,canvas = _visible_canvas()
    canvas.set_visual(QPixmap.fromImage(complete), snapshot)
    assert not canvas._compiled_scene.tracks
    assert canvas._compiled_scene.graph.effect_layers
    assert canvas._layer_images
    owner.close()
    owner.deleteLater()
