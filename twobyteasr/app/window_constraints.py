"""Qt logical-coordinate window bounds and narrow, explicit resize hit targets."""
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLayout, QSizeGrip, QWidget
from ..diagnostics.window_motion import record as trace_motion


def existing_native_handle(widget, *, hwnd=None):
    """Read an already-created native handle; never call QWidget.winId().

    winId() can create a platform window, including while Qt is destroying
    the previous one. Native callbacks and their diagnostics must only read
    internalWinId(), and reject messages belonging to another/retired HWND.
    """
    try:
        if (getattr(widget, '_studio_close_pending', False)
                or getattr(widget, '_studio_close_finalizing', False)
                or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
            return 0
        current = int(widget.internalWinId() or 0)
        if not current or (hwnd is not None and int(hwnd or 0) != current):
            return 0
        return current
    except (RuntimeError, AttributeError, TypeError, ValueError):
        return 0


def _native_window_is_special(widget):
    """Qt may briefly say Normal while the Windows HWND is already maximized."""
    if (QApplication.platformName() != 'windows'
            or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
        return False
    hwnd = existing_native_handle(widget)
    if not hwnd:
        return False
    return bool(_user32().IsZoomed(hwnd) or _user32().IsIconic(hwnd))


def _special_window_state(widget):
    return (widget.isMaximized() or widget.isMinimized() or widget.isFullScreen()
            or _native_window_is_special(widget))


def restore_minimized_window(widget):
    """Clear only minimization, preserving maximized/fullscreen state."""
    if widget.isMinimized():
        widget.setWindowState(widget.windowState() & ~Qt.WindowState.WindowMinimized)
    widget.show()


def remember_normal_geometry(widget):
    """Record only settled normal client geometry, never a transition frame."""
    bounds=getattr(widget,'_window_bounds',None)
    if (getattr(widget,'_window_geometry_transition',False)
            or bounds is not None and bounds.resume_state is not None
            or _special_window_state(widget)):
        return
    rect=QRect(widget.geometry())
    screen=widget.screen()
    if not rect.isValid() or screen is None:
        return
    user_placed=bool(bounds is not None and (bounds.owner!='idle' or bounds._position()==bounds.user_position))
    widget._normal_window_placement=(rect,QPoint(screen.geometry().topLeft()),user_placed)


def normal_restore_geometry(widget):
    placement=getattr(widget,'_normal_window_placement',None)
    if placement is None:
        return QRect(QWidget.normalGeometry(widget))
    rect,origin,_user_placed=placement
    rect=QRect(rect)
    screen=widget.screen()
    if screen is not None and screen.geometry().topLeft()!=origin:
        # Relocate logical geometry relative to the new monitor's origin.
        # Windows QScreen origins are not multiplied by either monitor DPR.
        rect.translate(screen.geometry().topLeft()-origin)
        work=screen.availableGeometry().adjusted(8,8,-8,-8)
        rect.setWidth(min(rect.width(),work.width()))
        rect.setHeight(min(rect.height(),work.height()))
        rect.moveLeft(max(work.left(),min(rect.left(),work.right()-rect.width()+1)))
        rect.moveTop(max(work.top(),min(rect.top(),work.bottom()-rect.height()+1)))
    return rect


def restore_normal_window(widget):
    """Finish an explicit restore at both Qt and HWND, once.

    Qt's frameless maximize can be geometry-only. After minimizing/restoring,
    Windows can set WS_MAXIMIZE while Qt still remembers its geometry-only
    path. showNormal then clears only Qt's flag: the next WM_SIZE resurrects
    maximization. Preserve Qt's normal rectangle before that transient state.
    """
    was_special=_special_window_state(widget)
    normal = normal_restore_geometry(widget) if was_special else QRect(widget.geometry())
    placement=getattr(widget,'_normal_window_placement',None)
    bounds = getattr(widget, '_window_bounds', None)
    if bounds is not None:
        bounds.invalidate('explicit-normal', clear_resume=True)
    widget._window_geometry_transition=True
    try:
        native = native_frame(widget)
        if native and native['zoomed']:
            trace_motion(widget, 'native-restore', actor='normal-command', reason='qt-normal-hwnd-still-zoomed')
            # Native first. Qt-first queues a stale maximized notification.
            _user32().ShowWindow(existing_native_handle(widget), 9)
        QWidget.showNormal(widget)
        if normal.isValid():
            widget.setGeometry(normal)
    finally:
        widget._window_geometry_transition=False
    if was_special and bounds is not None and placement is not None and placement[2]:
        bounds.user_position=bounds._position()
    remember_normal_geometry(widget)


def maximize_window(widget):
    """Make Qt's frameless maximization a native maximization as well.

    Geometry-only maximization leaves the system menu believing the window
    is movable/normal. Use the same one-shot native completion as restore.
    """
    bounds=getattr(widget,'_window_bounds',None)
    if bounds is not None:
        bounds.invalidate('explicit-maximize',clear_resume=True)
    # Native first preserves WINDOWPLACEMENT's normal rectangle. Performing
    # geometry-only Qt maximization first would store the work area as the
    # native restore size. Fullscreen is exited through its normal rectangle.
    if widget.isFullScreen():
        restore_normal_window(widget)
    remember_normal_geometry(widget)
    widget._window_geometry_transition=True
    try:
        native=native_frame(widget)
        if native and not native['zoomed'] and not native['iconic']:
            trace_motion(widget,'native-maximize',actor='maximize-command',reason='qt-frame-needs-native-state')
            _user32().ShowWindow(existing_native_handle(widget),3)
        QWidget.showMaximized(widget)
    finally:
        widget._window_geometry_transition=False


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

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                        ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                        ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                        ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                        ('rcCaret', wintypes.RECT)]

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int,wintypes.UINT]
        user32.GetSystemMetricsForDpi.restype = ctypes.c_int
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND,ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetAsyncKeyState.argtypes=[ctypes.c_int]
        user32.GetAsyncKeyState.restype=ctypes.c_short
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.IsZoomed.argtypes = user32.IsIconic.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
        user32.GetGUIThreadInfo.restype = wintypes.BOOL
        user32.MONITORINFO = MONITORINFO
        user32.GUITHREADINFO = GUITHREADINFO
        _USER32 = user32
    return _USER32


