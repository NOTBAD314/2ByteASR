"""兔白看画面 (2026-11-16): a picture of 2ByteASR's own windows, only for an AI that can see images."""
from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_state():
    from twobyteasr.app import bunny_memory
    from twobyteasr.app.bunny_chat import NOTICE_KEY
    from twobyteasr.app.bunny_permissions import DEFAULTS, KEY
    from twobyteasr.app.onboarding import load_state, save_state
    bunny_memory.clear_chats()
    save_state(dict(load_state(), **{NOTICE_KEY: True, KEY: dict(DEFAULTS)}))
    yield
    bunny_memory.clear_chats()


def _until(app, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def test_which_ais_can_see_and_what_she_says_when_hers_cannot():
    from twobyteasr.app.bunny_vision import SEEING_MODELS, advice, judge
    able, why = judge('deepseek', 'deepseek-flash', 'openai_compatible', None)
    assert not able and '文字模型' in why and 'deepseek-flash' in why
    assert SEEING_MODELS in advice(why) and 'Claude' in advice(why) and 'AI 设置' in advice(why)
    assert judge('deepseek', 'deepseek-v4-pro', 'openai_compatible', False)[0] is False
    assert judge('anthropic', 'claude-sonnet-5-5', 'openai_compatible', None) == (True, '')
    assert judge('openai', 'gpt-4.1-mini', 'openai_compatible', None)[0]
    assert judge('gemini', 'gemini-3.8-flash', 'openai_compatible', None)[0]
    assert judge('bailian', 'qwen-vl-max', 'openai_compatible', None)[0]
    assert not judge('bailian', 'qwen3.7-flash-2026-07-15', 'openai_compatible', None)[0]    # does not say: no
    assert judge('custom', 'my-model', 'openai_compatible', True)[0]           # the model list says images
    assert not judge('custom', 'gpt-4o', 'openai_compatible', False)[0]        # ... or says no
    assert judge('custom', 'my-model', 'openai_compatible', None, declared=True)[0]
    assert judge('grok_oauth', '', 'grok_cli', None)[0]
    assert not judge('openai_codex_cli', '', 'codex_cli', None)[0]


def test_support_reads_the_bunny_service_and_never_guesses_without_settings(monkeypatch):
    from twobyteasr.app import bunny_vision
    able, why = bunny_vision.support(None)
    assert not able and '还没有设置文字 AI' in why
    settings = {'models': {'polish_provider': 'deepseek', 'polish_model': 'deepseek-flash',
                           'polish_base_url': 'https://api.deepseek.com/v1'}}
    able, why = bunny_vision.support(settings)
    assert not able and bunny_vision.SEEING_MODELS in why


def test_the_switch_is_off_by_default_and_refuses_with_where_to_turn_it_on():
    from twobyteasr.app import bunny_permissions
    from twobyteasr.app.bunny_tools import TOOLS
    values = bunny_permissions.load()
    assert values['see_screen'] is False
    assert '让兔白截图看 2ByteASR 的画面' in bunny_permissions.refusal(TOOLS['look_screen'], values)
    assert bunny_permissions.refusal(TOOLS['look_screen'], dict(values, see_screen=True)) == ''
    # a look is not an action: 「只指路」 may still look
    assert bunny_permissions.refusal(TOOLS['look_screen'], dict(values, see_screen=True, level='guide')) == ''
    assert not bunny_permissions.needs_confirmation(TOOLS['look_screen'], dict(values, see_screen=True))
    saved = bunny_permissions.save({'see_screen': True})
    assert saved['see_screen'] is True and bunny_permissions.load()['see_screen'] is True
    assert '能截图' in bunny_permissions.describe()


def test_the_picture_is_only_2byteasr_and_never_her_own_card(app):
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QDialog, QLabel, QWidget
    from twobyteasr.app import bunny_vision
    window = QWidget()
    window.setStyleSheet('background: #ff0000;')
    window.resize(400, 300)
    card = QLabel('兔白', window)
    card.setObjectName('bunnyChat')
    card.setStyleSheet('background: #00ff00;')
    card.setGeometry(250, 150, 140, 140)
    window.show()
    other = QDialog(window)
    other.setWindowTitle('导出字幕')
    other.resize(120, 80)
    other.show()
    app.processEvents()
    try:
        shot = bunny_vision.capture(window)
        assert shot.data_url.startswith('data:image/jpeg;base64,')
        assert max(shot.width, shot.height) <= bunny_vision.LONG_SIDE
        assert '「导出字幕」' in shot.receipt and '看不清' in shot.receipt
        assert card.isVisible()                                     # put back after the picture
        image = QImage.fromData(__import__('base64').b64decode(shot.data_url.split(',', 1)[1]))
        origin = window.mapToGlobal(window.rect().topLeft())
        left = min(origin.x(), other.mapToGlobal(other.rect().topLeft()).x())
        top = min(origin.y(), other.mapToGlobal(other.rect().topLeft()).y())
        sample = QColor(image.pixel(origin.x() - left + 320, origin.y() - top + 220))
        assert sample.red() > 180 and sample.green() < 90           # the window's red, not her green card
        assert shot.placeholder.startswith('[截图 ')
    finally:
        other.close()
        window.close()


def test_only_the_next_request_carries_the_picture():
    from twobyteasr.app.bunny_vision import Capture, text_only, with_images
    shot = Capture('截好了', 'data:image/jpeg;base64,AAAA', 640, 360)
    turn = {'role': 'user', 'content': '【兔白操作结果】'}
    sent = with_images(turn, [shot])
    assert sent['content'][0] == {'type': 'text', 'text': '【兔白操作结果】'}
    assert sent['content'][1]['image_url']['url'] == shot.data_url
    assert with_images(turn, []) is turn
    assert text_only(sent) == {'role': 'user', 'content': '【兔白操作结果】\n[截图]'}


@pytest.fixture
def chat_env(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'Claude · claude-sonnet-5-5'))
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


