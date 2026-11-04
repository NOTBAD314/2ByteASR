from __future__ import annotations

import copy
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtWidgets import QApplication

import twobyteasr.playback.audio_engine as audio_engine
from twobyteasr.rendering.advanced_preview import (
    AdvancedPreviewIdentity,
    AdvancedPreviewStateMachine,
)
from twobyteasr.design.color_picker import (
    ColorPickerWidget,
    alpha_to_percent,
    percent_to_alpha,
)
from twobyteasr.timeline.studio_commands import SetCuePresentationCommand, cue_by_id
from twobyteasr.projects.studio_project import (
    StudioCue,
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
)
from twobyteasr.design.themed_icons import cached_icon_pixmap, paint_cached_icon
from twobyteasr.caption_style.style_recipe import compile_native_recipe
from twobyteasr.caption_design.visual_design_graph import clean_subtitle_graph, style_recipe_from_graph
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("percent", [0, 1, 25, 50, 75, 99, 100])
def test_color_picker_opacity_percent_is_bidirectional(percent: int):
    _app()
    picker = ColorPickerWidget(show_alpha=True)
    picker.set_color(QColor("#FF336699"))

    picker._opacity_slider.setValue(percent)

    expected_alpha = percent_to_alpha(percent)
    assert picker.alpha_spin.value() == percent
    assert picker._opacity_slider.value() == percent
    assert picker.color().alpha() == expected_alpha
    assert alpha_to_percent(picker.color().alpha()) == percent

    restored = QColor("#FF336699")
    restored.setAlpha(expected_alpha)
    picker.set_color(restored)
    assert picker.alpha_spin.value() == percent
    assert picker._opacity_slider.value() == percent
    assert picker.color().alpha() == expected_alpha
    picker.close()


def _style(style_id: str, width: float) -> SubtitleStyle:
    return SubtitleStyle(
        id=style_id,
        name=style_id,
        outline_color="#FF000000",
        outline_width=width,
    )


def test_snapshot_materializes_preset_plus_override_over_stale_visual_graph():
    graph = clean_subtitle_graph().to_dict()
    graph["textLayer"]["strokes"] = []
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=3_000),
        styles=[_style("default", 4), _style("preset-a", 3), _style("derived", 0)],
        cues=[StudioCue(
            "cue",
            0,
            2_000,
            "0 8 B 中 口 回",
            style_id="derived",
            base_preset_id="preset-a",
            appearance_override={"outline_width": 20.0},
            appearance_generation=7,
        )],
        style_recipes={
            "derived": {
                "name": "stale derived",
                "outline": {"color": "#FF000000", "width": 0, "layers": []},
                "visualGraph": graph,
            },
        },
    )
    project.validate()

    snapshot = build_visual_cue_snapshot(project, "cue")

    assert snapshot.appearance_generation == 7
    assert snapshot.strokes[0]["width"] == 20.0
    assert snapshot.style_recipe["outline"]["layers"][0]["width"] == 20.0
    assert snapshot.style_recipe["visualGraph"]["textLayer"]["strokes"][0]["width"] == 20.0


def test_advanced_apply_keeps_gradient_graph_when_native_mirror_is_materialized(
    tmp_path, monkeypatch,
):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(path="fixture.mp4", duration_ms=10_000)
    page.project.cues = [StudioCue("cue", 0, 2_000, "gradient", style_id="default")]
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    page.select_cue("cue")
    page._queue_advanced_preview = lambda *_args, **_kwargs: None

    graph = clean_subtitle_graph()
    graph.text_layer.fill = {
        "type": "linear-gradient",
        "angle": 90,
        "stops": [
            {"position": 0.0, "color": "#FFFFFF4D"},
            {"position": 1.0, "color": "#FFFF7A00"},
        ],
    }
    recipe = style_recipe_from_graph(graph)
    recipe.engine = "remotion"

    assert page._apply_style_recipe("cue", recipe)
    cue = page._cue_lookup["cue"]
    persisted = page.project.style_recipes[cue.style_id]
    fill = persisted["visualGraph"]["textLayer"]["fill"]
    assert fill["type"] == "linear-gradient"
    assert len(fill["stops"]) == 2
    assert fill["stops"][0]["color"] == "#FFFFFF4D"
    assert fill["stops"][1]["color"] == "#FFFF7A00"
    page.close_page()


