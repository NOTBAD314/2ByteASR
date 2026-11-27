"""Bridge startup to Home with Home's skeleton (kept, or a built-in one) or a cached client image.

The kept files survive program updates, and the temporary window fades after
the real window paints. A compatible native launcher draws the saved layout
from ``cover.txt`` and uses ``TWOBYTEASR_LAUNCH_COVER`` for the handoff signal;
without one (the packaged daily keeps its old root launcher) the app draws the
same skeleton itself as soon as it can.

2026-11-20 (user, about the small square bunny head on the launch screen without a kept skeleton:
"really ugly, better without this icon"; they picked draft A 「骨架微光」): a start with nothing
kept draws Home's skeleton too, laid out from ``launch_default_cover`` for the window's size and
theme, so the launch screen is always Home's shape and never shows the icon.

2026-11-23 (user: the skeleton is "too plain and crude"; from three drafts in
``tmp/launch-drafts-20261123`` they picked B2 「音波時間軸」): every start draws ``launch_screen`` -
the wordmark over a waveform timeline - on the theme's background instead of Home's skeleton or the
kept picture, and at the end the wordmark flies to Home's title while Home appears under it
(``_land``). The kept files (place, skeleton for a native launcher) are still written at a close.

The Qt window is disabled in isolated tests unless explicitly enabled.

No application imports at module level: ``show`` runs before the heavy imports.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

FORMAT = 3
NAME = 'launch-picture'
# What a kept picture depends on. Not the program: a picture survives an update (2026-11-19).
_PICTURE_KEY = ('screens', 'client', 'scale', 'theme', 'language', 'zoom')
_SHELL = None
_FADING = []
_COVER_EVENT = ''                        # the launcher's skeleton is up: set this event to end it
COVER_FORMAT = 1
_WRITER: threading.Thread | None = None
_SHOWN_AT = None                         # perf_counter when the launch window went up
_LOAD_S = None                           # how long this start took until the real window was up
_WINDOW = None                           # the real window, from ``adopt`` (the end flies onto its title)
LAND_GRACE_MS = 600                      # the end's flight is given this long beyond its own length


# ---------------------------------------------------------------------------- where and whether
def _directory() -> Path:
    from ..runtime_paths import user_data_root
    return user_data_root() / 'cache' / NAME


def enabled() -> bool:
    choice = os.environ.get('TWOBYTEASR_LAUNCH_PICTURE', '')
    if choice in ('0', '1'):
        return choice == '1'
    if sys.platform != 'win32':
        return False
    return not any(os.environ.get(name) for name in (
        'TWOBYTEASR_TEST_ROOT', 'TWOBYTEASR_ACCEPTANCE_DIR', 'TWOBYTEASR_ACCEPTANCE_SCENARIO',
        'TWOBYTEASR_AUDIT_TOP_LEVELS', 'TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE'))


def program_stamp() -> str:
    """Identify the build that last wrote the cache metadata."""
    try:
        target = Path(sys.executable) if getattr(sys, 'frozen', False) else Path(__file__).with_name('ui.py')
        state = target.stat()
        return f'{target.name}|{state.st_mtime_ns}|{state.st_size}'
    except OSError:
        return ''


def screens_signature(app) -> list:
    rows = []
    for screen in app.screens():
        g = screen.geometry()
        rows.append([g.x(), g.y(), g.width(), g.height(), round(float(screen.devicePixelRatio()), 4)])
    return sorted(rows)


# ---------------------------------------------------------------------------- native helpers
def _user32():
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.UINT]
    user.SetWindowPos.restype = wintypes.BOOL
    user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsZoomed.argtypes = [wintypes.HWND]
    return user


def _dwm_set(hwnd: int, attribute: int, value: int) -> None:
    try:
        import ctypes
        from ctypes import wintypes
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        number = ctypes.c_int(value)
        dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))
    except (OSError, AttributeError):
        pass


# ---------------------------------------------------------------------------- showing it
def read() -> dict | None:
    """What was kept at the last close, or None."""
    try:
        meta = json.loads((_directory() / 'meta.json').read_text('utf8'))
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or meta.get('format') != FORMAT:
        return None
    return meta


def read_cover(meta: dict | None):
    """Home's skeleton as kept for the launcher (``cover.txt``) while it still matches ``meta``
    (same place, size and scale): ``(colors, parts)``, or None."""
    try:
        lines = (_directory() / 'cover.txt').read_text('utf8').splitlines()
        header, colors, parts = {}, None, []
        for line in lines:
            fields = line.split()
            if len(fields) == 6 and fields[0] == 'part':
                if fields[1] != 'mascot':  # Layouts saved by earlier builds included the header icon.
                    parts.append((fields[1], *(float(value) for value in fields[2:])))
            elif len(fields) == 6 and fields[0] == 'colors':
                colors = fields[1:]
            elif fields:
                header[fields[0]] = fields[1:]
        if (not meta or header.get('format') != [str(COVER_FORMAT)] or colors is None or len(parts) < 3
                or [int(value) for value in header.get('client', ())] != list(meta.get('client') or ())
                or abs(float(header['scale'][0]) - float(meta.get('scale') or 1.0)) > 1e-3):
            return None
        return colors, parts
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def usable(meta: dict | None, app, *, arguments=()) -> str:
    """'skeleton', 'picture', 'plain' or '' (nothing is shown)."""
    if not meta or arguments or meta.get('next_page') != 'recognition':
        return ''
    client = meta.get('client')
    if (not isinstance(client, list) or len(client) != 4 or client[2] < 320 or client[3] < 200
            or meta.get('screens') != screens_signature(app)):
        return ''
    if read_cover(meta) is not None:
        # 2026-11-19: the packaged daily keeps its old root launcher, which never draws the
        # skeleton (user report: "I see my icon"), so the app draws the same loading screen itself.
        return 'skeleton'
    if meta.get('picture') and (_directory() / 'home.bmp').is_file():
        return 'picture'                    # also after an update: the real window fades in over it
    return 'plain' if meta.get('background') else ''


def show(app, *, arguments=()):
    """Show the kept window now. Returns it, or None. Never raises."""
    global _SHELL, _COVER_EVENT, _SHOWN_AT
    try:
        cover = os.environ.pop('TWOBYTEASR_LAUNCH_COVER', '')     # not handed on to a restart
        if cover:
            _COVER_EVENT = cover
            return None                     # the launcher draws Home's skeleton until our first paint
        if _SHELL is not None or not enabled():
            return _SHELL
        meta = read()
        kind = usable(meta, app, arguments=arguments)
        if not kind and meta is None and not arguments and _next_page() == 'recognition':
            meta, kind = _first_start_meta(app), 'first'
        if not kind or meta is None:
            return None
        shell = _make_shell(app, meta, kind)
        if shell is None:
            return None
        _SHELL = shell
        _SHOWN_AT = time.perf_counter()
        if kind == 'first':
            shell.show()                    # placed by Qt where the window opens by default
        else:
            # Its native window is put in place while hidden (the position first: that tells Qt
            # which screen and scale it is on), then its size, then shown and set to the pixels.
            _place(shell, meta, size=False)
            scale = float(meta.get('scale') or 1.0) or 1.0
            shell.resize(max(1, round(meta['client'][2] / scale)), max(1, round(meta['client'][3] / scale)))
            shell.show()
            _place(shell, meta)
        # Its first frame before the imports and the main window take the GUI thread.
        from PySide6.QtCore import QEventLoop
        deadline = time.perf_counter() + 0.25
        while not shell.painted and time.perf_counter() < deadline:
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        _start_motion(shell, meta)
        return shell
    except Exception:  # noqa: BLE001 - the app starts as it always did
        dismiss()
        return None


def _make_shell(app, meta: dict, kind: str):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QWidget
    from . import launch_motion
    from .launch_screen import LaunchScreen, Sprites, palette, unit_for

    if not kind:
        return None
    colors = palette(meta.get('theme'))
    language = meta.get('language')
    if kind == 'first':
        x, y, width, height = meta['geometry']
        logical = (width, height)
    else:
        scale = float(meta.get('scale') or 1.0) or 1.0
        x, y = meta['client'][:2]
        logical = (max(1, round(meta['client'][2] / scale)), max(1, round(meta['client'][3] / scale)))
    expected = _expected_load_s(meta)

    class Shell(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.NoDropShadowWindowHint)
            self.setObjectName('launchPicture')
            self.setWindowTitle('2ByteASR')
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
            self.setProperty('transitionMotion', False)
            self.setCursor(Qt.CursorShape.BusyCursor)
            self.painted = False
            self.kind = kind
            self.colors = colors
            self.language = language
            self.background = str(colors['background'])
            self.motion = None              # launch_motion.LaunchMotion once it runs
            self.screen = None              # launch_screen.LaunchScreen, made at the window's scale
            # Drawn moving (``launch_motion``) the still picture is only the background, the frames
            # bring the screen in; without motion it is the whole screen at rest.
            self.still_t = 0.0 if launch_motion.enabled() else 1.2

        def ensure_screen(self):
            if self.screen is None:
                # Text pictures at the size they are drawn (the layout grows with the window), so
                # the wordmark stays sharp.
                ratio = (float(self.devicePixelRatioF()) or 1.0) * max(1.0, unit_for(self.width(), self.height()))
                sprites = Sprites.build(colors, language, ratio)
                self.screen = LaunchScreen(self.width(), self.height(), colors, sprites, language, expected)
            return self.screen

        def paintEvent(self, _event):  # noqa: N802 - Qt override
            painter = QPainter(self)
            motion = self.motion
            if motion is not None:
                # The moving screen's latest frame (launch_motion), never the still picture again.
                with motion.lock:
                    painter.drawImage(self.rect(), motion.frame)
                painter.end()
                return
            painter.fillRect(self.rect(), QColor(self.background))
            if self.still_t > 0:
                try:
                    self.ensure_screen().draw(painter, self.still_t)
                except Exception:  # noqa: BLE001 - the background alone
                    pass
            painter.end()
            self.painted = True

    shell = Shell()
    shell.setGeometry(round(x), round(y), int(logical[0]), int(logical[1]))
    # Layered from its first frame, so the fade at the end changes nothing else about the window.
    shell.setWindowOpacity(0.999)
    return shell


def _start_motion(shell, meta: dict) -> None:
    """The launch screen moves from its own thread while the app loads (launch_motion; B2 since
    2026-11-23). Never raises."""
    try:
        from . import launch_motion
        if not launch_motion.enabled() or not shell.painted or not shell.isVisible():
            return
        scale = float(shell.devicePixelRatioF()) or 1.0
        base = shell.grab().toImage()
        if base.isNull():
            return
        screen = shell.ensure_screen()
        motion = launch_motion.LaunchMotion(
            shell, base, kind=shell.kind, scale=scale, screen=screen, colors=shell.colors,
            language=shell.language, background=shell.background, expected_s=_expected_load_s(meta))
        # Not layered while it moves: pixels copied into a layered window from the thread let the
        # desktop behind show through faintly (seen 2026-11-20). Layered again before a fade.
        shell.motion = motion
        shell.setWindowOpacity(1.0)
        shell.repaint()
        if not motion.start():
            shell.motion = None
            shell.still_t = 1.2
            shell.setWindowOpacity(0.999)
            shell.repaint()
    except Exception:  # noqa: BLE001 - the still picture stays
        try:
            shell.motion = None
        except RuntimeError:
            pass


def _expected_load_s(meta: dict):
    """How long the last start took (kept at its close), for the accent line's stages; or None."""
    try:
        value = float(meta.get('launch_s') or 0)
    except (TypeError, ValueError):
        return None
    return value if 0.3 <= value <= 30 else None


