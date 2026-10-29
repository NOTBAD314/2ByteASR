"""Real-window check of "split at a text position" (2026-10-22, MFA plan step 4).

Opens a copy of a recognized Chinese project whose captions carry graded cut
positions (MFA + Qwen3 cross-check), and in the real Studio window:

1. an independent position: timeline menu "按文字位置拆分…" opens the inline
   editor, the cursor goes to the position, Ctrl+Enter splits at the
   acoustic boundary (one undo step, texts and time as planned);
2. a position inside a word: Ctrl+Enter shows the choice menu; "改在…切开"
   splits at the nearest independent position;
3. an unreliable position: the menu offers re-alignment first and an
   estimated cut last; re-alignment runs the real aligners (MFA, then Qwen3
   as the second opinion) in the background, grades the caption's positions
   into its receipt, and plans the split again;
4. undo returns every caption.
"""
from __future__ import annotations

import json
import time
import traceback


def find_targets(project):
    """One caption position per grade, each in a different caption."""
    from ..timeline.text_split import plan_text_split
    found, used = {}, set()
    for cue in sorted(project.cues, key=lambda c: c.start_ms):
        if cue.id in used or len(found) == 3:
            continue
        for position in range(1, len(cue.text)):
            plan = plan_text_split(project, cue, position)
            if plan.position != position or plan.grade in found or plan.grade == "blocked":
                continue
            if plan.grade == "whole" and not any(c.kind == "cut" for c in plan.choices):
                continue
            if plan.grade == "unreliable" and not any(c.kind == "estimate" for c in plan.choices):
                continue
            found[plan.grade] = (cue.id, position, plan)
            used.add(cue.id)
            break
    return found


