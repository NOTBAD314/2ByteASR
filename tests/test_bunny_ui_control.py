"""兔白's universal control layer (2026-11-17): see every control, press, set, run registered commands,
with the risk judged per call and undo records."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ASK = {'level': 'ask', 'read_subtitles': True, 'read_diagnostics': True, 'remember': True, 'allow_paid': False,
       'keep_chat': True, 'see_screen': False}
AUTO = dict(ASK, level='auto')


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(app):
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                                   QTabWidget, QVBoxLayout, QWidget)
    window = QWidget()
    window.resize(700, 500)
    outer = QVBoxLayout(window)
    tabs = QTabWidget()
    tabs.addTab(QWidget(), '常规')
    tabs.addTab(QWidget(), '字幕样式')
    outer.addWidget(tabs)
    form_host = QWidget()
    form = QFormLayout(form_host)
    window.show_names = QCheckBox('字幕前显示名字')
    window.color = QComboBox()
    window.color.addItems(['白色', '黄色', '青色'])
    window.size_box = QSpinBox()
    window.size_box.setRange(10, 120)
    window.size_box.setValue(48)
    window.search = QLineEdit()
    window.search.setPlaceholderText('搜索工程…')
    window.key_box = QLineEdit()
    window.key_box.setEchoMode(QLineEdit.EchoMode.Password)
    window.key_box.setText('sk-secret-123')
    form.addRow('描边颜色', window.color)
    form.addRow('字号', window.size_box)
    form.addRow('API Key', window.key_box)
    for widget in (window.show_names, window.search):
        form.addRow(widget)
    outer.addWidget(form_host)
    window.pressed = []
    window.go = QPushButton('打开识别记录')
    window.go.clicked.connect(lambda: window.pressed.append('go'))
    window.remove = QPushButton('删除工程')
    window.remove.clicked.connect(lambda: window.pressed.append('remove'))
    window.grey = QPushButton('开始生成字幕')
    window.grey.setEnabled(False)
    window.grey.setToolTip('先选择素材')
    for widget in (window.go, window.remove, window.grey):
        outer.addWidget(widget)
    card = QLabel('兔白的聊天', window)                # her own card is never part of the picture
    card.setObjectName('bunnyChat')
    QPushButton('兔白卡片上的按钮', card)
    window.tabs = tabs
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _ref(listing, words):
    line = next(row for row in listing.splitlines() if words in row)
    return line.split()[0]


def test_the_snapshot_shows_every_control_with_refs_values_and_state(screen):
    from twobyteasr.app.bunny_tools import run_turn
    listing = run_turn(screen, [('ui_snapshot', {})], None).receipts[0]
    assert '成功' in listing
    for words in ('页签「常规」（当前）', '页签「字幕样式」', '勾选「字幕前显示名字」 没勾', '下拉「描边颜色」 现在：白色；选项：白色 / 黄色 / 青色',
                  '数字「字号」 48（10–120）', '文字框「搜索工程…」（空）', '按钮「打开识别记录」', '按钮「删除工程」',
                  '按钮「开始生成字幕」（灰的：先选择素材）'):
        assert words in listing, words
    assert '兔白卡片' not in listing                                   # never her own card
    assert 'sk-secret' not in listing and '（密码类，不显示）' in listing
    narrowed = run_turn(screen, [('ui_snapshot', {'text': '字号'})], None).receipts[0]
    assert '字号' in narrowed and '删除工程' not in narrowed


def test_an_open_dialog_comes_first_and_is_listed_once(app, screen):
    """Live run 2026-11-17: the settings dialog (a child of the main window) was listed twice, after the main window."""
    from PySide6.QtWidgets import QDialog, QPushButton, QVBoxLayout
    from twobyteasr.app.bunny_tools import run_turn
    dialog = QDialog(screen)
    dialog.setWindowTitle('应用设置')
    QVBoxLayout(dialog).addWidget(QPushButton('保存更改'))
    dialog.show()
    app.processEvents()
    try:
        listing = run_turn(screen, [('ui_snapshot', {})], None).receipts[0]
        assert listing.count('保存更改') == 1
        assert listing.index('【应用设置】') < listing.index('【主窗口】')
        only = run_turn(screen, [('ui_snapshot', {'window': '应用设置'})], None).receipts[0]
        assert '保存更改' in only and '删除工程' not in only
    finally:
        dialog.close()


def test_a_press_happens_a_moment_later_and_tabs_switch(app, screen):
    from twobyteasr.app.bunny_tools import run_turn
    listing = run_turn(screen, [('ui_snapshot', {})], None).receipts[0]
    done = run_turn(screen, [('ui_press', {'ref': _ref(listing, '打开识别记录')})], ASK).receipts[0]
    assert '成功' in done and '下一轮' in done and screen.pressed == []    # not inside her turn
    app.processEvents()
    assert screen.pressed == ['go']
    by_name = run_turn(screen, [('ui_press', {'text': '字幕样式'})], ASK).receipts[0]
    assert '切到了「字幕样式」页签' in by_name and screen.tabs.currentIndex() == 1
    grey = run_turn(screen, [('ui_press', {'text': '开始生成字幕'})], AUTO).receipts[0]
    assert '没做成' in grey and '灰的' in grey and '先选择素材' in grey
    stale = run_turn(screen, [('ui_press', {'ref': 'e999'})], ASK).receipts[0]
    assert '过期' in stale


def test_risk_is_judged_per_call(app, screen):
    from twobyteasr.app.bunny_tools import pending_summary, run_turn
    result = run_turn(screen, [('ui_press', {'text': '删除工程'})], AUTO)          # even "do undoable edits"
    assert result.pending[0][0] == 'ui_press' and result.pending[0][1]['text'] == '删除工程'
    assert result.pending[0][1]['ref'].startswith('e') and '帮我做' in result.receipts[0]
    app.processEvents()
    assert screen.pressed == []
    assert pending_summary(result.pending) == '按「删除工程」'
    confirmed = run_turn(screen, result.pending, AUTO, confirmed=True)
    app.processEvents()
    assert '成功' in confirmed.receipts[0] and screen.pressed == ['remove']
    guided = run_turn(screen, [('ui_press', {'text': '打开识别记录'})], dict(ASK, level='guide')).receipts[0]
    assert '只指路' in guided
    search = run_turn(screen, [('ui_set', {'text': '搜索工程', 'value': '日常'})], ASK)
    assert not search.pending and '成功' in search.receipts[0]           # a search box never asks
    setting = run_turn(screen, [('ui_set', {'text': '描边颜色', 'value': '黄色'})], ASK)
    assert setting.pending and screen.color.currentText() == '白色'      # a setting follows 「兔白权限」


def test_set_reports_before_after_and_undoes(screen):
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    result = run_turn(screen, [('ui_set', {'text': '描边颜色', 'value': '黄'}),
                               ('ui_set', {'text': '字号', 'value': 60}),
                               ('ui_set', {'text': '字幕前显示名字', 'value': True})], AUTO)
    assert '从 白色 改成了 黄色' in result.receipts[0] and '从 48 改成了 60' in result.receipts[1]
    assert '从 没勾 改成了 勾着' in result.receipts[2]
    assert screen.color.currentText() == '黄色' and screen.size_box.value() == 60 and screen.show_names.isChecked()
    assert len(result.undo) == 3
    undone, why = undo_records(result.undo)
    assert undone == 3 and not why
    assert screen.color.currentText() == '白色' and screen.size_box.value() == 48 and not screen.show_names.isChecked()
    wrong = run_turn(screen, [('ui_set', {'text': '字号', 'value': 500})], AUTO).receipts[0]
    assert '10–120' in wrong
    missing = run_turn(screen, [('ui_set', {'text': '描边颜色', 'value': '紫色'})], AUTO).receipts[0]
    assert '没有「紫色」' in missing and '黄色' in missing
    secret = run_turn(screen, [('ui_set', {'text': 'API Key', 'value': 'x'})], AUTO).receipts[0]
    assert '不碰' in secret and screen.key_box.text() == 'sk-secret-123'
    later = run_turn(screen, [('ui_set', {'text': '字号', 'value': 70})], AUTO)
    screen.size_box.setValue(72)                                        # the user changed it afterwards
    assert undo_records(later.undo)[1] and screen.size_box.value() == 72


def test_registered_workbench_commands_run_with_undo_and_risk(app, monkeypatch):
    from PySide6.QtGui import QUndoCommand, QUndoStack
    from twobyteasr.app import bunny_chat
    from twobyteasr.app.bunny_tools import TOOLS, resolve, run_turn, undo_records
    monkeypatch.setattr(bunny_chat, 'current_page', lambda _window: '字幕工作台')
    stack = QUndoStack()
    done = []

    def split():
        stack.push(QUndoCommand('拆分'))
        done.append('split')
    page = SimpleNamespace(project=object(), undo_stack=stack, _review_mode=False,
                           _command_callbacks={'split': split, 'delete': lambda: done.append('delete'),
                                               'translate_selected': lambda: done.append('translate'),
                                               'next_cue': lambda: done.append('next')})
    window = SimpleNamespace(built_page=lambda name: page if name == 'studio' else None)
    result = run_turn(window, [('run_command', {'id': 'split'})], AUTO)
    assert '做了「拆分当前字幕」（1 步，可以撤销）' in result.receipts[0] and done == ['split']
    assert undo_records(result.undo) == (1, '') and stack.index() == 0
    asked = run_turn(window, [('run_command', {'id': 'split'})], ASK)
    assert asked.pending and done == ['split']                           # an edit follows 「兔白权限」
    assert run_turn(window, [('run_command', {'id': 'next_cue'})], ASK).receipts[0].startswith('- run_command(id=next_cue)：成功')
    assert run_turn(window, [('run_command', {'id': 'delete'})], AUTO).pending      # deleting always asks
    paid = resolve(TOOLS['run_command'], window, {'id': 'translate_selected'})
    assert paid.paid and run_turn(window, [('run_command', {'id': 'translate_selected'})], AUTO).pending
    review = run_turn(window, [('run_command', {'id': 'confirm_review'})], AUTO).receipts[0]
    assert '审核模式' in review
    unknown = run_turn(window, [('run_command', {'id': 'fly'})], AUTO).receipts[0]
    assert 'list_commands' in unknown
    listing = run_turn(window, [('list_commands', {'text': '审核'})], None).receipts[0]
    assert 'confirm_review：确认当前审核' in listing and 'reasr_review：重新识别当前审核【花 Key】' in listing
    assert 'split：' not in listing


def test_home_and_global_commands_fire_their_shortcut(app, monkeypatch):
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_chat
    from twobyteasr.app.bunny_tools import run_turn
    monkeypatch.setattr(bunny_chat, 'current_page', lambda _window: '首页')
    window = QWidget()
    window.show()
    fired = []
    settings = QShortcut(QKeySequence('Ctrl+,'), window)
    settings.activated.connect(lambda: fired.append('settings'))
    try:
        done = run_turn(window, [('run_command', {'id': 'app.open_settings'})], ASK).receipts[0]
        assert '打开了' in done and fired == []
        app.processEvents()
        assert fired == ['settings']
        missing = run_turn(window, [('run_command', {'id': 'home.search'})], ASK).receipts[0]
        assert '接不到' in missing
    finally:
        window.close()


def test_list_items_show_and_can_be_picked(app, screen):
    """2026-11-17 eval: the settings window's navigation is a list; she could not see or pick its pages."""
    from PySide6.QtWidgets import QListWidget
    from twobyteasr.app.bunny_tools import run_turn
    pages = QListWidget(screen)
    pages.addItems(['工程与保存', '外观', '快捷键'])
    pages.setCurrentRow(0)
    picked = []
    pages.currentRowChanged.connect(picked.append)
    screen.layout().addWidget(pages)
    pages.show()
    app.processEvents()
    listing = run_turn(screen, [('ui_snapshot', {'text': '快捷键'})], None).receipts[0]
    assert '列表项「快捷键」' in listing
    done = run_turn(screen, [('ui_press', {'text': '快捷键'})], dict(ASK, level='ask'))
    assert not done.pending and '选中了列表里的「快捷键」' in done.receipts[0]
    assert pages.currentRow() == 2 and picked == [2]
    assert '列表项「快捷键」（当前）' in run_turn(screen, [('ui_snapshot', {'text': '快捷键'})], None).receipts[0]