def _stop_motion(shell, *, layered: bool = True) -> float | None:
    """Stop the frames; the time the last one showed (s since the start), or None."""
    motion = getattr(shell, 'motion', None)
    if motion is None:
        return None
    motion.stop()
    shown = motion.elapsed()
    try:
        if layered and shell.isVisible():
            shell.setWindowOpacity(0.999)           # layered again for the fade, painted at once
            shell.repaint()
    except RuntimeError:
        pass
    return shown


def _fit_picture(grabbed, width: int, height: int, background: str):
    """The grab as exactly the client's pixels, or None. At fractional scales (the user's 175%)
    Qt's logical size times the scale is a pixel or two off the native window, so an exact-size
    rule never kept a picture there (2026-11-19)."""
    from PySide6.QtGui import QColor, QImage, QPainter
    if grabbed.isNull():
        return None
    image = grabbed.toImage()
    if (image.width(), image.height()) == (width, height):
        return image
    if abs(image.width() - width) > 3 or abs(image.height() - height) > 3:
        return None
    image.setDevicePixelRatio(1.0)                  # copied pixel for pixel, not scaled down
    fitted = QImage(width, height, QImage.Format.Format_RGB32)
    fitted.fill(QColor(background or '#000000'))
    painter = QPainter(fitted)
    painter.drawImage(0, 0, image)
    painter.end()
    return fitted


