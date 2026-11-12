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
        import math
        extent=shadow.boundingRectFor(QRectF(0,0,100,100))
        self.layout().setContentsMargins(math.ceil(-extent.left())+1,math.ceil(-extent.top())+1,
                                        math.ceil(extent.right()-100)+1,math.ceil(extent.bottom()-100)+1)
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
        self._subtitle_x = content.center().x()
        draft = getattr(page, '_caption_draft', None)
        try:
            prepared = page._prepared_caption(draft.target.render_id) if draft is not None else None
            if prepared is not None:
                point = mapper.subtitle_to_preview(QPointF(prepared.snapshot.position_x, prepared.snapshot.position_y))
                if content.top() <= point.y() <= content.bottom(): bottom = point.y()
                self._subtitle_x = point.x()
            elif draft is not None:
                overlay = getattr(page, 'position_overlay', None)
                if overlay is not None:
                    point = mapper.subtitle_to_preview(QPointF(overlay.position_x,overlay.position_y))
                    if content.top() <= point.y() <= content.bottom(): bottom = point.y()
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
        if getattr(self, '_fitting', False): return
        self._fitting = True
        try:
            self._fit_component()
        finally:
            self._fitting = False

    def _fit_component(self):
        page, panel = self.page, self.panel
        anchor = page.video_overlay_host
        screen = anchor.screen()
        workspace = page.window().rect()
        workspace.moveTopLeft(page.window().mapToGlobal(QPoint()))
        if screen is not None: workspace = workspace.intersected(screen.availableGeometry())
        workspace.adjust(8, 8, -8, -8)
        content, subtitle_bottom = self._subtitle_band(anchor)
        top_left = anchor.mapToGlobal(QPoint())
        from PySide6.QtCore import QRect
        video = QRect(anchor.rect()); video.moveTopLeft(top_left)
        bounds = workspace.intersected(video)
        if bounds.width() < 160 or bounds.height() < 100: bounds = workspace
        margins = self.layout().contentsMargins()
        side = margins.left()+margins.right()
        width = min(bounds.width(), panel.preferred_width(max(120, min(880, bounds.width())-side),
                          min(self._covered_text_width(), bounds.width()))+side)
        draft = getattr(page, '_caption_draft', None)
        session = getattr(draft, 'edit_session_id', None)
        if session != getattr(self, '_layout_session', None):
            self._layout_session = session
            self._anchor_fraction = max(0., min(1., (subtitle_bottom-content.top())/max(1., content.height())))
            self._anchor_x_fraction = max(0., min(1., (self._subtitle_x-content.left())/max(1., content.width())))
            panel.set_strip_above(False)
        subtitle_center = top_left.y()+content.top()+content.height()*getattr(self, '_anchor_fraction', .93)-panel.editor.fontMetrics().lineSpacing()*.75
        self.setFixedWidth(width)
        panel.prepare_geometry(width-side, bounds.height()-margins.top()-margins.bottom())
        self.layout().activate()
        height = max(self.sizeHint().height(), self.layout().totalHeightForWidth(width) if self.layout().hasHeightForWidth() else 0)
        # A small/fullscreen preview can genuinely be shorter than the card.
        # Use the available workspace as an explicit fallback and a bounded
        # candidate viewport; key operations remain reachable.
        fallback = height > bounds.height()
        if fallback:
            bounds = workspace
            panel.prepare_geometry(width-side, bounds.height()-margins.top()-margins.bottom())
            self.layout().activate()
            height = max(self.sizeHint().height(), self.layout().totalHeightForWidth(width) if self.layout().hasHeightForWidth() else 0)
        height = min(bounds.height(), height)
        self.resize(width, height); self.layout().activate()
        panel.layout().activate(); panel.place_bubble()
        centre = panel.editor.mapTo(self, QPoint(0, panel.editor.height()//2)).y()
        ideal = int(subtitle_center-centre)
        # Retain the session direction. Flip only when the complete anchored
        # component cannot fit and the opposite orientation really can.
        if not bounds.top() <= ideal <= bounds.bottom()-height+1:
            old = panel.strip_above()
            displacement = panel.strip.height()-panel.lane.height()
            alternate = int(subtitle_center-(centre-displacement if old else centre+displacement))
            if bounds.top()+6 <= alternate and alternate+height <= bounds.bottom()-5:
                panel.set_strip_above(not old)
                panel.prepare_geometry(width-side, bounds.height()-margins.top()-margins.bottom())
                self.layout().activate(); panel.layout().activate()
                ideal = int(subtitle_center-panel.editor.mapTo(self,QPoint(0,panel.editor.height()//2)).y())
        x = max(bounds.left(), min(int(top_left.x()+content.left()+content.width()*getattr(self, '_anchor_x_fraction', .5)-width/2), bounds.right()-width+1))
        y = max(bounds.top(), min(ideal, bounds.bottom()-height+1))
        self.setProperty('workspaceFallback', fallback)
        if self.pos() != QPoint(x,y): self.move(x,y)
        panel.place_bubble()

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
        self._fit_timer.stop()
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
