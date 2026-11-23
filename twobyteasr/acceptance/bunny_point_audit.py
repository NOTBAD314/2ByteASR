"""Point at every control 兔白 can point at, on the real MainWindow, and check the outline lands on it (2026-11-22).

User (2026-11-22): 「基本所有按钮都要能指才好，带用户点的东西也要能是正确的而不是乱点。」

For one place (a page of the main window, or an open dialog) every target from
``bunny_pointing.visible_targets`` is checked (``verify``), outlined through the real chat card
(``BunnyChat.point_target``) and the outline's screen rectangle is compared with the control's own
(``covered``: the outline's center inside the control, the outline enclosing it). Each control is
also looked up by its own name (``locate``) to show that asking for that name finds that control
(or says it is ambiguous), never a different one. ``scripts/verify_bunny_pointing_headed.py`` runs it.
"""
from __future__ import annotations

PLACE_LIMIT = 260                # targets checked per place (a long settings page is cut here)


def _in_place(target, place: str) -> bool:
    return target.where == place


def audit_place(window, chat, place: str, *, limit: int = PLACE_LIMIT) -> dict:
    from PySide6.QtWidgets import QApplication
    from ..app import bunny_pointing
    targets = [target for target in bunny_pointing.visible_targets(window) if _in_place(target, place)]
    checked = pointed = 0
    wrong, skipped, misnamed, ambiguous, grey = [], [], [], 0, 0
    kinds: dict[str, int] = {}
    for target in targets[:limit]:
        checked += 1
        kinds[target.kind] = kinds.get(target.kind, 0) + 1
        problems, notes = bunny_pointing.verify(target)
        if problems:
            skipped.append(f'{target.describe()}：{problems[0]}')
            continue
        grey += any('灰的' in note for note in notes)
        if chat.point_target(target):
            pointed += 1
        else:
            wrong.append(f'{target.describe()}：{chat.last_point.get("detail")}')
        chat.spotlight_for(target.widget).hide()
        if target.kind != 'label' and target.label:
            dialog = place if target.widget.window() is not window else ''
            try:
                found = bunny_pointing.locate(window, {'text': target.label, 'window': dialog})
            except bunny_pointing.PointError as exc:
                if '好几个' in str(exc):
                    ambiguous += 1
                else:
                    misnamed.append(f'{target.describe()}：按名字找不到（{str(exc)[:60]}）')
                continue
            got = found.target
            if got is None or bunny_pointing._norm(got.label) != bunny_pointing._norm(target.label):
                misnamed.append(f'{target.describe()}：按名字找到的是 {got.describe() if got else "（要先打开别处）"}')
        if checked % 25 == 0:
            QApplication.processEvents()
    return {'place': place, 'targets': len(targets), 'checked': checked, 'pointed': pointed, 'wrong': wrong,
            'skipped': skipped, 'misnamed': misnamed, 'ambiguous': ambiguous, 'grey': grey, 'kinds': kinds}


def representative(window, place: str):
    """A target to leave outlined for the screenshot: a button that can be pressed, else anything."""
    from ..app import bunny_pointing
    rows = [target for target in bunny_pointing.visible_targets(window) if _in_place(target, place)]
    for wanted in ('button', 'item', 'tab', 'toggle', 'dropdown', 'checkbox'):
        for target in rows:
            if target.kind == wanted and target.widget.isEnabled() and not bunny_pointing.verify(target)[0]:
                return target
    return rows[0] if rows else None