def _first_start_meta(app):
    """Where and in what colour the window opens when nothing was kept (the very first start):
    the saved place when there is one, else the default size in the middle of the main screen (as
    ``MainWindow._apply_sane_initial_geometry`` does), in the chosen theme's background."""
    try:
        from PySide6.QtCore import QRect, QSettings
        screen = app.primaryScreen()
        if screen is None:
            return None
        avail = screen.availableGeometry()
        settings = QSettings('2ByteASR', '2ByteASR')
        saved = settings.value('mainWindow/geometry')
        maximized = str(settings.value('mainWindow/maximized')).lower() in {'true', '1'}
        width, height = max(320, min(1320, avail.width() - 16)), max(200, min(880, avail.height() - 16))
        rect = QRect(0, 0, width, height)
        rect.moveCenter(avail.center())
        if maximized:
            rect = QRect(avail)
        elif isinstance(saved, (list, tuple)) and len(saved) >= 4:
            candidate = QRect(*(int(value) for value in saved[:4]))
            if avail.contains(candidate.center()) and candidate.width() >= 320 and candidate.height() >= 200:
                rect = candidate
        from ..design.ui_theme import DEFAULT_THEME_KEY, THEMES
        key = str(settings.value('appearance/theme') or DEFAULT_THEME_KEY)
        theme = THEMES.get(key) or THEMES[DEFAULT_THEME_KEY]
        return dict(geometry=(rect.x(), rect.y(), rect.width(), rect.height()), theme=str(theme.key),
                    background=str(theme.app_background), maximized=maximized)
    except Exception:  # noqa: BLE001
        return None


