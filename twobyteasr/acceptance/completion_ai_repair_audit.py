"""Real window: 兔白处理 bubble and window on the completion page (2026-11-21, 乙1).

A generated isolated task goes through the production completion handler. The
audit runs the two local kinds, then runs rejected-suggestion review with a
fixed provider response. It clicks through undo and restore and checks the
original bytes. Light and dark captures. No network provider is called.
"""
import hashlib
import json
import os
import time
import traceback
from pathlib import Path


def build_task(output):
    from .completion_todo_audit import build_tasks
    from ..projects.studio_project import load_project, save_project
    from ..recognition import speech_coverage as coverage
    busy, _quiet = build_tasks(output)
    project = load_project(busy[1])
    state = coverage.make_state([dict(start=60, end=62), dict(start=80, end=83)], [], duration=110)
    project.generation_metadata[coverage.KEY] = state
    save_project(project, busy[1])
    # 2026-11-22: one refused AI suggestion, so the 保护规则拒绝 card shows.
    report = json.loads(Path(busy[2]).read_text(encoding='utf-8'))
    report.setdefault('events', []).append(dict(event='terminology_polish_final', cue_id=8, details=dict(rejected_edits=[
        {'from': '输出', 'to': '输入', 'start': 4, 'end': 6, 'rule_id': 'local_difference_without_two_sources'}])))
    Path(busy[2]).write_text(json.dumps(report, ensure_ascii=False), 'utf-8')
    return busy


