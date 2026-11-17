"""2026-11-17 (user): 「打开识别结果」 must reach the completion page, 兔白 opens results and projects
herself, and her two suggestion buttons follow the conversation."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_saved_chats():
    from twobyteasr.app import bunny_memory
    from twobyteasr.app.bunny_chat import NOTICE_KEY
    from twobyteasr.app.bunny_permissions import DEFAULTS, KEY
    from twobyteasr.app.onboarding import load_state, save_state
    bunny_memory.clear_chats()
    save_state(dict(load_state(), **{NOTICE_KEY: True, KEY: dict(DEFAULTS)}))   # past the first-time notice
    yield
    bunny_memory.clear_chats()


def _record(tmp_path, name='试玩第三集.mp4', status='completed', project=True, usable=True):
    target = tmp_path / f'{Path(name).stem}.2byteasr'
    if project:
        target.write_text('{}', encoding='utf-8')
    payload = {'status': status, 'media': {'path': name}, 'task': {}, 'events': [],
               'result': {'outputs': {'project': str(target)} if project else {}, 'elapsed_seconds': 1.0}}
    return SimpleNamespace(media_name=name, completed_at='2026-11-17 14:30', status=status, status_label='已完成',
                           cue_count=42, payload=payload, outcome=SimpleNamespace(result_usable=usable),
                           path=tmp_path / f'{Path(name).stem}.json')


def test_history_open_shows_the_completion_page(app, tmp_path, monkeypatch):
    """Before: the result loaded behind 识别记录 and the page never changed (only the progress page moved on)."""
    import subtitle_core
    from twobyteasr.app import ui
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda provider, base_url='': ('', ''))
    monkeypatch.setattr(llm_config, 'resolve_api_key', lambda stage: ('', ''))
    monkeypatch.setattr(ui, 'save_runtime_settings', lambda settings: None)
    window = ui.MainWindow([], subtitle_core, object(), None)
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    try:
        assert window.pages.currentWidget() is not window.pages.widget(2)
        window._open_completion_from_history(_record(tmp_path))
        app.processEvents()
        assert window.pages.currentWidget() is window.pages.widget(2)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_she_opens_a_recognition_result_by_number_or_name(tmp_path, monkeypatch):
    from twobyteasr.app import bunny_nav_tools
    from twobyteasr.app.bunny_tools import TOOLS, run_turn
    rows = [(tmp_path / 'a.json', _record(tmp_path, '日常第21话.mp4')),
            (tmp_path / 'b.json', _record(tmp_path, '崩铁抽卡.mp4', status='failed', project=False)),
            (tmp_path / 'c.json', None)]
    monkeypatch.setattr(bunny_nav_tools, 'result_records', lambda limit=10, roots=None: rows[:limit])
    opened = []
    window = SimpleNamespace(_open_completion_from_history=opened.append)
    listing = run_turn(window, [('recent_results', {})]).receipts[0]
    assert '1. 2026-11-17 14:30 · 日常第21话.mp4' in listing and '能打开结果' in listing
    assert '没有可打开的结果' in listing and '读不出来' in listing
    assert str(tmp_path) not in listing                              # names only, never paths
    done = run_turn(window, [('open_result', {'number': 1})]).receipts[0]
    assert '成功' in done and '识别完成的结果页' in done and opened == [rows[0][1]]
    by_name = run_turn(window, [('open_result', {'name': '日常'})]).receipts[0]
    assert '成功' in by_name and len(opened) == 2
    failed = run_turn(window, [('open_result', {'number': 2})]).receipts[0]
    assert '没做成' in failed and '没有能打开的结果' in failed and len(opened) == 2
    assert '没有第 9 个' in run_turn(window, [('open_result', {'number': 9})]).receipts[0]
    busy = SimpleNamespace(_open_completion_from_history=opened.append, _run_in_progress=True)
    assert '正在跑' in run_turn(busy, [('open_result', {'number': 1})]).receipts[0] and len(opened) == 2
    assert TOOLS['open_result'].acts and not TOOLS['recent_results'].acts
    # live run 2026-11-17: "the latest result" when the newest record failed — the newest one that has a result
    rows[:] = [rows[1], rows[0], rows[2]]
    latest = run_turn(window, [('open_result', {})]).receipts[0]
    assert '成功' in latest and '第 2 条「日常第21话.mp4」' in latest and opened[-1] is rows[1][1]
    hinted = run_turn(window, [('open_result', {'number': 1})]).receipts[0]
    assert '没有能打开的结果' in hinted and '最新一次能打开的是第 2 条「日常第21话.mp4」' in hinted


def test_her_project_list_is_in_the_librarys_recent_order(tmp_path, monkeypatch):
    from twobyteasr.app import bunny_nav_tools
    from twobyteasr.projects import studio_project
    settings = tmp_path / 'studio_settings.json'
    settings.write_text(json.dumps({'recent_projects': [
        {'path': str(tmp_path / 'a.2byteproj'), 'name': '旧的', 'last_opened': '2026-11-10T04:38:18+00:00'},
        {'path': str(tmp_path / 'b.2byteproj'), 'name': '未命名工程 33', 'last_opened': '2026-11-17T06:30:00+00:00'},
        {'path': str(tmp_path / 'c.2byteproj'), 'name': '更旧的', 'modified': '2026-11-01T00:00:00+00:00'},
    ]}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(studio_project, 'studio_settings_path', lambda: settings)
    assert [row['name'] for row in bunny_nav_tools.project_records()] == ['未命名工程 33', '旧的', '更旧的']


def test_she_opens_a_project_after_her_answer(tmp_path, monkeypatch):
    from twobyteasr.app import bunny_nav_tools
    from twobyteasr.app.bunny_tools import run_later, run_turn
    there = tmp_path / '未命名工程 33.2byteasr'
    there.write_text('{}', encoding='utf-8')
    rows = [{'path': str(there), 'name': '未命名工程 33', 'cue_count': 0, 'modified': '11-17 14:30',
             'source_media': r'C:\私人\狗.mp4', 'exists': True},
            {'path': str(tmp_path / 'gone.2byteasr'), 'name': '日常第14话', 'cue_count': 282, 'exists': False}]
    monkeypatch.setattr(bunny_nav_tools, 'project_records', lambda limit=10: rows)
    opened = []
    window = SimpleNamespace(open_studio_project=opened.append)
    listing = run_turn(window, [('recent_projects', {})]).receipts[0]
    assert '1. 「未命名工程 33」' in listing and '素材 狗.mp4' in listing and '私人' not in listing
    assert '工程文件不见了' in listing
    result = run_turn(window, [('open_project', {'number': 1})])
    assert '马上' in result.receipts[0] and not opened                 # not inside run_turn: the chat opens it
    assert result.later == [('open_project', {'number': 1})]
    run_later(window, *result.later[0])
    assert opened == [str(there)]
    assert '文件不见了' in run_turn(window, [('open_project', {'name': '日常'})]).receipts[0]


def test_her_suggestions_follow_the_conversation():
    from twobyteasr.app import bunny_persona
    reply = bunny_persona.parse_reply(
        '{"lines": ["好～"], "suggest": ["**帮我打开最近的识别结果**", "为什么会失败？", "为什么会失败？", "第三个"]}', [])
    assert reply.suggest == ('帮我打开最近的识别结果', '为什么会失败？')
    assert bunny_persona.parse_reply('{"lines": ["好～"]}', []).suggest == ()
    prompt = bunny_persona.system_prompt([])
    assert '- suggest：' in prompt and 'open_result' in prompt and 'recent_projects' in prompt


def _until(app, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def test_every_answer_ends_with_two_fresh_choices(app, monkeypatch):
    """2026-11-17 (user): two choices after every answer, like a galgame; when her answer forgot them,
    one quick request asks for them (no thinking, no pictures again)."""
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat, bunny_persona
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek'))
    asked = []

    def fake_run(worker):
        last = worker._messages[-1]['content']
        asked.append((getattr(worker, 'effort', 'off'), last))
        if last == bunny_persona.SUGGEST_ONLY:
            worker.answered.emit('{"suggest": ["帮我看看日志", "为什么会失败？"]}')
        else:
            worker.answered.emit('{"lines": ["导出失败多半是显卡编码器的问题～"]}')
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    monkeypatch.setattr(bunny_chat.ChoicesWorker, 'run', fake_run)
    window = QWidget()
    window.resize(1100, 720)
    window.help_button = QPushButton('说明', window)
    window.show()
    chat = bunny_chat.open_bunny_chat(window)
    try:
        chat.reveal_all()
        chat.input.setText('导出失败了')
        chat.send()
        deadline = time.monotonic() + 5
        while (len(asked) < 2 or chat._pending or chat.typer.running) and time.monotonic() < deadline:
            if chat.typer.running:
                chat.typer.finish()
            chat.reveal_all()
            app.processEvents()
        chat.reveal_all()
        app.processEvents()
        assert asked[1] == ('off', bunny_persona.SUGGEST_ONLY)            # quick, no thinking
        layout = chat.suggest_row.layout()
        labels = [layout.itemAt(i).widget().text() for i in range(layout.count()) if layout.itemAt(i).widget()]
        assert labels == [f'{bunny_chat.CHOICE_MARK}帮我看看日志', f'{bunny_chat.CHOICE_MARK}为什么会失败？']
        assert chat.suggest_row.isVisibleTo(chat)
        assert bunny_persona.suggestions_from('{"suggest": ["a 选项", "b 选项", "c"]}') == ('a 选项', 'b 选项')
    finally:
        chat.close_chat()
        window.close()


def test_the_buttons_show_her_next_steps_then_fall_back(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat, bunny_persona
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek'))
    monkeypatch.setattr(bunny_chat, 'current_page', lambda _window: '识别记录')
    window = QWidget()
    window.resize(1100, 720)
    window.help_button = QPushButton('说明', window)
    window.show()
    app.processEvents()
    chat = bunny_chat.open_bunny_chat(window)
    try:
        def labels():
            layout = chat.suggest_row.layout()
            return [layout.itemAt(i).widget().text().removeprefix(bunny_chat.CHOICE_MARK) for i in range(layout.count())
                    if layout.itemAt(i).widget() is not None]
        chat.reveal_all()
        chat.say(bunny_persona.BunnyReply(lines=['在呢～']))           # an answer without next steps
        chat.reveal_all()
        while chat.typer.running:
            chat.typer.finish()
        chat.reveal_all()
        chat.refresh_suggestions()
        assert labels() == ['打开最近一次识别结果', '上次识别为什么失败？']        # this page's own
        chat.say(bunny_persona.BunnyReply(lines=['打开啦，这次有 3 条待复核～'],
                                          suggest=('帮我逐条复核', '导出成 SRT')))
        chat.reveal_all()
        while chat.typer.running:
            chat.typer.finish()
        chat.reveal_all()
        chat.refresh_suggestions()
        assert labels() == ['帮我逐条复核', '导出成 SRT']
        sent = []
        monkeypatch.setattr(chat, '_ask', lambda question: sent.append(question))
        chat.suggest_row.layout().itemAt(0).widget().click()
        assert sent == ['帮我逐条复核']
        chat._ai_suggest = ()
        chat.refresh_suggestions()
        assert labels() == ['打开最近一次识别结果', '上次识别为什么失败？']
    finally:
        chat.close_chat()
        window.close()
        app.processEvents()
