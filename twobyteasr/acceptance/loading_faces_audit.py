"""Real-window check of the 2026-11-02 loading faces (library fan, poster, failure).

Runs inside the normal MainWindow (scenario ``loading-faces``) on an isolated
profile whose recent projects were seeded by ``scripts/verify_loading_faces_headed.py``.
It opens the project library cold, clicks a fanned recent project, checks that
the picked project opens once the library is ready, then opens a missing
project for the failure face. Every distinct loading state is grabbed.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def start(window, out: Path):
    from PySide6.QtCore import QObject, QPoint, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    theme = os.environ.get('TWOBYTEASR_LOADING_FACES_THEME', 'sand')
    picked_index = int(os.environ.get('TWOBYTEASR_LOADING_FACES_PICK', '1'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(passed=False, theme=theme, checks=[], captures=[], errors=[])
            self.keys = set()
            self.sequence = self.run()
            self.waiting = None
            self.deadline = time.perf_counter() + 150
            self.closed = self.finished = False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(20)
            QApplication.instance().aboutToQuit.connect(self.quit)

        def save(self):
            (out / f'loading-faces-{theme}.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')

        def check(self, name, value, **detail):
            self.result['checks'].append(dict(name=name, passed=bool(value), **detail))
            self.save()
            if not value:
                raise AssertionError(f'{name}: {detail}')

        def session(self):
            return window.__dict__.get('_studio_loading_session')

        def capture(self, label=''):
            session = self.session()
            if session is None or not session.view.isVisible():
                return
            view = session.view
            face = 'library' if view.library_mode else 'project'
            steps = view.library_steps if view.library_mode else view.steps_view
            key = (face, steps.current, steps.failed, label)
            if key in self.keys:
                return
            self.keys.add(key)
            name = f'{theme}-{len(self.keys):02d}-{face}-{label or steps.failed or steps.current or "done"}.png'
            view.grab().save(str(out / name))
            self.result['captures'].append(dict(file=name, face=face, current=steps.current, failed=steps.failed,
                                                generation=session.generation, state=session.state,
                                                status=view.label.text()))

        def ready(self, path):
            page = window.built_page('studio')
            return bool(page is not None and getattr(page, '_readiness', None) is not None
                        and page._readiness.ready and str(page.project_path) == str(Path(path).resolve()))

        def run(self):
            from ..design.theme_manager import apply_theme
            apply_theme(theme)
            window.resize(1440, 900)
            window.move(QApplication.primaryScreen().availableGeometry().topLeft() + QPoint(32, 32))
            self.check('cold entry has no Studio', window.built_page('studio') is None)
            window.open_studio_project()
            yield lambda: self.session() is not None and self.session().view.isVisible()
            session = self.session()
            session.changed.connect(lambda: self.capture())
            view = session.view
            self.check('library face shown', view.library_mode and view.faces.currentWidget() is view.library_face)
            self.check('recent projects fanned', len(view.fan.entries) == 5, count=len(view.fan.entries))
            self.check('nothing picked by default', session.picked_project() == '')
            fan = view.fan
            transform = dict(fan._transforms())[picked_index]
            width, height = fan._card_size()
            # A point on the picked card that no card painted above it covers.
            target = transform.map(QPoint(int(width * (.18 if picked_index < 2 else .82)), int(height * .2)))
            QTest.mouseClick(fan, Qt.MouseButton.LeftButton, pos=target)
            expected = str(fan.entries[picked_index]['path'])
            self.check('clicked card is picked', session.picked_project() == expected,
                       picked=session.picked_project(), expected=expected)
            self.capture('picked')
            yield lambda: self.ready(expected)
            self.check('picked project opened after the library was ready', self.ready(expected))
            page = window.built_page('studio')
            self.check('picked project is the editor project', str(page.project_path) == str(Path(expected).resolve()))
            yield .4
            missing = out / 'missing-project.2byteproj'
            window.open_studio_project(str(missing))
            yield lambda: self.session().state == 'failed'
            yield .6
            self.capture('failed')
            view = self.session().view
            self.check('failure keeps the poster face', not view.library_mode and view.cover.failed
                       and view.eyebrow.property('state') == 'failed' and view.perch.mood == 'sad')
            QTest.mouseClick(view.back, Qt.MouseButton.LeftButton)
            yield .4
            self.result['passed'] = all(item['passed'] for item in self.result['checks'])
            self.save()
            if page is not None:
                page.undo_stack.setClean()
            window.close()
            yield lambda: self.closed

        def tick(self):
            if self.finished:
                return
            try:
                if time.perf_counter() > self.deadline:
                    raise TimeoutError('loading faces audit deadline')
                self.capture()
                if self.waiting is not None:
                    if callable(self.waiting):
                        if not self.waiting():
                            return
                    elif time.perf_counter() < self.waiting:
                        return
                step = next(self.sequence)
                self.waiting = step if callable(step) else time.perf_counter() + float(step)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['errors'].append(traceback.format_exc())
                self.finish()

        def finish(self):
            if self.finished:
                return
            self.finished = True
            self.timer.stop()
            self.save()
            if not self.closed:
                page = window.built_page('studio')
                if page is not None:
                    page.undo_stack.setClean()
                window.close()

        def quit(self):
            self.closed = True
            self.result['normal_shutdown'] = True
            self.finish()
            self.save()

    window._loading_faces_audit = Audit()
