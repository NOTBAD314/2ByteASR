"""One definition of every customizable keyboard shortcut (2026-10-13).

Menus, tooltips, the shortcut settings page, conflict checks and the key
dispatchers all read this registry, so a changed key shows up everywhere.

Scopes decide what may share a key:

* ``studio``        — the subtitle workbench (not while typing in a text box);
* ``studio.review`` — priority review inside the workbench; while review is on
                      these win over ``studio`` keys (a shared key is shown as
                      "审核时优先", not as an error);
* ``home``          — the recognition home page;
* ``proofread``     — the AI 词库校对 page;
* ``app``           — everywhere (interface zoom). Clashes with any scope.

Different pages never conflict. Bindings are stored in PortableText (``Ctrl``
is Command on macOS) under ``shortcuts`` in the Studio settings file; Studio
commands keep their historic ids, other scopes use ``<scope>.<name>``.
Mouse gestures listed in :data:`FIXED_GESTURES` cannot be customized.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

FORMAT = '2byteasr-shortcuts'
FORMAT_VERSION = 1


@dataclass(frozen=True)
class ShortcutAction:
    id: str
    label: str
    default: str
    scope: str
    category: str
    note: str = ''


def _a(id, label, default, scope='studio', category='编辑', note=''):
    return ShortcutAction(id, label, default, scope, category, note)


ACTIONS: tuple[ShortcutAction, ...] = (
    # Studio — playback
    _a('play_pause', '播放 / 暂停', 'Space', category='播放'),
    _a('reverse', '反向播放', 'J', category='播放'),
    _a('pause', '暂停', 'K', category='播放'),
    _a('forward', '正向播放（再按加速）', 'L', category='播放'),
    _a('frame_left', '上一帧', 'Left', category='播放'),
    _a('frame_right', '下一帧', 'Right', category='播放'),
    _a('previous_cue', '上一条字幕', 'Up', category='播放'),
    _a('next_cue', '下一条字幕', 'Down', category='播放'),
    # Studio — tools
    _a('selection_tool', '选择工具', 'V', category='时间轴工具'),
    _a('track_forward_tool', '轨道向前选择', 'A', category='时间轴工具'),
    _a('razor_tool', '剃刀工具（移动预览切点，点击切开）', 'C', category='时间轴工具'),
    _a('merge_tool', '合并工具（点选字幕后拖动方向合并）', 'B', category='时间轴工具'),
    _a('toggle_snap', '切换时间轴吸附', 'S', category='时间轴工具'),
    _a('track_gain', '轨道音量（分贝）', 'G', category='时间轴工具'),
    # Studio — editing
    _a('trim_start', '字幕起点至播放头 / 视频向前波纹剪除', 'Q'),
    _a('trim_end', '字幕终点至播放头 / 视频向后波纹剪除', 'W'),
    _a('merge_previous', '波纹向前合并（与上一条合并）', 'Shift+Q'),
    _a('merge_next', '波纹向后合并（与下一条合并）', 'Shift+W'),
    _a('edit_at_playhead', '编辑播放头处的字幕', 'E'),
    _a('add_subtitle', '添加字幕', 'T'),
    _a('split', '拆分当前字幕', 'Ctrl+Shift+S'),
    _a('merge', '与下一条合并', 'Ctrl+Shift+M'),
    _a('delete', '删除当前字幕', 'Delete'),
    _a('select_all', '全选（时间轴或字幕列表）', 'Ctrl+A'),
    _a('copy_style', '复制字幕样式', 'Ctrl+Shift+C'),
    _a('paste_style', '粘贴字幕样式', 'Ctrl+Shift+V'),
    _a('undo', '撤销', 'Ctrl+Z'),
    _a('redo', '重做', 'Ctrl+Y'),
    _a('redo_alt', '重做（备用）', 'Ctrl+Shift+Z'),
    _a('find', '查找字幕文字', 'Ctrl+F'),
    _a('find_replace', '批量替换字幕文字', 'Ctrl+H'),
    # Studio — video edit
    _a('video_transition', '应用默认视频转场', 'Ctrl+D', category='剪辑'),
    _a('audio_transition', '应用默认音频转场', 'Ctrl+Shift+D', category='剪辑'),
    _a('split_at_playhead', '在播放头分割所有未锁视频轨', 'Ctrl+K', category='剪辑'),
    _a('mark_in', '设置入点', 'I', category='剪辑'),
    _a('mark_out', '设置出点', 'O', category='剪辑'),
    _a('add_marker', '添加时间轴标记', 'Shift+M', category='剪辑'),
    _a('add_io_candidate', '将 I/O 加入剪辑候选', 'Shift+I', category='剪辑'),
    # Studio — file and panels
    _a('save', '保存工程', 'Ctrl+S', category='文件'),
    _a('save_current_frame', '保存当前帧', 'Ctrl+Alt+F', category='文件'),
    _a('performance_panel', '播放性能面板', 'Ctrl+Shift+P', category='文件'),
    # Studio — review mode
    _a('toggle_review', '进入 / 退出审核模式', 'R', category='审核'),
    _a('review_play_context', '播放当前审核片段', 'Space', 'studio.review', '审核'),
    _a('confirm_review', '确认当前审核', 'Return', 'studio.review', '审核'),
    _a('confirm_next_review', '确认并播放下一条审核', 'Ctrl+Return', 'studio.review', '审核'),
    _a('reasr_review', '重新识别当前审核', 'Shift+R', 'studio.review', '审核'),
    _a('skip_review', '跳过当前审核', 'Ctrl+Down', 'studio.review', '审核'),
    _a('review_previous', '上一条待审核', 'Up', 'studio.review', '审核'),
    _a('review_next', '下一条待审核', 'Down', 'studio.review', '审核'),
    _a('exit_review', '退出优先审核', 'Esc', 'studio.review', '审核'),
    _a('review_adopt_1', '采用第 1 个候选', '1', 'studio.review', '审核'),
    _a('review_adopt_2', '采用第 2 个候选', '2', 'studio.review', '审核'),
    _a('review_adopt_3', '采用第 3 个候选', '3', 'studio.review', '审核'),
    _a('review_adopt_4', '采用第 4 个候选', '4', 'studio.review', '审核'),
    # Home page
    _a('home.start_run', '开始生成字幕', 'Ctrl+Return', 'home', '首页'),
    _a('home.choose_media', '选择素材', 'Ctrl+O', 'home', '首页'),
    _a('home.search', '搜索功能与设置', 'Ctrl+K', 'home', '首页'),
    # AI 词库校对 page
    _a('proofread.find', '查找', 'Ctrl+F', 'proofread', '词库校对页'),
    _a('proofread.replace', '替换', 'Ctrl+H', 'proofread', '词库校对页'),
    _a('proofread.undo', '撤销', 'Ctrl+Z', 'proofread', '词库校对页'),
    _a('proofread.redo', '重做', 'Ctrl+Y', 'proofread', '词库校对页'),
    _a('proofread.redo_alt', '重做（备用）', 'Ctrl+Shift+Z', 'proofread', '词库校对页'),
    # Everywhere
    _a('app.zoom_in', '放大界面', 'Ctrl+=', 'app', '全局', '界面缩放（不影响字幕与导出；工作台内部不缩放）'),
    _a('app.zoom_in_alt', '放大界面（备用）', 'Ctrl++', 'app', '全局'),
    _a('app.zoom_out', '缩小界面', 'Ctrl+-', 'app', '全局'),
    _a('app.zoom_reset', '界面缩放复原', 'Ctrl+0', 'app', '全局'),
)

BY_ID = {action.id: action for action in ACTIONS}
SCOPE_LABELS = {'studio': '字幕工作台', 'studio.review': '审核模式（工作台内）', 'home': '首页',
                'proofread': 'AI 词库校对页', 'app': '全局'}
CATEGORY_ORDER = ('播放', '编辑', '时间轴工具', '剪辑', '审核', '文件', '首页', '词库校对页', '全局')

# Kept out of the editor on purpose; listed in settings so nobody guesses.
FIXED_GESTURES = (
    ('Ctrl + 滚轮（工作台）', '时间轴以鼠标为中心缩放；工作台以外是界面缩放'),
    ('Ctrl + 拖动字幕相接处', '双边修剪（相邻两条一起改）'),
    ('Ctrl / Shift + 点击', '多选、范围选择'),
    ('Alt + 拖动', '复制拖动；拖动时按住 Alt 暂停吸附'),
    ('Shift + 点击时间尺', '平移时间轴'),
    ('双击字幕块', '在时间轴上直接改字'),
    ('字幕编辑框里的 Enter / Esc / Ctrl+Enter / Shift+Enter / Tab', '提交 / 取消 / 提交并编辑下一条 / 换行 / 下一条'),
    ('对话框里的 Esc 与 Enter', '关闭 / 确认（系统约定）'),
)

# Keys the operating system or a text field owns; refused when recording.
RESERVED = {
    'win32': {'Alt+F4', 'Ctrl+Alt+Del', 'Meta+L', 'Meta+D', 'Meta+Tab', 'Alt+Tab', 'Ctrl+Esc', 'Ctrl+Shift+Esc'},
    'darwin': {'Ctrl+Q', 'Ctrl+H', 'Ctrl+M', 'Ctrl+Tab', 'Ctrl+Space', 'Ctrl+Alt+Esc', 'Ctrl+Alt+H'},
}


def platform_defaults(platform: str | None = None) -> dict[str, str]:
    """Defaults with macOS standard keys (Command = ``Ctrl`` in PortableText)."""
    platform = platform or sys.platform
    values = {action.id: action.default for action in ACTIONS}
    if platform == 'darwin':
        # Cmd+H hides the app on macOS; Cmd+Shift+F is free and close to Find.
        values['find_replace'] = 'Ctrl+Shift+F'
        values['proofread.replace'] = 'Ctrl+Shift+F'
        values['redo'] = 'Ctrl+Shift+Z'
        values['redo_alt'] = ''
        values['proofread.redo'] = 'Ctrl+Shift+Z'
        values['proofread.redo_alt'] = ''
    return values


def normalize(sequence: str) -> str:
    """One spelling per key: Enter → Return, keypad prefix dropped, Del → Delete."""
    text = str(sequence or '').strip()
    if not text:
        return ''
    try:
        from PySide6.QtGui import QKeySequence
        portable = QKeySequence(text).toString(QKeySequence.SequenceFormat.PortableText)
        if portable:
            text = portable
    except Exception:
        pass
    if ', ' in text:
        text = text.split(', ', 1)[0]  # chords are not supported: first combination only
    parts = text.split('+')
    if len(parts) > 1 and parts[-1] == '' and parts[-2] == '':
        parts = parts[:-2] + ['+']  # "Ctrl++"
    out = []
    for part in parts:
        if part == 'Num':
            continue
        out.append({'Enter': 'Return', 'Del': 'Delete', 'Escape': 'Esc', 'Ins': 'Insert'}.get(part, part))
    return '+'.join(out)


def scopes_overlap(first: str, second: str) -> bool:
    if first == second or 'app' in (first, second):
        return True
    return False


def shadows(first: str, second: str) -> bool:
    """Review keys win while review is on; a shared key is a note, not an error."""
    return {first, second} == {'studio', 'studio.review'}


def load_values(stored: dict | None, platform: str | None = None) -> tuple[dict[str, str], list[str]]:
    """Merged bindings and the ids whose new default was left unbound.

    Stored files hold every Studio id (defaults included). A new action whose
    default would collide with a key the user deliberately chose stays unbound
    and is reported, so a new default never steals a custom binding.
    """
    defaults = platform_defaults(platform)
    stored = {str(k): str(v) for k, v in dict(stored or {}).items() if isinstance(k, str)}
    values = {}
    for action_id, default in defaults.items():
        values[action_id] = normalize(stored[action_id]) if action_id in stored else default
    # Historic migrations (moved here from the Studio page, unchanged): the
    # merge tool's old default M became B; review keys R / Shift+R swapped.
    if values.get('merge_tool', '').upper() == 'M':
        values['merge_tool'] = defaults['merge_tool']
    if stored.get('reasr_review', '').strip().upper() == 'R':
        values['reasr_review'] = defaults['reasr_review']
    if values.get('toggle_review', '').upper() == 'SHIFT+R':
        values['toggle_review'] = defaults['toggle_review']
    # 2026-10-13: E was hard-wired to "edit at playhead" in every mode, which
    # made the stored "edit_review: E" dead. Keep E's behaviour, drop the alias.
    stored.pop('edit_review', None)
    # Ctrl+Enter used to be stored but never matched; same key, real spelling.
    for action_id in ('confirm_review', 'confirm_next_review'):
        if action_id in stored:
            values[action_id] = normalize(stored[action_id])
    unbound = []
    custom = {action_id: value for action_id, value in values.items()
              if action_id in stored and value and value != defaults.get(action_id)}
    for action_id, value in list(values.items()):
        if action_id in stored or not value:
            continue
        scope = BY_ID[action_id].scope
        owners = [other for other, key in custom.items()
                  if key.casefold() == value.casefold() and scopes_overlap(scope, BY_ID[other].scope)]
        if owners:
            values[action_id] = ''
            unbound.append(action_id)
    return values, unbound


@dataclass(frozen=True)
class Conflict:
    key: str
    first: str
    second: str
    blocking: bool

    def describe(self) -> str:
        a, b = BY_ID[self.first], BY_ID[self.second]
        if self.blocking:
            return f'“{self.key}”同时给了“{a.label}”和“{b.label}”（{SCOPE_LABELS[a.scope]}）'
        review, normal = (a, b) if a.scope == 'studio.review' else (b, a)
        return f'“{self.key}”：审核模式中由“{review.label}”优先，平时是“{normal.label}”'


def conflicts(values: dict[str, str]) -> list[Conflict]:
    found = []
    items = [(action_id, normalize(key)) for action_id, key in values.items() if key and action_id in BY_ID]
    for index, (first, key) in enumerate(items):
        for second, other in items[index + 1:]:
            if key.casefold() != other.casefold():
                continue
            scope_a, scope_b = BY_ID[first].scope, BY_ID[second].scope
            if scopes_overlap(scope_a, scope_b):
                found.append(Conflict(key, first, second, True))
            elif shadows(scope_a, scope_b):
                found.append(Conflict(key, first, second, False))
    return found


def blocking_conflicts(values: dict[str, str]) -> list[Conflict]:
    return [item for item in conflicts(values) if item.blocking]


def reserved_reason(sequence: str, platform: str | None = None) -> str:
    platform = platform or sys.platform
    key = normalize(sequence)
    if key in RESERVED.get(platform, set()):
        return '这个组合由系统使用，不能设为快捷键。'
    return ''


def display(sequence: str) -> str:
    """Platform key names for menus and tooltips (⌘ on macOS)."""
    text = normalize(sequence)
    if not text:
        return ''
    try:
        from PySide6.QtGui import QKeySequence
        native = QKeySequence(text).toString(QKeySequence.SequenceFormat.NativeText)
        return native or text
    except Exception:
        return text


def export_payload(values: dict[str, str]) -> str:
    return json.dumps({'format': FORMAT, 'version': FORMAT_VERSION,
                       'bindings': {key: values.get(key, '') for key in BY_ID}},
                      ensure_ascii=False, indent=2) + '\n'


def import_payload(text: str) -> dict[str, str]:
    """Bindings from an exported file; unknown ids are ignored, keys normalized."""
    payload = json.loads(text)
    if not isinstance(payload, dict) or payload.get('format') != FORMAT:
        raise ValueError('不是兔白字幕导出的快捷键文件。')
    bindings = payload.get('bindings')
    if not isinstance(bindings, dict):
        raise ValueError('快捷键文件缺少 bindings。')
    return {key: normalize(value) for key, value in bindings.items()
            if key in BY_ID and isinstance(value, str)}


# ----------------------------------------------------------------- store

def settings_path():
    from .studio_project import studio_settings_path
    return studio_settings_path()


def read_stored() -> dict:
    try:
        payload = json.loads(settings_path().read_text(encoding='utf-8'))
        value = payload.get('shortcuts', {}) if isinstance(payload, dict) else {}
        return dict(value) if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def current_values() -> dict[str, str]:
    return load_values(read_stored())[0]


def save_values(values: dict[str, str]) -> None:
    """Merge into the Studio settings file, keeping every other key."""
    from .theme_persistence import write_text_atomic
    path = settings_path()
    try:
        payload = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, ValueError, TypeError):
        payload = {}
    stored = dict(payload.get('shortcuts') or {})
    stored.update({key: normalize(value) for key, value in values.items() if key in BY_ID})
    stored.pop('edit_review', None)
    payload['shortcuts'] = stored
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    _notify()


_listeners = []


def subscribe(callback) -> None:
    """``callback(values)`` after every save (pages refresh keys and tooltips)."""
    _listeners.append(callback)


def unsubscribe(callback) -> None:
    try:
        _listeners.remove(callback)
    except ValueError:
        pass


def _notify() -> None:
    values = current_values()
    for callback in list(_listeners):
        try:
            callback(values)
        except RuntimeError:
            unsubscribe(callback)  # the widget behind it was deleted


def keep_keys(bindings: dict) -> None:
    """Give widgets their registry keys now and after every save.

    ``bindings`` maps action id -> a QShortcut, or a callable ``apply(key)``
    (for buttons with ``setShortcut`` and tooltips). Entries whose Qt object
    was deleted are dropped automatically.
    """
    from PySide6.QtGui import QKeySequence

    def apply(values):
        alive = False
        for action_id, target in list(bindings.items()):
            key = values.get(action_id, '')
            try:
                if callable(target) and not hasattr(target, 'setKey'):
                    target(key)
                else:
                    target.setKey(QKeySequence(key))
                alive = True
            except RuntimeError:
                bindings.pop(action_id, None)  # the widget behind it was deleted
        if not alive:
            raise RuntimeError('no live shortcut targets')

    apply(current_values())
    subscribe(apply)


def key_for(action_id: str, values: dict | None = None) -> str:
    values = values if values is not None else current_values()
    return values.get(action_id, '')


def tooltip_key(action_id: str, values: dict | None = None) -> str:
    """Key text for a tooltip, or 未绑定."""
    key = key_for(action_id, values)
    return display(key) if key else '未绑定'