def _place(shell, meta: dict, *, size: bool = True) -> None:
    """Exactly over the main window's old client area, in physical pixels; rounded like it."""
    try:
        hwnd = int(shell.winId())
        x, y, width, height = (int(value) for value in meta['client'])
        flags = 0x0004 | 0x0010 | 0x0200                       # NOZORDER | NOACTIVATE | NOOWNERZORDER
        _user32().SetWindowPos(hwnd, None, x, y, width, height, flags if size else flags | 0x0001)
        _dwm_set(hwnd, 3, 1)                                   # no system open/close animation
        if not meta.get('maximized'):
            _dwm_set(hwnd, 33, 2)                              # Windows 11: rounded like the real window
    except Exception:  # noqa: BLE001 - Qt's own geometry stays
        pass


def adopt(window) -> None:
    """The real window is about to be shown: the picture stays above it until it has painted."""
    global _WINDOW
    shell = _SHELL
    if shell is None:
        return
    _WINDOW = window
    try:
        # Topmost from here until the real window has painted (a moment), so the real window is
        # never seen empty. Not as the real window's owned window: measured 2026-11-19, a window
        # fully covered by a window it owns gets no first paint at all.
        _user32().SetWindowPos(int(shell.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)   # HWND_TOPMOST
    except Exception:  # noqa: BLE001
        pass


def dismiss(fade: bool = True) -> None:
    """The real window is on screen (or the start failed: ``fade=False``): the picture goes - the
    wordmark flying onto Home's title as Home appears under it (``_land``), else fading out over
    the real window (``LAUNCH_HANDOFF``) where motion is on."""
    global _SHELL, _LOAD_S, _WINDOW
    release_cover()
    shell, _SHELL = _SHELL, None
    window, _WINDOW = _WINDOW, None
    if shell is None:
        return
    if fade and _SHOWN_AT is not None and _LOAD_S is None:
        _LOAD_S = time.perf_counter() - _SHOWN_AT          # kept at the close for the next start's stages
    try:
        if fade and _land(shell, window):
            return
        _stop_motion(shell)                 # holds still while it fades, as the native launcher does
        if fade and _fade_out(shell):
            return
        shell.hide()
        shell.deleteLater()
    except RuntimeError:
        pass


def _brand_targets(shell, window) -> dict | None:
    """Where each half of the wordmark lands, in the launch window's logical coordinates: 'en' on
    Home's brand label (2ByteASR), 'zh' on 「兔白字幕」 next to it; their text areas. None unless both
    are on the screen."""
    from PySide6.QtCore import QRect
    targets = {}
    for prefix, name in (('en', 'brand'), ('zh', 'header_subtitle')):
        widget = getattr(window, name, None)
        try:
            if widget is None or not widget.isVisible() or widget.width() < 4:
                return None
            inner = widget.contentsRect()
            at = shell.mapFromGlobal(widget.mapToGlobal(inner.topLeft()))
            # As wide as its text reads (the label can be wider): the halves land letter on letter.
            width = min(inner.width(), max(1, round(_text_width(widget))))
            rect = QRect(at, inner.size())
            rect.setWidth(width)
        except RuntimeError:
            return None
        if not QRect(0, 0, shell.width(), shell.height()).contains(rect.center()):
            return None
        targets[prefix] = (float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()))
    return targets


