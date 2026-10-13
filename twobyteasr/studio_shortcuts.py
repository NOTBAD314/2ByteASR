"""Shortcut command metadata shared by Studio UI surfaces.

Also hosts the native media-key filter and the shortcut settings
panel (moved out of studio_ui). 2026-10-13: every binding comes from
``shortcut_registry`` (one definition for menus, tooltips, settings and
dispatch); the panel searches, records single key combinations, unbinds,
restores one or all defaults, imports/exports, and checks conflicts per scope.
"""

from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QAbstractNativeEventFilter, QKeyCombination, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import shortcut_registry as registry
from .design.presentation import button_role
from .i18n import bind_text, tr
from .i18n_widgets import bind_item

STUDIO_SCOPES = ('studio', 'studio.review')

# id -> (label, default): historic shape kept for callers and tests.
STUDIO_COMMANDS = {
    action.id: (action.label, action.default)
    for action in registry.ACTIONS if action.scope in STUDIO_SCOPES
}


def studio_default_shortcuts() -> dict[str, str]:
    """Platform defaults of the Studio commands (PortableText; Ctrl = Command on macOS)."""
    import sys
    values = registry.platform_defaults(sys.platform)
    return {key: values[key] for key in STUDIO_COMMANDS}


class _WindowsMessage(ctypes.Structure):
    # ctypes caches POINTER types globally. Defining MSG per native message
    # leaked a new structure/pointer pair even for paints, timers and mouse
    # movement; all those messages share this fixed Win32 ABI instead.
    _fields_ = [
        ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint), ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


_WindowsMessagePointer = ctypes.POINTER(_WindowsMessage)


class _StudioNativeKeyFilter(QAbstractNativeEventFilter):
    """Bridge Win32 key messages that never become Qt events on the mpv surface."""

    _SPECIAL_KEYS = {
        0x20: Qt.Key.Key_Space,
        0x25: Qt.Key.Key_Left,
        0x26: Qt.Key.Key_Up,
        0x27: Qt.Key.Key_Right,
        0x28: Qt.Key.Key_Down,
        0x2E: Qt.Key.Key_Delete,
        0x1B: Qt.Key.Key_Escape,
        0x0D: Qt.Key.Key_Return,
        0x21: Qt.Key.Key_PageUp,
        0x22: Qt.Key.Key_PageDown,
        0x23: Qt.Key.Key_End,
        0x24: Qt.Key.Key_Home,
        0x2D: Qt.Key.Key_Insert,
        0xBB: Qt.Key.Key_Equal,
        0xBD: Qt.Key.Key_Minus,
    }

    def __init__(self, page):
        super().__init__()
        self.page = page

    def nativeEventFilter(self, event_type, message):
        if os.name != "nt" or event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0

        try:
            msg = ctypes.cast(int(message), _WindowsMessagePointer).contents
        except (TypeError, ValueError):
            return False, 0
        if msg.message not in (0x0100, 0x0104):
            return False, 0
        if msg.lParam & (1 << 30):
            return False, 0
        page = self.page
        # An open canvas editor owns all keyboard/IME input even during the
        # native-child focus transition where QApplication.focusWidget() is
        # temporarily None.
        if not page.isVisible() or getattr(page, "_canvas_editor", None) is not None or page._editing_has_focus():
            return False, 0
        root_hwnd = int(page.window().winId())
        message_hwnd = int(msg.hwnd or 0)
        user32 = ctypes.windll.user32
        if message_hwnd != root_hwnd and not user32.IsChild(root_hwnd, message_hwnd):
            return False, 0
        # A modal card/overlay inside the main window owns its keys (e.g. Delete
        # in the style preset manager must not delete the subtitle underneath).
        owner = getattr(page, "_native_keys_blocked", None)
        if callable(owner) and owner():
            return False, 0
        # Windows-key combinations belong to the system.
        if user32.GetKeyState(0x5B) & 0x8000 or user32.GetKeyState(0x5C) & 0x8000:
            return False, 0
        virtual_key = int(msg.wParam)
        if 0x41 <= virtual_key <= 0x5A or 0x30 <= virtual_key <= 0x39:
            key = Qt.Key(virtual_key)
        elif 0x70 <= virtual_key <= 0x7B:
            key = Qt.Key(int(Qt.Key.Key_F1) + virtual_key - 0x70)
        else:
            key = self._SPECIAL_KEYS.get(virtual_key)
        if key is None:
            return False, 0
        modifiers = Qt.KeyboardModifier.NoModifier
        if user32.GetKeyState(0x11) & 0x8000:
            modifiers |= Qt.KeyboardModifier.ControlModifier
        if user32.GetKeyState(0x10) & 0x8000:
            modifiers |= Qt.KeyboardModifier.ShiftModifier
        # Alt counts: Alt+Q is not Q, and AltGr (Ctrl+Alt) is not Ctrl.
        if user32.GetKeyState(0x12) & 0x8000:
            modifiers |= Qt.KeyboardModifier.AltModifier
        sequence = QKeySequence(QKeyCombination(modifiers, key)).toString(
            QKeySequence.SequenceFormat.PortableText
        )
        return page._dispatch_shortcut_sequence(sequence), 0


