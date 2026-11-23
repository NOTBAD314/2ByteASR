"""兔白 2026-11-22: long tasks fold into a progress note, subtasks run in clean contexts, and she points at
any control from the live widget tree, checked before anything is outlined."""
from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

AUTO = {'level': 'auto', 'read_subtitles': True, 'read_diagnostics': True, 'remember': True, 'allow_paid': False,
        'keep_chat': True, 'see_screen': False, 'folders': [], 'files_anywhere': False}


@pytest.fixture(autouse=True)
def no_saved_chats():
    from twobyteasr.app import bunny_bond, bunny_memory
    bunny_memory.clear_chats()
    bunny_bond.clear()
    yield
    bunny_memory.clear_chats()


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def level(monkeypatch):
    from twobyteasr.app import bunny_permissions
    state = {'level': 'auto'}
    monkeypatch.setattr(bunny_permissions, 'load', lambda: dict(AUTO, level=state['level']))
    return state


def _until(app, condition, seconds=6.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


# ------------------------------------------------------------------ long-task summary
def _round(index, tool='ui_snapshot', ok=True):
    reply = {'lines': [f'第 {index} 步'], 'tools': [{'name': tool, 'args': {'text': f'按钮{index}'}}],
             'steps': ['打开设置', '改间隔', '保存', '确认'], 'step_now': min(index, 3)}
    outcome = '成功。能操作的控件：' + '很长的结果' * 400 if ok else '没做成。屏幕上没有这个控件'
    return [{'role': 'assistant', 'content': json.dumps(reply, ensure_ascii=False)},
            {'role': 'user', 'content': f'【兔白操作结果】\n- {tool}(text=按钮{index})：{outcome}\n\n【现在的软件状态】\n首页'}]


def test_a_long_task_folds_older_rounds_into_a_note_and_keeps_the_users_words():
    from twobyteasr.app import bunny_context
    question = {'role': 'user', 'content': '世界书……\n\n【小兔纸说】\n帮我把自动保存改成 5 分钟然后保存'}
    messages = [{'role': 'system', 'content': '人设'}, {'role': 'user', 'content': '早'},
                {'role': 'assistant', 'content': '{"lines": ["早"]}'}, question]
    for index in range(1, 10):
        messages += _round(index, ok=index != 4)
    folded, count = bunny_context.summarize(messages, 3)
    assert count == 9 - bunny_context.KEEP_ROUNDS
    note = folded[3]['content']
    assert note.startswith(question['content'])                         # the original words go whole
    assert bunny_context.SUMMARY_MARK in note and '1. ui_snapshot(text=按钮1)：成功' in note
    assert '没做成 1 步' in note and '还要做：确认' in note
    assert [row['role'] for row in folded[4:]] == ['assistant', 'user'] * bunny_context.KEEP_ROUNDS
    assert folded[-1] == messages[-1]                                   # the newest round goes whole
    sent, _ = bunny_context.prepare(messages, 3)
    assert bunny_context.size(sent) <= bunny_context.REQUEST_CHARS
    assert sent[0]['content'] == '人设' and question['content'] in str(sent[3]['content'])


def test_a_short_question_is_sent_as_it_is():
    from twobyteasr.app import bunny_context
    messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'q'}, *_round(1)]
    assert bunny_context.summarize(messages, 1) == (messages, 0)


def test_one_request_stays_bounded_even_with_long_history():
    from twobyteasr.app import bunny_context
    history = []
    for _ in range(30):
        history += [{'role': 'user', 'content': '旧问题' * 800}, {'role': 'assistant', 'content': '旧回答' * 800}]
    messages = [{'role': 'system', 'content': '人设'}, *history, {'role': 'user', 'content': '新问题'}]
    start = len(messages) - 1
    for index in range(1, 4):
        messages += _round(index)
    sent, _ = bunny_context.prepare(messages, start)
    assert bunny_context.size(sent) <= bunny_context.REQUEST_CHARS
    assert sent[0]['content'] == '人设' and any(row.get('content') == '新问题' for row in sent)


