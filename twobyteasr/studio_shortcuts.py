"""Shortcut command metadata shared by Studio UI surfaces.

Also hosts the native media-key filter and the shortcut settings
dialog (moved out of studio_ui)."""

from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QAbstractNativeEventFilter, QKeyCombination, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QKeySequenceEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .design.presentation import button_role

from .i18n import bind_text

from .i18n import tr
from .i18n_widgets import bind_item


STUDIO_COMMANDS = {
    "play_pause": ("播放 / 暂停", "Space"),
    "track_gain": ("轨道音量（分贝）", "G"),
    "selection_tool": ("选择工具", "V"),
    "razor_tool": ("剃刀工具（按住拖动选切分点）", "C"),
    "split_at_playhead": ("在播放头分割所有未锁视频轨", "Ctrl+K"),
    "merge_tool": ("合并工具（点选字幕后拖动方向合并）", "B"),
    "merge_previous": ("波纹向前合并（与上一条合并）", "Shift+Q"),
    "merge_next": ("波纹向后合并（与下一条合并）", "Shift+W"),
    "trim_start": ("字幕起点至播放头 / 视频向前波纹剪除", "Q"),
    "trim_end": ("字幕终点至播放头 / 视频向后波纹剪除", "W"),
    "delete": ("删除当前字幕", "Delete"),
    "undo": ("撤销", "Ctrl+Z"),
    "redo": ("重做", "Ctrl+Y"),
    "redo_alt": ("重做（备用）", "Ctrl+Shift+Z"),
    "save": ("保存工程", "Ctrl+S"),
    "frame_left": ("上一帧", "Left"),
    "frame_right": ("下一帧", "Right"),
    "previous_cue": ("上一条字幕", "Up"),
    "next_cue": ("下一条字幕", "Down"),
    "reverse": ("反向播放", "J"),
    "pause": ("暂停", "K"),
    "forward": ("正向播放", "L"),
    "toggle_snap": ("切换时间轴吸附", "S"),
    "split": ("拆分当前字幕", "Ctrl+Shift+S"),
    "merge": ("与下一条合并", "Ctrl+Shift+M"),
    "confirm_review": ("确认当前审核", "Enter"),
    "confirm_next_review": ("确认并播放下一条审核", "Ctrl+Enter"),
    "toggle_review": ("进入 / 退出审核模式", "R"),
    "reasr_review": ("重新识别当前审核", "Shift+R"),
    "edit_review": ("手动编辑当前审核", "E"),
    "skip_review": ("跳过当前审核", "Ctrl+Down"),
    "exit_review": ("退出优先审核", "Esc"),
    "add_subtitle": ("添加字幕", "T"),
    "find_replace": ("批量替换字幕文字", "Ctrl+H"),
    "mark_in": ("设置入点", "I"),
    "mark_out": ("设置出点", "O"),
    "save_current_frame": ("保存当前帧", "Ctrl+Alt+F"),
    "add_marker": ("添加时间轴标记", "Shift+M"),
    "add_io_candidate": ("将 I/O 加入剪辑候选", "Shift+I"),
}


def studio_default_shortcuts() -> dict[str, str]:
    """Resolve standard edits with Qt's platform bindings after app startup.

    PortableText stays the settings format; on macOS Qt displays Command
    natively. Custom Q/W/E and clip commands retain their product semantics.
    """
    import sys
    defaults = {key: value[1] for key, value in STUDIO_COMMANDS.items()}
    if sys.platform != 'darwin':
        return defaults
    for command, standard in (('save', QKeySequence.Save), ('undo', QKeySequence.Undo),
                              ('redo', QKeySequence.Redo), ('find_replace', QKeySequence.Replace)):
        bindings = QKeySequence.keyBindings(standard)
        if bindings:
            defaults[command] = bindings[0].toString(QKeySequence.PortableText)
        elif command == 'find_replace':
            # Cocoa has no Qt Replace StandardKey binding. Command-H hides
            # the application; retain a distinct Option-Command-F fallback.
            defaults[command] = 'Ctrl+Alt+F'
    # A second native Redo binding can be absent or equal the first. Keep the
    # alternate empty in that case instead of creating a default conflict.
    redo = QKeySequence.keyBindings(QKeySequence.Redo)
    if redo:
        alternatives = [key.toString(QKeySequence.PortableText) for key in redo[1:]
                        if key.toString(QKeySequence.PortableText) != defaults['redo']]
        defaults['redo_alt'] = alternatives[0] if alternatives else ''
    return defaults


