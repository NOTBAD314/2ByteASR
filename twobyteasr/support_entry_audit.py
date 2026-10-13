"""Opt-in source/frozen support-entry acceptance using the real application."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch

def capture(window, target):
    import ctypes
    from ctypes import wintypes as W
    from scripts.capture_process_window import print_window
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetWindowDC.argtypes = [W.HWND]; user.GetWindowDC.restype = W.HDC
    user.ReleaseDC.argtypes = [W.HWND, W.HDC]
    user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
    gdi.CreateCompatibleDC.argtypes = [W.HDC]; gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]; gdi.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]; gdi.SelectObject.restype = W.HANDLE
    gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT]
    gdi.DeleteObject.argtypes = [W.HANDLE]; gdi.DeleteDC.argtypes = [W.HDC]
    rect = W.RECT(); user.GetWindowRect(W.HWND(int(window.winId())), ctypes.byref(rect))
    print_window(int(window.winId()), (rect.left, rect.top, rect.right, rect.bottom)).save(target)


def start(window, out):
    restart = os.environ.get('TWOBYTEASR_SUPPORT_RESTART') == '1'
    from PySide6.QtCore import QObject, QTimer, Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton, QMessageBox
    from twobyteasr import support_entry as support
    from twobyteasr.i18n import tr, current_language
    from twobyteasr.theme_manager import apply_theme
    from twobyteasr.ui_theme import THEMES
    from twobyteasr.build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self, window):
            super().__init__(window)
            self.window = window
            self.result = dict(passed=False, checks=[], entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main', restart=restart,
                               pid=os.getpid(), executable=sys.executable, identity=load_build_identity().to_dict(),
                               dpr=window.devicePixelRatioF(), screenshots=[])
            self.opened = []
            self.browser_patch = patch.object(support.QDesktopServices, 'openUrl',
                                             side_effect=lambda url: self.opened.append(url.toString()) or True)
            self.browser_patch.start()
            self.steps = self.run(); self.wait_until = 0
            self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(80)

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            if not value:
                raise AssertionError(name + ': ' + str(detail))

        def tick(self):
            if time.monotonic() < self.wait_until:
                return
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.result['passed'] = True; self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc(); self.finish()

        def shot(self, name, window):
            capture(window, out / (name + '.png'))
            self.result['screenshots'].append(name + '.png')

        def click(self, button):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        def fits(self, name, dialog):
            errors = []
            for widget in dialog.findChildren(QLabel) + dialog.findChildren(QAbstractButton):
                if not widget.isVisible() or widget.window() is not dialog:
                    continue
                if isinstance(widget, QLabel) and widget.objectName() in {
                    'dialogSurfaceTitle', 'supportParagraph', 'supportEmphasis'
                } and not widget.alignment() & Qt.AlignmentFlag.AlignHCenter:
                    errors.append((widget.text(), 'not centered'))
                if isinstance(widget, QLabel) and widget.wordWrap():
                    if widget.height() < widget.heightForWidth(widget.width()):
                        errors.append((widget.text(), 'height', widget.height(), widget.heightForWidth(widget.width())))
                elif widget.text() and widget.width() < widget.fontMetrics().horizontalAdvance(widget.text()) + 8:
                    errors.append((widget.text(), 'width', widget.width()))
                if not dialog.rect().contains(widget.mapTo(dialog, QPoint(0, 0))) or not dialog.rect().contains(widget.mapTo(dialog, widget.rect().bottomRight())):
                    errors.append((widget.text(), 'outside'))
            self.check(name + ' text fits', not errors, errors)

        def toolbar(self, name):
            window = self.window
            controls = [window.brand, window.header_subtitle, window.support_button, window.update_button,
                        window.subtitle_studio_button, window.model_workshop_button, window.return_recognition_button,
                        window.app_settings_button, window.language_combo]
            visible = [w for w in controls if w.isVisible()]
            rects = [w.geometry() for w in visible]
            self.check(name + ' toolbar contained and ordered',
                       all(window.header_content.rect().contains(r) for r in rects)
                       and all(a.right() < b.left() for a, b in zip(rects, rects[1:])),
                       [(w.objectName(), w.x(), w.width()) for w in visible])
            if window.support_button.isVisible():
                self.check(name + ' immediately before update',
                           window.update_button.x() - window.support_button.geometry().right() - 1 == 10)

        def error_surface(self, name, action):
            self.timer.stop()
            def dismiss():
                try:
                    error = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
                    self.shot(name, error)
                    self.check(name + ' feedback visible', bool(error.text()))
                    error.accept()
                except Exception:
                    self.result['error'] = traceback.format_exc()
                    QApplication.closeAllWindows()
            QTimer.singleShot(300, dismiss)
            action()
            self.timer.start(80)

        def run(self):
            window = self.window
            window.showNormal(); window.resize(1440, 900)
            QApplication.instance().setProperty('reduceMotion', True)
            yield .7
            if restart:
                self.check('new process restores permanent choice', support.support_entry_hidden() and window.support_button.isHidden())
                self.check('new process restores language', current_language() == 'ja')
                self.toolbar('restart')
                self.shot('restart-hidden-home', window)
                return
            self.check('old config missing key displays entry', not support._settings().contains(support.SUPPORT_HIDDEN_KEY) and window.support_button.isVisible())
            self.check('startup makes no support requests', not self.opened)
            baseline = deepcopy(window.legacy.RUNTIME_SETTINGS)
            original_worker = window.worker
            for language in ('zh', 'en', 'ja'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                window.ai_panel.set_expanded(False, animate=False)
                window.settings_scroll.verticalScrollBar().setValue(0)
                for theme in THEMES:
                    apply_theme(theme, QApplication.instance())
                    yield .3
                    self.toolbar(language + '-' + theme)
                    self.click(window.support_button)
                    yield .2
                    dialog = window._support_dialog
                    self.check('localized support title ' + language, dialog.windowTitle() == tr('支持我！'))
                    self.fits(language + '-' + theme, dialog)
                    self.shot(language + '-' + theme + '-support', dialog)
                    self.click(window.support_button)
                    self.check('repeated entry keeps same dialog', window._support_dialog is dialog)
                    self.click(dialog.hide_button)
                    yield .2
                    confirmation = dialog._confirmation
                    self.check('Cancel gets initial focus', confirmation.focusWidget() is confirmation.cancel_button)
                    self.fits(language + '-' + theme + '-confirmation', confirmation)
                    if theme == 'grape':
                        self.shot(language + '-grape-confirmation', confirmation)
                    QTest.keyClick(confirmation, Qt.Key.Key_Escape)
                    yield .1
                    self.check('Escape cancels without persistence', dialog.isVisible() and not support.support_entry_hidden())
                    self.click(dialog.close_button)
                    yield .1
                    self.check('ordinary close leaves entry', window.support_button.isVisible() and window._support_dialog is None)
                for width in (900, 1100, 1440):
                    apply_theme('grape', QApplication.instance())
                    window.resize(width, 720 if width < 1440 else 900)
                    yield .25
                    self.toolbar(language + '-width-' + str(width))
                    self.shot(language + '-width-' + str(width), window)
            self.check('dialogs did not make support requests', not self.opened)
            self.click(window.support_button)
            yield .2
            dialog = window._support_dialog
            for language, theme in (('en', 'warm'), ('zh', 'grape'), ('ja', 'plum')):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                apply_theme(theme, QApplication.instance())
                yield .25
                self.check('open support translates live ' + language, dialog.windowTitle() == tr('支持我！'))
                self.fits('live-' + language, dialog)
            for button in dialog.channel_buttons:
                self.click(button)
            self.check('exact two fixed URLs', self.opened == [url for _, url in support.SUPPORT_CHANNELS], self.opened)
            with patch.object(support.QDesktopServices, 'openUrl', return_value=False):
                self.error_surface('browser-failure', lambda: self.click(dialog.channel_buttons[0]))
            self.click(dialog.hide_button)
            yield .2
            with patch.object(support, 'hide_support_entry', side_effect=OSError('simulated write failure')):
                self.error_surface('save-failure', lambda: self.click(dialog._confirmation.confirm_button))
            self.check('save failure keeps entry and support dialog', window.support_button.isVisible() and dialog.isVisible() and not support.support_entry_hidden())
            self.check('recognition settings and worker preserved', window.legacy.RUNTIME_SETTINGS == baseline and window.worker is original_worker)
            self.click(dialog.hide_button)
            yield .2
            self.click(dialog._confirmation.confirm_button)
            yield .3
            self.check('confirmed hide is immediately durable', window.support_button.isHidden() and support.support_entry_hidden() and window._support_dialog is None)
            self.toolbar('hidden')
            self.shot('confirmed-hidden-home', window)
            for language, theme in (('en', 'warm'), ('zh', 'plum'), ('ja', 'grape')):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                apply_theme(theme, QApplication.instance())
                yield .3
                self.check('hidden after language/theme ' + language, window.support_button.isHidden())
            # Actual project files and Studio navigation stay inside the QA root.
            from twobyteasr.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project
            from twobyteasr.audio_engine import studio_ffmpeg_path
            from twobyteasr.processes import run_hidden_subprocess
            media = out/'fixture.mp4'
            result = run_hidden_subprocess([str(studio_ffmpeg_path()), '-y', '-f', 'lavfi', '-i',
                'color=c=0x342b40:s=640x360:r=25:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(media)],
                purpose='support navigation fixture', capture_output=True, timeout=30)
            self.check('isolated media created', result.returncode == 0)
            self.click(window.subtitle_studio_button)
            yield .8
            self.check('real Studio entry still works', window.pages.currentWidget() is window.studio_page)
            for number in (1, 2):
                project = SubtitleProject(media=StudioMedia(path=str(media), display_name=media.name,
                    duration_ms=2000, width=640, height=360), cues=[StudioCue('one', 0, 1800, 'Support test')])
                target = save_project(project, out/f'project-{number}.2byteproj')
                window.studio_page.open_project(target, skip_dirty_guard=True)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and not window.studio_page._readiness.ready:
                    yield .2
                self.check('project switch ready ' + str(number), window.studio_page._readiness.ready)
            window._return_to_settings()
            yield .6
            self.check('Studio return retains hidden entry', window.pages.currentWidget() is window.settings_scroll and window.support_button.isHidden())
            self.check('core navigation remains enabled', all(b.isEnabled() for b in (window.update_button, window.model_workshop_button, window.app_settings_button, window.subtitle_studio_button)))
            self.shot('studio-return-hidden-home', window)

        def finish(self):
            self.timer.stop(); self.browser_patch.stop()
            if 'error' in self.result:
                self.result['passed'] = False
            name = 'restart-result.json' if restart else 'result.json'
            (out/name).write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')
            self.window.result_exit_code = 0 if self.result['passed'] else 1
            def stopped():
                self.result['gui_shutdown'] = True
                (out/name).write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')
            QApplication.instance().aboutToQuit.connect(stopped)
            self.window.close()

    window._support_audit = Audit(window)
