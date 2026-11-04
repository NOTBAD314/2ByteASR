"""Opt-in real-window check of the 2026-10-22 split report (Japanese with Chinese translation).

Runs inside the normal desktop entry (source or frozen EXE) on an owned copy of
the user's project: the razor tool cuts each case at the user's own pointer
position with real QTest mouse events. Checks that the cut moved out of the
sounding word to its measured boundary, that both halves carry a piece of the
Chinese translation (flagged "needs update"), that undo/redo, merging the two
halves back and save/reopen keep the translation. Results go to
``result.json``; nothing outside ``output`` is written.
"""
import json
import time
import traceback


def _content(text):
    import unicodedata
    return "".join(ch for ch in str(text or "") if not ch.isspace()
                   and not unicodedata.category(ch).startswith(("P", "Z", "S")))


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from ..recognition.cue_word_alignment import cue_words
    from ..subtitle_rules import subtitle_translation as st
    from ..timeline.studio_commands import merge_cues_command
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(checks=[], cases=[], identity=load_build_identity().to_dict(), passed=False)
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def capture(name):
        _capture(window, output / (name + '.png'))
        event('capture', name=name)

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def by_text(text):
        return next((c for c in page.project.cues if c.text == text), None)

    def view():
        return dict(page.project.generation_metadata.get('translations') or {})

    def track_point(t, cue, ms):
        rect = t._track_layout()[0][cue.speaker_id]
        return QPoint(round(t._time_to_x(ms)), round(rect.center().y()))

    def move_pointer(t, point):
        top = t.window()
        QTest.mouseMove(top.windowHandle(), t.mapTo(top, point))

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='ja_split_report_audit')
        yield ready
        yield 1.0
        t = page.timeline
        yield lambda: t.waveform_state == 'READY'
        if not page.video._paused:
            QTest.mouseClick(page.play_button, Qt.LeftButton)
            yield .3
        QTest.mouseClick(page.razor_tool_button, Qt.LeftButton)
        yield .2
        check('razor tool selected', t.tool_mode == 'razor')
        undo = page.session.undo_stack
        for case in spec['cases']:
            cue = by_text(case['text'])
            check(f"case {case['text'][:6]} found", cue is not None, case['text'])
            if cue is None:
                continue
            original = st.records_of(page.project)[cue.id]['text']
            words = cue_words(page.project, cue)[0]
            t.set_visible_window(cue.start_ms - 500, cue.end_ms - cue.start_ms + 1000)
            yield .5
            point = track_point(t, cue, case['pointer_ms'])
            move_pointer(t, point)
            want = t._x_to_time(point.x())
            yield lambda: (t._razor_hover or t._razor_drag or {}).get('split_ms') == want
            QApplication.processEvents()
            shown = t._razor_resolution()
            from ..studio.timeline_razor import status_lines
            status = status_lines(shown)[0] if shown is not None else ''
            yield .2
            capture(f"hover-{cue.id}")
            before = undo.count()
            QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier, point)
            yield .8
            left, right = by_text(case['left']), by_text(case['right'])
            row = dict(text=case['text'], pointer_ms=want, preview_ms=shown.split_ms if shown else None,
                       snap=shown.snap if shown else None, status=status,
                       left=getattr(left, 'text', None), right=getattr(right, 'text', None),
                       cut_ms=getattr(left, 'end_ms', None), right_start_ms=getattr(right, 'start_ms', None),
                       words=[(cue.text[w.char_start:w.char_end], w.start_ms, w.end_ms) for w in words],
                       original_translation=original)
            check(f"{cue.id}: one undoable split into the expected texts",
                  left is not None and right is not None and undo.count() == before + 1, row)
            if left is None or right is None:
                result['cases'].append(row)
                continue
            straddled = [w for w in words if w.start_ms < want < w.end_ms]
            onset = min((w.start_ms for w in words if w.start_ms >= want), default=None)
            check(f"{cue.id}: cut moved out of the sounding word to its boundary (preview = commit)",
                  left.end_ms == right.start_ms == shown.split_ms and straddled
                  and straddled[0].end_ms <= left.end_ms <= onset and shown.snap == 'word', row)
            texts = view()
            row.update(left_translation=texts.get(left.id), right_translation=texts.get(right.id),
                       states=[st.cue_status(page.project, left), st.cue_status(page.project, right)])
            check(f"{cue.id}: both halves have a piece of the Chinese, flagged needs update",
                  texts.get(left.id) and texts.get(right.id)
                  and _content(texts[left.id] + texts[right.id]) == _content(original)
                  and row['states'] == ['needs_update', 'needs_update'], row)
            result['cases'].append(row)
            page._seek((right.start_ms + 300) / 1000.0)
            yield 1.0
            capture(f"after-{cue.id}-right-half")
            page._seek((left.start_ms + 300) / 1000.0)
            yield 1.0
            capture(f"after-{cue.id}-left-half")
        # Undo both splits, then redo them.
        t.setFocus()
        for _ in spec['cases']:
            QTest.keyClick(t, Qt.Key_Z, Qt.ControlModifier); yield .5
        restored = [by_text(case['text']) for case in spec['cases']]
        check('undo restores both sentences and their whole translations',
              all(restored) and all(view().get(c.id) == st.records_of(page.project)[c.id]['text']
                                    and st.cue_status(page.project, c) in ('done', 'manual') for c in restored),
              [(c.text, view().get(c.id)) for c in restored if c])
        for _ in spec['cases']:
            QTest.keyClick(t, Qt.Key_Y, Qt.ControlModifier); yield .5
        pairs = [(by_text(case['left']), by_text(case['right'])) for case in spec['cases']]
        check('redo brings both splits and their pieces back',
              all(a and b and view().get(a.id) and view().get(b.id) for a, b in pairs))
        # Merging the two halves of the first case back restores its translation.
        a, b = pairs[0]
        undo.push(merge_cues_command(page.project, [a.id, b.id], page.cue_controller.model_changed))
        yield .6
        merged = by_text(spec['cases'][0]['text'])
        check('merging the halves back restores the original translation (done)',
              merged is not None and view().get(merged.id) == result['cases'][0]['original_translation']
              and st.cue_status(page.project, merged) == 'done',
              dict(text=getattr(merged, 'text', None), translation=view().get(getattr(merged, 'id', ''))))
        QTest.keyClick(t, Qt.Key_S, Qt.ControlModifier)
        yield lambda: undo.isClean()
        reopened = load_project(spec['project'])
        second = spec['cases'][1]
        halves = [next((c for c in reopened.cues if c.text == second[key]), None) for key in ('left', 'right')]
        saved = (reopened.generation_metadata.get('translations') or {})
        check('save and reopen keep the second split and both pieces of its translation',
              all(halves) and all(saved.get(c.id) for c in halves),
              [(c.text, saved.get(c.id)) for c in halves if c])
        result['passed'] = all(x['passed'] for x in result['checks'])

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop(); save(); log.close()
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
                state.update(wait=value, deadline=time.monotonic() + 180)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            try:
                capture('failure')
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