# ------------------------------------------------------------------ subtasks: the pieces
def test_a_subtask_call_is_capped_and_its_result_is_one_short_line():
    from twobyteasr.app import bunny_context, bunny_subtasks
    from twobyteasr.app.bunny_tools import ToolError
    sub = bunny_subtasks.from_call({'goal': '体检原神词库', 'max_rounds': 99}, 1, 2)
    assert sub.max_rounds == bunny_subtasks.ROUNDS_CAP and sub.over() == ''
    with pytest.raises(ToolError):
        bunny_subtasks.from_call({'goal': ' '}, 1, 1)
    sub.sent_chars = bunny_subtasks.CHAR_BUDGET
    assert '费用上限' in sub.over()
    sub.sent_chars, sub.rounds, sub.requests, sub.final = 0, 2, 3, '找到 3 个重复词条'
    rounds = bunny_context.split_rounds([*_round(1), *_round(2, ok=False)])
    line = bunny_subtasks.result_line(sub, rounds)
    assert line.startswith('- run_subtask(goal=体检原神词库)：完成') and '没做成 1' in line and '找到 3 个重复词条' in line
    assert len(line) <= bunny_subtasks.RESULT_CHARS
    assert '子任务 1/2' in sub.status()


# ------------------------------------------------------------------ the chat
@pytest.fixture
def chat_env(app, monkeypatch, level):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    window = QWidget()
    window.resize(1100, 720)
    window.model_workshop_button = QPushButton('模型工坊', window)
    window.model_workshop_button.setGeometry(900, 10, 90, 28)
    window.save_button = QPushButton('保存设置', window)
    window.save_button.setGeometry(40, 300, 120, 32)
    window.grey_button = QPushButton('开始生成字幕', window)
    window.grey_button.setGeometry(40, 360, 140, 32)
    window.grey_button.setEnabled(False)
    window.grey_button.setToolTip('先选择素材')
    window.show()
    app.processEvents()
    yield bunny_chat, window
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    window.close()
    window.deleteLater()
    app.processEvents()


def _answer(**data):
    data.setdefault('lines', ['好'])
    data.setdefault('mood', 'happy')
    data.setdefault('suggest', ['好的', '再说说'])
    return json.dumps(data, ensure_ascii=False)


def _all_text(messages) -> str:
    return json.dumps(messages, ensure_ascii=False)


