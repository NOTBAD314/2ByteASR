"""兔白 reads the evidence herself and answers in bounded time (2026-11-22).

User: one knowledge entry per reported problem does not make her smarter. Generic fixes: what the
windows say goes with every question, recent exports can be looked up, a question has a time
budget and the thinking row says what she is doing, and the prompt asks for evidence-based answers.
"""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_screen_reading_keeps_warnings_reasons_and_progress_only(app):
    from PySide6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton, QVBoxLayout, QWidget
    from twobyteasr.app.bunny_screen import read_screen
    window = QWidget()
    layout = QVBoxLayout(window)
    for text in ('入点必须早于出点，不能导出零时长或反向范围。', '欢迎回来', '找不到 C:\\Users\\me\\Videos\\直播.mp4',
                 '这句不能删'):
        layout.addWidget(QLabel(text))
    grey = QPushButton('导出')
    grey.setEnabled(False)
    grey.setToolTip('先设好输出文件夹')
    layout.addWidget(grey)
    plain_grey = QPushButton('下一步')
    plain_grey.setEnabled(False)
    layout.addWidget(plain_grey)
    bar = QProgressBar()
    bar.setRange(0, 200)
    bar.setValue(50)
    layout.addWidget(bar)
    rows = QListWidget()
    rows.addItem('列表里失败的那一行')
    layout.addWidget(rows)
    hidden = QLabel('不能显示我')
    layout.addWidget(hidden)
    project = SimpleNamespace(cues=[SimpleNamespace(text='这句不能删')])
    window.built_page = lambda name: SimpleNamespace(project=project) if name == 'studio' else None
    window.show()
    hidden.hide()
    app.processEvents()
    try:
        text = read_screen(window)
    finally:
        window.close()
    assert '写着：入点必须早于出点，不能导出零时长或反向范围。' in text
    assert '「导出」是灰的：先设好输出文件夹' in text and '下一步' not in text
    assert '进度条 25%' in text
    assert '…\\直播.mp4' in text and 'Users' not in text           # a path becomes its last part
    assert '欢迎回来' not in text and '这句不能删' not in text and '不能显示我' not in text
    assert '列表里' not in text                                      # rows may hold subtitle text


def test_app_state_carries_the_screen_only_with_permission(app, monkeypatch):
    from twobyteasr.app import bunny_chat, bunny_permissions, bunny_screen
    monkeypatch.setattr(bunny_chat, 'current_page', lambda _window: '首页')
    monkeypatch.setattr(bunny_screen, 'read_screen', lambda _window: '写着：转换失败')
    window = SimpleNamespace(built_page=lambda _name: None)
    monkeypatch.setattr(bunny_permissions, 'load', lambda: dict(bunny_permissions.DEFAULTS, read_diagnostics=True))
    assert bunny_chat.app_state(window, True).get('screen') == '写着：转换失败'
    monkeypatch.setattr(bunny_permissions, 'load', lambda: dict(bunny_permissions.DEFAULTS, read_diagnostics=False))
    assert 'screen' not in bunny_chat.app_state(window, True)
    from twobyteasr.app.bunny_persona import format_state
    assert format_state({'screen': '写着：转换失败'}) == '- 屏幕上的提示：写着：转换失败'


def _manifest(root, name, data, age):
    folder = root / name / 'run'
    folder.mkdir(parents=True)
    path = folder / 'manifest.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