class ShortcutSettingsPanel(QWidget):
    """All customizable shortcuts, grouped by where they apply.

    ``scopes`` limits the rows (the Studio drawer shows Studio and review keys;
    the application settings page shows every scope). ``values()`` returns the
    edited bindings for the shown rows; the caller saves them.
    """
    accepted = Signal()
    rejected = Signal()

    COLUMNS = ('功能', '适用范围', '快捷键', '')

    def __init__(self, shortcuts: dict[str, str], parent=None, *, scopes=STUDIO_SCOPES, embedded=False):
        from .studio_theme import apply_secondary_surface_theme
        super().__init__(parent)
        bind_text(self, '快捷键', property='windowTitle')
        if not embedded:
            apply_secondary_surface_theme(self)
        self.setObjectName("shortcutSettings")
        self._scopes = tuple(scopes)
        self._actions = [action for action in registry.ACTIONS if action.scope in self._scopes]
        self._defaults = registry.platform_defaults()
        merged = registry.load_values(None)[0]
        merged.update({key: registry.normalize(value) for key, value in (shortcuts or {}).items()})
        self._editors: dict[str, QKeySequenceEdit] = {}
        self._rows: dict[str, int] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        title = QLabel("快捷键设置")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        note = QLabel(tr('点击快捷键格后直接按下新组合（只认一个组合）；点“解除”清空，点“默认”恢复这一项。'
                         '保存后立即生效，重启和更新后保留。输入文字时，单字母与空格快捷键不会触发。'))
        note.setWordWrap(True)
        outer.addWidget(note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName('shortcutSearch')
        bind_text(self.search, '搜索功能名称、按键或分类（例如：剃刀、Ctrl+S、审核）', property='placeholderText')
        filters.addWidget(self.search, 1)
        self.scope_filter = QComboBox()
        self.scope_filter.addItem(tr('全部范围'), '')
        for scope in self._scopes:
            self.scope_filter.addItem(tr(registry.SCOPE_LABELS[scope]), scope)
        self.scope_filter.setVisible(len(self._scopes) > 1)
        filters.addWidget(self.scope_filter)
        outer.addLayout(filters)
        self.table = QTableWidget(len(self._actions), len(self.COLUMNS))
        self.table.setObjectName('shortcutTable')
        self.table.setHorizontalHeaderLabels([tr(text) for text in self.COLUMNS])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        # 2026-09-03 修复：此行原写在 self.table 创建之前，AttributeError 使
        # 快捷键设置窗口一打开即崩溃（用户实测"点开不了"）。
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        ordered = sorted(self._actions, key=lambda a: (registry.CATEGORY_ORDER.index(a.category)
                                                       if a.category in registry.CATEGORY_ORDER else 99))
        self._actions = ordered
        for row, action in enumerate(ordered):
            item = bind_item(QTableWidgetItem(), action.label)
            item.setData(Qt.ItemDataRole.UserRole, action.id)
            item.setToolTip(tr(action.category) + (' · ' + tr(action.note) if action.note else ''))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            scope_item = QTableWidgetItem(tr(registry.SCOPE_LABELS[action.scope]))
            scope_item.setFlags(scope_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, scope_item)
            editor = QKeySequenceEdit(QKeySequence(merged.get(action.id, self._defaults.get(action.id, ''))))
            editor.setObjectName('shortcutEditor_' + action.id)
            if hasattr(editor, 'setMaximumSequenceLength'):
                editor.setMaximumSequenceLength(1)  # chords are never dispatched
            if hasattr(editor, 'setClearButtonEnabled'):
                editor.setClearButtonEnabled(True)
            editor.keySequenceChanged.connect(lambda _seq, action_id=action.id: self._edited(action_id))
            self.table.setCellWidget(row, 2, editor)
            self.table.setCellWidget(row, 3, self._row_actions(action.id))
            self._editors[action.id] = editor
            self._rows[action.id] = row
        outer.addWidget(self.table, 1)
        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("studioSaveState")
        self.conflict_label.setWordWrap(True)
        outer.addWidget(self.conflict_label)
        self.resolve_button = QPushButton(tr('解除冲突：保留刚改的，清空另一项'))
        self.resolve_button.setObjectName('shortcutResolve')
        self.resolve_button.clicked.connect(self._resolve_conflicts)
        self.resolve_button.hide()
        outer.addWidget(self.resolve_button)
        fixed = QLabel(tr('不能自订的鼠标与编辑框操作：') + '；'.join(
            f'{tr(key)}：{tr(text)}' for key, text in registry.FIXED_GESTURES))
        fixed.setObjectName('muted')
        fixed.setWordWrap(True)
        outer.addWidget(fixed)
        actions = QHBoxLayout()
        outer.addLayout(actions)
        from .studio_widgets import _icon
        reset = QPushButton(tr("全部恢复默认"))
        reset.setIcon(_icon("fa5s.undo-alt"))
        self.reset_button = reset
        reset.clicked.connect(self._restore_defaults)
        actions.addWidget(reset)
        export = QPushButton(tr('导出…'))
        export.setObjectName('shortcutExport')
        export.clicked.connect(self._export)
        actions.addWidget(export)
        import_button = QPushButton(tr('导入…'))
        import_button.setObjectName('shortcutImport')
        import_button.clicked.connect(self._import)
        actions.addWidget(import_button)
        actions.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        bind_text(buttons.button(QDialogButtonBox.StandardButton.Save), '保存')
        bind_text(buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
        buttons.accepted.connect(self.accepted)
        buttons.rejected.connect(self.rejected)
        actions.addWidget(buttons)
        self._save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self._save_button.setIcon(_icon("fa5s.save"))
        self.cancel_button.setIcon(_icon("fa5s.times"))
        button_role(self._save_button, "primary")
        self._last_edited = ''
        self.search.textChanged.connect(lambda _text: self._filter())
        self.scope_filter.currentIndexChanged.connect(lambda _index: self._filter())
        self._validate_conflicts()

    def _row_actions(self, action_id: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        reset = QToolButton()
        reset.setObjectName('shortcutReset_' + action_id)
        reset.setText(tr('默认'))
        reset.setToolTip(tr('恢复这一项的默认快捷键：{key}', key=registry.display(self._defaults.get(action_id, ''))
                            or tr('未绑定')))
        reset.clicked.connect(lambda _=False: self._editors[action_id].setKeySequence(
            QKeySequence(self._defaults.get(action_id, ''))))
        clear = QToolButton()
        clear.setObjectName('shortcutClear_' + action_id)
        clear.setText(tr('解除'))
        clear.setToolTip(tr('不为这一项设置快捷键'))
        clear.clicked.connect(lambda _=False: self._editors[action_id].clear())
        row.addWidget(reset)
        row.addWidget(clear)
        return box

    def _filter(self) -> None:
        query = self.search.text().strip().casefold()
        scope = self.scope_filter.currentData() or ''
        by_id = registry.BY_ID
        for action_id, row in self._rows.items():
            action = by_id[action_id]
            key = self._value(action_id)
            haystack = ' '.join((str(tr(action.label)), action.label, str(tr(action.category)), action.category,
                                 key, registry.display(key))).casefold()
            hidden = bool(query and query not in haystack) or bool(scope and action.scope != scope)
            self.table.setRowHidden(row, hidden)

    def _value(self, action_id: str) -> str:
        editor = self._editors[action_id]
        return registry.normalize(editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def _edited(self, action_id: str) -> None:
        value = self._value(action_id)
        reason = registry.reserved_reason(value) if value else ''
        if reason:
            editor = self._editors[action_id]
            editor.blockSignals(True)
            editor.clear()
            editor.blockSignals(False)
            bind_text(self.conflict_label, '{key}：{reason}', key=registry.display(value), reason=tr(reason))
            return
        self._last_edited = action_id
        self._validate_conflicts()

    def _restore_defaults(self) -> None:
        for command_id, editor in self._editors.items():
            editor.setKeySequence(QKeySequence(self._defaults.get(command_id, '')))

    def _current_conflicts(self):
        return registry.conflicts(self.values())

    def _validate_conflicts(self) -> None:
        found = self._current_conflicts()
        blocking = [item for item in found if item.blocking]
        notes = [item for item in found if not item.blocking]
        lines = []
        if blocking:
            lines.append(tr('快捷键冲突，需要先处理：') + '；'.join(item.describe() for item in blocking))
        if notes and not blocking:
            lines.append(tr('未发现快捷键冲突') + '（' + '；'.join(item.describe() for item in notes[:3]) + '）')
        if not lines:
            lines.append(tr('未发现快捷键冲突'))
        self.conflict_label.setText('\n'.join(lines))
        self._save_button.setEnabled(not blocking)
        self.resolve_button.setVisible(bool(blocking and self._last_edited))

    def _resolve_conflicts(self) -> None:
        """Keep the key on the row just edited; clear the other row of each clash."""
        keep = self._last_edited
        for item in [c for c in self._current_conflicts() if c.blocking]:
            other = item.second if item.first == keep else item.first if item.second == keep else item.second
            if other in self._editors:
                self._editors[other].clear()
        self._validate_conflicts()

    def values(self) -> dict[str, str]:
        return {command_id: self._value(command_id) for command_id in self._editors}

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr('导出快捷键'), 'shortcuts.2byteasr-keys.json',
                                              tr('快捷键文件 (*.json)'))
        if not path:
            return
        values = registry.load_values(None)[0]
        values.update(self.values())
        try:
            with open(path, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(registry.export_payload(values))
        except OSError as exc:
            bind_text(self.conflict_label, '导出失败：{exc}', exc=exc)
            return
        bind_text(self.conflict_label, '已导出到 {path}', path=path)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr('导入快捷键'), '', tr('快捷键文件 (*.json)'))
        if not path:
            return
        self.import_file(path)

    def import_file(self, path: str) -> bool:
        try:
            with open(path, encoding='utf-8') as stream:
                bindings = registry.import_payload(stream.read())
        except (OSError, ValueError) as exc:
            bind_text(self.conflict_label, '导入失败：{exc}', exc=exc)
            return False
        for action_id, value in bindings.items():
            if action_id in self._editors:
                self._editors[action_id].setKeySequence(QKeySequence(value))
        self._validate_conflicts()
        return True


# Import compatibility for callers that only inspect/edit this widget. Studio
# always embeds the QWidget and never creates a modal/native shortcut window.
ShortcutSettingsDialog = ShortcutSettingsPanel
