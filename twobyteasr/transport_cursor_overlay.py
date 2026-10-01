"""A paint-only child for the timeline transport cursor; owns no timer or time."""
from time import perf_counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from . import playback_probe as probe


class TransportCursorOverlay(QWidget):
    def __init__(self, timeline):
        super().__init__(timeline)
        self.timeline = timeline
        self.setObjectName('timelineTransportCursor')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(timeline.rect())
        self.show()

    def paintEvent(self, event):
        timeline = self.timeline
        started = 0.
        if probe.ENABLED and event.region().intersects(timeline._transport_cursor_region(timeline.playhead_ms)):
            started = perf_counter()
        if started:
            probe.mark('cursor_paint_begin', project_ms=timeline.playhead_ms,
                       dirty_width=event.rect().width(), dirty_height=event.rect().height())
        painter = QPainter(self)
        painter.setFont(timeline.font())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        timeline._paint_transport_cursor(painter, timeline._timeline_palette())
        painter.end()
        if started:
            probe.EVENTS.append(dict(at=started, stage='playhead_paint',
                ms=(perf_counter()-started)*1000, project_ms=timeline.playhead_ms,
                pixel_x=round(timeline._time_to_x(timeline.playhead_ms))))
            probe.mark('cursor_paint_end', project_ms=timeline.playhead_ms)