def _text_width(label) -> float:
    """How wide ``label``'s text is drawn (rich text, like the brand, through a text document)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetricsF, QTextDocument
    text = label.text()
    rich = label.textFormat() == Qt.TextFormat.RichText or (
        label.textFormat() == Qt.TextFormat.AutoText and text.lstrip().startswith('<'))
    if rich:
        document = QTextDocument()
        document.setDefaultFont(label.font())
        document.setDocumentMargin(0)
        document.setHtml(text)
        return document.idealWidth()
    return QFontMetricsF(label.font()).horizontalAdvance(text)


def settle_layout(window) -> None:
    """Bring ``window``'s layout up to date before a picture of it is taken: its own pending
    responsive passes (``settle_for_picture``), then every queued layout request."""
    from PySide6.QtCore import QCoreApplication, QEvent
    try:
        settle = getattr(window, 'settle_for_picture', None)
        # 2026-11-27: three rounds - a pass of the settle (the zoom, the cards' names) can change
        # sizes that the next round's layout and passes depend on.
        for _round in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            if callable(settle):
                settle()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    except Exception:  # noqa: BLE001 - a picture slightly off is better than no start
        pass


def _land(shell, window) -> bool:
    """B2's end (2026-11-23): the launch screen's drawer draws Home coming in under it and the
    wordmark flying onto Home's title, ending on Home's picture; then the window goes. The drawer
    (the helper process) keeps going while the GUI thread is busy with Home's first moments, so a
    late ``hide`` shows nothing but Home. False when it cannot (no motion, no title): the caller
    fades as before."""
    try:
        from ..design import motion_tokens as tokens
        from ..design.transitions import enabled
        motion = getattr(shell, 'motion', None)
        if (window is None or motion is None or not enabled() or not shell.isVisible()
                or os.environ.get('TWOBYTEASR_LAUNCH_FADE', '1') == '0'
                or not window.isVisible() or window.isMinimized()):
            return False
        # 2026-11-27 (user: for the first two seconds Home looked broken — the header's buttons cut
        # to two characters, the left card narrow beside an empty gap): the picture was grabbed at
        # Home's first paint, while the layout of its final (often just maximized) size was still
        # queued, and the drawer showed that stale picture until the flight ended. Settle first.
        settle_layout(window)
        targets = _brand_targets(shell, window)
        if targets is None:
            return False
        picture = window.grab().toImage()
        if picture.isNull():
            return False
        from PySide6.QtCore import QPoint, Qt, QTimer
        at = shell.mapFromGlobal(window.mapToGlobal(QPoint(0, 0)))
        if not motion.land(picture, (float(at.x()), float(at.y())), targets):
            return False
        _click_through(shell)                   # clicks reach the real window during the flight
        shell.setCursor(Qt.CursorShape.ArrowCursor)
        began = time.perf_counter()
        limit = (tokens.PAGE_IN.ms + LAND_GRACE_MS) / 1000
        timer = QTimer(shell)
        timer.setTimerType(Qt.TimerType.PreciseTimer)

        def check():
            if not motion.landed() and time.perf_counter() - began < limit:
                return
            timer.stop()
            motion.stop()
            shell.hide()
            shell.deleteLater()
            if shell in _FADING:
                _FADING.remove(shell)

        timer.timeout.connect(check)
        _FADING.append(shell)
        timer.start(16)
        return True
    except Exception:  # noqa: BLE001 - fades as before
        return False


def release_cover() -> None:
    """Tell the launcher that the real window is on the screen (or the start failed): its
    skeleton fades out. Once; never raises."""
    global _COVER_EVENT
    name, _COVER_EVENT = _COVER_EVENT, ''
    if not name or sys.platform != 'win32':
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.OpenEventW.restype = wintypes.HANDLE
        kernel.SetEvent.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenEventW(0x0002, False, name)              # EVENT_MODIFY_STATE
        if handle:
            kernel.SetEvent(handle)
            kernel.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass


# Home's parts the launcher draws, by object name (several widgets may share one), and how.
_COVER_NAMES = (('mediaRow', 'dash'), ('studioEntryCard', 'panel'), ('homeRecentHero', 'block'),
                ('studioEntryPrimary', 'block'), ('homeSettingsCard', 'panel'), ('recognitionRoleCard', 'block'),
                ('homeAiCard', 'block'), ('homeContentBody', 'block'), ('homeLanguageField', 'block'))


def cover_parts(window) -> list:
    """``(kind, x, y, width, height)`` of Home's parts in the window's coordinates, back to front."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget
    parts = []

    def add(kind, widget):
        try:
            if widget is None or not widget.isVisible() or widget.width() < 8 or widget.height() < 8:
                return
            at = widget.mapTo(window, QPoint(0, 0))
            x, y, width, height = at.x(), at.y(), widget.width(), widget.height()
            if isinstance(widget, QLabel) and widget.text():
                # A line of text: as tall as the text, as wide as it reads, where it sits.
                metrics = widget.fontMetrics()
                text_height = min(height, metrics.height())
                width = min(width, metrics.horizontalAdvance(widget.text()) + 4)
                y += (height - text_height) // 2
                height = text_height
            parts.append((kind, x, y, width, height))
        except RuntimeError:
            pass

    add('bar', getattr(window, 'app_header', None))
    header = getattr(window, 'header_content', None)
    mascot = getattr(window, 'header_mascot', None)
    if header is not None:
        for widget in header.findChildren(QWidget):
            if widget is not mascot and isinstance(widget, (QAbstractButton, QLabel)) and widget.width() >= 30 \
                    and not any(isinstance(parent, QAbstractButton) for parent in _ancestors(widget, header)):
                add('pill', widget)
    home = getattr(window, 'settings_scroll', None)
    if home is not None:
        for name, kind in _COVER_NAMES:
            for widget in home.findChildren(QWidget, name):
                add(kind, widget)
    bar = getattr(window, 'bottom_bar', None)
    add('bar', bar)
    if bar is not None:
        for widget in bar.findChildren(QAbstractButton, 'primary'):
            add('block', widget)
    return parts


