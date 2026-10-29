"""P1: the WaveformTimeline must follow the application theme."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skipif(
    pytest.importorskip("PySide6", reason="PySide6 required") is None,
    reason="PySide6 required",
)

from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject  # noqa: E402
from twobyteasr.studio.studio_ui import WaveformTimeline, _speaker_color  # noqa: E402
from twobyteasr.design.theme_manager import apply_application_theme  # noqa: E402
from twobyteasr.design.timeline_theme import TIMELINE_PALETTES, mix, rgba_color, timeline_palette  # noqa: E402


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def _project() -> SubtitleProject:
    return SubtitleProject(
        media=StudioMedia(path="D:/synthetic.mp4", duration_ms=10_000),
        speakers=[StudioSpeaker("S01", "玩家")],
        cues=[StudioCue("a", 0, 2000, "a", speaker_id="S01")],
    )


def test_p3_every_theme_has_full_timeline_palette():
    required = {
        "background", "header", "ruler", "grid_major", "grid_minor",
        "track_background", "track_alternate", "track_header", "playhead",
        "time_label", "clip_text", "clip_selected_border", "waveform",
        "waveform_background", "speaker_accents",
    }
    from twobyteasr.design.ui_theme import THEMES
    assert set(TIMELINE_PALETTES) == set(THEMES)
    for key, palette in TIMELINE_PALETTES.items():
        missing = required - {
            field_name for field_name in palette.__dataclass_fields__
        }
        assert not missing, f"{key} missing tokens: {missing}"
        assert palette.speaker_accents, f"{key} needs speaker accents"


def test_p3_dark_palettes_are_dark_and_readable():
    for key in ("plum", "lavender", "slate", "grape"):
        palette = timeline_palette(key)
        assert palette.dark
        background = mix(palette.background, "#000000", 0.0)
        text = mix(palette.clip_text, "#000000", 0.0)
        luminance_bg = (0.299 * background.red() + 0.587 * background.green() + 0.114 * background.blue())
        luminance_text = (0.299 * text.red() + 0.587 * text.green() + 0.114 * text.blue())
        assert luminance_text - luminance_bg > 110, f"{key} clip text lacks contrast"


def test_p3_timeline_repaints_with_theme_switch(qtbot=None):
    app = _app()
    apply_application_theme(app=app, key="plum")
    timeline = WaveformTimeline()
    timeline.resize(900, 320)
    timeline.set_project(_project())
    timeline.set_visible_window(0, 8000)
    assert timeline._timeline_palette().key == "plum"
    apply_application_theme(app=app, key="slate")
    timeline.refresh_theme_palette()
    assert timeline._timeline_palette().key == "slate"
    timeline.deleteLater()
    apply_application_theme(app=app, key="warm")


def test_p3_speaker_color_uses_theme_fallbacks():
    project = _project()
    plum_color = _speaker_color(project, "S01", timeline_palette("plum"))
    plum_fallbacks = {color.lower() for color in timeline_palette("plum").speaker_accents}
    assert plum_color.name().lower() in plum_fallbacks
    warm_color = _speaker_color(project, "S01", timeline_palette("warm"))
    warm_fallbacks = {color.lower() for color in timeline_palette("warm").speaker_accents}
    assert warm_color.name().lower() in warm_fallbacks


def test_p3_rgba_token_parser():
    color = rgba_color("rgba(244,124,104,70)")
    assert (color.red(), color.green(), color.blue(), color.alpha()) == (244, 124, 104, 70)
    plain = rgba_color("#cf4b43")
    assert plain.name() == "#cf4b43"


def test_p5_preview_quality_tiers():
    """Draft/Balanced/High map to 640/960/1280; legacy values still resolve."""
    app = _app()
    from PySide6.QtWidgets import QComboBox

    from twobyteasr.studio.studio_ui import SubtitleStudioPage

    page = SubtitleStudioPage()
    try:
        # Pin the preview surface so the Auto tier is deterministic.
        page.advanced_preview_image.setFixedSize(320, 180)
        combo = QComboBox()
        for label, value in (
            ("自动", "auto"), ("草稿 640", "draft"), ("均衡 960", "balanced"),
            ("高质量 1280", "high"), ("legacy low", "low"), ("legacy medium", "medium"),
        ):
            combo.addItem(label, value)
        page.advanced_preview_quality = combo
        combo.setCurrentIndex(combo.findData("auto"))
        assert page._advanced_preview_size() == (640, 360)
        combo.setCurrentIndex(combo.findData("draft"))
        assert page._advanced_preview_size() == (640, 360)
        combo.setCurrentIndex(combo.findData("balanced"))
        assert page._advanced_preview_size() == (960, 540)
        combo.setCurrentIndex(combo.findData("high"))
        assert page._advanced_preview_size() == (1280, 720)
        # Legacy persisted values keep working.
        combo.setCurrentIndex(combo.findData("medium"))
        assert page._advanced_preview_size() == (960, 540)
        combo.setCurrentIndex(combo.findData("low"))
        assert page._advanced_preview_size() == (640, 360)
    finally:
        page.close_page()