def test_a_command_can_be_named_by_its_key(app, monkeypatch):
    """2026-11-17 eval: she knew Ctrl+= from the manual and only told the user to press it."""
    from twobyteasr.app.bunny_tools import TOOLS, pending_summary, resolve
    from twobyteasr.app.bunny_ui_control import _action
    assert _action({'key': 'Ctrl+='}).id == 'app.zoom_in'
    assert _action({'key': 'ctrl+shift+s'}).id == 'split'
    with pytest.raises(Exception):
        _action({'key': 'Ctrl+Alt+Shift+F12'})
    assert resolve(TOOLS['run_command'], None, {'key': 'Delete'}).persistent      # deleting asks, by key too
    assert pending_summary([('run_command', {'key': 'Ctrl+Shift+S'})]) == '执行「拆分当前字幕」'


def test_words_of_doing_without_a_tool_are_caught():
    """2026-11-17 eval: "好～兔白先去把「快捷键」那一页打开，然后找找搜索框" and no tools: nothing happened."""
    from twobyteasr.app.bunny_persona import BunnyReply, promised_without_doing
    said = BunnyReply(lines=['好～兔白先去把「快捷键」那一页打开。', '然后找找搜索框。'])
    assert promised_without_doing('打开快捷键设置，在搜索框里帮我搜「拆分」', said)
    assert not promised_without_doing('打开快捷键设置', BunnyReply(lines=['我来弄～'], tools=(('open_place', {}),)))
    assert not promised_without_doing('快捷键怎么改？', BunnyReply(lines=['我来教你：先打开设置。']))
    assert not promised_without_doing('今天好累', BunnyReply(lines=['辛苦啦，我陪你聊聊～']))
    assert not promised_without_doing('帮我改成深色', BunnyReply(lines=['我来帮你改～'], do=('set_theme', 'dark')))


