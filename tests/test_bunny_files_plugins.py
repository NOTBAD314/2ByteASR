"""2026-11-20: 兔白's files and her extension scripts.

User: reading, changing files and exporting .txt worked badly, a Chinese file name could not be read,
and 兔白 should be able to write and fix the user's own extensions (for example 识别后自动整理术语),
which the program everyone gets does not do by itself.
"""
from __future__ import annotations

import io
import os
import zipfile
from types import SimpleNamespace

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture
def folder(tmp_path, monkeypatch):
    from twobyteasr.app import bunny_permissions
    root = tmp_path / '授權資料夾'
    root.mkdir()
    state = {}
    monkeypatch.setattr('twobyteasr.app.onboarding.load_state', lambda: dict(state))
    monkeypatch.setattr('twobyteasr.app.onboarding.save_state', lambda value: (state.clear(), state.update(value)))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path / 'data'))
    bunny_permissions.save({'folders': [str(root)]})
    return root


# ------------------------------------------------------------------ names as she writes them
def test_chinese_names_match_across_simplified_traditional_width_quotes_and_escapes(folder):
    from twobyteasr.app import bunny_files
    (folder / '原神術語.csv').write_text('派蒙,角色\n', encoding='utf-8')
    (folder / '子目錄').mkdir()
    (folder / '子目錄' / '說明.txt').write_text('第一集', encoding='utf-8')
    target = (folder / '原神術語.csv').resolve()
    for spelling in ('原神術語.csv', '原神术语.csv', '「原神术语.csv」', '原神 術語.CSV', '授权资料夹/原神术语.csv',
                     '\\u539f\\u795e\\u672f\\u8bed.csv', str(folder / '原神术语.csv')):
        assert bunny_files.resolve(spelling)[0] == target, spelling
    assert bunny_files.resolve('子目录/说明.txt')[0] == (folder / '子目錄' / '說明.txt').resolve()
    assert bunny_files.resolve('说明.txt')[0] == (folder / '子目錄' / '說明.txt').resolve()     # found in a subfolder
    assert '第一集' in bunny_files.read_file('说明.txt')


def test_missing_and_ambiguous_names_say_what_is_there(folder):
    from twobyteasr.app import bunny_files
    from twobyteasr.app.bunny_tools import ToolError
    (folder / '原神術語.csv').write_text('x', encoding='utf-8')
    with pytest.raises(ToolError, match='名字相近的有：.*原神術語.csv'):
        bunny_files.resolve('原神.csv')
    for name in ('一', '二'):
        (folder / name).mkdir()
        (folder / name / '術語.txt').write_text(name, encoding='utf-8')
    with pytest.raises(ToolError, match='有 2 个都叫'):
        bunny_files.resolve('术语.txt')
    assert bunny_files.resolve('二/术语.txt')[0].read_text(encoding='utf-8') == '二'


def test_reads_any_text_file_word_documents_and_refuses_binaries(folder):
    from twobyteasr.app import bunny_files
    from twobyteasr.app.bunny_tools import ToolError
    (folder / 'plugin.py').write_text('print("你好")\n', encoding='utf-8')
    assert '你好' in bunny_files.read_file('plugin.py')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml',
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                         '<w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:p><w:r><w:t>派蒙</w:t><w:tab/><w:t>角色</w:t></w:r></w:p>'
                         '</w:body></w:document>')
    (folder / '名单.docx').write_bytes(buffer.getvalue())
    read = bunny_files.read_file('名單.docx')
    assert '第一段\n派蒙\t角色' in read
    (folder / 'clip.mp4').write_bytes(b'\x00\x00\x00\x18ftypmp42')
    with pytest.raises(ToolError, match='不是文字文件'):
        bunny_files.read_file('clip.mp4')


