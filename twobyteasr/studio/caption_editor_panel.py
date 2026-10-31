"""Compact caption controls inside the nonmodal native tool window."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QTextOption
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)


def _signature(row):
    return (row.start, row.end, row.original, str(row.kind), tuple(o.text for o in row.options))


@dataclass
class _DisplayRow:
    row: object
    status: str = "pending"
    replacement: str = ""


class CaptionSuggestionView(QScrollArea):
    """Explicit word/option grid; handled rows retain their navigation position."""
    activated = Signal(int, int)
    selected_changed = Signal()
    location_requested = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("captionSuggestionScroll")
        self.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.setProperty('uiZoomOwnSize', True)
        self._fit_pending = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._body = QWidget(self)
        self._body.setObjectName("captionSuggestionsBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(7, 3, 7, 3)
        self._layout.setSpacing(2)
        self.setWidget(self._body)
        self._body.installEventFilter(self)
        self._suggestions = ()
        self._display = []
        self._text = self._expected_text = ""
        self._selection = None
        self._frames = []
        self._buttons = {}

    def reset(self):
        self._display = []
        self._text = self._expected_text = ""
        self._selection = None
        self.update_rows("", ())

    @property
    def selected(self):
        if self._selection is None:
            return (-1, -1)
        index, option = self._selection
        if not 0 <= index < len(self._display):
            return (-1, -1)
        item = self._display[index]
        if item.status != "pending":
            return (-1, -1)
        key = _signature(item.row)
        for mark, row in enumerate(self._suggestions):
            if _signature(row) == key:
                return mark, option
        return (-1, -1)

    @selected.setter
    def selected(self, value):
        mark, option = value
        if not 0 <= mark < len(self._suggestions):
            self._selection = None
        else:
            key = _signature(self._suggestions[mark])
            index = next((i for i, item in enumerate(self._display)
                          if item.status == "pending" and _signature(item.row) == key), None)
            self._selection = None if index is None else (index, option)
        self._paint_selection()

    def owns_focus(self):
        focus = QApplication.focusWidget()
        return focus is self or (focus is not None and self.isAncestorOf(focus))

    def has_rows(self):
        return bool(self._display)

    def update_rows(self, text, rows):
        focused = self.owns_focus()
        rows = tuple(rows)
        preserve = text == self._text or text == self._expected_text
        if not preserve:
            self._display = []
            self._selection = None
        by_key = {_signature(row): row for row in rows}
        merged = []
        selected_item = (self._display[self._selection[0]]
                         if self._selection and self._selection[0] < len(self._display) else None)
        selected_option = self._selection[1] if self._selection else 0
        for item in self._display:
            if item.status != "pending":
                merged.append(item)
                continue
            row = by_key.pop(_signature(item.row), None)
            if row is not None:
                item.row = row
                merged.append(item)
        merged.extend(_DisplayRow(row) for row in by_key.values())
        self._display = sorted(merged, key=lambda item: (item.row.start, item.row.end))
        self._suggestions = rows
        self._text = self._expected_text = text
        if selected_item is not None and selected_item in self._display:
            self._selection = (self._display.index(selected_item), selected_option)
        elif self._display:
            first = next((i for i, item in enumerate(self._display) if item.status == "pending"), 0)
            self._selection = (first, 0)
        else:
            self._selection = None
        self._rebuild()
        if focused:
            self.focus_current()

    def stage_patch(self, start, end, replacement, new_text):
        """Only a validated draft patch can carry old row locations forward."""
        from dataclasses import replace
        delta = len(replacement) - (end - start)
        for item in self._display:
            row = item.row
            if row.start == start and row.end == end and item.status == "pending":
                item.status, item.replacement = "applied", replacement
                item.row = replace(row, end=start + len(replacement))
            elif row.start >= end:
                item.row = replace(row, start=row.start + delta, end=row.end + delta)
        self._expected_text = new_text

    def stage_ignore(self):
        if self._selection is not None and self.selected[0] >= 0:
            self._display[self._selection[0]].status = "ignored"
            self._expected_text = self._text

    def select_first(self):
        first = next((i for i, item in enumerate(self._display) if item.status == "pending"), None)
        if first is None:
            return False
        self._selection = (first, 0)
        self.focus_current()
        return True

    def navigate(self, vertical=0, horizontal=0):
        """Return False on down from the final row, to return to the draft."""
        if not self._display:
            return False
        index, option = self._selection or (0, 0)
        if vertical > 0 and index == len(self._display) - 1:
            return False
        index = max(0, min(len(self._display) - 1, index + vertical))
        count = max(1, len(self._display[index].row.options))
        option = max(0, min(count - 1, option + horizontal))
        self._selection = index, option
        self.focus_current()
        return True

    def cycle(self, direction, *, from_body=False):
        """Read-order candidates plus one body stop, shared by A and D."""
        entries = [(index, option) for index, item in enumerate(self._display)
                   for option in range(max(1, len(item.row.options)) if item.status == 'pending' else 1)]
        if not entries:
            return False
        if from_body:
            target = entries[0] if direction > 0 else entries[-1]
        else:
            index = entries.index(self._selection) if self._selection in entries else 0
            next_index = index + (1 if direction > 0 else -1)
            if not 0 <= next_index < len(entries):
                return False
            target = entries[next_index]
        self._selection = target
        self.focus_current()
        return True

    def focus_current(self):
        if self._selection is None:
            return
        target = self._buttons.get(self._selection) or self._frames[self._selection[0]]
        # Explicit candidate navigation may cross from the timeline into the
        # non-activating tool; activation belongs to this user action only.
        QApplication.setActiveWindow(self.window())
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.ensureWidgetVisible(target, 0, 0)
        self._paint_selection()
        item = self._display[self._selection[0]]
        if item.status == "pending":
            self.location_requested.emit(item.row.start, item.row.end)
        self.selected_changed.emit()

    def candidate_button(self, mark, option):
        self.selected = mark, option
        return self._buttons.get(self._selection)

    def _choose(self, index, option):
        self._selection = index, option
        self._paint_selection()
        self.selected_changed.emit()

    def _activate(self, index, option):
        self._choose(index, option)
        mark, selected = self.selected
        if mark >= 0:
            self.activated.emit(mark, selected)

    def _rebuild(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._frames, self._buttons = [], {}
        for index, item in enumerate(self._display):
            frame = QFrame(self._body)
            frame.setObjectName("captionSuggestionRow")
            frame.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            row_layout = QHBoxLayout(frame)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            suspect = QPushButton(f"「{item.row.original or '∅'}」".replace('&', '&&'), frame)
            suspect.setObjectName("captionSuspect")
            suspect.setToolTip(f"第 {item.row.start + 1}–{item.row.end} 字；只处理这一处")
            suspect.setEnabled(item.status == "pending")
            suspect.clicked.connect(lambda checked=False, i=index: self._locate(i))
            row_layout.addWidget(suspect)
            position = QLabel(f"{item.row.start + 1}–{item.row.end} 字", frame)
            position.setObjectName("captionEditorMeta")
            row_layout.addWidget(position)
            arrow = QLabel("→", frame)
            arrow.setObjectName("captionEditorMeta")
            row_layout.addWidget(arrow)
            if item.status == "pending":
                for option, value in enumerate(item.row.options):
                    button = QPushButton((value.text or "∅").replace('&', '&&'), frame)
                    button.setObjectName("captionCandidateButton")
                    button.setAccessibleName(f"将{item.row.original}替换为{value.text}")
                    button.setToolTip("点击或空格采纳当前选项；Shift+R 保存并关闭")
                    button.setCheckable(True)
                    button.setAutoExclusive(False)
                    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                    button.clicked.connect(lambda checked=False, i=index, j=option: self._activate(i, j))
                    button.installEventFilter(self)
                    button._caption_choice = (index, option)
                    self._buttons[index, option] = button
                    row_layout.addWidget(button)
            else:
                text = f"{item.replacement} · 已采纳" if item.status == "applied" else "已忽略此建议"
                result = QLabel(text, frame)
                result.setObjectName("captionSuggestionHandled")
                row_layout.addWidget(result)
            row_layout.addStretch(1)
            self._layout.addWidget(frame)
            # Include freshly rebuilt rows in the layout hint even when the
            # scroll area was hidden for the previous empty suggestion set.
            frame.show()
            self._frames.append(frame)
        count = len(self._display)
        self._fit_rows()
        self._schedule_fit()
        self.setVisible(bool(count))
        self._paint_selection()
        self.selected_changed.emit()
        owner=self.window()
        if hasattr(owner,'schedule_fit'):owner.schedule_fit()

    def _locate(self, index):
        self._selection = index, 0
        self.focus_current()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self._body and event.type() == QEvent.Type.LayoutRequest:
            self._schedule_fit()
        if event.type() == QEvent.Type.FocusIn and hasattr(watched, "_caption_choice"):
            self._choose(*watched._caption_choice)
        return super().eventFilter(watched, event)

    def _schedule_fit(self):
        if self._fit_pending:
            return
        self._fit_pending = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._fit_rows)

    def _fit_rows(self):
        self._fit_pending = False
        for frame in self._frames:
            for widget in (frame, *frame.findChildren(QWidget)):
                widget.ensurePolished()
        self._layout.activate()
        height = min(110, self._layout.sizeHint().height()) if self._display else 0
        if self.height() != height or self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def _paint_selection(self):
        for key, button in self._buttons.items():
            button.setChecked(key == self._selection)
        for index, frame in enumerate(self._frames):
            chosen = self._selection is not None and index == self._selection[0]
            if frame.property("selected") != chosen:
                frame.setProperty("selected", chosen)
                frame.style().unpolish(frame)
                frame.style().polish(frame)


class CaptionShortcutHint(QWidget):
    """Wrap complete shortcut groups; never split an instruction mid-word."""
    def __init__(self,parent=None):
        super().__init__(parent)
        from ..design.soft_widgets import WrapLayout
        self._flow=WrapLayout(self,spacing=10,fill=False)
        self._text=''
        self.groups=[]
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        policy=self.sizePolicy();policy.setHeightForWidth(True);self.setSizePolicy(policy)

    def text(self):
        return self._text

    def setText(self,text):
        text=str(text)
        if text==self._text:return
        self._text=text
        while self._flow.count():
            item=self._flow.takeAt(0)
            if item.widget() is not None:
                item.widget().hide();item.widget().deleteLater()
        self.groups=[]
        for part in text.split(' · '):
            label=QLabel(part,self);label.setObjectName('subtitleEditCardHint')
            label.setWordWrap(False);label.setTextFormat(Qt.TextFormat.PlainText)
            self._flow.addWidget(label);label.show();self.groups.append(label)
        self.setAccessibleName(text)
        self._flow.invalidate();self.updateGeometry()


class CaptionEditorPanel(QFrame):
    """A-style header, bold editable field and one compact tools/actions row."""
    def __init__(self, editor_type, parent=None):
        super().__init__(parent)
        self.setObjectName("subtitleEditCard")
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._resize_queued = False
        self.setMinimumWidth(0)
        self.setMaximumWidth(1100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy=self.sizePolicy();policy.setHeightForWidth(True);self.setSizePolicy(policy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(9)
        self.title = QLabel("编辑字幕", self)
        self.title.setObjectName("subtitleEditCardTitle")
        header.addWidget(self.title)
        self.role = QLabel(self)
        self.role.setObjectName("captionEditorRole")
        header.addWidget(self.role)
        self.meta = QLabel(self)
        self.meta.setObjectName("captionEditorMeta")
        self.meta.setWordWrap(True)
        header.addWidget(self.meta, 1)
        self.close_button = QPushButton("×", self)
        self.close_button.setObjectName("captionClose")
        self.close_button.setAccessibleName("保存并收起编辑浮窗")
        self.close_button.setToolTip("保存修改并收起")
        self.close_button.setFixedSize(26, 26)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.suggestions = CaptionSuggestionView(self)
        layout.addWidget(self.suggestions)
        self.suggestions.hide()
        self.reference = QLabel(self)
        self.reference.setObjectName("captionEditorReference")
        self.reference.setTextFormat(Qt.TextFormat.PlainText)
        self.reference.setWordWrap(True)
        self.reference.setMaximumHeight(65)
        self.reference.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.reference)
        self.reference.hide()
        self.editor = editor_type(self)
        self.editor.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.editor.setObjectName("subtitleEditCardInput")
        self.editor.setMinimumWidth(0)
        self.editor.setTabChangesFocus(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont(self.editor.font())
        font.setPixelSize(18)
        font.setWeight(QFont.Weight.DemiBold)
        self.editor.setFont(font)
        self.editor.document().setDocumentMargin(0)
        option = self.editor.document().defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignLeft)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.document().setDefaultTextOption(option)
        self.editor.setFixedHeight(48)
        layout.addWidget(self.editor)
        self.error_label = QLabel(self)
        self.error_label.setObjectName("captionEditorError")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_row = QHBoxLayout()
        error_row.setContentsMargins(0, 0, 0, 0)
        error_row.setSpacing(6)
        error_row.addWidget(self.error_label, 1)
        self.error_toggle = QToolButton(self)
        self.error_toggle.setText("技术详情")
        self.error_toggle.setCheckable(True)
        error_row.addWidget(self.error_toggle)
        self.error_host = QWidget(self)
        self.error_host.setLayout(error_row)
        layout.addWidget(self.error_host)
        self.error_host.hide()
        self.error_detail = QLabel(self)
        self.error_detail.setObjectName("captionEditorReference")
        self.error_detail.setWordWrap(True)
        self.error_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.error_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_detail.hide()
        layout.addWidget(self.error_detail)
        self.error_toggle.toggled.connect(self.error_detail.setVisible)
        self.hint = CaptionShortcutHint(self)
        layout.addWidget(self.hint)
        footer = QHBoxLayout()
        footer.setSpacing(5)
        self.pronoun_button = QPushButton("他 / 她", self)
        self.pronoun_button.setToolTip("Shift+P · 切换当前草稿里的全部人称，不需要移动光标")
        self.pronoun_button.setObjectName("captionQuiet")
        footer.addWidget(self.pronoun_button)
        self.reference_button = QPushButton("原文参考", self)
        self.reference_button.setObjectName("captionQuiet")
        self.reference_button.setCheckable(True)
        self.reference_button.toggled.connect(self.reference.setVisible)
        self.reference_button.hide()
        footer.addWidget(self.reference_button)
        self.ignore_button = QPushButton("忽略此建议", self)
        self.ignore_button.setObjectName("captionQuiet")
        self.ignore_button.setToolTip("仅忽略当前词、本条字幕和当前语言层；确认后生效")
        self.ignore_button.hide()
        footer.addWidget(self.ignore_button)
        footer.addStretch(1)
        self.cancel_button = QPushButton("取消修改", self)
        self.cancel_button.setObjectName("captionQuiet")
        self.cancel_button.setToolTip("Esc · 取消并还原草稿")
        footer.addWidget(self.cancel_button)
        self.confirm_button = QPushButton("确认", self)
        self.confirm_button.setObjectName("captionConfirm")
        self.confirm_button.setToolTip("Enter / Shift+R · 保存成功后关闭")
        footer.addWidget(self.confirm_button)
        layout.addLayout(footer)
        self.editor.textChanged.connect(self.resize_editor)
        self.suggestions.selected_changed.connect(self.update_hint)
        self.editor.installEventFilter(self)
        self.update_hint()

    def reset(self):
        self.suggestions.reset()
        self.reference_button.setChecked(False)
        self.reference.hide()
        self.error_host.hide()
        self.error_toggle.setChecked(False)
        self.error_label.clear()
        self.error_detail.clear()

    def set_error(self, summary, detail):
        self.error_label.setText(summary)
        self.error_label.show()
        self.error_detail.setText(detail)
        self.error_toggle.setChecked(False)
        self.error_host.show()

    def update_hint(self):
        candidate_mode = self.suggestions.owns_focus()
        if candidate_mode:
            text = "Shift+A/D 候选↔正文 · Shift+W 上一行 · 空格采纳 · Shift+Enter 换行 · Enter/Shift+R 保存并关闭"
        else:
            text = "Shift+A/D 光标 · Shift+Enter 换行 · Enter/Shift+R 保存并关闭"
            if self.suggestions.has_rows():
                text = "Shift+A/D 候选↔正文 · Shift+W 候选 · Shift+Enter 换行 · Enter/Shift+R 保存并关闭"
        self.hint.setText(text)
        self.ignore_button.setEnabled(self.suggestions.selected[0] >= 0)
        self.updateGeometry()
        owner=self.window()
        if hasattr(owner,'schedule_fit'):owner.schedule_fit()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self.editor and event.type() == QEvent.Type.FocusIn:
            self.update_hint()
        return super().eventFilter(watched, event)

    def resize_editor(self):
        # Bound this small field using font metrics, without forcing full
        # document layout on each key or recursively resizing from show events.
        import math
        metrics = self.editor.fontMetrics()
        width = max(80, self.editor.viewport().width() - 18)
        lines = 0
        for text in self.editor.toPlainText().split('\n'):
            lines += max(1, math.ceil(metrics.horizontalAdvance(text[:512]) / width))
            if lines >= 4:
                break
        target = max(48, min(112, metrics.lineSpacing() * min(4, max(1, lines)) + 16))
        if self.editor.height() != target:
            self.editor.setFixedHeight(target)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (not hasattr(self, 'editor') or event.size().width() == event.oldSize().width()
                or self._resize_queued):
            return
        self._resize_queued = True
        def resized():
            self._resize_queued = False
            self.resize_editor()
        QTimer.singleShot(0, self, resized)

    def refresh_theme_palette(self, theme=None):
        # ThemeRootFilter invokes this callback without arguments when a
        # previously hidden panel is shown after an application theme change.
        from ..design.ui_theme import blend_hex, theme_definition
        if theme is None:
            from ..design.theme_manager import theme_key
            theme = theme_definition(theme_key())
        field = theme.surface_elevated if theme.is_light else blend_hex(theme.panel, "#000000", .28)
        panel = blend_hex(theme.surface_elevated, theme.accent, .08 if theme.is_light else .15)
        self.setStyleSheet(
            f"QFrame#subtitleEditCard{{background:{panel};border:1px solid {theme.focus};border-radius:8px;}}"
            f"QLabel#subtitleEditCardTitle{{color:{theme.text};font-size:14px;font-weight:600;}}"
            f"QLabel#captionEditorMeta,QLabel#subtitleEditCardHint{{color:{theme.text_muted};font-size:11px;}}"
            f"QLabel#captionEditorRole{{background:{theme.accent_soft};color:{theme.accent_text};padding:1px 5px;border-radius:3px;font-size:11px;}}"
            f"QPlainTextEdit#subtitleEditCardInput{{background:{field};color:{theme.text};border:1px solid {theme.border_strong};border-radius:5px;padding:6px 8px;font-size:18px;font-weight:600;selection-background-color:{theme.accent};selection-color:{theme.text_on_accent};}}"
            f"QPlainTextEdit#subtitleEditCardInput:focus{{border:1px solid {theme.focus};}}"
            f"QPushButton#captionQuiet,QPushButton#captionClose{{background:transparent;color:{theme.text_muted};border:1px solid transparent;border-radius:4px;padding:3px 6px;font-size:11px;min-height:20px;}}"
            f"QPushButton#captionQuiet:hover,QPushButton#captionClose:hover{{background:{theme.input_surface};border-color:{theme.border};}}"
            f"QPushButton#captionConfirm{{background:{theme.accent};color:{theme.text_on_accent};border:1px solid {theme.accent};border-radius:5px;min-height:22px;padding:3px 16px;font-size:12px;font-weight:600;}}"
            f"QPushButton#captionConfirm:hover{{background:{theme.accent_hover};}}"
            f"QScrollArea#captionSuggestionScroll,QWidget#captionSuggestionsBody{{background:{theme.accent_soft};border:0;border-radius:4px;}}"
            f"QFrame#captionSuggestionRow{{background:transparent;border:0;}}"
            f"QFrame#captionSuggestionRow:focus{{border:1px solid {theme.focus};}}"
            f"QPushButton#captionCandidateButton{{background:{field};color:{theme.text};border:1px solid {theme.border};border-radius:4px;min-height:21px;padding:1px 8px;font-size:13px;}}"
            f"QPushButton#captionCandidateButton:checked,QPushButton#captionCandidateButton:focus{{border:1px solid {theme.focus};color:{theme.accent_text};}}"
            f"QPushButton#captionSuspect{{color:{theme.text};font-size:12px;background:transparent;border:0;padding:1px 0;min-height:21px;}}"
            f"QLabel#captionSuggestionHandled{{color:{theme.text_muted};font-size:12px;}}"
            f"QLabel#captionEditorReference{{color:{theme.text_muted};background:{theme.input_surface};padding:4px 6px;font-size:12px;}}"
            f"QLabel#captionEditorError{{color:{theme.danger};font-size:12px;}}"
        )
