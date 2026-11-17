"""Harness phase 2 (2026-11-17): tool search, an action log she can read and replay, windows that
open mid-turn, and the 「帮我做」 note while a dialog blocks her card."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

AUTO = {'level': 'auto', 'read_subtitles': True, 'read_diagnostics': True, 'remember': True, 'allow_paid': False,
        'keep_chat': True, 'see_screen': False}


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_log():
    from twobyteasr.app import bunny_audit, bunny_permissions
    bunny_permissions.save({'remember': True})
    bunny_audit.clear()
    yield
    bunny_audit.clear()
    bunny_audit.current_question = ''


def test_tool_search_lists_rare_tools_by_name_and_explains_them_on_request():
    from twobyteasr.app.bunny_tools import COMPACT, TOOLS, describe_for_prompt, run_turn
    prompt = describe_for_prompt()
    assert '更多工具' in prompt and '- propose_change：' in prompt
    assert TOOLS['propose_change'].args not in prompt                     # the long usage only on request
    assert '- ui_snapshot {' in prompt and '- tool_help {' in prompt         # everyday tools stay whole
    assert all(name in TOOLS for name in COMPACT)
    helped = run_turn(None, [('tool_help', {'names': ['propose_change', 'change_terms']})], None).receipts[0]
    assert TOOLS['propose_change'].args in helped and TOOLS['change_terms'].args in helped
    found = run_turn(None, [('tool_help', {'text': '术语'})], None).receipts[0]
    assert 'change_terms' in found and 'term_update' in found
    assert '没有找到' in run_turn(None, [('tool_help', {'text': '飞上月球'})], None).receipts[0]


def test_every_move_change_and_spend_goes_to_her_action_log(app):
    from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget
    from twobyteasr.app import bunny_audit
    from twobyteasr.app.bunny_tools import run_turn
    window = QWidget()
    QVBoxLayout(window).addWidget(QCheckBox('字幕前显示名字'))
    window.show()
    app.processEvents()
    try:
        bunny_audit.current_question = '帮我把名字显示出来'
        run_turn(window, [('ui_snapshot', {}), ('ui_set', {'text': '字幕前显示名字', 'value': True}),
                          ('ui_set', {'text': '没有这个', 'value': 1})], AUTO)
        rows = bunny_audit.read()
        assert [row['tool'] for row in rows] == ['ui_set', 'ui_set']           # reads are not logged
        assert rows[0]['outcome'] == 'ok' and rows[1]['outcome'] == 'failed'
        assert rows[0]['question'] == '帮我把名字显示出来' and rows[0]['args'] == {'text': '字幕前显示名字', 'value': True}
        listing = run_turn(window, [('recent_actions', {})], None).receipts[0]
        assert '#1' in listing and 'ui_set(text=字幕前显示名字, value=True) → 做成了' in listing and '没做成' in listing
        again = run_turn(window, [('replay_action', {'id': 1})], None).receipts[0]
        assert '"name": "ui_set"' in again and '「兔白权限」' in again
    finally:
        window.close()


def test_the_log_keeps_no_secrets_no_stale_refs_and_respects_the_switch():
    from twobyteasr.app import bunny_audit, bunny_permissions
    from twobyteasr.app.bunny_tools import run_turn
    bunny_audit.record('ui_set', {'api_key': 'sk-123', 'text': 'x' * 300}, '- ui_set：成功。')
    bunny_audit.record('ui_press', {'ref': 'e12'}, '- ui_press：成功。')
    rows = bunny_audit.read()
    assert rows[0]['args']['api_key'] == '***' and rows[0]['args']['text'].endswith('…')
    assert 'sk-123' not in bunny_audit.log_path().read_text('utf-8')
    assert '没法原样重做' in run_turn(None, [('replay_action', {'id': 1})], None).receipts[0]
    assert '编号已经过期' in run_turn(None, [('replay_action', {'id': 2})], None).receipts[0]
    bunny_permissions.save({'remember': False})
    bunny_audit.record('ui_press', {'text': '保存'}, '- ui_press：成功。')
    assert len(bunny_audit.read()) == 2
    assert '关掉了' in run_turn(None, [('recent_actions', {})], None).receipts[0]


def test_a_pending_step_says_when_a_dialog_blocks_the_button(app):
    from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget
    from twobyteasr.app.bunny_tools import run_turn
    window = QWidget()
    window.show()
    dialog = QDialog(window)
    dialog.setWindowTitle('应用设置')
    QVBoxLayout(dialog).addWidget(QPushButton('全部恢复默认'))
    dialog.setModal(True)
    dialog.show()
    app.processEvents()
    try:
        result = run_turn(window, [('ui_press', {'text': '全部恢复默认'})], AUTO)
        assert result.pending and '「应用设置」窗口开着' in result.receipts[0] and '按不到「帮我做」' in result.receipts[0]
    finally:
        dialog.close()
        window.close()


def test_windows_she_opens_appear_before_her_next_round(app, monkeypatch):
    """Before: open_place waited for her last words, so "open settings, change X, save" stopped at step one."""
    from PySide6.QtWidgets import QPushButton, QWidget
    from twobyteasr.app import bunny_chat, bunny_permissions, bunny_tools
    from twobyteasr.app.bunny_chat import NOTICE_KEY, OPEN_MID_TURN
    from twobyteasr.app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{NOTICE_KEY: True}))
    bunny_permissions.save({'level': 'ask'})
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_chat, 'ai_readiness', lambda settings: (True, 'DeepSeek'))
    opened = []
    monkeypatch.setattr(bunny_tools, 'run_later', lambda window, name, args: opened.append(name))
    window = QWidget()
    window.help_button = QPushButton('说明', window)
    window.show()
    chat = bunny_chat.open_bunny_chat(window)
    try:
        assert {'open_place', 'open_window', 'open_project'} <= OPEN_MID_TURN
        chat._ask = lambda question: None
        chat._generation, chat._question, chat._turn_messages = 1, '打开快捷键设置', []
        chat._pending_edits, chat._undo_batch, chat._later, chat._tool_rounds = [], [], [], 0
        sent = []
        monkeypatch.setattr(chat, '_start_worker', lambda messages, **extra: sent.append(messages))
        reply = bunny_chat.bunny_persona.BunnyReply(lines=['我来弄～'], tools=(('open_place', {'key': 'shortcuts'}),))
        chat._run_tools(reply, {'role': 'assistant', 'content': '{}'})
        assert sent and not chat._later                  # the next request went out, nothing left for "after"
        deadline = __import__('time').monotonic() + 3
        while not opened and __import__('time').monotonic() < deadline:
            app.processEvents()
        assert opened == ['open_place']                    # opened while her next request is on its way
    finally:
        chat.close_chat()
        window.close()
