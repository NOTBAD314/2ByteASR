"""Observation/setup for OS mouse input; never synthesizes the tested moves.

Only reachable through the existing isolated acceptance guard. The external
driver owns SendInput. Commands set up scenarios, never drag the window.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import platform
import sys
import time
import traceback

from PySide6.QtCore import QObject, QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from ..app import window_constraints as wc
from ..diagnostics.build_identity import load_build_identity


def start(window, output):
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.rows = []
            self.last_id = 0
            self.tag = 'startup'
            self.finished = False
            self.origin = time.perf_counter()
            self.result = dict(identity=load_build_identity().to_dict(), pid=os.getpid(),
                               executable=sys.executable, windows=platform.platform(),
                               win_version=list(sys.getwindowsversion()), checks=[])
            from ..app.ui_zoom import zoom_percent
            self.result['ui_zoom_percent']=zoom_percent()
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as key:
                self.result['windows_release'] = {name:winreg.QueryValueEx(key,name)[0]
                    for name in ('ProductName','DisplayVersion','CurrentBuild','UBR')}
            self.user32 = ctypes.WinDLL('user32', use_last_error=True)
            self.user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            self.user32.GetDpiForWindow.argtypes = [wintypes.HWND]
            class APPBARDATA(ctypes.Structure):
                _fields_ = [('cbSize',wintypes.DWORD),('hWnd',wintypes.HWND),('uCallbackMessage',wintypes.UINT),
                    ('uEdge',wintypes.UINT),('rc',wintypes.RECT),('lParam',wintypes.LPARAM)]
            data=APPBARDATA()
            data.cbSize=ctypes.sizeof(data)
            shell=ctypes.WinDLL('shell32')
            shell.SHAppBarMessage.argtypes=[wintypes.DWORD,ctypes.POINTER(APPBARDATA)]
            shell.SHAppBarMessage.restype=ctypes.c_size_t
            self.result['taskbar_auto_hide']=bool(shell.SHAppBarMessage(4,ctypes.byref(data)) & 1)
            window.installEventFilter(self)
            window.window_title_bar.installEventFilter(self)
            # Observe the real callers, including constrain -> widget.move.
            # Wrappers delegate unchanged; no geometry/state is suppressed.
            for name in ('move', 'setGeometry', 'showNormal', 'showMaximized', 'showFullScreen'):
                original = getattr(window, name)
                def observed(*args, _name=name, _original=original, **kwargs):
                    self.record('call.' + _name, args=[str(a) for a in args],
                                callers=[dict(function=f.name, line=f.lineno,
                                              file=f.filename.replace('\\', '/').split('/')[-1])
                                         for f in traceback.extract_stack(limit=7)[:-1]])
                    return _original(*args, **kwargs)
                setattr(window, name, observed)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(25)
            self.sampler = QTimer(self)
            self.sampler.timeout.connect(lambda: self.record('sample'))
            self.sampler.start(12)
            self.result['screens'] = [dict(name=s.name(), geometry=list(s.geometry().getRect()),
                available=list(s.availableGeometry().getRect()), dpr=s.devicePixelRatio())
                for s in QApplication.screens()]
            self.publish(0)

        def snapshot(self):
            native = wc.native_frame(window)
            cursor = wintypes.POINT()
            self.user32.GetCursorPos(ctypes.byref(cursor))
            point = QCursor.pos()
            bounds = window._window_bounds
            drag = getattr(window, '_title_drag', None)
            return dict(t=round(time.perf_counter()-self.origin, 6), tag=self.tag,
                native=native, geometry=list(window.geometry().getRect()),
                frame=list(window.frameGeometry().getRect()), normal=list(window.normalGeometry().getRect()),
                qt_state=window.windowState().value, maximized=window.isMaximized(),
                fullscreen=window.isFullScreen(), minimized=window.isMinimized(),
                cursor_physical=[cursor.x, cursor.y], cursor_logical=[point.x(), point.y()],
                dpr=window.devicePixelRatioF(), dpi=self.user32.GetDpiForWindow(int(window.winId())),
                screen=window.screen().name(), in_move=wc.in_move_size_loop(window),
                generation=getattr(bounds, 'generation', None),
                owner=getattr(bounds, 'owner', None), title_drag=drag is not None,
                native_caption_available=bool(getattr(window,'_native_caption_active',False)),
                caption_presses=getattr(bounds,'caption_presses',0),
                drag_phase=getattr(drag, 'phase', None), user_position=getattr(bounds, 'user_position', None))

        def record(self, event, **details):
            if not self.finished and len(self.rows) < 80000:
                self.rows.append(dict(event=event, **self.snapshot(), **details))

        def physical_rect(self, widget):
            local = widget.mapTo(window, QPoint())
            origin = wintypes.POINT()
            self.user32.ClientToScreen(int(window.winId()), ctypes.byref(origin))
            dpr = window.devicePixelRatioF()
            return [origin.x + round(local.x()*dpr), origin.y + round(local.y()*dpr),
                    round(widget.width()*dpr), round(widget.height()*dpr)]

        def publish(self, command_id, error=None):
            row = self.snapshot()
            bar = window.window_title_bar
            row.update(command_id=command_id, hwnd=int(window.winId()), pid=os.getpid(), error=error,
                       bar=self.physical_rect(bar), bar_visible=bar.isVisible(),
                       buttons={name:self.physical_rect(getattr(bar, name + '_button'))
                                for name in ('minimize', 'maximize', 'close')})
            studio = window.built_page('studio')
            if studio is not None:
                toolbar = getattr(studio, 'studio_toolbar', None)
                if toolbar is not None:
                    row['studio_toolbar'] = self.physical_rect(toolbar)
                    if not bar.isVisible() and toolbar.isVisible():
                        row['bar'] = self.physical_rect(studio.filename)
                        row['bar_visible'] = studio.filename.isVisible()
                        row['bar_kind'] = 'studioFilename'
                video = getattr(studio, 'video', None)
                if video is not None:
                    row['video'] = dict(rect=self.physical_rect(video), visible=video.isVisible(),
                                        paused=getattr(video, '_paused', None))
            # One immutable reply per command: Windows readers do not share
            # DELETE by default, so replacing the same open JSON can fail.
            temporary = output/f'mouse-status-{command_id:04d}.tmp'
            temporary.write_text(json.dumps(row, ensure_ascii=False), 'utf8')
            temporary.replace(output/f'mouse-status-{command_id:04d}.json')

        def eventFilter(self, obj, event):
            kind = event.type()
            if kind in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange, QEvent.Hide,
                        QEvent.WindowDeactivate, QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                        QEvent.MouseButtonDblClick, QEvent.UngrabMouse):
                self.record('qt.' + kind.name, receiver=obj.objectName() or type(obj).__name__)
            return False

        def tick(self):
            if self.finished:
                return
            path = output/f'mouse-command-{self.last_id+1:04d}.json'
            try:
                command = json.loads(path.read_text('utf8')) if path.exists() else {}
                command_id = int(command.get('id', 0))
                if command_id <= self.last_id:
                    return
                self.last_id = command_id
                action = command['action']
                self.tag = command.get('tag', self.tag)
                self.record('command.' + action)
                if action == 'setup':
                    screen = QApplication.screens()[int(command.get('screen', 0))]
                    avail = screen.availableGeometry()
                    window.showNormal()
                    window.setGeometry(avail.x()+50, avail.y()+15,
                        min(1200, avail.width()-100),
                        avail.height()-30 if command.get('tall') else min(760, avail.height()-130))
                    window.raise_()
                    window.activateWindow()
                elif action == 'maximize':
                    window.showMaximized()
                elif action == 'fullscreen':
                    window.showFullScreen()
                elif action == 'normal':
                    window.showNormal()
                elif action == 'minimize':
                    window.showMinimized()
                elif action == 'restore':
                    wc.restore_minimized_window(window)
                elif action == 'hide':
                    window.hide()
                elif action == 'show':
                    window.show()
                    window.raise_()
                    window.activateWindow()
                elif action == 'studio':
                    window.open_studio_project(output/'project.2byteproj')
                elif action in ('play', 'pause'):
                    page = window.built_page('studio')
                    page.video.set_paused(action == 'pause')
                    if action == 'play':
                        page.video.seek(1.0)
                elif action == 'mark':
                    pass
                elif action == 'snapshot':
                    pass
                elif action == 'finish':
                    self.finish()
                    return
                else:
                    raise ValueError('Unknown mouse audit command: ' + action)
                QTimer.singleShot(100, lambda: self.publish(command_id))
            except Exception:
                self.publish(self.last_id, traceback.format_exc())

        def finish(self):
            self.record('finish')
            self.finished = True
            self.timer.stop()
            self.sampler.stop()
            self.result['finished'] = True
            self.result['rows'] = len(self.rows)
            (output/'mouse-events.json').write_text(json.dumps(self.rows, ensure_ascii=False), 'utf8')
            (output/'mouse-result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')
            QApplication.instance().aboutToQuit.connect(self.closed)
            window.close()

        def closed(self):
            self.result['gui_shutdown'] = True
            (output/'mouse-result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

    window._window_title_mouse_audit = Audit()