def _ancestors(widget, stop):
    parent = widget.parentWidget()
    while parent is not None and parent is not stop:
        yield parent
        parent = parent.parentWidget()


def _cover_text(meta: dict, parts: list, theme) -> str:
    client = ' '.join(str(int(value)) for value in meta['client'])
    lines = [f'format {COVER_FORMAT}', f"next_page {meta['next_page']}", f'client {client}',
             f"scale {meta['scale']}", f"maximized {1 if meta['maximized'] else 0}",
             f'colors {theme.app_background} {theme.panel} {theme.surface} {theme.surface_elevated} {theme.border_strong}']
    lines += [f'part {kind} {x} {y} {width} {height}' for kind, x, y, width, height in parts]
    return '\n'.join(lines) + '\n'


def _click_through(shell) -> None:
    try:
        import ctypes
        from ctypes import wintypes
        user = _user32()
        user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        hwnd = int(shell.winId())
        user.SetWindowLongPtrW(hwnd, -20, user.GetWindowLongPtrW(hwnd, -20) | 0x00080000 | 0x00000020)
    except Exception:  # noqa: BLE001
        pass


def _fade_out(shell) -> bool:
    try:
        from ..design import motion_tokens as tokens
        from ..design.transitions import enabled
        if not enabled() or os.environ.get('TWOBYTEASR_LAUNCH_FADE', '1') == '0' or not shell.isVisible():
            return False
        from PySide6.QtCore import Qt, QTimer
        _click_through(shell)                   # clicks reach the real window during the fade
        shell.setCursor(Qt.CursorShape.ArrowCursor)
        curve = tokens.easing_curve(tokens.LAUNCH_HANDOFF)
        began = time.perf_counter()
        timer = QTimer(shell)
        timer.setTimerType(Qt.TimerType.PreciseTimer)

        def step():
            progress = (time.perf_counter() - began) * 1000 / tokens.LAUNCH_HANDOFF.ms
            if progress >= 1.0:
                timer.stop()
                shell.hide()
                shell.deleteLater()
                if shell in _FADING:
                    _FADING.remove(shell)
                return
            shell.setWindowOpacity(max(0.0, 0.999 * (1.0 - curve.valueForProgress(progress))))

        timer.timeout.connect(step)
        _FADING.append(shell)
        timer.start(8)
        return True
    except Exception:  # noqa: BLE001
        return False