def native_frame(widget, *, hwnd=None):
    """Window rect, its monitor's work area and monitor rect (physical pixels).

    Returns ``None`` off Windows or before the native window exists.
    """
    if (QApplication.platformName() != 'windows'
            or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
        return None
    import ctypes
    from ctypes import wintypes
    user32 = _user32()
    hwnd = existing_native_handle(widget, hwnd=hwnd)
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = user32.MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    as_tuple = lambda r: (r.left, r.top, r.right, r.bottom)
    client=wintypes.RECT()
    origin=wintypes.POINT()
    client_rect=None
    if user32.GetClientRect(hwnd,ctypes.byref(client)) and user32.ClientToScreen(hwnd,ctypes.byref(origin)):
        client_rect=(origin.x,origin.y,origin.x+client.right,origin.y+client.bottom)
    return dict(rect=as_tuple(rect), work=as_tuple(info.rcWork), monitor=as_tuple(info.rcMonitor),
                client=client_rect, dpi=int(user32.GetDpiForWindow(hwnd)),
                style=int(user32.GetWindowLongPtrW(hwnd,-16)) & 0xffffffff,
                zoomed=bool(user32.IsZoomed(hwnd)), iconic=bool(user32.IsIconic(hwnd)))


def in_move_size_loop(widget):
    """True while the user moves or resizes ``widget`` (2026-10-22).

    Windows' own move/size loop (``startSystemMove``/``startSystemResize``,
    the system menu's keyboard move) or the manual title-drag fallback.
    """
    if getattr(widget, '_title_drag', None) is not None:
        return True
    bounds = getattr(widget, '_window_bounds', None)
    if bounds is not None and bounds.owner != 'idle':
        return True
    return native_move_size_loop(widget)


def native_move_size_loop(widget):
    """Only the OS state; unlike in_move_size_loop this cannot self-latch."""
    if (QApplication.platformName() != 'windows'
            or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)):
        return False
    import ctypes
    user32 = _user32()
    hwnd = existing_native_handle(widget)
    if not hwnd:
        return False
    info = user32.GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetGUIThreadInfo(user32.GetWindowThreadProcessId(hwnd, None), ctypes.byref(info)):
        return False
    return bool(info.flags & 0x2) and int(info.hwndMoveSize or 0) == hwnd  # GUI_INMOVESIZE


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
        if getattr(widget,'_native_frame_active',False) and not widget.isFullScreen() and native.get('client'):
            # The outer sizing frame can legitimately overhang a maximized
            # work area; the usable client must match. Still catch a huge or
            # wrongly positioned outer frame after monitor removal.
            u=_user32()
            dpi=native.get('dpi') or 96
            padding=u.GetSystemMetricsForDpi(92,dpi)
            bx=u.GetSystemMetricsForDpi(32,dpi)+padding+2
            by=u.GetSystemMetricsForDpi(33,dpi)+padding+2
            return (max(abs(a-b) for a,b in zip(native['client'],target))>2
                    or any(abs(a-b)>limit for a,b,limit in zip(native['rect'],target,(bx,by,bx,by))))
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
        _user32().ShowWindow(existing_native_handle(widget), 9)  # SW_RESTORE
    widget.setGeometry(rect)
    if state & Qt.WindowState.WindowFullScreen:
        widget.showFullScreen()
    elif state & Qt.WindowState.WindowMaximized:
        widget.showMaximized()


