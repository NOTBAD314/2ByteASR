"""The launch screen keeps moving while the app loads (2026-11-20, B2 since 2026-11-23).

User (2026-11-20): the loading screen at start is still plain - a still picture looks cheap; a
loading animation that keeps going would feel more refined.

The launch window (``launch_picture``) is shown before the heavy imports and the main window are
built, and that work holds the GUI thread for a second or more, so nothing Qt animates there can
move. This thread draws the frames itself: it paints into a ``QImage`` (painting on an image is
allowed outside the GUI thread) and copies the changed pixels straight into the launch window's
device context (``StretchDIBits``), which Windows allows from any thread. Python switches threads
every few milliseconds, so the loading work is not held up noticeably (measured, see the plan).

What moves is ``launch_screen.LaunchScreen`` (B2 「音波時間軸」, the user's pick of 2026-11-23,
replacing Home's glowing skeleton): the wordmark comes in glyph by glyph, the timeline card's
playhead moves on as the start goes through its stages (catching up on the VALUE spring), the
waveform lights up where it has passed and cues drop onto the timeline.

Every frame is a function of the time since the start alone (``_draw(t)``), so the thread and the
helper process draw the same picture at the same moment. Durations and curves come only from
``design/motion_tokens.py``.

At the end (``land``) the same drawer draws the wordmark's flight onto Home's title over a picture
of the real window, ending on that picture alone: the helper process keeps drawing while the GUI
thread is busy with Home's first moments, and if the window goes a little late nothing is seen.

The window's own paint draws the latest frame (``frame``), so a repaint never shows the still
picture. ``stop`` ends it before the window fades or goes; nothing is drawn after it returns.
Windows only; ``TWOBYTEASR_LAUNCH_MOTION=0`` turns it off.
"""
from __future__ import annotations

import math
import os
import sys
import threading
import time

FRAME_S = 1 / 60
SWITCH_INTERVAL_S = 0.001
# The start's stages, as shares of the time the last start took (``expected_s``), and how far the
# playhead heads during each; it waits at the last value until the real window takes over.
STAGE_AT = (0.0, 0.18, 0.5, 0.8)
STAGE_VALUE = (0.12, 0.38, 0.66, 0.9)
EXPECTED_S = 3.0               # without a measured start


def enabled() -> bool:
    return sys.platform == 'win32' and os.environ.get('TWOBYTEASR_LAUNCH_MOTION', '1') != '0'


def progress_at(t: float, expected_s: float | None = None) -> float:
    """The playhead's place (0..1) ``t`` s after the start: the VALUE spring (no overshoot)
    catching up with each stage's value in turn. A function of ``t`` alone (both drawers agree)."""
    from ..design import motion_tokens as tokens
    expected = float(expected_s or EXPECTED_S)
    omega = 2 * math.pi / tokens.VALUE.response
    x = v = 0.0
    previous = 0.0
    for index, target in enumerate(STAGE_VALUE):
        end = STAGE_AT[index + 1] * expected if index + 1 < len(STAGE_AT) else math.inf
        until = min(max(t, 0.0), end)
        dt = until - previous
        if dt > 0:
            # Critically damped (damping 1.0): exact over any step.
            x0, decay = x - target, math.exp(-omega * dt)
            x, v = target + (x0 + (v + omega * x0) * dt) * decay, (v - omega * (v + omega * x0) * dt) * decay
        previous = until
        if t <= end:
            break
    return max(0.0, min(1.0, x))


