"""「问问兔白」 chat card (2026-11-14): greeting, asking the AI, pointing, 「带我去」, closing."""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture(autouse=True)
def no_saved_chats():
    """2026-11-16: each project's chat is kept; a test never inherits another test's chat."""
    from twobyteasr.app import bunny_bond, bunny_memory
    bunny_memory.clear_chats()
    bunny_bond.clear()               # 2026-11-18: every test meets her as a stranger (her greeting follows it)
    yield
    bunny_memory.clear_chats()


def _choices_only(worker) -> bool:
    """2026-11-17: the quick request for her two choices after an answer; answered here, not counted."""
    from twobyteasr.app import bunny_persona
    if worker._messages and worker._messages[-1].get('content') == bunny_persona.SUGGEST_ONLY:
        worker.answered.emit('{"suggest": ["好的", "再说说"]}')
        return True
    return False


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _until(app, condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture
def chat_env(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    window = QWidget()
    window.resize(1100, 720)
    calls = []
    window.model_workshop_button = QPushButton('模型工坊', window)
    window.model_workshop_button.setGeometry(900, 10, 90, 28)
    window.help_button = QPushButton('说明', window)
    window._open_model_workshop = lambda: calls.append('workshop')
    window._open_ai_settings_dialog = lambda: calls.append('ai_settings')
    window.show()
    app.processEvents()
    yield bunny_chat, window, calls
    chat = getattr(window, '_bunny_chat', None)
    if chat is not None:
        chat.close_chat()
    window.close()
    window.deleteLater()
    app.processEvents()


def _plain(text):
    return str(text).replace('\u2060', '')    # word joiners keep words on one line


def _ready(monkeypatch, bunny_chat, ready=True):
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (ready, 'DeepSeek · deepseek-chat' if ready else ''))


def _shown_lines(chat):
    return chat.last_reply_html()


def test_without_ai_she_greets_and_offers_the_ai_settings(app, chat_env, monkeypatch):
    bunny_chat, window, calls = chat_env
    _ready(monkeypatch, bunny_chat, False)
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    assert chat.isVisible() and window._bunny_chat is chat
    assert '找功能在哪里' in ''.join(_shown_lines(chat))
    assert chat.go_button.isVisible() and '文字 AI' in chat.go_button.text()
    chat.go_button.click()
    assert calls == ['ai_settings']
    assert bunny_chat.open_bunny_chat(window) is chat          # the open card is reused

    chat.input.setText('标点怎么关掉')
    chat.send()
    chat.reveal_all()
    assert '首页' in ''.join(_shown_lines(chat))
    assert not chat.busy


def test_the_first_ai_greeting_says_where_the_words_go_once(app, chat_env, monkeypatch):
    from twobyteasr.app.onboarding import load_state, save_state
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    save_state({key: value for key, value in load_state().items() if key != bunny_chat.NOTICE_KEY})   # a first time
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    assert 'DeepSeek' in ''.join(_shown_lines(chat))
    assert load_state().get(bunny_chat.NOTICE_KEY) is True
    chat.close_chat()
    again = bunny_chat.open_bunny_chat(window)
    again.reveal_all()
    assert 'DeepSeek' not in ''.join(_shown_lines(again))


def test_first_notice_is_complete_in_the_initial_dialog_before_send(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    from twobyteasr.app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{bunny_chat.NOTICE_KEY: False}))
    _ready(monkeypatch, bunny_chat)
    chat = bunny_chat.open_bunny_chat(window)
    assert chat.mode == 'dialog'
    # Neither advance() nor reveal_all(): inspect what the user first sees.
    shown = _plain(chat.box.label.source_html)
    assert 'DeepSeek' in shown
    assert '额度' in shown and '字幕原文' in shown and '关闭' in shown
    assert not chat.typer.running


