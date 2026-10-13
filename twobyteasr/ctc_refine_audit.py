"""Real-window check of the Studio CTC line-start action (2026-10-13).

Opens a copy of a Japanese project, opens the real timeline context menu,
clicks "按 CTC 对齐模型校正日语句首（整个工程）", waits for the background
measurement, and checks: one undo step, only starts (and same-speaker cuts
that move with them) change, every move agrees within 80 ms with its
reference, undo restores everything, redo re-applies, text/speakers/
translations unchanged.
"""
from __future__ import annotations

import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication, QMenu
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], identity=load_build_identity().to_dict(), passed=False)
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def snapshot():
        from .bilingual_layout import translations_of
        return ({c.id: (c.start_ms, c.end_ms) for c in page.project.cues},
                {c.id: (c.text, c.speaker_id) for c in page.project.cues},
                dict(translations_of(page.project.generation_metadata)))

    def pick_menu_action():
        menus = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible()]
        for menu in menus:
            for action in menu.actions():
                if action.text().startswith('按 CTC 对齐模型校正日语句首'):
                    result['menu_action_enabled'] = action.isEnabled()
                    action.trigger()
                    menu.close()
                    return
        if menus:
            result['menu_texts'] = [a.text() for a in menus[0].actions()]
            menus[0].close()
        else:
            QTimer.singleShot(200, pick_menu_action)

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='ctc_refine_audit')
        yield ready
        yield 1.5
        if not page.video._paused:
            page._toggle_playback()
            yield .3
        times0, texts0, translations0 = snapshot()
        index0 = page.undo_stack.index()
        cue = page.project.cues[len(page.project.cues) // 3]
        page.select_cue(cue.id)
        yield .5
        QTimer.singleShot(600, pick_menu_action)
        page._show_timeline_menu(cue.id, QCursor.pos())      # the real menu (nested loop until picked)
        yield .3
        check('menu offers the CTC action and it is enabled', result.get('menu_action_enabled') is True,
              result.get('menu_texts'))
        started = time.monotonic()
        yield lambda: getattr(page, '_ctc_refine_signals', None) is None and page.undo_stack.index() != index0 \
            or time.monotonic() - started > 600
        result['seconds'] = round(time.monotonic() - started, 1)
        status = page.save_state.text()
        result['status'] = status
        check('one undo step named for the action', page.undo_stack.index() == index0 + 1
              and page.undo_stack.text(index0) == '按 CTC 对齐模型校正日语句首', status)
        times1, texts1, translations1 = snapshot()
        moved_starts = [k for k in times0 if times0[k][0] != times1[k][0]]
        moved_ends = [k for k in times0 if times0[k][1] != times1[k][1]]
        result['moved_starts'] = len(moved_starts)
        result['moved_ends'] = len(moved_ends)
        result['median_move_ms'] = sorted(times1[k][0] - times0[k][0] for k in moved_starts)[len(moved_starts) // 2] \
            if moved_starts else None
        check('starts moved; text, speakers and translations unchanged', moved_starts and texts1 == texts0
              and translations1 == translations0, dict(starts=len(moved_starts), ends=len(moved_ends)))
        by_start = {times1[k][0]: k for k in moved_starts}
        ends_ok = all(times1[k][1] in by_start for k in moved_ends)
        check('ends move only together with the next line of the same speaker (cut)', ends_ok, len(moved_ends))
        check('no line shorter than 300 ms after the moves',
              all(times1[k][1] - times1[k][0] >= 300 for k in moved_starts + moved_ends))
        from .studio_cut_refine import _measured
        by_id = {c.id: c for c in page.project.cues}
        references = {k: (_measured(page.project, by_id[k], 'start') or times0[k][0]) for k in moved_starts}
        off = {k: times1[k][0] - references[k] for k in moved_starts if abs(times1[k][0] - references[k]) > 80}
        check('every moved start is within 80 ms of its reference and moved at most 600 ms',
              not off and all(abs(times1[k][0] - times0[k][0]) <= 600 for k in moved_starts),
              dict(off_reference=off, largest=max((abs(times1[k][0] - times0[k][0]) for k in moved_starts), default=0)))
        page.timeline.set_visible_window(max(0, times1[moved_starts[0]][0] - 4000), 12000) if moved_starts else None
        yield .6
        _capture(window, output / 'after-ctc.png')
        page.undo_stack.undo()
        yield .8
        check('undo restores every start and end', snapshot()[0] == times0)
        page.undo_stack.redo()
        yield .8
        check('redo applies the same moves', snapshot()[0] == times1)
        result['passed'] = all(c['passed'] for c in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
        save()
        log.close()
        page.session.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def tick():
        if state.get('ticking'):
            return
        state['ticking'] = True
        try:
            if state['wait'] is not None:
                if state['wait']():
                    state['wait'] = None
                elif time.monotonic() > state['deadline']:
                    raise TimeoutError('Real GUI condition did not settle')
                else:
                    return
            if time.monotonic() < state['until']:
                return
            value = next(iterator)
            if callable(value):
                state.update(wait=value, deadline=time.monotonic() + 700)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            try:
                _capture(window, output / 'failure.png')
            except Exception:
                pass
            finish()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
