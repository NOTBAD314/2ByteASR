"""原始报告页：识别记录里一份报告的 JSON 单独成页（2026-11-22）。

用户：识别记录里打开 JSON 的界面很难看——它原来挤在详情窗最底下，只露出十来行深色代码。
现在它是识别记录页里的一页（左侧导航保留）：「结构」逐层展开，「文本」带行号和按主题配色的
高亮；可以查找、一键复制、另存为文件。敏感字段（API Key 等）仍先打码再显示、复制和保存。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import qtawesome as qta
from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QKeySequence, QPainter, QShortcut,
                           QSyntaxHighlighter, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QStackedWidget, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QTextEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..i18n import bind_text, tr

# Above this the page suggests saving the JSON as a file instead of pasting it (2026-10-22: a
# 24-minute task's 3.4 MB report pasted into a chat window froze it for 68 s).
LARGE_JSON_BYTES = 1024 * 1024
# QSyntaxHighlighter colours the whole document at once; past this the text stays plain.
HIGHLIGHT_MAX_LINES = 20000
# The 「结构」 view adds children when a row is opened, and at most this many at a time.
TREE_CHILD_LIMIT = 400
SEARCH_MATCH_LIMIT = 2000
_MONO_FAMILIES = ("JetBrains Mono", "Cascadia Mono", "Consolas", "Source Han Sans SC Medium", "Microsoft YaHei UI")
_FONT_READY = False


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def mono_font(point_size: float = 10.0) -> QFont:
    """The bundled JetBrains Mono (registered on first use), then the system's monospace faces;
    Chinese text inside the JSON falls back to the bundled UI face."""
    global _FONT_READY
    if not _FONT_READY:
        _FONT_READY = True
        if "JetBrains Mono" not in QFontDatabase.families():
            try:
                from ..runtime_paths import detect_install_root
                path = Path(detect_install_root()) / "assets" / "fonts" / "JetBrainsMono-Regular.ttf"
                if path.is_file():
                    QFontDatabase.addApplicationFont(str(path))
            except Exception:  # noqa: BLE001 - the system monospace faces then
                pass
    font = QFont()
    font.setFamilies(list(_MONO_FAMILIES))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(point_size)
    return font


def json_palette(t) -> dict[str, str]:
    """Syntax colours from the theme's own tokens, so the code reads as part of the page."""
    violet = "#4b3c9e" if getattr(t, "is_light", True) else "#b2a6f2"
    return {"key": t.accent, "string": t.success, "number": t.warning, "literal": violet,
            "null": t.text_muted, "punctuation": t.text_muted}


