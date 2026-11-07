"""Full-recording coverage and interactive zoom through the normal Studio."""
import cProfile
import json
import os
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import numpy as np

    app = QApplication.instance()
    result = dict(passed=False, checks={}, views=[], interactions=[], progress=[],
                  profiled=os.environ.get('WAVEFORM_FULL_PROFILE', '1') == '1',
                  scope='Canonical MainWindow, read-only full media, Qt input and paint observations')
    beats = []
    previous = [time.perf_counter()]
    timer = QTimer(window)
    timer.setInterval(10)

    def heartbeat():
        now = time.perf_counter()
        beats.append((now - previous[0]) * 1000)
        previous[0] = now

    timer.timeout.connect(heartbeat)

    def receipt():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def check(name, value):
        result['checks'][name] = bool(value)
        receipt()
        if not value:
            raise AssertionError(name)

    def wait(predicate, timeout=120):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            app.processEvents()
            time.sleep(.003)
        raise TimeoutError('full waveform audit wait')

    def ready_page():
        page = window.built_page('studio')
        return page if page is not None and page.project is not None and page._readiness.ready else None

    def run():
        page = None
        try:
            began = time.perf_counter()
            window.open_studio_project(os.environ['EDIT_SAVE_PROJECT'])
            wait(ready_page)
            page = ready_page()
            page.video.set_paused(True)
            timeline = page.timeline
            previous[0] = time.perf_counter()
            timer.start()
            check('recording exceeds five hours', page.project.media.duration_ms > 18_000_000)
            last_progress = [None]

            def completed():
                cache = timeline.cache
                if cache is None:
                    return False
                state = (cache.metadata.incomplete, cache.metadata.coverage_end_ms, str(cache.root))
                if state != last_progress[0]:
                    result['progress'].append(dict(at_ms=(time.perf_counter() - began) * 1000,
                                                   incomplete=state[0], coverage_end_ms=state[1], root=state[2]))
                    last_progress[0] = state
                return not page._waveform_inflight and not cache.metadata.incomplete and not cache.root.name.endswith('coarse-v1')

            wait(completed, 600)
            result['full_ready_ms'] = (time.perf_counter() - began) * 1000
            cache = timeline.cache
            result['cache'] = cache.metadata.to_dict()
            duration = page.project.media.duration_ms
            check('decoded coverage reaches recording end', cache.metadata.coverage_end_ms >= duration - 64)
            timeline._manual_view_hold = True

            def settled():
                worker = getattr(timeline, '_waveform_tile_worker', None)
                return worker is not None and worker.signature is None and not getattr(timeline, '_waveform_tile_jobs', {})

            for label, start_ms in [('beginning', 0), ('middle', duration // 2), ('end', duration - 60_000)]:
                timeline.set_visible_window(start_ms, 60_000)
                timeline.update()
                QTest.qWait(30)
                wait(settled, 30)
                level, pairs = cache.read_window(start_ms, min(duration, start_ms + 60_000), 1200)
                check(label + ' has decoded samples', len(pairs) > 0)
                check(label + ' has nonzero waveform', bool(np.max(np.abs(pairs)) > 1e-6))
                worker = timeline._waveform_tile_worker
                before = worker.serial
                for _ in range(20):
                    timeline.update()
                    QTest.qWait(20)
                check(label + ' remains terminal', worker.serial == before)
                timeline.grab().save(str(output / (label + '.png')))
                result['views'].append(dict(name=label, start_ms=start_ms, buckets=len(pairs),
                    level=level.level, serial=worker.serial, paint=dict(getattr(timeline, '_last_paint_stats', {}))))
                receipt()

            timeline.set_visible_window(duration // 2, 600_000)
            timeline.update()
            QTest.qWait(20)
            profiler = cProfile.Profile()
            if result['profiled']:
                profiler.enable()
            for index, delta in enumerate([-120] * 20 + [120] * 20):
                position = QPointF(timeline.rect().center())
                event = QWheelEvent(position, QPointF(timeline.mapToGlobal(position.toPoint())),
                    QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
                beat_index = len(beats)
                began_input = time.perf_counter()
                app.sendEvent(timeline, event)
                handler_ms = (time.perf_counter() - began_input) * 1000
                QTest.qWait(20)
                result['interactions'].append(dict(kind='ctrl-wheel', index=index, handler_ms=handler_ms,
                    gap_ms=max(beats[beat_index:], default=handler_ms), start_ms=timeline.visible_start_ms,
                    duration_ms=timeline.visible_duration_ms, paint=dict(getattr(timeline, '_last_paint_stats', {}))))
            if result['profiled']:
                profiler.disable()
                profiler.dump_stats(str(output / 'wheel.pstats'))
            wait(settled, 30)

            slider = page.timeline_zoom_slider
            profiler = cProfile.Profile()
            if result['profiled']:
                profiler.enable()
            for value in [0, 250, 500, 750, 1000, 500, 0]:
                beat_index = len(beats)
                began_input = time.perf_counter()
                slider.setValue(value)
                handler_ms = (time.perf_counter() - began_input) * 1000
                QTest.qWait(30)
                result['interactions'].append(dict(kind='toolbar-slider', value=value, handler_ms=handler_ms,
                    gap_ms=max(beats[beat_index:], default=handler_ms), start_ms=timeline.visible_start_ms,
                    duration_ms=timeline.visible_duration_ms, paint=dict(getattr(timeline, '_last_paint_stats', {}))))
            if result['profiled']:
                profiler.disable()
                profiler.dump_stats(str(output / 'slider.pstats'))
            wait(settled, 30)
            timeline.grab().save(str(output / 'whole-recording.png'))
            check('zoom tasks settle', settled())
            check('waveform remains ready', timeline.waveform_state == 'READY')
            result['max_event_loop_gap_ms'] = max(beats, default=0)
            result['passed'] = all(result['checks'].values())
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            timer.stop()
            receipt()
            if page is not None:
                page.undo_stack.setClean()
                page.project_dirty = False
            window.close()

    app.aboutToQuit.connect(lambda: (result.update(gui_shutdown=True), receipt()))
    QTimer.singleShot(1200, run)