class LaunchMotion:
    """Draws the moving launch screen into ``shell``'s native window from its own thread.

    ``screen``: the ``launch_screen.LaunchScreen`` to draw (its sprites travel to the helper
    process as files); ``colors`` and ``language`` are what it was made from."""

    def __init__(self, shell, base, *, kind: str, scale: float, screen=None, colors=None, language=None,
                 background=None, began: float | None = None, expected_s: float | None = None):
        from PySide6.QtGui import QColor, QImage
        self.hwnd = int(shell) if isinstance(shell, int) else int(shell.winId())
        self.kind = kind
        self.screen = screen
        self.colors = dict(colors or {})
        self.language = language
        self._began = time.perf_counter() if began is None else float(began)
        self._full = True                                  # the first copy is the whole window
        self._handed_over = threading.Event()              # the helper process draws from now on
        self._helper = None
        self._helper_folder = None
        self._helper_done = threading.Event()
        self.expected_s = float(expected_s or EXPECTED_S)
        self.background_name = str(background or self.colors.get('background') or '#19151c')
        self.scale = float(scale) or 1.0
        self.base = base.convertToFormat(QImage.Format.Format_RGB32)
        self.base.setDevicePixelRatio(self.scale)
        self.frame = self.base.copy()
        self.frame.setDevicePixelRatio(self.scale)
        self.width = self.frame.width() / self.scale       # logical
        self.height = self.frame.height() / self.scale
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._area = screen.area() if screen is not None else None
        self.background = QColor(self.background_name)
        self._bits = None
        self._info = None
        self.frames = 0                                    # drawn so far (for measurements)
        self.last_t = 0.0                                  # the time of the frame on the screen
        self._landing = None                               # the end's flight, once ``begin_landing`` ran
        self._landed = threading.Event()                   # its last frame (Home alone) is up
        # TWOBYTEASR_LAUNCH_MOTION_LOG=<folder>: each drawer writes its frame times there (measuring).
        self.frame_log = [] if os.environ.get('TWOBYTEASR_LAUNCH_MOTION_LOG') else None

    def write_frame_log(self, name: str) -> None:
        folder = os.environ.get('TWOBYTEASR_LAUNCH_MOTION_LOG')
        if not folder or self.frame_log is None:
            return
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f'{name}-{os.getpid()}.txt'), 'w', encoding='utf-8') as handle:
                handle.write('\n'.join(f'{value:.4f}' for value in self.frame_log))
        except OSError:
            pass

    def elapsed(self) -> float:
        """Seconds since the start, as the frames count them."""
        return time.perf_counter() - self._began

    # ------------------------------------------------------------ the end
    def begin_landing(self, picture, at, targets: dict, t: float) -> None:
        """Draw the end from the next frame on (``LaunchScreen.draw_landing``)."""
        with self.lock:
            self._landing = dict(began=time.perf_counter(), picture=picture, at=tuple(at), targets=dict(targets),
                                 t=float(t))

    def land(self, picture, at, targets: dict) -> bool:
        """Main process: start the end on whichever drawer is running. False: nothing draws (the
        caller fades as before). ``picture``: the real window as a QImage at the screen's scale."""
        import json
        if self.screen is None or self._stop.is_set():
            return False
        t = self.elapsed()
        helper = self._helper
        folder = self._helper_folder
        if self._handed_over.is_set() and folder and helper is not None and helper.poll() is None:
            try:
                path = os.path.join(folder, 'home.bmp')
                if not picture.save(path, 'BMP'):
                    return False
                order = os.path.join(folder, 'land.json')
                with open(order, 'w', encoding='utf-8') as handle:
                    json.dump(dict(at=list(at), targets=targets, t=t), handle)
                helper.stdin.write(b'land\n')
                helper.stdin.flush()
                return True
            except (OSError, ValueError):
                return False
        if helper is not None and not self._handed_over.is_set():
            # Not drawing yet: it must not take over in the middle of the end.
            try:
                helper.kill()
            except OSError:
                pass
            self._helper = None
            self._helper_done.set()
        if not self.running():
            return False
        self.begin_landing(picture, at, targets, t)
        return True

    def landed(self) -> bool:
        return self._landed.is_set()

    # ------------------------------------------------------------ running
    def start(self, *, helper: bool = True) -> bool:
        try:
            self._prepare_blit()
        except Exception:  # noqa: BLE001 - the still picture stays
            return False
        # Python hands the interpreter to another thread every 5 ms by default; the loading work
        # on the GUI thread then left this one about 13 frames a second (measured). 1 ms gives it
        # its turn on time; set back when it stops.
        self._interval = sys.getswitchinterval()
        sys.setswitchinterval(min(self._interval, SWITCH_INTERVAL_S))
        self._thread = threading.Thread(target=self._run, args=(helper,), name='launch-motion', daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 0.25) -> None:
        """No frame is drawn after this returns (the window may fade or go)."""
        self._stop.set()
        with self.lock:
            pass                                           # a frame being drawn has finished
        interval = getattr(self, '_interval', None)
        if interval is not None:
            self._interval = None
            sys.setswitchinterval(interval)
        helper = self._helper
        if helper is not None:
            try:
                helper.stdin.write(b'stop\n')
                helper.stdin.flush()
            except (OSError, ValueError):
                pass
            if not self._helper_done.wait(timeout):        # it says 'stopped' after its last frame
                try:
                    helper.kill()
                except OSError:
                    pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self.write_frame_log('main')

    # ------------------------------------------------------------ the helper process
    def _start_helper(self) -> None:
        """2026-11-20, measured in a real start: the main process's imports and window building
        hold Python's lock for up to 0.7 s at a time, so this thread drew 5-8 frames a second.
        A small process of the app itself (``--launch-motion``) draws the same frames into the
        same window with a lock of its own and takes over once its first frame is up; both count
        time from the same moment, so the hand-over is not seen."""
        import json
        import subprocess
        import tempfile
        if self.screen is None:
            return
        # The parent owns the directory and its cleanup. The worker receives
        # fixed filenames and never deletes paths supplied through its CLI or pipe.
        directory = tempfile.TemporaryDirectory(prefix='2byteasr-launch-', ignore_cleanup_errors=True)
        folder = directory.name
        base_path = os.path.join(folder, 'base.bmp')
        if not self.base.save(base_path, 'BMP'):
            return
        self.screen.sprites.save(folder)
        payload = dict(hwnd=self.hwnd, kind=self.kind, scale=self.scale, began=self._began, base=base_path,
                       colors=self.colors, language=self.language, background=self.background_name,
                       expected_s=self.expected_s, parent=os.getpid())
        path = os.path.join(folder, 'motion.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        if getattr(sys, 'frozen', False):
            command = [sys.executable, '--launch-motion', path]
        else:
            python = sys.executable
            windowless = os.path.join(os.path.dirname(python), 'pythonw.exe')
            entry = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                 'quick_start.py')
            command = [windowless if os.path.isfile(windowless) else python, entry, '--launch-motion', path]
        if self._stop.is_set():
            return
        self._helper_folder = folder
        self._helper = helper = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                 stderr=subprocess.DEVNULL, creationflags=0x08000000)  # NO_WINDOW
        if self._stop.is_set():                            # stopped while it was being started
            helper.kill()

        def listen():
            try:
                for line in helper.stdout:
                    word = line.strip()
                    if word == b'ready':
                        self._handed_over.set()
                    elif word == b'landed':
                        self._landed.set()
                    elif word == b'stopped':
                        break
            except (OSError, ValueError):
                pass
            finally:
                helper.wait()
                directory.cleanup()
                self._helper_done.set()

        threading.Thread(target=listen, name='launch-motion-helper', daemon=True).start()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def _run(self, helper: bool = False, on_frame=None) -> None:
        import ctypes
        winmm = None
        try:
            winmm = ctypes.WinDLL('winmm')
            winmm.timeBeginPeriod(1)                       # 1 ms sleeps (Python 3.10 sleeps in 15.6 ms steps)
        except OSError:
            winmm = None
        try:
            user = ctypes.WinDLL('user32')
            user.IsWindow.argtypes = [ctypes.c_void_p]
            user.IsWindowVisible.argtypes = [ctypes.c_void_p]
            next_at = time.perf_counter()
            helper_due = helper
            while not self._stop.is_set() and not self._handed_over.is_set():
                if not user.IsWindow(self.hwnd):
                    break
                if helper_due and self.frames >= 2:        # after this thread's first frames are up
                    helper_due = False
                    try:
                        self._start_helper()
                    except Exception:  # noqa: BLE001 - this thread keeps drawing
                        self._helper = None
                if on_frame is not None and self.frames == 1:
                    on_frame()
                with self.lock:
                    if self._stop.is_set():
                        break
                    if user.IsWindowVisible(self.hwnd):
                        rects = self._draw(time.perf_counter() - self._began)
                        self._blit(rects)
                        self.frames += 1
                        if self.frame_log is not None:
                            self.frame_log.append(time.perf_counter())
                if self._landed.is_set():
                    break                                  # Home's picture is up: nothing more to draw
                next_at += FRAME_S
                wait = next_at - time.perf_counter()
                if wait < -FRAME_S * 4:                     # far behind (the GIL was busy): no catching up
                    next_at = time.perf_counter()
                    wait = 0.0
                if wait > 0:
                    self._stop.wait(wait)
        except Exception:  # noqa: BLE001 - motion never breaks the start
            pass
        finally:
            if winmm is not None:
                try:
                    winmm.timeEndPeriod(1)
                except OSError:
                    pass

    # ------------------------------------------------------------ one frame
    def _draw(self, t: float) -> list:
        """Paint the frame for time ``t`` (s); the logical rects whose pixels changed."""
        from PySide6.QtGui import QPainter
        if self.screen is None or self._area is None:
            return []
        landing = self._landing
        if landing is not None:
            from PySide6.QtCore import QRectF
            ms = (time.perf_counter() - landing['began']) * 1000
            painter = QPainter(self.frame)
            try:
                self.screen.draw_landing(painter, ms, landing['picture'], landing['at'], landing['targets'], landing['t'])
            finally:
                painter.end()
            if ms >= self.screen.landing_ms():
                self._landed.set()
            return [QRectF(0, 0, self.width, self.height)]
        painter = QPainter(self.frame)
        try:
            area = self._area
            # The still background comes back under the moving screen, then the screen at ``t``.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(area, self.base, self._device(area))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self.screen.draw(painter, t)
        finally:
            painter.end()
        self.last_t = t
        return [area]

    def _device(self, rect):
        from PySide6.QtCore import QRectF
        s = self.scale
        return QRectF(rect.x() * s, rect.y() * s, rect.width() * s, rect.height() * s)

    # ------------------------------------------------------------ to the screen
    def _prepare_blit(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                        ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD),
                        ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                        ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                        ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]

        frame = self.frame
        if frame.bytesPerLine() != frame.width() * 4:
            raise ValueError('unexpected stride')
        info = BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.biWidth = frame.width()
        info.biHeight = -frame.height()                    # top-down, as QImage stores it
        info.biPlanes = 1
        info.biBitCount = 32
        info.biCompression = 0                             # BI_RGB
        self._info = info
        view = frame.bits()                                # detaches now, once; painted in place later
        self._view = view
        self._bits = (ctypes.c_char * (frame.bytesPerLine() * frame.height())).from_buffer(view)
        self._user = ctypes.WinDLL('user32')
        self._user.GetDC.restype = ctypes.c_void_p
        self._user.GetDC.argtypes = [ctypes.c_void_p]
        self._user.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._gdi = ctypes.WinDLL('gdi32')
        self._gdi.StretchDIBits.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 8 + [
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]

    def _blit(self, rects) -> None:
        import ctypes
        if self._full:
            from PySide6.QtCore import QRectF
            self._full = False
            rects = [QRectF(0, 0, self.width, self.height)]
        if not rects:
            return
        hdc = self._user.GetDC(self.hwnd)
        if not hdc:
            return
        try:
            w, h = self.frame.width(), self.frame.height()
            for rect in rects:
                device = self._device(rect).toAlignedRect().intersected(self.frame.rect())
                if device.isEmpty():
                    continue
                x, y, cw, ch = device.x(), device.y(), device.width(), device.height()
                # StretchDIBits counts the source rows from the bottom even for a top-down DIB
                # (seen 2026-11-20: a partial copy landed mirrored about the middle).
                self._gdi.StretchDIBits(hdc, x, y, cw, ch, x, h - y - ch, cw, ch, ctypes.addressof(self._bits),
                                        ctypes.addressof(self._info), 0, 0x00CC0020)    # DIB_RGB_COLORS, SRCCOPY
        finally:
            self._user.ReleaseDC(self.hwnd, hdc)