def test_recent_exports_can_be_looked_up(tmp_path, monkeypatch):
    from twobyteasr.app import bunny_lookup, bunny_permissions
    from twobyteasr.app.bunny_tools import BACKGROUND, TOOLS
    monkeypatch.setenv('TWOBYTEASR_EXPORT_LOG_ROOT', str(tmp_path))
    assert '没有找到视频导出的记录' in bunny_lookup.exports_summary()
    settings = {'encoder': 'h264_nvenc', 'container': 'mp4', 'width': 1920, 'height': 1080}
    _manifest(tmp_path, 'a', {'settings': settings, 'published': True,
                              'output_path': 'C:\\Users\\me\\out.mp4'}, age=300)
    _manifest(tmp_path, 'b', {'settings': settings, 'published': False, 'failure': {
        'stage': 'encode', 'message': '显卡编码器不可用（-40）\n\nTraceback…'}}, age=100)
    _manifest(tmp_path, 'c', {'settings': settings, 'published': False}, age=10)
    text = bunny_lookup.run_check('exports')
    lines = text.splitlines()
    assert len(lines) == 3
    assert '没有结束记录' in lines[0]
    assert '失败，停在「视频编码」：显卡编码器不可用（-40）' in lines[1] and 'Traceback' not in lines[1]
    assert lines[2].endswith('mp4，1920×1080，请求的编码器 ?') and '成功' in lines[2]
    assert 'Users' not in text                                       # never a path
    assert 'exports' in BACKGROUND and TOOLS['exports'].background
    assert bunny_permissions.refusal(TOOLS['exports'], dict(bunny_permissions.DEFAULTS, read_diagnostics=False))


def test_a_question_has_a_time_budget():
    from twobyteasr.app.bunny_chat import QUESTION_SECONDS, BunnyChat
    chat = SimpleNamespace(_sub=None, _task_mode=False, _ui_mode=False, _asked_at=time.monotonic())
    chat._time_budget = lambda: BunnyChat._time_budget(chat)
    assert BunnyChat._time_budget(chat) == QUESTION_SECONDS['plain']
    assert BunnyChat._time_left(chat) > QUESTION_SECONDS['plain'] - 5
    chat._asked_at = time.monotonic() - QUESTION_SECONDS['plain'] - 1
    assert BunnyChat._time_left(chat) < 0                            # out of time: answer from what she has
    chat._ui_mode = True
    assert BunnyChat._time_left(chat) > 0                            # working the screen gets longer
    chat._task_mode = True
    assert BunnyChat._time_budget(chat) == QUESTION_SECONDS['task']


def test_the_thinking_row_says_what_she_is_doing():
    from twobyteasr.app.bunny_chat import BunnyChat, TOOL_WORDS
    label = SimpleNamespace(text='', setText=lambda value: setattr(label, 'text', value))
    chat = SimpleNamespace(mode='dialog', box=SimpleNamespace(label=label), _sub_status='',
                           _work_status='正在查导出记录', _asked_at=time.monotonic())
    BunnyChat._think_tick(chat)
    assert label.text.startswith('正在查导出记录  ·')
    chat._asked_at = time.monotonic() - 40
    BunnyChat._think_tick(chat)
    assert label.text.startswith('正在查导出记录（40 秒）') or label.text.startswith('正在查导出记录（41 秒）')
    chat._work_status = ''
    BunnyChat._think_tick(chat)
    assert label.text.startswith('还在想（')
    assert TOOL_WORDS['exports'] == '查导出记录'


def test_the_prompt_asks_for_evidence_and_a_bounded_search():
    from twobyteasr.app import bunny_persona
    rules = bunny_persona.RULES
    assert '排查问题' in rules and '先读证据' in rules and '屏幕上的提示' in rules
    assert '先怀疑' in rules and '依据' in rules and '查了两轮还没有新线索' in rules
    assert '依据' in bunny_persona.ROUNDS_DONE and 'tools' in bunny_persona.ROUNDS_DONE


def test_the_language_pass_does_not_raise_on_the_save_prompt(app):
    """Found by the bunny eval run (2026-11-22): SaveChangesDialog has informativeText() but no setter."""
    from twobyteasr.i18n_widgets import apply
    from twobyteasr.projects.save_changes_dialog import SaveChangesDialog
    dialog = SaveChangesDialog(None, '退出应用', '第3集')
    try:
        apply(dialog, 'zh-Hant')
        apply(dialog, 'zh', visible_only=False)
    finally:
        dialog.deleteLater()
