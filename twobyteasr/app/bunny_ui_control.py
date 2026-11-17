"""兔白's universal control layer: see every control, press, set, run any command (2026-11-17).

User (2026-11-17): 「问问兔白」 should go beyond other agent harnesses and really operate and change
almost everything in the software. Instead of one hand-written tool per feature, she works the
way computer-use agents do (docs/exec-plans/active/2026-11-17-bunny-universal-control.md):

* ``ui_snapshot`` — the accessibility-tree view: every visible control in 2ByteASR's own windows
  (buttons, check boxes, radio buttons, drop-downs, number boxes, sliders, text boxes, tabs) with a
  ref (e1, e2 …), its kind, its name, its value and whether it can be used. Refs go stale with the
  next snapshot; a name works too.
* ``ui_press`` — press a button or pick a tab. The press happens a moment later
  (``QTimer.singleShot``) so a dialog it opens never blocks her turn; the dialog then shows up in
  the next snapshot and she can work inside it.
* ``ui_set`` — set a check box, drop-down, number, slider or text box; reports before / after and
  leaves an undo record for 「撤销兔白刚才做的」.
* ``run_command`` / ``list_commands`` — every command registered in ``shortcut_registry`` (the
  workbench's ~90 commands, the home page's and the global ones); edits join the undo records.

Risk is judged per call (``Tool.variant``): looking and moving around run at once; changing
settings or subtitles follows 「兔白权限」; deleting, clearing, starting a recognition or export,
overwriting, installing, logging in or uploading always waits for 「帮我做」; AI work on the
user's key follows the 【花 Key】 rule. Her own chat card is never part of the picture, password
fields are neither read nor written.
"""
from __future__ import annotations

import dataclasses
import re
import weakref

SNAPSHOT_LIMIT = 70
LIST_ROWS = 30           # rows of one list shown in a snapshot
OPTION_LIMIT = 10
TEXT_LIMIT = 40
SKIP_NAMES = ('bunny',)                  # her own card, carrier, log, mascot
_REFS: dict[str, weakref.ref] = {}
_NEXT_REF = 0

# What a control's words tell about pressing it (checked in this order).
DANGER = re.compile(r'删除|删掉|清空|清除全部|全部清除|移除|卸载|重置|恢复默认|覆盖|全部替换|替换全部|不保存|放弃|丢弃|'
                    r'退出|关闭软件|注销|开始识别|开始生成|生成字幕|开始导出|导出|加入队列|上传|发送|提交|充值|购买|付费|'
                    r'登录|授权|安装|下载|重新识别|重新开始|格式化|清理|delete|remove|reset|uninstall|install|'
                    r'download|upload|export|overwrite|discard', re.I)
PAID = re.compile(r'AI|翻译|校对|润色|断句|术语更新|补新词|智能', re.I)
COMMIT = re.compile(r'保存|确定|应用|好的|完成|^OK$|确认|采用|采纳|替换', re.I)
HARMLESS_INPUT = re.compile(r'搜索|查找|筛选|过滤|排序|显示方式|视图|缩放|search|filter|sort|find', re.I)
SECRET = re.compile(r'key|token|密钥|密码|口令|password|secret', re.I)


# ------------------------------------------------------------------ the tree
def _own(widget) -> bool:
    node = widget
    while node is not None:
        if str(node.objectName()).startswith(SKIP_NAMES):
            return False
        node = node.parentWidget()
    return True


def _tops(window):
    from PySide6.QtWidgets import QApplication
    tops = []
    for top in QApplication.topLevelWidgets():
        if top is window or not top.isVisible() or top.isMinimized() or not _own(top):
            continue
        if top.metaObject().className() in ('QTipLabel', 'QComboBoxPrivateContainer') or top.width() < 40:
            continue
        tops.append(top)
    # Open dialogs and windows first (what she just opened, live run 2026-11-17), the active one and
    # the dialog that must be answered before them; the main window last.
    active = QApplication.activeWindow()
    if active is not None and active in tops:
        tops.remove(active)
        tops.insert(0, active)
    modal = QApplication.activeModalWidget()
    if modal is not None and modal in tops:
        tops.remove(modal)
        tops.insert(0, modal)
    return [*tops, window] if window is not None else tops


