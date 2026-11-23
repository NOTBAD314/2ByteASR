"""兔白's task suite: real tasks through the real chat card, scored by checks (2026-11-17, harness P3).

Agent harness work is measured with a fixed set of real tasks (evals): each change to her prompt or
tools is run against the same tasks and the success rate, rounds and seconds are compared. Here a
real MainWindow on isolated user data, the real 「问问兔白」 card and the user's own text AI; each
task is asked like a user would, then a check reads the app's state (page, dialog, setting file,
zoom, what she did). Opt-in and paid (a few cents on DeepSeek): it uses the user's key.

    python -X utf8 -m twobyteasr.acceptance.bunny_eval            # all tasks
    python -X utf8 -m twobyteasr.acceptance.bunny_eval zoom_in    # some tasks by id

The key is read from the user's store before the switch to the isolated folders and handed over in
memory only; nothing of the user's own data folder is written. Report: tmp/bunny-eval/<time>.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]


@dataclass
class Task:
    id: str
    question: str
    check: Callable                      # (window, chat) -> (passed, detail)
    level: str = 'auto'                  # 「兔白权限」 for this task
    seconds: float = 150.0
    note: str = ''
    setup: Callable | None = None        # (window) -> None, right before the question (2026-11-18)
    press: bool = False                  # 2026-11-20: press 「帮我做」 when she leaves edits waiting, like the user
    settle: float = 0.0                  # seconds between setup and the question (a project still opening)


@dataclass
class Result:
    id: str
    passed: bool
    detail: str
    seconds: float
    rounds: int
    tools: list = field(default_factory=list)
    said: list = field(default_factory=list)


# ------------------------------------------------------------------ checks
def _page(name):
    def check(window, _chat):
        from ..app.bunny_chat import current_page
        page = current_page(window)
        return page == name, f'当前页面：{page or "?"}'
    return check


def _page_soon(name, seconds: float = 12.0):
    """Like ``_page`` for a page that is built after she answered (the workbench loads lazily)."""
    def check(window, _chat):
        from PySide6.QtWidgets import QApplication
        from ..app.bunny_chat import current_page
        deadline = time.monotonic() + seconds
        while current_page(window) != name and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.05)
        page = current_page(window)
        return page == name, f'当前页面：{page or "?"}'
    return check


def _settings_section(name):
    def check(window, _chat):
        from ..app.bunny_ui_control import elements
        hits = [item for item in elements(window, want=name)
                if item.kind in ('toggle', 'tab', 'radio', 'item') and item.window != '主窗口']
        on = [item for item in hits if '勾着' in item.value or '当前' in item.value]
        return bool(on), f'设置里「{name}」：' + ('选中' if on else '没选中' if hits else '设置窗口没开')
    return check


def _autosave(seconds):
    def check(_window, _chat):
        # The isolated folder's own settings (studio_settings_path may have been resolved before the switch).
        root = Path(os.environ.get('2BYTEASR_USER_DATA_ROOT') or os.environ['LOCALAPPDATA'])
        values = []
        for path in root.rglob('settings.json'):
            try:
                data = json.loads(path.read_text('utf-8'))
            except (OSError, ValueError):
                continue
            stack = [data]
            while stack:                             # the value sits under studio_preferences
                node = stack.pop()
                if isinstance(node, dict):
                    if 'autosave_interval_seconds' in node:
                        values.append(node['autosave_interval_seconds'])
                    stack.extend(node.values())
        return seconds in values, f'autosave_interval_seconds={values or None}'
    return check


def _zoom_above(percent):
    def check(_window, _chat):
        from ..app.ui_zoom import zoom_percent
        value = zoom_percent()
        return value > percent, f'界面缩放 {value}%'
    return check


def _search_text(text):
    def check(window, _chat):
        from ..app.bunny_ui_control import elements
        boxes = [item for item in elements(window) if item.kind == 'text' and item.window != '主窗口' and text in item.value]
        return bool(boxes), '设置的搜索框：' + (boxes[0].value if boxes else '没有含「' + text + '」的')
    return check


def _used(tool, *, answer_has=''):
    def check(_window, chat):
        used = any(line.lstrip('- ').startswith(tool + '(') for line in chat.action_log)
        said = ''.join(text for who, text in chat.transcript[-4:] if who != 'user')
        ok = used and (answer_has in said if answer_has else True)
        return ok, f'用了 {tool}：{used}' + (f'；回答含「{answer_has}」：{answer_has in said}' if answer_has else '')
    return check


def _not_started(_window, chat):
    window = chat.window_
    started = bool(getattr(window, '_run_in_progress', False))
    said = ''.join(text for who, text in chat.transcript[-4:] if who != 'user')
    honest = any(word in said for word in ('素材', '选', '灰'))
    return (not started and honest), f'开始了识别：{started}；说明了原因：{honest}'


def _zoom_is(percent):
    def check(_window, _chat):
        from ..app.ui_zoom import zoom_percent
        value = zoom_percent()
        return value == percent, f'界面缩放 {value}%'
    return check


def _answer(chat) -> str:
    rows = []
    for who, text in reversed(chat.transcript):
        if who == 'user':
            break
        rows.insert(0, text)
    return '\n'.join(rows).replace('**', '').replace('==', '')


def _explains(*groups, card_rows: int = 0, handed: str = ''):
    """Her answer names one spelling of every group; ``card_rows``: a detail card of at least that many
    rows; ``handed``: these words were in what the program gave her (a lookup done before she asked)."""
    def check(_window, chat):
        said = _answer(chat)
        missing = [group for group in groups if not any(word in said for word in group)]
        cards = [text for who, text in chat.transcript if who == 'detail']
        rows = len(cards[-1].split('\n')) if cards else 0
        given = '\n'.join(str(turn.get('content')) for turn in chat._history)
        ok = not missing and rows >= card_rows and (handed in given if handed else True)
        detail = (f'缺 {missing}；' if missing else '') + f'卡片 {rows} 行，回答 {len(said)} 字'
        return ok, detail + (f'；先查好了：{handed in given}' if handed else '')
    return check


def _remember_error(_window):
    from ..app import bunny_events
    bunny_events.forget_recent()
    bunny_events.remember('跳出过一个提示框「导出失败：显卡编码器 h264_nvenc 不可用（-40）」')


# ------------------------------------------------------------------ 2026-11-20: files and extensions
# User (2026-11-20): reading / changing files and txt export worked badly, a Chinese file name could not be
# read; she should be able to write the user's own extension (识别后自动整理术语). These run on the real AI.
TERMS_CSV = '术语,分类\n派门,角色\n那维莱特,角色\n璃月,地名\n'


def _files_folder() -> Path:
    return Path(os.environ['TWOBYTEASR_TEST_ROOT']) / '我的資料'


def _give_folder(_window):
    """A folder with 繁體 names she is likely to write in 简体; the folder is allowed in 「兔白权限」."""
    from ..app import bunny_permissions
    root = _files_folder()
    (root / '遊戲').mkdir(parents=True, exist_ok=True)
    target = root / '遊戲' / '原神術語表.csv'
    target.write_text(TERMS_CSV, encoding='utf-8')
    (root / '說明.txt').write_text('这个文件夹放我做原神实况用的资料。\n', encoding='utf-8')
    bunny_permissions.save({'folders': [str(root)]})


def _receipt_ok(chat, tool) -> bool:
    return any(line.lstrip('- ').startswith(tool + '(') and '成功' in line for line in chat.action_log)


def _read_chinese(_window, chat):
    said = _answer(chat)
    read = _receipt_ok(chat, 'read_file')
    named = all(word in said for word in ('那维莱特',))
    return read and named, f'read_file 成功：{read}；回答提到文件里的角色：{named}'


def _edited_file(_window, chat):
    target = _files_folder() / '遊戲' / '原神術語表.csv'
    text = target.read_text(encoding='utf-8') if target.is_file() else ''
    from ..app.bunny_files import backup_root
    backups = list(backup_root().rglob('原神術語表.csv')) if backup_root().is_dir() else []
    ok = '派蒙,角色' in text and '派门' not in text and bool(backups) and '那维莱特' in text
    return ok, f'文件现在：{text.strip()[:60]!r}；备份 {len(backups)} 份；edit_file 成功：{_receipt_ok(chat, "edit_file")}'


def _open_sample(window):
    from ..app.sample_project import ensure_sample_project
    _give_folder(window)
    window.open_studio_project(str(ensure_sample_project()))


def _exported(_window, chat):
    files = sorted(_files_folder().rglob('*.txt'))
    made = [path for path in files if path.name != '說明.txt']
    text = made[-1].read_text(encoding='utf-8') if made else ''
    used = _receipt_ok(chat, 'export_subtitles')
    return used and bool(text.strip()), f'export_subtitles 成功：{used}；txt：{[p.name for p in made]}，{len(text)} 字'


def _plugin_runs(window, chat):
    """Her script is saved switched off; switched on here like the user would, it hears two corrections and a
    save, asks the real AI and puts categorized terms into a library."""
    from PySide6.QtCore import QCoreApplication
    from ..app import extension_events, user_overlay, user_overlay_runtime
    from ..local_mcp import mcp_glossary
    import subtitle_core as legacy
    mine = [entry for entry in user_overlay.entries('script') if entry.get('by') == 'bunny']
    if not mine:
        return False, '没有存下兔白写的脚本；用了：' + ' '.join(line.split('(')[0].lstrip('- ') for line in chat.action_log)
    entry = mine[-1]
    guide = any(line.lstrip('- ').startswith('script_guide(') for line in chat.action_log)
    if entry.get('enabled'):
        return False, '兔白写的脚本不该是开着的'
    runtime = user_overlay_runtime.runtime() or user_overlay_runtime.install(QCoreApplication.instance(), safe=False)
    runtime.window = window
    user_overlay.set_scripts_allowed(True)
    user_overlay.set_enabled(entry['id'], True)
    runtime.load_scripts(window)
    if entry['id'] not in runtime.loaded:
        return False, f'脚本没能运行：{user_overlay.find(entry["id"]).get("detail")}；看过 script_guide：{guide}'
    before = {row['id'] for row in mcp_glossary.list_libraries(legacy)}
    extension_events.emit('subtitle_edited', before='派门说要去离月', after='派蒙说要去璃月',
                          replacements=[('派门', '派蒙'), ('离月', '璃月')], glossary_ids=[], language='zh', project=None)
    extension_events.emit('subtitle_edited', before='那为莱特来了', after='那维莱特来了',
                          replacements=[('那为莱特', '那维莱特')], glossary_ids=[], language='zh', project=None)
    extension_events.emit('project_saved', path=str(_files_folder() / 'x.2byteproj'), project=None)
    deadline = time.monotonic() + 120
    rows = []
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)
        libraries = [row for row in mcp_glossary.list_libraries(legacy) if row['id'] not in before or row['personal_rows']]
        rows = [found for row in libraries for found in mcp_glossary.search(legacy, '', row['id'], 0, 100)['rows']]
        if any(row['to'] == '派蒙' for row in rows) and any(row['to'] == '那维莱特' for row in rows):
            break
    log = runtime.script_log(entry['id'], 6)
    terms = '、'.join(f"{row['from']}→{row['to']}[{row['category']}]《{row['library']}》" for row in rows[:8])
    ok = any(row['to'] == '派蒙' for row in rows) and any(row['to'] == '那维莱特' for row in rows)
    return ok, f'看过 script_guide：{guide}；术语库里：{terms or "没有"}；脚本记录：{" / ".join(log)[:200]}'


FILE_TASKS = (
    Task('read_chinese_name', '帮我看看授权文件夹里那份原神术语表，里面有哪些角色？', _read_chinese, level='ask',
         setup=_give_folder, note='繁體文件名，问题用简体；要自己 list_folder / read_file 找到'),
    Task('edit_file', '把原神术语表.csv 里的「派门」改成「派蒙」', _edited_file, level='ask', press=True,
         note='edit_file，按「帮我做」后文件改好、原来的另存'),
    Task('write_plugin', '我想要一个插件：识别完我改好字幕后，让 AI 把我改过的专有名词自动分类，加进一个叫“自动术语”的术语库，'
         '不用我手动加。帮我写好。', _plugin_runs, level='ask', press=True, seconds=300,
         note='script_guide → propose_change kind=script；存下关着；打开后用真实 AI 分类进术语库'),
)
def _in_point_at_end(window):
    """User report (2026-11-22): the in point sat at the video's end, so the export had no picture and
    「卡在压制」; she kept thinking about encoders. Open the sample, put I 20 ms before its end."""
    from PySide6.QtCore import QTimer
    from ..projects.project_range import range_points, set_range
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    _open_sample(window)
    # The sample finishes opening a few seconds later and its chat thread switches with it (run
    # 2026-11-22: a range set right away was gone, and a question asked meanwhile lost its answer).
    # Keep putting I back until the question goes out (``settle``).
    def arm(left=40):
        page = window.built_page('studio')
        project = getattr(page, 'project', None) if page is not None else None
        if project is not None and range_points(project) == (None, None):
            set_range(project, timeline_duration_ms(project) - 20, None, page.undo_stack)
        if left > 0:
            QTimer.singleShot(200, lambda: arm(left - 1))
    arm()


EXPORT_TASKS = (
    Task('export_txt', '把现在这个工程的字幕导出成 txt，存到授权文件夹里', _exported, level='ask', press=True,
         setup=_open_sample, settle=8.0, note='export_subtitles，程序直接写，不经模型抄写'),
    Task('export_range_empty', '我一直導出不了影片，卡在壓制那裡，怎麼辦？',
         _explains(('入点', '入點'), ('范围', '範圍', '末尾', '结尾', '結尾')), level='guide',
         setup=_in_point_at_end, settle=8.0,
         note='2026-11-22 用户实报：入点在末尾、范围不到一帧；要从「导出范围检查」说出是范围，不是显卡'),
)



# ------------------------------------------------------------------ pointing (2026-11-22)
# User (2026-11-22): 「基本所有按钮都要能指才好，带用户点的东西也要能是正确的而不是乱点。」
def _point_name(point) -> str:
    from ..app import bunny_pointing
    from ..app.bunny_ui_control import _label_for
    widget = point.get('widget')
    if widget is None:
        return ''
    kind = point.get('kind', '')
    if kind in ('tab', 'item', 'label', 'group'):
        return bunny_pointing.current_label(bunny_pointing.Target(widget, kind, '', index=point.get('index', -1)))
    return _label_for(widget)


def _pointed_at(label: str, *, page: str = '', object_name: str = ''):
    """She outlined the control named ``label`` (on ``page``), and the outline sits on it."""
    def check(window, chat):
        from ..app import bunny_pointing
        from ..app.bunny_chat import current_page
        point = getattr(chat, 'last_point', None) or {}
        if not point.get('ok'):
            return False, f'没指成：{point.get("detail") or "没有指"}'
        widget = point.get('widget')
        name = _point_name(point)
        right = (widget is not None and widget.objectName() == object_name) if object_name else             bunny_pointing._norm(label) in bunny_pointing._norm(name)
        kind = point.get('kind') if point.get('kind') in ('tab', 'item') else 'button'
        on, where = bunny_pointing.covered(chat.spotlight_for(widget).global_target(),
                                           bunny_pointing.Target(widget, kind, name, index=point.get('index', -1)))
        at = current_page(window)
        ok = right and on and (not page or at == page)
        return ok, f'指到「{name}」（{point.get("kind")}）；外框在控件上：{on}' + (f'；页面：{at}' if page else '') +             ('' if on else f'；{where}')
    return check


MISSING_WORDS = ('没有', '找不到', '没找到', '不确定', '没指', '不存在')


def _said_missing(_window, chat):
    """Asked for a button that does not exist: nothing is outlined and she says so."""
    point = getattr(chat, 'last_point', None) or {}
    said = _answer(chat)
    honest = any(word in said for word in MISSING_WORDS)
    return (not point.get('ok') and honest), f'外框：{"指了「" + _point_name(point) + "」" if point.get("ok") else "没指"}；说明了：{honest}'


def _guided_only(window, chat):
    """「只指路」: she does not change the page herself; she says where it is or offers 「带我去」."""
    from ..app.bunny_chat import current_page
    page = current_page(window)
    said = _answer(chat)
    offered = chat.go_button.isVisible() or '带我去' in said or '识别记录' in said
    return page == '首页' and offered, f'页面：{page}；给了路：{offered}'


def _open_settings(window):
    from ..app.application_settings_ui import ApplicationSettingsDialog
    dialog = ApplicationSettingsDialog(window, {}, Path(os.environ['APPDATA']) / 'eval-projects',
                                       browse=lambda *a: None, clear_recent=lambda: None, reset_layout=lambda: None)
    dialog.resize(940, 720)
    dialog.show()


def _completion_bubble(window):
    window._switch_page(2)
    bubble = getattr(window, 'result_ai_repair_bubble', None)
    if bubble is not None:                       # as if a recognition left 3 items 兔白 can fix
        bubble.title.setText('兔白可以帮你修 <b>3</b> 项')
        bubble.note.setText('不用打开工作台')
        bubble.button.setText('交给兔白')
        bubble.show()


POINT_TASKS = (
    Task('point_workshop', '模型工坊在哪？指给我看', _pointed_at('模型工坊'), level='guide'),
    Task('point_settings', '设置按钮在哪里？指一下', _pointed_at('设置'), level='guide'),
    Task('point_start', '「开始生成字幕」的按钮在哪', _pointed_at('开始生成字幕'), level='guide',
         note='没有素材时是灰的：照样指，并说为什么灰'),
    Task('point_terms_toggle', '原文校对术语库那个开关在哪', _pointed_at('原文校对术语库'), level='guide'),
    Task('point_other_page', '识别记录里的「刷新记录」按钮在哪？指给我看', _pointed_at('刷新记录', page='识别记录'),
         note='先切到识别记录再指'),
    Task('point_workshop_search', '模型工坊里搜模型的输入框在哪', _pointed_at('搜索模型', page='模型工坊')),
    Task('point_terms_add', '术语库里添加词条的按钮在哪', _pointed_at('添加', page='术语库')),
    Task('point_settings_save', '这个窗口保存的按钮在哪', _pointed_at('保存更改'), level='guide', setup=_open_settings,
         settle=0.8),
    Task('point_settings_section', '兔白权限在哪一页？指一下', _pointed_at('兔白权限'), level='guide',
         setup=_open_settings, settle=0.8),
    Task('point_shortcuts_closed', '快捷键在哪里改？指给我看', _pointed_at('快捷键'), note='先打开设置再指'),
    Task('point_completion_bubble', '「交给兔白」的按钮在哪', _pointed_at('交给兔白', object_name='aiRepairGo'),
         level='guide', setup=_completion_bubble, settle=1.0),
    Task('point_missing_douyin', '一键发布到抖音的按钮在哪？指给我看', _said_missing, level='guide'),
    Task('point_missing_pdf', '帮我指一下「导出为 PDF」按钮', _said_missing, level='guide'),
    Task('point_guide_other_page', '识别记录里的「刷新记录」按钮在哪？', _guided_only, level='guide',
         note='只指路：不替小兔纸切页面'),
    Task('subtask_split', '用两个子任务分别数一下首页和设置窗口各有几个按钮，最后告诉我总数', _used('run_subtask'),
         seconds=240, note='子任务：干净上下文、结果摘要回来'),
)


TASKS = (
    Task('open_history', '帮我打开识别记录', _page('识别记录')),
    Task('open_workshop', '我想下载模型，带我去模型工坊', _page('模型工坊')),
    Task('settings_shortcuts', '打开应用设置，切到快捷键那一页', _settings_section('快捷键')),
    Task('shortcut_search', '打开快捷键设置，在搜索框里帮我搜「拆分」', _search_text('拆分'),
         note='通用操作：打开 → 快照 → 在对话框的搜索框里填字'),
    Task('autosave_5min', '帮我打开应用设置的工程与保存，把自动保存间隔改成 5 分钟，然后保存', _autosave(300),
         note='通用操作：多步、对话框里改选项再保存'),
    Task('zoom_in', '界面的字有点小，帮我整体放大一档', _zoom_above(100), note='run_command app.zoom_in 或设置'),
    Task('start_without_media', '帮我开始生成字幕', _not_started, note='没有素材：不能开始，要说明原因'),
    Task('recall_actions', '你刚才都帮我做了哪些操作？', _used('recent_actions'), level='ask', note='跨聊天的操作记录'),
    # 2026-11-18 (phases 1, 2, 5): more places, answers that carry enough, things she is handed.
    Task('zoom_reset', '把界面缩放恢复成原来的大小', _zoom_is(100), note='run_command Ctrl+0'),
    Task('open_terms', '带我去术语库', _page('术语库')),
    Task('settings_storage', '打开设置里的存储与缓存那一页', _settings_section('存储与缓存')),
    Task('settings_bunny', '打开兔白权限的设置', _settings_section('兔白权限')),
    Task('howto_card', '我第一次用，怎么从头做一份字幕？', _explains(('开始生成字幕',), ('导出',), card_rows=3),
         level='guide', note='第 1 阶段：结论加完整步骤的卡片'),
    Task('knowledge_garbled', '导出的 SRT 用记事本打开全是乱码怎么办', _explains(('UTF-8',)), level='guide',
         note='第 2 阶段：知识库'),
    Task('why_failed', '上次识别为什么失败？', _explains(('没有', '还没', '找不到'), handed='【兔白查到的：'),
         level='ask', note='第 5 阶段：先查再答；隔离资料里没有记录，要照实说'),
    Task('recent_error', '刚才那个报错是什么意思，怎么办？', _explains(('CPU',), ('编码',)), level='guide',
         setup=_remember_error, note='第 5 阶段：最近发生的事'),
    # Last: the workbench is built after her answer, and a page that appears during the next
    # question would (rightly) make that question's context stale.
    *POINT_TASKS,
    Task('open_studio', '打开字幕工作台', _page_soon('字幕工作台')),
    *FILE_TASKS,
    *EXPORT_TASKS,
)


# ------------------------------------------------------------------ the run
def _prepare(settings: dict):
    """Isolated folders, the key in memory, the user's (non-secret) AI choices, a real window."""
    from ..providers import llm_config
    models = settings.get('models', {})
    key = llm_config.read_scoped_api_key(models.get('polish_provider', ''), models.get('polish_base_url', ''))
    if not key[0]:
        raise SystemExit('没有读到文字 AI 的 Key：请先在 2ByteASR 的 AI 设置里设好。')
    llm_config.read_scoped_api_key = lambda provider, base_url='': key
    llm_config.resolve_api_key = lambda stage: key
    os.environ.setdefault('TWOBYTEASR_TEST_ROOT', str(REPO / 'tmp' / 'bunny-eval' / time.strftime('root-%Y%m%d-%H%M%S')))
    from ..test_isolation import install
    install()
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(Path(os.environ['APPDATA']) / 'qsettings'))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import subtitle_core
    subtitle_core.RUNTIME_SETTINGS.setdefault('models', {}).update(
        {name: value for name, value in models.items() if 'key' not in name.casefold()})
    subtitle_core.RUNTIME_SETTINGS.setdefault('switches', {}).update(settings.get('switches', {}))
    from ..app import bunny_chat, ui
    from ..app.bunny_chat import NOTICE_KEY
    from ..app.onboarding import load_state, save_state
    save_state(dict(load_state(), **{NOTICE_KEY: True}))
    bunny_chat.BunnyChat.FLOATING = False
    ui.save_runtime_settings = lambda value: None
    window = ui.MainWindow([], subtitle_core, object(), None)
    window.resize(1500, 950)
    window.show()
    from ..app import ui_zoom
    window._eval_zoom = ui_zoom.install(app, window)      # the app's entry installs it (its Ctrl+= / Ctrl+- keys)
    return app, window


