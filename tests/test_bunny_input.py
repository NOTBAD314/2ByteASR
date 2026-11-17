"""2026-11-17 (user): the chat input takes long pastes (a JSON, a log) on its own row above the buttons."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _key(widget, key, modifiers=None):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(widget, key, modifiers or Qt.KeyboardModifier.NoModifier)


def test_enter_sends_shift_enter_breaks_and_long_text_fits(app):
    from PySide6.QtCore import Qt
    from twobyteasr.app.bunny_chat import INPUT_LIMIT, ChatInput
    box = ChatInput()
    box.resize(360, 40)
    box.show()
    sent, typed = [], []
    box.returnPressed.connect(lambda: sent.append(box.text()))
    box.textEdited.connect(typed.append)
    single = box.height()
    box.setText('{"a": 1,')
    assert typed == []                                          # programmatic text is not typing
    _key(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    box.insertPlainText(' "b": 2}')
    assert box.text() == '{"a": 1,\n "b": 2}' and sent == [] and typed
    _key(box, Qt.Key.Key_Return)
    assert sent == ['{"a": 1,\n "b": 2}']
    long = 'x' * 5000
    box.setText(long)
    app.processEvents()
    assert box.text() == long                                   # no more 300-character cut
    assert box.height() > single                                # grows with the text …
    tall = box.height()
    box.setText('\n'.join(['line'] * 40))
    app.processEvents()
    assert box.height() == tall or box.height() <= tall + 4     # … up to a few lines, then scrolls
    box.setText('y' * (INPUT_LIMIT + 50))
    assert len(box.text()) == INPUT_LIMIT
    typed.clear()
    box.clear()
    assert typed == [] and box.text() == ''


def test_the_card_keeps_line_breaks_and_shows_a_short_bubble(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat
    from twobyteasr.app.bunny_chat import BUBBLE_CHARS, NOTICE_KEY, bubble_text
    from twobyteasr.app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{NOTICE_KEY: True}))
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek'))
    window = QWidget()
    window.resize(1100, 720)
    window.help_button = QPushButton('说明', window)
    window.show()
    chat = bunny_chat.open_bunny_chat(window)
    try:
        assert isinstance(chat.input, bunny_chat.ChatInput)
        assert chat.input.geometry().width() > chat.send_button.geometry().width() * 6     # the input has its own row
        assert chat.send_button.geometry().top() > chat.input.geometry().bottom() - 2       # buttons below it
        asked = []
        monkeypatch.setattr(chat, '_ask', lambda question, **_extra: asked.append(question))
        paste = '{\n  "status": "failed",   \n  "error": "' + '很长' * 400 + '"\n}\n'
        chat.input.setText(paste)
        chat.send()
        assert asked and asked[0].startswith('{\n  "status": "failed",\n  "error"') and asked[0].endswith('"\n}')
        assert chat.transcript[-1] == ('user', asked[0])                                      # kept whole
        short = bubble_text(asked[0])
        assert len(short) < len(asked[0]) and short.startswith(asked[0][:BUBBLE_CHARS]) and '已完整发给兔白' in short
        assert chat._user_html('a\nb') == 'a<br>b'
    finally:
        chat.close_chat()
        window.close()
