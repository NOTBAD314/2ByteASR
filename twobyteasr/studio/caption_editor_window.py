"""Owned, nonmodal tool window above native video, outside the Studio layout.

2026-11-09 (user): the editor sits on the picture, over the subtitle being
edited, instead of a card above the timeline. It stays a separate top-level
tool window: a Qt child over mpv's native surface is what broke earlier
on-video editing attempts (hidden video, stale GDI pixels).
"""
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGraphicsDropShadowEffect


class CaptionEditorWindow(QWidget):
    def __init__(self, page):
        super().__init__(page, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.page = page
        self.setObjectName('captionEditorWindow')
        self.setProperty('uiZoomExclude', True)  # Studio uses OS DPI, not home reading zoom.
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 18)  # room for the card shadow
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_workspace)
        self._cut_timer = QTimer(self)
        self._cut_timer.setInterval(120)
        self._cut_timer.timeout.connect(self._refresh_cut_status)

    def set_panel(self, panel):
        self.layout().addWidget(panel)
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(0, 0, 0, 115))
        panel.setGraphicsEffect(shadow)
        self.panel = panel

    def schedule_fit(self):
        if self.isVisible() and not self._fit_timer.isActive():
            self._fit_timer.start(0)

    def _subtitle_band(self, anchor):
        """(content rect, subtitle bottom y) in anchor coordinates."""
        from .studio_geometry import SubtitleCoordinateMapper
        page = self.page
        project = getattr(page, 'project', None)
        settings = project.render_settings if project is not None else {}
        media = project.media if project is not None else None
        mapper = SubtitleCoordinateMapper(
            QRectF(anchor.rect()),
            int(settings.get('play_res_x', 1920) or 1920), int(settings.get('play_res_y', 1080) or 1080),
            int(getattr(media, 'width', 0) or 1920), int(getattr(media, 'height', 0) or 1080))
        content = mapper.video_content_rect
        bottom = content.bottom() - content.height() * 0.07
        overlay = getattr(page, 'position_overlay', None)
        try:
            if overlay is not None and int(overlay.alignment) in (1, 2, 3):
                y = mapper.subtitle_to_preview(QPointF(overlay.position_x, overlay.position_y)).y()
                if content.top() + content.height() * 0.3 <= y <= content.bottom():
                    bottom = y
        except (TypeError, ValueError, AttributeError):
            pass
        return content, bottom

    def _covered_text_width(self):
        """Width of the rendered subtitle the card must cover, if known."""
        overlay = getattr(self.page, 'position_overlay', None)
        try:
            return max(0, int(overlay._rendered_text_rect().width())) if overlay is not None else 0
        except Exception:
            return 0

    def fit_to_workspace(self):
        page = self.page
        anchor = page.video_overlay_host
        screen = page.screen()
        bounds = page.window().rect()
        bounds.moveTopLeft(page.window().mapToGlobal(QPoint()))
        if screen is not None:
            bounds = bounds.intersected(screen.availableGeometry())
        bounds.adjust(8, 8, -8, -8)
        content, subtitle_bottom = self._subtitle_band(anchor)
        margins = self.layout().contentsMargins()
        side = margins.left() + margins.right()
        widest = int(max(240, min(880, max(420, content.width() - 24), bounds.width())))
        # 2026-11-10 字卡: the window is as wide as the card, not the video.
        width = self.panel.preferred_width(widest - side, min(self._covered_text_width(), widest)) + side
        self.setFixedWidth(width)
        self.panel.resize_editor()
        top_left = anchor.mapToGlobal(QPoint(0, 0))
        editor = self.panel.editor
        line = editor.fontMetrics().lineSpacing()
        subtitle_center = top_left.y() + subtitle_bottom - line * 0.75
        video_bottom = top_left.y() + anchor.height()
        track_top = page.timeline.mapToGlobal(QPoint(0, page.timeline.RULER_HEIGHT)).y()
        floor = min(video_bottom, track_top - 4, bounds.bottom() + 1)
        # The strip hangs under the card, between the subtitle and the
        # tracks; with no room there it goes above the card instead.
        below = (editor.height() / 2 + self.panel.face.layout().contentsMargins().bottom()
                 + self.panel.strip.sizeHint().height() + margins.bottom())
        self.panel.set_strip_above(floor - subtitle_center < below)
        self.layout().activate()
        height_hint = self.sizeHint().height()
        if self.layout().hasHeightForWidth():
            height_hint = max(height_hint,self.layout().totalHeightForWidth(width))
        height = min(bounds.height(), height_hint)
        self.resize(width, height)
        self.layout().activate()
        # Lay the text field over the subtitle line: its centre goes where
        # the subtitle's centre is. The window never reaches below the video
        # (the tracks stay visible) and grows upward over the picture.
        editor_center = editor.mapTo(self, QPoint(0, editor.height() // 2)).y()
        lowest = floor - height
        x = int(top_left.x() + content.center().x() - width / 2)
        x = max(bounds.left(), min(x, bounds.right() - width + 1))
        y = int(subtitle_center - editor_center)
        y = max(max(bounds.top(), top_left.y()), min(y, lowest))
        if self.pos() != QPoint(x, y):
            self.move(x, y)

    def _refresh_cut_status(self):
        page = self.page
        draft = getattr(page, '_caption_draft', None)
        cue = None
        if draft is not None and getattr(page, 'project', None) is not None:
            try:
                cue = draft.target.resolve(page.project)
            except Exception:
                cue = None
        self.panel.update_cut_status(int(page.timeline.playhead_ms),
                                     cue.start_ms if cue is not None else None,
                                     cue.end_ms if cue is not None else None)

    def showEvent(self, event):
        super().showEvent(event)
        self._cut_timer.start()

    def hideEvent(self, event):
        self._cut_timer.stop()
        super().hideEvent(event)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, '_fit_timer'):
            self.schedule_fit()
        return result

    def closeEvent(self, event):
        self.page._cancel_bound_caption_editor(trigger='window_close')
        event.accept()