def _plain(text) -> str:
    return ' '.join(str(text or '').replace('&', '').split())


def _label_for(widget) -> str:
    """The words that name a control: its own text, accessible name, the form label beside it, tooltip."""
    from PySide6.QtWidgets import QAbstractButton, QFormLayout, QGroupBox, QLabel
    if isinstance(widget, QAbstractButton) and _plain(widget.text()):
        return _plain(widget.text())
    if _plain(widget.accessibleName()):
        return _plain(widget.accessibleName())
    parent = widget.parentWidget()
    if parent is not None:
        layout = parent.layout()
        if isinstance(layout, QFormLayout):
            label = layout.labelForField(widget)
            if isinstance(label, QLabel) and _plain(label.text()):
                return _plain(label.text()).rstrip('：:')
        for label in parent.findChildren(QLabel):
            if label.buddy() is widget and _plain(label.text()):
                return _plain(label.text()).rstrip('：:')
        if layout is not None:                       # the label just before it in the same row
            index = layout.indexOf(widget)
            for back in range(index - 1, max(-1, index - 3), -1):
                item = layout.itemAt(back)
                other = item.widget() if item is not None else None
                if isinstance(other, QLabel) and _plain(other.text()) and other.isVisible():
                    return _plain(other.text()).rstrip('：:')[:TEXT_LIMIT]
        group = parent
        while group is not None and not isinstance(group, QGroupBox):
            group = group.parentWidget()
        if group is not None and _plain(group.title()):
            hint = _plain(getattr(widget, 'placeholderText', lambda: '')())
            return f'{_plain(group.title())}{" · " + hint if hint else ""}'
    hint = _plain(getattr(widget, 'placeholderText', lambda: '')())
    return hint or _plain(widget.toolTip())[:TEXT_LIMIT] or widget.objectName()


def _secret(widget, label: str) -> bool:
    from PySide6.QtWidgets import QLineEdit
    return (isinstance(widget, QLineEdit) and widget.echoMode() != QLineEdit.EchoMode.Normal) or bool(
        SECRET.search(f'{label} {widget.objectName()}'))


@dataclasses.dataclass
class Element:
    widget: object
    kind: str
    label: str
    value: str = ''
    tab: int = -1                    # a tab bar's tab index
    window: str = ''

    @property
    def enabled(self) -> bool:
        if self.kind == 'tab':
            return self.widget.isEnabled() and self.widget.isTabEnabled(self.tab)
        if self.kind == 'item':
            from PySide6.QtCore import Qt
            item = self.widget.item(self.tab)
            return bool(self.widget.isEnabled() and item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled)
        return self.widget.isEnabled()


def _value(widget, kind: str, label: str) -> str:
    if kind in ('checkbox', 'radio', 'toggle'):
        return '勾着' if widget.isChecked() else '没勾'
    if kind == 'dropdown':
        options = [_plain(widget.itemText(i)) for i in range(min(widget.count(), OPTION_LIMIT))]
        more = f' …共 {widget.count()} 项' if widget.count() > OPTION_LIMIT else ''
        return f'现在：{_plain(widget.currentText()) or "（空）"}；选项：' + ' / '.join(options) + more
    if kind == 'number':
        unit = _plain(widget.suffix()) if hasattr(widget, 'suffix') else ''
        return f'{widget.text() or widget.value()}{"" if unit and unit in widget.text() else unit}（{widget.minimum()}–{widget.maximum()}）'
    if kind == 'slider':
        return f'{widget.value()}（{widget.minimum()}–{widget.maximum()}）'
    if kind == 'text':
        if _secret(widget, label):
            return '（密码类，不显示）'
        text = widget.toPlainText() if hasattr(widget, 'toPlainText') else widget.text()
        text = _plain(text)
        return f'「{text[:TEXT_LIMIT]}{"…" if len(text) > TEXT_LIMIT else ""}」' if text else '（空）'
    return ''


