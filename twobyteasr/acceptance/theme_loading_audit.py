"""Event-loop, real mascot Paint and navigation measurements; opt-in only."""
import json
import os
from pathlib import Path
import platform
import time
import traceback


def summary(values):
    values = sorted(values)
    return dict(samples=len(values), p95_ms=round(values[min(len(values)-1, int(len(values)*.95))], 3) if values else None,
        max_ms=round(max(values), 3) if values else None, over50=sum(x > 50 for x in values), over100=sum(x > 100 for x in values))


def start(window, out):
    from PySide6.QtCore import QObject, QEvent, Qt, QTimer
    from PySide6.QtGui import QFontInfo
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtTest import QTest
    from ..design.bunny_mascot import BunnyMascot
    from ..design import theme_manager
    apply_theme = getattr(theme_manager, 'request_theme', theme_manager.apply_theme)
    theme_key = theme_manager.theme_key

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(passed=False, cases=[], checks=[], machine=dict(os=platform.platform(), python=platform.python_version(),
                cpu=platform.processor(), logical_cores=os.cpu_count(), scale=window.devicePixelRatioF()),
                measurement='10ms Qt heartbeat lateness; real QWidget paint; not physical display scanout', spans=[])
            self.case = None
            self.feedback_widget = None
            from ..runtime_paths import detect_install_root
            from PySide6.QtGui import QRawFont
            try:
                from ..design.loading_font import loading_font
            except ImportError:
                self.result['font'] = None  # A measured predecessor has no target font yet.
            else:
                font = loading_font()
                font_id, families, _ = QApplication.instance()._loading_status_font
                self.result['font'] = dict(application_font_id=font_id, families=families,
                    resolved_family=QFontInfo(font).family(), glyphs=QRawFont.fromFont(font).glyphIndexesForString('正在准备播放器ABC123，。！？'),
                    bundled_font=(detect_install_root()/'assets/fonts/MaokenAssortedSans.otf').is_file(),
                    bundled_license=(detect_install_root()/'assets/fonts/MaokenAssortedSans-OFL.txt').is_file())
            self.profiler = None
            if os.environ.get('TWOBYTEASR_LOADING_PROFILE') == '1':
                import cProfile
                self.profiler = cProfile.Profile()
                self.profiler.enable()
            from ..design import theme_manager
            original_mark = theme_manager._trace_mark
            def mark(label, started=None):
                now = time.perf_counter()
                self.result['spans'].append(dict(label=label, ms=round((now-started)*1000,3) if started else None))
                return original_mark(label, started)
            theme_manager._trace_mark = mark
            original_root = theme_manager._ThemeRootFilter.apply_root
            def root_apply(owner, widget):
                began = time.perf_counter()
                result = original_root(owner, widget)
                elapsed = (time.perf_counter()-began)*1000
                if elapsed > 5:
                    self.result.setdefault('theme_roots', []).append(dict(name=widget.objectName(),
                        type=widget.metaObject().className(), visible=widget.isVisible(), ms=round(elapsed,3)))
                return result
            theme_manager._ThemeRootFilter.apply_root = root_apply
            self.capturing = False
            self.frames = []
            self.started = time.perf_counter()
            self.last = self.started
            self.deadline = self.started + 300
            self.waiting = None
            self.sequence = self.run()
            self.heartbeat = QTimer(self)
            self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
            self.heartbeat.timeout.connect(self.beat)
            self.heartbeat.start(10)
            QApplication.instance().installEventFilter(self)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(16)
            self.capture_timer = QTimer(self)
            self.capture_timer.timeout.connect(self.frame)
            if os.environ.get('TWOBYTEASR_LOADING_RECORD') == '1':
                self.capture_timer.start(50)
            QApplication.instance().aboutToQuit.connect(self.quit)

        def save(self):
            (out / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf8')

        def session(self):
            return window.__dict__.get('_studio_loading_session')

        def beat(self):
            now = time.perf_counter()
            if self.case is not None:
                self.case['delays'].append(max(0, (now-self.last)*1000-10))
            self.last = now

        def eventFilter(self, obj, event):
            if self.case is not None and event.type() == QEvent.Type.Paint and not self.capturing:
                now = time.perf_counter()
                if isinstance(obj, BunnyMascot) and obj.isVisible():
                    key = str(id(obj))
                    self.case['mascot_paints'].setdefault(key, []).append((now-self.case['start'])*1000)
                if isinstance(obj, QWidget) and obj.isVisible():
                    self.case.setdefault('first_paint_ms', (now-self.case['start'])*1000)
                if obj is self.feedback_widget and obj.isChecked() and not obj.isDown():
                    self.case.setdefault('feedback_ms', (now-self.case['start'])*1000)
            return False

        def begin(self, name):
            self.case = dict(name=name, start=time.perf_counter(), delays=[], mascot_paints={})
            self.last = self.case['start']

        def project_state(self, page):
            return (id(page.project), page.timeline.playhead_ms, page.selected_cue_id,
                page.timeline.visible_start_ms, page.timeline.visible_duration_ms,
                page.cue_table.verticalScrollBar().value(), page.context_drawer.currentIndex())

        def end(self):
            case, self.case = self.case, None
            self.feedback_widget = None
            if case is None:
                return
            case['ready_ms'] = round((time.perf_counter()-case.pop('start'))*1000, 3)
            case['event_loop'] = summary(case.pop('delays'))
            series = case.pop('mascot_paints')
            gaps = [b-a for values in series.values() for a,b in zip(values, values[1:])]
            case['mascot'] = dict(summary(gaps), paint_count=sum(map(len, series.values())),
                raw_times_ms=series, expected_frame_ms=16)
            page = window.built_page('studio')
            if page is not None:
                case['workspace'] = page._workspace_build_profile
                case['open_profile'] = page.last_open_profile
            session = self.session()
            if session is not None:
                case['stages'] = list(session.events)
            self.result['cases'].append(case)
            self.save()

        def ready(self, path=None):
            page = window.built_page('studio')
            session = self.session()
            if session is not None and session.state == 'failed':
                raise AssertionError(session.view.label.text())
            if page is None or session is None or session.view.isVisible():
                return False
            if path is None:
                return page._project_view_state == 'hub'
            gate = getattr(page, '_readiness', None)
            if gate is not None and gate.profile.get('error'):
                raise AssertionError(str(gate.profile['error']))
            return bool(gate is not None and gate.ready and str(page.project_path) == str(Path(path).resolve()))

        def frame(self):
            session = self.session()
            if session is None or not session.view.isVisible():
                return
            view = session.view
            bunny = view.library_bunny if view.library_mode else view.perch
            self.capturing = True
            try:
                stamp = time.perf_counter()-self.started
                name = f'bunny-{len(self.frames):05}.png'
                bunny.grab().save(str(out / name))
                self.frames.append(dict(file=name, seconds=stamp, stage=view.library_steps.current if view.library_mode else view.steps_view.current))
            finally:
                self.capturing = False

        def check(self, name, passed, **details):
            self.result['checks'].append(dict(name=name, passed=bool(passed), **details))
            self.save()
            if not passed:
                raise AssertionError(name)

        def run(self):
            window.resize(1440, 900)
            yield .4
            for key in ('grape', 'sand', 'graphite', 'sand'):
                from ..design.ui_theme import THEMES
                if key not in THEMES:
                    continue
                self.begin('theme-home-'+key)
                apply_theme(key)
                self.case['dispatch_ms'] = (time.perf_counter()-self.case['start'])*1000
                yield lambda key=key: theme_key() == key and not getattr(QApplication.instance(), '_theme_update_pending', False)
                self.case['theme_stable_ms'] = (time.perf_counter()-self.case['start'])*1000
                yield .15
                self.end()
            mode = os.environ.get('TWOBYTEASR_LOADING_MODE', 'all')
            if mode == 'flows':
                yield from self.flows()
                self.result['passed'] = True
                self.save()
                window.close()
                yield 10
                return
            if mode != 'cold-project':
                self.begin('library-cold')
                window.open_studio_project()
                yield lambda: self.ready()
                self.end()
                window._return_to_settings()
                yield .2
                self.begin('library-warm')
                window.open_studio_project()
                yield lambda: self.ready()
                self.end()
            for count in ((12,) if mode == 'cold-project' else (12, 2000, 10000)):
                path = out / f'p{count}/project.2byteproj'
                self.begin(f'project-{count}')
                window.open_studio_project(str(path))
                yield lambda path=path: self.ready(path)
                self.end()
                page = window.built_page('studio')
                self.check(f'{count} captions retained', len(page.project.cues) == count)
                page.undo_stack.setClean()
                yield .15
                if count == 12:
                    window.grab().save(str(out / 'editor.png'))
                for key in ('grape', 'sand'):
                    self.begin(f'theme-{count}-{key}')
                    identity = self.project_state(page)
                    apply_theme(key)
                    self.case['dispatch_ms'] = (time.perf_counter()-self.case['start'])*1000
                    yield lambda key=key: theme_key() == key and not getattr(QApplication.instance(), '_theme_update_pending', False)
                    self.case['theme_stable_ms'] = (time.perf_counter()-self.case['start'])*1000
                    yield .15
                    self.end()
                    self.check(f'theme preserves {count} project, playhead, selection and scroll',
                        self.project_state(page) == identity)
                page.show_project_hub(skip_dirty_guard=True)
                yield .2
            if (out/'real/project.2byteproj').is_file():
                path = out/'real/project.2byteproj'
                self.begin('real-project')
                window.open_studio_project(str(path))
                yield lambda: self.ready(path)
                self.end()
                page = window.built_page('studio')
                self.check('real project copy opens', len(page.project.cues) == json.loads((out/'real-input.json').read_text('utf8'))['count'])
                before = self.project_state(page)
                apply_theme('grape')
                yield lambda: theme_key() == 'grape' and not getattr(QApplication.instance(),'_theme_update_pending',False)
                self.check('real project state survives theme switch', self.project_state(page) == before)
                page.undo_stack.setClean()
                window.grab().save(str(out/'real-editor.png'))
                page.show_project_hub(skip_dirty_guard=True)
                yield .2
            if mode == 'stress':
                import psutil
                process = psutil.Process()
                samples = []
                for index in range(10):
                    path = out/f'p{12 if index%2 else 2000}/project.2byteproj'
                    window.open_studio_project(str(path))
                    yield lambda path=path: self.ready(path)
                    page.undo_stack.setClean()
                    page.show_project_hub(skip_dirty_guard=True)
                    yield .15
                    children = [child for child in process.children(recursive=True) if child.is_running()]
                    samples.append(dict(iteration=index+1, parent_mib=round(process.memory_info().rss/2**20,2), children=len(children)))
                yield 1
                self.result['resource_cycles'] = samples
                self.check('one retained workspace across ten opens', window.built_page('studio') is page)
            session = self.session()
            self.result['passed'] = True
            self.save()
            window.close()
            yield 10

        def flows(self):
            self.begin('cold-library-cancel')
            window.open_studio_project()
            session = self.session()
            QTimer.singleShot(60, self, lambda: QTest.mouseClick(session.view.back, Qt.MouseButton.LeftButton))
            yield lambda: not session.view.isVisible() and session.state == 'cancelled'
            self.end()
            self.check('cancel returns home', window.pages.currentWidget() is window.settings_scroll)
            partial = window.__dict__.get('_studio_page_building')
            self.begin('library-resume-after-cancel')
            window.open_studio_project()
            yield lambda: self.ready()
            self.end()
            page = window.built_page('studio')
            self.check('resume reuses partial workspace', partial is None or page is partial)
            # A deliberately slow reader exercises the real loading view with
            # actual hydration/player work afterwards. It is not an external disk claim.
            from ..projects import studio_project as project_module
            original_load = project_module.load_project
            def slow_load(*args, **kwargs):
                time.sleep(.7)
                return original_load(*args, **kwargs)
            project_module.load_project = slow_load
            path = out / 'p12/project.2byteproj'
            target = out / 'p2000/project.2byteproj'
            self.begin('slow-reader-switch-target')
            window.open_studio_project(str(path))
            QTimer.singleShot(100, self, lambda: window.open_studio_project(str(target)))
            yield lambda: self.ready(target)
            self.end()
            project_module.load_project = original_load
            self.check('latest project owns callbacks', len(page.project.cues) == 2000 and page._readiness.path == str(target))
            page.undo_stack.setClean()
            page.show_project_hub(skip_dirty_guard=True)
            yield .15
            self.begin('missing-project-error')
            window.open_studio_project(str(out/'missing-file.2byteproj'))
            yield lambda: self.session().state == 'failed'
            self.end()
            self.check('missing project shows reason', bool(session.view.label.text()) and session.view.cover.line != '正在读取工程')
            session.view.grab().save(str(out/'missing-project.png'))
            QTest.mouseClick(session.view.back, Qt.MouseButton.LeftButton)
            yield lambda: not session.view.isVisible()
            self.begin('missing-media')
            window.open_studio_project(str(out/'missing-media.2byteproj'))
            yield lambda: self.session().state == 'failed' or self.ready(out/'missing-media.2byteproj')
            self.end()
            self.result['missing_media_state'] = dict(state=session.state, status=session.view.label.text(),
                editor_status=page.save_state.text(), caption=session.view.cover.line)
            if session.state == 'failed':
                QTest.mouseClick(session.view.back, Qt.MouseButton.LeftButton)
                yield lambda: not session.view.isVisible()
            # Real application-settings entry and real theme-card click.
            QTimer.singleShot(0, window, window._open_application_settings)
            yield lambda: window.__dict__.get('_application_settings_dialog') is not None and window._application_settings_dialog.isVisible()
            dialog = window._application_settings_dialog
            dialog.ensure_section('外观')
            yield .1
            card = dialog.theme_gallery.card('grape')
            from PySide6.QtWidgets import QScrollArea
            node = card.parentWidget()
            while node is not None and not isinstance(node, QScrollArea):
                node = node.parentWidget()
            if node is not None:
                node.ensureWidgetVisible(card, 0, 24)
            yield .1
            self.begin('settings-card-theme-feedback')
            self.feedback_widget = card
            QTest.mouseClick(card, Qt.MouseButton.LeftButton)
            yield lambda: (theme_key() == 'grape' and not getattr(QApplication.instance(),'_theme_update_pending',False)
                          and self.case.get('feedback_ms') is not None)
            self.case['theme_stable_ms'] = (time.perf_counter()-self.case['start'])*1000
            self.end()
            for key in ('sand','graphite','warm','grape','sand'):
                QTest.mouseClick(dialog.theme_gallery.card(key), Qt.MouseButton.LeftButton)
            yield lambda: theme_key() == 'sand' and not getattr(QApplication.instance(),'_theme_update_pending',False)
            self.check('rapid theme final selection wins', theme_key() == 'sand')
            dialog.grab().save(str(out/'settings-theme.png'))
            dialog.done(0)
            yield lambda: not dialog.isVisible()
            if self.result['font'] is not None:
                self.check('font is bundled and registered', self.result['font']['application_font_id'] >= 0
                    and self.result['font']['bundled_font'] and self.result['font']['bundled_license'])

        def tick(self):
            try:
                if time.perf_counter() > self.deadline:
                    raise TimeoutError('Theme/loading audit exceeded deadline')
                if self.waiting is not None:
                    if callable(self.waiting):
                        if not self.waiting():
                            return
                    elif time.perf_counter() < self.waiting:
                        return
                step = next(self.sequence)
                self.waiting = step if callable(step) else time.perf_counter()+float(step)
                session = self.session()
                if (os.environ.get('TWOBYTEASR_LOADING_RECORD') == '1'
                        and session is not None and session.view.isVisible()):
                    key = (session.generation, session.view.steps_view.current, session.state)
                    if key != getattr(self, '_capture_stage', None):
                        self._capture_stage = key
                        self.result.setdefault('loading_styles', []).append(dict(stage=key[1],
                            eyebrow_scope=session.view.eyebrow.__dict__.get('_theme_component_scope'),
                            eyebrow_local=session.view.eyebrow.styleSheet()[:80],
                            line=session.view.cover.line))
                    self.capturing = True
                    session.view.grab().save(str(out / 'loading-latest.png'))
                    self.capturing = False
            except StopIteration:
                self.timer.stop()
            except Exception:
                self.capturing = False
                self.end()
                self.result['error'] = traceback.format_exc()
                self.result['passed'] = False
                self.save()
                self.timer.stop()
                modal = QApplication.activeModalWidget() or window.__dict__.get('_application_settings_dialog')
                if modal is not None:
                    modal.done(0)
                window.close()

        def quit(self):
            if self.profiler is not None:
                self.profiler.disable()
                self.profiler.dump_stats(str(out / 'gui.prof'))
            self.result['normal_shutdown'] = True
            self.result['frames'] = self.frames
            self.save()

    window._theme_loading_audit = Audit()
