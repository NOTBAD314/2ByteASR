"""「我的改动」 (2026-11-16): the user's own changes live in the user data folder, survive updates,
can be listed, switched off and taken back, and are never dropped silently."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

SCRIPT = '''API_VERSION = 1

def setup(api):
    api.window.setProperty('userScriptRan', api.script_id)
    api.log('hello')
'''


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path / 'data'))
    from twobyteasr import i18n
    yield tmp_path / 'data'
    i18n.set_user_texts({})


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_changes_live_in_the_user_data_folder_and_can_be_switched_off_and_removed(data_root):
    from twobyteasr.app import user_overlay
    assert user_overlay.root() == data_root / '2ByteASR' / 'user-overlay'
    entry, snapshot = user_overlay.add('style', '#bunnyChatSend', 'font-size: 16px; color: #333333', by='bunny',
                                       note='发送按钮太小', app_version='0.9.7 abc')
    assert entry['id'] == 'u1' and entry['enabled'] and entry['value'] == 'font-size: 16px; color: #333333;'
    assert (user_overlay.store_path()).is_file() and snapshot
    assert user_overlay.styles() == {'bunnyChatSend': [('u1', '#bunnyChatSend', 'font-size: 16px; color: #333333;')]}
    user_overlay.set_enabled('u1', False)
    assert user_overlay.styles() == {} and user_overlay.find('u1')['enabled'] is False
    user_overlay.add('text', '保存更改', '存起来')
    user_overlay.add('note', '', '回答简短一点')
    assert user_overlay.text_overrides() == {'保存更改': '存起来'} and user_overlay.notes() == ['回答简短一点']
    removed = user_overlay.remove('u2')
    assert removed['kind'] == 'text' and user_overlay.text_overrides() == {}
    assert '兔白' in user_overlay.describe(user_overlay.find('u1')) and '关着' in user_overlay.describe(user_overlay.find('u1'))


def test_bad_changes_are_refused_in_plain_words():
    from twobyteasr.app import user_overlay
    with pytest.raises(user_overlay.OverlayError, match='控件名'):
        user_overlay.add('style', 'QWidget', 'color: red')
    with pytest.raises(user_overlay.OverlayError, match='属性: 值'):
        user_overlay.add('style', '#x', 'color red')
    with pytest.raises(user_overlay.OverlayError, match='引用文件'):
        user_overlay.add('style', '#x', 'background: url(c:/evil.png)')
    with pytest.raises(user_overlay.OverlayError):
        user_overlay.add('style', '#x', 'color: red } QWidget { color: blue')
    with pytest.raises(user_overlay.OverlayError, match='API_VERSION'):
        user_overlay.add('script', '', '做点事', code='def setup(api):\n    pass\n')
    with pytest.raises(user_overlay.OverlayError, match='语法错误'):
        user_overlay.add('script', '', '做点事', code='API_VERSION = 1\ndef setup(api)\n')
    with pytest.raises(user_overlay.OverlayError, match='不认识'):
        user_overlay.add('python', '', 'x')
    assert user_overlay.entries() == []


def test_a_script_bunny_wrote_waits_switched_off_and_everything_can_go_back():
    from twobyteasr.app import user_overlay
    mine, _ = user_overlay.add('script', '', '我的脚本', code=SCRIPT)
    hers, before_hers = user_overlay.add('script', '', '兔白写的', code=SCRIPT, by='bunny')
    assert mine['enabled'] and not hers['enabled']
    assert user_overlay.script_path(hers).read_text('utf-8') == SCRIPT
    user_overlay.remove(hers['id'])
    assert not user_overlay.script_path(hers).exists()
    back = user_overlay.restore(before_hers)          # before her script was added
    assert [entry['id'] for entry in back['entries']] == [mine['id']]
    snapshot = user_overlay.snapshots()[0]['id']      # restoring kept the state before it
    user_overlay.restore(snapshot)
    assert user_overlay.find(mine['id']) is not None
    new, _ = user_overlay.add('note', '', '再加一条')
    assert new['id'] not in (mine['id'], hers['id'])  # ids never come back
    assert all(row['reason'] for row in user_overlay.snapshots())


def test_a_newer_change_of_the_same_control_wins_and_the_older_one_stays_off():
    from twobyteasr.app import user_overlay
    user_overlay.add('style', '#startButton', 'font-size: 14px')
    user_overlay.add('style', '#startButton', 'font-size: 18px')
    rows = user_overlay.entries('style')
    assert [row['enabled'] for row in rows] == [False, True]
    assert user_overlay.styles()['startButton'][0][2] == 'font-size: 18px;'


def test_history_is_numerically_ordered_when_many_changes_share_one_second(monkeypatch):
    from twobyteasr.app import user_overlay
    monkeypatch.setattr(user_overlay.time, 'strftime', lambda _fmt: '20261116-120000')
    for index in range(14):
        user_overlay.add('note', '', f'第{index}条')
    assert user_overlay.snapshots()[0]['id'].endswith('-r13')


def test_restoring_oldest_retained_snapshot_preserves_its_scripts(monkeypatch):
    from twobyteasr.app import user_overlay
    monkeypatch.setattr(user_overlay, 'HISTORY_KEEP', 3)
    entry, _ = user_overlay.add('script', '', '我的脚本', code=SCRIPT)
    for index in range(3):
        user_overlay.add('note', '', f'第{index}条')
    user_overlay.remove(entry['id'])
    oldest = user_overlay.snapshots()[-1]['id']
    user_overlay.restore(oldest)
    assert user_overlay.find(entry['id']) is not None
    assert user_overlay.script_path(entry).read_text('utf8') == SCRIPT


def test_script_timers_stop_when_script_or_global_permission_is_disabled(app):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import user_overlay, user_overlay_runtime
    window = QWidget()
    code = ('API_VERSION = 1\ndef setup(api):\n'
            '    api.every(50, lambda: api.window.setProperty("ticks", (api.window.property("ticks") or 0) + 1))\n')
    entry, _ = user_overlay.add('script', '', '计数', code=code)
    user_overlay.set_scripts_allowed(True)
    runtime = user_overlay_runtime.install(app, safe=False)
    runtime.after_window(window, show_notices=False)
    QTest.qWait(140)
    first = window.property('ticks')
    assert first > 0
    user_overlay.set_enabled(entry['id'], False)
    runtime.reapply()
    QTest.qWait(140)
    assert window.property('ticks') == first
    user_overlay.set_enabled(entry['id'], True)
    runtime.reapply()
    QTest.qWait(140)
    assert window.property('ticks') > first
    user_overlay.set_scripts_allowed(False)
    runtime.reapply()
    final = window.property('ticks')
    QTest.qWait(140)
    assert window.property('ticks') == final
    window.close()


def test_an_unreadable_file_is_kept_aside_not_overwritten(data_root):
    from twobyteasr.app import user_overlay
    user_overlay.store_path().parent.mkdir(parents=True)
    user_overlay.store_path().write_text('{broken', 'utf-8')
    assert user_overlay.load()['entries'] == []
    assert list(user_overlay.root().glob('overlay.unreadable-*.json'))


def test_a_style_stays_on_its_control_even_when_the_program_sets_the_sheet_again(app):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.app import user_overlay, user_overlay_runtime
    button = QPushButton('发送')
    button.setObjectName('bunnyChatSend')
    button.setStyleSheet('QPushButton { color: blue; }')
    button.show()
    user_overlay.add('style', 'QPushButton#bunnyChatSend', 'font-size: 19px')
    runtime = user_overlay_runtime.install(app, safe=False)
    assert 'font-size: 19px' in button.styleSheet() and 'color: blue' in button.styleSheet()
    button.setStyleSheet('QPushButton { color: red; }')            # e.g. a theme refresh
    app.processEvents()
    assert 'font-size: 19px' in button.styleSheet() and 'color: red' in button.styleSheet()
    user_overlay.set_enabled('u1', False)
    runtime.reapply()
    assert 'font-size' not in button.styleSheet() and 'color: red' in button.styleSheet()
    button.close()


def test_a_text_change_reads_in_every_language_and_applies_at_once(app):
    from PySide6.QtWidgets import QLabel
    from twobyteasr import i18n
    from twobyteasr.app import user_overlay, user_overlay_runtime
    source = '保存更改'
    assert user_overlay_runtime.is_ui_text(source)
    assert user_overlay_runtime.resolve_ui_text(i18n.translate(source, 'en')) == source     # shown in English
    assert user_overlay_runtime.resolve_ui_text('这是一句字幕内容') == ''                  # user content: no
    label = QLabel(source)
    label.show()
    runtime = user_overlay_runtime.install(app, safe=False)
    user_overlay.add('text', source, '存起来')
    runtime.reapply()
    assert i18n.translate(source, 'en') == '存起来' and i18n.ui_literal(source, 'ja') == '存起来'
    assert label.text() == '存起来'
    user_overlay.set_enabled('u1', False)
    runtime.reapply()
    assert i18n.translate(source, 'zh') == source and label.text() == source
    label.close()


def test_after_an_update_what_no_longer_fits_is_paused_and_told_not_dropped(app):
    from twobyteasr.app import user_overlay, user_overlay_runtime
    user_overlay.add('text', '保存更改', '存起来')
    user_overlay.add('note', '', '回答简短')
    state = user_overlay.load()
    state['entries'][0]['target'] = '某个已经被删掉的按钮文字'          # the new version no longer has it
    state['last_app_version'] = '0.9.6 old'
    user_overlay.store_path().write_text(json.dumps(state, ensure_ascii=False), 'utf-8')
    runtime = user_overlay_runtime.install(app, safe=False)
    first = user_overlay.find('u1')
    assert first is not None and first['status'] == 'paused_update' and '没有这句' in first['detail']
    assert user_overlay.find('u2')['status'] == ''
    assert any('更新后' in notice and 'u1' in notice for notice in runtime.notices)
    assert user_overlay.load()['last_app_version'] == runtime.identity
    again = user_overlay_runtime.install(app, safe=False)           # told once, not at every start
    assert not again.notices
    user_overlay.set_enabled('u1', True)                             # the user can switch it on to try again
    assert user_overlay.find('u1')['status'] == ''


def test_scripts_run_only_when_allowed_and_a_broken_one_is_switched_off(app):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import user_overlay, user_overlay_runtime
    window = QWidget()
    good, _ = user_overlay.add('script', '', '标记窗口', code=SCRIPT)
    bad, _ = user_overlay.add('script', '', '会出错', code='API_VERSION = 1\n\ndef setup(api):\n    raise RuntimeError("boom")\n')
    runtime = user_overlay_runtime.install(app, safe=False)
    runtime.after_window(window, show_notices=False)
    assert window.property('userScriptRan') is None                  # 「允许运行我的扩展脚本」 is off
    user_overlay.set_scripts_allowed(True)
    runtime.reapply()
    assert window.property('userScriptRan') == good['id'] and '[u1] hello' in runtime.log
    broken = user_overlay.find(bad['id'])
    assert broken['status'] == 'failed' and not broken['enabled'] and 'boom' in broken['detail']
    assert any(bad['id'] in notice for notice in runtime.notices)
    assert not (user_overlay.root() / user_overlay_runtime.LOADING_MARKER).exists()


@pytest.fixture
def screen(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
    from twobyteasr.app import bunny_memory
    from twobyteasr.app.bunny_permissions import DEFAULTS, KEY
    from twobyteasr.app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{KEY: dict(DEFAULTS)}))
    bunny_memory.clear_chats()
    window = QWidget()
    layout = QVBoxLayout(window)
    start = QPushButton('开始生成字幕')
    start.setObjectName('startButton')
    layout.addWidget(start)
    window.show()
    app.processEvents()
    yield window, start
    window.close()


def test_she_finds_the_control_and_her_change_waits_for_the_users_ok_even_when_trusted(app, screen):
    from twobyteasr.app import bunny_permissions, user_overlay, user_overlay_runtime
    from twobyteasr.app.bunny_tools import pending_summary, run_turn, undo_records
    window, start = screen
    user_overlay_runtime.install(app, safe=False)
    found = run_turn(window, [('ui_widgets', {'text': '开始生成'})], None).receipts[0]
    assert 'QPushButton#startButton「开始生成字幕」' in found
    call = ('propose_change', {'kind': 'style', 'target': '#startButton', 'value': 'font-size: 21px;', 'why': '字太小'})
    trusted = dict(bunny_permissions.load(), level='auto')
    waiting = run_turn(window, [call], trusted)
    assert waiting.pending == [call] and user_overlay.entries() == []                 # stays forever: always asks
    assert pending_summary(waiting.pending) == '改 #startButton 的样式'
    guide = run_turn(window, [call], dict(trusted, level='guide'))
    assert '只指路' in guide.receipts[0] and not guide.pending
    done = run_turn(window, [call], trusted, confirmed=True)
    assert '成功' in done.receipts[0] and '更新也不会盖掉' in done.receipts[0]
    app.processEvents()
    assert 'font-size: 21px' in start.styleSheet()
    entry = user_overlay.find('u1')
    assert entry['by'] == 'bunny' and entry['note'] == '字太小'
    assert undo_records(done.undo) == (1, '')                                        # 「撤销兔白刚才做的」
    assert user_overlay.entries() == [] and 'font-size' not in start.styleSheet()


def test_her_text_script_and_switch_off_changes(app, screen):
    from twobyteasr import i18n
    from twobyteasr.app import user_overlay, user_overlay_runtime
    from twobyteasr.app.bunny_persona import system_prompt
    from twobyteasr.app.bunny_tools import run_turn, undo_records
    window, _start = screen
    user_overlay_runtime.install(app, safe=False)
    shown = i18n.translate('保存更改', 'en')                    # she read it off an English screen
    text = run_turn(window, [('propose_change', {'kind': 'text', 'target': shown, 'value': '存起来'})], None)
    assert '成功' in text.receipts[0] and user_overlay.find('u1')['target'] == '保存更改'
    assert i18n.translate('保存更改') == '存起来'
    nope = run_turn(window, [('propose_change', {'kind': 'text', 'target': '第 3 条字幕的内容', 'value': 'x'})], None)
    assert '不是软件自带的界面文字' in nope.receipts[0]
    script = run_turn(window, [('propose_change', {'kind': 'script', 'value': '标记窗口', 'code': SCRIPT})], None)
    assert '关着' in script.receipts[0] and user_overlay.find('u2')['enabled'] is False
    bad = run_turn(window, [('propose_change', {'kind': 'script', 'value': 'x', 'code': 'print(1)'})], None)
    assert 'API_VERSION' in bad.receipts[0]
    note = run_turn(window, [('propose_change', {'kind': 'note', 'value': '回答时先说结论'})], None)
    assert '成功' in note.receipts[0] and '回答时先说结论' in system_prompt([])
    off = run_turn(window, [('disable_change', {'id': 'u1'})], None)
    assert '关掉了 u1' in off.receipts[0] and i18n.translate('保存更改', 'zh') == '保存更改'
    assert undo_records(off.undo) == (1, '') and i18n.translate('保存更改', 'zh') == '存起来'
    listed = run_turn(window, [('list_changes', {})], None).receipts[0]
    assert '[u1]' in listed and '[u2]' in listed and '允许运行我的扩展脚本」关着' in listed
    # an undo after the user changed the layer again does not trample their change
    later = run_turn(window, [('propose_change', {'kind': 'note', 'value': '第二条'})], None)
    user_overlay.add('note', '', '小兔纸自己加的')
    assert '不敢乱撤' in undo_records(later.undo)[1]


def test_the_settings_page_lists_switches_and_takes_changes_back(app, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from twobyteasr import i18n
    from twobyteasr.app import user_overlay, user_overlay_runtime
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    user_overlay_runtime.install(app, safe=False)
    user_overlay.add('text', '保存更改', '存起来', by='bunny')
    user_overlay.add('script', '', '标记窗口', code=SCRIPT, by='bunny')
    user_overlay_runtime.reapply()
    owner = QWidget()
    dialog = ApplicationSettingsDialog(owner, {}, tmp_path / 'projects', browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    try:
        labels = [dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
        dialog.navigation.setCurrentRow(labels.index('我的改动'))
        dialog.show()
        app.processEvents()
        rows = [dialog.overlay_list.item(i) for i in range(dialog.overlay_list.count())]
        assert len(rows) == 2 and '兔白' in rows[0].text() and rows[1].checkState() == Qt.CheckState.Unchecked
        rows[0].setCheckState(Qt.CheckState.Unchecked)                    # switch her text change off
        app.processEvents()
        assert user_overlay.find('u1')['enabled'] is False and i18n.translate('保存更改', 'zh') == '保存更改'
        assert not dialog.overlay_scripts.isChecked()
        dialog.overlay_scripts.setChecked(True)
        assert user_overlay.load()['scripts_allowed'] is True
        assert dialog.overlay_history.count() >= 3
        dialog.overlay_history.setCurrentIndex(dialog.overlay_history.count() - 1)   # before anything
        dialog.overlay_restore.click()
        app.processEvents()
        assert user_overlay.entries() == [] and not dialog.overlay_scripts.isChecked()
        assert '回去了' in dialog.overlay_status.text()
    finally:
        dialog.reject()
        dialog.deleteLater()
        owner.deleteLater()


def test_a_crash_while_loading_pauses_the_scripts_and_shift_starts_safe(app):
    from twobyteasr import i18n
    from twobyteasr.app import user_overlay, user_overlay_runtime
    user_overlay.add('script', '', '标记窗口', code=SCRIPT)
    user_overlay.add('text', '保存更改', '存起来')
    user_overlay.set_scripts_allowed(True)
    (user_overlay.root() / user_overlay_runtime.LOADING_MARKER).write_text('u1', 'utf-8')   # died mid-load
    runtime = user_overlay_runtime.install(app, safe=False)
    assert user_overlay.find('u1')['status'] == 'paused_crash'
    assert any('意外关闭' in notice for notice in runtime.notices)
    safe = user_overlay_runtime.install(app, safe=True)
    assert i18n.translate('保存更改', 'zh') == '保存更改'               # nothing applied this time
    assert any('安全模式' in notice for notice in safe.notices)
    assert user_overlay.find('u2')['enabled']                          # ... and nothing changed
