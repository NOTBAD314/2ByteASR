"""The timeline toolbar's zoom slider, between 缩小 and 放大 (2026-10-30, user picked draft B).

Left is the whole project, right is one second (the timeline's own floor).
The scale is logarithmic so each step of the handle zooms by the same factor.
Ctrl+wheel, the buttons and 适应窗口 move the handle through ``view_changed``.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider

from ..i18n import bind_text

STEPS = 1000
MIN_VISIBLE_MS = 1000  # WaveformTimeline.set_visible_window never shows less


def visible_for(value: int, duration_ms: int) -> int:
    duration = max(MIN_VISIBLE_MS, int(duration_ms))
    return round(duration * (MIN_VISIBLE_MS / duration) ** (max(0, min(STEPS, value)) / STEPS))


def value_for(visible_ms: int, duration_ms: int) -> int:
    duration = max(MIN_VISIBLE_MS, int(duration_ms))
    if duration <= MIN_VISIBLE_MS:
        return 0
    visible = max(MIN_VISIBLE_MS, min(duration, int(visible_ms)))
    return round(math.log(duration / visible) / math.log(duration / MIN_VISIBLE_MS) * STEPS)


class TimelineZoomSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("timelineZoomSlider")
        self.setRange(0, STEPS)
        self.setPageStep(STEPS // 10)
        self.setFixedWidth(72)
        # Arrow keys and Space stay the Studio's shortcuts, as with the volume slider.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bind_text(self, '时间轴缩放：向左看到更多，向右放大（也可以 Ctrl+滚轮）', property='toolTip')
        self._timeline = None
        self.setEnabled(False)
        self.valueChanged.connect(self._apply)

    def attach(self, timeline) -> None:
        self._timeline = timeline
        timeline.view_changed.connect(self.sync)
        self.sync()

    def sync(self) -> None:
        timeline = self._timeline
        duration = timeline._duration_ms() if timeline is not None else 0
        self.setEnabled(duration > MIN_VISIBLE_MS)
        value = value_for(timeline.visible_duration_ms, duration) if duration > MIN_VISIBLE_MS else 0
        # One step of rounding is the drag itself coming back; leave the handle where it is.
        if abs(value - self.value()) > 1:
            self.blockSignals(True)
            self.setValue(value)
            self.blockSignals(False)

    def _apply(self, value: int) -> None:
        timeline = self._timeline
        if timeline is None or timeline._duration_ms() <= MIN_VISIBLE_MS:
            return
        from time import perf_counter
        timeline.hold_manual_view()
        visible = visible_for(value, timeline._duration_ms())
        center = timeline.visible_start_ms + timeline.visible_duration_ms // 2
        timeline.set_visible_window(center - visible // 2, visible)