def json_page_qss(t) -> str:
    from ..design.typography import TITLE_FONT_STACK
    from ..design.ui_theme import blend_hex
    heavy = f"font-family: {TITLE_FONT_STACK}; font-weight: 800;"
    on_accent = getattr(t, "text_on_accent", "") or "#ffffff"
    gutter = blend_hex(t.surface_elevated, t.text, 0.035 if t.is_light else 0.06)
    chip = blend_hex(t.surface, t.text, 0.06 if t.is_light else 0.12)
    return f"""
QWidget#historyJsonPage {{ background: transparent; }}
QLabel#historyJsonEyebrow {{ color: {t.accent}; font-size: 12px; {heavy} }}
QLabel#historyJsonTitle {{ color: {t.text}; font-size: 22px; {heavy} }}
QLabel#historyJsonChip {{ background: {chip}; color: {t.text_secondary}; border-radius: 9px; padding: 3px 10px;
    font-size: 12px; font-weight: 600; }}
QLabel#historyJsonShield {{ background: {t.success_soft}; color: {t.success}; border-radius: 9px; padding: 3px 10px;
    font-size: 12px; font-weight: 600; }}
QPushButton#historyJsonCopy {{ background: {t.accent}; color: {on_accent}; border: 1px solid {t.accent};
    border-radius: 12px; padding: 9px 18px; {heavy} }}
QPushButton#historyJsonCopy:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#historyJsonCopy:pressed {{ background: {t.accent_pressed}; }}
QPushButton#historyJsonCopy[done="true"] {{ background: {t.success}; border-color: {t.success}; }}
QPushButton#historyJsonSave {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: 12px; padding: 9px 16px; {heavy} }}
QPushButton#historyJsonSave:hover {{ background: {t.surface_elevated}; border-color: {t.border_strong}; }}
QFrame#historyJsonPanel {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 18px; }}
QPlainTextEdit#historyJsonCode {{ background: {t.surface_elevated}; color: {t.text}; border: 0; font-size: 13px;
    font-family: {", ".join(f'"{name}"' for name in _MONO_FAMILIES)}, monospace;
    selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
QTreeWidget#historyJsonTree {{ background: {t.surface_elevated}; color: {t.text}; border: 0; outline: 0;
    selection-background-color: {t.accent_soft}; selection-color: {t.text}; }}
QTreeWidget#historyJsonTree::item {{ padding: 4px 2px; border-radius: 7px; }}
QTreeWidget#historyJsonTree::item:hover {{ background: {t.panel}; }}
QTreeWidget#historyJsonTree::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QTreeWidget#historyJsonTree QHeaderView::section {{ background: transparent; color: {t.text_muted}; border: 0;
    border-bottom: 1px solid {t.border}; padding: 6px 8px; font-size: 12px; {heavy} }}
QLabel#historyJsonNote {{ background: {t.warning_soft}; color: {t.warning}; border-radius: 12px; padding: 9px 14px;
    font-size: 12px; font-weight: 600; }}
QLabel#historyJsonToast {{ color: {t.success}; font-size: 12px; {heavy} }}
QLabel#historyJsonCount {{ color: {t.text_muted}; font-size: 12px; font-weight: 600; }}
QLabel#historyJsonLoading {{ color: {t.text_muted}; font-size: 14px; }}
QWidget#historyJsonGutter {{ background: {gutter}; border-radius: 10px; }}
QStackedWidget#historyJsonViews, QLabel#historyJsonLoading {{ background: {t.surface_elevated}; }}
"""


class JsonHighlighter(QSyntaxHighlighter):
    PATTERNS = (
        ("string", re.compile(r'"(?:\\.|[^"\\])*"')),
        ("key", re.compile(r'"(?:\\.|[^"\\])*"(?=\s*:)')),
        ("number", re.compile(r'(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')),
        ("literal", re.compile(r'\b(?:true|false)\b')),
        ("null", re.compile(r'\bnull\b')),
        ("punctuation", re.compile(r'[{}\[\],:]')),
    )

    def __init__(self, document, palette: dict[str, str]):
        super().__init__(document)
        self._formats = {}
        for name, color in palette.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if name == "key":
                fmt.setFontWeight(QFont.Weight.DemiBold)
            self._formats[name] = fmt

    def highlightBlock(self, text: str):  # noqa: N802 - Qt override
        # Strings first, keys over them; numbers and literals only outside strings.
        strings = []
        for name, pattern in self.PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span()
                if name in {"number", "literal", "null", "punctuation"} and any(s <= start < e for s, e in strings):
                    continue
                if name == "string":
                    strings.append((start, end))
                self.setFormat(start, end - start, self._formats[name])


class _Gutter(QWidget):
    def __init__(self, view: "JsonCodeView"):
        super().__init__(view)
        self.setObjectName("historyJsonGutter")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.view = view

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(self.view.gutter_width(), 0)

    def paintEvent(self, event):  # noqa: N802 - Qt override
        self.view.paint_gutter(event)