def _kind(widget) -> str:
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QCheckBox, QComboBox,
                                   QLineEdit, QListWidget, QPlainTextEdit, QRadioButton, QScrollBar, QTabBar, QTextEdit)
    if isinstance(widget, QTabBar):
        return 'tabs'
    if isinstance(widget, QListWidget):
        return 'list'
    if isinstance(widget, QCheckBox):
        return 'checkbox'
    if isinstance(widget, QRadioButton):
        return 'radio'
    if isinstance(widget, QAbstractButton):
        return 'toggle' if widget.isCheckable() else 'button'
    if isinstance(widget, QComboBox):
        return 'dropdown'
    if isinstance(widget, QAbstractSpinBox):
        return 'number' if hasattr(widget, 'value') else ''
    if isinstance(widget, QAbstractSlider) and not isinstance(widget, QScrollBar):
        return 'slider'
    if isinstance(widget, QLineEdit):
        parent = widget.parentWidget()
        return '' if isinstance(parent, (QComboBox, QAbstractSpinBox)) else 'text'
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return '' if widget.isReadOnly() else 'text'
    return ''


KIND_WORDS = {'button': '按钮', 'toggle': '开关按钮', 'checkbox': '勾选', 'radio': '单选', 'dropdown': '下拉',
              'number': '数字', 'slider': '滑杆', 'text': '文字框', 'tab': '页签', 'item': '列表项'}


def elements(window, *, want: str = '', where: str = '') -> list[Element]:
    """The usable controls on screen, the dialog to answer first, then the main window, then the rest."""
    from PySide6.QtWidgets import QWidget
    found = []
    for top in _tops(window):
        title = _plain(top.windowTitle()) if top is not window else '主窗口'
        if where and where not in title:
            continue
        for widget in [top, *top.findChildren(QWidget)]:
            if not widget.isVisible() or widget.width() < 4 or widget.height() < 4 or not _own(widget):
                continue
            if widget.window() is not top:              # a dialog parented to the main window is listed once, as itself
                continue
            if widget.visibleRegion().isEmpty():
                continue
            kind = _kind(widget)
            if not kind:
                continue
            if kind == 'tabs':
                for index in range(widget.count()):
                    if widget.isTabVisible(index):
                        label = _plain(widget.tabText(index)) or _plain(widget.tabToolTip(index))
                        current = '（当前）' if index == widget.currentIndex() else ''
                        found.append(Element(widget, 'tab', label, current, index, title))
                continue
            if kind == 'list':
                # 2026-11-17 eval: the settings window's left navigation is a list, not buttons
                for row in range(min(widget.count(), LIST_ROWS)):
                    item = widget.item(row)
                    if item is None or item.isHidden() or not _plain(item.text()):
                        continue
                    current = '（当前）' if row == widget.currentRow() else ''
                    found.append(Element(widget, 'item', _plain(item.text())[:TEXT_LIMIT], current, row, title))
                continue
            label = _label_for(widget)
            found.append(Element(widget, kind, label, _value(widget, kind, label), window=title))
    if want:
        words = want.casefold()

        def hints(item) -> str:                    # eval run 5: the search box's words were only its placeholder
            widget = item.widget
            return ' '.join((str(widget.objectName()), _plain(widget.toolTip()), _plain(widget.accessibleName()),
                             _plain(getattr(widget, 'placeholderText', lambda: '')()))).casefold()
        found = [item for item in found if words in item.label.casefold() or words in item.value.casefold()
                 or words in hints(item)]
    return found


def _ref(element: Element) -> str:
    # Never reuse an approval's number for a different control after a new snapshot.
    global _NEXT_REF
    _NEXT_REF += 1
    key = f'e{_NEXT_REF}'
    _REFS[key] = (weakref.ref(element.widget), element.tab, element.kind, element.label)
    return key


