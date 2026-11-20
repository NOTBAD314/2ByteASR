"""Harness phase 5 (2026-11-18): what just happened, looking up before she is asked to, made-up names."""
from __future__ import annotations

import json
import time

import pytest

from twobyteasr.app import bunny_events, bunny_permissions, bunny_persona


@pytest.fixture(autouse=True)
def clean():
    from twobyteasr.app import bunny_bond, bunny_memory
    bunny_events.forget_recent()
    bunny_memory.clear_chats()
    bunny_bond.clear()
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS))
    yield
    bunny_events.forget_recent()
    bunny_memory.clear_chats()
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS))


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _until(app, condition, seconds=8.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def chat_env(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    from twobyteasr.app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{bunny_chat.NOTICE_KEY: True}))
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek · deepseek-chat'))
    window = QWidget()
    window.resize(1100, 720)
    window.help_button = QPushButton('说明', window)
    window.show()
    app.processEvents()
    yield bunny_chat, window
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    window.close()
    window.deleteLater()
    app.processEvents()


def _provider(monkeypatch, answers):
    """A text AI that gives ``answers`` in turn; the quick request for her two choices is answered apart."""
    from twobyteasr.providers import ai_providers
    sent = []
    rows = iter(answers)

    class Fake:
        def complete(self, messages, **kwargs):
            if messages and messages[-1].get('content') == bunny_persona.SUGGEST_ONLY:
                return '{"suggest": ["好的", "再说说"]}'
            sent.append(list(messages))
            return json.dumps(next(rows), ensure_ascii=False)
    monkeypatch.setattr(ai_providers, 'provider_for_stage', lambda settings, stage: Fake())
    return sent


# ------------------------------------------------------------------ what just happened
def test_she_keeps_the_last_half_hour_of_happenings():
    now = 10_000.0
    assert bunny_events.recent_text(now) == ''
    bunny_events.remember('跳出过一个提示框「导出失败：显卡编码器不可用」', now - 600)
    bunny_events.remember('一次识别结束了，状态是“失败 · 可重试”', now - 20)
    bunny_events.remember('一次识别结束了，状态是“失败 · 可重试”', now - 10)          # the same twice in a row
    text = bunny_events.recent_text(now)
    assert text.startswith('10 分钟前跳出过一个提示框') and '刚才一次识别结束了' in text and text.count('识别结束') == 1
    assert bunny_events.recent_text(now + bunny_events.RECENT_S + 700) == ''       # old news is not news
    for index in range(20):
        bunny_events.remember(f'第 {index} 件事 ' + '长' * 400, now + index * 40)
    kept = bunny_events.recent_text(now + 800)
    assert kept.count('件事') == bunny_events.RECENT_KEEP and '第 19 件事' in kept
    assert max(len(part) for part in kept.split('；')) < bunny_events.RECENT_CHARS + 12


def test_the_ai_gets_the_happenings_only_when_she_may_read_diagnostics(app, chat_env):
    bunny_chat, window = chat_env
    bunny_events.remember('跳出过一个提示框「导出失败：显卡编码器不可用」')
    state = bunny_chat.app_state(window, True)
    assert '显卡编码器不可用' in state['recent']
    shown = bunny_persona.format_state(state)
    assert '最近发生的事：刚才跳出过一个提示框' in shown
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS, read_diagnostics=False))
    assert 'recent' not in bunny_chat.app_state(window, True)