class JsonCodeView(QPlainTextEdit):
    """Read-only JSON text with line numbers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyJsonCode")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(mono_font(10.5))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.gutter = _Gutter(self)
        self.number_color = QColor("#999999")
        self.current_color = QColor("#333333")
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self.gutter.update)
        self._update_margins()

    def set_colors(self, number: str, current: str) -> None:
        self.number_color, self.current_color = QColor(number), QColor(current)
        self.gutter.update()

    def gutter_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 26 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self, *_args) -> None:
        self.setViewportMargins(self.gutter_width() + 10, 4, 4, 4)

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        area = self.contentsRect()
        self.gutter.setGeometry(QRect(area.left(), area.top(), self.gutter_width(), area.height()))

    def paint_gutter(self, event) -> None:
        painter = QPainter(self.gutter)
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top()) + 4
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        height = self.fontMetrics().height()
        width = self.gutter.width() - 12
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self.current_color if number == current else self.number_color)
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
        painter.end()


def _type_label(value: Any) -> str:
    if isinstance(value, dict):
        return "对象"
    if isinstance(value, list):
        return "列表"
    if isinstance(value, bool):
        return "是/否"
    if value is None:
        return "空"
    if isinstance(value, (int, float)):
        return "数字"
    return "文字"


def _preview(value: Any) -> str:
    if isinstance(value, dict):
        return "{ " + tr("{count} 个字段", count=len(value)) + " }" if value else "{ }"
    if isinstance(value, list):
        return "[ " + tr("{count} 项", count=len(value)) + " ]" if value else "[ ]"
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 160 else text[:157] + "…\""


class _TreeTextDelegate(QStyledItemDelegate):
    """Draws the row's text itself, in its own colour and the monospace face: the application's
    style paints item text with the view's palette and its style sheet sets the UI face."""

    def __init__(self, tree: "JsonTree"):
        super().__init__(tree)
        self.tree = tree

    def paint(self, painter, option, index):  # noqa: D401 - Qt override
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if not text:
            return
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget).adjusted(4, 0, -4, 0)
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        color = brush.color() if hasattr(brush, "color") else QColor(_theme().text)
        painter.save()
        font = self.tree.mono
        if index.column() == 0 and index.data(JsonTree._VALUE) is not None:
            font = self.tree.mono_bold
        painter.setFont(font)
        painter.setPen(color)
        metrics = QFontMetrics(font)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width()))
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802 - Qt override
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), QFontMetrics(self.tree.mono).height() + 12))


class JsonTree(QTreeWidget):
    """The report as rows that open level by level (children are added when a row opens)."""

    copied = Signal(str)
    _VALUE = Qt.ItemDataRole.UserRole
    _PENDING = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyJsonTree")
        self.setColumnCount(3)
        self.setHeaderLabels([tr("字段"), tr("值"), tr("类型")])
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(0, 260)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setIndentation(20)
        self.mono = mono_font(10.5)
        self.mono_bold = QFont(self.mono)
        self.mono_bold.setWeight(QFont.Weight.DemiBold)
        self.setItemDelegate(_TreeTextDelegate(self))
        self.palette_colors = json_palette(_theme())
        self.itemExpanded.connect(self._populate)
        self.itemDoubleClicked.connect(self._copy_item)
        bind_text(self, "双击一行复制它的值", property="toolTip")

    def set_data(self, data: Any) -> None:
        self.clear()
        self._add_children(self.invisibleRootItem(), data)
        # The first level of each top-level object is open: one glance shows the shape.
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            value = item.data(0, self._VALUE)
            if isinstance(value, (dict, list)) and 0 < len(value) <= 12:
                item.setExpanded(True)

    def _color_for(self, value: Any) -> str:
        palette = self.palette_colors
        if isinstance(value, str):
            return palette["string"]
        if isinstance(value, bool):
            return palette["literal"]
        if value is None:
            return palette["null"]
        if isinstance(value, (int, float)):
            return palette["number"]
        return palette["punctuation"]

    def _add_children(self, parent: QTreeWidgetItem, value: Any, start: int = 0) -> None:
        pairs = list(value.items()) if isinstance(value, dict) else list(enumerate(value)) if isinstance(value, list) else []
        end = min(len(pairs), start + TREE_CHILD_LIMIT)
        key_color = QColor(self.palette_colors["key"])
        for key, child in pairs[start:end]:
            item = QTreeWidgetItem(parent)
            item.setText(0, str(key) if isinstance(value, dict) else f"[{key}]")
            item.setForeground(0, key_color)
            item.setText(1, _preview(child))
            item.setForeground(1, QColor(self._color_for(child)))
            item.setText(2, tr(_type_label(child)))
            item.setForeground(2, QColor(self.palette_colors["null"]))
            item.setData(0, self._VALUE, child)
            if isinstance(child, str) and len(child) > 60:
                item.setToolTip(1, child[:2000])
            if isinstance(child, (dict, list)) and child:
                item.setData(0, self._PENDING, True)
                QTreeWidgetItem(item)          # placeholder so the row can open
        if end < len(pairs):
            more = QTreeWidgetItem(parent)
            more.setText(0, tr("还有 {count} 项…", count=len(pairs) - end))
            more.setForeground(0, QColor(self.palette_colors["null"]))
            more.setData(0, self._PENDING, ("more", value, end))

    def _populate(self, item: QTreeWidgetItem) -> None:
        if item.data(0, self._PENDING) is not True:
            return
        item.setData(0, self._PENDING, None)
        item.takeChildren()
        self._add_children(item, item.data(0, self._VALUE))

    def _copy_item(self, item: QTreeWidgetItem, _column: int) -> None:
        pending = item.data(0, self._PENDING)
        if isinstance(pending, tuple) and pending and pending[0] == "more":
            _tag, value, start = pending
            parent = item.parent() or self.invisibleRootItem()
            parent.removeChild(item)
            self._add_children(parent, value, start)
            return
        value = item.data(0, self._VALUE)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        QApplication.clipboard().setText(text)
        self.copied.emit(item.text(0))