def _ui_snapshot(window, args) -> str:
    from .bunny_tools import ToolError
    want = _plain(args.get('text'))
    where = _plain(args.get('window'))
    items = elements(window, want=want, where=where)
    _REFS.clear()
    if not items:
        raise ToolError(f'屏幕上没有找到{"含「" + want + "」的" if want else ""}能操作的控件')
    rows, current = [], None
    for item in items[:SNAPSHOT_LIMIT]:
        if item.window != current:
            current = item.window
            rows.append(f'【{current}】')
        state = '' if item.enabled else '（灰的' + (f'：{_plain(item.widget.toolTip())[:50]}' if _plain(item.widget.toolTip()) else '') + '）'
        value = ('' if item.value.startswith('（') else ' ') + item.value if item.value else ''
        rows.append(f'{_ref(item)} {KIND_WORDS[item.kind]}「{item.label[:TEXT_LIMIT]}」{value}{state}')
    more = f'\n（还有 {len(items) - SNAPSHOT_LIMIT} 个没列，用 text 或 window 缩小范围）' if len(items) > SNAPSHOT_LIMIT else ''
    return ('能操作的控件（编号只在这次快照有效，操作后要再快照）：\n' + '\n'.join(rows) + more)


def _resolve(window, args, kinds) -> Element:
    """The element a call means: a ref from the last snapshot, else the best match for ``text``."""
    from .bunny_tools import ToolError
    ref = _plain(args.get('ref'))
    if ref:
        held = _REFS.get(ref)
        widget = held[0]() if held else None
        if widget is None:
            raise ToolError(f'编号 {ref} 已经过期了（界面变了），先 ui_snapshot 再按新的编号')
        try:
            visible = widget.isVisible()
        except RuntimeError:
            visible = False
        if not visible:
            raise ToolError(f'编号 {ref} 的控件现在不在屏幕上了，先 ui_snapshot')
        element = Element(widget, held[2], held[3], tab=held[1])
    else:
        text = _plain(args.get('text'))
        if not text:
            raise ToolError('要给 ref（快照里的编号）或 text（控件上的字）')
        items = [item for item in elements(window, where=_plain(args.get('window'))) if item.kind in kinds]
        exact = [item for item in items if item.label == text]
        partial = [item for item in items if text in item.label]
        pool = exact or partial
        if not pool:
            raise ToolError(f'屏幕上没有「{text}」这个可以操作的控件；用 ui_snapshot 看看现在有什么')
        enabled = [item for item in pool if item.enabled]
        element = (enabled or pool)[0]
        if len({(id(item.widget), item.tab) for item in (enabled or pool)}) > 1:
            names = '、'.join(f'「{item.label[:16]}」' for item in (enabled or pool)[:4])
            raise ToolError(f'「{text}」对得上好几个：{names}，用 ui_snapshot 的编号指定')
    if element.kind not in kinds:
        raise ToolError(f'「{element.label}」是{KIND_WORDS.get(element.kind, element.kind)}，不能这样操作')
    if not _own(element.widget) or not any(element.widget.window() is top for top in _tops(window)):
        raise ToolError('这个控件已不属于当前窗口，请重新 ui_snapshot')
    return element


def _words(element: Element) -> str:
    widget = element.widget
    return ' '.join((element.label, str(widget.objectName()), _plain(widget.toolTip())))


def bind_confirmation(window, name, args):
    """Bind a proposed edit to this control, never to a later same-name replacement."""
    kinds = PRESS_KINDS if name == 'ui_press' else SET_KINDS if name == 'ui_set' else ()
    if not kinds:
        return args
    element = _resolve(window, args, kinds)
    return dict(args, ref=_ref(element))


def _reveal(widget) -> None:
    try:
        from .bunny_chat import reveal_widget
        reveal_widget(widget)
    except Exception:  # noqa: BLE001 - scrolling into view is a nicety
        pass


# ------------------------------------------------------------------ press
PRESS_KINDS = ('button', 'toggle', 'checkbox', 'radio', 'tab', 'item')


def _press(window, args) -> str:
    from PySide6.QtCore import QTimer
    from .bunny_tools import ToolError
    element = _resolve(window, args, PRESS_KINDS)
    if not element.enabled:
        why = _plain(element.widget.toolTip())
        raise ToolError(f'「{element.label}」现在是灰的，按不了' + (f'（{why[:60]}）' if why else ''))
    widget = element.widget
    _reveal(widget)
    if element.kind == 'tab':
        index = element.tab
        widget.setCurrentIndex(index)
        return f'切到了「{element.label}」页签'
    if element.kind == 'item':
        item = widget.item(element.tab)
        if item is None:
            raise ToolError(f'「{element.label}」这一项已经不在列表里了，先 ui_snapshot')
        widget.setCurrentRow(element.tab)            # what the window listens for (currentRowChanged)
        widget.scrollToItem(item)
        widget.itemClicked.emit(item)                # … and for lists that act on a click
        return f'选中了列表里的「{element.label}」'
    # A moment later: a dialog it opens runs its own loop and must not block this turn.
    QTimer.singleShot(0, widget, widget.click)
    return (f'按下了{KIND_WORDS[element.kind]}「{element.label}」（马上生效；要确认结果，下一轮用 ui_snapshot 或 look_screen 看，'
            '弹出的窗口也会在快照里）')


