"""Opt-in normal source/frozen UI acceptance for zero-duration projects."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback

_provider_calls = 0
_blocked_external_connections: list[str] = []


def install_offline_guards() -> None:
    """Prevent incidental probes and external requests before normal UI setup."""
    import socket
    from .ui import EndpointEditor
    from .studio_ai_flow import StudioAIFlowMixin
    from .provider_service import ProviderService

    EndpointEditor._queue_model_discovery = lambda *a, **kw: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **kw: None

    def denied_provider(*args, **kwargs):
        global _provider_calls
        _provider_calls += 1
        raise RuntimeError('No provider requests authorized in blank-project acceptance')

    ProviderService.submit = denied_provider
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if address[0] not in {'127.0.0.1', '::1', 'localhost'}:
            _blocked_external_connections.append(str(address))
            raise RuntimeError('External network prohibited in blank-project acceptance')
        return original_connect(sock, address)

    socket.socket.connect = local_only


def _capture(window, target: Path) -> None:
    """Capture the real blank-workbench window without creating a native child."""
    if sys.platform == 'darwin':
        # Blank projects contain no native mpv surface. Qt's own widget grab
        # captures the composed window without winId() promoting its children.
        pixmap = window.grab()
        if pixmap.isNull() or not pixmap.save(str(target)):
            raise RuntimeError('Could not capture the normal macOS blank-project window')
        return
    import ctypes
    from ctypes import wintypes as W
    from scripts.capture_process_window import print_window

    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetWindowDC.argtypes = [W.HWND]; user.GetWindowDC.restype = W.HDC
    user.ReleaseDC.argtypes = [W.HWND, W.HDC]
    user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    gdi.CreateCompatibleDC.argtypes = [W.HDC]; gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]; gdi.SelectObject.restype = W.HANDLE
    gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, W.UINT]
    gdi.DeleteObject.argtypes = [W.HANDLE]; gdi.DeleteDC.argtypes = [W.HDC]
    rect = W.RECT()
    user.GetWindowRect(W.HWND(int(window.winId())), ctypes.byref(rect))
    print_window(int(window.winId()), (rect.left, rect.top, rect.right, rect.bottom)).save(target)


def start(window, output: Path) -> None:
    from PySide6.QtCore import QObject, QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .build_identity import load_build_identity
    from .studio_edit_sequence import sequence_of, timeline_duration_ms
    from .studio_project import load_project

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.started = time.monotonic()
            self.result = dict(passed=False, checks=[], screenshots=[], projects=[],
                               entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main',
                               identity=load_build_identity().to_dict(), pid=os.getpid(),
                               executable=sys.executable, dpr=window.devicePixelRatioF(),
                               pixel_source=('Qt QWidget.grab of actual normal macOS blank-workbench window'
                                             if sys.platform == 'darwin' else
                                             'PrintWindow of actual normal application on private Windows desktop'))
            self.steps = self.run()
            self.waiting = 0.
            self.deadline = self.started + 40
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            if not value:
                raise AssertionError(name + ': ' + str(detail))

        def tick(self):
            try:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    error = modal.text() + ' ' + modal.informativeText()
                    self.shot('unexpected-dialog', modal)
                    modal.reject()
                    raise RuntimeError(error)
                now = time.monotonic()
                if callable(self.waiting):
                    if self.page._readiness.profile.get('error'):
                        raise RuntimeError(str(self.page._readiness.profile['error']))
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError('Blank project UI readiness timed out')
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else now + float(step)
                self.deadline = now + 40
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failure', window)
                except Exception:
                    self.result['screenshot_error'] = traceback.format_exc()
                self.finish()

        def shot(self, name, surface=None):
            name += '.png'
            _capture(surface or window, output/name)
            self.result['screenshots'].append(name)

        def click(self, button):
            self.check('enabled visible button: ' + button.objectName(),
                       button.isVisible() and button.isEnabled(), button.text())
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        def ready(self):
            p = self.page
            return bool(p.project is not None and p._readiness.ready and not p._readiness.active
                        and p._project_view_state == 'open' and not p._readiness.overlay.isVisible())

        def empty(self, phase):
            p = self.page
            project = p.project
            sequence = sequence_of(project)
            self.check(phase + ': every real readiness stage completed',
                       set(p._readiness.TASKS).issubset(p._readiness.completed), p._readiness.profile)
            self.check(phase + ': empty media and captions',
                       not project.media.path and project.media.duration_ms == 0
                       and not project.media_pool and not project.cues)
            self.check(phase + ': no video or audio clips',
                       not any(track.clips for track in project.video_tracks + project.audio_tracks))
            self.check(phase + ': empty timeline visible',
                       p.timeline.isVisible() and p.timeline.project is project
                       and p.timeline._duration_ms() == 0 and timeline_duration_ms(project) == 0
                       and not any(s.timeline_out_ms > s.timeline_in_ms for s in sequence.segments)
                       and p.cue_model.rowCount() == 0)
            self.check(phase + ': project file stays isolated',
                       Path(p.project_path).resolve().is_relative_to(output/'projects'))
            self.result['projects'].append(dict(phase=phase, path=str(p.project_path),
                                               project_id=project.project_id,
                                               readiness=dict(p._readiness.profile)))
            self.shot(phase)

        def run(self):
            p = self.page
            window.showNormal()
            window.resize(1440, 900)
            QApplication.instance().setProperty('reduceMotion', True)
            yield .3
            for key in ('APPDATA', 'LOCALAPPDATA'):
                self.check(key + ' isolated', Path(os.environ[key]).resolve().is_relative_to(output))
            self.check('QSettings isolated', Path(QSettings('2ByteASR', 'blank-project-audit').fileName()).resolve().is_relative_to(output))
            self.click(window.subtitle_studio_button)
            yield .3
            self.check('ordinary Studio entry opens project library',
                       window.pages.currentWidget() is p and p.studio_empty.isVisible() and p.project is None)
            self.shot('01-project-library')
            self.click(p.project_new_button)
            yield self.ready
            yield .15
            self.empty('02-first-new')
            first_path, first_id = Path(p.project_path), p.project.project_id
            self.click(p.save_button)
            yield .15
            saved = load_project(first_path)
            self.check('normal save retains zero-duration project',
                       saved.project_id == first_id and not saved.media.path and saved.media.duration_ms == 0
                       and not saved.cues and p.undo_stack.isClean())
            self.click(p.studio_back_button)
            yield .2
            self.check('ordinary back returns to project library', p.project is None and p.studio_empty.isVisible())
            window.open_studio_project(first_path, mode='edit', source='blank_project_audit_reopen')
            yield self.ready
            yield .15
            self.empty('03-saved-reopen')
            self.check('reopen retains project identity', p.project.project_id == first_id)
            self.click(p.studio_back_button)
            yield .2
            self.click(p.project_new_button)
            yield self.ready
            yield .15
            self.empty('04-second-new')
            self.check('second new project has independent identity and path',
                       p.project.project_id != first_id and Path(p.project_path) != first_path)
            self.click(p.studio_back_button)
            yield .2
            fixture = output/'projects'/'existing-zero'/'existing-zero.2byteproj'
            window.open_studio_project(fixture, mode='edit', source='blank_project_audit_existing')
            yield self.ready
            yield .15
            self.empty('05-existing-zero-reopen')
            self.check('no provider calls', _provider_calls == 0, _provider_calls)

        def finish(self):
            self.timer.stop()
            self.result['provider_calls'] = _provider_calls
            self.result['external_connections_blocked'] = list(_blocked_external_connections)
            self.result['elapsed_seconds'] = round(time.monotonic() - self.started, 3)
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()

            def stopped():
                self.result['gui_shutdown'] = True
                self.write()

            QApplication.instance().aboutToQuit.connect(stopped)
            window.close()

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

    window._blank_project_audit = Audit()