def test_solid_alpha_and_rich_shadow_survive_recipe_materialization():
    graph = clean_subtitle_graph()
    graph.motion_graph.tracks = []
    graph.text_layer.fill = {"type": "solid", "color": "#00FFFFFF"}
    graph.text_layer.shadow = {}
    native_recipe = style_recipe_from_graph(graph)
    plan = compile_native_recipe(native_recipe, style_id="recipe-style")
    assert plan.style.primary_color == "#00FFFFFF"

    graph.text_layer.shadow = {
        "enabled": True,
        "color": "#FF000000",
        "opacity": 0.8,
        "offset_x": 12,
        "offset_y": 12,
        "blur_radius": 12,
        "spread": 2,
    }
    recipe = style_recipe_from_graph(graph)

    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=3_000),
        styles=[_style("default", 4), plan.style],
        cues=[StudioCue(
            "cue", 0, 2_000, "0 8 B 中 口 回",
            style_id=plan.style.id,
            base_preset_id=plan.style.id,
        )],
        style_recipes={plan.style.id: recipe.to_dict()},
    )
    project.validate()
    snapshot = build_visual_cue_snapshot(project, "cue")
    assert snapshot.fill["color"] == "#00FFFFFF"
    assert snapshot.shadow["enabled"] is True
    assert snapshot.shadow["blur_radius"] == 12
    assert snapshot.style_recipe["visualGraph"]["textLayer"]["shadow"]["spread"] == 2


def test_appearance_generation_is_monotonic_and_drops_old_fidelity():
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=3_000),
        styles=[_style("default", 4), _style("preset-a", 3)],
        cues=[StudioCue("cue", 0, 2_000, "test")],
    )
    project.validate()
    command = SetCuePresentationCommand(
        project,
        "cue",
        cue_changes={
            "style_id": "preset-a",
            "base_preset_id": "preset-a",
            "appearance_override": {"outline_width": 20.0},
        },
        text="AppearanceTransaction",
    )
    command.redo()
    first_generation = cue_by_id(project, "cue").appearance_generation
    command.undo()
    second_generation = cue_by_id(project, "cue").appearance_generation
    assert first_generation > 0
    assert second_generation > first_generation

    state = AdvancedPreviewStateMachine()
    old = AdvancedPreviewIdentity(
        "cue", "snapshot", "glyph", "motion", "request", 0,
        (640, 360), 30.0, "graph", first_generation,
    )
    generation = state.select(old, cache_hit=False)
    current = AdvancedPreviewIdentity(
        "cue", "snapshot", "glyph", "motion", "request", 0,
        (640, 360), 30.0, "graph", second_generation,
    )
    state.select(current, cache_hit=False)
    assert state.publish_ready(old, generation, "old.png") is False


def test_native_route_revoke_clears_advanced_identity_and_pending_work(monkeypatch):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage.__new__(SubtitleStudioPage)
    page._advanced_preview_state = AdvancedPreviewStateMachine()
    page._advanced_preview_generation = 0
    page._advanced_preview_pending_job = ("old",)
    page._advanced_preview_pending_payload = {"engine": "remotion"}
    page._advanced_preview_pending_force = True
    page._advanced_preview_expected_key = "old-key"
    page._advanced_preview_snapshot = object()
    page._advanced_cue_pixmap = QPixmap(2, 2)
    page._advanced_canvas_source_kind = "fidelity"
    page._advanced_active_cue_id = "cue"
    page._studio_trace = lambda *_args, **_kwargs: None
    identity = AdvancedPreviewIdentity(
        "cue", "snapshot", "glyph", "motion", "request", 0,
        (640, 360), 30.0, "graph", 1,
    )
    page._advanced_preview_state.select(identity, cache_hit=False)
    before = page._advanced_preview_state.generation

    generation = page._revoke_advanced_preview(reason="test_native")

    assert generation > before
    assert page._advanced_preview_state.identity is None
    assert page._advanced_preview_state.phase.value == "FALLBACK_NATIVE"
    assert page._advanced_preview_pending_job is None
    assert page._advanced_preview_pending_payload is None
    assert page._advanced_preview_snapshot is None
    assert page._advanced_cue_pixmap.isNull()
    assert page._advanced_canvas_source_kind == "none"