def _press_variant(tool, window, args):
    try:
        element = _resolve(window, args, PRESS_KINDS)
    except Exception:  # noqa: BLE001 - the run itself reports what is wrong
        return tool
    if element.kind in ('tab', 'item') or not element.enabled:     # moving around; a grey one is reported as grey
        return tool
    words = _words(element)
    if DANGER.search(words):
        return dataclasses.replace(tool, persistent=True, edit=True)
    if PAID.search(element.label):
        return dataclasses.replace(tool, paid=True)
    if COMMIT.search(element.label) or element.kind in ('checkbox', 'radio', 'toggle'):
        return dataclasses.replace(tool, edit=True)
    if re.search(r'打开|查看|取消|返回|上一步|下一步|展开|收起|open|view|cancel|back|next', words, re.I):
        return tool
    # Icon-only, translated or unknown buttons have no reliable risk label.
    return dataclasses.replace(tool, persistent=True, edit=True)


# ------------------------------------------------------------------ set a value
SET_KINDS = ('checkbox', 'radio', 'toggle', 'dropdown', 'number', 'slider', 'text')


def _current(element: Element):
    widget, kind = element.widget, element.kind
    if kind in ('checkbox', 'radio', 'toggle'):
        return widget.isChecked()
    if kind == 'dropdown':
        return widget.currentIndex()
    if kind in ('number', 'slider'):
        return widget.value()
    return widget.toPlainText() if hasattr(widget, 'toPlainText') else widget.text()


def _apply(element: Element, value) -> None:
    widget, kind = element.widget, element.kind
    if kind in ('checkbox', 'radio', 'toggle'):
        # A click, like the user's: windows that listen for clicked / idClicked (the settings' 「5 分钟」
        # button group, eval run 5) never heard a quiet setChecked, and saved the old value.
        if widget.isChecked() != bool(value):
            widget.click()
        if widget.isChecked() != bool(value):
            widget.setChecked(bool(value))
    elif kind == 'dropdown':
        widget.setCurrentIndex(int(value))
    elif kind in ('number', 'slider'):
        widget.setValue(value)
    elif hasattr(widget, 'setPlainText'):
        widget.setPlainText(str(value))
    else:
        widget.setText(str(value))
        widget.editingFinished.emit()            # what the app listens for after typing


def _shown(element: Element, value) -> str:
    if element.kind in ('checkbox', 'radio', 'toggle'):
        return '勾着' if value else '没勾'
    if element.kind == 'dropdown':
        return _plain(element.widget.itemText(int(value))) if 0 <= int(value) < element.widget.count() else str(value)
    return f'「{str(value)[:TEXT_LIMIT]}」' if element.kind == 'text' else str(value)


def _wanted(element: Element, raw):
    from .bunny_tools import ToolError
    widget, kind = element.widget, element.kind
    text = _plain(raw)
    if kind in ('checkbox', 'radio', 'toggle'):
        if text.casefold() in ('true', '1', 'on', '勾', '勾上', '开', '打开', 'yes', '是'):
            return True
        if text.casefold() in ('false', '0', 'off', '不勾', '取消', '关', '关掉', 'no', '否'):
            return False
        raise ToolError('勾选要给 true 或 false')
    if kind == 'dropdown':
        options = [_plain(widget.itemText(i)) for i in range(widget.count())]
        if text in options:
            return options.index(text)
        partial = [index for index, option in enumerate(options) if text and text in option]
        if len(partial) == 1:
            return partial[0]
        raise ToolError(f'「{element.label}」没有「{text}」这一项；选项：' + ' / '.join(options[:12]))
    if kind in ('number', 'slider'):
        try:
            number = float(text)
        except ValueError:
            raise ToolError(f'「{element.label}」要给数字') from None
        number = int(round(number)) if kind == 'slider' or not hasattr(widget, 'decimals') else number
        if not widget.minimum() <= number <= widget.maximum():
            raise ToolError(f'「{element.label}」只能在 {widget.minimum()}–{widget.maximum()} 之间')
        return number
    if _secret(widget, element.label):
        raise ToolError('密码、Key 这类输入框兔白不碰，请小兔纸自己填')
    if widget.isReadOnly():
        raise ToolError(f'「{element.label}」是只读的')
    return str(raw if raw is not None else '')


