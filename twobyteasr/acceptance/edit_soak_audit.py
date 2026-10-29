"""Investigation (2026-10-21): does each typed edit + Enter freeze longer as a session goes on?

User report: a project with 1,000+ bilingual subtitles is fast at first; after manual
edits and Enter the window stops for seconds, worse and worse, then the app closes.
Earlier: selecting 1,000+ cues and clicking the style scope 「已选」 was slow.

Part A (optional, TWOBYTEASR_SOAK_BATCH=1): select all cues, click 「已选」, move Y.
Part B: N iterations on different cues: select, open the inline editor, type with
posted key events, post Enter, then watch a 10 ms GUI heartbeat until it is quiet.
Every iteration records the longest GUI gap after Enter, time to commit, and the
project/session sizes that could grow (style recipes, undo stack, Qt objects, RSS).
Not shipped; lives only in this investigation copy.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            (Path(output) / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


def run(output, *, window):
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt, QTimer
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    import psutil
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity

    fixture = Path(os.environ['TWOBYTEASR_EDITOR_FIXTURES'])
    size = int(os.environ.get('TWOBYTEASR_EDITOR_SIZE', '2000'))
    iterations = int(os.environ.get('TWOBYTEASR_SOAK_ITERATIONS', '150'))
    batch = os.environ.get('TWOBYTEASR_SOAK_BATCH', '0') == '1'
    mode = os.environ.get('TWOBYTEASR_EDITOR_MODE', 'paused')
    budget = int(os.environ.get('TWOBYTEASR_EDITOR_SOAK_SECONDS', '900'))
    # 2026-10-22 (report-eb10): optional user-like steps, all off by default.
    seek = os.environ.get('TWOBYTEASR_SOAK_SEEK', '0') == '1'
    pause_every = int(os.environ.get('TWOBYTEASR_SOAK_PAUSE_EVERY', '0') or 0)
    pause_s = float(os.environ.get('TWOBYTEASR_SOAK_PAUSE_S', '4') or 4)
    click_every = int(os.environ.get('TWOBYTEASR_SOAK_CLICK_EVERY', '0') or 0)
    search_text = os.environ.get('TWOBYTEASR_SOAK_SEARCH', '')
    page = window.studio_page
    window.resize(1440, 900)
    window.show()
    result = dict(passed=False, size=size, iterations_requested=iterations, batch=batch, mode=mode,
                  seek=seek, pause_every=pause_every, pause_s=pause_s, click_every=click_every,
                  search_text=search_text,
                  frozen=bool(getattr(sys, 'frozen', False)), identity=load_build_identity().to_dict(),
                  method='posted QKeyEvent typing and Enter; GUI blocked time = longest gap of a 10 ms QTimer heartbeat',
                  batch_steps=[], rows=[])
    process = psutil.Process()

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def wait(predicate, seconds=60):
        end = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() > end:
                raise TimeoutError('soak condition timed out')
            QTest.qWait(10)

    # Heartbeat: every tick records the gap since the previous tick.
    beats = []
    last = [time.perf_counter()]

    def tick():
        now = time.perf_counter()
        beats.append((now, (now - last[0]) * 1000))
        last[0] = now
    heart = QTimer()
    heart.setInterval(10)
    heart.setTimerType(Qt.TimerType.PreciseTimer)
    heart.timeout.connect(tick)
    heart.start()

    def blocked_since(t0):
        return max((gap for stamp, gap in beats if stamp >= t0), default=0.0)

    def settle(t0, quiet_ms=400, limit_s=30):
        """Pump events until no gap >50 ms for quiet_ms; return (settled ms, longest gap ms)."""
        end = time.monotonic() + limit_s
        while time.monotonic() < end:
            QTest.qWait(20)
            recent = [stamp for stamp, gap in beats if stamp >= t0 and gap > 50]
            quiet_from = recent[-1] if recent else t0
            if (time.perf_counter() - quiet_from) * 1000 >= quiet_ms:
                return (quiet_from - t0) * 1000, blocked_since(t0)
        return None, blocked_since(t0)

    def sizes():
        project = page.project
        recipes = getattr(project, 'style_recipes', {}) or {}
        return dict(rss_mb=round(process.memory_info().rss / 1024 ** 2, 1), handles=process.num_handles(),
                    qt_objects=len(page.findChildren(QObject)), widgets=len(QApplication.allWidgets()),
                    undo=page.undo_stack.count(), styles=len(getattr(project, 'styles', []) or []),
                    recipes=len(recipes), cue_styles=len({c.style_id for c in project.cues}),
                    ass_profile=len(getattr(page, '_ass_profile', []) or []),
                    translations=len((project.generation_metadata or {}).get('translations') or {}))

    kernel = ctypes.WinDLL('kernel32')
    kernel.GetTickCount64.restype = ctypes.c_ulonglong

    def post_keys(editor, specs, interval=0.03):
        errors = []

        def produce():
            try:
                for key, text in specs:
                    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
                    event.setTimestamp(int(kernel.GetTickCount64()) & 0xFFFFFFFF)
                    QCoreApplication.postEvent(editor, event)
                    time.sleep(interval)
            except Exception:
                errors.append(traceback.format_exc())
        thread = threading.Thread(target=produce, daemon=True)
        thread.start()
        wait(lambda: not thread.is_alive(), 30)
        if errors:
            raise RuntimeError(errors[0])

    # Exceptions raised inside Qt virtual overrides (eventFilter) go to
    # sys.excepthook; count them by type.
    exceptions = []
    previous_hook = sys.excepthook

    def counting_hook(kind, value, trace):
        exceptions.append(kind.__name__)
        previous_hook(kind, value, trace)
    sys.excepthook = counting_hook
    try:
        path = output / f'{size}.2byteproj'
        path.write_bytes((fixture / f'{size}.2byteproj').read_bytes())
        window.open_studio_project(path, mode='edit', source='edit_soak_audit')
        wait(lambda: page.project is not None and page._readiness.ready, 120)
        page.video.set_paused(True)
        QTest.qWait(1500)
        result['initial'] = sizes()
        save()
        started = time.monotonic()
        if batch:
            t0 = time.perf_counter()
            page._select_all_timeline_cues()
            settled, gap = settle(t0)
            result['batch_steps'].append(dict(step='select_all', settled_ms=settled, longest_gap_ms=gap, **sizes()))
            save()
            t0 = time.perf_counter()
            page.style_scope.setCurrentIndex(page.style_scope.findData('selected'))
            settled, gap = settle(t0)
            result['batch_steps'].append(dict(step='scope_selected', settled_ms=settled, longest_gap_ms=gap, **sizes()))
            save()
            for value in (900, 860):
                t0 = time.perf_counter()
                page.style_position_y.setValue(value)
                page.style_position_y.editingFinished.emit()
                settled, gap = settle(t0)
                result['batch_steps'].append(dict(step=f'position_y_{value}', settled_ms=settled, longest_gap_ms=gap, **sizes()))
                save()
            _capture(window, output / 'after-batch.png')
        page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
        QTest.qWait(500)
        for i in range(iterations):
            if time.monotonic() - started > budget:
                result['stopped_by_budget'] = True
                break
            cue_id = f'c{(i * 37) % size}'
            t_sel = time.perf_counter()
            page.select_cue(cue_id)
            if seek:
                cue = page._cue_lookup[cue_id]
                page._seek((cue.start_ms + cue.end_ms) / 2000)
            sel_settled, sel_gap = settle(t_sel, quiet_ms=200)
            page._begin_canvas_inline_edit()
            wait(lambda: page._canvas_editor is not None and page.subtitle_edit_input.isVisible(), 10)
            editor = page.subtitle_edit_input
            QTest.qWait(100)
            t_type = time.perf_counter()
            post_keys(editor, [(Qt.Key.Key_End, '')] + [(Qt.Key.Key_X, 'x')] * 5)
            QTest.qWait(150)
            typing_gap = blocked_since(t_type)
            expected = editor.toPlainText()
            by_click = bool(click_every) and i % click_every == click_every - 1
            t0 = time.perf_counter()
            if by_click:
                # A real press through the window: Qt hands it to the QWindow
                # first, then to the timeline ruler under the pointer.
                ruler = page.timeline
                point = ruler.mapTo(window, QPoint(ruler.width() // 2, 6))
                QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier, point)
            else:
                QCoreApplication.postEvent(editor, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, '\r'))
            wait(lambda: page._canvas_editor is None, 30)
            commit_ms = (time.perf_counter() - t0) * 1000
            settled, gap = settle(t0)
            committed = page._cue_lookup[cue_id].text == expected
            row = dict(i=i, cue=cue_id, commit_by='click' if by_click else 'enter',
                       commit_ms=round(commit_ms, 1), enter_settled_ms=None if settled is None else round(settled, 1),
                       enter_longest_gap_ms=round(gap, 1), select_settled_ms=None if sel_settled is None else round(sel_settled, 1),
                       select_longest_gap_ms=round(sel_gap, 1), typing_longest_gap_ms=round(typing_gap, 1),
                       committed=committed, elapsed_s=round(time.monotonic() - started, 1))
            if pause_every and i % pause_every == pause_every - 1:
                # The user stops to read or listen: autosave fires after 3 s idle.
                profile = getattr(page, '_autosave_profile', None)
                before_saves = len(profile) if profile is not None else 0
                t_pause = time.perf_counter()
                QTest.qWait(int(pause_s * 1000))
                wait(lambda: not getattr(page, '_autosave_worker_running', False), 60)
                settle(t_pause, quiet_ms=200)
                saves = list(profile[before_saves:]) if profile is not None else []
                row.update(pause_ms=round((time.perf_counter() - t_pause) * 1000, 1),
                           pause_longest_gap_ms=round(blocked_since(t_pause), 1),
                           pause_autosaves=saves)
            if i % 5 == 0 or gap > 500:
                row.update(sizes())
            result['rows'].append(row)
            if not committed:
                raise AssertionError(f'edit not committed on {cue_id}')
            if i % 20 == 19:
                page.save()
            if len(beats) > 200000:
                del beats[:100000]
            if i % 10 == 9:
                save()
        if search_text:
            # Live search runs on every keystroke (180 ms debounce).
            from ..studio.studio_find_replace import FindReplaceDialog
            dialog = FindReplaceDialog(page, page)
            dialog.show()
            QTest.qWait(500)
            result['search'] = []
            for char in search_text:
                t0 = time.perf_counter()
                dialog.find_edit.insert(char)
                QTest.qWait(250)
                settled, gap = settle(t0)
                result['search'].append(dict(char=char, settled_ms=None if settled is None else round(settled, 1),
                                             longest_gap_ms=round(gap, 1)))
            save()
            dialog.close()
            dialog.deleteLater()
            QTest.qWait(200)
        result['final'] = sizes()
        rows = result['rows']

        def median(values):
            values = sorted(v for v in values if v is not None)
            return values[len(values) // 2] if values else None
        head, tail = rows[:20], rows[-20:]
        result['trend'] = dict(
            first20_enter_gap_median=median(r['enter_longest_gap_ms'] for r in head),
            last20_enter_gap_median=median(r['enter_longest_gap_ms'] for r in tail),
            first20_commit_median=median(r['commit_ms'] for r in head),
            last20_commit_median=median(r['commit_ms'] for r in tail),
            first20_select_gap_median=median(r['select_longest_gap_ms'] for r in head),
            last20_select_gap_median=median(r['select_longest_gap_ms'] for r in tail),
            max_enter_gap=max((r['enter_longest_gap_ms'] for r in rows), default=None))
        _capture(window, output / 'final.png')
        result['passed'] = True
    except Exception:
        result['error'] = traceback.format_exc()
        try:
            _capture(window, output / 'failure.png')
        except Exception:
            pass
    finally:
        sys.excepthook = previous_hook
        result['python_exceptions'] = {name: exceptions.count(name) for name in sorted(set(exceptions))}
        heart.stop()
        try:
            page.undo_stack.setClean()
        except Exception:
            pass
        save()
    return 0 if result['passed'] else 1