def test_an_answer_is_typed_points_at_the_place_and_offers_to_go(app, chat_env, monkeypatch):
    bunny_chat, window, calls = chat_env
    _ready(monkeypatch, bunny_chat)
    sent = []

    def fake_run(worker):
        if _choices_only(worker):
            return
        sent.append(worker._messages)
        worker.answered.emit(json.dumps({'lines': ['哇！在上面的 **模型工坊**', '~~兔白才没偷懒~~'],
                                         'point_to': 'model_workshop', 'offer_open': 'model_workshop',
                                         'mood': 'excited'}, ensure_ascii=False))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('模型去哪里下载')
    chat.send()
    assert chat.busy and not chat.send_button.isEnabled()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    lines = _shown_lines(chat)
    assert len(lines) == 2 and '模型工坊' in lines[0] and 'line-through' in lines[1]
    assert chat.spotlight.isVisible()
    assert chat.spotlight.target.topLeft() == window.model_workshop_button.pos()
    assert chat.go_button.isVisible() and chat.go_button.text().endswith('模型工坊')
    chat.go_button.click()
    assert calls == ['workshop']
    messages = sent[0]
    assert messages[0]['role'] == 'system' and messages[-1]['content'].endswith('模型去哪里下载')
    assert '模型工坊' in messages[-1]['content']                    # the world book entry went along

    chat.input.setText('谢谢兔白')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    history = sent[1]
    assert [m['role'] for m in history[1:]] == ['user', 'assistant', 'user']
    assert history[1]['content'] == '模型去哪里下载'
    assert json.loads(history[2]['content'])['point_to'] == 'model_workshop'


def test_a_failed_request_is_said_kindly_and_forgotten(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: worker.failed.emit('余额不足'))
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('你好')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert '余额不足' in ''.join(_shown_lines(chat))
    assert chat._history == []
    assert chat.input.isEnabled()