def _set(window, args):
    from .bunny_tools import ToolError, UndoRecord
    element = _resolve(window, args, SET_KINDS)
    if not element.enabled:
        raise ToolError(f'「{element.label}」现在是灰的，改不了')
    if 'value' not in args:
        raise ToolError('要给 value（要改成什么）')
    wanted = _wanted(element, args.get('value'))
    before = _current(element)
    if before == wanted:
        return f'「{element.label}」本来就是 {_shown(element, before)}，没动'
    previous_radio = None
    if element.kind == 'radio' and wanted:
        from PySide6.QtWidgets import QRadioButton
        group = element.widget.group()
        radios = group.buttons() if group is not None else element.widget.parentWidget().findChildren(QRadioButton)
        previous_radio = next((weakref.ref(w) for w in radios if w.isChecked()), None)
    _reveal(element.widget)
    _apply(element, wanted)
    after = _current(element)
    if after != wanted:
        raise ToolError(f'「{element.label}」没改成（软件没接受 {_shown(element, wanted)}），现在是 {_shown(element, after)}')
    ref = weakref.ref(element.widget)

    def restore() -> str:
        widget = ref()
        if widget is None:
            return f'「{element.label}」已经不在了，没法改回去'
        try:
            if _current(Element(widget, element.kind, element.label)) != after:
                return f'「{element.label}」之后又被改过，兔白不敢乱撤'
            old_radio = previous_radio() if previous_radio else None
            if old_radio is not None:
                old_radio.setChecked(True)
            else:
                _apply(Element(widget, element.kind, element.label), before)
        except RuntimeError:
            return f'「{element.label}」已经不在了，没法改回去'
        return ''
    return (f'「{element.label}」从 {_shown(element, before)} 改成了 {_shown(element, after)}（可以撤销）',
            UndoRecord('call', restore, 0))


def _set_variant(tool, window, args):
    try:
        element = _resolve(window, args, SET_KINDS)
    except Exception:  # noqa: BLE001
        return tool
    words = _words(element)
    if not element.enabled:
        return tool
    if DANGER.search(words):
        return dataclasses.replace(tool, persistent=True, edit=True)
    if HARMLESS_INPUT.search(words):
        return dataclasses.replace(tool, edit=False)
    return tool


# ------------------------------------------------------------------ registered commands
PAID_COMMANDS = frozenset({'translate_selected', 'merge_translate', 'reasr_current', 'reasr_review'})
ASK_COMMANDS = frozenset({'delete', 'home.start_run', 'paste_link', 'adopt_suggestion', 'review_adopt_1', 'review_adopt_2',
                          'review_adopt_3', 'review_adopt_4'})
MODAL_COMMANDS = frozenset({'open_project', 'import_media', 'find', 'find_replace', 'export_subtitles', 'export_video',
                            'save_current_frame', 'speaker_manager', 'home.choose_media', 'app.open_settings',
                            'track_gain', 'performance_panel', 'home.search', 'proofread.find', 'proofread.replace'})
LOOK_CATEGORIES = frozenset({'播放', '时间轴', '窗口'})
LOOK_COMMANDS = frozenset({'previous_cue', 'next_cue', 'review_previous', 'review_next', 'review_next_w', 'review_next_a',
                           'review_previous_s', 'review_previous_d', 'toggle_review', 'exit_review', 'skip_review',
                           'review_play_context', 'go_to_in', 'go_to_out', 'select_all', 'home.open_studio',
                           'app.zoom_in', 'app.zoom_in_alt', 'app.zoom_out', 'app.zoom_reset', 'copy_style'})