def _scripted(monkeypatch, bunny_chat, replies, sent):
    queue = list(replies)

    def fake_run(worker):
        sent.append(worker._messages if not worker._receipts else worker._messages)
        if worker._receipts is not None or worker._background:
            from twobyteasr.app.bunny_vision import with_images
            turn = bunny_chat.bunny_persona.tool_results_message(worker._receipts or [], worker._state_text)
            sent[-1] = [*worker._messages, with_images(turn, worker._images)]
            worker.looked_up.emit(turn)
        worker.answered.emit(json.dumps(queue.pop(0), ensure_ascii=False))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)


def test_she_looks_once_shows_the_picture_and_keeps_only_words(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from twobyteasr.app import bunny_permissions, bunny_vision
    bunny_permissions.save({'see_screen': True})
    monkeypatch.setattr(bunny_vision, 'support', lambda settings: (True, ''))
    sent = []
    _scripted(monkeypatch, bunny_chat, [
        {'lines': ['兔白看一眼～'], 'tools': [{'name': 'look_screen'}, {'name': 'look_screen'}]},
        {'lines': ['看到了，右下角的按钮被挡住了'], 'mood': 'thinking'},
        {'lines': ['不客气～']},
    ], sent)
    chat = bunny_chat.open_bunny_chat(window)
    assert 'look_screen' in chat.messages_for('你看一下')[0]['content']
    chat.input.setText('你看一下画面哪里怪')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    second = sent[1][-1]
    assert isinstance(second['content'], list) and second['content'][1]['type'] == 'image_url'
    assert '截好了 2ByteASR 的画面' in second['content'][0]['text']
    assert '一轮只截一张' in second['content'][0]['text']                 # the second ask in one round waits
    assert chat.shot_label.isVisible() and not chat.shot_label.pixmap().isNull()
    assert all(isinstance(turn['content'], str) for turn in chat._history)   # no picture kept
    chat.input.setText('谢谢')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    assert all(isinstance(m['content'], str) for m in sent[2])               # never sent twice
    assert not chat.shot_label.isVisible()


def test_a_text_only_ai_is_not_offered_the_tool_and_she_knows_why(app, chat_env, monkeypatch):
    bunny_chat, window = chat_env
    from twobyteasr.app import bunny_permissions, bunny_vision
    bunny_permissions.save({'see_screen': True})
    monkeypatch.setattr(bunny_vision, 'support',
                        lambda settings: (False, bunny_vision.advice('现在兔白用的 deepseek-flash 是文字模型，看不了图。')))
    chat = bunny_chat.open_bunny_chat(window)
    messages = chat.messages_for('你看得到画面吗')
    assert 'look_screen {}' not in messages[0]['content']
    assert '兔白看画面：不能' in messages[-1]['content'] and 'Claude' in messages[-1]['content']
    # asked anyway: refused with the same advice, nothing is pictured
    from twobyteasr.app.bunny_tools import run_turn
    result = run_turn(window, [('look_screen', {})], bunny_permissions.load())
    assert not result.images and '文字模型' in result.receipts[0]
    bunny_permissions.save({'see_screen': False})
    assert '没打开' in chat.messages_for('你看一下')[-1]['content']
    result = run_turn(window, [('look_screen', {})], bunny_permissions.load())
    assert not result.images and '兔白权限' in result.receipts[0]
