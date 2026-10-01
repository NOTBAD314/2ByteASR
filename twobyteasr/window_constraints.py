"""Qt logical-coordinate window bounds and narrow, explicit resize hit targets."""
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLayout, QSizeGrip


def available_rect(widget, *, within_parent=False):
    screen = widget.screen() or QApplication.primaryScreen()
    rect = QRect(screen.availableGeometry())
    parent = widget.parentWidget()
    if within_parent and parent is not None and parent.isVisible():
        host = parent.window()
        visible = QRect(host.mapToGlobal(QPoint()), host.size()).intersected(rect)
        if visible.width() >= 280 and visible.height() >= 200:
            rect = visible
    return rect.adjusted(8, 8, -8, -8)


def constrain(widget, *, within_parent=False):
    if widget.isMaximized() or widget.isMinimized():
        return
    bounds = available_rect(widget, within_parent=within_parent)
    if bounds.isEmpty():
        return
    layout = widget.layout()
    if layout:
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    widget.setMinimumSize(min(widget.minimumWidth(), bounds.width()),
                          min(widget.minimumHeight(), bounds.height()))
    frame = widget.frameGeometry()
    extra_w = max(0, frame.width()-widget.width())
    extra_h = max(0, frame.height()-widget.height())
    widget.resize(min(widget.width(), max(1, bounds.width()-extra_w)),
                  min(widget.height(), max(1, bounds.height()-extra_h)))
    frame = widget.frameGeometry()
    x = max(bounds.left(), min(frame.left(), bounds.right()-frame.width()+1))
    y = max(bounds.top(), min(frame.top(), bounds.bottom()-frame.height()+1))
    widget.move(widget.pos()+QPoint(x-frame.left(), y-frame.top()))


class WindowBounds(QObject):
    def __init__(self, widget, *, within_parent=False, resizable=True):
        super().__init__(widget)
        self.widget, self.within_parent = widget, within_parent
        self.pending = False
        self.grip = None
        widget.installEventFilter(self)
        parent = widget.parentWidget()
        if parent:
            parent.window().installEventFilter(self)
        self.grip = QSizeGrip(widget) if resizable else None
        for screen in QApplication.screens():
            screen.availableGeometryChanged.connect(self.schedule)
        self.schedule()

    def schedule(self, *args):
        if not self.pending:
            self.pending = True
            QTimer.singleShot(0, self.apply)

    def apply(self):
        from shiboken6 import isValid
        if not hasattr(self, 'widget') or not isValid(self.widget):
            return
        self.pending = False
        constrain(self.widget, within_parent=self.within_parent)
        backdrop = getattr(self.widget, '_modal_backdrop', None)
        if backdrop is not None and self.widget.parentWidget() is not None:
            backdrop.setGeometry(self.widget.parentWidget().window().rect())
        if self.grip:
            self.grip.setGeometry(max(0,self.widget.width()-16), max(0,self.widget.height()-16), 16, 16)
            self.grip.raise_()

    def eventFilter(self, obj, event):
        if not hasattr(self, 'widget') or not hasattr(self, 'grip'):
            return False
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.ScreenChangeInternal):
            self.schedule()
        # Border resize is limited to the outer 5 logical pixels. The rest of
        # the content remains interactive; the visible corner grip works too.
        if obj is self.widget and self.grip and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            p = event.position()
            edges = Qt.Edge(0)
            if p.x() < 5: edges |= Qt.LeftEdge
            if p.x() >= obj.width()-5: edges |= Qt.RightEdge
            if p.y() < 5: edges |= Qt.TopEdge
            if p.y() >= obj.height()-5: edges |= Qt.BottomEdge
            if edges and obj.windowHandle() and obj.windowHandle().startSystemResize(edges):
                return True
        return False


def install_window_bounds(widget, **options):
    if not hasattr(widget, '_window_bounds'):
        widget._window_bounds = WindowBounds(widget, **options)
    return widget._window_bounds


class EmbeddedCardInteraction(QObject):
    """Drag a card inside its overlay; never move the application's HWND."""
    def __init__(self, card, header):
        super().__init__(card)
        from PySide6.QtWidgets import QFrame
        self.card, self.header = card, header
        self.origin = None
        self.edges = Qt.Edge(0)
        self.grip = QFrame(card)
        self.grip.setObjectName('modalResizeGrip')
        self.grip.setStyleSheet('QFrame#modalResizeGrip { border-right: 2px solid #808080; border-bottom: 2px solid #808080; margin: 3px; }')
        self.grip.setCursor(Qt.SizeFDiagCursor)
        for widget in (card, header, self.grip):
            widget.installEventFilter(self)
        self.place_grip()

    def place_grip(self):
        self.grip.setGeometry(max(0,self.card.width()-16),max(0,self.card.height()-16),16,16)
        self.grip.raise_()

    def eventFilter(self, obj, event):
        if obj is self.card and event.type() in (QEvent.Resize,QEvent.Show):
            self.place_grip()
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            edges = Qt.Edge(0)
            if obj is self.grip:
                edges = Qt.RightEdge | Qt.BottomEdge
            elif obj is self.card:
                p = event.position()
                if p.x() < 5: edges |= Qt.LeftEdge
                if p.x() >= obj.width()-5: edges |= Qt.RightEdge
                if p.y() < 5: edges |= Qt.TopEdge
                if p.y() >= obj.height()-5: edges |= Qt.BottomEdge
            if edges or obj is self.header:
                self.origin = (event.globalPosition().toPoint(),QRect(self.card.geometry()))
                self.edges = edges
                return True
        if event.type() == QEvent.MouseMove and self.origin is not None:
            start, original = self.origin
            delta = event.globalPosition().toPoint()-start
            bounds = self.card.parentWidget().rect().adjusted(8,8,-8,-8)
            rect = QRect(original)
            if not self.edges:
                rect.moveTopLeft(original.topLeft()+delta)
                rect.moveLeft(max(bounds.left(),min(rect.left(),bounds.right()-rect.width()+1)))
                rect.moveTop(max(bounds.top(),min(rect.top(),bounds.bottom()-rect.height()+1)))
            else:
                min_w,min_h=min(280,bounds.width()),min(200,bounds.height())
                if self.edges & Qt.RightEdge:rect.setRight(min(bounds.right(),max(rect.left()+min_w-1,original.right()+delta.x())))
                if self.edges & Qt.BottomEdge:rect.setBottom(min(bounds.bottom(),max(rect.top()+min_h-1,original.bottom()+delta.y())))
                if self.edges & Qt.LeftEdge:rect.setLeft(max(bounds.left(),min(rect.right()-min_w+1,original.left()+delta.x())))
                if self.edges & Qt.TopEdge:rect.setTop(max(bounds.top(),min(rect.bottom()-min_h+1,original.top()+delta.y())))
            self.card.setGeometry(rect)
            return True
        if event.type() == QEvent.MouseButtonRelease and self.origin is not None:
            self.origin = None
            return True
        return False