def begin_title_drag(window, press_global, grip_y, *, source=None):
    """Drag from custom title chrome (2026-10-15).

    A click on the title area of a maximized window no longer restores it:
    only moving past the platform drag distance restores it under the cursor
    and hands the move to the window manager (per-monitor DPI included).
    """
    drag = getattr(window, '_title_drag', None)
    if drag is not None:
        drag.stop('superseded')
    if window.isFullScreen() or window.isMinimized():
        trace_motion(window, 'press-ignored', actor='title', reason='fullscreen-or-minimized')
        return None
    window._title_drag = _TitleDrag(window, press_global, grip_y, source=source)
    if not window.isMaximized():
        window._title_drag.request_native(at_press=True)
    return window._title_drag


def cancel_title_drag(window, reason='state-command'):
    drag = getattr(window, '_title_drag', None)
    if drag is not None:
        drag.stop(reason)
    bounds = getattr(window, '_window_bounds', None)
    if bounds is not None:
        bounds.invalidate(reason, clear_resume=True)


def _start_system_move(window):
    handle = window.windowHandle()
    return bool(handle is not None and handle.startSystemMove())


def start_system_resize(window, edges):
    if _special_window_state(window):
        return False
    bounds = getattr(window, '_window_bounds', None)
    if bounds is not None:
        bounds.begin_interaction('native-pending')
    handle = window.windowHandle()
    if handle is not None and handle.startSystemResize(edges):
        if bounds is not None:
            bounds.watch_interaction()
        return True
    if bounds is not None:
        bounds.end_interaction('resize-handoff-unavailable', moved=False)
    return False