# studio_theme re-exports the command metadata. Define it before importing
# themed dialog primitives so this module is also safe to import directly.


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
        virtual_key = int(msg.wParam)
        if 0x41 <= virtual_key <= 0x5A:
            key = Qt.Key(virtual_key)
        else:
            key = self._SPECIAL_KEYS.get(virtual_key)
        if key is None:
            return False, 0
        modifiers = Qt.KeyboardModifier.NoModifier
        if user32.GetKeyState(0x11) & 0x8000:
            modifiers |= Qt.KeyboardModifier.ControlModifier
        if user32.GetKeyState(0x10) & 0x8000:
            modifiers |= Qt.KeyboardModifier.ShiftModifier
        sequence = QKeySequence(QKeyCombination(modifiers, key)).toString(
            QKeySequence.SequenceFormat.PortableText
        )
        return page._dispatch_shortcut_sequence(sequence), 0


class ShortcutSettingsPanel(QWidget):
    accepted = Signal()
    rejected = Signal()

    def __init__(self, shortcuts: dict[str, str], parent=None):
        from .studio_theme import apply_secondary_surface_theme
        super().__init__(parent)
        bind_text(self, 'Studio 快捷键', property='windowTitle')
        apply_secondary_surface_theme(self)
        # 2026-09-02：表格样式跟随主题 token（此前硬编码浅色，深色主题下刺眼）。
        from .ui_theme import theme_definition
        from .theme_manager import theme_key

        theme = theme_definition(theme_key())
        self.setObjectName("shortcutSettings")
        self._editors: dict[str, QKeySequenceEdit] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        title = QLabel("快捷键设置")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        note = QLabel("点击当前快捷键后按键修改；保存后生效。")
        note.setWordWrap(True)
        outer.addWidget(note)
        layout = outer
        search = QLineEdit()
        bind_text(search, '搜索命令', property='placeholderText')
        layout.addWidget(search)
        self.table = QTableWidget(len(STUDIO_COMMANDS), 2)
        self.table.setHorizontalHeaderLabels(["命令", "当前快捷键"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        # 2026-09-03 修复：此行原写在 self.table 创建之前，AttributeError 使
        # 快捷键设置窗口一打开即崩溃（用户实测"点开不了"）。
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        defaults = studio_default_shortcuts()
        for row, (command_id, (label, _default)) in enumerate(STUDIO_COMMANDS.items()):
            item = bind_item(QTableWidgetItem(), label)
            item.setData(Qt.ItemDataRole.UserRole, command_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            editor = QKeySequenceEdit(QKeySequence(shortcuts.get(command_id, defaults[command_id])))
            editor.keySequenceChanged.connect(self._validate_conflicts)
            self.table.setCellWidget(row, 1, editor)
            self._editors[command_id] = editor
        layout.addWidget(self.table, 1)
        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("studioSaveState")
        layout.addWidget(self.conflict_label)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        reset = QPushButton("恢复默认")
        from .studio_widgets import _icon
        reset.setIcon(_icon("fa5s.undo-alt"))
        self.reset_button = reset
        reset.clicked.connect(self._restore_defaults)
        actions.addWidget(reset)
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
        search.textChanged.connect(self._filter)
        self._validate_conflicts()

    def _filter(self, query: str) -> None:
        query = query.strip().casefold()
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row, query not in self.table.item(row, 0).text().casefold())

    def _restore_defaults(self) -> None:
        for command_id, default in studio_default_shortcuts().items():
            self._editors[command_id].setKeySequence(QKeySequence(default))

    def _validate_conflicts(self) -> None:
        owners: dict[str, list[str]] = {}
        for command_id, editor in self._editors.items():
            value = editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            if value:
                owners.setdefault(value.casefold(), []).append(command_id)
        conflicts = [key for key, commands in owners.items() if len(commands) > 1]
        (bind_text(self.conflict_label, '快捷键冲突：{value0}', value0='、'.join(conflicts)) if conflicts else bind_text(self.conflict_label, '未发现快捷键冲突'))
        self._save_button.setEnabled(not conflicts)

    def values(self) -> dict[str, str]:
        return {
            command_id: editor.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            for command_id, editor in self._editors.items()
        }


# Import compatibility for callers that only inspect/edit this widget. Studio
# always embeds the QWidget and never creates a modal/native shortcut window.
ShortcutSettingsDialog = ShortcutSettingsPanel