def test_closing_stops_everything_and_frees_the_window(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    chat = bunny_chat.open_bunny_chat(window)
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    app.sendEvent(chat, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    if chat.puck is not None:
        # 2026-11-26 (user): Esc folds the dialog box away; 兔白 stays. × closes the chat.
        assert window._bunny_chat is chat and chat.collapsed and not chat.isVisible()
        assert chat.puck.carrier.isVisible() and chat.fold_reason == 'user'
        chat.close_button.click()
    assert window._bunny_chat is None
    assert not chat.isVisible()


def test_the_state_names_the_page_and_never_more(app, chat_env):
    from PySide6.QtWidgets import QStackedWidget, QWidget
    bunny_chat, window, _calls = chat_env
    window.pages = QStackedWidget(window)
    home, progress, result = QWidget(), QWidget(), QWidget()
    for page in (home, progress, result):
        window.pages.addWidget(page)
    window.settings_scroll = home
    window.pages.setCurrentWidget(result)
    state = bunny_chat.app_state(window, True)
    assert state['page'] == '识别完成的结果页' and state['text_ai_ready'] is True
    assert set(state) <= set(__import__('twobyteasr.app.bunny_persona', fromlist=['x']).STATE_FIELDS)


def test_the_help_menu_entry_opens_the_chat(app, monkeypatch):
    from twobyteasr.app.ui import MainWindow
    opened = []
    monkeypatch.setattr('twobyteasr.app.bunny_chat.open_bunny_chat', lambda window: opened.append(window) or 'chat')
    fake = object()
    assert MainWindow._open_bunny_chat(fake) == 'chat' and opened == [fake]


def test_she_looks_up_the_last_task_before_answering(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from twobyteasr.app import bunny_lookup
    monkeypatch.setattr(bunny_lookup, 'run_check', lambda name, ai_ready=None, **_kw: '状态：失败；问题：显存不足')
    sent = []

    def fake_run(worker):
        if _choices_only(worker):
            return
        # 2026-11-15: the older ``check`` is a background tool now; its read rides with the next request.
        sent.append(list(worker._messages))
        if worker._background:
            from twobyteasr.app import bunny_persona
            from twobyteasr.app.bunny_tools import run_background
            turn = bunny_persona.tool_results_message(run_background(worker._background), '（状态）')
            worker._messages.append(turn)
            worker.looked_up.emit(turn)
            sent[-1] = list(worker._messages)
            worker.answered.emit(json.dumps({'lines': ['上次是 ==显存不足== 停下来的。'], 'mood': 'comfort'}, ensure_ascii=False))
        else:
            worker.answered.emit(json.dumps({'lines': ['我去看看你上一次的识别记录～'], 'check': 'last_task'}, ensure_ascii=False))
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', fake_run)
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('为什么识别出错了')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert '显存不足' in ''.join(_shown_lines(chat))
    assert len(sent) == 2
    assert sent[1][-1]['content'].startswith('【兔白操作结果】') and '显存不足' in sent[1][-1]['content']
    roles = [m['role'] for m in chat._history]
    assert roles == ['user', 'assistant', 'user', 'assistant']
    assert json.loads(chat._history[1]['content'])['check'] == 'last_task'


def test_the_dialog_box_goes_on_by_itself_and_keeps_the_answer_together(app, chat_env, monkeypatch):
    """2026-11-18 (user: a few words, then another click for the next sentence)."""
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from twobyteasr.app import bunny_persona
    monkeypatch.setattr(bunny_chat, 'LINE_PAUSE_MS', 10)
    chat = bunny_chat.open_bunny_chat(window)
    assert chat.mode == 'dialog' and not bunny_chat.click_lines()
    chat.reveal_all()
    chat.say(bunny_persona.BunnyReply(lines=['第一句。', '第二句。', '第三句。'],
                                      detail=('1. 点 **模型工坊**', '· 下载 ==不花钱=='), suggest=('好', '然后呢')))
    assert chat._detail_card is None                                   # the memo waits for her first sentence
    reserved = chat._reserve_h
    chat.typer.finish()
    assert not chat.box.more and chat.box.count.text() == ''           # nothing asks for a click
    # 2026-11-26 draft D: after her first sentence the memo is in her box and she writes on it while
    # she goes on speaking; its height was reserved before she began, so the box does not grow again.
    memo = chat._detail_card
    assert isinstance(memo, bunny_chat.MemoCard) and memo.parent() is chat.box and chat._pending
    assert reserved >= memo.height() and chat.box.height() >= reserved
    deadline = time.monotonic() + 3
    while (chat._pending or chat.typer.running or chat._memo_writing()) and time.monotonic() < deadline:
        app.processEvents()
        chat.typer.finish()
        chat.memo_typer.finish()
    shown = _plain(chat.box.label.source_html)
    assert '第一句' in shown and '第二句' in shown and '第三句' in shown  # together, not one replacing the other
    card = chat._detail_card
    assert card is not None and card.isVisible() and card.parent() is chat.box
    assert '模型工坊' in _plain(card.label.source_html) and card.height() <= chat.box.height()
    card.copy_button.click()
    from PySide6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == '1. 点 模型工坊\n· 下载 不花钱'
    assert chat.transcript[-1] == ('detail', '1. 点 **模型工坊**\n· 下载 ==不花钱==')
    assert chat.last_reply_html() and all('模型工坊' not in line for line in chat.last_reply_html())
    # A click on the box while she is still speaking shows everything at once.
    chat.say(bunny_persona.BunnyReply(lines=['甲。', '乙。', '丙。'], detail=('· 要点',)))
    assert chat._detail_card is None
    chat.advance()
    shown = _plain(chat.box.label.source_html)
    assert '甲' in shown and '丙' in shown and not chat._pending and chat._detail_card is not None
    # The thread view shows the same answer: bubbles, then the card; the saved chat brings it back.
    chat.set_mode('thread')
    assert chat._detail_card is None and chat.thread.findChildren(bunny_chat.DetailCard)
    history = bunny_chat.history_from(chat.transcript + [('user', '然后呢')])
    assert json.loads(history[-2]['content'])['detail'][-1] == '· 要点'   # (both answers, no question between)
    long_turn = bunny_chat.BunnyChat._reply_turn(bunny_persona.BunnyReply(lines=['好'], detail=('字' * 120,) * 6))
    assert sum(len(row) for row in json.loads(long_turn['content'])['detail']) <= bunny_chat.DETAIL_HISTORY_CHARS
    chat.set_mode('dialog')


def test_a_long_answer_never_grows_the_box_without_end(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from twobyteasr.app import bunny_persona, ui_zoom
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    lines = [f'第{n}句' + '很长的话' * 14 + '。' for n in range(1, 6)]
    chat.say(bunny_persona.BunnyReply(lines=lines, detail=tuple(f'{n}. ' + '步骤' * 40 for n in range(1, 13))))
    chat.reveal_all()
    shown = _plain(chat.box.label.source_html)
    assert '第5句' in shown and '第1句' not in shown                    # the oldest left; the thread keeps them
    assert [text for who, text in chat.transcript if who == 'bunny'][-5:] == lines
    assert chat._detail_card.scroll.height() <= ui_zoom.px(bunny_chat.DETAIL_HEIGHT)


@pytest.mark.parametrize('click', [False, True])
@pytest.mark.parametrize('floating', [False, True])
def test_her_later_sentences_never_move_or_resize_the_card(app, chat_env, monkeypatch, floating, click):
    """2026-11-19 (user): at her 2nd and 3rd sentence the card twitched, flashed or grew. The reply's
    height is taken at once, so later sentences change no geometry; when the card does change size
    it is placed in the same step, its bottom and 兔白 staying where they are."""
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', floating)   # (offscreen: Qt's own geometry)
    monkeypatch.setattr(bunny_chat, 'LINE_PAUSE_MS', 10)
    bunny_chat.set_click_lines(click)
    from PySide6.QtCore import QEvent, QObject
    from twobyteasr.app import bunny_persona
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    for _ in range(10):
        app.processEvents()
    seen = []

    class Watch(QObject):
        def eventFilter(self, watched, event):  # noqa: N802 - Qt override
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
                seen.append((chat.geometry().bottom(), chat.mascot.mapTo(window, chat.mascot.rect().topLeft())))
            return False
    watch = Watch()
    chat.installEventFilter(watch)
    bottom = chat.geometry().bottom()
    bunny_at = chat.mascot.mapTo(window, chat.mascot.rect().topLeft())
    chat.say(bunny_persona.BunnyReply(lines=['短的一句。', '第二句长一些，框要多一行才能放下这么多字。',
                                             '第三句还要更长一点点，看看框会不会再跳一次，兔白是不是会跟着动来动去。']))
    first = chat.geometry(), chat.box.geometry()
    deadline = time.monotonic() + 5
    while (chat._pending or chat.typer.running) and time.monotonic() < deadline:
        assert (chat.geometry(), chat.box.geometry()) == first         # sentences 2 and 3: nothing moves
        if click and not chat.typer.running:
            chat.advance()                                             # the click for the next sentence
        chat.typer.finish()                                            # (the last one brings her choices)
        app.processEvents()
        time.sleep(0.002)
    assert not chat._pending
    for _ in range(10):
        app.processEvents()
    assert seen, 'the reply should have changed the card at least once'
    assert all(at_bottom == bottom and at == bunny_at for at_bottom, at in seen)   # never a frame grown downward
    chat.removeEventFilter(watch)
    bunny_chat.set_click_lines(False)


def test_the_dialog_box_says_one_sentence_at_a_time_when_asked_to(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    bunny_chat.set_click_lines(True)                                   # 「兔白一句一句说，点一下才说下一句」
    from twobyteasr.app import bunny_persona
    from twobyteasr.app.tour_mascot import MascotVoice
    chat = bunny_chat.open_bunny_chat(window)
    assert chat.mode == 'dialog' and chat.box.isVisible() and not chat.thread.isVisible()
    assert isinstance(chat.voice, MascotVoice)                         # the tutorial's own voice
    chat.reveal_all()
    chat.say(bunny_persona.BunnyReply(lines=['第一句。', '第二句。', '第三句。']))
    chat.typer.finish()
    assert '第一句' in _plain(chat.box.label.source_html) and chat.box.more and chat.box.count.text() == '1 / 3'
    chat.advance()                                                     # a click on the box
    chat.typer.finish()
    assert '第二句' in _plain(chat.box.label.source_html) and chat.box.count.text() == '2 / 3'
    chat.input.clear()
    chat.send()                                                        # Enter with nothing typed goes on too
    chat.typer.finish()
    assert '第三句' in _plain(chat.box.label.source_html) and not chat.box.more
    # 2026-11-26 (user, later the same day): what she says reads in 猫啃什锦黑 again, a size up;
    # the input stays in 思源黑体.
    assert chat.box.label.font().family() == bunny_chat.chat_font_family()
    assert chat.input.font().family() == 'Source Han Sans SC Medium'


def test_cancelled_lookup_does_not_start_an_ai_request(app, monkeypatch):
    from twobyteasr.app import bunny_chat, bunny_lookup
    from twobyteasr.providers import ai_providers
    worker = bunny_chat.BunnyChatWorker({}, [], lookup='last_task')
    cancelled = {'value': False}
    monkeypatch.setattr(worker, 'isInterruptionRequested', lambda: cancelled['value'])
    def lookup(*args, **kwargs):
        cancelled['value'] = True
        return '状态：完成'
    monkeypatch.setattr(bunny_lookup, 'run_check', lookup)
    def unexpected(*args, **kwargs):
        raise AssertionError('cancelled lookup started a provider')
    monkeypatch.setattr(ai_providers, 'provider_for_stage', unexpected)
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert cancelled['value'] and not failures


def test_the_thread_keeps_every_line_and_switching_keeps_the_talk(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from twobyteasr.app import bunny_persona
    from twobyteasr.app.onboarding import load_state
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    chat.transcript.append(('user', '<b>你好</b>'))
    chat.say(bunny_persona.BunnyReply(lines=['你好呀。', '今天也做字幕吗？']))
    chat.set_mode('thread')
    app.processEvents()
    assert load_state().get(bunny_chat.MODE_KEY) == 'thread'
    assert chat.thread.isVisible() and not chat.box.isVisible()
    from twobyteasr.app.tour_mascot import MarkedLabel
    labels = [label for label in chat.thread.body.findChildren(MarkedLabel)]
    texts = [_plain(label.source_html) for label in labels]
    assert any('&lt;b&gt;你好' in text for text in texts)                # the user's words, escaped
    assert any('今天也做字幕吗' in text for text in texts)
    # 兔白 stands beside the panel, never over its words
    assert not chat.thread.geometry().intersects(
        chat.mascot.geometry().adjusted(chat.mascot.pad_x, 0, -chat.mascot.pad_x, 0)) or chat.mascot is None
    chat.set_mode('dialog')
    assert '今天也做字幕吗' in _plain(chat.box.label.source_html)
    chat.close_chat()
    reopened = bunny_chat.open_bunny_chat(window)
    assert reopened.mode == 'dialog'


def test_a_poke_gets_a_real_line_in_its_own_voice(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    monkeypatch.setattr(bunny_chat, 'POKE_TIP_SHARE', 0.0)   # 2026-11-16: the joke side; tips: test_bunny_tips
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    moods = []
    real_say = chat.voice.say
    monkeypatch.setattr(chat.voice, 'say', lambda char, mood='': moods.append(mood) or real_say(char, mood))
    chat.poke()
    import html as html_lib
    import re
    from twobyteasr.app.tour_mascot import plain
    said = html_lib.unescape(re.sub(r'<[^>]+>', '', _plain(chat.last_reply_html()[-1])))
    assert said in [plain(line) for line, _mood in bunny_chat.POKE_LINES]
    chat.reveal_all()
    while chat.typer.running:
        chat.typer.finish()
    assert all('字幕' not in line for line, _mood in bunny_chat.POKE_LINES)


def test_a_fright_stays_with_her_until_they_make_up(app, chat_env, monkeypatch):
    """2026-11-17 (user): frightening or hurtful words leave her uneasy for a while, until an apology;
    a meme waits a few questions; the cat-girl act works once per chat."""
    from twobyteasr.app import bunny_persona
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    monkeypatch.setattr(bunny_chat, 'POKE_TIP_SHARE', 1.0)        # a tip normally — but not while she hides
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    chat._note_mood(bunny_persona.BunnyReply(lines=['%%呜%%……不要说这个……'], mood='scared', spooked=True))
    assert chat._uneasy == bunny_persona.UNEASY_TURNS
    state = chat.inner_state('怎么导出')
    assert state['uneasy'] and not state['meme_ok'] and not state['plot_ok']
    assert '还有点怕' in chat.messages_for('怎么导出')[-1]['content']
    chat.poke()
    from twobyteasr.app.tour_mascot import plain
    import html as html_lib
    import re
    said = html_lib.unescape(re.sub(r'<[^>]+>', '', _plain(chat.last_reply_html()[-1])))
    assert said in [plain(line) for line, _mood in bunny_chat.UNEASY_POKE_LINES]
    chat._note_mood(bunny_persona.BunnyReply(lines=['……那、那就原谅你这一次'], made_up=True))
    assert chat._uneasy == 0 and '还有点怕' not in chat.messages_for('怎么导出')[-1]['content']
    chat._note_mood(bunny_persona.BunnyReply(lines=['又是电子牛马的一天']))
    assert chat._since_meme == 0 and not chat.inner_state()['meme_ok']
    chat._question = '兔白你是猫娘吧'
    chat._note_mood(bunny_persona.BunnyReply(lines=['喵～', '要摸摸头吗喵？', '逗逗你的！']))
    assert chat.inner_state('再扮演一次猫娘')['tricked'] and not chat.inner_state('怎么导出')['tricked']
    chat.new_conversation()
    assert not chat.inner_state('再扮演一次猫娘')['tricked']
    while chat.typer.running:
        chat.typer.finish()


def _mouse(kind, widget, local, global_point):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    button = Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind.name == 'MouseButtonRelease' else button
    return QMouseEvent(kind, QPointF(local), QPointF(global_point), button if kind.name != 'MouseMove' else Qt.MouseButton.NoButton,
                       buttons, Qt.KeyboardModifier.NoModifier)


def test_she_can_be_thrown_bounces_off_the_edges_and_comes_home(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from twobyteasr.app import bunny_puck
    from twobyteasr.design import bunny_physics
    monkeypatch.setattr(bunny_puck, 'REST_BEFORE_HOME_MS', 50)
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    puck = chat.puck
    if puck is None:
        pytest.skip('no mascot pictures in this build')
    hits = []
    monkeypatch.setattr(puck, '_edge_hit', lambda side, power: hits.append(side))
    puck.undock()
    assert not puck.docked and not chat.mascot_docked and chat.mascot.parent() is puck.carrier
    from PySide6.QtCore import QPointF
    import time as _time
    puck.velocity = QPointF(-3000, -1800)
    puck.started = puck.last = _time.perf_counter()
    puck.timer.start()
    assert _until(app, lambda: puck.docked, seconds=bunny_physics.MAX_FLIGHT_S + 3)
    assert hits and set(hits) <= {'left', 'right', 'top', 'bottom'}
    assert chat.mascot.parent() is chat and chat.mascot_docked
    limits = puck.limits()
    assert limits.width() > 0 and limits.height() > 0


def test_a_click_without_moving_is_still_a_poke(app, chat_env, monkeypatch):
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from PySide6.QtCore import QEvent, QPointF
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    if chat.puck is None:
        pytest.skip('no mascot pictures in this build')
    pokes = []
    monkeypatch.setattr(chat, 'poke', lambda: pokes.append(1))
    mascot = chat.mascot
    at = mascot.rig_to_widget(458, 330)          # the top of her head (2026-11-26: ears, cheeks... react on their own)
    origin = QPointF(mascot.mapToGlobal(at.toPoint()))
    assert chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, mascot, at, origin))
    assert chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, mascot, at, origin))
    assert pokes == [1] and chat.puck.docked


def test_her_parts_answer_taps_and_pulls_on_their_own(app, chat_env, monkeypatch):
    """2026-11-26: tapping a cheek squashes it, an ear pulled stretches and springs back, the ring spins."""
    bunny_chat, window, _calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from PySide6.QtCore import QEvent, QPointF
    chat = bunny_chat.open_bunny_chat(window)
    chat.reveal_all()
    if chat.puck is None:
        pytest.skip('no mascot pictures in this build')
    pokes = []
    monkeypatch.setattr(chat, 'poke', lambda: pokes.append(1))
    mascot, life = chat.mascot, chat.mascot.life

    def tap(x, y):
        at = mascot.rig_to_widget(x, y)
        origin = QPointF(mascot.mapToGlobal(at.toPoint()))
        chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, mascot, at, origin))
        chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, mascot, at, origin))

    tap(548, 578)                                # right cheek
    assert life.squash.v < 0 and life.blush > 0
    tap(452, 100)                                # the key ring
    assert abs(life.part('ring').spin) > 10
    # Pull the left ear well away from her: it bends and stretches toward the pointer, she winces.
    root = mascot.rig_to_widget(346, 256)
    start = mascot.rig_to_widget(316, 150)
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonPress, mascot, start, QPointF(mascot.mapToGlobal(start.toPoint()))))
    pull = root + QPointF(-60, -10)
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseMove, mascot, pull, QPointF(mascot.mapToGlobal(pull.toPoint()))))
    ear = life.part('earL')
    assert life.tugging and ear.stretch_target > 0.1 and ear.target < -0.5
    chat.eventFilter(mascot, _mouse(QEvent.Type.MouseButtonRelease, mascot, pull, QPointF(mascot.mapToGlobal(pull.toPoint()))))
    assert not life.tugging and ear.target == 0 and ear.stretch_target == 0
    assert pokes == [] and chat.puck.docked


