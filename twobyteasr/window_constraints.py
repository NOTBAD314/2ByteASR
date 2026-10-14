"""Qt logical-coordinate window bounds and narrow, explicit resize hit targets."""
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLayout, QSizeGrip


def _native_window_is_special(widget):
    """Qt may briefly say Normal while the Windows HWND is already maximized."""
    if (QApplication.platformName() != 'windows'
            or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
        return False
    import ctypes
    hwnd = ctypes.c_void_p(int(widget.winId()))
    return bool(ctypes.windll.user32.IsZoomed(hwnd) or ctypes.windll.user32.IsIconic(hwnd))


def _special_window_state(widget):
    return (widget.isMaximized() or widget.isMinimized() or widget.isFullScreen()
            or _native_window_is_special(widget))


def restore_minimized_window(widget):
    """Clear only minimization, preserving maximized/fullscreen state."""
    if widget.isMinimized():
        widget.setWindowState(widget.windowState() & ~Qt.WindowState.WindowMinimized)
    widget.show()


_USER32 = None


def _user32():
    """A private user32 binding: argtypes set here never leak into other modules."""
    global _USER32
    if _USER32 is None:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                        ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.IsZoomed.argtypes = user32.IsIconic.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.MONITORINFO = MONITORINFO
        _USER32 = user32
    return _USER32


def native_frame(widget):
    """Window rect, its monitor's work area and monitor rect (physical pixels).

    Returns ``None`` off Windows or before the native window exists.
    """
    if (QApplication.platformName() != 'windows'
            or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
        return None
    import ctypes
    from ctypes import wintypes
    user32 = _user32()
    hwnd = int(widget.winId())
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = user32.MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    as_tuple = lambda r: (r.left, r.top, r.right, r.bottom)
    return dict(rect=as_tuple(rect), work=as_tuple(info.rcWork), monitor=as_tuple(info.rcMonitor),
                zoomed=bool(user32.IsZoomed(hwnd)), iconic=bool(user32.IsIconic(hwnd)))


def special_geometry_broken(widget):
    """A maximized or full-screen window that no longer covers exactly its screen.

    2026-10-15: Windows moves top-level windows when monitors sleep, wake or
    are re-arranged. A frameless window could then keep its old physical size
    on a screen with another scale (3840x2090 on a 1080-wide monitor) or sit
    partly above the screen, its title buttons out of reach, while Qt and
    ``IsZoomed`` still called it maximized, so :func:`constrain` skipped it.
    """
    if widget.isMinimized() or not widget.isVisible():
        return False
    native = native_frame(widget)
    if native is not None:
        if native['iconic']:
            return False
        if widget.isFullScreen():
            target = native['monitor']
        elif native['zoomed'] or widget.isMaximized():
            target = native['work']
        else:
            return False
        return max(abs(a - b) for a, b in zip(native['rect'], target)) > 2
    if not (widget.isMaximized() or widget.isFullScreen()):
        return False
    screen = widget.screen()
    if screen is None:
        return False
    target = screen.geometry() if widget.isFullScreen() else screen.availableGeometry()
    return not target.adjusted(-2, -2, 2, 2).contains(widget.frameGeometry())


def place_on_screen(widget, screen, state):
    """Normal geometry centred on ``screen``, then ``state`` (maximized/full screen)."""
    avail = screen.availableGeometry()
    normal = QRect(widget.normalGeometry())
    width = normal.width() if 0 < normal.width() <= avail.width() - 32 else min(1320, avail.width() - 32)
    height = normal.height() if 0 < normal.height() <= avail.height() - 32 else min(880, avail.height() - 32)
    rect = QRect(0, 0, max(1, width), max(1, height))
    rect.moveCenter(avail.center())
    widget.showNormal()
    native = native_frame(widget)
    if native is not None and native['zoomed']:
        # Qt may already call the window normal while the HWND is still zoomed.
        _user32().ShowWindow(int(widget.winId()), 9)  # SW_RESTORE
    widget.setGeometry(rect)
    if state & Qt.WindowState.WindowFullScreen:
        widget.showFullScreen()
    elif state & Qt.WindowState.WindowMaximized:
        widget.showMaximized()


def begin_title_drag(window, press_global, grip_y):
    """Drag from custom title chrome (2026-10-15).

    A click on the title area of a maximized window no longer restores it:
    only moving past the platform drag distance restores it under the cursor
    and hands the move to the window manager (per-monitor DPI included).
    """
    drag = getattr(window, '_title_drag', None)
    if drag is not None:
        drag.stop()
    window._title_drag = _TitleDrag(window, press_global, grip_y)
    return window._title_drag


class _TitleDrag(QObject):
    def __init__(self, window, press_global, grip_y):
        super().__init__(window)
        self.window, self.press, self.grip_y = window, QPoint(press_global), max(8, int(grip_y))
        self.offset = None
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def stop(self):
        self.timer.stop()
        if getattr(self.window, '_title_drag', None) is self:
            self.window._title_drag = None
        self.deleteLater()

    def poll(self):
        from PySide6.QtGui import QCursor, QGuiApplication
        if not QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.stop()
            return
        position = QCursor.pos()
        if self.offset is not None:
            # Manual fallback when the platform cannot run the move itself.
            self.window.move(position - self.offset)
            return
        if (position - self.press).manhattanLength() < QApplication.startDragDistance():
            return
        window = self.window
        if window.isMaximized():
            frame = window.frameGeometry()
            ratio = (self.press.x() - frame.left()) / max(1, frame.width())
            screen = window.screen().availableGeometry()
            normal = QRect(window.normalGeometry())
            width = normal.width() if 0 < normal.width() <= screen.width() else min(1320, screen.width() - 32)
            height = normal.height() if 0 < normal.height() <= screen.height() else min(880, screen.height() - 32)
            window.showNormal()
            x = position.x() - round(width * ratio)
            y = position.y() - self.grip_y
            x = min(max(x, screen.left()), screen.right() - width + 1)
            y = min(max(y, screen.top()), screen.bottom() - 40)
            window.setGeometry(x, y, width, height)
        handle = window.windowHandle()
        if handle is not None and handle.startSystemMove():
            self.stop()
            return
        self.offset = position - window.frameGeometry().topLeft()


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
    if _special_window_state(widget):
        return
    bounds = available_rect(widget, within_parent=within_parent)
    if bounds.isEmpty():
        return
    layout = widget.layout()
    if layout:
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    minimum = (min(widget.minimumWidth(), bounds.width()), min(widget.minimumHeight(), bounds.height()))
    if (widget.minimumWidth(), widget.minimumHeight()) != minimum:
        widget.setMinimumSize(*minimum)
    if _special_window_state(widget):
        return
    frame = widget.frameGeometry()
    extra_w = max(0, frame.width()-widget.width())
    extra_h = max(0, frame.height()-widget.height())
    size = (min(widget.width(), max(1, bounds.width()-extra_w)),
            min(widget.height(), max(1, bounds.height()-extra_h)))
    if (widget.width(), widget.height()) != size:
        widget.resize(*size)
    if _special_window_state(widget):
        return
    frame = widget.frameGeometry()
    x = max(bounds.left(), min(frame.left(), bounds.right()-frame.width()+1))
    y = max(bounds.top(), min(frame.top(), bounds.bottom()-frame.height()+1))
    if x != frame.left() or y != frame.top():
        widget.move(widget.pos()+QPoint(x-frame.left(), y-frame.top()))


class WindowBounds(QObject):
    def __init__(self, widget, *, within_parent=False, resizable=True):
        super().__init__(widget)
        self.widget, self.within_parent = widget, within_parent
        self.pending = False
        self.resume_state = None
        self.resume_screen = None
        self.last_screen = None
        self.repair_pending = False
        self.repairs = []
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
        native = native_frame(self.widget)
        if not self.widget.isMinimized() and not (native and native['iconic']):
            # A minimized window is parked off screen (Windows -32000), where
            # Qt reports the primary screen: remember the screen before that.
            self.last_screen = self.widget.screen()
        if self.resume_state is not None and not self.widget.isMinimized():
            # Windows' SC_RESTORE may report Normal between the native restore
            # and Qt's final state. Never resize that transient normal window.
            # Consume this once; a later user restore-to-normal remains valid.
            wanted, self.resume_state = self.resume_state, None
            screen, self.resume_screen = self.resume_screen, None
            if wanted and self.widget.windowState() != wanted:
                self.widget.setWindowState(wanted)
            if (wanted & Qt.WindowMaximized and not wanted & Qt.WindowFullScreen
                    and QApplication.platformName() == 'windows'):
                # A queued native restore can leave Qt's flag ahead of the HWND.
                # Complete this one restore at the OS boundary as well.
                import ctypes
                hwnd = ctypes.c_void_p(int(self.widget.winId()))
                if not ctypes.windll.user32.IsZoomed(hwnd):
                    ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            if wanted and screen is not None:
                QTimer.singleShot(200, lambda: self._return_to_screen(screen, wanted))
        else:
            constrain(self.widget, within_parent=self.within_parent)
            if not self.repair_pending and special_geometry_broken(self.widget):
                # Monitors waking up move windows several times; repair only
                # what is still wrong once the moves have settled.
                self.repair_pending = True
                QTimer.singleShot(350, self._repair_if_broken)
        backdrop = getattr(self.widget, '_modal_backdrop', None)
        if backdrop is not None and self.widget.parentWidget() is not None:
            backdrop.setGeometry(self.widget.parentWidget().window().rect())
        if self.grip:
            self.grip.setVisible(not _special_window_state(self.widget))
            self.grip.setGeometry(max(0,self.widget.width()-16), max(0,self.widget.height()-16), 16, 16)
            self.grip.raise_()

    def _alive(self):
        from shiboken6 import isValid
        return hasattr(self, 'widget') and isValid(self) and isValid(self.widget)

    def _repair_if_broken(self):
        if not self._alive():
            return
        self.repair_pending = False
        if not special_geometry_broken(self.widget):
            return
        import time
        now = time.monotonic()
        self.repairs = [t for t in self.repairs if now - t < 5.0]
        if len(self.repairs) >= 3:
            return  # never fight the window manager in a loop
        self.repairs.append(now)
        state = Qt.WindowState.WindowFullScreen if self.widget.isFullScreen() else Qt.WindowState.WindowMaximized
        place_on_screen(self.widget, self.widget.screen() or QApplication.primaryScreen(), state)

    def _return_to_screen(self, screen, wanted):
        """Minimize/restore of a frameless window maximized on a secondary
        monitor came back maximized on the primary one (2026-10-15)."""
        if (not self._alive() or self.widget.isMinimized() or screen not in QApplication.screens()
                or self.widget.screen() is screen):
            return
        place_on_screen(self.widget, screen, wanted)

    def eventFilter(self, obj, event):
        if not hasattr(self, 'widget') or not hasattr(self, 'grip'):
            return False
        if obj is self.widget and event.type() == QEvent.Type.WindowStateChange:
            if self.widget.isMinimized() and not (event.oldState() & Qt.WindowMinimized):
                self.resume_state = event.oldState() & (Qt.WindowMaximized | Qt.WindowFullScreen)
                self.resume_screen = self.last_screen
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.ScreenChangeInternal, QEvent.Type.WindowStateChange):
            self.schedule()
        # Border resize is limited to the outer 5 logical pixels. The rest of
        # the content remains interactive; the visible corner grip works too.
        if (obj is self.widget and self.grip and not (obj.isMaximized() or obj.isFullScreen())
                and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton):
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