def child_main(payload_path: str) -> int:
    """``--launch-motion <json>``: draw the launch screen's frames into the main process's launch
    window until told to stop (stdin), the window is gone, or the main process ends."""
    import ctypes
    import json
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # physical pixels
    except (AttributeError, OSError):
        pass
    folder = os.path.dirname(os.path.abspath(payload_path))
    try:
        with open(payload_path, encoding='utf-8') as handle:
            payload = json.load(handle)
        from PySide6.QtGui import QImage
        from .launch_screen import LaunchScreen, Sprites
        base = QImage(payload['base'])
        if base.isNull():
            return 1
        scale = float(payload.get('scale') or 1.0)
        colors = dict(payload.get('colors') or {})
        expected = payload.get('expected_s')
        screen = LaunchScreen(base.width() / scale, base.height() / scale, colors, Sprites.load(folder),
                              payload.get('language'), expected)
        motion = LaunchMotion(int(payload['hwnd']), base, kind=str(payload.get('kind') or ''), scale=scale,
                              screen=screen, colors=colors, language=payload.get('language'),
                              background=payload.get('background'), began=float(payload['began']),
                              expected_s=expected)
        motion._prepare_blit()

        def listen():
            try:
                for line in sys.stdin.buffer:
                    word = line.strip()
                    if word == b'stop':
                        break
                    if word == b'land':
                        try:
                            with open(os.path.join(folder, 'land.json'), encoding='utf-8') as handle:
                                order = json.load(handle)
                            picture = QImage(os.path.join(folder, 'home.bmp'))
                            if picture.isNull():
                                break
                            picture.setDevicePixelRatio(scale)
                            targets = {key: tuple(value) for key, value in order['targets'].items()}
                            motion.begin_landing(picture, order['at'], targets, order['t'])
                        except (OSError, ValueError, KeyError):
                            break                          # the main process fades instead
            except (OSError, ValueError):
                pass
            motion._stop.set()                             # told to stop, or the main process ended

        threading.Thread(target=listen, daemon=True).start()

        def announce():
            sys.stdout.write('ready\n')
            sys.stdout.flush()

        deadline = threading.Timer(60.0, motion._stop.set)  # never outlives a start by much
        deadline.daemon = True
        deadline.start()
        motion._run(on_frame=announce)
        if motion.landed():
            sys.stdout.write('landed\n')
        sys.stdout.write('stopped\n')
        sys.stdout.flush()
        motion.write_frame_log('helper')
        return 0
    except Exception:  # noqa: BLE001 - the main process keeps its own still picture
        return 1


def theme_accent(meta: dict) -> str:
    try:
        from ..design.ui_theme import DEFAULT_THEME_KEY, THEMES
        theme = THEMES.get(str(meta.get('theme') or '')) or THEMES[DEFAULT_THEME_KEY]
        return str(theme.accent)
    except Exception:  # noqa: BLE001
        return '#d9538f'


__all__ = ['LaunchMotion', 'enabled', 'progress_at', 'theme_accent']