class _TitleDrag(QObject):
    """One gesture: armed -> restoring -> native OR manual -> finished.

    The poller is stopped *before* invoking startSystemMove: on Windows that
    call can re-enter the event loop. No second restore or fallback may run
    while the native call owns the move.
    """
    def __init__(self, window, press_global, grip_y, *, source=None):
        super().__init__(window)
        self.window, self.press, self.grip_y = window, QPoint(press_global), max(8, int(grip_y))
        self.source = source
        self.phase = 'armed'
        self.original = QRect(window.geometry())
        self.original_state = window.windowState()
        self.normal = QRect(window.normalGeometry())
        self.frame = QRect(window.frameGeometry())
        self.offset = self.press - self.frame.topLeft()
        self.moved = False
        self.native_rejected = False
        bounds = getattr(window, '_window_bounds', None)
        if bounds is not None:
            bounds.begin_interaction('title-armed')
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

        trace_motion(window, 'press', actor='title', reason='armed')

    def stop(self, reason='release'):
        if self.phase == 'finished':
            return
        native = self.phase == 'native'
        self.phase = 'finished'
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        if getattr(self.window, '_title_drag', None) is self:
            self.window._title_drag = None
        bounds = getattr(self.window, '_window_bounds', None)
        if bounds is not None and not native:
            bounds.end_interaction(reason, moved=self.moved)
        trace_motion(self.window, 'gesture-end', actor='title', reason=reason)
        self.deleteLater()

    def poll(self):
        from PySide6.QtGui import QCursor, QGuiApplication
        if not QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.stop('release')
            return
        position = QCursor.pos()
        self.advance(position)

    def advance(self, position):
        if self.phase == 'manual':
            trace_motion(self.window, 'move-request', actor='title-fallback', reason='held-mouse',
                         target_logical=[position.x()-self.offset.x(),position.y()-self.offset.y()])
            self.window.move(position - self.offset)
            return
        if self.phase != 'armed':
            return
        if (position - self.press).manhattanLength() < QApplication.startDragDistance():
            return
        window = self.window
        self.phase = 'restoring'  # set before a reentrant showNormal/resize
        self.moved = True
        self.timer.stop()
        if self.original_state & Qt.WindowMaximized:
            ratio = min(1.0,max(0.0,(self.press.x()-self.frame.left())/max(1,self.frame.width())))
            screen = (QApplication.screenAt(position) or window.screen() or QApplication.primaryScreen()).availableGeometry()
            width = self.normal.width() if self.normal.width()>0 else min(1320,screen.width()-32)
            height = self.normal.height() if self.normal.height()>0 else min(880,screen.height()-32)
            width, height = min(width,screen.width()), min(height,screen.height())
            trace_motion(window, 'restore', actor='title', reason='drag-threshold-crossed')
            window.showNormal()
            x = position.x() - round(width * ratio)
            y = position.y() - self.grip_y
            # Preserve the cursor's horizontal grab point. Whole-window
            # clamping here used to move the grip away near monitor edges.
            window.setGeometry(x, y, width, height)
            self.offset = position - window.frameGeometry().topLeft()
        if self.native_rejected:
            self.phase = 'manual'
            bounds = getattr(window, '_window_bounds', None)
            if bounds is not None:
                bounds.owner = 'manual'
            self.timer.start()
            self.advance(position)
            return
        self.request_native()

    def request_native(self, *, at_press=False):
        window = self.window
        bounds = getattr(window, '_window_bounds', None)
        self.phase = 'native'
        self.timer.stop()
        if bounds is not None:
            bounds.owner = 'native-pending'
            bounds.watch_interaction()
        trace_motion(window, 'native-request', actor='title', reason='system-move-handoff')
        if _start_system_move(window):
            # Keep this gesture until WM_EXITSIZEMOVE (or release watchdog).
            # A successful handoff never runs manual moves.
            return
        if self.phase == 'finished':
            return
        self.native_rejected = True
        self.phase = 'armed' if at_press else 'manual'
        if bounds is not None:
            bounds.owner = 'title-armed' if at_press else 'manual'
            bounds._watchdog.stop()
        trace_motion(window, 'fallback', actor='title', reason='system-move-unavailable')
        self.timer.start()
        if not at_press:
            from PySide6.QtGui import QCursor
            self.advance(QCursor.pos())

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self.phase != 'native':
                self.stop('release')
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Escape and self.phase != 'native':
            if self.moved:
                trace_motion(self.window, 'cancel-restore', actor='title-fallback', reason='escape')
                self.window.setGeometry(self.original)
                if self.original_state & Qt.WindowMaximized:
                    self.window.setGeometry(self.normal)
                    self.window.showMaximized()
                else:
                    self.window.setWindowState(self.original_state)
            self.stop('escape')
            return True
        elif (kind == QEvent.UngrabMouse and obj is self.source and self.phase in {'armed','manual'}):
            self.stop('capture-lost')
        elif obj is self.window and kind in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.Close):
            self.stop(kind.name)
        return False


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


def constrain(widget, *, within_parent=False, user_placed=False):
    """Fit ``widget`` into its screen (or parent window).

    ``user_placed``: the top-level window sits where the user dropped it; it
    may hang past the screen edges as long as its title strip is reachable.
    """
    if _special_window_state(widget):
        trace_motion(widget, 'bounds-skip', actor='constrain', reason='special-state')
        return
    bounds = available_rect(widget, within_parent=within_parent)
    if bounds.isEmpty():
        return
    # User placement never requires the entire window to fit. In particular,
    # do not resize a tall window before deciding its title is already usable.
    if user_placed and not within_parent and widget.windowType() == Qt.Window:
        frame = widget.frameGeometry()
        if title_reachable(frame):
            trace_motion(widget, 'bounds-skip', actor='constrain', reason='reachable-user-title')
            return
        target = recover_title_rect(frame, [s.availableGeometry() for s in QApplication.screens()])
        if target.topLeft() != frame.topLeft():
            trace_motion(widget, 'move-request', actor='constrain', reason='recover-unreachable-title',
                         target_logical=[target.x(),target.y()])
            widget.move(widget.pos()+target.topLeft()-frame.topLeft())
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
        trace_motion(widget, 'resize-request', actor='constrain', reason='fit-initial-or-dialog', target_size=size)
        widget.resize(*size)
    if _special_window_state(widget):
        return
    frame = widget.frameGeometry()
    x = max(bounds.left(), min(frame.left(), bounds.right()-frame.width()+1))
    y = max(bounds.top(), min(frame.top(), bounds.bottom()-frame.height()+1))
    if x != frame.left() or y != frame.top():
        trace_motion(widget, 'move-request', actor='constrain',
                     reason='fit-initial-or-dialog',
                     target_logical=[x,y])
        widget.move(widget.pos()+QPoint(x-frame.left(), y-frame.top()))