def test_preset_activation_cancels_stale_style_debounce(tmp_path, monkeypatch):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page.project.media = StudioMedia(path="fixture.mp4", duration_ms=10_000)
    page.project.cues = [StudioCue("cue", 0, 2_000, "trace", style_id="default")]
    page.cue_controller.model_changed()
    page.timeline.reindex_project()
    page.select_cue("cue")
    page._queue_advanced_preview = lambda *_args, **_kwargs: None

    page.style_outline_width.setValue(20)
    assert page._style_debounce_timer.isActive()
    index = page.style_preset.findData("game")
    assert index >= 0
    page.style_preset.setCurrentIndex(index)
    page._preset_activated(index)
    assert not page._style_debounce_timer.isActive()
    cue = page._cue_lookup["cue"]
    assert cue.base_preset_id == "game"
    assert cue.appearance_generation == 1
    page.close_page()


@pytest.mark.parametrize("state", [
    "normal", "hover", "pressed", "checked", "checked-hover", "disabled",
])
def test_timeline_icon_pixmap_matrix_never_returns_null(state: str):
    _app()
    pixmap = cached_icon_pixmap(
        "fa5s.eye",
        "#445566",
        QSize(18, 18),
        device_pixel_ratio=1.5,
        state=state,
    )
    assert not pixmap.isNull()
    image = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painted = paint_cached_icon(
        painter,
        "fa5s.eye",
        "#445566",
        image.rect().adjusted(7, 7, -7, -7),
        state=state,
    )
    painter.end()
    assert not painted.isNull()
    assert any(image.pixelColor(x, y).alpha() > 0 for y in range(32) for x in range(32))


def test_audio_sink_uses_preferred_float_format_and_pcm_signal_starts_sink(monkeypatch):
    _app()
    preferred = QAudioFormat()
    preferred.setSampleRate(44_100)
    preferred.setChannelCount(1)
    preferred.setSampleFormat(QAudioFormat.SampleFormat.Float)

    class Output:
        def id(self):return b"fixture-float-device"

        def isNull(self):
            return False

        def isFormatSupported(self, _audio_format):
            return False

        def preferredFormat(self):
            return preferred

        def description(self):
            return "Fixture Float Device"

    class Sink(QObject):
        stateChanged = Signal(object)

        def __init__(self, _output, audio_format, parent=None):
            super().__init__(parent)
            self.audio_format = audio_format
            self.started_with = None
            self._buffer_size = 0

        def setBufferSize(self, value):
            self._buffer_size = int(value)

        def start(self, device):
            self.started_with = device

        def resume(self):
            return None

        def processedUSecs(self):
            return 0

        def elapsedUSecs(self):
            return 0

        def bytesFree(self):
            return self._buffer_size

        def bufferSize(self):
            return self._buffer_size

        def state(self):
            return SimpleNamespace(name='ActiveState')

        def error(self):
            return SimpleNamespace(name='NoError')

    monkeypatch.setattr(audio_engine.QMediaDevices, "defaultAudioOutput", lambda: Output())
    monkeypatch.setattr(audio_engine, "QAudioSink", Sink)
    worker = audio_engine._AudioEngineWorker(audio_engine.Path("ffmpeg.exe"))
    assert worker._ensure_sink()
    assert worker._output_spec is not None
    assert worker._output_spec.ffmpeg_format == "f32le"
    assert worker._output_spec.sample_rate == 44_100
    worker._active = True
    worker._paused = False
    payload = b"\x00\x00\x00\x3f" * 8_000
    assert worker.device is not None
    worker.device.append(payload, worker.device._generation, threading.Event())
    _app().processEvents()
    assert worker.sink.started_with is worker.device
    assert worker.device.producer_rms > 0.0