def run_window_audit(win, output, theme):
    """Exercise the live, normally launched application on an isolated desktop."""
    import json
    import time

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QApplication
    from ..app import bunny_chat, bunny_pointing
    from ..design.theme_manager import apply_theme, save_theme_key
    from ..recognition.service import MediaResult, QueueResult, RunOptions
    from .completion_ai_repair_audit import build_task
    app = QApplication.instance()
    save_theme_key(theme)
    apply_theme(theme, app)
    checks, places, started = [], [], time.monotonic()

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    def settle(ms):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)

    def wait(predicate, seconds=25.0):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        return predicate()

    def shot(name):
        base = win.grab()
        painter = QPainter(base)
        origin = win.mapToGlobal(QPoint(0, 0))
        for top in QApplication.topLevelWidgets():
            if top is win or not top.isVisible() or top.width() < 2:
                continue
            painter.drawPixmap(top.mapToGlobal(QPoint(0, 0)) - origin, top.grab())
        painter.end()
        base.save(str(output / f'{name}.png'))

    def visit(place, key, *, label=''):
        result = audit_place(win, chat, place)
        result['label'] = label or place
        places.append(result)
        check(f'{label or place}: every checked outline lands on its control', not result['wrong'], result['wrong'][:5])
        check(f'{label or place}: asking by name finds that control', not result['misnamed'], result['misnamed'][:5])
        check(f'{label or place}: something to point at', result['pointed'] > 0, result['targets'])
        target = representative(win, place)
        if target is not None and key:
            chat.point_target(target)
            settle(450)
            shot(f'{key}-{theme}')
        return result

    win.resize(1440, 900)
    win.show()
    settle(2500)
    chat = bunny_chat.open_bunny_chat(win)
    settle(900)
    chat.reveal_all()
    check('outline floats above the window on Windows', chat.spotlight.floating)

    win._switch_page(0)
    wait(lambda: bunny_chat.current_page(win) == '首页')
    settle(800)
    visit('首页', 'home')
    visit('主窗口', '', label='顶栏和侧栏')

    _, project, report = build_task(output)
    win._last_run_options = RunOptions()
    win._handle_result(QueueResult((MediaResult(str(output / 'busy.mp4'), 'success', project_path=str(project),
                                               report_json_path=str(report), elapsed_seconds=302.0),), 302.0))
    win._switch_page(2)
    wait(lambda: bunny_chat.current_page(win) == '识别完成的结果页')
    settle(1200)
    for widget in QApplication.topLevelWidgets():
        if type(widget).__name__ == 'CompletionDialog' and widget.isVisible():
            widget.accept()
    bubble = win.result_ai_repair_bubble
    win.pages.widget(2).ensureWidgetVisible(bubble.button)
    settle(300)
    visit('识别完成的结果页', 'completion')
    go = next((t for t in bunny_pointing.visible_targets(win) if t.widget.objectName() == 'aiRepairGo'), None)
    check('completion bubble button 「交给兔白」 is a target', go is not None)
    if go is not None:
        check('completion bubble button outlined on its own rectangle', chat.point_target(go), chat.last_point.get('detail'))
        settle(450)
        shot(f'completion-bubble-{theme}')

    for opener, page, key in (('_open_model_workshop', '模型工坊', 'workshop'), ('_manage_terms', '术语库', 'terms'),
                              ('_open_recognition_history', '识别记录', 'history'),
                              ('_open_subtitle_studio', '字幕工作台', 'studio')):
        getattr(win, opener)()
        if not wait(lambda: bunny_chat.current_page(win) == page, 45):
            check(f'{page} opened', False, bunny_chat.current_page(win))
            continue
        settle(1200)
        visit(page, key)
        if page == '术语库':
            hint = bunny_pointing.hint_for(win, '术语库里添加词条的按钮在哪')
            check('qualified language resolves the visible add-term control',
                  '按钮「添加」' in hint and '现在就在屏幕上' in hint, hint)
            check('floating bunny and outline do not masquerade as dialogs',
                  '现在开着的窗口' not in hint, hint)

    win._switch_page(0)
    wait(lambda: bunny_chat.current_page(win) == '首页')
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    dialog = ApplicationSettingsDialog(win, {}, output / 'projects', browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    dialog.resize(940, 720)
    dialog.show()
    settle(600)
    title = ' '.join(dialog.windowTitle().split())
    hint = bunny_pointing.hint_for(win, '这个窗口保存的按钮在哪')
    check('guidance identifies the real open settings dialog and Save button',
          f'现在开着的窗口：「{title}」' in hint and '按钮「保存更改」' in hint, hint)
    for row in range(dialog.navigation.count()):
        section = dialog.navigation.item(row).text()
        dialog.navigation.setCurrentRow(row)
        settle(350)
        visit(title, f'settings-{row}' if row in (0, 2) else '', label=f'{title} → {section}')
    dialog.reject()
    settle(300)

    messages = []
    main_round = 0
    sub_goal = '查看操作說明'
    question = '請分工檢查操作說明並完成剩下的步驟'

    def reply_to_audit(worker):
        nonlocal main_round
        request = worker._messages
        messages.append(json.dumps(request, ensure_ascii=False))
        if any('【子任务】' in str(row.get('content')) for row in request if row.get('role') == 'user'):
            tools, line = [], '已核對操作說明'
        else:
            main_round += 1
            tools, line = [], '檢查完成'
            if main_round == 1:
                tools = [
                    {'name': 'start_task', 'args': {'goal': question, 'steps': ['看說明', '核對', '回報']}},
                    {'name': 'run_subtask', 'args': {'goal': sub_goal}},
                ]
                line = '我先分一個子任務'
            elif main_round < 10:
                tools = [{'name': 'tool_help', 'args': {'names': ['look']}}]
                line = '繼續核對'
        worker.answered.emit(json.dumps({'lines': [line], 'tools': tools, 'mood': 'happy'}, ensure_ascii=False))

    original_worker = bunny_chat.BunnyChatWorker.run
    original_ready = chat.ready
    try:
        bunny_chat.BunnyChatWorker.run = reply_to_audit
        chat.ready = True
        chat.set_mode('thread', persist=False)
        chat.input.setText(question)
        chat.send()
        finished = wait(lambda: not chat.busy, 30)
        sub_requests = [request for request in messages if '【子任务】这是兔白自己' in request]
        check('scripted task finishes', finished and main_round == 10, main_round)
        check('subtask gets its own goal and sends a receipt',
              len(sub_requests) == 1 and sub_goal in sub_requests[0] and '我先分一個子任務' not in sub_requests[0]
              and any('run_subtask(goal=' + sub_goal + ')：完成' in request for request in messages))
        check('long task retains original request while consolidating old rounds',
              chat.last_summary > 0 and any(question in request and '【任务进度摘要】（较早的' in request for request in messages),
              chat.last_summary)
        chat.reveal_all()
        shot(f'long-task-{theme}')
    finally:
        chat.ready = original_ready
        bunny_chat.BunnyChatWorker.run = original_worker

    total = {key: sum(place[key] if isinstance(place[key], int) else len(place[key]) for place in places)
             for key in ('targets', 'checked', 'pointed', 'wrong', 'skipped', 'misnamed', 'ambiguous', 'grey')}
    result = dict(passed=all(item['passed'] for item in checks), theme=theme, checks=checks, total=total,
                  places=places, seconds=round(time.monotonic() - started, 1),
                  dpr=app.primaryScreen().devicePixelRatio())
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    chat.close_chat()
    win.close()
    return result


def start(window, output):
    import json
    import os
    import traceback
    from PySide6.QtWidgets import QApplication
    from .studio_acceptance_audit import require

    app = QApplication.instance()
    try:
        require(os.environ.get('TWOBYTEASR_TEST_ROOT') == str(output),
                'Pointing verification requires its own test profile')
        run_window_audit(window, output, os.environ.get('TWOBYTEASR_POINT_AUDIT_THEME', 'sand'))
    except Exception:
        (output / 'result.json').write_text(json.dumps({'passed': False, 'error': traceback.format_exc()}), 'utf8')
    finally:
        app.quit()


__all__ = ['audit_place', 'representative']
