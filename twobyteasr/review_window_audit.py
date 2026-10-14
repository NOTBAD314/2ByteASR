"""Opt-in real-window check: review replay and the frameless main window (2026-10-15).

Also embedded in the frozen EXE (scenario ``review-window``). Window part, on
every monitor of this PC: the min/max/system-menu styles exist; a maximized
window that Windows moves to another monitor (as when monitors sleep, wake or
are re-arranged) comes back to exactly that monitor's work area with its
title buttons on screen; minimize + restore keeps the monitor; a click on the
title bar keeps a maximized window maximized while a double-click restores
it; a long failure message scrolls inside a compact dialog; Studio's own
window buttons stay on screen. Review part (Studio, copied project with real
media): Space/重听 replays only the selected caption at 1x and 2x, stops
before the next caption, keeps the selection; transport play follows the
clock again.
"""
import ctypes
import json
import os
import sys
import time
import traceback
from ctypes import wintypes


SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
WM_SYSCOMMAND, SC_RESTORE = 0x0112, 0xF120
WS_SYSMENU, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00080000, 0x00020000, 0x00010000


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .build_identity import load_build_identity
    from .window_constraints import native_frame, restore_minimized_window, special_geometry_broken

    app = QApplication.instance()
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pid': os.getpid(), 'executable': sys.executable, 'records': []}
            self.steps = self.run()
            self.wait_until = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        # ------------------------------------------------------------ helpers
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

        def controls_on_screen(self, buttons):
            avail = window.screen().availableGeometry()
            rects = [QRect(b.mapToGlobal(QPoint(0, 0)), b.size()) for b in buttons]
            return all(b.isVisible() for b in buttons) and all(avail.contains(r.center()) for r in rects)

        def title_buttons(self):
            bar = window.window_title_bar
            return (bar.minimize_button, bar.maximize_button, bar.close_button)

        def snapshot(self, tag):
            native = native_frame(window) or {}
            row = dict(tag=tag, screen=window.screen().name(), state=int(window.windowState().value),
                       geometry=list(window.geometry().getRect()), **native)
            self.result['records'].append(row)
            return row

        def fits(self, native):
            return bool(native) and max(abs(a - b) for a, b in zip(native['rect'], native['work'])) <= 2

        def screen_work_origin(self, screen):
            """Physical top-left of ``screen``'s work area (EnumDisplayMonitors)."""
            found = []

            class MI(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                            ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]

            proc_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)

            def callback(monitor, _dc, _rect, _data):
                info = MI()
                info.cbSize = ctypes.sizeof(info)
                ctypes.windll.user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
                found.append((info.rcWork, info.rcMonitor))
                return 1

            ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_type(callback), None)
            geometry = screen.geometry()
            scale = screen.devicePixelRatio()
            best = min(found, key=lambda pair: abs((pair[1].right - pair[1].left) / scale - geometry.width())
                       + abs((pair[1].bottom - pair[1].top) / scale - geometry.height())
                       + (0 if (pair[1].left == 0 and pair[1].top == 0) == (screen is app.primaryScreen()) else 10_000))
            return best[0].left, best[0].top

        def place_normal(self, screen, size=(1100, 760)):
            window.showNormal()
            avail = screen.availableGeometry()
            window.setGeometry(avail.x() + 40, avail.y() + 40, min(size[0], avail.width() - 80),
                               min(size[1], avail.height() - 80))

        # --------------------------------------------------------------- run
        def run(self):
            yield 1.0
            style = user32.GetWindowLongW(self.hwnd(), -16) & 0xFFFFFFFF
            self.check('window_has_sysmenu_min_max_styles',
                       style & (WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX) == WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX,
                       hex(style))
            screens = list(app.screens())
            primary = app.primaryScreen()
            self.result['screens'] = [dict(name=s.name(), geometry=list(s.geometry().getRect()),
                                           dpr=s.devicePixelRatio()) for s in screens]

            # A maximized window moved by Windows to another monitor.
            for target in [s for s in screens if s is not primary]:
                for case in ('qt', 'native'):
                    self.place_normal(primary)
                    yield .5
                    if case == 'qt':
                        window.showMaximized()
                    else:
                        user32.ShowWindow(self.hwnd(), 3)  # SW_MAXIMIZE
                    yield .9
                    x, y = self.screen_work_origin(target)
                    user32.SetWindowPos(self.hwnd(), None, x + 20, y + 20, 0, 0,
                                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                    yield 2.0
                    row = self.snapshot(f'moved-{case}-max-to-{target.name()}')
                    # Either still maximized on exactly one work area, or an
                    # ordinary window fully inside the screen it landed on.
                    inside = (self.fits(row) if window.isMaximized()
                              else window.screen().availableGeometry().contains(window.frameGeometry()))
                    self.check(f'moved_{case}_max_to_{target.name()}_title_buttons_on_screen',
                               self.controls_on_screen(self.title_buttons()) and inside
                               and not special_geometry_broken(window), row)

            # Minimize + restore keeps the monitor (Qt restore and taskbar SC_RESTORE).
            for screen in screens:
                for how in ('qt', 'taskbar'):
                    self.place_normal(screen)
                    yield .5
                    window.showMaximized()
                    yield .9
                    window.showMinimized()
                    yield .8
                    if how == 'qt':
                        restore_minimized_window(window)
                    else:
                        user32.PostMessageW(self.hwnd(), WM_SYSCOMMAND, SC_RESTORE, 0)
                    yield 1.6
                    row = self.snapshot(f'min-restore-{how}-{screen.name()}')
                    self.check(f'min_restore_{how}_keeps_{screen.name()}',
                               window.screen() is screen and window.isMaximized() and self.fits(row), row)

            # Title bar: a click keeps a maximized window, a double-click restores it.
            self.place_normal(primary)
            yield .5
            window.showMaximized()
            yield .9
            bar = window.window_title_bar
            spot = QPoint(max(20, bar.minimize_button.x() - 120), bar.height() // 2)
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot)
            yield .6
            self.check('title_click_keeps_maximized', window.isMaximized())
            QTest.mouseDClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot)
            yield .8
            self.check('title_double_click_restores', not window.isMaximized()
                       and self.controls_on_screen(self.title_buttons()))
            QTest.mouseDClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spot)
            yield .8
            self.check('title_double_click_maximizes_again', window.isMaximized())

            # Failure dialog: long details scroll in a compact card.
            long_details = 'PRIMARY_API worker failed (exit 1):\nstderr:\n' + '\n'.join(
                f'  File "moss_firered_pipeline.py", line {4000 + i}, in run_stage_{i}\n'
                f'    value = runner_{i}()  # 子进程返回了非 JSON 内容' for i in range(60))
            window._show_task_notification('字幕任务异常中止', '任务未能正常完成，请查看结果页和运行日志。',
                                           QMessageBox.Icon.Critical, long_details)
            yield 1.2
            dialog = window._completion_dialog
            avail = window.screen().availableGeometry()
            frame = dialog.frameGeometry() if dialog is not None else QRect()
            confirm = QRect(dialog.confirm_button.mapToGlobal(QPoint(0, 0)), dialog.confirm_button.size()) if dialog else QRect()
            self.check('failure_dialog_compact_and_reachable',
                       dialog is not None and frame.height() <= avail.height() * 0.7 and avail.contains(frame)
                       and avail.contains(confirm.center()),
                       dict(dialog=list(frame.getRect()), avail=list(avail.getRect())))
            if dialog is not None:
                dialog.reject()
            yield .6
            window._show_task_notification('识别完成', '完成 1 个 · 部分完成 0 个 · 失败 0 个 · 取消 0 个',
                                           QMessageBox.Icon.Information, '待检查问题 0 项 · 联网核验未完成或未执行 0 个任务')
            yield 1.2
            dialog = window._completion_dialog
            short_height = dialog.frameGeometry().height() if dialog is not None else None
            self.result['short_dialog_height'] = short_height
            self.check('short_dialog_stays_compact', short_height is not None and short_height <= 360, short_height)
            if dialog is not None:
                dialog.reject()
            yield .6

            # Studio: its own window buttons stay on screen on every monitor.
            project = os.environ.get('TWOBYTEASR_STARTUP_PROJECT', '')
            window.open_studio_project(project)
            deadline = time.monotonic() + 40
            page = None
            while time.monotonic() < deadline:
                page = window.built_page('studio')
                if (page is not None and page.project is not None
                        and getattr(page.video, '_startup_state', '') == 'READY'):
                    break
                yield .3
            self.check('studio_opened', page is not None and page.project is not None)
            if page is None or page.project is None:
                return
            studio_buttons = (page.studio_minimize_button, page.studio_maximize_button, page.studio_close_button)
            self.result.setdefault('paused_trace', []).append(('studio-ready', bool(page.video._paused)))
            for screen in screens:
                self.place_normal(screen)
                yield .5
                window.showMaximized()
                yield 1.2
                self.result.setdefault('paused_trace', []).append((screen.name(), bool(page.video._paused)))
                self.check(f'studio_window_buttons_on_{screen.name()}', self.controls_on_screen(studio_buttons),
                           [list(QRect(b.mapToGlobal(QPoint(0, 0)), b.size()).getRect()) for b in studio_buttons])
            self.place_normal(primary, (1600, 1000))
            yield .5
            window.showMaximized()
            yield 1.5
            yield from self.review(page)

        def review(self, page):
            self.result.setdefault('paused_trace', []).append(('before-review', bool(page.video._paused)))
            page.volume_slider.setValue(0)
            page._set_review_mode(True)
            yield .8
            self.result.setdefault('paused_trace', []).append(('review-on', bool(page.video._paused)))
            cues = {cue.id: cue for cue in page.project.cues}
            target, following = cues['c1'], cues['c2']
            for speed in (1.0, 2.0):
                # Replay is a play/pause toggle: start each run from a pause.
                self.result.setdefault('playing_before_replay', []).append(not bool(page.video._paused))
                page.video.set_paused(True)
                page._sync_play_button(True)
                page._review_space_playing = False
                yield .3
                page._set_speed(speed)
                page.select_cue('c1')
                page._seek(target.start_ms / 1000)
                yield 1.0
                for attempt in range(2):
                    started = time.monotonic()
                    page._play_review_context()
                    seen, peak, trace = [], 0, []
                    while time.monotonic() - started < 8:
                        yield .01
                        if not seen or seen[-1] != page.selected_cue_id:
                            seen.append(page.selected_cue_id)
                        peak = max(peak, int(page.timeline.playhead_ms))
                        review = page._review_playback
                        trace.append((round((time.monotonic() - started) * 1000), int(page.timeline.playhead_ms),
                                      bool(page.video._paused), bool(getattr(page.video, '_seek_hold_active', False)),
                                      bool(review is not None and review.finished)))
                        if review is not None and review.finished:
                            break
                    yield .6
                    final = int(page.timeline.playhead_ms)
                    detail = dict(seen=seen, peak=peak, final=final, next_start=following.start_ms, end=target.end_ms,
                                  trace=trace[::3] + trace[-3:])
                    self.check(f'replay_{speed:g}x_{attempt}_stays_on_caption',
                               seen == ['c1'] and page.selected_cue_id == 'c1', detail)
                    self.check(f'replay_{speed:g}x_{attempt}_stops_before_next',
                               target.end_ms - 60 <= final < following.start_ms and peak < following.start_ms, detail)
            page._set_speed(1.0)
            yield .4
            # Transport play is ordinary playback again: the selection follows the clock.
            page._toggle_playback()
            yield 2.5
            page._toggle_playback()
            yield .8
            self.check('transport_play_follows_clock_after_replay', page.selected_cue_id != 'c1',
                       dict(selected=page.selected_cue_id, playhead=int(page.timeline.playhead_ms)))
            page._set_review_mode(False)
            yield .5

        def finish(self):
            self.timer.stop()
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

    window._review_window_audit = Audit()
