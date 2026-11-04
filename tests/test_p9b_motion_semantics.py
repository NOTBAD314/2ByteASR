"""P9B deterministic motion semantics for one 5000ms cue.

The cue is sampled at fixed times across entrance/hold/exit. The contract:

* a subtitle that finished its entrance may never go hidden before the exit
  window starts;
* a graph without an exit must stay visible until the last sampled
  millisecond before cue end;
* a graph with an exit may only fade inside its exit window;
* a Fidelity takeover (static frame) must animate again on the first moving
  tick — the "frozen after resume" regression.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.studio.studio_ui import AdvancedLiveCanvas
from twobyteasr.caption_design.visual_design_graph import (
    CompiledLiveScene,
    MotionGraph,
    MotionKeyframe,
    MotionTrack,
    VisualDesignGraph,
    TextLayer,
    compile_live_scene,
    normalize_motion_graph_to_cue,
)

CUE_MS = 5_000
SAMPLES_MS = (0, 16, 100, 300, 800, 1_500, 2_500, 4_000, 4_800, 4_999)


def _app():
    return QApplication.instance() or QApplication([])


def _graph(tracks, name="P9B Deterministic"):
    return VisualDesignGraph(
        name=name,
        text_layer=TextLayer(),
        motion_graph=MotionGraph(2_400, tracks),
    ).validate()


def test_entrance_without_exit_holds_visible_until_cue_end():
    graph = _graph([
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"), MotionKeyframe(240, 1.0, "ease-out"),
        ]),
        MotionTrack("group", "scale", [
            MotionKeyframe(0, 0.8, "overshoot"), MotionKeyframe(240, 1.0, "ease-out"),
        ]),
    ])
    scene = compile_live_scene(graph, cue_duration_ms=CUE_MS)
    visible = []
    for moment in SAMPLES_MS:
        sample = scene.sample(moment)
        opacity = sample.value("group", "opacity", 1.0)
        visible.append((moment, opacity))
    # Entrance may be transparent; everything after entrance end (240ms
    # normalized) must be fully readable until 4999ms.
    for moment, opacity in visible:
        if moment >= 300:
            assert opacity >= 0.99, f"hidden at {moment}ms without an exit: {opacity}"
    assert visible[-1] == (4_999, pytest.approx(1.0))


def test_exit_only_fades_inside_exit_window():
    graph = _graph([
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "ease-out"), MotionKeyframe(200, 1.0, "ease-out"),
            MotionKeyframe(2_150, 1.0, "ease-in"), MotionKeyframe(2_400, 0.0, "ease-in"),
        ]),
    ])
    normalized = normalize_motion_graph_to_cue(graph, CUE_MS)
    scene = compile_live_scene(normalized)
    hold_opacities = [
        scene.sample(moment).value("group", "opacity", 1.0)
        for moment in (800, 1_500, 2_500, 4_000)
    ]
    assert all(o >= 0.99 for o in hold_opacities), hold_opacities
    near_end = scene.sample(4_999).value("group", "opacity", 1.0)
    assert near_end <= 0.5, "exit must be anchored to the cue end"


def test_tail_fade_without_exit_flag_is_still_an_exit():
    # A provider graph whose opacity dips below 0.5 at the tail must anchor
    # that fade to the cue end, not blank the hold (the applied-AI bug).
    graph = _graph([
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0), MotionKeyframe(150, 1.0),
            MotionKeyframe(1_200, 1.0), MotionKeyframe(2_400, 0.0),
        ]),
    ])
    scene = compile_live_scene(graph, cue_duration_ms=CUE_MS)
    for moment in (800, 1_500, 2_500):
        assert scene.sample(moment).value("group", "opacity", 1.0) >= 0.99
    assert scene.sample(4_000).value("group", "opacity", 1.0) >= 0.5


def _canvas_owner() -> tuple[QWidget, AdvancedLiveCanvas]:
    owner = QWidget()
    canvas = AdvancedLiveCanvas(owner)
    return owner, canvas


def _pixmap(width: int, height: int) -> QPixmap:
    from PySide6.QtGui import QColor

    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#FFFFFFFF"))
    return pixmap


def _snapshot(cue_id: str = "cue-p9b"):
    from types import SimpleNamespace

    return SimpleNamespace(
        cue_id=cue_id, text="确定性采样", start_ms=1_000, end_ms=6_000,
        font_family="Microsoft YaHei", font_size=52.0, font_weight=700,
        italic=False, letter_spacing=0.0,
        fill={"type": "solid", "color": "#FFFFFFFF"},
        strokes=({"color": "#FF000000", "width": 3, "alignment": "OUTSIDE"},),
        shadow={}, glow={},
        playres_x=1920, playres_y=1080,
        position_x=960.0, position_y=1000.0,
        anchor_x=0.5, anchor_y=1.0, scale_x=1.0, scale_y=1.0, rotation=0.0,
        style_recipe={}, motion_recipe={},
        stable_hash=lambda: "p9b-hash",
    )


def test_fidelity_takeover_resumes_animation_on_next_tick():
    app = _app()
    owner, canvas = _canvas_owner()
    canvas._base_rect = canvas.rect().adjusted(0, 0, 1280, 720)
    graph = VisualDesignGraph(
        name="Takeover Resume",
        text_layer=TextLayer(),
        motion_graph=MotionGraph(5_000, [
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0.0), MotionKeyframe(200, 1.0),
                MotionKeyframe(4_700, 1.0), MotionKeyframe(5_000, 0.0),
            ]),
        ]),
    ).validate()
    canvas._snapshot = _snapshot()
    canvas._layer_render_geometry = (1280, 720, 1.0)
    canvas._compiled_scene = CompiledLiveScene.compile(
        graph, cue_duration_ms=CUE_MS,
    )
    canvas.set_visual(_pixmap(1280, 720), canvas._snapshot, animate_graph=False)
    # set_visual recompiles from the minimal fake snapshot (no graph); restore
    # the real compiled scene the way a visualGraph-backed snapshot would.
    canvas._compiled_scene = CompiledLiveScene.compile(graph, cue_duration_ms=CUE_MS)
    assert not canvas._layer_images, "Fidelity takeover starts as a static frame"
    canvas._last_frame_signature = None
    canvas.sync_time(3_000, paused=False)
    app.processEvents()
    assert canvas._layer_pipeline_started_for == canvas._layer_generation, (
        "first moving tick after a Fidelity takeover must restart layer rasters"
    )
    assert canvas._layer_images, "offscreen layer pipeline completes synchronously"
    canvas.deleteLater()
    owner.deleteLater()


def test_publish_gap_phase_cannot_remove_mid_cue(monkeypatch):
    app = _app()

    class Controller:
        running = True
        removed: list[int] = []
        overlays: dict[int, dict] = {}

        def post_raw_overlay(self, overlay_id, path, **geometry):
            self.overlays[int(overlay_id)] = True
            return True

        def post_remove_overlay(self, overlay_id):
            self.removed.append(int(overlay_id))
            self.overlays.pop(int(overlay_id), None)
            return True

    from twobyteasr.studio.studio_ui import MpvCanvas

    video = MpvCanvas()
    video.controller = Controller()
    video._media_attached = True  # explicit live-media precondition
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage

    opaque = QImage(8, 8, QImage.Format.Format_ARGB32)
    opaque.fill("#FFFF0000")
    assert video.publish_compositor_overlay(
        0, opaque, QRect(0, 0, 8, 8), source_bounds=QRect(0, 0, 8, 8),
    )
    transparent = QImage(8, 8, QImage.Format.Format_ARGB32)
    transparent.fill("#00000000")
    # Transparent frames mid-cue (ENTRANCE/HOLD/EXIT) must retain the overlay.
    for phase in ("ENTRANCE", "HOLD", "EXIT"):
        assert not video.publish_compositor_overlay(
            0, transparent, QRect(0, 0, 8, 8), phase=phase,
        )
        assert video.controller.overlays == {0: True}, phase
    # AFTER_CUE transparent frames remove it.
    assert not video.publish_compositor_overlay(
        0, transparent, QRect(0, 0, 8, 8), phase="AFTER_CUE",
    )
    assert video.controller.overlays == {}
    video.deleteLater()