SKIP_COMMANDS = frozenset({'redo_alt', 'app.zoom_in_alt', 'review_next_w', 'review_next_a', 'review_previous_s',
                           'review_previous_d', 'proofread.redo_alt'})


def _command_owner(window, action):
    """(callable, where it runs) for a registered command, or (None, why not)."""
    from .bunny_chat import current_page
    from .bunny_tools import _built
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is not None and QApplication.activeModalWidget() is not None:
        return None, '请先处理当前对话框，再运行命令；可以用 ui_snapshot 查看对话框'
    if action.scope.startswith('studio'):
        page = _built(window, 'studio')
        if page is None or current_page(window) != '字幕工作台':
            return None, '这个命令在字幕工作台里用，先 open_page 打开 studio'
        if getattr(page, 'project', None) is None and action.category not in ('文件', '窗口'):
            return None, '字幕工作台还没有打开工程'
        if action.scope == 'studio.review' and not getattr(page, '_review_mode', False):
            return None, '这是审核模式里的命令，先 run_command toggle_review 进入审核模式'
        callback = getattr(page, '_command_callbacks', {}).get(action.id)
        return (callback, page) if callable(callback) else (None, '工作台现在没有接这个命令')
    if action.scope == 'home' and current_page(window) != '首页':
        return None, '这是首页的命令，先 open_page 回首页'
    # Home, global and proofread commands are bound as QShortcut (or a button's shortcut): fire the
    # one whose key is this command's current key, exactly as pressing it would.
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QAbstractButton
    from ..studio.shortcut_registry import current_values
    sequence = current_values().get(action.id, '') or action.default
    if not sequence:
        return None, f'「{action.label}」现在没有绑定按键，兔白接不到它'
    wanted = QKeySequence(sequence)
    for top in _tops(window):
        for shortcut in top.findChildren(QShortcut):
            if shortcut.isEnabled() and shortcut.key().matches(wanted) == QKeySequence.SequenceMatch.ExactMatch:
                return shortcut.activated.emit, window
        for button in top.findChildren(QAbstractButton):
            if (button.isVisible() and button.isEnabled() and not button.shortcut().isEmpty()
                    and button.shortcut().matches(wanted) == QKeySequence.SequenceMatch.ExactMatch):
                return button.click, window
    return None, f'「{action.label}」在{action.scope}里，现在这个页面接不到它'


def _action(args):
    from ..studio.shortcut_registry import BY_ID, current_values, normalize
    from .bunny_tools import ToolError
    pressed = _plain(args.get('key'))
    if pressed and not _plain(args.get('id')):
        # 2026-11-17 eval: she knew 「Ctrl+=」 from the manual but not the command id, and only told the user to press it
        try:
            wanted = normalize(pressed)
        except Exception:  # noqa: BLE001
            wanted = pressed
        values = current_values()
        hits = [BY_ID[name] for name, value in values.items() if value and name in BY_ID and normalize(value) == wanted
                and name not in SKIP_COMMANDS]
        if not hits:
            raise ToolError(f'没有命令绑在「{pressed}」上（按键可能被改过），用 list_commands 查')
        return hits[0]
    key = _plain(args.get('id'))
    action = BY_ID.get(key)
    if action is None:
        found = [item for item in BY_ID.values() if key and key in item.label]
        if len(found) == 1:
            return found[0]
        raise ToolError(f'没有「{key}」这个命令，用 list_commands 看命令编号')
    return action


