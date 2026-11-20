"""兔白's task suite: real tasks through the real chat card, scored by checks (2026-11-17, harness P3).

Agent harness work is measured with a fixed set of real tasks (evals): each change to her prompt or
tools is run against the same tasks and the success rate, rounds and seconds are compared. Here a
real MainWindow on isolated user data, the real 「问问兔白」 card and the user's own text AI; each
task is asked like a user would, then a check reads the app's state (page, dialog, setting file,
zoom, what she did). Opt-in and paid (a few cents on DeepSeek): it uses the user's key.

    python -X utf8 -m twobyteasr.acceptance.bunny_eval            # all tasks
    python -X utf8 -m twobyteasr.acceptance.bunny_eval zoom_in    # some tasks by id

The key is read from the user's store before the switch to the isolated folders and handed over in
memory only; nothing of the user's own data folder is written. Report: tmp/bunny-eval/<time>.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]


@dataclass
class Task:
    id: str
    question: str
    check: Callable                      # (window, chat) -> (passed, detail)
    level: str = 'auto'                  # 「兔白权限」 for this task
    seconds: float = 150.0
    note: str = ''
    setup: Callable | None = None        # (window) -> None, right before the question (2026-11-18)


@dataclass
class Result:
    id: str
    passed: bool
    detail: str
    seconds: float
    rounds: int
    tools: list = field(default_factory=list)
    said: list = field(default_factory=list)


# ------------------------------------------------------------------ checks
def _page(name):
    def check(window, _chat):
        from ..app.bunny_chat import current_page
        page = current_page(window)
        return page == name, f'当前页面：{page or "?"}'
    return check


def _page_soon(name, seconds: float = 12.0):
    """Like ``_page`` for a page that is built after she answered (the workbench loads lazily)."""
    def check(window, _chat):
        from PySide6.QtWidgets import QApplication
        from ..app.bunny_chat import current_page
        deadline = time.monotonic() + seconds
        while current_page(window) != name and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.05)
        page = current_page(window)
        return page == name, f'当前页面：{page or "?"}'
    return check


def _settings_section(name):
    def check(window, _chat):
        from ..app.bunny_ui_control import elements
        hits = [item for item in elements(window, want=name)
                if item.kind in ('toggle', 'tab', 'radio', 'item') and item.window != '主窗口']
        on = [item for item in hits if '勾着' in item.value or '当前' in item.value]
        return bool(on), f'设置里「{name}」：' + ('选中' if on else '没选中' if hits else '设置窗口没开')
    return check


def _autosave(seconds):
    def check(_window, _chat):
        # The isolated folder's own settings (studio_settings_path may have been resolved before the switch).
        root = Path(os.environ.get('2BYTEASR_USER_DATA_ROOT') or os.environ['LOCALAPPDATA'])
        values = []
        for path in root.rglob('settings.json'):
            try:
                data = json.loads(path.read_text('utf-8'))
            except (OSError, ValueError):
                continue
            stack = [data]
            while stack:                             # the value sits under studio_preferences
                node = stack.pop()
                if isinstance(node, dict):
                    if 'autosave_interval_seconds' in node:
                        values.append(node['autosave_interval_seconds'])
                    stack.extend(node.values())
        return seconds in values, f'autosave_interval_seconds={values or None}'
    return check


def _zoom_above(percent):
    def check(_window, _chat):
        from ..app.ui_zoom import zoom_percent
        value = zoom_percent()
        return value > percent, f'界面缩放 {value}%'
    return check


def _search_text(text):
    def check(window, _chat):
        from ..app.bunny_ui_control import elements
        boxes = [item for item in elements(window) if item.kind == 'text' and item.window != '主窗口' and text in item.value]
        return bool(boxes), '设置的搜索框：' + (boxes[0].value if boxes else '没有含「' + text + '」的')
    return check


def _used(tool, *, answer_has=''):
    def check(_window, chat):
        used = any(line.lstrip('- ').startswith(tool + '(') for line in chat.action_log)
        said = ''.join(text for who, text in chat.transcript[-4:] if who != 'user')
        ok = used and (answer_has in said if answer_has else True)
        return ok, f'用了 {tool}：{used}' + (f'；回答含「{answer_has}」：{answer_has in said}' if answer_has else '')
    return check


def _not_started(_window, chat):
    window = chat.window_
    started = bool(getattr(window, '_run_in_progress', False))
    said = ''.join(text for who, text in chat.transcript[-4:] if who != 'user')
    honest = any(word in said for word in ('素材', '选', '灰'))
    return (not started and honest), f'开始了识别：{started}；说明了原因：{honest}'


def _zoom_is(percent):
    def check(_window, _chat):
        from ..app.ui_zoom import zoom_percent
        value = zoom_percent()
        return value == percent, f'界面缩放 {value}%'
    return check


def _answer(chat) -> str:
    rows = []
    for who, text in reversed(chat.transcript):
        if who == 'user':
            break
        rows.insert(0, text)
    return '\n'.join(rows).replace('**', '').replace('==', '')


def _explains(*groups, card_rows: int = 0, handed: str = ''):
    """Her answer names one spelling of every group; ``card_rows``: a detail card of at least that many
    rows; ``handed``: these words were in what the program gave her (a lookup done before she asked)."""
    def check(_window, chat):
        said = _answer(chat)
        missing = [group for group in groups if not any(word in said for word in group)]
        cards = [text for who, text in chat.transcript if who == 'detail']
        rows = len(cards[-1].split('\n')) if cards else 0
        given = '\n'.join(str(turn.get('content')) for turn in chat._history)
        ok = not missing and rows >= card_rows and (handed in given if handed else True)
        detail = (f'缺 {missing}；' if missing else '') + f'卡片 {rows} 行，回答 {len(said)} 字'
        return ok, detail + (f'；先查好了：{handed in given}' if handed else '')
    return check


def _remember_error(_window):
    from ..app import bunny_events
    bunny_events.forget_recent()
    bunny_events.remember('跳出过一个提示框「导出失败：显卡编码器 h264_nvenc 不可用（-40）」')


TASKS = (
    Task('open_history', '帮我打开识别记录', _page('识别记录')),
    Task('open_workshop', '我想下载模型，带我去模型工坊', _page('模型工坊')),
    Task('settings_shortcuts', '打开应用设置，切到快捷键那一页', _settings_section('快捷键')),
    Task('shortcut_search', '打开快捷键设置，在搜索框里帮我搜「拆分」', _search_text('拆分'),
         note='通用操作：打开 → 快照 → 在对话框的搜索框里填字'),
    Task('autosave_5min', '帮我打开应用设置的工程与保存，把自动保存间隔改成 5 分钟，然后保存', _autosave(300),
         note='通用操作：多步、对话框里改选项再保存'),
    Task('zoom_in', '界面的字有点小，帮我整体放大一档', _zoom_above(100), note='run_command app.zoom_in 或设置'),
    Task('start_without_media', '帮我开始生成字幕', _not_started, note='没有素材：不能开始，要说明原因'),
    Task('recall_actions', '你刚才都帮我做了哪些操作？', _used('recent_actions'), level='ask', note='跨聊天的操作记录'),
    # 2026-11-18 (phases 1, 2, 5): more places, answers that carry enough, things she is handed.
    Task('zoom_reset', '把界面缩放恢复成原来的大小', _zoom_is(100), note='run_command Ctrl+0'),
    Task('open_terms', '带我去术语库', _page('术语库')),
    Task('settings_storage', '打开设置里的存储与缓存那一页', _settings_section('存储与缓存')),
    Task('settings_bunny', '打开兔白权限的设置', _settings_section('兔白权限')),
    Task('howto_card', '我第一次用，怎么从头做一份字幕？', _explains(('开始生成字幕',), ('导出',), card_rows=3),
         level='guide', note='第 1 阶段：结论加完整步骤的卡片'),
    Task('knowledge_garbled', '导出的 SRT 用记事本打开全是乱码怎么办', _explains(('UTF-8',)), level='guide',
         note='第 2 阶段：知识库'),
    Task('why_failed', '上次识别为什么失败？', _explains(('没有', '还没', '找不到'), handed='兔白查到的：最近一次识别'),
         level='ask', note='第 5 阶段：先查再答；隔离资料里没有记录，要照实说'),
    Task('recent_error', '刚才那个报错是什么意思，怎么办？', _explains(('CPU',), ('编码',)), level='guide',
         setup=_remember_error, note='第 5 阶段：最近发生的事'),
    # Last: the workbench is built after her answer, and a page that appears during the next
    # question would (rightly) make that question's context stale.
    Task('open_studio', '打开字幕工作台', _page_soon('字幕工作台')),
)


# ------------------------------------------------------------------ the run
def _prepare(settings: dict):
    """Isolated folders, the key in memory, the user's (non-secret) AI choices, a real window."""
    from ..providers import llm_config
    models = settings.get('models', {})
    key = llm_config.read_scoped_api_key(models.get('polish_provider', ''), models.get('polish_base_url', ''))
    if not key[0]:
        raise SystemExit('没有读到文字 AI 的 Key：请先在 2ByteASR 的 AI 设置里设好。')
    llm_config.read_scoped_api_key = lambda provider, base_url='': key
    llm_config.resolve_api_key = lambda stage: key
    os.environ.setdefault('TWOBYTEASR_TEST_ROOT', str(REPO / 'tmp' / 'bunny-eval' / time.strftime('root-%Y%m%d-%H%M%S')))
    from ..test_isolation import install
    install()
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path(os.environ['APPDATA']) / 'qsettings'))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import subtitle_core
    subtitle_core.RUNTIME_SETTINGS.setdefault('models', {}).update(
        {name: value for name, value in models.items() if 'key' not in name.casefold()})
    subtitle_core.RUNTIME_SETTINGS.setdefault('switches', {}).update(settings.get('switches', {}))
    from ..app import bunny_chat, ui
    from ..app.bunny_chat import NOTICE_KEY
    from ..app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{NOTICE_KEY: True}))
    bunny_chat.BunnyChat.FLOATING = False
    ui.save_runtime_settings = lambda value: None
    window = ui.MainWindow([], subtitle_core, object(), None)
    window.resize(1500, 950)
    window.show()
    from ..app import ui_zoom
    window._eval_zoom = ui_zoom.install(app, window)      # the app's entry installs it (its Ctrl+= / Ctrl+- keys)
    return app, window


