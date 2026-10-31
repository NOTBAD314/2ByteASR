"""Shared pieces of the subtitle export dialogs (2026-10-18 redesign).

Format cards with one line on what each format is for, a segmented choice
for speaker splitting and destination, a short path with “打开文件夹”, and a
preview of the files an export will write. Used by the Studio “导出字幕”
dialog and the home completion page's export dialog.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..design.presentation import button_role
from ..design.themed_icons import themed_icon
from ..i18n import bind_text, tr

FORMAT_CARDS = (
    ("srt", "SRT", "最通用：剪映、Premiere、播放器都能读"),
    ("ass", "ASS", "保留字体、颜色和特效，给 Aegisub 或压制用"),
    ("txt", "TXT", "纯文字稿，方便校对或贴到视频简介"),
    ("json", "JSON", "含逐字时间和说话人，给程序处理"),
)
SPEAKER_CHOICES = (("combined", "合并成一份"), ("per_speaker", "每人一份"), ("both", "两种都要"))
DESTINATION_CHOICES = (("source", "视频旁边"), ("project", "工程 exports"), ("custom", "其他文件夹…"))
LANGUAGE_CHOICES = (("original", "原文"), ("translation", "译文"), ("bilingual", "双语（同一条两行）"))
_PREVIEW_ROWS = 8


def build_subtitle_export_qss(theme) -> str:
    return f"""
        QLabel#exportSectionLabel {{ color: {theme.text_muted}; font-size: 12px; font-weight: 700; background: transparent; }}
        QLabel#exportDialogTitle {{ color: {theme.text}; font-size: 17px; font-weight: 700; background: transparent; }}
        QLabel#exportDialogMeta {{ color: {theme.text_muted}; background: transparent; }}
        QPushButton#formatCard {{ background: {theme.surface_elevated}; border: 1px solid {theme.border};
            border-radius: 9px; padding: 0; max-height: 16777215px; text-align: left; }}
        QPushButton#formatCard:hover {{ border-color: {theme.accent}; }}
        QPushButton#formatCard:checked {{ border-color: {theme.accent}; background: {theme.accent_tint}; }}
        QPushButton#formatCard:focus {{ border-color: {theme.focus}; }}
        QLabel#formatCardBox {{ border: 2px solid {theme.border_strong}; border-radius: 4px; color: transparent;
            background: {theme.input_surface}; font-size: 11px; font-weight: 900; }}
        QLabel#formatCardBox[checked="true"] {{ background: {theme.accent}; border-color: {theme.accent}; color: {theme.text_on_accent}; }}
        QLabel#formatCardTitle {{ color: {theme.text}; font-size: 14px; font-weight: 700; background: transparent; }}
        QLabel#formatCardNote {{ color: {theme.text_secondary}; font-size: 12px; background: transparent; }}
        QPushButton#segmentChoice {{ background: {theme.input_surface}; color: {theme.text_secondary};
            border: 1px solid {theme.border_strong}; border-radius: 0; padding: 5px 12px; min-height: 24px; }}
        QPushButton#segmentChoice[segment="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
        QPushButton#segmentChoice[segment="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
        QPushButton#segmentChoice[segment="middle"], QPushButton#segmentChoice[segment="last"] {{ border-left: 0; }}
        QPushButton#segmentChoice:hover {{ color: {theme.text}; background: {theme.selected}; }}
        QPushButton#segmentChoice:checked {{ background: {theme.accent}; border-color: {theme.accent};
            color: {theme.text_on_accent}; font-weight: 700; }}
        QPushButton#exportChip {{ background: {theme.input_surface}; color: {theme.text_secondary};
            border: 1px solid {theme.border_strong}; border-radius: 13px; padding: 3px 12px; min-height: 20px; }}
        QPushButton#exportChip:hover {{ color: {theme.text}; border-color: {theme.accent}; }}
        QPushButton#exportChip:checked {{ background: {theme.accent}; border-color: {theme.accent};
            color: {theme.text_on_accent}; font-weight: 700; }}
        QFrame#exportPathRow, QFrame#exportFileList {{ background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 8px; }}
        QFrame#exportPathRow QLabel, QFrame#exportFileList QLabel {{ background: transparent; }}
        QLabel#exportPathText {{ color: {theme.text}; font-family: Consolas, "Cascadia Mono", monospace; }}
        QLabel#exportFileHeader {{ color: {theme.text_muted}; font-size: 12px; }}
        QLabel#exportFileName {{ color: {theme.text_secondary}; font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; }}
        QLabel#exportFileName[status="replace"], QLabel#exportFileName[status="renamed"] {{ color: {theme.warning}; }}
        QLabel#exportHint {{ color: {theme.text_muted}; font-size: 12px; background: transparent; }}
        QLabel#exportDoneBadge {{ background: {theme.accent_tint}; color: {theme.accent_text}; border-radius: 18px;
            font-size: 18px; font-weight: 900; }}
        QFrame#exportDialogFooter {{ background: {theme.panel}; border-top: 1px solid {theme.border}; }}
    """


def section_label(text: str) -> QLabel:
    label = QLabel()
    label.setObjectName("exportSectionLabel")
    bind_text(label, text)
    return label


def open_folder(path) -> bool:
    folder = Path(path)
    if not folder.is_dir():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))


class FormatCard(QPushButton):
    """A checkable card: tick box, format name and one line on its use."""

    def __init__(self, title: str, note: str, parent=None):
        super().__init__(parent)
        self.setObjectName("formatCard")
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(title)
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(2)
        self.box = QLabel("✓")
        self.box.setObjectName("formatCardBox")
        self.box.setFixedSize(18, 18)
        self.box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(title)
        self.title.setObjectName("formatCardTitle")
        self.note = QLabel()
        self.note.setObjectName("formatCardNote")
        self.note.setWordWrap(True)
        bind_text(self.note, note)
        bind_text(self, note, property="toolTip")
        for label in (self.box, self.title, self.note):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        grid.addWidget(self.box, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.title, 0, 1)
        grid.addWidget(self.note, 1, 1)
        grid.setColumnStretch(1, 1)
        # A taller neighbour (wrapped note) stretches the row: keep text on top.
        grid.setRowStretch(2, 1)
        self.toggled.connect(self._sync)
        self._sync(False)

    def _sync(self, checked: bool) -> None:
        self.box.setProperty("checked", bool(checked))
        self.box.style().unpolish(self.box)
        self.box.style().polish(self.box)

    def sizeHint(self) -> QSize:
        hint = self.layout().sizeHint()
        return QSize(max(180, hint.width()), hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(160, self.layout().minimumSize().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Generic button CSS supplies an explicit minimum height, which makes
        # Qt ignore this card's minimumSizeHint when a dialog is constrained by
        # screen size. Keep the two text rows readable; the dialog can scroll.
        margins = self.layout().contentsMargins()
        width = max(1, self.width() - margins.left() - margins.right()
                    - self.box.width() - self.layout().horizontalSpacing())
        note_height = max(self.note.fontMetrics().height(), self.note.heightForWidth(width))
        height = (margins.top() + margins.bottom() + self.layout().verticalSpacing()
                  + max(self.box.height(), self.title.sizeHint().height()) + note_height)
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
            self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.layout().totalHeightForWidth(width)


class SegmentedChoice(QWidget):
    """One choice of a few, as a segmented control (QComboBox-like accessors)."""

    changed = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self._keys = [key for key, _label in options]
        for index, (key, label) in enumerate(options):
            button = QPushButton()
            bind_text(button, label)
            button.setObjectName("segmentChoice")
            button.setProperty("segment", "first" if index == 0 else "last" if index == len(options) - 1 else "middle")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=key: self.changed.emit(value))
            self.group.addButton(button, index)
            self.buttons[key] = button
            layout.addWidget(button)

    def value(self) -> str:
        return next((key for key, button in self.buttons.items() if button.isChecked()), "")

    def set_value(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    # QComboBox-style accessors kept for scripted acceptance runs.
    def currentData(self) -> str:
        return self.value()

    def findData(self, key: str) -> int:
        return self._keys.index(key) if key in self._keys else -1

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            self.set_value(self._keys[index])
            self.changed.emit(self._keys[index])


class ElidedPathLabel(QLabel):
    """A path shortened in the middle; the full path is the tooltip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self.setObjectName("exportPathText")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def set_path(self, path: str) -> None:
        self._path = str(path or "")
        self.setToolTip(self._path)
        self._refit()

    def path(self) -> str:
        return self._path

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        width = max(20, self.contentsRect().width())
        super().setText(self.fontMetrics().elidedText(self._path, Qt.TextElideMode.ElideMiddle, width))


