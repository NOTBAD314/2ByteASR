"""Owned, nonmodal tool window above native video, outside the Studio layout."""
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
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
        layout.setContentsMargins(9, 9, 9, 12)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_to_workspace)

    def set_panel(self, panel):
        self.layout().addWidget(panel)
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 85))
        panel.setGraphicsEffect(shadow)
        self.panel = panel

    def schedule_fit(self):
        if self.isVisible() and not self._fit_timer.isActive():
            self._fit_timer.start(0)

    def fit_to_workspace(self):
        page = self.page
        anchor = page.video_overlay_host
        screen = page.screen()
        bounds = page.window().rect()
        bounds.moveTopLeft(page.window().mapToGlobal(QPoint()))
        if screen is not None:
            bounds = bounds.intersected(screen.availableGeometry())
        bounds.adjust(8, 8, -8, -8)
        width = max(240, min(820, max(520, anchor.width() - 40), bounds.width()))
        self.setFixedWidth(width)
        self.panel.resize_editor()
        self.layout().activate()
        height_hint = self.sizeHint().height()
        if self.layout().hasHeightForWidth():
            height_hint = max(height_hint,self.layout().totalHeightForWidth(width))
        height = min(bounds.height(), height_hint)
        self.resize(width, height)
        self.layout().activate()
        # The lower edge sits just above the first timeline subtitle row,
        # between on-video captions and track captions. Suggestions may grow
        # upward over the picture; neither expansion nor follow resizes mpv.
        origin = anchor.mapToGlobal(QPoint(anchor.width() // 2, 0))
        track_top = page.timeline.mapToGlobal(QPoint(0, page.timeline.RULER_HEIGHT)).y()
        x = max(bounds.left(), min(origin.x() - width // 2, bounds.right() - width + 1))
        y = max(bounds.top(), min(track_top - 8 - height, bounds.bottom() - height + 1))
        if self.pos() != QPoint(x, y):
            self.move(x, y)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and hasattr(self, '_fit_timer'):
            self.schedule_fit()
        return result

    def closeEvent(self, event):
        if self.page._end_caption_editor(keep_open=False):
            event.accept()
        else:
            event.ignore()
