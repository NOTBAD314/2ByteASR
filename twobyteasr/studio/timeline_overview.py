"""Review markers aligned with the timeline's current visible interval."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..i18n_widgets import bind_text


class TimelineOverview(QWidget):
    HEIGHT = 18
    REFRESH_MS = 250

    def __init__(self, page, timeline, parent=None):
        super().__init__(parent)
        self.page = page
        self.timeline = timeline
        self.setObjectName("timelineOverview")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '当前时间段的复核标记，黄色为建议确认，红色为需要检查。随时间轴缩放和滚动，点击或拖动定位此段内的位置', property='toolTip')
        self._markers: QPixmap | None = None
        self._marker_key = None
        self._painted_state = None
        self._dragging = False
        self._drag_window = None
        timeline.view_changed.connect(self.update)
        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------------------------------------------------------- geometry
    def _track(self) -> QRectF:
        left = float(self.timeline.TRACK_HEADER_WIDTH)
        right = float(self.width() - self.timeline.vertical_scrollbar.width())
        return QRectF(left, 3.0, max(1.0, right - left), self.height() - 6.0)

    def _x(self, ms: float) -> float:
        return self.timeline._time_to_x(ms)

    def _ms(self, x: float) -> int:
        track = self._track()
        start, duration = self._drag_window or (
            self.timeline.visible_start_ms, self.timeline.visible_duration_ms)
        fraction = max(0.0, min(1.0, (x - track.left()) / track.width()))
        return round(start + fraction * duration)

    # ---------------------------------------------------------------- markers
    def _cues(self):
        project = getattr(self.page, "project", None)
        if project is None:
            return None, ()
        return project, self.timeline.visible_cues()

    def _build_markers(self, project, cues, key) -> None:
        from ..design.studio_theme import studio_status_colors
        from ..design.timeline_theme import timeline_palette
        from ..subtitle_rules.studio_review import cached_review_risks
        from .studio_cue_table import _cue_review_level
        track = self._track()
        pixmap = QPixmap(max(1, int(track.width())), max(1, int(track.height())))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        palette = timeline_palette()
        colors = studio_status_colors()
        plain = QColor(palette.header_name)
        plain.setAlpha(70)
        warn = QColor(colors["pending"][1])
        issue = QColor(colors["issue"][1])
        risks = cached_review_risks(project)
        width = pixmap.width()
        flagged = []
        for cue in cues:
            x0 = max(0, int(self._x(cue.start_ms) - track.left()))
            x1 = min(width, max(x0 + 1, int(self._x(cue.end_ms) - track.left())))
            level = _cue_review_level(project, cue, risks)
            if level == "confident":
                painter.fillRect(x0, pixmap.height() // 3, x1 - x0, pixmap.height() // 3, plain)
            else:
                flagged.append((x0, x1, issue if level == "high" else warn))
        for x0, x1, color in flagged:  # on top, at least 2 px so they stay visible
            painter.fillRect(x0, 0, max(2, x1 - x0), pixmap.height(), color)
        painter.end()
        self._markers = pixmap
        self._marker_key = key

    def _key(self, project, cues=()):
        # Data revisions are independent of transport. Never enumerate cues or
        # rebuild the derived review view for a cursor-only paint/poll.
        session = getattr(self.page, 'session', None)
        revision = (getattr(session, 'generation', 0), id(getattr(project, '_qc_result', None)),
                    id(project.studio_state.get('current_issue_decisions')),
                    id(getattr(project, '_review_risks_cache', None)))
        return (id(project), revision, self.timeline.visible_start_ms,
                self.timeline.visible_duration_ms, self._track().width())

    def _tick(self) -> None:
        if not self.isVisible():
            return
        project = getattr(self.page, 'project', None)
        if project is not None and self._key(project) != self._marker_key:
            self._markers = None
            self.update()
            return
        t = self.timeline
        state = (t.playhead_ms, t.visible_start_ms, t.visible_duration_ms)
        if state != self._painted_state:
            self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        from ..design.timeline_theme import timeline_palette
        palette = timeline_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track()
        ground = QColor(palette.header)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ground)
        painter.drawRoundedRect(track, 3, 3)
        project = getattr(self.page, 'project', None)
        if project is not None:
            key = self._key(project)
            if self._markers is None or key != self._marker_key:
                _, cues = self._cues()
                self._build_markers(project, cues, key)
            painter.drawPixmap(track.topLeft(), self._markers)
            t = self.timeline
            accent = QColor(palette.playhead)
            painter.setPen(QPen(accent, 1.2))
            x = self._x(t.playhead_ms)
            if track.left() <= x <= track.right():
                painter.drawLine(int(x), 0, int(x), self.height())
            self._painted_state = (t.playhead_ms, t.visible_start_ms, t.visible_duration_ms)
        painter.end()

    # ---------------------------------------------------------------- input
    def _jump(self, x: float) -> None:
        t = self.timeline
        center = self._ms(x)
        duration = self._drag_window[1] if self._drag_window else t.visible_duration_ms
        t.set_visible_window(center - duration // 2, duration)
        self.update()

    def mousePressEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton and self.page.project is not None
                and self._track().contains(event.position())):
            self._dragging = True
            self._drag_window = (self.timeline.visible_start_ms, self.timeline.visible_duration_ms)
            self._jump(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._jump(event.position().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        self._drag_window = None
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._markers = None