def test_deepseeks_native_parameter_calls_are_understood():
    """Live run 2026-11-17: deep thinking wrote <｜DSML｜invoke …><｜DSML｜parameter name="ref">e15</…> instead of JSON."""
    from twobyteasr.app.bunny_persona import native_tool_calls, parse_reply
    cut = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="ui_press">\n<｜｜DSML｜｜ parameter name="ref">e15</｜｜DSML｜｜ parameter>\n'
    assert parse_reply(cut, []).tools == (('ui_press', {'ref': 'e15'}),)
    two = ('<｜DSML｜function_calls><｜DSML｜invoke name="ui_set"><｜DSML｜parameter name="ref" string="true">e14</｜DSML｜parameter>'
           '<｜DSML｜parameter name="value" string="false">true</｜DSML｜parameter></｜DSML｜invoke><｜DSML｜invoke name="ui_press">'
           '<｜DSML｜parameter name="ref" string="true">e15</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜function_calls>')
    assert native_tool_calls(two) == [{'name': 'ui_set', 'args': {'ref': 'e14', 'value': True}},
                                      {'name': 'ui_press', 'args': {'ref': 'e15'}}]
    old = '<｜DSML｜ invoke name="tools">[{"name": "look", "args": {}}]</｜DSML｜ invoke>'
    assert native_tool_calls(old) == [{'name': 'look', 'args': {}}]