def _dismiss_prompts() -> None:
    """Answer a question box (e.g. "discard unsaved changes?") the way a user leaving would: discard / no / cancel.
    Run 2 (2026-11-17) stopped for good on one: closing a settings window she had changed but not saved."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    box = QApplication.activeModalWidget()
    discard = getattr(box, 'discard_button', None)
    if discard is not None:              # 2026-11-22: SaveChangesDialog (CandyPrompt) is no QMessageBox
        discard.click()
        return
    if not isinstance(box, QMessageBox):
        return
    for role in (QMessageBox.ButtonRole.DestructiveRole, QMessageBox.ButtonRole.NoRole, QMessageBox.ButtonRole.RejectRole):
        for button in box.buttons():
            if box.buttonRole(button) == role:
                button.click()
                return
    box.reject()


def _reset(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    for delay in (100, 400, 900, 1600):                  # a prompt opened by reject() runs its own loop
        QTimer.singleShot(delay, _dismiss_prompts)
    from ..app import bunny_events
    bunny_events.forget_recent()       # 2026-11-22: one task's planted error box never leaks into the next
    for top in QApplication.topLevelWidgets():
        if top is not window and top.isVisible() and hasattr(top, 'reject') and not str(top.objectName()).startswith('bunny'):
            top.reject()
    if callable(getattr(window, '_switch_page', None)):
        window._switch_page(0)


def run(tasks, settings: dict, *, out: Path | None = None) -> list[Result]:
    from PySide6.QtCore import QTimer
    app, window = _prepare(settings)
    from ..app import bunny_permissions
    from ..app.bunny_chat import open_bunny_chat
    results: list[Result] = []
    queue = list(tasks)
    state = {'finished': set()}

    def start_next():
        if not queue:
            # 2026-11-22: a "save changes?" prompt left by the last task ran its own loop and kept
            # the run from ever exiting; answer it like a user leaving, then quit.
            _reset(window)
            sweeper = QTimer(app)            # a prompt raised by quitting itself is answered too
            sweeper.timeout.connect(_dismiss_prompts)
            sweeper.start(500)
            QTimer.singleShot(2000, app.quit)
            return
        task = queue.pop(0)
        _reset(window)
        bunny_permissions.save({'level': task.level, 'see_screen': False})
        chat = open_bunny_chat(window)
        chat.reveal_all()
        chat.new_conversation()
        chat.reveal_all()
        chat.action_log.clear() if task.id != 'recall_actions' else None
        chat.last_point = None                       # 2026-11-22: a point from the task before never counts
        if task.setup is not None:
            task.setup(window)
        state.update(task=task, chat=chat, started=time.monotonic(), sent=False, pressed=0)
        wait = int(300 + task.settle * 1000)
        QTimer.singleShot(wait, lambda: (chat.ask_now(task.question), state.update(sent=True)))
        QTimer.singleShot(wait + 200, poll)

        def watchdog(task=task, chat=chat):
            # Never wait forever (run 2 stopped on an unanswered box): give up on this task and go on.
            if task.id not in state['finished']:
                _dismiss_prompts()
                finish(task, chat, time.monotonic() - state['started'], False)
        QTimer.singleShot(int((task.seconds + 45) * 1000), watchdog)

    def poll():
        task, chat = state['task'], state['chat']
        elapsed = time.monotonic() - state['started']
        if chat.typer.running:
            chat.typer.finish()
        chat.reveal_all()
        done = state['sent'] and not chat.busy and not chat._pending
        if done and task.press and chat._pending_edits and state['pressed'] < 3:
            state['pressed'] += 1                     # the user reads her card and presses 「帮我做」
            chat._run_pending()
            QTimer.singleShot(600, poll)
            return
        if not done and elapsed < task.seconds:
            QTimer.singleShot(400, poll)
            return
        QTimer.singleShot(1200, lambda: finish(task, chat, elapsed, done))     # windows opened after her words

    def finish(task, chat, elapsed, done):
        if task.id in state['finished']:
            return                                  # the watchdog and the poll both arrived
        state['finished'].add(task.id)
        try:
            passed, detail = task.check(window, chat)
        except Exception as exc:  # noqa: BLE001 - a broken check is a failed task, never a crash
            passed, detail = False, f'检查出错：{type(exc).__name__}: {exc}'
        if not done:
            passed, detail = False, f'超时（{task.seconds:.0f} 秒）；{detail}'
        tools = [' '.join(line.lstrip('- ').split())[:160] for line in chat.action_log]    # call and receipt
        said = [text for who, text in chat.transcript if who != 'user'][-3:]
        result = Result(task.id, passed, detail, round(elapsed, 1), int(getattr(chat, '_tool_rounds', 0)), tools, said)
        results.append(result)
        print(f'{"PASS" if passed else "FAIL"} {task.id:20s} {elapsed:5.1f}s rounds={result.rounds} {detail}', flush=True)
        print(f'     tools: {" | ".join(tool.split("：", 1)[0] for tool in tools[:8])}', flush=True)
        print(f'     said: {" / ".join(said)[:220]}', flush=True)
        start_next()

    QTimer.singleShot(1500, start_next)
    app.exec()
    passed = sum(result.passed for result in results)
    print(f'\n{passed}/{len(results)} passed; {sum(r.seconds for r in results):.0f}s; '
          f'{sum(r.rounds for r in results)} tool rounds', flush=True)
    target = out or REPO / 'tmp' / 'bunny-eval' / time.strftime('%Y%m%d-%H%M%S.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'report: {target}', flush=True)
    return results


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    user = Path(os.environ['LOCALAPPDATA']) / '2ByteASR' / '2byteasr_settings.json'
    settings = json.loads(user.read_text(encoding='utf-8'))
    wanted = [task for task in TASKS if not argv or task.id in argv]
    results = run(wanted, settings)
    sys.stdout.flush()
    os._exit(0 if all(result.passed for result in results) else 1)


if __name__ == '__main__':
    main()