def test_she_drifts_beside_the_place_and_does_only_what_is_pressed(app, chat_env, monkeypatch):
    bunny_chat, window, calls = chat_env
    _ready(monkeypatch, bunny_chat)
    from PySide6.QtWidgets import QComboBox
    from twobyteasr.app import bunny_puck
    monkeypatch.setattr(bunny_puck, 'DRIFT_MS', 60)
    combo = QComboBox(window)
    for label, value in (('自动识别语言', 'auto'), ('英语', 'en')):
        combo.addItem(label, value)
    combo.setGeometry(100, 300, 160, 30)
    combo.show()
    window.recognition_language = combo
    window._return_to_settings = lambda: calls.append('home')
    answer = json.dumps({'lines': ['要我帮你改成英语吗？'], 'do': {'action': 'set_spoken_language', 'value': 'en'}},
                        ensure_ascii=False)
    monkeypatch.setattr(bunny_chat.BunnyChatWorker, 'run', lambda worker: worker.answered.emit(answer))
    chat = bunny_chat.open_bunny_chat(window)
    chat.input.setText('帮我把语言改成英语')
    chat.send()
    assert _until(app, lambda: not chat.busy)
    chat.reveal_all()
    assert chat.do_button.isVisible() and '英语' in chat.do_button.text()
    assert combo.currentData() == 'auto'                                   # nothing changed yet
    chat.do_button.click()
    assert _until(app, lambda: combo.currentData() == 'en', seconds=5)
    assert 'home' in calls
    if chat.puck is not None:
        spot = chat.puck.spot_beside(combo)
        assert abs(chat.puck.pos.x() - spot.x()) < 2 and abs(chat.puck.pos.y() - spot.y()) < 2
    chat.reveal_all()
    assert '视频里说的话' in _plain(''.join(chat.last_reply_html())) and not chat.do_button.isVisible()