def test_the_prompt_teaches_look_act_verify():
    from twobyteasr.app import bunny_persona
    prompt = bunny_persona.system_prompt([])
    for words in ('ui_snapshot', 'ui_press', 'ui_set', 'run_command', 'list_commands', '看 → 做 → 验证'):
        assert words in prompt, words


def test_pending_control_cannot_retarget_after_a_new_snapshot(app, screen):
    from twobyteasr.app.bunny_tools import run_turn
    pending = run_turn(screen, [('ui_press', {'text': '删除工程'})], AUTO).pending
    old_ref = pending[0][1]['ref']
    listing = run_turn(screen, [('ui_snapshot', {})], AUTO).receipts[0]
    assert _ref(listing, '删除工程') != old_ref
    result = run_turn(screen, pending, AUTO, confirmed=True)
    app.processEvents()
    assert '过期' in result.receipts[0] and screen.pressed == []


def test_new_tools_obey_closed_read_permissions(screen, monkeypatch):
    from twobyteasr.app.bunny_tools import run_turn
    from twobyteasr.app import bunny_nav_tools
    monkeypatch.setattr(bunny_nav_tools, 'result_records', lambda *_a: pytest.fail('must not read records'))
    closed = dict(AUTO, read_subtitles=False, read_diagnostics=False)
    for name, args in [('ui_snapshot', {}), ('ui_set', {'text': '字号', 'value': 60}),
                       ('recent_results', {}), ('open_result', {}), ('recent_projects', {}), ('open_project', {})]:
        result = run_turn(screen, [(name, args)], closed)
        assert '关掉了' in result.receipts[0] and not result.pending
    assert screen.size_box.value() == 48


def test_duplicate_buttons_require_a_ref_and_radio_undo_restores_group(app, screen):
    from PySide6.QtWidgets import QPushButton, QRadioButton
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    duplicate = QPushButton('打开识别记录', screen)
    duplicate.setGeometry(500, 20, 150, 30)
    duplicate.show()
    result = run_turn(screen, [('ui_press', {'text': '打开识别记录'})], AUTO)
    assert '好几个' in result.receipts[0] and screen.pressed == []
    first = QRadioButton('一分钟', screen)
    second = QRadioButton('五分钟', screen)
    first.setGeometry(500, 60, 150, 30);second.setGeometry(500, 100, 150, 30)
    first.show();second.show();first.setChecked(True)
    app.processEvents()
    changed = run_turn(screen, [('ui_set', {'text': '五分钟', 'value': True})], AUTO)
    assert second.isChecked() and changed.undo
    assert undo_records(changed.undo) == (1, '') and first.isChecked()