class HistoryJsonPage(QWidget):
    """One report's JSON as its own page inside 识别记录."""

    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("historyJsonPage")
        self.record = None
        self.data: Any = None
        self._raw_text = ""
        self._matches: list[QTextCursor] = []
        self._match_index = -1
        self._highlighter = None
        self._view = "tree"
        self.paged_view = None
        self._build()

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 12)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.back_button = QPushButton()
        self.back_button.setObjectName("historyToolButton")
        self.back_button.setIcon(qta.icon("fa5s.arrow-left", color=_theme().text))
        bind_text(self.back_button, "返回记录")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested)
        header.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        eyebrow = QLabel()
        eyebrow.setObjectName("historyJsonEyebrow")
        bind_text(eyebrow, "原始报告 · JSON")
        titles.addWidget(eyebrow)
        self.title = QLabel()
        self.title.setObjectName("historyJsonTitle")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        titles.addWidget(self.title)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.status_chip = QLabel()
        self.when_chip = QLabel()
        self.when_chip.setObjectName("historyJsonChip")
        self.size_chip = QLabel()
        self.size_chip.setObjectName("historyJsonChip")
        self.shield_chip = QLabel()
        self.shield_chip.setObjectName("historyJsonShield")
        bind_text(self.shield_chip, "🔒 API Key 等敏感字段已打码")
        for chip in (self.status_chip, self.when_chip, self.size_chip, self.shield_chip):
            chips.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        chips.addStretch(1)
        titles.addLayout(chips)
        header.addLayout(titles, 1)
        actions = QVBoxLayout()
        actions.setSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.folder_button = QPushButton()
        self.folder_button.setObjectName("historyToolButton")
        self.folder_button.setIcon(qta.icon("fa5s.folder-open", color=_theme().text))
        bind_text(self.folder_button, "打开报告所在文件夹", property="toolTip")
        bind_text(self.folder_button, "打开报告所在文件夹", property="accessibleName")
        self.folder_button.clicked.connect(self._open_folder)
        buttons.addWidget(self.folder_button)
        self.save_button = QPushButton()
        self.save_button.setObjectName("historyJsonSave")
        bind_text(self.save_button, "另存为…")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        self.copy_button = QPushButton()
        self.copy_button.setObjectName("historyJsonCopy")
        bind_text(self.copy_button, "复制 JSON")
        self.copy_button.clicked.connect(self.copy)
        buttons.addWidget(self.copy_button)
        actions.addLayout(buttons)
        self.toast = QLabel()
        self.toast.setObjectName("historyJsonToast")
        self.toast.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        actions.addWidget(self.toast)
        header.addLayout(actions)
        layout.addLayout(header)

        self.note = QLabel()
        self.note.setObjectName("historyJsonNote")
        self.note.setWordWrap(True)
        self.note.hide()
        layout.addWidget(self.note)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.view_switch = QFrame()
        self.view_switch.setObjectName("historyViewSwitch")
        switch = QHBoxLayout(self.view_switch)
        switch.setContentsMargins(3, 3, 3, 3)
        switch.setSpacing(2)
        self.view_buttons = {}
        for key, text, icon in (("tree", "结构", "fa5s.stream"), ("text", "文本", "fa5s.code")):
            button = QPushButton()
            bind_text(button, text)
            button.setObjectName("historyViewButton")
            button.setCheckable(True)
            button.setChecked(key == self._view)
            button.clicked.connect(lambda _checked=False, key=key: self.set_view(key))
            switch.addWidget(button)
            self.view_buttons[key] = button
        tools.addWidget(self.view_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.expand_button = QPushButton()
        self.expand_button.setObjectName("historyToolButton")
        bind_text(self.expand_button, "全部展开")
        self.expand_button.clicked.connect(self._toggle_expand)
        tools.addWidget(self.expand_button)
        tools.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("historySearch")
        bind_text(self.search, "在 JSON 中查找（Enter 下一个）", property="placeholderText")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self.search.setMaximumWidth(360)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(160)
        self._search_timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        self.search.returnPressed.connect(lambda: self.find_next(1))
        tools.addWidget(self.search, 1)
        self.count_label = QLabel()
        self.count_label.setObjectName("historyJsonCount")
        self.count_label.setMinimumWidth(64)
        tools.addWidget(self.count_label)
        self.prev_button = QPushButton()
        self.next_button = QPushButton()
        for button, icon, step, tip in ((self.prev_button, "fa5s.chevron-up", -1, "上一个"),
                                        (self.next_button, "fa5s.chevron-down", 1, "下一个")):
            button.setObjectName("historyToolButton")
            button.setIcon(qta.icon(icon, color=_theme().text))
            bind_text(button, tip, property="toolTip")
            bind_text(button, tip, property="accessibleName")
            button.clicked.connect(lambda _checked=False, step=step: self.find_next(step))
            tools.addWidget(button)
        self.inline_tools = QWidget()
        tools.setContentsMargins(0, 0, 0, 0)
        self.inline_tools.setLayout(tools)
        layout.addWidget(self.inline_tools)

        self.panel = QFrame()
        self.panel.setObjectName("historyJsonPanel")
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(6, 6, 6, 6)
        self.views = QStackedWidget()
        self.views.setObjectName("historyJsonViews")
        self.tree = JsonTree()
        self.tree.copied.connect(lambda key: self._flash(tr("已复制「{key}」的值", key=key)))
        self.code = JsonCodeView()
        self.loading = QLabel()
        self.loading.setObjectName("historyJsonLoading")
        self.loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading.setWordWrap(True)
        self.views.addWidget(self.tree)
        self.views.addWidget(self.code)
        self.views.addWidget(self.loading)
        panel.addWidget(self.views)
        layout.addWidget(self.panel, 1)

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._focus_search)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._escape)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(2400)
        self._toast_timer.timeout.connect(self._clear_toast)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = _theme()
        for button, icon in ((self.back_button, "fa5s.arrow-left"), (self.folder_button, "fa5s.folder-open"),
                             (self.prev_button, "fa5s.chevron-up"), (self.next_button, "fa5s.chevron-down")):
            button.setIcon(qta.icon(icon, color=t.text))
        self.code.set_colors(t.text_muted, t.accent)
        self.tree.palette_colors = json_palette(t)
        if self._highlighter is not None:
            self._highlight()
        if self.data is not None:
            self.tree.set_data(self.data)

    # ------------------------------------------------------------ content
    @property
    def raw_text(self) -> str:
        return self._raw_text

    def clear_paged_view(self) -> None:
        if self.paged_view is not None:
            self.paged_view.shutdown()
            self.views.removeWidget(self.paged_view)
            self.paged_view.deleteLater()
            self.paged_view = None

    def show_loading(self, record=None, text: str = "") -> None:
        self.clear_paged_view()
        self.inline_tools.show()
        self.note.hide()
        self.copy_button.show()
        self.save_button.show()
        for chip in (self.status_chip, self.when_chip, self.size_chip):
            chip.hide()
        self.record = record
        self.data = None
        self._raw_text = ""
        if record is not None:
            self.title.setText(str(getattr(record, "media_name", "") or ""))
        self.loading.setText(text or tr("正在读取报告…"))
        self.views.setCurrentWidget(self.loading)
        for widget in (self.copy_button, self.save_button, self.search, self.expand_button):
            widget.setEnabled(False)

    def show_record(self, record) -> None:
        """Show ``record`` (a parsed report): its payload with sensitive fields masked."""
        from .recognition_history import RecognitionHistoryDetail, _status_object, redact_report_payload
        self.show_loading(record)
        self.status_chip.show()
        self.size_chip.show()
        self.title.setText(str(record.media_name or Path(str(record.path)).name))
        self.status_chip.setObjectName(_status_object(record.status))
        bind_text(self.status_chip, record.status_label)
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)
        self.when_chip.setText(str(getattr(record, "completed_at", "") or ""))
        self.when_chip.setVisible(bool(self.when_chip.text()))
        if getattr(record, 'report_pages', None) is not None:
            self.size_chip.setText(_size_label(record.report_pages.identity[0]))
            self.inline_tools.hide()
            self.save_button.hide()
            self.copy_button.hide()
            self.paged_view = RecognitionHistoryDetail(record, raw_only=True)
            self.views.addWidget(self.paged_view)
            self.views.setCurrentWidget(self.paged_view)
            if self.property('_uiZoomApplied') is not None:
                from ..app.ui_zoom import apply_to
                apply_to(self.paged_view)
            return
        self.data = redact_report_payload(record.payload)
        self._raw_text = json.dumps(self.data, ensure_ascii=False, indent=2)
        size = len(self._raw_text.encode("utf-8"))
        lines = self._raw_text.count("\n") + 1
        self.size_chip.setText(tr("{size} · {lines} 行", size=_size_label(size), lines=f"{lines:,}"))
        if size >= LARGE_JSON_BYTES:
            bind_text(self.note, "这份 JSON 有 {size}，粘贴到聊天或 AI 窗口可能让它卡住很久；要分享时请点“另存为…”保存成文件再附上。",
                      size=_size_label(size))
        self.note.setVisible(size >= LARGE_JSON_BYTES)
        self.code.setPlainText(self._raw_text)
        self._highlighter = None
        self._highlight()
        self.tree.set_data(self.data)
        self._expanded = False
        bind_text(self.expand_button, "全部展开")
        for widget in (self.copy_button, self.save_button, self.search, self.expand_button):
            widget.setEnabled(True)
        self._matches, self._match_index = [], -1
        self.count_label.clear()
        if self.search.text():
            self._run_search()
        self._clear_toast()
        self.set_view(self._view)

    def _highlight(self) -> None:
        if self.code.document().blockCount() > HIGHLIGHT_MAX_LINES:
            return
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
        self._highlighter = JsonHighlighter(self.code.document(), json_palette(_theme()))

    def set_view(self, key: str) -> None:
        self._view = key if key in {"tree", "text"} else "tree"
        for name, button in self.view_buttons.items():
            button.setChecked(name == self._view)
        self.expand_button.setVisible(self._view == "tree")
        if self.data is None:
            return
        from ..design.transitions import content_change
        target = self.tree if self._view == "tree" else self.code
        if self.views.currentWidget() is not target:
            with content_change(self.views):
                self.views.setCurrentWidget(target)

    def _toggle_expand(self) -> None:
        self._expanded = not getattr(self, "_expanded", False)
        if self._expanded:
            # Opens every row that is already there and one level below each (big lists stay bounded).
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                item.setExpanded(True)
                for child in range(item.childCount()):
                    item.child(child).setExpanded(True)
            bind_text(self.expand_button, "全部收起")
        else:
            self.tree.collapseAll()
            bind_text(self.expand_button, "全部展开")

    # ------------------------------------------------------------ search
    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.back_requested.emit()

    def _run_search(self) -> None:
        needle = self.search.text()
        self._matches, self._match_index = [], -1
        document = self.code.document()
        if needle and self.data is not None:
            cursor = QTextCursor(document)
            while len(self._matches) < SEARCH_MATCH_LIMIT:
                cursor = document.find(needle, cursor)
                if cursor.isNull():
                    break
                self._matches.append(QTextCursor(cursor))
        if needle and self._view != "text":
            self.set_view("text")
        if self._matches:
            self._match_index = 0
        self._show_matches()

    def find_next(self, step: int = 1) -> None:
        if not self._matches:
            self._run_search()
            return
        self._match_index = (self._match_index + step) % len(self._matches)
        self._show_matches()

    def _show_matches(self) -> None:
        t = _theme()
        selections = []
        for index, cursor in enumerate(self._matches[:SEARCH_MATCH_LIMIT]):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor(t.accent if index == self._match_index else t.warning_soft))
            if index == self._match_index:
                selection.format.setForeground(QColor(getattr(t, "text_on_accent", "") or "#ffffff"))
            selections.append(selection)
        self.code.setExtraSelections(selections)
        if self._matches:
            current = QTextCursor(self._matches[self._match_index])
            current.clearSelection()
            self.code.setTextCursor(current)
            self.code.centerCursor()
            more = "+" if len(self._matches) >= SEARCH_MATCH_LIMIT else ""
            self.count_label.setText(f"{self._match_index + 1} / {len(self._matches)}{more}")
        else:
            self.count_label.setText(tr("无匹配") if self.search.text() else "")

    # ------------------------------------------------------------ actions
    def copy(self) -> None:
        if not self._raw_text:
            return
        QApplication.clipboard().setText(self._raw_text)
        bind_text(self.copy_button, "✓ 已复制")
        self.copy_button.setProperty("done", True)
        self.copy_button.style().unpolish(self.copy_button)
        self.copy_button.style().polish(self.copy_button)
        self._flash(tr("JSON 已复制到剪贴板"))

    def save(self) -> None:
        if not self._raw_text:
            return
        from PySide6.QtCore import QStandardPaths
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
        name = str(getattr(self.record, "media_name", "") or "recognition")
        stem = re.sub(r'[\\/:*?"<>|]+', "_", Path(name).stem)[:80] or "recognition"
        path, _filter = QFileDialog.getSaveFileName(self, tr("另存为…"), str(Path(folder) / f"{stem}.json"),
                                                    "JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).resolve() == Path(self.record.path).resolve():
                raise ValueError(tr('请选择不同于原报告的文件'))
            from ..storage.atomic_files import write_text_atomic
            write_text_atomic(Path(path), self._raw_text)
        except (OSError, ValueError) as exc:
            self._flash(tr("保存失败：{error}", error=str(exc)), error=True)
        else:
            self._flash(tr("已保存到 {path}", path=Path(path).name))

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = Path(str(getattr(self.record, "path", "") or ""))
        folder = path.parent
        if str(path) and folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _flash(self, text: str, *, error: bool = False) -> None:
        t = _theme()
        self.toast.setStyleSheet(f"color: {t.danger};" if error else "")
        self.toast.setText(text)
        self._toast_timer.start()

    def _clear_toast(self) -> None:
        self.toast.clear()
        if self.copy_button.property("done"):
            bind_text(self.copy_button, "复制 JSON")
            self.copy_button.setProperty("done", False)
            self.copy_button.style().unpolish(self.copy_button)
            self.copy_button.style().polish(self.copy_button)


def _size_label(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"