TITLE_REACH = (160, 40)  # logical px of a top-level window's top strip kept on a screen


def recover_title_rect(frame, work_areas):
    """Smallest translation onto any work area; never rescale user placement.

    QScreen rectangles and the frame here are Qt logical coordinates. Screen
    origins may be negative and need not form one contiguous rectangle.
    """
    candidates = []
    for work in work_areas:
        area = work.adjusted(8,8,-8,-8)
        if area.isEmpty():
            continue
        keep_w = min(TITLE_REACH[0],frame.width(),area.width())
        keep_h = min(TITLE_REACH[1],frame.height(),area.height())
        x = max(area.left()-frame.width()+keep_w,min(frame.x(),area.right()-keep_w+1))
        y = max(area.top(),min(frame.y(),area.bottom()-keep_h+1))
        candidates.append((abs(x-frame.x())**2+abs(y-frame.y())**2,QRect(x,y,frame.width(),frame.height())))
    return min(candidates,key=lambda item:item[0])[1] if candidates else QRect(frame)


def title_reachable(frame):
    keep_w, keep_h = min(TITLE_REACH[0], frame.width()), min(TITLE_REACH[1], frame.height())
    strip = QRect(frame.left(), frame.top(), frame.width(), keep_h)
    for screen in QApplication.screens():
        visible = strip.intersected(screen.availableGeometry())
        if visible.width() >= keep_w and visible.height() >= keep_h:
            return True
    return False


