"""Opt-in theme picker and palette check in the real window (2026-10-14).

Also embedded in the frozen EXE (scenario ``theme-gallery``): opens 应用设置 →
外观, previews themes from the cards, cancels (the opening theme must come
back), saves one (it must persist and the dialog must be released), reopens
(the chosen card must be scrolled into view), then shows every theme on the
home page and in Studio. Pixels are grabs of the visible native window.
"""
import json
import os
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
    from .build_identity import load_build_identity
    from .theme_manager import apply_theme, theme_key
    from .ui_theme import DEFAULT_THEME_KEY, THEME_ORDER, THEMES, theme_display_label

    app = QApplication.instance()

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pid': os.getpid(), 'executable': sys.executable, 'apply_ms': {}}
            self.steps = self.run()
            self.wait_until = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(80)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})
            if not value:
                raise AssertionError(name)

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

        def window_color(self):
            return app.palette().color(QPalette.ColorRole.Window).name()

        def settings(self, drive):
            """Open the real settings dialog and run ``drive(dialog)`` inside its loop."""
            state = {}

            def go():
                try:
                    dialog = next(w for w in app.topLevelWidgets()
                                  if type(w).__name__ == 'ApplicationSettingsDialog' and w.isVisible())
                    # The page that holds the gallery, not its (translated) label.
                    page = next(i for i in range(dialog.pages.count())
                                if dialog.pages.widget(i).isAncestorOf(dialog.theme_gallery))
                    dialog.navigation.setCurrentRow(page)
                    for _ in range(5):
                        app.processEvents()
                    drive(dialog, state)
                except Exception:
                    state['error'] = traceback.format_exc()
                    for item in app.topLevelWidgets():
                        if isinstance(item, QDialog) and item.isVisible():
                            item.done(0)

            # The modal dialog runs a nested loop; pause the step timer meanwhile.
            self.timer.stop()
            QTimer.singleShot(900, go)
            try:
                window._open_application_settings()
            finally:
                self.timer.start(80)
            if state.get('error'):
                raise AssertionError(state['error'])
            return state

        def run(self):
            yield 1.5
            self.check('fresh profile starts on the default theme', theme_key() == DEFAULT_THEME_KEY, theme_key())

            def preview_and_cancel(dialog, state):
                gallery = dialog.theme_gallery
                state['count'] = gallery.count()
                state['start'] = gallery.currentData()
                state['previews'] = []
                for key in ('frost', 'obsidian', 'paper'):
                    QTest.mouseClick(gallery.card(key), Qt.MouseButton.LeftButton)
                    for _ in range(3):
                        app.processEvents()
                    state['previews'].append(dict(key=key, applied=theme_key(), window=self.window_color()))
                    dialog.grab().save(str(output / f'settings-preview-{key}.png'))
                state['hint'] = dialog.theme_preview_hint.text()
                dialog.done(0)  # Cancel / Esc / × all end here

            state = self.settings(preview_and_cancel)
            yield 0.8
            self.check('gallery lists every theme', state['count'] == len(THEMES), state['count'])
            self.check('gallery starts on the active theme', state['start'] == DEFAULT_THEME_KEY, state['start'])
            for item in state['previews']:
                self.check(f"card click previews {item['key']} at once",
                           item['applied'] == item['key'] and item['window'] == THEMES[item['key']].app_background, item)
            self.check('preview hint names the preview and the way back',
                       theme_display_label(THEMES['paper']) in state['hint']
                       and theme_display_label(THEMES[DEFAULT_THEME_KEY]) in state['hint'], state['hint'])
            self.check('cancel restores the opening theme',
                       theme_key() == DEFAULT_THEME_KEY and self.window_color() == THEMES[DEFAULT_THEME_KEY].app_background,
                       (theme_key(), self.window_color()))
            self.check('cancelled dialog is released',
                       not any(type(w).__name__ == 'ApplicationSettingsDialog' for w in app.allWidgets()))

            def save_obsidian(dialog, state):
                QTest.mouseClick(dialog.theme_gallery.card('obsidian'), Qt.MouseButton.LeftButton)
                for _ in range(3):
                    app.processEvents()
                dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

            self.settings(save_obsidian)
            yield 0.8
            from PySide6.QtCore import QSettings
            stored = QSettings('2ByteASR', '2ByteASR').value('appearance/theme')
            self.check('save keeps the chosen theme', theme_key() == 'obsidian' and stored == 'obsidian', stored)
            self.check('saved dialog is released',
                       not any(type(w).__name__ == 'ApplicationSettingsDialog' for w in app.allWidgets()))
            window.grab().save(str(output / 'home-after-save-obsidian.png'))

            def reopen(dialog, state):
                gallery = dialog.theme_gallery
                for _ in range(6):
                    app.processEvents()
                card = gallery.card(gallery.currentData())
                state['current'] = gallery.currentData()
                state['visible'] = not card.visibleRegion().isEmpty()
                dialog.grab().save(str(output / 'settings-reopen-obsidian.png'))
                dialog.done(0)

            state = self.settings(reopen)
            yield 0.6
            self.check('reopened picker shows the saved theme', state['current'] == 'obsidian', state['current'])
            self.check('chosen card is scrolled into view', state['visible'])

            project = os.environ.get('TWOBYTEASR_STARTUP_PROJECT', '')
            studio_ready = {'done': False}
            if project:
                window.open_studio_project(project, mode='edit', source='startup_audit',
                                           on_ready=lambda *a, **k: studio_ready.__setitem__('done', True))
                deadline = time.monotonic() + 60
                while not studio_ready['done'] and time.monotonic() < deadline:
                    yield 0.3
            for key in THEME_ORDER:
                started = time.perf_counter()
                apply_theme(key, app)
                self.result['apply_ms'][key] = round((time.perf_counter() - started) * 1000, 1)
                window._return_to_settings()
                yield 0.6
                self.check(f'{key}: palette applied', self.window_color() == THEMES[key].app_background,
                           self.window_color())
                window.grab().save(str(output / f'home-{key}.png'))
                page = getattr(window, '_studio_page_instance', None)
                if page is not None and studio_ready['done']:
                    window._switch_page(page)
                    yield 0.8
                    window.grab().save(str(output / f'studio-{key}.png'))
            apply_theme(DEFAULT_THEME_KEY, app)
            yield 0.4

        def finish(self):
            self.timer.stop()
            self.result['passed'] = 'error' not in self.result
            self.result['gui_shutdown'] = True
            (output / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')
            window.result_exit_code = 0 if self.result['passed'] else 1
            QTimer.singleShot(100, window.close)

    window._theme_gallery_audit = Audit()
