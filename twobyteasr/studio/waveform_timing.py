"""Cue timing gestures over the existing waveform, in project milliseconds."""
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QApplication

from ..timeline.timeline_cue_gesture import CueInterval


@dataclass
class _Gesture:
    project: object
    cue: object
    origin: QPointF
    button: Qt.MouseButton
    edge: str
    moved: bool = False


class WaveformTiming:
    def __init__(self, timeline):
        self.timeline = timeline
        self.enabled = False
        self.gesture = None

    def cue(self):
        timeline = self.timeline
        cue = timeline._timeline_cue_by_id.get(timeline.selected_id)
        if cue is None or cue.speaker_id in timeline.locked_speakers or len(timeline.selected_ids) > 1:
            return None
        return cue

    def waveform_at(self, point):
        timeline = self.timeline
        if not timeline.waveform_visible or not self.bounds().contains(point):
            return None
        for row in timeline._audio_track_rects().values():
            if row.contains(point):
                return row
        wave = timeline._track_layout()[2]
        return wave if wave.contains(point) else None

    def bounds(self):
        timeline = self.timeline
        return QRectF(timeline.TRACK_HEADER_WIDTH, timeline.RULER_HEIGHT,
                      timeline._content_right() - timeline.TRACK_HEADER_WIDTH,
                      timeline._canvas_bottom() - timeline.RULER_HEIGHT)

    def press(self, event):
        if not self.enabled or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        timeline = self.timeline
        cue = self.cue()
        point = event.position()
        if cue is None or not self.waveform_at(point.toPoint()):
            return False
        timeline.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.MouseButton.MiddleButton:
            timeline.seek_requested.emit(timeline._x_to_time(point.x()) / 1000)
            return True
        if event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            return False
        edge = ""
        if event.button() == Qt.MouseButton.LeftButton:
            a = abs(point.x() - timeline._time_to_x(cue.start_ms))
            b = abs(point.x() - timeline._time_to_x(cue.end_ms))
            if min(a, b) <= 7:
                edge = "start" if a <= b else "end"
        self.gesture = _Gesture(timeline.project, cue, QPointF(point), event.button(), edge)
        timeline.interaction_changed.emit(True)
        return True

    def interval(self, point):
        gesture = self.gesture
        timeline = self.timeline
        cue = gesture.cue
        at = timeline._bounded_time_ms(timeline._x_to_time(point.x()))
        start, end = cue.start_ms, cue.end_ms
        if gesture.button == Qt.MouseButton.RightButton or gesture.edge == "end":
            end = max(start + 50, at)
        elif gesture.moved and not gesture.edge:
            origin = timeline._bounded_time_ms(timeline._x_to_time(gesture.origin.x()))
            start, end = sorted((origin, at))
        else:
            start = min(at, end - 50)
        if 0 <= start and start + 50 <= end <= timeline._duration_ms():
            return CueInterval(start, end, cue.speaker_id)
        return None

    def move(self, event):
        gesture = self.gesture
        if gesture is None:
            return False
        if gesture.button == Qt.MouseButton.RightButton:
            return True
        if (event.position() - gesture.origin).manhattanLength() >= QApplication.startDragDistance():
            gesture.moved = True
        if gesture.moved:
            interval = self.interval(event.position())
            if interval is not None:
                self.timeline._timing_preview[gesture.cue.id] = interval
                self.timeline.update()
        return True

    def release(self, event):
        gesture = self.gesture
        if gesture is None or gesture.button != event.button():
            return False
        timeline = self.timeline
        current = self.cue()
        interval = self.interval(event.position())
        self.cancel()
        if (interval is not None and current is gesture.cue and timeline.project is gesture.project
                and (interval.start_ms, interval.end_ms) != (current.start_ms, current.end_ms)):
            timeline.timing_edit_committed.emit({current.id: interval})
        return True

    def cancel(self):
        if self.gesture is None:
            return False
        self.timeline._timing_preview.pop(self.gesture.cue.id, None)
        self.gesture = None
        self.timeline.interaction_changed.emit(False)
        self.timeline.update()
        return True

    def paint(self, painter, palette):
        if not self.enabled or not self.timeline.waveform_visible:
            return
        timeline = self.timeline
        cue = self.cue()
        if cue is None:
            return
        interval = timeline._timing_preview.get(cue.id, cue)
        rows = list(timeline._audio_track_rects().values())
        if not rows:
            rows = [timeline._track_layout()[2]]
        left, right = (timeline._time_to_x(value) for value in (interval.start_ms, interval.end_ms))
        color = QColor(palette.clip_selected_border)
        fill = QColor(color)
        fill.setAlpha(45)
        painter.save()
        painter.setClipRect(self.bounds())
        painter.setPen(QPen(color, 2))
        for row in rows:
            painter.fillRect(QRectF(left, row.top(), right - left, row.height()), fill)
            for edge in (left, right):
                painter.drawLine(QPointF(edge, row.top()), QPointF(edge, row.bottom()))
        painter.restore()