class WindowBounds(QObject):
    def __init__(self, widget, *, within_parent=False, resizable=True, native_events=False):
        super().__init__(widget)
        self.widget, self.within_parent = widget, within_parent
        self.pending = False
        self.resume_state = None
        self.resume_screen = None
        self.last_screen = None
        self.repair_pending = False
        self.repairs = []
        self.drag_wait = False
        self.dragged = False
        self.user_position = None
        self.generation = 0
        self.owner = 'idle'
        self.native_events = native_events
        self._tasks = {}
        self._applying = False
        self._native_seen = False
        self.caption_presses = 0
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(25)
        self._watchdog.timeout.connect(self._check_interaction)
        self.grip = None
        widget.installEventFilter(self)
        parent = widget.parentWidget()
        if parent:
            parent.window().installEventFilter(self)
        self.grip = QSizeGrip(widget) if resizable else None
        for screen in QApplication.screens():
            self._watch_screen(screen)
        QApplication.instance().screenAdded.connect(self._screen_added)
        QApplication.instance().screenRemoved.connect(self._screen_changed)
        if not native_events:
            _watch_move_size(self)
        self.schedule()

    def move_size_event(self, started):
        """Windows began or ended moving/resizing this window. Without
        "show window contents while dragging" (Remote Desktop's default) no
        move event arrives until the drop, so the drag is noted here."""
        if started:
            if self.owner not in {'native','native-pending'}:
                if self.owner == 'idle':
                    self.begin_interaction('native')
            self.owner = 'native'
            self._native_seen = True
            self.dragged = True
            self.watch_interaction()
            trace_motion(self.widget, 'native-start', actor='windows', reason='enter-move-size')
        elif self.owner in {'native','native-pending'} or self._native_seen:
            drag = getattr(self.widget, '_title_drag', None)
            if drag is not None and drag.phase == 'native':
                drag.stop('native-exit')
            self.end_interaction('native-exit', moved=True)

    def invalidate(self, reason, *, clear_resume=False):
        self.generation += 1
        for name, (timer, _callback, generation) in tuple(self._tasks.items()):
            trace_motion(self.widget, 'callback-cancel', actor='bounds', reason=reason,
                         callback=name, queued_generation=generation)
            timer.stop()
            timer.deleteLater()
        self._tasks.clear()
        self.pending = self.repair_pending = self.drag_wait = False
        if clear_resume:
            self.resume_state = self.resume_screen = None
        trace_motion(self.widget, 'invalidate', actor='bounds', reason=reason)

    def _queue(self, name, delay, callback):
        if name in self._tasks:
            return
        generation = self.generation
        timer = QTimer(self)
        timer.setSingleShot(True)
        def run():
            current = self._tasks.get(name)
            if current is None or current[0] is not timer:
                return
            self._tasks.pop(name)
            timer.deleteLater()
            if not self._alive() or generation != self.generation:
                return
            trace_motion(self.widget, 'callback-run', actor='bounds', reason='current-generation',
                         callback=name, queued_generation=generation)
            callback()
        timer.timeout.connect(run)
        self._tasks[name] = (timer, callback, generation)
        trace_motion(self.widget, 'callback-create', actor='bounds', reason='deferred-check',
                     callback=name, queued_generation=generation, delay_ms=delay)
        timer.start(delay)

    def begin_interaction(self, owner):
        self.invalidate('new-' + owner, clear_resume=True)
        self.owner = owner
        self.dragged = False
        self._native_seen = False
        self._prior_user_position = self.user_position
        self.user_position = None
        if owner == 'manual-resize':
            QApplication.instance().installEventFilter(self)
        trace_motion(self.widget, 'interaction-start', actor=owner, reason='new-user-intent')

    def end_interaction(self, reason, *, moved=True):
        self._watchdog.stop()
        was_manual_resize = self.owner == 'manual-resize'
        self.owner = 'idle'
        if was_manual_resize:
            QApplication.instance().removeEventFilter(self)
            self.widget._resize_dragging = False
            self.widget._resize_edge = None
            self.widget._resize_start_geom = self.widget._resize_start_pos = None
            if self.widget.mouseGrabber() is self.widget:
                self.widget.releaseMouse()
        self._native_seen = False
        self.invalidate(reason, clear_resume=True)
        self.dragged = bool(moved)
        if moved:
            self.user_position = self._position()
        else:
            self.user_position = getattr(self, '_prior_user_position', None)
        trace_motion(self.widget, 'interaction-end', actor='bounds', reason=reason)
        self.schedule()

    def watch_interaction(self):
        self._watchdog.start()

    def native_message(self, message, wparam=0, lparam=0):
        if message==0x00A1 and wparam==2:  # actual NC title mouse press
            remember_normal_geometry(self.widget)
            self.begin_interaction('native-pending')
            self.caption_presses+=1
            trace_motion(self.widget,'caption-press',actor='windows',reason='native-title-hit-test',
                         target=getattr(self.widget,'_native_caption_target','title'),
                         caption_press=self.caption_presses)
            self.watch_interaction()
        elif message==0x00A2 and wparam==2 and self.owner=='native-pending' and not native_move_size_loop(self.widget):
            self.move_size_event(False)
        if message==0x0112:  # WM_SYSCOMMAND
            command=wparam & 0xfff0
            if command==0xf030:  # SC_MAXIMIZE
                remember_normal_geometry(self.widget)
        if message == 0x0231:  # WM_ENTERSIZEMOVE, synchronous ownership boundary
            self.move_size_event(True)
        elif message == 0x0232:  # WM_EXITSIZEMOVE, including Esc cancellation
            self.move_size_event(False)
        elif message == 0x02E0:  # WM_DPICHANGED: Qt applies the suggested native rect
            self.invalidate('dpi-change', clear_resume=True)
            trace_motion(self.widget, 'dpi-change', actor='qt-platform', reason='qt-owns-native-scaling',
                         dpi_x=wparam & 0xffff, dpi_y=(wparam >> 16) & 0xffff)
            self.schedule()
        elif message in (0x001F,0x0215):  # CANCELMODE / CAPTURECHANGED
            trace_motion(self.widget, 'capture-change', actor='windows', reason=hex(message))
            # Releasing Qt capture is part of entering the native loop. The
            # native exit or watchdog, not this transient message, ends it.
            if self.owner == 'manual-resize':
                self.widget._resize_dragging = False
                self.widget._resize_edge = None
                self.widget._resize_start_geom = self.widget._resize_start_pos = None
                self.end_interaction('capture-lost')

    def _check_interaction(self):
        from PySide6.QtGui import QGuiApplication
        if not self._alive():
            self._watchdog.stop()
            return
        if native_move_size_loop(self.widget):
            self._native_seen = True
            return
        # A successful startSystemMove is asynchronous on Windows. Until its
        # native start arrives keep ownership, but never keep it past release.
        held=(bool(_user32().GetAsyncKeyState(1)&0x8000) if QApplication.platformName()=='windows'
              else bool(QGuiApplication.mouseButtons() & Qt.LeftButton))
        if self.owner in {'native','native-pending'} and (self._native_seen or not held):
            self.move_size_event(False)

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self._screen_changed)
        screen.geometryChanged.connect(self._screen_changed)

    def _screen_added(self, screen):
        self._watch_screen(screen)
        self._screen_changed()

    def _screen_changed(self, *args):
        self.invalidate('display-configuration', clear_resume=True)
        self.user_position = None
        self.schedule()

    def schedule(self, *args):
        if not self.pending:
            self.pending = True
            self._queue('apply', 0, self.apply)

    def apply(self):
        from shiboken6 import isValid
        if not hasattr(self, 'widget') or not isValid(self.widget):
            return
        self.pending = False
        if self._applying or not self.widget.isVisible():
            return
        if in_move_size_loop(self.widget):
            self.dragged = True
            trace_motion(self.widget, 'bounds-skip', actor='bounds', reason='interactive-owner')
            # Poll only for legacy/platform move loops without a native event.
            if self.owner == 'idle' and not self.drag_wait:
                self.drag_wait = True
                self._queue('after-drag', 50, self._after_drag)
            self._place_grip()
            return
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
                hwnd = existing_native_handle(self.widget)
                if hwnd and not _user32().IsZoomed(hwnd):
                    _user32().ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            if wanted and screen is not None:
                self._queue('return-screen', 200, lambda: self._return_to_screen(screen, wanted))
        else:
            position = self._position()
            if self.dragged:
                self.dragged, self.user_position = False, position
            # Moves by the program or by Windows itself (monitor changes)
            # still put the whole window inside the screen.
            user_placed = position == self.user_position
            self._applying = True
            try:
                constrain(self.widget, within_parent=self.within_parent, user_placed=user_placed)
            finally:
                self._applying = False
            if user_placed:  # a title dropped out of reach was pulled back
                self.user_position = self._position()
            if not self.repair_pending and special_geometry_broken(self.widget):
                # Monitors waking up move windows several times; repair only
                # what is still wrong once the moves have settled.
                self.repair_pending = True
                self._queue('repair', 350, self._repair_if_broken)
        remember_normal_geometry(self.widget)
        self._place_grip()

    def _place_grip(self):
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

    def _position(self):
        """Top-left now. Qt applies a move made by Windows to its own
        geometry a moment later, so the HWND rect is the reliable one."""
        native = native_frame(self.widget)
        if native is not None:
            return native['rect'][:2]
        point = self.widget.frameGeometry().topLeft()
        return point.x(), point.y()

    def _after_drag(self):
        if not self._alive():
            return
        self.drag_wait = False
        self.schedule()

    def _repair_if_broken(self):
        if not self._alive():
            return
        self.repair_pending = False
        if in_move_size_loop(self.widget):
            trace_motion(self.widget, 'callback-skip', actor='repair', reason='interactive-owner')
            return
        if not special_geometry_broken(self.widget):
            trace_motion(self.widget, 'callback-skip', actor='repair', reason='geometry-already-valid')
            return
        import time
        now = time.monotonic()
        self.repairs = [t for t in self.repairs if now - t < 5.0]
        if len(self.repairs) >= 3:
            return  # never fight the window manager in a loop
        self.repairs.append(now)
        state = Qt.WindowState.WindowFullScreen if self.widget.isFullScreen() else Qt.WindowState.WindowMaximized
        trace_motion(self.widget, 'repair', actor='repair', reason='special-frame-outside-monitor')
        place_on_screen(self.widget, self.widget.screen() or QApplication.primaryScreen(), state)

    def _return_to_screen(self, screen, wanted):
        """Minimize/restore of a frameless window maximized on a secondary
        monitor came back maximized on the primary one (2026-10-15)."""
        if (not self._alive() or self.widget.isMinimized() or in_move_size_loop(self.widget)
                or not self.widget.isVisible() or self.widget.windowState() != wanted
                or screen not in QApplication.screens()
                or self.widget.screen() is screen):
            if self._alive():
                trace_motion(self.widget, 'callback-skip', actor='restore', reason='screen-return-no-longer-applicable')
            return
        trace_motion(self.widget, 'return-screen', actor='restore', reason='minimized-screen-restoration')
        place_on_screen(self.widget, screen, wanted)

    def eventFilter(self, obj, event):
        if not hasattr(self, 'widget') or not hasattr(self, 'grip'):
            return False
        kind = event.type()
        if self.owner == 'manual-resize':
            if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                original = getattr(self.widget, '_resize_start_geom', None)
                if original is not None:
                    self.widget.setGeometry(original)
                self.end_interaction('resize-escape')
                return True
            if obj is self.widget and kind == QEvent.UngrabMouse:
                self.end_interaction('resize-capture-lost')
        if obj is self.widget and kind in (QEvent.Hide, QEvent.Close, QEvent.WindowDeactivate):
            drag = getattr(self.widget, '_title_drag', None)
            if drag is not None:
                drag.stop(kind.name)
            if self.owner != 'idle':
                self.end_interaction(kind.name, moved=self.dragged)
            self.invalidate(kind.name, clear_resume=kind != QEvent.Hide and not self.widget.isMinimized())
        if obj is self.widget and event.type() == QEvent.Type.WindowStateChange:
            if self.widget.isMaximized() or self.widget.isFullScreen() or self.widget.isMinimized():
                drag = getattr(self.widget,'_title_drag',None)
                if drag is not None and drag.phase in {'armed','manual'}:
                    drag.stop('special-state-change')
                if self.owner == 'manual-resize':
                    self.end_interaction('special-state-change')
            self.invalidate('window-state-change')
            if self.native_events:
                from .window_native_frame import configure
                configure(self.widget)
            if self.widget.isMinimized() and not (event.oldState() & Qt.WindowMinimized):
                self.resume_state = event.oldState() & (Qt.WindowMaximized | Qt.WindowFullScreen)
                self.resume_screen = self.last_screen
            elif not event.oldState() & Qt.WindowMinimized:
                self.resume_state = self.resume_screen = None
            self.user_position = None
            trace_motion(self.widget, 'state-change', actor='qt', reason='window-state-event',
                         old_state=event.oldState().value)
        if obj is self.widget and kind == QEvent.ScreenChangeInternal:
            self.invalidate('window-screen-change', clear_resume=self.owner != 'idle')
        if obj is self.widget and kind in (QEvent.Move,QEvent.Resize):
            trace_motion(self.widget, 'move' if kind == QEvent.Move else 'resize', actor='qt', reason='observed')
            remember_normal_geometry(self.widget)
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
            if edges and start_system_resize(obj, edges):
                return True
        return False