def _run_command(window, args):
    from PySide6.QtCore import QTimer
    from .bunny_tools import ToolError, UndoRecord
    action = _action(args)
    callback, owner = _command_owner(window, action)
    if callback is None:
        raise ToolError(owner)
    if action.id in MODAL_COMMANDS or not action.scope.startswith('studio'):
        QTimer.singleShot(0, callback)
        if action.id in MODAL_COMMANDS:
            return f'「{action.label}」打开了（马上出现；里面的按钮可以接着用 ui_snapshot / ui_press 操作）'
        return f'做了「{action.label}」（马上生效；要确认就再 ui_snapshot 看）'
    stack = getattr(owner, 'undo_stack', None)
    before = stack.index() if stack is not None else None
    result = callback()
    if result is False:
        raise ToolError(f'「{action.label}」现在用不了（没有选中字幕、播放头下面没有字幕，或者不在对的模式）')
    if stack is not None and stack.index() > before:
        steps = stack.index() - before
        record = UndoRecord('stack', stack, stack.index(), steps,
                            tuple(stack.command(i) for i in range(before, stack.index())))
        return f'做了「{action.label}」（{steps} 步，可以撤销）', record
    return f'做了「{action.label}」'


def _command_variant(tool, _window, args):
    try:
        action = _action(args)
    except Exception:  # noqa: BLE001
        return tool
    if action.id in PAID_COMMANDS:
        return dataclasses.replace(tool, paid=True)
    if action.id in ASK_COMMANDS:
        return dataclasses.replace(tool, persistent=True, edit=True)
    if action.id in MODAL_COMMANDS or action.id in LOOK_COMMANDS or action.category in LOOK_CATEGORIES:
        return tool
    return dataclasses.replace(tool, edit=True)


def _list_commands(_window, args) -> str:
    from ..studio.shortcut_registry import ACTIONS, SCOPE_LABELS, current_values
    want = _plain(args.get('text'))
    keys = current_values()
    rows, group = [], None
    for action in ACTIONS:
        if action.id in SKIP_COMMANDS or action.scope == 'studio.editor':
            continue
        if want and want not in action.label and want not in action.id and want != action.category:
            continue
        heading = f'{SCOPE_LABELS.get(action.scope, action.scope)} · {action.category}'
        if heading != group:
            group = heading
            rows.append(f'【{heading}】')
        mark = '【花 Key】' if action.id in PAID_COMMANDS else '【要确认】' if action.id in ASK_COMMANDS else ''
        key = keys.get(action.id) or ''
        rows.append(f'{action.id}：{action.label}{mark}' + (f'（{key}）' if key else ''))
    if not rows:
        from .bunny_tools import ToolError
        raise ToolError(f'没有含「{want}」的命令')
    return '能用 run_command 跑的命令（id：做什么）：\n' + '\n'.join(rows)


def tools():
    from .bunny_tools import Tool
    return (
        Tool('ui_snapshot', '{"text": "", "window": ""}',
             '看屏幕上所有能操作的控件（按钮、勾选、下拉、数字、滑杆、文字框、页签），每个有编号 e1、e2…、现在的值、灰不灰；'
             'text 只看含这些字的，window 只看某个窗口。要操作没有专用工具的东西时先用它', _ui_snapshot),
        Tool('ui_press', '{"ref": "e12"}', '按一个按钮、勾选或切到一个页签：ref 填快照编号，或 text 填按钮上的字。'
             '下一刻生效，按完再 ui_snapshot 确认；删除、开始识别/导出这类会等小兔纸按「帮我做」', _press, acts=True,
             variant=_press_variant),
        Tool('ui_set', '{"ref": "e5", "value": "黄色"}', '改一个控件的值：勾选填 true/false，下拉填选项文字，数字框/滑杆填数字，'
             '文字框填文字（密码和 Key 不碰）；回报改前改后，可以撤销', _set, edit=True, acts=True, variant=_set_variant),
        Tool('run_command', '{"id": "split"}', '跑一个软件登录过的命令（工作台剪辑、时间轴、审核、文件、窗口，首页和全局的），'
             '和按快捷键一样：id 用 list_commands 查，或者直接填 key（说明书里的按键，例如 {"key": "Ctrl+="} 放大界面）；'
             '编辑类可以撤销。小兔纸说“帮我…”而说明书里有按键能做到时，就用它直接做，不要只告诉他按哪个键',
             _run_command, acts=True, variant=_command_variant),
        Tool('list_commands', '{"text": ""}', '列出 run_command 能跑的命令编号（text 可以只看含这些字的或某一类，例如「审核」）',
             _list_commands),
    )


__all__ = ['DANGER', 'elements', 'tools']