def test_a_closed_error_box_is_remembered_by_the_resident(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QWidget
    from twobyteasr.app import bunny_chat, bunny_resident
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    window = QWidget()
    window.show()
    resident = bunny_resident.install(window, hello=False)
    try:
        box = QMessageBox(QMessageBox.Icon.Critical, '识别失败', '显存不够：CUDA out of memory',
                          QMessageBox.StandardButton.Ok, window)
        box.show()
        app.processEvents()
        box.hide()
        app.processEvents()
        assert 'CUDA out of memory' in bunny_events.recent_text()
        box.deleteLater()
    finally:
        resident._timer.stop()
        app.removeEventFilter(resident)
        window.close()
        window.deleteLater()
        app.processEvents()


# ------------------------------------------------------------------ looking up before she asks
@pytest.mark.parametrize('question, wanted', [
    # 2026-11-18: recognition trouble gets the whole raw JSON analysed (bunny_report), not the short summary.
    ('识别又失败了', 'analyze_recognition'), ('为什么错字这么多', 'analyze_recognition'),
    ('刚才报错了是怎么回事', 'analyze_recognition'), ('上次识别为什么失败？帮我查一下原因和解决办法', 'analyze_recognition'),
    ('我的电脑能不能用本机识别', 'hardware'), ('这显卡跑得动吗，显存够不够', 'hardware'),
    ('怎么导出字幕', ''), ('刚才导出失败了', ''), ('模型下载失败了', ''), ('字幕怎么切开', ''), ('今天好累', ''),
    ('失败' * 150, ''),
])
def test_which_questions_are_looked_up_first(question, wanted):
    assert bunny_persona.auto_lookup(question) == wanted


def test_why_did_it_fail_is_answered_in_one_request(app, chat_env, monkeypatch):
    from twobyteasr.app import bunny_report
    bunny_chat, window = chat_env
    looked = []
    monkeypatch.setattr(bunny_report, 'task_path',
                        lambda job='', number=0: (looked.append('analyze_recognition') or 'x.json', '最近一次识别'))
    monkeypatch.setattr(bunny_report, 'analyze_file', lambda path, **kw: '【有问题】主力转写 · 显存不够')
    sent = _provider(monkeypatch, [{'lines': ['是显存不够啦，关掉游戏再试一次。']}])
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    chat.input.setText('识别又失败了')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert looked == ['analyze_recognition'] and len(sent) == 1        # one request, the record already in it
    handed = sent[0][-1]['content']
    assert handed.startswith('【兔白查到的：这次识别的原始 JSON 分析】') and '显存不够' in handed
    assert bunny_persona.AUTO_REPLY_HINT in handed and bunny_persona.CHECK_REPLY_HINT not in handed
    assert '显存不够' in ''.join(chat.last_reply_html())


def test_nothing_is_looked_up_when_she_may_not_read_the_records(app, chat_env, monkeypatch):
    from twobyteasr.app import bunny_lookup
    bunny_chat, window = chat_env
    bunny_permissions.save(dict(bunny_permissions.DEFAULTS, read_diagnostics=False))
    looked = []
    monkeypatch.setattr(bunny_lookup, 'run_check', lambda name, **kw: looked.append(name) or 'x')
    from twobyteasr.app import bunny_report
    monkeypatch.setattr(bunny_report, 'task_path', lambda job='', number=0: (looked.append('analysis') or None, 'x'))
    sent = _provider(monkeypatch, [{'lines': ['兔白现在不能读识别记录，可以在兔白权限里打开。']}])
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    assert chat._auto_lookup('识别又失败了') == ''
    chat.input.setText('识别又失败了')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    assert looked == [] and len(sent) == 1 and '兔白查到的' not in sent[0][-1]['content']


# ------------------------------------------------------------------ a how-to that stops at step one
def test_a_how_to_that_gives_only_the_first_step_is_asked_again(app, chat_env, monkeypatch):
    drip = bunny_persona.parse_reply('{"lines": ["第一次用呀，兔白带你走一遍～", "先把视频拖进首页的大框里。", "拖进来之后，兔白再陪你挑方案。"]}', ())
    assert bunny_persona.thin_how_to('我第一次用，怎么从头做一份字幕？', drip)
    assert not bunny_persona.thin_how_to('帮我从头做一份字幕，怎么弄都行', drip)          # he asked her to do it
    assert not bunny_persona.thin_how_to('今天天气怎么样', bunny_persona.parse_reply('{"lines": ["兔白不知道外面的天气呢。"]}', ()))
    full = bunny_persona.parse_reply('{"lines": ["三步就好～"], "detail": ["1. 拖进视频", "2. 选方案", "3. 点开始"]}', ())
    assert not bunny_persona.thin_how_to('怎么从头做一份字幕？', full)
    bunny_chat, window = chat_env
    sent = _provider(monkeypatch, [
        {'lines': ['兔白带你走一遍～', '先把视频拖进大框，拖好了告诉兔白，再说下一步。']},
        {'lines': ['其实就三步～'], 'detail': ['1. 把视频拖进首页的大框', '2. 选识别方案', '3. 点开始，做完导出']},
    ])
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    chat.input.setText('怎么从头做一份字幕？')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert len(sent) == 2 and sent[1][-1]['content'] == bunny_persona.THIN_RETRY
    assert chat.transcript[-1][0] == 'detail' and '导出' in chat.transcript[-1][1]


# ------------------------------------------------------------------ made-up names
def test_a_quoted_name_must_come_from_what_she_was_given():
    reply = bunny_persona.parse_reply(
        '{"lines": ["点「模型工坊」里的「一键优化」就好～"], "detail": ["1. 打开 **「模型工坊」**", "2. 点「一键优化」"]}', ())
    assert bunny_persona.unknown_names(reply, '说明书：「模型工坊」下载模型') == ['一键优化']
    assert bunny_persona.unknown_names(reply, '「模型工坊」「一键优化」') == []
    plain = bunny_persona.parse_reply('{"lines": ["按 **Ctrl+E** 导出，很快的～"]}', ())
    assert bunny_persona.unknown_names(plain, '') == []                 # only 「」 names are checked
    retry = bunny_persona.names_retry_messages('{"lines": []}', ['一键优化'])
    assert retry[0]['role'] == 'assistant' and '「一键优化」' in retry[1]['content']


def test_a_made_up_button_is_pointed_out_once_and_she_answers_again(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    sent = _provider(monkeypatch, [
        {'lines': ['点「一键美化字幕」就全部弄好啦～']},
        {'lines': ['兔白说错了……在工具面板的「样式」里改字号和描边。']},
    ])
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    chat.input.setText('怎么让字幕好看一点')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert len(sent) == 2 and '「一键美化字幕」' in sent[1][-1]['content']
    said = ''.join(chat.last_reply_html())
    assert '一键美化字幕' not in said and '样式' in said
    # Once per question: a second made-up name is shown rather than looping.
    sent2 = _provider(monkeypatch, [{'lines': ['点「魔法按钮」～']}, {'lines': ['点「另一个魔法按钮」～']}])
    chat.input.setText('再说一次')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    assert len(sent2) == 2
