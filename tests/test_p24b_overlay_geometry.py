"""Regression: the mpv overlay must stay anchored to the canvas rect.

The "subtitle appears 1-2 frames then vanishes" bug was geometric: after the
background layer callback arrived, the full-canvas raster was re-anchored at
the in-bitmap bbox offset, pushing the glyphs outside the video window. mpv
accepted overlay-add and painted it — off-screen. These tests pin the
publish contract: target rect == canvas geometry, and the cropped display
rect stays inside the window.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.rendering.studio_live_canvas import AdvancedLiveCanvas


@pytest.fixture(scope="module", autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


class _RecordingOwner(QWidget):
    ADVANCED_OVERLAY_ID = 0

    def __init__(self):
        super().__init__()
        self.published: list[dict] = []
        self.removed: list[int] = []

    def publish_compositor_overlay(self, overlay_id, source, target_rect, **kwargs):
        self.published.append({
            "id": int(overlay_id),
            "target": QRect(target_rect),
            "bounds": QRect(kwargs.get("source_bounds") or QRect()),
            "pixmap": QPixmap(source),
        })
        return True

    def remove_compositor_overlay(self, overlay_id, **_kwargs):
        self.removed.append(int(overlay_id))
        return True

    def active_compositor_overlay_ids(self):
        return []


def _canvas_with_layers(owner: _RecordingOwner) -> AdvancedLiveCanvas:
    canvas = AdvancedLiveCanvas(owner)
    canvas._base_rect = QRect(0, 0, 1280, 720)
    pixmap = QPixmap(1280, 720)
    pixmap.fill()
    from types import SimpleNamespace

    snapshot = SimpleNamespace(
        cue_id="geo", text="几何回归", start_ms=1_000, end_ms=6_000,
        font_family="Microsoft YaHei", font_size=52.0, font_weight=700,
        italic=False, letter_spacing=0.0,
        fill={"type": "solid", "color": "#FFFFFFFF"},
        strokes=({"color": "#FF000000", "width": 3, "alignment": "OUTSIDE"},),
        shadow={}, glow={},
        playres_x=1920, playres_y=1080,
        position_x=960.0, position_y=1000.0,
        anchor_x=0.5, anchor_y=1.0, scale_x=1.0, scale_y=1.0, rotation=0.0,
        style_recipe={}, motion_recipe={},
        stable_hash=lambda: "geo-hash",
    )
    canvas.set_visual(pixmap, snapshot, animate_graph=True)
    return canvas


def test_publish_target_anchored_to_canvas_rect():
    owner = _RecordingOwner()
    canvas = _canvas_with_layers(owner)
    assert owner.published, "set_visual must publish"
    for record in owner.published:
        assert record["target"] == QRect(canvas.geometry()), (
            "overlay target must be the canvas rect; anchoring at an "
            "in-bitmap offset pushes subtitles off-screen"
        )
    canvas.deleteLater()
    owner.deleteLater()


def test_layer_callback_keeps_canvas_anchor():
    owner = _RecordingOwner()
    canvas = _canvas_with_layers(owner)
    # Materialize a tracked scene the way a visualGraph-backed snapshot does
    # (the fake snapshot has no recipe, so set_visual compiled nothing).
    from twobyteasr.caption_design.visual_design_graph import (
        CompiledLiveScene, MotionGraph, MotionKeyframe, MotionTrack,
        TextLayer, VisualDesignGraph,
    )

    graph = VisualDesignGraph(
        name="geo", text_layer=TextLayer(),
        motion_graph=MotionGraph(4_000, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0.0), MotionKeyframe(200, 1.0),
                MotionKeyframe(3_800, 1.0), MotionKeyframe(4_000, 0.0),
            ]),
        ]),
    ).validate()
    canvas._compiled_scene = CompiledLiveScene.compile(graph, cue_duration_ms=5_000)
    canvas._layer_pipeline_started_for = -1
    canvas.sync_time(2_000, paused=False)
    QApplication.processEvents()
    # the background layer pipeline completes synchronously offscreen and
    # triggers _accept_live_layers — the exact moment the old bug moved
    # the overlay off-screen
    assert canvas._layer_images, "offscreen layer pipeline must complete"
    canvas._last_frame_signature = None
    owner.published.clear()
    canvas.sync_time(2_040, paused=False)
    QApplication.processEvents()
    assert owner.published, "moving tick must publish"
    for record in owner.published:
        assert record["target"] == QRect(canvas.geometry())
        assert record["target"].x() == 0 and record["target"].y() == 0
    canvas.deleteLater()
    owner.deleteLater()


def test_bounds_hint_stays_within_raster():
    owner = _RecordingOwner()
    canvas = _canvas_with_layers(owner)
    from twobyteasr.caption_design.visual_design_graph import (
        CompiledLiveScene, MotionGraph, MotionKeyframe, MotionTrack,
        TextLayer, VisualDesignGraph,
    )

    graph = VisualDesignGraph(
        name="geo", text_layer=TextLayer(),
        motion_graph=MotionGraph(4_000, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0.0), MotionKeyframe(200, 1.0),
            ]),
        ]),
    ).validate()
    canvas._compiled_scene = CompiledLiveScene.compile(graph, cue_duration_ms=5_000)
    canvas._layer_pipeline_started_for = -1
    canvas.sync_time(2_000, paused=False)
    QApplication.processEvents()
    assert canvas._layer_images, "offscreen layer pipeline must complete"
    hint = canvas._mpv_bounds_hint
    raster = canvas._source_image.rect()
    assert not hint.isEmpty()
    assert raster.contains(hint)
    canvas.deleteLater()
    owner.deleteLater()
