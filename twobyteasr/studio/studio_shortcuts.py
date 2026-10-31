"""Shortcut command metadata shared by Studio UI surfaces.

Also hosts the native media-key filter and the shortcut settings
panel (moved out of studio_ui). 2026-10-13: every binding comes from
``shortcut_registry`` (one definition for menus, tooltips, settings and
dispatch); the panel searches, records single key combinations, unbinds,
restores one or all defaults, imports/exports, and checks conflicts per scope.

2026-10-17 redesign (user: "密密麻麻的太嚇人了也沒任何有效信息"): the cramped
table with three buttons per row became one scrolling list grouped by where
the keys apply. Each row is the action's name and its keys drawn as key caps;
click the caps and press the new combination (Esc cancels). Restore-default
shows only on changed rows, clear only under the pointer, and a clash is
named on both rows plus one banner. The mouse gestures that cannot be
changed sit in a section that opens on request.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from collections import deque

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QKeyCombination, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import shortcut_registry as registry
from ..design.presentation import button_role
from ..i18n import bind_text, tr

STUDIO_SCOPES = ('studio', 'studio.review', 'studio.editor')

# id -> (label, default): historic shape kept for callers and tests.
STUDIO_COMMANDS = {
    action.id: (action.label, action.default)
    for action in registry.ACTIONS if action.scope in STUDIO_SCOPES
}


def studio_default_shortcuts() -> dict[str, str]:
    """Platform defaults of the Studio commands (PortableText; Ctrl = Command on macOS)."""
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
        # 2026-10-17: keys people can now bind. Only the punctuation whose
        # virtual key means the same character on every layout.
        0xBC: Qt.Key.Key_Comma,
        0xBE: Qt.Key.Key_Period,
        0x08: Qt.Key.Key_Backspace,
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


# ------------------------------------------------------------ key caps

_MAC_MODIFIERS = {'Ctrl': '⌘', 'Meta': '⌃', 'Alt': '⌥', 'Shift': '⇧'}
_CAP_NAMES = {'Left': '←', 'Right': '→', 'Up': '↑', 'Down': '↓', 'Return': 'Enter', 'PgDown': 'PgDn'}


def _portable_parts(text: str) -> list[str]:
    """``Ctrl+Shift+S`` -> [Ctrl, Shift, S]; the plus key itself survives (``Ctrl++``)."""
    parts, out, index = text.split('+'), [], 0
    while index < len(parts):
        if parts[index] == '' and index + 1 < len(parts) and parts[index + 1] == '':
            out.append('+')
            index += 2
            continue
        if parts[index]:
            out.append(parts[index])
        index += 1
    return out


def key_caps(sequence: str, platform: str | None = None) -> list[str]:
    """The key caps one binding is drawn with (platform modifier names, arrows as glyphs)."""
    platform = platform or sys.platform
    caps = []
    for part in _portable_parts(registry.normalize(sequence)):
        if platform == 'darwin' and part in _MAC_MODIFIERS:
            caps.append(_MAC_MODIFIERS[part])
        elif part == 'Meta':
            caps.append('Win')
        elif part == 'Space':
            caps.append(str(tr('空格')))
        elif part in _CAP_NAMES:
            caps.append(_CAP_NAMES[part])
        else:
            caps.append(part)
    return caps


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _qcolor(value: str):
    from PySide6.QtGui import QColor
    return QColor(value)


class ShortcutKeyField(QKeySequenceEdit):
    """One binding shown as key caps; click it, then press the new combination.

    Qt's editor still records the keys (one combination). Its own line edit is
    hidden. The caps, the "press keys" prompt and 未设置 are small labels
    styled by the panel sheet (the page's own fonts and colours; testable).
    The field paints only its frame: full width while recording, hugging the
    caps under the pointer or when the key clashes. Esc cancels instead of
    being recorded (only 退出优先审核 uses Esc; its default restores it), and
    recording ends by leaving the field, so the next key press does not start
    a second recording.
    """

    focusChanged = Signal(bool)

    def __init__(self, sequence: str = '', parent=None, *, compact: bool = False):
        super().__init__(QKeySequence(sequence), parent)
        if hasattr(self, 'setMaximumSequenceLength'):
            self.setMaximumSequenceLength(1)  # chords are never dispatched
        inner = self.findChild(QLineEdit)
        if inner is not None:
            inner.hide()
        self._compact = compact
        self._conflict = False
        self._recording = False  # set by focus in / out
        self._shown = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.caps = QWidget(self)
        self.caps.setObjectName('shortcutKeyCaps')
        self.caps.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row = QHBoxLayout(self.caps)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(4)
        self.layout().addWidget(self.caps)
        self.editingFinished.connect(self._recorded)
        self.keySequenceChanged.connect(lambda _sequence: self._sync_caps())
        self._sync_caps()

    def sizeHint(self) -> QSize:
        from ..app.ui_zoom import px
        # Styled Ctrl + Shift + S needs ~186 logical px including cap borders
        # and margins. Narrow drawers already stack this fixed-width column.
        return QSize(px(192), px(30))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_conflict(self, conflict: bool) -> None:
        if conflict != self._conflict:
            self._conflict = conflict
            self.update()

    def is_recording(self) -> bool:
        return self._recording

    def cap_texts(self) -> list[str]:
        return [label.text() for label in self.caps.findChildren(QLabel, 'shortcutKeyCap')]

    def event(self, event):
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride) and event.modifiers() in (
                Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
            if event.key() == Qt.Key.Key_Escape:
                event.accept()
                if kind == QEvent.Type.KeyPress:
                    self._leave()
                return True
        if kind == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            # Tab moves on; it is not a shortcut here (the caption editor owns it).
            QWidget.focusNextPrevChild(self, event.key() == Qt.Key.Key_Tab
                                       and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            return True
        return super().event(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._recording = True
        self.focusChanged.emit(True)
        self._sync_caps()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._recording = False
        self.focusChanged.emit(False)
        self._sync_caps()

    def setKeySequence(self, sequence) -> None:
        super().setKeySequence(sequence)
        self._sync_caps()

    def clear(self) -> None:
        super().clear()
        self._sync_caps()

    def _label(self, text, name: str) -> QLabel:
        label = QLabel(str(text), self.caps)
        label.setObjectName(name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.caps.layout().addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        label.show()  # now, not on the layout's queued show (a grab right after would miss it)
        return label

    def _sync_caps(self) -> None:
        sequence = self.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        state = (self._recording, sequence)
        if state == self._shown:
            return
        self._shown = state
        row = self.caps.layout()
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        row.addStretch(1)
        caps = key_caps(sequence)
        if self._recording:
            self._label(tr('按新组合 · Esc 取消'), 'shortcutKeyPrompt')
        elif not caps:
            self._label(tr('未设置'), 'shortcutKeyEmpty')
        else:
            labels = []
            for index, cap in enumerate(caps):
                if index:
                    labels.append(self._label('+', 'shortcutKeyPlus'))
                labels.append(self._label(cap, 'shortcutKeyCap'))
            room = self.sizeHint().width() - 16  # fixed size: the real width once laid out
            for label in labels:
                label.ensurePolished()
            if sum(label.sizeHint().width() for label in labels) + row.spacing() * max(0, len(labels) - 1) > room:
                for label in labels:  # very long combination: one line of text instead of caps
                    row.removeWidget(label)
                    label.setParent(None)
                    label.deleteLater()
                text = self._label('', 'shortcutKeyText')
                text.ensurePolished()
                text.setText(text.fontMetrics().elidedText(' + '.join(caps), Qt.TextElideMode.ElideRight, room))
        self.update()

    def _recorded(self) -> None:
        if self._recording:
            QTimer.singleShot(0, self._leave)

    def _leave(self) -> None:
        host = self.parentWidget()
        while host is not None and not isinstance(host, ShortcutSettingsPanel):
            host = host.parentWidget()
        if host is not None:
            host.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.clearFocus()

    def paintEvent(self, _event) -> None:
        recording, hovered = self._recording, self.underMouse()
        if not (recording or self._conflict or hovered):
            return
        from ..app.ui_zoom import px
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        field = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        box = field
        labels = [child for child in self.caps.findChildren(QLabel) if child.isVisible()]
        if labels and not recording:
            # The hover and clash boxes hug the keys, which sit flush right.
            left = min(label.geometry().left() for label in labels) + self.caps.x() - px(8)
            box = QRectF(max(field.left(), left), field.top(), field.right() - max(field.left(), left), field.height())
        if recording:
            painter.setPen(QPen(_qcolor(t.focus), 1.5))
            painter.setBrush(_qcolor(t.input_surface))
        elif self._conflict:
            painter.setPen(QPen(_qcolor(t.danger), 1.2))
            painter.setBrush(_qcolor(t.danger_soft))
        else:
            painter.setPen(QPen(_qcolor(t.control_border_hover), 1.0))
            painter.setBrush(_qcolor(t.selected))
        painter.drawRoundedRect(box, px(7), px(7))


def _panel_sheet() -> str:
    """The panel's own sheet: inside 应用设置 the dialog's application sheet
    outranks any outer rule (2026-10-14), so colours are set here."""
    from ..design.ui_theme import blend_hex
    t = _theme()
    row_hover = blend_hex(t.surface_elevated, t.text, 0.035)
    cap_fill = blend_hex(t.surface_elevated, t.text, 0.06)
    return (
        f"QScrollArea#shortcutScroll, QWidget#shortcutList {{ background: transparent; border: 0; }}"
        f"QFrame#shortcutGroup {{ background: {t.surface_elevated}; border: 1px solid {t.border};"
        f" border-radius: 10px; }}"
        f"QFrame#shortcutRow {{ background: transparent; border: 0; border-top: 1px solid {t.border};"
        f" border-radius: 0; }}"
        f"QFrame#shortcutRow[firstRow=\"true\"] {{ border-top: 0; }}"
        f"QFrame#shortcutRow:hover {{ background: {row_hover}; }}"
        f"QLabel#shortcutName {{ background: transparent; color: {t.text}; font-size: 14px; }}"
        f"QLabel#shortcutKeyCap {{ background: {cap_fill}; color: {t.text}; border: 1px solid {t.border_strong};"
        f" border-bottom-width: 2px; border-radius: 5px; padding: 0px 7px; font-size: 12px; font-weight: 600;"
        f" min-width: 10px; min-height: 18px; }}"
        f"QLabel#shortcutKeyPlus {{ background: transparent; color: {t.text_muted}; font-size: 12px; }}"
        f"QLabel#shortcutKeyPrompt {{ background: transparent; color: {t.accent_text}; font-size: 13px; }}"
        f"QLabel#shortcutKeyEmpty {{ background: transparent; color: {t.text_muted}; font-size: 13px; }}"
        f"QLabel#shortcutKeyText {{ background: transparent; color: {t.text}; font-size: 13px; }}"
        f"QLabel#shortcutDetail {{ background: transparent; color: {t.text_muted}; font-size: 12px; }}"
        f"QLabel#shortcutDetail[clash=\"true\"] {{ color: {t.danger}; }}"
        f"QLabel#shortcutGroupTitle {{ background: transparent; color: {t.text}; font-size: 15px;"
        f" font-weight: 600; }}"
        f"QLabel#shortcutGroupMeta, QLabel#shortcutEmpty, QLabel#shortcutTypingNote {{ background: transparent;"
        f" color: {t.text_muted}; font-size: 12px; }}"
        f"QToolButton[shortcutRowButton=\"true\"] {{ background: transparent; border: 0; border-radius: 6px;"
        f" padding: 4px; min-width: 20px; min-height: 20px; }}"
        f"QToolButton[shortcutRowButton=\"true\"]:hover {{ background: {t.selected}; }}"
        f"QFrame#shortcutBanner {{ background: {t.surface_elevated}; border: 1px solid {t.border};"
        f" border-radius: 8px; }}"
        f"QFrame#shortcutBanner[kind=\"error\"] {{ background: {t.danger_soft}; border-color: {t.danger}; }}"
        f"QFrame#shortcutBanner QLabel {{ background: transparent; color: {t.text_secondary}; font-size: 13px; }}"
        f"QFrame#shortcutBanner[kind=\"error\"] QLabel {{ color: {t.danger}; }}"
        f"QToolButton#shortcutFixedToggle {{ background: transparent; border: 0; color: {t.text_secondary};"
        f" font-size: 13px; padding: 4px 2px; }}"
        f"QToolButton#shortcutFixedToggle:hover {{ color: {t.text}; }}"
        f"QLabel#shortcutFixedKey {{ background: transparent; color: {t.text}; font-size: 13px;"
        f" font-weight: 600; }}"
        f"QLabel#shortcutFixedText {{ background: transparent; color: {t.text_secondary}; font-size: 13px; }}"
    )


class _ShortcutRow(QFrame):
    """Name (and a short status line) on the left, the key caps on the right."""

    def __init__(self, panel: 'ShortcutSettingsPanel', action, value: str, *, compact: bool, parent=None):
        super().__init__(parent)
        from ..design.themed_icons import install_themed_icon
        self.panel, self.action = panel, action
        self.setObjectName('shortcutRow')
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # a click beside the keys ends recording
        self._hovered = False
        self._clash = ''
        self.name = bind_text(QLabel(), action.label)
        self.name.setObjectName('shortcutName')
        self.name.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setObjectName('shortcutDetail')
        self.detail.setWordWrap(True)
        self.detail.hide()
        self.field = ShortcutKeyField(value, self, compact=compact)
        self.field.setObjectName('shortcutEditor_' + action.id)
        self.field.setAccessibleName(str(tr(action.label)))
        self.reset = QToolButton()
        self.reset.setObjectName('shortcutReset_' + action.id)
        install_themed_icon(self.reset, 'fa5s.undo-alt', 'secondary')
        self.reset.clicked.connect(lambda _=False: self.field.setKeySequence(
            QKeySequence(self.panel._defaults.get(action.id, ''))))
        self.clear = QToolButton()
        self.clear.setObjectName('shortcutClear_' + action.id)
        install_themed_icon(self.clear, 'fa5s.times', 'secondary')
        bind_text(self.clear, '清空这个快捷键', property='toolTip')
        self.clear.clicked.connect(lambda _=False: self.field.clear())
        from ..app.ui_zoom import px
        for button in (self.reset, self.clear):
            button.setProperty('shortcutRowButton', True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(px(13), px(13)))
            policy = button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            button.setSizePolicy(policy)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(2)
        words.addWidget(self.name)
        words.addWidget(self.detail)
        self.keys = QHBoxLayout()
        self.keys.setContentsMargins(0, 0, 0, 0)
        self.keys.setSpacing(2)
        self.keys.addWidget(self.field)
        self.keys.addWidget(self.reset)
        self.keys.addWidget(self.clear)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(14, 5, 6, 5)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(4)
        self.grid.addLayout(words, 0, 0)
        self.grid.addLayout(self.keys, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        self.grid.setColumnStretch(0, 1)
        self._stacked = False
        self.field.focusChanged.connect(lambda _focused: self.sync())

    def set_stacked(self, stacked: bool) -> None:
        """Narrow drawers put the keys under the name instead of beside it."""
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self.grid.removeItem(self.keys)
        if stacked:
            self.grid.addLayout(self.keys, 1, 0, Qt.AlignmentFlag.AlignRight)
        else:
            self.grid.addLayout(self.keys, 0, 1, Qt.AlignmentFlag.AlignVCenter)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.sync()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.sync()
        super().leaveEvent(event)

    def value(self) -> str:
        return registry.normalize(self.field.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def changed(self) -> bool:
        return self.value() != registry.normalize(self.panel._defaults.get(self.action.id, ''))

    def set_clash(self, other_label: str) -> None:
        self._clash = other_label
        self.field.set_conflict(bool(other_label))
        self.sync()

    def sync(self) -> None:
        value = self.value()
        default = self.panel._defaults.get(self.action.id, '')
        changed = value != registry.normalize(default)
        self.reset.setVisible(changed)
        bind_text(self.reset, '恢复默认（{key}）', property='toolTip',
                  key=registry.display(default) or tr('未设置'))
        self.clear.setVisible(bool(value) and (self._hovered or self.field.is_recording() or self.clear.hasFocus()))
        if self._clash:
            bind_text(self.detail, '和「{other}」重复', other=tr(self._clash))
        elif changed:
            bind_text(self.detail, '已改动，默认是 {key}', key=' + '.join(key_caps(default)) or tr('未设置'))
        elif self.action.note:
            bind_text(self.detail, self.action.note)
        else:
            self.detail.setText('')
        self.detail.setProperty('clash', bool(self._clash))
        self.detail.style().unpolish(self.detail)
        self.detail.style().polish(self.detail)
        self.detail.setVisible(bool(self.detail.text()))


class ShortcutSettingsPanel(QWidget):
    """All customizable shortcuts, grouped by where they apply.

    ``scopes`` limits the rows (the Studio drawer shows Studio and review keys;
    the application settings page shows every scope). ``values()`` returns the
    edited bindings for the shown rows; the caller saves them. ``embedded``
    (inside 应用设置) drops the panel's own title and save / cancel buttons:
    the dialog's 保存更改 saves the keys too.
    """
    accepted = Signal()
    rejected = Signal()
    close_requested = Signal()  # × in the drawer panel; unsaved keys are the owner's question

    def __init__(self, shortcuts: dict[str, str], parent=None, *, scopes=STUDIO_SCOPES, embedded=False, incremental=False):
        from ..design.studio_theme import apply_secondary_surface_theme
        from ..design.themed_icons import install_themed_icon
        super().__init__(parent)
        bind_text(self, '快捷键', property='windowTitle')
        if not embedded:
            apply_secondary_surface_theme(self)
        self.setObjectName("shortcutSettings")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # recording ends here
        self._embedded = embedded
        self._scopes = tuple(scopes)
        actions = [action for action in registry.ACTIONS if action.scope in self._scopes]
        order = registry.CATEGORY_ORDER
        self._actions = sorted(actions, key=lambda a: order.index(a.category) if a.category in order else 99)
        self._defaults = registry.platform_defaults()
        merged = registry.load_values(None)[0]
        merged.update({key: registry.normalize(value) for key, value in (shortcuts or {}).items()})
        compact = not embedded
        self._compact = compact
        self._incremental = incremental
        self._bindings = {action.id: merged.get(action.id, self._defaults.get(action.id, '')) for action in self._actions}
        self._pending_rows = deque()
        self._clashes = {}
        self._row_timer = QTimer(self)
        self._row_timer.setSingleShot(True)
        self._row_timer.timeout.connect(self._build_rows)
        outer = QVBoxLayout(self)
        margin = 0 if embedded else 12
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(10)
        title = QLabel(tr("快捷键设置"), self)
        title.setObjectName('sectionTitle')
        # Inside 应用设置 the page already has its heading (2026-10-14).
        title.setVisible(not embedded)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(title, 1)
        # 2026-10-18 (user): closing the drawer panel meant scrolling down to
        # 取消. The × closes it from the top; the owner asks about unsaved keys.
        self.close_button = None
        if not embedded:
            close = button_role(QPushButton('×'), 'ghost')
            close.setObjectName('shortcutPanelClose')
            close.setFixedSize(30, 30)
            close.setStyleSheet('padding: 0; min-width: 0; min-height: 0; font-size: 20px;')
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            bind_text(close, '关闭快捷键设置', property='toolTip')
            close.clicked.connect(self.close_requested)
            title_row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
            self.close_button = close
        outer.addLayout(title_row)

        self.search = QLineEdit()
        self.search.setObjectName('shortcutSearch')
        self.search.setClearButtonEnabled(True)
        bind_text(self.search, '搜索功能或按键，如：剃刀、Ctrl+S', property='placeholderText')
        self.scope_filter = QComboBox(self)
        self.scope_filter.setObjectName('shortcutScopeFilter')
        self.scope_filter.addItem(tr('全部范围'), '')
        for scope in self._scopes:
            self.scope_filter.addItem(tr(registry.SCOPE_LABELS[scope]), scope)
        self.scope_filter.setVisible(len(self._scopes) > 1)
        self.changed_only = QCheckBox()
        self.changed_only.setObjectName('shortcutChangedOnly')
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(10)
        filters.setVerticalSpacing(6)
        if compact:  # the Studio drawer is narrow: search on its own line
            filters.addWidget(self.search, 0, 0, 1, 3)
            filters.addWidget(self.scope_filter, 1, 0)
            filters.addWidget(self.changed_only, 1, 1)
            filters.setColumnStretch(2, 1)
        else:
            filters.addWidget(self.search, 0, 0)
            filters.addWidget(self.scope_filter, 0, 1)
            filters.addWidget(self.changed_only, 0, 2)
            filters.setColumnStretch(0, 1)
        outer.addLayout(filters)
        self.build_status = QLabel(self)
        self.build_status.setObjectName('shortcutBuildStatus')
        self.build_status.setProperty('typography', 'meta')
        outer.addWidget(self.build_status)

        self.banner = QFrame()
        self.banner.setObjectName('shortcutBanner')
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(12, 8, 8, 8)
        banner_row.setSpacing(10)
        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("shortcutStatus")
        self.conflict_label.setWordWrap(True)
        banner_row.addWidget(self.conflict_label, 1)
        self.resolve_button = button_role(QPushButton(tr('保留刚改的，清空另一项')), 'secondary')
        self.resolve_button.setObjectName('shortcutResolve')
        self.resolve_button.clicked.connect(self._resolve_conflicts)
        self.resolve_button.hide()
        banner_row.addWidget(self.resolve_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.banner.hide()
        outer.addWidget(self.banner)

        self.list_view = QScrollArea()
        self.list_view.setObjectName('shortcutScroll')
        self.list_view.setWidgetResizable(True)
        self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('shortcutList')
        content.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # a click beside the keys ends recording
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 6 if embedded else 2, 8)
        column.setSpacing(6)
        self.rows: dict[str, _ShortcutRow] = {}
        self._editors: dict[str, ShortcutKeyField] = {}
        self._groups: list[tuple[QWidget, QWidget, list[_ShortcutRow]]] = []
        for category in dict.fromkeys(action.category for action in self._actions):
            members = [action for action in self._actions if action.category == category]
            header = QWidget(content)
            header_row = QHBoxLayout(header)
            header_row.setContentsMargins(4, 10 if self._groups else 0, 4, 2)
            header_row.setSpacing(8)
            name = bind_text(QLabel(), category)
            name.setObjectName('shortcutGroupTitle')
            header_row.addWidget(name)
            meta = QLabel(self._group_meta(members))
            meta.setObjectName('shortcutGroupMeta')
            header_row.addWidget(meta, 1, Qt.AlignmentFlag.AlignBottom)
            group = QFrame(content)
            group.setObjectName('shortcutGroup')
            group_rows = QVBoxLayout(group)
            group_rows.setContentsMargins(1, 1, 1, 1)
            group_rows.setSpacing(0)
            rows = []
            for index, action in enumerate(members):
                self._pending_rows.append((group, group_rows, rows, index, action))
            column.addWidget(header)
            column.addWidget(group)
            self._groups.append((header, group, rows))
        self.empty_label = QLabel(tr('没有找到匹配的快捷键'))
        self.empty_label.setObjectName('shortcutEmpty')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        column.addWidget(self.empty_label)
        column.addSpacing(6)
        column.addWidget(self._fixed_section())
        column.addStretch(1)
        self.list_view.setWidget(content)
        outer.addWidget(self.list_view, 1)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        outer.addLayout(actions_row)
        # The drawer can be 360 px wide: save / cancel get their own line there.
        buttons_row = QHBoxLayout() if compact else actions_row
        if compact:
            buttons_row.addStretch(1)
            outer.addLayout(buttons_row)
        reset = button_role(QPushButton(tr("全部恢复默认")), 'secondary')
        install_themed_icon(reset, "fa5s.undo-alt", "primary")
        self.reset_button = reset
        reset.clicked.connect(self._restore_defaults)
        actions_row.addWidget(reset)
        export = button_role(QPushButton(tr('导出…')), 'ghost')
        export.setObjectName('shortcutExport')
        export.clicked.connect(self._export)
        actions_row.addWidget(export)
        import_button = button_role(QPushButton(tr('导入…')), 'ghost')
        import_button.setObjectName('shortcutImport')
        import_button.clicked.connect(self._import)
        actions_row.addWidget(import_button)
        actions_row.addStretch(1)
        self._save_button = None
        self.cancel_button = None
        if not embedded:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
            )
            bind_text(buttons.button(QDialogButtonBox.StandardButton.Save), '保存')
            bind_text(buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
            buttons.accepted.connect(self.accepted)
            buttons.rejected.connect(self.rejected)
            buttons_row.addWidget(buttons)
            self._save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
            self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            install_themed_icon(self._save_button, "fa5s.save", "on_accent")
            install_themed_icon(self.cancel_button, "fa5s.times", "primary")
            button_role(self._save_button, "primary")

        self._apply_sheet()
        self._last_edited = ''
        self.search.textChanged.connect(lambda _text: self._filter())
        self.scope_filter.currentIndexChanged.connect(lambda _index: self._filter())
        self.changed_only.toggled.connect(lambda _checked: self._filter())
        self._validate_conflicts()
        self._update_changed_count()
        self._build_rows(complete=not incremental)

    @property
    def construction_complete(self):
        return not self._pending_rows

    def _build_rows(self, *, complete=False):
        started = time.perf_counter()
        added = []
        while self._pending_rows:
            group, layout, rows, index, action = self._pending_rows.popleft()
            row = _ShortcutRow(self, action, self._bindings[action.id], compact=self._compact, parent=group)
            row.setProperty('firstRow', index == 0)
            row.field.keySequenceChanged.connect(lambda _seq, action_id=action.id: self._edited(action_id))
            layout.addWidget(row)
            rows.append(row)
            self.rows[action.id] = row
            self._editors[action.id] = row.field
            row.set_clash(self._clashes.get(action.id, ''))
            added.append(row)
            if not complete and time.perf_counter()-started >= .012:
                break
        if added and self.isVisible():
            # Rows added after the window was shown missed its zoom and
            # language passes (2026-10-25: at 150% they kept 100% margins).
            from ..app.ui_zoom import apply_to
            from ..i18n import apply_ui_language, current_language
            for row in added:
                apply_to(row)
                apply_ui_language(row, current_language())
        if self._pending_rows:
            bind_text(self.build_status, '正在列出快捷键：{done} / {total}；已显示的项目可以先修改。',
                      done=len(self.rows), total=len(self._actions))
            self.build_status.show()
            if self.isVisible():
                self._row_timer.start(0)
        else:
            self.build_status.hide()
        self._filter()

    def hideEvent(self, event):
        self._row_timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------ layout

    def _group_meta(self, members) -> str:
        scopes = list(dict.fromkeys(action.scope for action in members))
        where = ' · '.join(str(tr(registry.SCOPE_LABELS[scope])) for scope in scopes)
        count = str(tr('{count} 项', count=len(members)))
        # The Studio drawer only shows Studio keys; naming the place there is noise.
        return count if not self._embedded else f'{where} · {count}'

    def _fixed_section(self) -> QWidget:
        """The mouse and text-box keys nobody can change, folded until asked for."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.fixed_toggle = QToolButton()
        self.fixed_toggle.setObjectName('shortcutFixedToggle')
        self.fixed_toggle.setCheckable(True)
        self.fixed_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.fixed_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.fixed_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.fixed_toggle, '鼠标操作与输入框里的按键（固定，不能改）')
        lay.addWidget(self.fixed_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.fixed_body = QFrame()
        self.fixed_body.setObjectName('shortcutGroup')
        grid = QGridLayout(self.fixed_body)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for index, (keys, text) in enumerate(registry.FIXED_GESTURES):
            key = bind_text(QLabel(), keys)
            key.setObjectName('shortcutFixedKey')
            key.setWordWrap(True)
            words = bind_text(QLabel(), text)
            words.setObjectName('shortcutFixedText')
            words.setWordWrap(True)
            grid.addWidget(key, index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(words, index, 1, Qt.AlignmentFlag.AlignTop)
        note = bind_text(QLabel(), '在输入框里打字时，单个字母、数字和空格的快捷键不会触发。')
        note.setObjectName('shortcutTypingNote')
        note.setWordWrap(True)
        grid.addWidget(note, len(registry.FIXED_GESTURES), 0, 1, 2)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        self.fixed_body.hide()
        lay.addWidget(self.fixed_body)

        def toggled(opened):
            self.fixed_toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
            self.fixed_body.setVisible(opened)
            if opened:
                QTimer.singleShot(0, lambda: self.list_view.ensureWidgetVisible(self.fixed_body, 0, 0))
        self.fixed_toggle.toggled.connect(toggled)
        return box

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        from ..app.ui_zoom import px
        stacked = self.width() < px(420)
        for row in self.rows.values():
            row.set_stacked(stacked)

    def _apply_sheet(self) -> None:
        # On the list and the banner, not on the panel: in the Studio drawer
        # the panel already carries the secondary-surface sheet.
        from ..app.ui_zoom import set_sheet
        self._sheet_theme = _theme().key
        sheet = _panel_sheet()
        set_sheet(self.list_view, sheet)
        set_sheet(self.banner, sheet)

    def showEvent(self, event) -> None:
        if self._pending_rows:
            self._row_timer.start(0)
        if _theme().key != self._sheet_theme:  # a theme previewed in 应用设置 meanwhile
            self._apply_sheet()
        super().showEvent(event)

    # ------------------------------------------------------------ filters

    def _filter(self) -> None:
        query = self.search.text().strip().casefold()
        scope = self.scope_filter.currentData() or ''
        changed_only = self.changed_only.isChecked()
        shown_any = False
        for header, group, rows in self._groups:
            visible = 0
            for row in rows:
                action = row.action
                key = row.value()
                haystack = ' '.join((str(tr(action.label)), action.label, str(tr(action.category)), action.category,
                                     key, registry.display(key), ' '.join(key_caps(key)))).casefold()
                hidden = (bool(query and query not in haystack) or bool(scope and action.scope != scope)
                          or (changed_only and not row.changed()))
                row.setHidden(hidden)
                if row.property('firstRow') != (not hidden and not visible):
                    row.setProperty('firstRow', not hidden and not visible)  # no line above the group's top row
                    row.style().unpolish(row)
                    row.style().polish(row)
                visible += not hidden
            header.setVisible(bool(visible))
            group.setVisible(bool(visible))
            shown_any = shown_any or bool(visible)
        bind_text(self.empty_label, '正在查找其余快捷键…' if self._pending_rows else '没有找到匹配的快捷键')
        self.empty_label.setVisible(not shown_any)

    def visible_action_ids(self) -> list[str]:
        return [action_id for action_id, row in self.rows.items() if not row.isHidden()]

    def _update_changed_count(self) -> None:
        count = sum(value != registry.normalize(self._defaults.get(key, '')) for key, value in self.values().items())
        bind_text(self.changed_only, '只看改过的（{count}）', count=count)
        if not count and self.changed_only.isChecked():
            self.changed_only.setChecked(False)
        self.changed_only.setEnabled(bool(count))

    # ------------------------------------------------------------ editing

    def _value(self, action_id: str) -> str:
        row = self.rows.get(action_id)
        return row.value() if row is not None else self._bindings[action_id]

    def _edited(self, action_id: str) -> None:
        value = self._value(action_id)
        reason = registry.reserved_reason(value) if value else ''
        if reason:
            editor = self._editors[action_id]
            editor.blockSignals(True)
            editor.clear()
            editor.blockSignals(False)
            self._bindings[action_id] = ''
            self.rows[action_id].sync()
            self.show_message(tr('{key}：{reason}', key=registry.display(value), reason=tr(reason)), 'error')
            return
        self._bindings[action_id] = value
        self._last_edited = action_id
        self.rows[action_id].sync()
        self._validate_conflicts()
        self._update_changed_count()
        if self.changed_only.isChecked():
            self._filter()

    def _apply_bindings(self, values):
        for command_id, value in values.items():
            if command_id not in self._bindings:
                continue
            self._bindings[command_id] = registry.normalize(value)
            editor = self._editors.get(command_id)
            if editor is not None:
                blocked = editor.blockSignals(True)
                editor.setKeySequence(QKeySequence(value))
                editor.blockSignals(blocked)
                self.rows[command_id].sync()
        self._validate_conflicts()
        self._update_changed_count()
        self._filter()

    def _restore_defaults(self) -> None:
        self._apply_bindings({key:self._defaults.get(key,'') for key in self._bindings})

    def _current_conflicts(self):
        return registry.conflicts(self.values())

    def has_blocking_conflicts(self) -> bool:
        return any(item.blocking for item in self._current_conflicts())

    def show_message(self, text: str, kind: str = 'info') -> None:
        """One line above the list (saved, exported, refused key, clash); empty hides it."""
        self.conflict_label.setText(str(text))
        self.banner.setProperty('kind', kind)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        for label in self.banner.findChildren(QLabel):
            label.style().unpolish(label)
            label.style().polish(label)
        self.banner.setVisible(bool(text))

    def _validate_conflicts(self) -> None:
        blocking = [item for item in self._current_conflicts() if item.blocking]
        clashes: dict[str, str] = {}
        for item in blocking:
            clashes.setdefault(item.first, registry.BY_ID[item.second].label)
            clashes.setdefault(item.second, registry.BY_ID[item.first].label)
        self._clashes = clashes
        for action_id, row in self.rows.items():
            row.set_clash(clashes.get(action_id, ''))
        if blocking:
            details = '；'.join(
                str(tr('「{key}」同时给了「{first}」和「{second}」', key=registry.display(item.key),
                       first=tr(registry.BY_ID[item.first].label), second=tr(registry.BY_ID[item.second].label)))
                for item in blocking[:2]) + ('…' if len(blocking) > 2 else '')
            self.show_message(tr('有 {count} 处按键重复，改好才能保存。', count=len(blocking)) + details, 'error')
        elif self.banner.property('kind') == 'error':
            self.show_message('')
        if self._save_button is not None:
            self._save_button.setEnabled(not blocking)
        self.resolve_button.setVisible(bool(blocking and self._last_edited))

    def _resolve_conflicts(self) -> None:
        """Keep the key on the row just edited; clear the other row of each clash."""
        keep = self._last_edited
        for item in [c for c in self._current_conflicts() if c.blocking]:
            other = item.second if item.first == keep else item.first if item.second == keep else item.second
            if other in self._bindings:
                self._apply_bindings({other:''})
        self._validate_conflicts()

    def values(self) -> dict[str, str]:
        return {command_id: self._value(command_id) for command_id in self._bindings}

    # ------------------------------------------------------------ files

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
            self.show_message(tr('导出失败：{exc}', exc=exc), 'error')
            return
        self.show_message(tr('已导出到 {path}', path=path))

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
            self.show_message(tr('导入失败：{exc}', exc=exc), 'error')
            return False
        self._apply_bindings(bindings)
        return True


# Import compatibility for callers that only inspect/edit this widget. Studio
# always embeds the QWidget and never creates a modal/native shortcut window.
ShortcutSettingsDialog = ShortcutSettingsPanel