def _dismiss_prompts() -> None:
    """Answer a question box (e.g. "discard unsaved changes?") the way a user leaving would: discard / no / cancel.
    Run 2 (2026-11-17) stopped for good on one: closing a settings window she had changed but not saved."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    box = QApplication.activeModalWidget()
    if not isinstance(box, QMessageBox):
        return
    for role in (QMessageBox.ButtonRole.DestructiveRole, QMessageBox.ButtonRole.NoRole, QMessageBox.ButtonRole.RejectRole):
        for button in box.buttons():
            if box.buttonRole(button) == role:
                button.click()
                return
    box.reject()


def _reset(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    for delay in (100, 400, 900, 1600):                  # a prompt opened by reject() runs its own loop
        QTimer.singleShot(delay, _dismiss_prompts)
    for top in QApplication.topLevelWidgets():
        if top is not window and top.isVisible() and hasattr(top, 'reject') and not str(top.objectName()).startswith('bunny'):
            top.reject()
    if callable(getattr(window, '_switch_page', None)):
        window._switch_page(0)


def run(tasks, settings: dict, *, out: Path | None = None) -> list[Result]:
    from PySide6.QtCore import QTimer
    app, window = _prepare(settings)
    from ..app import bunny_permissions
    from ..app.bunny_chat import open_bunny_chat
    results: list[Result] = []
    queue = list(tasks)
    state = {'finished': set()}

    def start_next():
        if not queue:
            QTimer.singleShot(200, app.quit)
            return
        task = queue.pop(0)
        _reset(window)
        bunny_permissions.save({'level': task.level, 'see_screen': False})
        chat = open_bunny_chat(window)
        chat.reveal_all()
        chat.new_conversation()
        chat.reveal_all()
        chat.action_log.clear() if task.id != 'recall_actions' else None
        if task.setup is not None:
            task.setup(window)
        state.update(task=task, chat=chat, started=time.monotonic(), sent=False)
        QTimer.singleShot(300, lambda: (chat.ask_now(task.question), state.update(sent=True)))
        QTimer.singleShot(500, poll)

        def watchdog(task=task, chat=chat):
            # Never wait forever (run 2 stopped on an unanswered box): give up on this task and go on.
            if task.id not in state['finished']:
                _dismiss_prompts()
                finish(task, chat, time.monotonic() - state['started'], False)
        QTimer.singleShot(int((task.seconds + 45) * 1000), watchdog)

    def poll():
        task, chat = state['task'], state['chat']
        elapsed = time.monotonic() - state['started']
        if chat.typer.running:
            chat.typer.finish()
        chat.reveal_all()
        done = state['sent'] and not chat.busy and not chat._pending
        if not done and elapsed < task.seconds:
            QTimer.singleShot(400, poll)
            return
        QTimer.singleShot(1200, lambda: finish(task, chat, elapsed, done))     # windows opened after her words

    def finish(task, chat, elapsed, done):
        if task.id in state['finished']:
            return                                  # the watchdog and the poll both arrived
        state['finished'].add(task.id)
        try:
            passed, detail = task.check(window, chat)
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed task, never a crash
            passed, detail = False, f'检查出错：{type(exc).__name__}: {exc}'
        if not done:
            passed, detail = False, f'超时（{task.seconds:.0f} 秒）；{detail}'
        tools = [' '.join(line.lstrip('- ').split())[:160] for line in chat.action_log]    # call and receipt
        said = [text for who, text in chat.transcript if who != 'user'][-3:]
        result = Result(task.id, passed, detail, round(elapsed, 1), int(getattr(chat, '_tool_rounds', 0)), tools, said)
        results.append(result)
        print(f'{"PASS" if passed else "FAIL"} {task.id:20s} {elapsed:5.1f}s rounds={result.rounds} {detail}', flush=True)
        print(f'     tools: {" | ".join(tool.split("：", 1)[0] for tool in tools[:8])}', flush=True)
        print(f'     said: {" / ".join(said)[:220]}', flush=True)
        start_next()

    QTimer.singleShot(1500, start_next)
    app.exec()
    passed = sum(result.passed for result in results)
    print(f'\n{passed}/{len(results)} passed; {sum(r.seconds for r in results):.0f}s; '
          f'{sum(r.rounds for r in results)} tool rounds', flush=True)
    target = out or REPO / 'tmp' / 'bunny-eval' / time.strftime('%Y%m%d-%H%M%S.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'report: {target}', flush=True)
    return results


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    user = Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / '2byteasr_settings.json'
    settings = json.loads(user.read_text(encoding='utf-8'))
    wanted = [task for task in TASKS if not argv or task.id in argv]
    results = run(wanted, settings)
    sys.stdout.flush()
    os._exit(0 if all(result.passed for result in results) else 1)


if __name__ == '__main__':
    main()