def start(window, output):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
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

    def cues():
        return {c.id: (c.start_ms, c.end_ms, c.text) for c in page.project.cues}

    def press_ctrl_enter(position):
        editor = page.timeline._inline_editor
        cursor = editor.textCursor()
        cursor.setPosition(position)
        editor.setTextCursor(cursor)
        QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)

    def show_cue(cue_id):
        cue = next(c for c in page.project.cues if c.id == cue_id)
        page.select_cue(cue_id)
        page.timeline.set_visible_window(max(0, cue.start_ms - 3000), 9000)

    def menu_texts():
        menu = getattr(page, '_text_split_menu', None)
        return [a.text() for a in menu.actions() if a.text()] if menu is not None else []

    def pick(prefix):
        menu = page._text_split_menu
        action = next(a for a in menu.actions() if a.text().startswith(prefix))
        enabled = action.isEnabled()
        menu.close()
        action.trigger()
        return enabled

    def pick_timeline_action():
        menus = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible()]
        for menu in menus:
            for action in menu.actions():
                if action.text().startswith('按文字位置拆分'):
                    menu.close()
                    action.trigger()
                    result['timeline_menu_action'] = action.text()
                    # Read now: background progress (waveform) may replace the status line later.
                    result['timeline_menu_hint'] = page.save_state.text()
                    return
        if menus:
            result['timeline_menu_texts'] = [a.text() for a in menus[0].actions()]
            menus[0].close()
        else:
            QTimer.singleShot(200, pick_timeline_action)

    def steps():
        import subtitle_core
        # This isolated profile aligns with MFA (experimental), as the clip was recognized.
        subtitle_core.RUNTIME_SETTINGS.setdefault('models', {})['firered_asr_backend'] = 'mfa_aligner'
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='text_split_audit')
        yield ready
        yield 1.5
        if not page.video._paused:
            page._toggle_playback()
            yield .3
        before = cues()
        index0 = page.undo_stack.index()
        targets = find_targets(page.project)
        result['targets'] = {grade: dict(cue=cue_id, position=position, text=plan.left_text + '|' + plan.right_text,
                                         reason=plan.reason, choices=[c.kind for c in plan.choices])
                             for grade, (cue_id, position, plan) in targets.items()}
        check('the project offers an independent, a whole-word and an unreliable position',
              set(targets) == {'independent', 'whole', 'unreliable'}, result['targets'])

        # Step 5: the measured speech span under each caption, apart from its display time.
        page.timeline.set_visible_window(0, 9000)
        yield .8
        spans = [page.timeline.acoustic_span_of(c) for c in sorted(page.project.cues, key=lambda c: c.start_ms)[:4]]
        result['acoustic_spans'] = [None if s is None else [s.start_ms, s.end_ms, s.start_grade, s.end_grade] for s in spans]
        check('the timeline reads the acoustic span of the first captions', all(s is not None for s in spans),
              result['acoustic_spans'])
        _capture(window, output / '0-acoustic-lines.png')

        # 1. independent: the real timeline menu entry, then Ctrl+Enter in the inline editor.
        cue_id, position, plan = targets['independent']
        show_cue(cue_id)
        yield .5
        QTimer.singleShot(600, pick_timeline_action)
        page._show_timeline_menu(cue_id, QCursor.pos())
        yield .5
        editor = page.timeline._inline_editor
        check('timeline menu opens the caption text for a text-position split',
              editor is not None and editor.textCursor().position() == len(editor.toPlainText())
              and not editor.textCursor().hasSelection() and '按 Ctrl+Enter' in str(result.get('timeline_menu_hint')),
              dict(action=result.get('timeline_menu_action'), hint=result.get('timeline_menu_hint')))
        _capture(window, output / '1-editor-open.png')
        press_ctrl_enter(position)
        yield .8
        after = cues()
        right = next((cid for cid in after if cid not in before), None)
        split = after.get(cue_id), after.get(right)
        check('independent position: split at the acoustic boundary in one undo step',
              page.undo_stack.index() == index0 + 1 and right is not None
              and split[0][2] == plan.left_text and split[1][2] == plan.right_text
              and split[0][1] == split[1][0] and abs(split[0][1] - plan.split_ms) <= 1,
              dict(planned=plan.split_ms, left=split[0], right=split[1], status=page.save_state.text()))
        check('status names the acoustic cut', page.save_state.text().startswith('已按声学切点拆分'), page.save_state.text())
        _capture(window, output / '1-split.png')

        # 2. inside a word: the choice menu, then the nearest independent cut.
        cue_id, position, plan = targets['whole']
        show_cue(cue_id)
        yield .4
        index1 = page.undo_stack.index()
        page._open_text_split(cue_id)
        yield .3
        press_ctrl_enter(position)
        yield .5
        texts = menu_texts()
        check('inside a word: the menu explains and offers the nearest word boundary',
              texts and texts[0].startswith('这里在一个词里面') and any(t.startswith('改在') for t in texts), texts)
        menu = page._text_split_menu
        if menu is not None:
            menu.grab().save(str(output / '2-whole-menu.png'))
        choice = next(c for c in plan.choices if c.kind == 'cut')
        pick('改在')
        yield .8
        after = cues()
        check('choosing the nearest boundary splits there',
              page.undo_stack.index() == index1 + 1 and after.get(cue_id, (0, 0, ''))[2] == choice.left_text
              and abs(after[cue_id][1] - choice.split_ms) <= 1,
              dict(left=after.get(cue_id), planned=choice.split_ms))

        # 3. unreliable: re-align first (real aligners), then the split is planned again.
        cue_id, position, plan = targets['unreliable']
        show_cue(cue_id)
        yield .4
        index2 = page.undo_stack.index()
        page._open_text_split(cue_id)
        yield .3
        press_ctrl_enter(position)
        yield .5
        texts = menu_texts()
        check('unreliable position: re-alignment comes first, an estimated cut last',
              len(texts) >= 3 and texts[1].startswith('重新对齐这条字幕') and texts[-1].startswith('仍在这里切'), texts)
        menu = page._text_split_menu
        if menu is not None:
            menu.grab().save(str(output / '3-unreliable-menu.png'))
        result['realign_enabled'] = pick('重新对齐这条字幕')
        page._text_split_menu = None  # a menu shown after re-alignment is a new one
        started = time.monotonic()
        yield .5
        yield lambda: getattr(page, '_realign_signals', None) is None
        result['realign_seconds'] = round(time.monotonic() - started, 1)
        yield .8
        from ..timeline.studio_caption_timeline import KEY
        receipt = page.project.studio_state.get(KEY, {}).get('instances', {}).get(cue_id, {})
        result['realign_status'] = page.save_state.text()
        graded = receipt.get('boundaries') or []
        check('re-alignment graded the caption into its receipt (one undo step named for it)',
              graded and receipt.get('boundary_second') in ('qwen3', 'mfa')
              and page.undo_stack.text(index2) == '重新对齐字词时间',
              dict(rows=len(graded), second=receipt.get('boundary_second'), status=result['realign_status']))
        from ..timeline.text_split import plan_text_split
        cue = next((c for c in page.project.cues if c.id == cue_id), None)
        replanned = plan_text_split(page.project, cue, position) if cue is not None else None
        result['after_realign'] = dict(grade=getattr(replanned, 'grade', None), reason=getattr(replanned, 'reason', None))
        split_again = page.undo_stack.index() == index2 + 2
        menu_again = bool(getattr(page, '_text_split_menu', None)) and page._text_split_menu.isVisible()
        check('after re-alignment the split is planned again (cut, or the choices once more)',
              split_again or menu_again, dict(split=split_again, menu=menu_again, texts=menu_texts()))
        from ..recognition.cue_word_alignment import cue_words
        words, word_reason = cue_words(page.project, cue) if cue is not None else ((), 'missing')
        check('the re-aligned words are read back (and offered as cuts when the position stays unreliable)',
              len(words) > 1 and (split_again or any(t.startswith('改在') for t in menu_texts())),
              dict(words=len(words), reason=word_reason, texts=menu_texts()))
        if menu_again:
            page._text_split_menu.grab().save(str(output / '3-after-realign-menu.png'))
            page._text_split_menu.close()
        _capture(window, output / '3-after-realign.png')

        # 4. undo everything.
        while page.undo_stack.index() > index0:
            page.undo_stack.undo()
            yield .2
        check('undo returns every caption', cues() == before)
        from ..projects.timing_journal import journal_path
        journal = journal_path(page.project_path)
        rows = [json.loads(line) for line in journal.read_text('utf-8').splitlines()] if journal.is_file() else []
        actions = sorted({row['action'] for row in rows})
        result['journal'] = dict(path=str(journal), rows=len(rows), actions=actions)
        check('timing edits, undo included, were appended to the journal outside the project',
              len(rows) >= 6 and any('split' in a for a in actions) and not str(journal).startswith(str(output / 'project')),
              result['journal'])
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
                state.update(wait=value, deadline=time.monotonic() + 900)
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
