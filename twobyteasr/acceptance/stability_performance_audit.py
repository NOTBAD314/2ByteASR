"""Deterministic MainWindow replay, real Qt edits and bounded telemetry."""
from __future__ import annotations

from collections import defaultdict, deque
import json
import os
import random
import time
import traceback


def distribution(values):
    values = sorted(values)
    if not values:
        return dict(n=0)
    result = dict(n=len(values), p50=values[(len(values)-1)//2],
                  p95=values[min(len(values)-1, int(len(values)*.95))], maximum=max(values),
                  over_100_ms=sum(value>100 for value in values),
                  over_500_ms=sum(value>500 for value in values),
                  over_2000_ms=sum(value>2000 for value in values))
    if len(values) >= 1000:
        result['p99'] = values[min(len(values)-1, int(len(values)*.99))]
    else:
        result['p99'] = None
        result['sampling_note'] = 'fewer than 1000 samples'
    return result


def start(window, output):
    from PySide6.QtCore import QObject, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import launch_identity_payload
    from ..projects.studio_project import load_project
    from .blank_project_audit import _capture

    config = json.loads((output / 'configuration.json').read_text('utf8'))
    app = QApplication.instance()

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.started = time.perf_counter()
            self.completed = 0
            self.phase = 'startup'
            self.busy = False
            self.pending_until = 0
            self.last_paint = 0
            self.previous_beat = time.perf_counter()
            self.next_disk_beat = 0
            self.gaps = deque(maxlen=100000)
            self.latencies = defaultdict(lambda:deque(maxlen=10000))
            self.edit_baselines = {}
            self.rng = random.Random(config['seed'])
            self.result = dict(passed=False, checks={}, completed=0, opens=[],
                build=launch_identity_payload(), pid=os.getpid(), dpr=window.devicePixelRatioF(),
                screen_hz=window.screen().refreshRate(), seed=config['seed'],
                measurement='Qt input to committed data and completed QWidget paint; physical scanout unmeasured')
            self.operations = (output / 'operations.jsonl').open('w', encoding='utf8')
            original_paint = self.page.timeline._paint_timeline

            def paint(event):
                original_paint(event)
                self.last_paint = time.perf_counter()
            self.page.timeline._paint_timeline = paint
            self.heartbeat = QTimer(self)
            self.heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
            self.heartbeat.timeout.connect(self.beat)
            self.heartbeat.start(10)
            self.generator = self.run()
            self.driver = QTimer(self)
            self.driver.timeout.connect(self.step)
            self.driver.start(5)
            app.aboutToQuit.connect(self.shutdown)

        def beat(self):
            now = time.perf_counter()
            self.gaps.append((now-self.previous_beat)*1000)
            self.previous_beat = now
            if now < self.next_disk_beat:
                return
            self.next_disk_beat = now+.25
            value = dict(pid=os.getpid(), monotonic=now, completed=self.completed, phase=self.phase)
            value['project_cues'] = len(self.page.project.cues) if self.page.project else None
            value['project_path'] = str(self.page.project_path)
            readiness = getattr(self.page, '_readiness', None)
            value['ready'] = getattr(readiness, 'ready', False)
            value['loading_state'] = readiness.loading.state if readiness else 'initializing'
            pending = output / 'ui-heartbeat.pending'
            pending.write_text(json.dumps(value), 'utf8')
            try:
                pending.replace(output / 'ui-heartbeat.json')
            except PermissionError:
                # The independent Windows reader can briefly hold the previous
                # file without delete-sharing. Next beat publishes the latest.
                self.result['heartbeat_publish_retries'] = self.result.get('heartbeat_publish_retries', 0)+1

        def receipt(self):
            self.result.update(completed=self.completed, elapsed_seconds=time.perf_counter()-self.started,
                               heartbeat=distribution(self.gaps),
                               latency_ms={key:distribution(values) for key,values in self.latencies.items()})
            pending = output / 'result.pending'
            pending.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')
            pending.replace(output / 'result.json')

        def check(self, name, value):
            self.result['checks'][name] = bool(value)
            if not value:
                raise AssertionError(name)

        def step(self):
            if self.busy or time.perf_counter() < self.pending_until:
                return
            self.busy = True
            try:
                delay = next(self.generator)
                self.pending_until = time.perf_counter() + (delay or 0)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def wait(self, predicate, timeout=60):
            deadline = time.perf_counter()+timeout
            while not predicate():
                if time.perf_counter() >= deadline:
                    raise TimeoutError(self.phase)
                yield .01

        def operation(self, name, action, predicate=None, paint=False, timeout=15):
            self.phase = name
            started = time.perf_counter()
            received = time.perf_counter()
            action()
            returned = time.perf_counter()
            if predicate is not None:
                yield from self.wait(predicate, timeout)
            state_at = time.perf_counter()
            painted = None
            if paint:
                self.page.timeline.update()
                yield from self.wait(lambda:self.last_paint >= state_at, timeout)
                painted = self.last_paint
            end = time.perf_counter()
            self.completed += 1
            elapsed = ((painted or state_at)-started)*1000
            self.latencies[name].append(elapsed)
            row = dict(sequence=self.completed, name=name, input_at=started, received_at=received,
                       state_at=state_at, paint_at=painted, handler_ms=(returned-received)*1000,
                       completion_ms=elapsed, status='completed')
            self.operations.write(json.dumps(row)+'\n')
            self.operations.flush()
            if self.completed%25 == 0:
                self.receipt()
            yield .01

        def idle(self):
            queue = getattr(self.page, '_persistence_queue', None)
            return queue is None or not queue.busy

        def positioned(self, target):
            observation = self.page.video.controller.observed_frame()
            position = observation.get('position')
            return (observation.get('status') == 'ready' and position is not None
                    and abs(position*1000-target)<100
                    and abs(observation.get('seek_target', -1000)*1000-target)<100)

        def open(self):
            self.phase = 'open-project'
            page = self.page
            if page.project is not None:
                if getattr(page,'project_dirty',False) or not page.undo_stack.isClean():
                    yield from self.save()
                self.phase = 'return-library'
                page._request_return_library()
                yield from self.wait(lambda:page.project is None, 60)
                self.result['library_returns'] = self.result.get('library_returns',0)+1
            name = 'fixture-alternate.2byteproj' if len(self.result['opens'])%2 else 'fixture.2byteproj'
            target = output/name
            self.phase = 'open-project'
            began = time.perf_counter()
            window.open_studio_project(str(target))
            yield from self.wait(lambda:page.project is not None
                and str(page.project_path) == str(target)
                and len(page.project.cues) == config['count'] and page._readiness.ready, 120)
            yield from self.wait(lambda:not page._readiness.overlay.isVisible(), 60)
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            self.check('source cue count', len(page.project.cues) == config['count'])
            self.result['opens'].append((time.perf_counter()-began)*1000)
            self.completed += 1
            self.receipt()

        def edit(self, number):
            page = self.page
            cue = page.project.cues[number % min(20,len(page.project.cues))]
            page.select_cue(cue.id)
            target = cue.start_ms+50
            page._seek(target/1000)
            yield from self.wait(lambda:self.positioned(target), 20)
            QApplication.setActiveWindow(window)
            window.activateWindow()
            page.timeline.setFocus()
            yield .03
            QTest.keyClick(page.timeline, Qt.Key.Key_E)
            yield from self.wait(lambda:getattr(page,'_caption_draft',None) is not None)
            draft = page._caption_draft
            key = draft.target.layer, cue.id
            base = self.edit_baselines.setdefault(key,draft.before)
            value = base + (' edit1' if draft.before == base+' edit0' else ' edit0')
            before = page.undo_stack.index()
            page.subtitle_edit_input.setPlainText(value)
            yield from self.operation('E-confirm',
                lambda:QTest.keyClick(page.subtitle_edit_input, Qt.Key.Key_Return),
                lambda:not getattr(page,'_caption_following',False), paint=True)
            self.check('edit exact text', draft.target.read(page.project) == value)
            self.check('edit one undo command', page.undo_stack.index() == before+1)
            yield from self.operation('undo', page.undo_stack.undo, paint=True)
            self.check('undo exact text', draft.target.read(page.project) == draft.before)
            yield from self.operation('redo', page.undo_stack.redo, paint=True)
            self.check('redo exact text', draft.target.read(page.project) == value)
            # Bounded-length edits remain committed for real save/reopen cycles.
            yield .02

        def save(self):
            page = self.page
            expected = [(cue.id,cue.text,cue.start_ms,cue.end_ms,cue.speaker_id) for cue in page.project.cues]
            yield from self.operation('formal-save', page.save, lambda:self.idle(), timeout=120)
            self.check('formal saved clean', page.undo_stack.isClean())
            loaded = load_project(page.project_path)
            self.check('saved full cue readback', expected ==
                       [(cue.id,cue.text,cue.start_ms,cue.end_ms,cue.speaker_id) for cue in loaded.cues])
            queue = getattr(page, '_persistence_queue', None)
            if queue:
                self.result['save_queue'] = dict(started=queue.jobs_started,
                    coalesced=queue.requests_coalesced, max_pending=queue.max_pending)
            yield .02

        def search(self):
            from ..studio.studio_find_replace import FindReplaceDialog
            dialog = FindReplaceDialog(self.page)
            dialog.show()
            dialog.text_targets.mode.setCurrentIndex(dialog.text_targets.mode.findData('original'))
            yield from self.operation('search-latest', lambda:dialog.find_edit.setText('勇者'),
                lambda:not dialog._search_timer.isActive() and not getattr(dialog,'_search_pending',False),
                timeout=60)
            self.check('search full source coverage', len(dialog._preview_hits) == config['count'])
            dialog.reject()
            dialog.deleteLater()
            yield .03

        def export(self):
            from ..exports.studio_export_ui import SubtitleExportDialog
            dialog = SubtitleExportDialog(self.page.project, self.page.project_path, self.page,
                                          export_on_accept=True, base_name='replay')
            folder = output/'exports'
            folder.mkdir(exist_ok=True)
            dialog.custom_directory.setText(str(folder))
            dialog.destination_choice.set_value('custom')
            dialog.speaker_modes['combined'].setChecked(True)
            for control in dialog.format_checks.values():
                control.setChecked(True)
            for name, control in dialog.language_checks.items():
                control.setChecked(name == 'bilingual')
            dialog.show()
            yield from self.operation('text-export-all-formats',
                lambda:QTest.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton),
                lambda:dialog._subtitle_task is None, timeout=120)
            self.check('text export produces verified artifacts', bool(dialog.artifacts)
                       and all(item.cue_count == config['count'] for item in dialog.artifacts))
            self.result['export_formats'] = list(dialog.format_checks)
            self.result['export_artifacts'] = len(dialog.artifacts)
            dialog.close()
            dialog.deleteLater()
            yield .03

        def media_pool(self):
            from pathlib import Path
            page = self.page
            panel = page.media_pool_panel
            paths = []
            source = output/'numbered-1080p30.mp4'
            for index in range(config['media_count']):
                path = output/'pool-media'/str(index)/'同名.mp4'
                path.parent.mkdir(parents=True,exist_ok=True)
                os.link(source,path)
                paths.append(path)
            initial = len(page.project.media_pool)
            previous = 0
            for count in (100,500):
                if count > config['media_count']:
                    break
                batch = paths[previous:count]
                yield from self.operation(f'media-import-{count}',lambda:panel.import_paths(batch),
                    lambda:len(page.project.media_pool)==initial+count,timeout=180)
                panel._presentation(False)
                yield .05
                panel._presentation(True)
                panel.search.setText('同名')
                yield .05
                self.check('media same names remain distinct',panel.proxy.rowCount()==count)
                panel.search.clear()
                previous = count
            _capture(window,output/'pool-media.png')

        def run(self):
            page = self.page
            window._switch_page(page)
            # Let the normal startup entry finish before issuing a new open.
            yield 1.5
            yield from self.open()
            if config.get('media_count'):
                yield from self.media_pool()
            if config['inject_freeze']:
                self.phase = 'injected-freeze'
                time.sleep(config['inject_freeze'])
                yield .1
            _capture(window, output/'initial-window.png')
            for index in range(config['edits']):
                yield from self.edit(index)
                if index and index%20 == 0:
                    yield from self.save()
            yield from self.search()
            yield from self.export()
            page.select_cue(page.project.cues[0].id)
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            page.style_layer.setCurrentIndex(page.style_layer.findData('original'))
            from ..caption_style.scoped_style import effective_layer_style
            for index in range(100):
                value = 60 + index%2
                def change_size():
                    page.style_font_size.setValue(value)
                    page._commit_style_now()
                yield from self.operation('font-size', change_size,
                    lambda:effective_layer_style(page.project,page.project.cues[0],'original').font_size==value,
                    paint=True)
                page.undo_stack.undo()
                yield .01
            for index in range(config['seeks']):
                target = self.rng.randint(200,29000)
                yield from self.operation('seek-frame-ready', lambda target=target:page._seek(target/1000),
                    lambda target=target:self.positioned(target),
                    paint=True, timeout=20)
                if index in (0,config['seeks']-1):
                    target_path = output/f'video-seek-{index}.png'
                    page.video.controller.screenshot_to_file(str(target_path), mode='window', fast=True)
                    yield from self.wait(target_path.is_file, 10)
            controller = page.video.controller
            actor = getattr(controller,'_actor',None)
            before_requests = actor.request_metrics() if actor else None
            for index in range(200):
                page._seek((500+(index*137)%28000)/1000)
            final_target = 500+(199*137)%28000
            yield from self.wait(lambda:self.positioned(final_target), 30)
            self.check('burst lands on latest target', self.positioned(final_target))
            self.result['burst'] = dict(inputs=200, before=before_requests,
                after=actor.request_metrics() if actor else None,
                frame=controller.observed_frame())
            for index in range(max(0, config['opens']-1)):
                yield from self.save()
                yield from self.open()
            until = time.perf_counter()+config['seconds']
            self.result['soak_started_at'] = time.perf_counter()
            cycle = 0
            while time.perf_counter() < until:
                yield from self.edit(cycle)
                yield from self.operation('timeline-zoom',
                    lambda:page.timeline.set_visible_window((cycle%10)*1000, 30000+(cycle%4)*10000),
                    paint=True)
                target = self.rng.randint(200,29000)
                yield from self.operation('seek-frame-ready', lambda:page._seek(target/1000),
                    lambda:self.positioned(target),
                    paint=True, timeout=20)
                page.video.set_paused(False)
                yield .3
                page.video.set_paused(True)
                if cycle%20 == 0:
                    yield from self.save()
                    yield from self.search()
                    yield from self.export()
                    self.receipt()
                if cycle and cycle%50 == 0:
                    yield from self.open()
                cycle += 1
                yield .4
            self.result['soak_cycles'] = cycle
            self.result['soak_elapsed_seconds'] = time.perf_counter()-self.result['soak_started_at']
            yield from self.save()
            _capture(window, output/'final-window.png')
            self.result['passed'] = all(self.result['checks'].values())

        def finish(self):
            self.driver.stop()
            self.receipt()
            self.operations.close()
            self.page._cancel_canvas_inline_edit()
            self.page.project_dirty = False
            self.page.undo_stack.setClean()
            window.close()
            app.quit()

        def shutdown(self):
            self.heartbeat.stop()
            self.result['gui_shutdown'] = True
            self.receipt()

    window._stability_performance_audit = Audit()