def showing() -> bool:
    return _SHELL is not None


# ---------------------------------------------------------------------------- keeping it
def _conditions(window) -> dict:
    """What the picture depends on besides the window's place."""
    from ..design.theme_manager import theme_definition, theme_key
    from ..i18n import current_language
    from . import ui_zoom
    key = theme_key()
    theme = theme_definition(key)
    return dict(theme=str(key), language=str(getattr(window, '_ui_language', None) or current_language()),
                zoom=int(ui_zoom.zoom_percent()), background=str(theme.app_background), foreground=str(theme.text_muted))


def _home_is_clean(window) -> bool:
    """Home as a start shows it: on top, nothing over it, nothing chosen yet."""
    from ..design import transitions
    home = getattr(window, 'settings_scroll', None)
    if home is None or window.pages.currentWidget() is not home:
        return False
    if window.isMinimized() or window.isFullScreen() or not window.isVisible():
        return False
    if getattr(window, '_recognition_page_deferred', False):
        return False
    modal = getattr(window, '_modal_host', None)
    if modal is not None and modal.isVisible():
        return False
    if transitions._ACTIVE_FADES or home.verticalScrollBar().value() != 0:
        return False
    if getattr(window, 'media_paths', None) or getattr(window, '_run_in_progress', False):
        return False
    return True


def _next_page() -> str:
    """Where a start without files opens (the preference in the settings)."""
    try:
        from .application_settings import read_studio_preferences
        from .external_open import startup_destination
        return str(startup_destination((), read_studio_preferences()))
    except Exception:  # noqa: BLE001
        return 'recognition'


