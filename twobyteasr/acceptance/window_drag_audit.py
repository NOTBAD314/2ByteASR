"""Opt-in real-window check: moving a tall main window (2026-10-22).

User report (video): on a 1920x1080 screen the main window, almost as tall as
the work area, could not be dragged down; it snapped back and kept twitching.
``WindowBounds`` pushed the window back inside the screen on every move event
while Windows' own move loop kept moving it to the cursor.

The private desktop gets no mouse input, so the check opens the same native
move loop through the keyboard (``SC_MOVE``) and samples the HWND rect every
few milliseconds. Live part: inside that loop the HWND is moved the way
full-window dragging moves it on every mouse move; it must never jump back.
Hook part: a real keyboard move reaches ``WindowBounds`` as Windows'
move/size start and end events. Drop part: without "show window contents
while dragging" Windows sends start, one move at the drop, end; that drop is
kept while the title strip is reachable (also partly past the left edge), a
title dropped out of reach comes back, and a window moved by Windows or the
program instead still goes fully back inside. Runs on the 模型工坊 page (as in
the video) and re-checks decision 0121 there: a maximized window moved to
another monitor, minimize and restore.
"""
import ctypes
import json
import os
import sys
import time
import traceback
from ctypes import wintypes


WM_SYSCOMMAND, SC_MOVE = 0x0112, 0xF010
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
VK_RETURN, VK_ESCAPE, VK_DOWN = 0x0D, 0x1B, 0x28
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', wintypes.RECT)]


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QRect, QTimer
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..app.window_constraints import native_frame, restore_minimized_window

    app = QApplication.instance()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pid': os.getpid(), 'executable': sys.executable, 'records': []}
            self.samples = None
            self.samples_in_loop_only = False
            self.sampler = QTimer(self)
            self.sampler.timeout.connect(self.sample)
            self.sampler.start(4)
            self.steps = self.run()
            self.wait_until = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})

        def tick(self):
            if time.monotonic() < self.wait_until:
                return
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def hwnd(self):
            return int(window.winId())

        def sample(self):
            if self.samples is not None and (not self.samples_in_loop_only or self.loop_active()):
                native = native_frame(window)
                if native and (not self.samples or self.samples[-1] != native['rect']):
                    self.samples.append(native['rect'])

        def key(self, vk, count=1):
            for _ in range(count):
                user32.PostMessageW(self.hwnd(), WM_KEYDOWN, vk, 1)
                user32.PostMessageW(self.hwnd(), WM_KEYUP, vk, 0xC0000001)

        def native(self):
            return native_frame(window) or {}

        def loop_active(self):
            """Windows reports this window in its move/size loop (GUI_INMOVESIZE)."""
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(info)
            ok = user32.GetGUIThreadInfo(user32.GetWindowThreadProcessId(self.hwnd(), None), ctypes.byref(info))
            return bool(ok and info.flags & 0x2 and int(info.hwndMoveSize or 0) == self.hwnd())

        def enter_move_loop(self):
            """``SC_MOVE``; posted right after another loop ended it is sometimes dropped."""
            for _ in range(4):
                user32.PostMessageW(self.hwnd(), WM_SYSCOMMAND, SC_MOVE, 0)
                yield .4
                if self.loop_active():
                    return

        def live_drag(self, tag, step, count):
            """Full-window dragging: the HWND follows the cursor inside the move
            loop. The keyboard loop sometimes ends on its own; only steps taken
            and samples seen while it runs count."""
            before = self.native()['rect']
            yield from self.enter_move_loop()
            active = self.loop_active()
            self.samples, self.samples_in_loop_only = [before], True
            targets = []
            for index in range(1, count + 1):
                if not self.loop_active():
                    break
                targets.append(before[1] + index * step)
                user32.SetWindowPos(self.hwnd(), None, before[0], targets[-1], 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                yield .03
            yield .1
            during, self.samples, self.samples_in_loop_only = self.samples, None, False
            if self.loop_active():
                self.key(VK_ESCAPE)  # cancel: Windows puts it back where the loop started
            yield 1.0
            backs = [(a, b) for a, b in zip(during, during[1:]) if b[1] - a[1] < -2]
            row = dict(tag=tag, loop_active=active, steps_in_loop=len(targets), before=before,
                       last_target=targets[-1] if targets else None, last_in_loop=during[-1],
                       moves=len(during) - 1, snap_backs=len(backs), first_backs=backs[:4],
                       after_cancel=self.native()['rect'], work=self.native().get('work'))
            self.result['records'].append(row)
            return row

        def keyboard_move(self):
            """A real system move (SC_MOVE, arrow keys, Enter) and the start/end
            events ``WindowBounds`` receives from Windows' hook."""
            bounds = window._window_bounds
            calls = []
            original = bounds.move_size_event
            bounds.move_size_event = lambda started: (calls.append(started), original(started))
            try:
                before = self.native()['rect']
                yield from self.enter_move_loop()
                active = self.loop_active()
                self.key(VK_DOWN, 12)
                yield .4
                self.key(VK_RETURN)
                yield 1.2
            finally:
                del bounds.move_size_event
            row = dict(tag='keyboard-move', loop_active=active, events=calls, before=before,
                       after=self.native()['rect'], work=self.native().get('work'))
            self.result['records'].append(row)
            return row

        def outline_drop(self, tag, x, y):
            """What Windows does without full-window dragging: start, one move
            at the drop, end."""
            bounds = window._window_bounds
            bounds.move_size_event(True)
            user32.SetWindowPos(self.hwnd(), None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            bounds.move_size_event(False)
            yield 1.0
            row = dict(tag=tag, placed=[x, y], after=list(self.native()['rect']), work=self.native().get('work'))
            self.result['records'].append(row)
            return row

        def title_reachable(self, rect):
            """At least 40 x 160 physical px of the top strip lie inside the work area."""
            work = self.native().get('work')
            if not work:
                return False
            left, top, right, bottom = rect
            strip = QRect(left, top, right - left, 40).intersected(
                QRect(work[0], work[1], work[2] - work[0], work[3] - work[1]))
            return strip.height() >= 40 and strip.width() >= min(160, right - left)

        def work_origin(self, screen):
            """Physical top-left of ``screen``'s work area (screens sit at their native origins)."""
            top_left = screen.availableGeometry().topLeft()
            return top_left.x(), top_left.y()

        def fits_work(self):
            native = self.native()
            return bool(native) and max(abs(a - b) for a, b in zip(native['rect'], native['work'])) <= 2

        def title_buttons_on_screen(self):
            bar = window.window_title_bar
            avail = window.screen().availableGeometry()
            return all(b.isVisible() and avail.contains(QRect(b.mapToGlobal(QPoint(0, 0)), b.size()).center())
                       for b in (bar.minimize_button, bar.maximize_button, bar.close_button))

        def monitors(self):
            """Decision 0121 still holds with the drag changes: a maximized window
            moved to another monitor comes back to its work area; minimize and
            restore keep the monitor."""
            screens = list(app.screens())
            primary = app.primaryScreen()
            for target in [s for s in screens if s is not primary]:
                window.showNormal()
                avail = primary.availableGeometry()
                window.setGeometry(avail.x() + 40, avail.y() + 40, 1100, 760)
                yield .5
                window.showMaximized()
                yield .9
                x, y = self.work_origin(target)
                user32.SetWindowPos(self.hwnd(), None, x + 20, y + 20, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                yield 2.0
                row = dict(tag=f'moved-max-to-{target.name()}', screen=window.screen().name(),
                           maximized=window.isMaximized(), **self.native())
                self.result['records'].append(row)
                inside = (self.fits_work() if window.isMaximized()
                          else window.screen().availableGeometry().contains(window.frameGeometry()))
                self.check(f'moved_max_to_{target.name()}_comes_back_with_title_buttons',
                           inside and self.title_buttons_on_screen(), row)
            for screen in screens:
                window.showNormal()
                avail = screen.availableGeometry()
                window.setGeometry(avail.x() + 40, avail.y() + 40, min(1100, avail.width() - 80),
                                   min(760, avail.height() - 80))
                yield .5
                window.showMaximized()
                yield .9
                window.showMinimized()
                yield .8
                restore_minimized_window(window)
                yield 1.6
                row = dict(tag=f'min-restore-{screen.name()}', screen=window.screen().name(), **self.native())
                self.result['records'].append(row)
                self.check(f'min_restore_keeps_{screen.name()}',
                           window.screen() is screen and window.isMaximized() and self.fits_work(), row)

        def run(self):
            yield 1.0
            screen = app.primaryScreen()
            avail = screen.availableGeometry()
            self.result['screens'] = [dict(name=s.name(), geometry=list(s.geometry().getRect()),
                                           available=list(s.availableGeometry().getRect()),
                                           dpr=s.devicePixelRatio()) for s in app.screens()]
            # The page in the user's video. (The home page's model cards can
            # recurse in resizeEvent when the window lands on another monitor;
            # that separate crash is tracked in KNOWN_ISSUES.)
            window._open_model_workshop()
            yield 1.5
            self.check('model_workshop_page_shown', window.built_page('workshop') is not None
                       and window.workshop_page.isVisible())
            window.showNormal()
            yield .6
            # The user's window: nearly as tall as the work area, near its top.
            width = min(1500, avail.width() - 160)
            window.setGeometry(avail.x() + 80, avail.y() + 10, width, avail.height() - 24)
            yield 1.0
            self.result['start'] = self.native()

            def reset():
                window.setGeometry(avail.x() + 80, avail.y() + 10, width, avail.height() - 24)
                return 1.0

            for _ in range(3):
                row = yield from self.live_drag('live-down', 24, 20)
                if row['steps_in_loop'] >= 5:
                    break
                yield reset()
            self.check('live_drag_runs_inside_native_move_loop', row['loop_active'] and row['steps_in_loop'] >= 5, row)
            self.check('live_drag_down_never_snaps_back',
                       row['snap_backs'] == 0 and abs(row['last_in_loop'][1] - row['last_target']) <= 2, row)

            yield reset()
            row = yield from self.keyboard_move()
            self.check('system_move_reaches_window_bounds_as_start_and_end',
                       row['loop_active'] and row['events'][:1] == [True] and False in row['events'], row)
            self.check('after_system_move_title_reachable', self.title_reachable(row['after']), row)

            yield reset()
            rect, work = self.native()['rect'], self.native()['work']
            row = yield from self.outline_drop('outline-drop-down', rect[0], rect[1] + 600)
            self.check('outline_drop_down_is_kept', row['after'][:2] == row['placed'], row)
            yield reset()
            row = yield from self.outline_drop('outline-drop-past-left-edge', work[0] - 600, rect[1])
            self.check('outline_drop_partly_past_left_edge_is_kept',
                       row['after'][:2] == row['placed'] and self.title_reachable(row['after']), row)
            yield reset()
            row = yield from self.outline_drop('outline-drop-title-below', rect[0], work[3] - 10)
            self.check('outline_drop_title_below_comes_back_into_reach',
                       row['after'][1] < work[3] - 10 and self.title_reachable(row['after'])
                       and row['after'][3] > work[3], row)

            # Moved by Windows or the program (not dropped by the user): the
            # whole window goes back inside, as decision 0121 wants.
            yield reset()
            rect, work = self.native()['rect'], self.native()['work']
            user32.SetWindowPos(self.hwnd(), None, rect[0], work[3] - 10, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            yield 1.0
            row = dict(tag='moved-below-work-area', placed=[rect[0], work[3] - 10], after=self.native()['rect'], work=work)
            self.result['records'].append(row)
            after = row['after']
            self.check('window_moved_by_windows_goes_back_inside',
                       work[0] <= after[0] and work[1] <= after[1] and after[2] <= work[2] and after[3] <= work[3], row)
            yield from self.monitors()

        def finish(self):
            self.timer.stop()
            self.sampler.stop()
            checks = self.result['checks']
            self.result['passed'] = bool(checks) and all(c['passed'] for c in checks) and 'error' not in self.result
            path = output / 'result.json'
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

            def shutdown_done():
                self.result['gui_shutdown'] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

            app.aboutToQuit.connect(shutdown_done)
            window.showNormal()
            window.close()

    window._window_drag_audit = Audit()