class PathRow(QFrame):
    """Folder icon, a middle-shortened path, “打开文件夹” and optionally “更改…”."""

    open_clicked = Signal()
    change_clicked = Signal()

    def __init__(self, parent=None, *, can_change: bool = True):
        super().__init__(parent)
        self.setObjectName("exportPathRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(8)
        self.icon = QLabel()
        self.icon.setPixmap(themed_icon("fa5s.folder", "secondary").pixmap(16, 16))
        row.addWidget(self.icon)
        self.path_label = ElidedPathLabel()
        row.addWidget(self.path_label, 1)
        self.change_button = QPushButton()
        bind_text(self.change_button, "更改…")
        button_role(self.change_button, "ghost", size="compact")
        self.change_button.setAutoDefault(False)
        self.change_button.clicked.connect(self.change_clicked)
        self.change_button.setVisible(can_change)
        row.addWidget(self.change_button)
        self.open_button = QPushButton()
        bind_text(self.open_button, "打开文件夹")
        button_role(self.open_button, "secondary", size="compact")
        self.open_button.setAutoDefault(False)
        self.open_button.clicked.connect(self.open_clicked)
        row.addWidget(self.open_button)

    def set_path(self, path, *, exists: bool | None = None) -> None:
        text = str(path or "")
        self.path_label.set_path(text)
        exists = bool(text) and os.path.isdir(text) if exists is None else exists
        self.open_button.setEnabled(exists)
        if exists:
            bind_text(self.open_button, "在文件管理器里打开这个文件夹", property="toolTip")
        else:
            bind_text(self.open_button, "这个文件夹会在导出时建立", property="toolTip")


class FileList(QFrame):
    """The files an export writes, existing ones marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("exportFileList")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 7, 10, 8)
        self._layout.setSpacing(2)
        self.header = QLabel()
        self.header.setObjectName("exportFileHeader")
        self._layout.addWidget(self.header)
        self.rows: list[QLabel] = []

    def set_files(self, planned, *, header: str = "") -> None:
        for label in self.rows:
            self._layout.removeWidget(label)
            label.deleteLater()
        self.rows = []
        planned = list(planned)
        if header:
            self.header.setText(header)
        elif planned:
            bind_text(self.header, "会产生 {count} 个文件：", count=len(planned))
        else:
            bind_text(self.header, "至少选一种格式")
        for item in planned[:_PREVIEW_ROWS]:
            name, status = (item.name, item.status) if hasattr(item, "status") else (str(item), "new")
            label = QLabel()
            label.setObjectName("exportFileName")
            label.setProperty("status", status)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if status == "replace":
                label.setText(tr("{name}　已存在，会替换", name=name))
            elif status == "renamed":
                label.setText(tr("{name}　同名文件已存在，另存为新编号", name=name))
            else:
                label.setText(name)
            label.setToolTip(name)
            self._layout.addWidget(label)
            self.rows.append(label)
        if len(planned) > _PREVIEW_ROWS:
            more = QLabel()
            more.setObjectName("exportFileHeader")
            bind_text(more, "…另外 {count} 个", count=len(planned) - _PREVIEW_ROWS)
            self._layout.addWidget(more)
            self.rows.append(more)

    def names(self) -> list[str]:
        return [label.toolTip() for label in self.rows if label.objectName() == "exportFileName"]


class ChipFlowLayout(QLayout):
    """Chips left to right, wrapping to a new line when the row is full."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect, apply):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.isEmpty():  # a hidden chip takes no place and no gap
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y()


def chip(text: str, *, checked: bool = False) -> QPushButton:
    button = QPushButton()
    bind_text(button, text)
    button.setObjectName("exportChip")
    button.setCheckable(True)
    button.setChecked(checked)
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def format_grid(owner_checks: dict, selected) -> QWidget:
    """Two-by-two format cards; fills ``owner_checks`` name → card."""
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(8)
    for index, (name, title, note) in enumerate(FORMAT_CARDS):
        card = FormatCard(title, note)
        card.setChecked(name in selected)
        owner_checks[name] = card
        grid.addWidget(card, index // 2, index % 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    return host


def footer_frame() -> tuple[QFrame, QHBoxLayout]:
    frame = QFrame()
    frame.setObjectName("exportDialogFooter")
    row = QHBoxLayout(frame)
    row.setContentsMargins(20, 10, 20, 12)
    row.setSpacing(8)
    return frame, row