def test_subtasks_run_in_clean_contexts_and_report_back_in_one_line_each(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    sent = []

    def fake_run(worker):
        text = _all_text(worker._messages)
        sent.append(worker._messages)
        if '【子任务】' in text:
            if '体检词库A' in text:
                done = '【兔白操作结果' in worker._messages[-1]['content']
                worker.answered.emit(_answer(lines=['A：查到 2 个重复'], tools=[]) if done else
                                     _answer(lines=['先看看'], tools=[{'name': 'tool_help', 'args': {'names': ['look']}}]))
            else:
                worker.answered.emit(_answer(lines=['B：没有问题'], tools=[]))
        elif 'run_subtask(goal=体检词库A)' in text:
            worker.answered.emit(_answer(lines=['两个词库都看完啦']))
        elif '体检一下' not in worker._messages[-1]['content']:
            worker.answered.emit(_answer(lines=['不客气']))
        else:
            worker.answered.emit(_answer(lines=['兔白分两块做'], tools=[
                {'name': 'run_subtask', 'args': {'goal': '体检词库A', 'max_rounds': 3}},
                {'name': 'run_subtask', 'args': {'goal': '体检词库B'}}]))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    chat = bunny_chat.open_bunny_chat(window)
    chat.set_mode('thread', persist=False)
    chat.input.setText('谢谢兔白')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.input.setText('帮我把两个词库都体检一下')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    subtask_requests = [m for m in sent if '【子任务】' in _all_text(m)]
    assert len(subtask_requests) == 3                                       # A twice, B once
    for messages in subtask_requests:                                       # clean: no chat history, no main rounds
        assert '谢谢兔白' not in _all_text(messages) and '兔白分两块做' not in _all_text(messages)
        assert '帮我把两个词库都体检一下' in messages[-1]['content'] or '帮我把两个词库都体检一下' in _all_text(messages)
    final = _all_text(sent[-1])
    assert 'run_subtask(goal=体检词库A)：完成' in final and 'A：查到 2 个重复' in final
    assert 'run_subtask(goal=体检词库B)：完成' in final and 'B：没有问题' in final
    assert not any('【子任务】' in _all_text([row]) for row in chat._history)   # her saved chat keeps no subtask rounds
    assert any('子任务「体检词库A」' in str(who_text) for who_text in chat.transcript) or chat.mode == 'thread'
    assert sum('run_subtask' in line for line in chat.action_log) == 2


def test_a_subtask_stops_at_its_rounds_and_cannot_start_another(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    sent = []

    def fake_run(worker):
        text = _all_text(worker._messages)
        sent.append(text)
        if '【子任务】' in text:
            worker.answered.emit(_answer(lines=['还要再查'], tools=[
                {'name': 'tool_help', 'args': {'names': ['look']}},
                {'name': 'run_subtask', 'args': {'goal': '套娃'}}]))
        elif 'run_subtask(goal=没完没了)' in text:
            worker.answered.emit(_answer(lines=['子任务没做完，兔白照实说']))
        else:
            worker.answered.emit(_answer(tools=[{'name': 'run_subtask', 'args': {'goal': '没完没了', 'max_rounds': 2}}]))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('做一件大事')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    assert sum('【子任务】' in text for text in sent) == 3                      # 2 rounds, then the last word
    assert '子任务里不能再分子任务' in sent[-2]
    assert '没做完（停在轮数上限（2 轮））' in sent[-1]


def test_cancel_stops_a_running_subtask(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env

    def fake_run(worker):
        if '【子任务】' in _all_text(worker._messages):
            return                                                          # the subtask's request never returns
        worker.answered.emit(_answer(tools=[{'name': 'run_subtask', 'args': {'goal': '慢慢查'}},
                                            {'name': 'run_subtask', 'args': {'goal': '再查一个'}}]))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('做一件大事')
    chat.send()
    assert _until(app, lambda: chat._sub is not None)
    assert '子任务 1/2「慢慢查」' in chat._sub_status
    chat._cancel_reply()
    assert not chat.busy and chat._sub is None and chat._sub_queue == []
    assert any('已取消' in line for line in chat.action_log)


def test_a_long_task_in_the_chat_sends_a_progress_note_instead_of_every_round(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    sizes, last = [], {}

    def fake_run(worker):
        sizes.append(sum(len(str(m.get('content'))) for m in worker._messages))
        last['messages'] = worker._messages
        rounds = sum(1 for m in worker._messages if '【兔白操作结果' in str(m.get('content')))
        done = bunny_chat.bunny_persona.TOOL_TAG in str(worker._messages[-1].get('content')) and len(sizes) >= 12
        tools = [] if done else [{'name': 'start_task', 'args': {'goal': '长任务', 'steps': ['一', '二', '三']}}
                                 if len(sizes) == 1 else {'name': 'tool_help', 'args': {'names': ['look', 'ui_snapshot']}}]
        worker.answered.emit(_answer(lines=[f'第 {len(sizes)} 轮'], tools=tools, steps=['一', '二', '三'],
                                     step_now=min(2, rounds // 4)))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('帮我做一件要很多步的事')
    chat.send()
    assert _until(app, lambda: not chat.busy, 15)
    assert len(sizes) >= 12 and chat.last_summary > 0
    question = next(m for m in last['messages'] if '帮我做一件要很多步的事' in str(m.get('content')))
    assert '【任务进度摘要】' in question['content'] and '目标：长任务' in question['content']
    after = last['messages'][last['messages'].index(question) + 1:]
    assert len(after) <= 2 * 3 + 1
    assert max(sizes[8:]) < sizes[7] * 2                                   # the requests stop growing round by round


# ------------------------------------------------------------------ pointing
def test_point_at_checks_the_control_and_the_answer_outlines_it(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from twobyteasr.app import bunny_pointing
    from twobyteasr.app.bunny_tools import ToolError, TOOLS
    receipt = TOOLS['point_at'].run(window, {'text': '保存设置按钮'})
    assert '指好了：按钮「保存设置」' in receipt
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: worker.answered.emit(_answer(lines=['在这里'])))
    chat = bunny_chat.open_bunny_chat(window)
    window._bunny_point = None
    TOOLS['point_at'].run(window, {'text': '保存设置'})
    chat.input.setText('保存在哪')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    assert chat.last_point['ok'] and chat.last_point['widget'] is window.save_button
    assert chat.spotlight.isVisible()
    ok, detail = bunny_pointing.covered(chat.spotlight.global_target(),
                                        bunny_pointing.Target(window.save_button, 'button', '保存设置'))
    assert ok, detail
    grey = TOOLS['point_at'].run(window, {'text': '开始生成字幕'})
    assert '灰的' in grey and '先选择素材' in grey
    with pytest.raises(ToolError) as missing:
        TOOLS['point_at'].run(window, {'text': '保存全部设置吧'})
    assert '最像的是' in str(missing.value) and '保存设置' in str(missing.value)
    with pytest.raises(ToolError) as nothing:
        TOOLS['point_at'].run(window, {'text': '一键发布到抖音'})
    assert '没有找到' in str(nothing.value) and '不要指别的地方' in str(nothing.value)


def test_a_point_to_that_does_not_exist_is_said_and_nothing_is_outlined(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: worker.answered.emit(
        _answer(lines=['看这里！'], point_to='一键发布到抖音')))
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('发布按钮在哪')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert not chat.spotlight.isVisible() and chat.last_point['ok'] is False
    assert any('兔白没有指' in line for line in chat.last_reply_html())


def test_controls_in_dialogs_tabs_and_list_rows_are_outlined_on_their_own_rectangles(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from PySide6.QtWidgets import QDialog, QListWidget, QPushButton, QTabWidget, QVBoxLayout, QWidget
    from twobyteasr.app import bunny_pointing
    dialog = QDialog(window)
    dialog.setWindowTitle('应用设置')
    layout = QVBoxLayout(dialog)
    nav = QListWidget()
    nav.addItems(['外观', '工程与保存', '快捷键', '兔白权限'])
    tabs = QTabWidget()
    tabs.addTab(QWidget(), '常规')
    tabs.addTab(QWidget(), '字幕样式')
    save = QPushButton('保存更改')
    for widget in (nav, tabs, save):
        layout.addWidget(widget)
    dialog.resize(600, 500)
    dialog.show()
    app.processEvents()
    answers = iter(['保存更改', '兔白权限', '字幕样式'])
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: worker.answered.emit(
        _answer(lines=['这里'], point_to=next(answers))))
    chat = bunny_chat.open_bunny_chat(window)
    try:
        for expected, kind in (('保存更改', 'button'), ('兔白权限', 'item'), ('字幕样式', 'tab')):
            chat.input.setText(f'{expected}在哪')
            chat.send()
            assert _until(app, lambda: not chat.busy)
            point = chat.last_point
            assert point['ok'] and point['label'] == expected and point['kind'] == kind, point
            spot = chat.spotlight_for(point['widget'])
            assert spot is not chat.spotlight and spot.isVisible()
            target = bunny_pointing.Target(point['widget'], kind, expected, index=point['index'])
            ok, detail = bunny_pointing.covered(spot.global_target(), target)
            assert ok, detail
            whole = bunny_pointing.global_rect(bunny_pointing.Target(point['widget'], 'button', ''))
            if kind != 'button':                                          # a row or a tab, not the whole bar
                assert spot.global_target().width() * spot.global_target().height() < whole.width() * whole.height()
    finally:
        dialog.close()


def test_a_control_renamed_since_the_snapshot_is_not_pointed_at(app, chat_env):
    bunny_chat, window = chat_env
    from twobyteasr.app import bunny_pointing
    from twobyteasr.app.bunny_tools import TOOLS
    listing = TOOLS['ui_snapshot'].run(window, {'text': '保存设置'})
    ref = next(row.split()[0] for row in listing.splitlines() if '保存设置' in row)
    found = bunny_pointing.locate(window, {'ref': ref})
    window.save_button.setText('删除全部')
    problems, _notes = bunny_pointing.verify(found.target)
    assert problems and '现在叫「删除全部」' in problems[0]
    window.save_button.hide()
    problems, _notes = bunny_pointing.verify(found.target)
    assert problems and '不在屏幕上' in problems[0]


def _paged_window(app):
    from PySide6.QtWidgets import QPushButton, QStackedWidget, QVBoxLayout, QWidget
    window = QWidget()
    window.resize(900, 600)
    layout = QVBoxLayout(window)
    window.pages = QStackedWidget()
    layout.addWidget(window.pages)
    window.settings_scroll = QWidget()
    QPushButton('开始生成字幕', window.settings_scroll)
    workshop = QWidget()
    QVBoxLayout(workshop).addWidget(QPushButton('下载 FireRed 模型'))
    for page in (window.settings_scroll, QWidget(), QWidget(), workshop):
        window.pages.addWidget(page)
    window._workshop_page_instance = workshop
    window.term_library_page = QWidget()
    QVBoxLayout(window.term_library_page).addWidget(QPushButton('添加'))
    window.pages.addWidget(window.term_library_page)
    window.built_page = lambda name: getattr(window, f'_{name}_page_instance', None)
    window._open_model_workshop = lambda: window.pages.setCurrentWidget(workshop)
    window._return_to_settings = lambda: window.pages.setCurrentIndex(0)
    window.show()
    app.processEvents()
    return window, workshop


def test_a_control_on_another_page_is_reached_first_except_when_she_only_guides(app, level):
    from twobyteasr.app import bunny_pointing
    from twobyteasr.app.bunny_tools import ToolError, TOOLS
    window, workshop = _paged_window(app)
    try:
        level['level'] = 'guide'
        with pytest.raises(ToolError) as guided:
            TOOLS['point_at'].run(window, {'text': '下载 FireRed 模型'})
        assert 'offer_open=model_workshop' in str(guided.value) and window.pages.currentIndex() == 0
        level['level'] = 'ask'
        receipt = TOOLS['point_at'].run(window, {'text': '下载 FireRed 模型'})
        assert '先切到「模型工坊」页' in receipt and window.pages.currentWidget() is workshop
        asked = bunny_pointing.take(window)
        target, problems, _notes = bunny_pointing.resolve_request(window, asked)
        assert target is not None and not problems and target.label == '下载 FireRed 模型'
    finally:
        window.close()
        window.deleteLater()


def test_a_settings_section_is_opened_then_pointed_at(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from PySide6.QtWidgets import QDialog, QListWidget, QVBoxLayout
    from twobyteasr.app.bunny_tools import TOOLS
    opened = []

    def open_settings(initial_section=''):
        dialog = QDialog(window)
        dialog.setWindowTitle('应用设置')
        nav = QListWidget()
        nav.addItems(['外观', '工程与保存', '快捷键'])
        QVBoxLayout(dialog).addWidget(nav)
        dialog.resize(500, 400)
        dialog.show()
        opened.append((initial_section, dialog))
    window._open_application_settings = open_settings
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: worker.answered.emit(_answer(lines=['打开啦'])))
    chat = bunny_chat.open_bunny_chat(window)
    receipt = TOOLS['point_at'].run(window, {'text': '快捷键'})
    assert '应用设置 → 快捷键' in receipt and '现在帮小兔纸打开' in receipt
    chat.input.setText('快捷键在哪改')
    chat.send()
    assert _until(app, lambda: (getattr(chat, 'last_point', None) or {}).get('label') == '快捷键')
    assert opened and opened[0][0] == '快捷键' and chat.last_point['ok'] and chat.last_point['kind'] == 'item'
    opened[0][1].close()


def test_a_where_is_question_carries_what_the_screen_has(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from twobyteasr.app.bunny_pointing import hint_for
    assert '按钮「保存设置」' in hint_for(window, '「保存设置」在哪？') and '现在就在屏幕上' in hint_for(window, '「保存设置」在哪？')
    assert '没有找到「一键发布」' in hint_for(window, '「一键发布」在哪里')
    assert hint_for(window, '今天好累啊') == ''
    assert '没有找到' not in hint_for(window, '这个窗口保存的按钮在哪')    # a guessed name never claims "not there"
    assert '保存设置' in hint_for(window, '保存设置按钮在哪')
    sent = []
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: (sent.append(worker._messages),
                                                                          worker.answered.emit(_answer())))
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('「保存设置」在哪？')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    assert '【兔白先在屏幕上找了一下】' in sent[0][-1]['content']
    assert all('兔白先在屏幕上找了一下' not in str(row.get('content')) for row in chat._history)


def test_a_page_that_comes_up_late_is_waited_for_before_pointing(app, level):
    from PySide6.QtCore import QTimer
    from twobyteasr.app.bunny_tools import TOOLS
    window, workshop = _paged_window(app)
    window._open_model_workshop = lambda: QTimer.singleShot(400, lambda: window.pages.setCurrentWidget(workshop))
    try:
        receipt = TOOLS['point_at'].run(window, {'text': '下载 FireRed 模型'})
        assert '先切到「模型工坊」页，指好了' in receipt and window.pages.currentWidget() is workshop
    finally:
        window.close()
        window.deleteLater()


def test_live_run_misses_are_fixed(app, chat_env, level):
    """2026-11-22 full real run: 「术语库里添加词条」, "this window's save button", a tooltip-only 「快捷键」."""
    from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout
    from twobyteasr.app import bunny_pointing
    from twobyteasr.app.bunny_pointing import hint_for
    paged, _workshop = _paged_window(app)
    try:
        hint = hint_for(paged, '术语库里添加词条的按钮在哪')
        assert '按钮「添加」' in hint and '在「术语库」页' in hint
    finally:
        paged.close()
        paged.deleteLater()
    bunny_chat, window = chat_env
    dialog = QDialog(window)
    dialog.setWindowTitle('应用设置')
    QVBoxLayout(dialog).addWidget(QPushButton('保存更改'))
    dialog.show()
    app.processEvents()
    try:
        hint = hint_for(window, '这个窗口保存的按钮在哪')
        assert '现在开着的窗口：「应用设置」' in hint and '按钮「保存更改」' in hint
    finally:
        dialog.close()
    help_button = QPushButton('说明', window)
    help_button.setToolTip('说明、快捷键与新手教学')
    help_button.setGeometry(800, 10, 60, 28)
    help_button.show()
    window._open_application_settings = lambda initial_section='': None
    found = bunny_pointing.locate(window, {'text': '快捷键'})
    assert found.open_entry is not None and found.open_entry.key == 'shortcuts'


def test_a_page_still_coming_up_is_waited_for_not_called_missing(app, level):
    from PySide6.QtCore import QTimer
    from twobyteasr.app.bunny_tools import TOOLS
    window, workshop = _paged_window(app)
    try:
        window.pages.setCurrentWidget(workshop)              # switched, but behind a cover for a moment
        cover = __import__('PySide6.QtWidgets', fromlist=['QWidget']).QWidget(workshop)
        cover.setGeometry(workshop.rect())
        cover.setAutoFillBackground(True)
        cover.show()
        cover.raise_()
        app.processEvents()
        QTimer.singleShot(400, cover.hide)
        receipt = TOOLS['point_at'].run(window, {'text': '下载 FireRed 模型', 'page': 'workshop'})
        assert receipt.startswith('指好了') and '下载 FireRed 模型' in receipt
    finally:
        window.close()
        window.deleteLater()