_MOVE_SIZE_HOOK = None
_MOVE_SIZE_OWNERS = None


def _watch_move_size(bounds):
    """One process-wide EVENT_SYSTEM_MOVESIZESTART/END hook (2026-10-22).

    Owners are matched lazily by HWND so that no native window is created
    early; the callback runs on this GUI thread, only for those two events.
    """
    global _MOVE_SIZE_HOOK, _MOVE_SIZE_OWNERS
    if QApplication.platformName() != 'windows':
        return
    import weakref
    if _MOVE_SIZE_HOOK is None:
        import ctypes
        import os
        from ctypes import wintypes
        _MOVE_SIZE_OWNERS = weakref.WeakSet()
        callback_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                           wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

        def on_event(_hook, event, hwnd, object_id, _child, _thread, _time):
            if object_id != 0 or not hwnd:  # OBJID_WINDOW
                return
            for owner in list(_MOVE_SIZE_OWNERS):
                widget = owner.widget if owner._alive() else None
                if (widget is not None and widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
                        and existing_native_handle(widget) == int(hwnd)):
                    owner.move_size_event(event == 0x000A)
                    return

        callback = callback_type(on_event)
        user32 = _user32()
        user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, callback_type,
                                           wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
        user32.SetWinEventHook.restype = wintypes.HANDLE
        # MOVESIZESTART..MOVESIZEEND, this process only, WINEVENT_OUTOFCONTEXT.
        handle = user32.SetWinEventHook(0x000A, 0x000B, None, callback, os.getpid(), 0, 0)
        _MOVE_SIZE_HOOK = (handle, callback)  # the callback must stay alive
    _MOVE_SIZE_OWNERS.add(bounds)


def install_window_bounds(widget, **options):
    if not hasattr(widget, '_window_bounds'):
        widget._window_bounds = WindowBounds(widget, **options)
        if options.get('native_events'):
            from .window_native_frame import configure
            configure(widget)
        remember_normal_geometry(widget)
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
