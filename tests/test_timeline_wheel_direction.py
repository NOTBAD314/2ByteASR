"""Wheel direction includes Qt's Alt horizontal-axis translation."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline


@pytest.fixture
def timeline():
    app = QApplication.instance() or QApplication([])
    widget = WaveformTimeline()
    widget.resize(1000, 350)
    widget.set_project(SubtitleProject(media=StudioMedia(path="missing.mp4", duration_ms=120_000),
                                       cues=[StudioCue("a", 0, 120_000, "Wheel fixture")]))
    widget.set_visible_window(40_000, 10_000)
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def wheel(widget, angle=(0, 0), pixel=(0, 0), modifiers=Qt.NoModifier):
    point = QPointF(500, 150)
    event = QWheelEvent(point, point, QPoint(*pixel), QPoint(*angle),
                        Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event


@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.AltModifier, Qt.ShiftModifier])
@pytest.mark.parametrize("axis", ["vertical", "horizontal", "pixel_y", "pixel_x"])
def test_pan_both_directions_and_reverse(timeline, modifiers, axis):
    def turn(delta):
        return wheel(timeline,
                     angle=(0, delta) if axis == "vertical" else (delta, 0) if axis == "horizontal" else (0, 0),
                     pixel=(0, delta) if axis == "pixel_y" else (delta, 0) if axis == "pixel_x" else (0, 0),
                     modifiers=modifiers)
    positions = [timeline.visible_start_ms]
    for delta in (120, 120, -120, -120):
        assert turn(delta).isAccepted()
        positions.append(timeline.visible_start_ms)
    assert positions == [40_000, 38_800, 37_600, 38_800, 40_000]
    assert timeline.visible_duration_ms == 10_000
    assert timeline.playhead_ms == 0


@pytest.mark.parametrize("modifiers", [Qt.NoModifier, Qt.AltModifier, Qt.ControlModifier])
def test_zero_delta_does_nothing(timeline, modifiers):
    wheel(timeline, modifiers=modifiers)
    assert (timeline.visible_start_ms, timeline.visible_duration_ms) == (40_000, 10_000)


def test_pan_clamps_and_returns_from_both_ends(timeline):
    for start, outward, inward, returned in [(0, 120, -120, 1200), (110_000, -120, 120, 108_800)]:
        timeline.set_visible_window(start, 10_000)
        wheel(timeline, angle=(outward, 0), modifiers=Qt.AltModifier)
        assert timeline.visible_start_ms == start
        wheel(timeline, angle=(inward, 0), modifiers=Qt.AltModifier)
        assert timeline.visible_start_ms == returned


def test_control_zoom_keeps_existing_factors_and_precedence(timeline):
    wheel(timeline, angle=(0, 120), modifiers=Qt.ControlModifier)
    assert timeline.visible_duration_ms == 8000
    wheel(timeline, angle=(0, -120), modifiers=Qt.ControlModifier)
    assert timeline.visible_duration_ms == 10_000
    wheel(timeline, angle=(120, 0), modifiers=Qt.ControlModifier | Qt.AltModifier)
    assert timeline.visible_duration_ms == 8000


def test_vertical_angle_has_priority_without_double_counting(timeline):
    wheel(timeline, angle=(-120, 120), pixel=(-20, -20), modifiers=Qt.AltModifier)
    assert timeline.visible_start_ms == 38_800