def start(window, output):
    from PySide6.QtCore import QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..app import completion_ai_repair as repair
    from ..design import theme_manager
    from ..i18n import current_language, tr
    from ..i18n_widgets import refresh_application
    from ..projects.save_changes_dialog import SaveChangesDialog
    from ..projects.studio_project import load_project
    from ..recognition.service import MediaResult, QueueResult, RunOptions
    from ..test_isolation import require_isolated_paths
    require_isolated_paths('completion-ai-repair')
    scratch = str(output / 'qsettings.ini').replace('\\', '/')
    theme_manager._settings = lambda: QSettings(scratch, QSettings.Format.IniFormat)
    result = dict(checks=[], shots=[], passed=False)
    project_path = output / 'busy.2byteproj'
    report_path = output / 'busy.json'

    def write():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        write()
        if not ok:
            shot('failure')
            raise AssertionError(name)

    def shot(name, widget=None):
        target = output / f'{name}.png'
        _capture(widget or window, target)
        result['shots'].append(str(target))

    def close_notices():
        for widget in QApplication.topLevelWidgets():
            if type(widget).__name__ == 'CompletionDialog' and widget.isVisible():
                widget.accept()

    def settle():
        for _ in range(40):
            yield .1
            if any(type(w).__name__ == 'CompletionDialog' and w.isVisible() for w in QApplication.topLevelWidgets()):
                close_notices()
                yield .8
                return
        yield .3

    def show():
        window._last_run_options = RunOptions()
        window._handle_result(QueueResult((MediaResult(str(output / 'busy.mp4'), 'success', project_path=str(project_path),
                                                       report_json_path=str(report_path), elapsed_seconds=302.0),), 302.0))
        window._switch_page(2)
        window.pages.widget(2).verticalScrollBar().setValue(0)

    def review_count():
        tasks = window._completion_tasks
        evidence = window._completion_task_evidence[window._completion_task_key(tasks[0][0])]
        current = (evidence.get('display_payload') or {}).get('_current_review') or {}
        return len(current.get('items') or ())

    def stub_rejected_reply(system, payload, **kwargs):
        if system != repair.REJECTED_SYSTEM:
            raise AssertionError('Unexpected provider request in completion audit')
        return json.dumps({'results': [{'id': row['id'], 'decision': 'keep'}
                                       for row in payload['items']]})

    def flow():
        window.showNormal()
        window.resize(1460, 980)
        yield .5
        theme_manager.apply_theme('warm')
        prompt = SaveChangesDialog(window, '关闭', 'Audit copy')
        prompt.show()
        yield .4
        language = current_language()
        refresh_application('en' if language != 'en' else 'zh')
        refresh_application(language)
        check('save prompt survives live language refresh', prompt.isVisible() and bool(prompt.informativeText()))
        shot('save-language-refresh', prompt)
        QTest.mouseClick(prompt.cancel_button, Qt.MouseButton.LeftButton)
        check('save prompt can still cancel', prompt.choice == 'cancel' and prompt.isHidden())
        prompt.deleteLater()
        show()
        yield from settle()
        controller = window._ai_repair
        bubble = window.result_ai_repair_bubble
        check('bubble visible with fixable items', bubble.isVisible() and controller.plan is not None
              and controller.plan.fixable > 0, dict(fixable=getattr(controller.plan, 'fixable', None),
                                                    kinds=[(c.key, c.count, c.blocked) for c in controller.plan.categories]))
        card = window.result_summary_card
        check('bubble sits inside the result card', card.rect().contains(bubble.geometry())
              or card.geometry().contains(bubble.mapTo(card.parentWidget(), bubble.rect().topLeft())))
        check('page has no horizontal overflow', window.pages.widget(2).horizontalScrollBar().maximum() == 0)
        shot('warm-page')
        original = project_path.read_bytes()
        before_items = review_count()
        QTest.mouseClick(bubble.button, Qt.MouseButton.LeftButton)
        yield .6
        dialog = controller.dialog
        check('window opens in choose state', dialog is not None and dialog.isVisible() and controller.state == 'idle')
        check('three summary tiles visible', len(dialog.tiles) == 3 and all(tile.isVisible() for tile in dialog.tiles))
        check('category chips start collapsed', dialog.adjust_button.isVisible() and dialog.chips_host.isHidden())
        check('unavailable AI review cannot be selected', 'rejected' not in dialog.cards, sorted(dialog.cards))
        shot('warm-choose', dialog)
        QTest.mouseClick(dialog.adjust_button, Qt.MouseButton.LeftButton)
        yield .2
        check('disclosure exposes category choices', dialog.chips_host.isVisible()
              and all(chip.isVisible() for chip in dialog.cards.values()))
        shot('warm-categories', dialog)
        for key, card_widget in list(dialog.cards.items()):
            category = controller.plan.category(key)
            if category.automatic and key not in {'short', 'fast'}:
                QTest.mouseClick(card_widget, Qt.MouseButton.LeftButton)
                yield .05
        check('only local kinds chosen', dialog.chosen == {'short', 'fast'} & {c.key for c in controller.plan.categories},
              sorted(dialog.chosen))
        estimate = controller.plan.estimate(dialog.chosen)
        check('local kinds cost nothing', '不花钱' in estimate.cost_text() and estimate.audio_seconds == 0
              and estimate.cost_text() in (dialog.title.text() + dialog.subtitle.text()), dialog.title.text())
        shot('warm-local-only', dialog)
        QTest.mouseClick(dialog.primary, Qt.MouseButton.LeftButton)
        for _ in range(150):
            yield .2
            if controller.state != 'running':
                break
        check('run finished and saved', controller.state == 'done' and controller.record is not None,
              dict(state=controller.state, message=controller.message))
        yield .4
        after_items = review_count()
        check('page review count went down', after_items < before_items, dict(before=before_items, after=after_items))
        check('file changed', project_path.read_bytes() != original)
        check('results expose their categories', bool(dialog.result_chips)
              and all(chip.isVisible() for chip in dialog.result_chips.values()))
        check('unselected work is labeled pending', 'speech' not in controller.selected
              and controller.result.categories['speech'].left > 0
              and dialog.tiles[1].label.text() == tr('待处理'))
        shot('warm-done', dialog)
        shot('warm-page-done')
        undo = next((button for button in dialog.detail_rows.findChildren(type(dialog.primary))
                     if button.objectName() == 'aiRepairUndo'), None)
        check('a change can be undone', undo is not None)
        undone_before = sum(bool(row.get('undone')) for row in controller.record['changes'])
        QTest.mouseClick(undo, Qt.MouseButton.LeftButton)
        yield .5
        undone_after = sum(bool(row.get('undone')) for row in controller.record['changes'])
        check('one change undone', undone_after == undone_before + 1, dict(before=undone_before, after=undone_after))
        theme_manager.apply_theme('grape')
        yield .5
        dialog.refresh_theme_palette()
        bubble.refresh_theme_palette()
        yield .3
        shot('grape-done', dialog)
        shot('grape-page-done')
        QTest.mouseClick(dialog.secondary, Qt.MouseButton.LeftButton)
        yield .6
        check('restore gives back the exact original bytes',
              hashlib.sha256(project_path.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest())
        check('page count back after restore', review_count() == before_items, dict(now=review_count(), before=before_items))
        shot('grape-page-restored')

        repair.text_ai_ready = lambda *_args: True
        repair._default_ask = stub_rejected_reply
        window._select_completion_task(0)
        yield .5
        check('one rejected suggestion starts pending', window.result_todo._rejected == 1)
        QTest.mouseClick(bubble.button, Qt.MouseButton.LeftButton)
        yield .6
        dialog = controller.dialog
        check('available AI review has a category chip', 'rejected' in dialog.cards, sorted(dialog.cards))
        if dialog.chips_host.isHidden():
            QTest.mouseClick(dialog.adjust_button, Qt.MouseButton.LeftButton)
            yield .2
        for key, card_widget in dialog.cards.items():
            if (key in dialog.chosen) != (key == 'rejected'):
                QTest.mouseClick(card_widget, Qt.MouseButton.LeftButton)
                yield .05
        check('only rejected suggestions chosen', dialog.chosen == {'rejected'}, sorted(dialog.chosen))
        QTest.mouseClick(dialog.primary, Qt.MouseButton.LeftButton)
        for _ in range(100):
            yield .1
            if controller.state != 'running':
                break
        check('rejected review completes, saves and clears pending count',
              controller.state == 'done' and controller.result.requests == 1
              and controller.result.categories['rejected'].fixed == 1
              and window.result_todo._rejected == 0, controller.message)
        check('keep decision preserves caption text',
              next(cue.text for cue in load_project(project_path).cues if cue.id == 'c8') == '这里要注意输出色彩空间')
        shot('grape-rejected-result', dialog)
        undo = next(button for button in dialog.detail_rows.findChildren(type(dialog.primary))
                    if button.objectName() == 'aiRepairUndo')
        QTest.mouseClick(undo, Qt.MouseButton.LeftButton)
        yield .5
        check('undo restores pending rejected count', window.result_todo._rejected == 1)
        QTest.mouseClick(dialog.secondary, Qt.MouseButton.LeftButton)
        yield .5
        check('rejected review restore preserves the original project bytes', project_path.read_bytes() == original)
        result['passed'] = True
        window.close()

    steps = flow()
    state = dict(until=0., ticking=False)
    timer = QTimer(window)
    timer.setInterval(20)

    def tick():
        if state['ticking'] or time.monotonic() < state['until']:
            return
        state['ticking'] = True
        try:
            state['until'] = time.monotonic() + next(steps)
        except StopIteration:
            timer.stop(); write(); QApplication.instance().quit()
        except BaseException:
            result['error'] = traceback.format_exc()
            timer.stop(); write(); QApplication.instance().quit()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        write()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