def remember(window, *, next_page: str | None = None, take_picture: bool = True) -> bool:
    """Keep the window's place and, where Home is clean, its picture and skeleton. GUI thread; the
    files are written by a thread (``flush`` waits for it before the process ends). True when a
    picture or a skeleton was kept."""
    global _WRITER
    try:
        if not enabled():
            return False
        from . import floating_anchor
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        client = floating_anchor.client_pixels(window)
        if client is None or app is None:
            return False
        conditions = _conditions(window)
        hwnd = int(window.internalWinId() or 0)
        maximized = bool(hwnd and _user32().IsZoomed(hwnd))
        meta = dict(format=FORMAT, program=program_stamp(), screens=screens_signature(app), client=list(client),
                    scale=round(float(window.devicePixelRatioF()), 4), maximized=maximized,
                    next_page=str(next_page or _next_page()), saved=time.time(), picture=False, **conditions)
        previous = read() or {}
        if _LOAD_S is not None:
            meta['launch_s'] = round(_LOAD_S, 2)
        elif previous.get('launch_s'):
            meta['launch_s'] = previous['launch_s']
        key = [meta[name] for name in _PICTURE_KEY]
        image = None
        cover = None
        if take_picture and _home_is_clean(window):
            try:
                from ..design.theme_manager import theme_definition
                parts = cover_parts(window)
                if len(parts) >= 3:
                    cover = _cover_text(meta, parts, theme_definition(conditions['theme']))
            except Exception:  # noqa: BLE001 - the launcher then shows nothing of its own
                cover = None
            # Render only Home so overlapping applications cannot enter the cache.
            image = _fit_picture(window.grab(), int(client[2]), int(client[3]), conditions['background'])
        same = [previous.get(name) for name in _PICTURE_KEY] == key
        # Without a new picture (or skeleton) the old one stays only while everything it depends
        # on is the same; a close on another page keeps the skeleton as well as the picture.
        meta['picture'] = image is not None or bool(previous.get('picture') and same)
        directory = _directory()

        def write():
            try:
                directory.mkdir(parents=True, exist_ok=True)
                if cover is not None:
                    temporary = directory / 'cover.tmp.txt'
                    temporary.write_text(cover, 'utf8')
                    os.replace(temporary, directory / 'cover.txt')
                elif not same:
                    (directory / 'cover.txt').unlink(missing_ok=True)
                elif (directory / 'cover.txt').is_file():
                    _refresh_cover_header(directory / 'cover.txt', meta)
                if image is not None:
                    temporary = directory / 'home.tmp.bmp'
                    if image.save(str(temporary), 'BMP'):
                        os.replace(temporary, directory / 'home.bmp')
                    else:
                        meta['picture'] = False
                elif not meta['picture']:
                    (directory / 'home.bmp').unlink(missing_ok=True)
                temporary = directory / 'meta.tmp.json'
                temporary.write_text(json.dumps(meta, ensure_ascii=False), 'utf8')
                os.replace(temporary, directory / 'meta.json')
            except OSError:
                pass

        flush(0.5)
        if _WRITER is not None and _WRITER.is_alive():
            return False
        _WRITER = threading.Thread(target=write, name='launch-picture', daemon=True)
        _WRITER.start()
        return image is not None or cover is not None
    except Exception:  # noqa: BLE001 - keeping the picture never gets in the way of closing
        return False


def _refresh_cover_header(path: Path, meta: dict) -> None:
    """A kept layout (still valid: same place, size, theme) with the start page chosen now."""
    try:
        lines = path.read_text('utf8').splitlines()
        lines = [f"next_page {meta['next_page']}" if line.startswith('next_page ') else line for line in lines]
        path.write_text('\n'.join(lines) + '\n', 'utf8')
    except OSError:
        pass


def flush(timeout: float = 2.0) -> None:
    """Wait for a picture still being written (before the process is ended)."""
    writer = _WRITER
    if writer is not None and writer.is_alive():
        writer.join(timeout)


__all__ = ['adopt', 'cover_parts', 'dismiss', 'enabled', 'flush', 'read', 'read_cover', 'release_cover', 'remember', 'show',
           'showing', 'usable']