# ------------------------------------------------------------------ changing an existing file
def test_edit_file_replaces_one_passage_keeps_encoding_and_line_ends_and_undoes(folder):
    from twobyteasr.app import bunny_files
    from twobyteasr.app.bunny_tools import ToolError
    path = folder / '術語表.csv'
    original = '术语,分类\r\n派门,角色\r\n璃月,地名\r\n'.encode('gbk')
    path.write_bytes(original)
    receipt, undo = bunny_files.edit_file('术语表.csv', find='派门,角色', replace='派蒙,角色')
    assert '改好了' in receipt and '可以撤销' in receipt
    data = path.read_bytes()
    assert data == '术语,分类\r\n派蒙,角色\r\n璃月,地名\r\n'.encode('gbk')        # GBK and CRLF kept
    backups = list(bunny_files.backup_root().rglob('術語表.csv'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert undo() == '' and path.read_bytes() == original
    with pytest.raises(ToolError, match='找不到'):
        bunny_files.edit_file('术语表.csv', find='不存在', replace='x')
    path.write_text('a\na\n', encoding='utf-8')
    with pytest.raises(ToolError, match='出现 2 次'):
        bunny_files.edit_file('术语表.csv', find='a', replace='b')
    bunny_files.edit_file('术语表.csv', find='a', replace='b', every=True)
    assert path.read_text(encoding='utf-8') == 'b\nb\n'
    _receipt, undo = bunny_files.edit_file('术语表.csv', text='整份新内容')
    assert path.read_text(encoding='utf-8') == '整份新内容'
    path.write_text('之后小兔纸自己又改了', encoding='utf-8')
    assert '又被改过' in undo() and path.read_text(encoding='utf-8') == '之后小兔纸自己又改了'


def test_edit_file_refuses_programs_and_never_touches_app_data(folder, tmp_path):
    from twobyteasr.app import bunny_files, bunny_permissions
    from twobyteasr.app.bunny_tools import ToolError
    (folder / 'run.bat').write_text('echo', encoding='utf-8')
    with pytest.raises(ToolError, match='只写这些文件'):
        bunny_files.edit_file('run.bat', text='del *')
    data = tmp_path / 'data' / '2ByteASR'
    data.mkdir(parents=True)
    (data / 'notes.txt').write_text('x', encoding='utf-8')
    bunny_permissions.save({'files_anywhere': True})
    with pytest.raises(ToolError, match='资料文件夹'):
        bunny_files.edit_file(str(data / 'notes.txt'), text='y')


def test_original_named_from_txt_is_preserved_in_edit_backup(folder):
    from twobyteasr.app import bunny_files
    path = folder / 'from.txt'
    path.write_bytes(b'original')
    _, undo = bunny_files.edit_file('from.txt', text='edited')
    backup, = bunny_files.backup_root().glob('*/from.txt')
    assert backup.read_bytes() == b'original'
    assert undo() == '' and path.read_bytes() == b'original'


def test_files_anywhere_is_off_by_default_and_opens_full_paths(folder, tmp_path, monkeypatch):
    from pathlib import Path
    from twobyteasr.app import bunny_files, bunny_permissions
    from twobyteasr.app.bunny_tools import ToolError
    program = Path(bunny_files.__file__).resolve().parents[2]
    assert program in bunny_files._no_write_roots()                # never writes into the program by full path
    # The isolated test temp folder lives inside the source tree; keep only Windows' own folder for this test.
    windows = [Path(os.environ['WINDIR']).resolve()] if os.environ.get('WINDIR') else []
    monkeypatch.setattr(bunny_files, '_no_write_roots', lambda: windows)
    outside = tmp_path / '別處'
    outside.mkdir()
    (outside / '筆記.txt').write_text('外面的文件', encoding='utf-8')
    assert bunny_permissions.load()['files_anywhere'] is False
    with pytest.raises(ToolError, match='读写整台电脑'):
        bunny_files.read_file(str(outside / '笔记.txt'))
    bunny_permissions.save({'files_anywhere': True})
    assert '外面的文件' in bunny_files.read_file(str(outside / '笔记.txt'))
    assert '写好了' in bunny_files.write_file(str(outside / '新的.txt'), '内容')
    windir = os.environ.get('WINDIR')
    if windir and os.path.isdir(windir):
        with pytest.raises(ToolError, match='Windows'):
            bunny_files.write_file(os.path.join(windir, 'bunny-test.txt'), 'x')
    tool = SimpleNamespace(name='edit_file', acts=False, edit=True, paid=False)
    assert bunny_permissions.refusal(tool, dict(bunny_permissions.load(), folders=[])) == ''
    assert '整台电脑' in bunny_permissions.describe()


def test_file_tools_respect_auto_permission_without_enabling_extensions(folder):
    from twobyteasr.app import bunny_permissions, bunny_tools
    values = dict(bunny_permissions.load(), level='auto')
    for name in ('edit_file', 'export_subtitles', 'write_file'):
        tool = bunny_tools.TOOLS[name]
        assert not bunny_permissions.needs_confirmation(tool, values), name
        assert bunny_permissions.needs_confirmation(tool, {**values, 'level': 'ask'}), name
    assert bunny_permissions.needs_confirmation(bunny_tools.TOOLS['edit_script'], values)
    for name in ('script_guide', 'read_change'):
        assert not bunny_permissions.needs_confirmation(bunny_tools.TOOLS[name], values)
    details = bunny_tools.pending_details([('edit_file', {'path': 'a.csv', 'find': '派门', 'replace': '派蒙'})])
    assert '改文件「a.csv」' in details and '「派门」→「派蒙」' in details


def test_export_subtitles_writes_the_project_itself_never_her_retyping(folder, monkeypatch):
    from twobyteasr.app import bunny_harness_tools
    from twobyteasr.app.bunny_tools import ToolError
    page = SimpleNamespace(project=SimpleNamespace(cues=[1, 2, 3]))
    window = SimpleNamespace(built_page=lambda name: page if name == 'studio' else None)   # any page on screen
    with pytest.raises(ToolError, match='还没有打开工程'):
        bunny_harness_tools._export_subtitles(SimpleNamespace(built_page=lambda _name: None), {'path': 'a.txt'})
    asked = []
    monkeypatch.setattr(bunny_harness_tools, 'export_text',
                        lambda project, fmt, layer: asked.append((fmt, layer)) or '第一句\n第二句\n第三句\n')
    with pytest.raises(ToolError, match='没有「字幕」'):           # no such folder yet
        bunny_harness_tools._export_subtitles(window, {'path': '字幕/第一集', 'format': 'txt'})
    (folder / '字幕').mkdir()
    receipt = bunny_harness_tools._export_subtitles(window, {'path': '字幕/第一集', 'format': 'txt'})
    assert asked[-1] == ('txt', 'shown') and 'TXT' in receipt and '3 条' in receipt
    assert (folder / '字幕' / '第一集.txt').read_text(encoding='utf-8') == '第一句\n第二句\n第三句\n'
    receipt = bunny_harness_tools._export_subtitles(window, {'path': '字幕/第一集.srt', 'layer': 'original'})
    assert asked[-1] == ('srt', 'original') and (folder / '字幕' / '第一集.srt').exists()
    again = bunny_harness_tools._export_subtitles(window, {'path': '字幕/第一集.txt'})
    assert '新名字' in again and (folder / '字幕' / '第一集 (2).txt').exists()
    with pytest.raises(ToolError):
        bunny_harness_tools._export_subtitles(window, {'path': 'x.mp4'})


# ------------------------------------------------------------------ extension scripts
@pytest.fixture
def overlay(tmp_path, monkeypatch):
    monkeypatch.setenv('2BYTEASR_USER_DATA_ROOT', str(tmp_path / 'data'))
    from twobyteasr.app import extension_events
    extension_events.reset()
    yield
    extension_events.reset()


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


EVENT_SCRIPT = '''API_VERSION = 1

def setup(api):
    seen = api.window.property('seenEvents') or []
    def edited(event):
        api.window.setProperty('seenEvents', [*(api.window.property('seenEvents') or []), event['after']])
    api.on('subtitle_edited', edited)
    api.on('project_saved', lambda event: 1 / 0)
'''


def test_scripts_hear_events_only_while_switched_on_and_a_broken_one_is_switched_off(overlay, app):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import extension_events, user_overlay, user_overlay_runtime
    runtime = user_overlay_runtime.install(app, safe=False)
    window = QWidget()
    entry, _ = user_overlay.add('script', '', '记下改过的字幕', code=EVENT_SCRIPT, by='user')
    user_overlay.set_scripts_allowed(True)
    runtime.after_window(window, show_notices=False)
    assert entry['id'] in runtime.loaded
    assert extension_events.emit('subtitle_edited', before='派门', after='派蒙') == 1
    assert window.property('seenEvents') == ['派蒙']
    user_overlay.set_enabled(entry['id'], False)
    assert extension_events.emit('subtitle_edited', before='a', after='b') == 0
    user_overlay.set_enabled(entry['id'], True)
    for _ in range(extension_events.MAX_FAILURES):
        extension_events.emit('project_saved', path='x.2byteproj', project=None)
    marked = user_overlay.find(entry['id'])
    assert marked['enabled'] is False and marked['status'] == 'failed' and 'ZeroDivisionError' in marked['detail']
    assert any('project_saved 出错' in line for line in runtime.script_log(entry['id']))
    assert not extension_events.has('subtitle_edited')


def test_emit_never_raises_and_unknown_events_are_refused(overlay):
    from twobyteasr.app import extension_events
    assert extension_events.emit('subtitle_edited', before='a', after='b') == 0
    with pytest.raises(ValueError, match='没有「nope」'):
        extension_events.on('u1', 'nope', print)


def test_she_reads_and_fixes_a_script_which_then_waits_switched_off(overlay, app):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_tools, extension_events, user_overlay, user_overlay_runtime
    runtime = user_overlay_runtime.install(app, safe=False)
    window = QWidget()
    entry, _ = user_overlay.add('script', '', '记下改过的字幕', code=EVENT_SCRIPT, by='user')
    user_overlay.set_scripts_allowed(True)
    runtime.after_window(window, show_notices=False)
    read = bunny_tools.TOOLS['read_change'].run(window, {'id': entry['id']})
    assert "api.on('subtitle_edited'" in read and '【脚本代码开始】' in read and '已运行' in read
    fixed = EVENT_SCRIPT.replace("api.on('project_saved', lambda event: 1 / 0)\n", '')
    receipt, record = bunny_tools.TOOLS['edit_script'].run(window, {'id': entry['id'], 'code': fixed, 'why': '修好保存出错'})
    assert '先关上了' in receipt
    now = user_overlay.find(entry['id'])
    assert now['enabled'] is False and now['note'] == '修好保存出错'
    assert user_overlay.script_path(now).read_text('utf-8') == fixed
    assert entry['id'] not in runtime.loaded and not extension_events.has('subtitle_edited')
    assert record.target() == ''                                   # 撤销: the old code, switched on again
    back = user_overlay.find(entry['id'])
    assert back['enabled'] is True and 'lambda event: 1 / 0' in user_overlay.script_path(back).read_text('utf-8')
    with pytest.raises(bunny_tools.ToolError, match='语法错误'):
        bunny_tools.TOOLS['edit_script'].run(window, {'id': entry['id'], 'code': 'API_VERSION = 1\ndef setup(api:\n'})


def test_script_api_glossary_ai_and_background_hand_back_on_the_gui_thread(overlay, app, monkeypatch):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_harness_tools, user_overlay_runtime
    runtime = user_overlay_runtime.install(app, safe=False)
    window = QWidget()
    api = user_overlay_runtime.ScriptAPI(window, {'id': 'u7'}, runtime)
    calls = []
    monkeypatch.setattr(bunny_harness_tools, 'apply_term_changes',
                        lambda win, library, changes, origin='': calls.append((library, changes, origin)) or ('《库》加 2 条', None))
    receipt = api.glossary.add('我的自动术语', ['派蒙', {'from': '派门', 'to': '派蒙', 'category': '角色'}, {'x': 1}])
    assert receipt == '《库》加 2 条'
    assert calls == [('我的自动术语', [{'action': 'add', 'to': '派蒙'},
                                       {'action': 'add', 'to': '派蒙', 'from': '派门', 'category': '角色'}], '扩展脚本 u7')]
    got = []
    api.in_background(lambda: 41 + 1, lambda result, error: got.append((result, error)))
    monkeypatch.setattr('twobyteasr.app.bunny_chat.runtime_settings', lambda _window: None)
    api.ai('分类这些词', lambda text, error: got.append((text, type(error).__name__)))
    import time
    deadline = time.monotonic() + 5
    while len(got) < 2 and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert (42, None) in got and (None, 'RuntimeError') in got
    assert api.say('加好了') is False and any('兔白说：加好了' in line for line in runtime.script_log('u7'))


def test_the_guide_example_is_a_valid_script_and_is_never_installed_by_itself(overlay):
    from twobyteasr.app import extension_guide, user_overlay
    assert user_overlay.check_script(extension_guide.EXAMPLE_AUTO_TERMS)
    guide = extension_guide.guide()
    for word in ('subtitle_edited', 'project_saved', 'recognition_finished', 'api.glossary.add', 'api.ai'):
        assert word in guide
    assert user_overlay.entries('script') == []          # the program never adds it; only the user's 「帮我做」 does


def test_the_auto_terms_example_sorts_corrections_into_a_new_library(overlay, app, tmp_path, monkeypatch):
    """The user's request end to end, with a stubbed AI: corrections -> save -> categorized terms in a library."""
    import json
    import time
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QWidget
    import subtitle_core as legacy
    from twobyteasr.app import extension_events, extension_guide, user_overlay, user_overlay_runtime
    from twobyteasr.local_mcp import mcp_glossary
    monkeypatch.setattr(legacy, 'LEARNED_TERMS_PATH', str(tmp_path / 'terms' / 'terms.json'))
    monkeypatch.setattr(legacy, 'load_game_profiles', lambda: {})
    monkeypatch.setattr(legacy, 'save_runtime_game_history', lambda _name: None, raising=False)
    asked = []

    class Provider:
        def complete(self, messages, **_kwargs):
            asked.append(messages[-1]['content'])
            return '好的：' + json.dumps([{'from': '派门', 'to': '派蒙', 'category': '角色'},
                                         {'from': '离月', 'to': '璃月', 'category': '地名'}], ensure_ascii=False)
    monkeypatch.setattr('twobyteasr.app.bunny_chat.runtime_settings', lambda _window: {'models': {}})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *_a, **_k: Provider())
    runtime = user_overlay_runtime.install(app, safe=False)
    window = QWidget()
    window.legacy = legacy
    entry, _ = user_overlay.add('script', '', '识别后自动整理术语', code=extension_guide.EXAMPLE_AUTO_TERMS, by='user')
    user_overlay.set_scripts_allowed(True)
    runtime.after_window(window, show_notices=False)
    assert entry['id'] in runtime.loaded, runtime.script_log()
    extension_events.emit('subtitle_edited', before='派门来了', after='派蒙来了', replacements=[('派门', '派蒙')])
    extension_events.emit('subtitle_edited', before='去离月', after='去璃月', replacements=[('离月', '璃月')])
    extension_events.emit('project_saved', path='x.2byteproj', project=None)
    deadline = time.monotonic() + 10
    while not any('加' in line for line in runtime.script_log(entry['id'])) and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    assert asked and '派门 -> 派蒙' in asked[0] and '离月 -> 璃月' in asked[0]
    library_id, name = mcp_glossary.resolve_library(legacy, '我的自动术语')
    rows = mcp_glossary.search(legacy, '', library_id, 0, 50)['rows']
    pairs = {(row['from'], row['to'], row['category']) for row in rows}
    assert ('派门', '派蒙', '角色') in pairs and ('离月', '璃月', '地名') in pairs, (pairs, runtime.script_log())


def test_a_done_claim_without_any_writing_tool_is_sent_back_once():
    """Live run 2026-11-20: 「脚本写好了，已经存进我的改动」 after only reading the guide."""
    from twobyteasr.app import bunny_persona
    claim = bunny_persona.BunnyReply(lines=['脚本写好了，已经存进「我的改动」里～', '去设置里打开就行'])
    looked = ['- script_guide()：成功。【扩展脚本怎么写】…', '- tool_help(names=[...])：成功。…']
    assert bunny_persona.unbacked_claim(claim, looked, [])
    saved = [*looked, '- propose_change(kind=script, …)：成功。脚本存成了 u1，现在是关着的']
    assert not bunny_persona.unbacked_claim(claim, saved, [])
    assert not bunny_persona.unbacked_claim(claim, looked, [('propose_change', {})])        # waiting for 帮我做
    plain = bunny_persona.BunnyReply(lines=['可以写成插件，要兔白现在写吗？'])
    assert not bunny_persona.unbacked_claim(plain, looked, [])
    assert '还没做' in bunny_persona.claim_retry_messages('{}')[-1]['content']


def test_events_are_sent_from_edits_saves_and_finished_recognitions():
    import inspect
    from twobyteasr.app import ui
    from twobyteasr.projects import studio_save
    from twobyteasr.studio import studio_glossary_autosave
    assert "emit('recognition_finished'" in inspect.getsource(ui.MainWindow._handle_result)
    assert "emit('project_saved'" in inspect.getsource(studio_save.request_formal_save)
    assert 'emit("subtitle_edited"' in inspect.getsource(studio_glossary_autosave._tell_extensions)
