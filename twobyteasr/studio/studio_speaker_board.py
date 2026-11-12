"""Speaker board for the speaker manager (2026-11-12, user picked 方案 B).

Four boxes hold the speakers: 主要角色 (cards), 次要角色, 游戏声 and 已忽略
(chips). Dragging a speaker to another box changes its group or use; dropping
it on another speaker merges it there. The widgets here only present data and
forward input; ``SpeakerManagerDialog`` owns every project change.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ..design.studio_theme import _active_theme
from ..design.themed_icons import themed_icon
from ..design.ui_theme import blend_hex
from ..i18n import bind_text, tr

SPEAKER_MIME = "application/x-2byteasr-speakers"
BOX_TITLES = {"main": "主要角色", "secondary": "次要角色", "game": "游戏声", "ignore": "已忽略"}


def short_label(name: str, key: str) -> str:
    """What an avatar shows: the number of S06 / API_S07, else the first letter."""
    import re
    text = str(name or key or "?")
    match = re.fullmatch(r"(?:API_)?S(\d+)", text, re.IGNORECASE)
    return match.group(1)[-2:] if match else text[:1]


def build_speaker_board_qss(t) -> str:
    accent_tint = blend_hex(t.surface, t.accent, 0.2)
    hover = blend_hex(t.surface_elevated, t.selected, 0.55)
    info_soft = blend_hex(t.surface_elevated, t.focus, 0.16)
    return f"""
        QDialog#speakerManager {{ background: transparent; }}
        QWidget#speakerManagerRoot {{ background: {t.surface}; color: {t.text}; }}
        QFrame#speakerHeader {{ border: 0; border-top-left-radius: 26px; border-top-right-radius: 26px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {t.accent_soft}, stop:1 {t.surface}); }}
        QLabel#speakerBadge {{ background: {t.accent}; border-radius: 12px; }}
        QLabel#speakerTitle {{ color: {t.text}; font-size: 19px; font-weight: 800; }}
        QLabel#speakerMeta {{ color: {t.text_muted}; font-size: 12px; }}
        QLabel#speakerMetaWarn {{ color: {t.warning}; font-size: 12px; }}
        QPushButton#speakerWindowClose {{ background: transparent; border: 0; border-radius: 17px; color: {t.text_secondary};
            font-size: 20px; font-weight: 600; padding: 0; min-height: 0; min-width: 0; }}
        QPushButton#speakerWindowClose:hover {{ background: {t.selected}; color: {t.text}; }}
        QToolButton#speakerPillButton, QPushButton#speakerPillButton {{ background: {t.selected}; color: {t.text_secondary};
            border: 0; border-radius: 15px; padding: 5px 13px; font-size: 12px; font-weight: 600; min-height: 20px; }}
        QToolButton#speakerPillButton:hover, QPushButton#speakerPillButton:hover {{ color: {t.text};
            background: {blend_hex(t.selected, t.border_strong, 0.28)}; }}
        QToolButton#speakerPillButton:checked, QPushButton#speakerPillButton:checked {{ background: {t.accent_soft}; color: {t.accent_text}; }}
        QToolButton#speakerPillButton::menu-indicator {{ image: none; width: 0; }}
        QToolButton#speakerGhostButton, QPushButton#speakerGhostButton {{ background: transparent; color: {t.text_secondary};
            border: 0; border-radius: 14px; padding: 4px 10px; font-size: 12px; font-weight: 600; min-height: 20px; }}
        QToolButton#speakerGhostButton:hover, QPushButton#speakerGhostButton:hover {{ background: {t.selected}; color: {t.text}; }}
        QToolButton#speakerGhostButton::menu-indicator {{ image: none; width: 0; }}
        QPushButton#speakerPrimarySmall {{ background: {t.accent}; color: {t.text_on_accent}; border: 0; border-radius: 15px;
            padding: 5px 14px; font-size: 12px; font-weight: 700; min-height: 20px; }}
        QPushButton#speakerPrimarySmall:hover {{ background: {t.accent_hover}; }}
        QPushButton#speakerPrimarySmall:disabled {{ background: {t.selected}; color: {t.disabled}; }}
        QPushButton#speakerDone {{ background: {t.accent}; color: {t.text_on_accent}; border: 0; border-radius: 21px;
            min-height: 42px; padding: 0 28px; font-size: 15px; font-weight: 800; }}
        QPushButton#speakerDone:hover {{ background: {t.accent_hover}; }}
        QLineEdit#speakerSearch {{ background: {t.input_surface}; border: 1.5px solid transparent; border-radius: 17px;
            padding: 6px 12px; min-height: 20px; color: {t.text}; }}
        QLineEdit#speakerSearch:focus {{ border-color: {t.accent}; background: {t.surface_elevated}; }}
        QScrollArea#speakerBoardScroll, QWidget#speakerBoardHost {{ background: {t.surface}; border: 0; }}
        QFrame#speakerBox {{ background: {t.panel}; border: 0; border-radius: 20px; }}
        QFrame#speakerBox[dropTarget="true"] {{ background: {blend_hex(t.panel, t.accent, 0.09)}; border: 2px solid {t.accent}; }}
        QLabel#speakerBoxTitle {{ color: {t.text}; font-size: 15px; font-weight: 700; }}
        QLabel#speakerBoxCount {{ background: {t.selected}; color: {t.text_muted}; border-radius: 9px; padding: 1px 7px;
            font-size: 11px; font-weight: 700; }}
        QLabel#speakerBoxDesc {{ color: {t.text_muted}; font-size: 12px; }}
        QLabel#speakerBoxIcon {{ background: {t.surface_elevated}; border-radius: 10px; }}
        QLabel#speakerBoxIcon[game="true"] {{ background: {info_soft}; }}
        QLabel#speakerDropHint {{ color: {t.text_muted}; font-size: 12px; border: 2px dashed {blend_hex(t.panel, t.border_strong, 0.65)};
            border-radius: 14px; padding: 8px 12px; }}
        QFrame#speakerTile {{ background: {t.surface_elevated}; border: 0; border-radius: 19px; }}
        QFrame#speakerTile[main="true"] {{ border-radius: 18px; }}
        QFrame#speakerTile:hover {{ background: {hover}; }}
        QFrame#speakerTile[selected="true"] {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
        QFrame#speakerTile[dropTarget="true"] {{ border: 3px solid {t.accent}; }}
        QFrame#speakerTile[dragging="true"] {{ background: {t.panel}; border: 1px dashed {t.border_strong}; }}
        QFrame#speakerTile[folded="true"] {{ background: {t.panel}; border: 1px dashed {t.border_strong}; }}
        QFrame#speakerTile[folded="true"][selected="true"] {{ background: {t.accent_soft}; border: 2px solid {t.accent}; }}
        QFrame#speakerTile QLabel {{ background: transparent; }}
        QLabel#speakerTileName {{ color: {t.text}; font-size: 13px; font-weight: 700; }}
        QLabel#speakerTileName[dim="true"] {{ color: {t.text_muted}; }}
        QLabel#speakerTileCount {{ color: {t.text_muted}; font-size: 11px; }}
        QLabel#speakerTileMeta {{ color: {t.text_muted}; font-size: 12px; }}
        QLabel#speakerTileExcerpt {{ color: {t.text_secondary}; }}
        QToolButton#speakerTilePlay {{ background: {accent_tint}; border: 0; border-radius: 11px; }}
        QToolButton#speakerTilePlay:hover, QToolButton#speakerTilePlay[playing="true"] {{ background: {t.accent}; }}
        QFrame#speakerInspector {{ background: {t.surface}; border: 0; border-left: 1px solid {blend_hex(t.surface, t.border, 0.7)}; }}
        QLabel#speakerEmptyTitle {{ color: {t.text_secondary}; font-size: 18px; font-weight: 700; }}
        QLabel#speakerEmptyText {{ color: {t.text_muted}; font-size: 12px; }}
        QLabel#speakerSection {{ color: {t.text_muted}; font-size: 12px; font-weight: 700; }}
        QLabel#mergeTitle {{ color: {t.text}; font-size: 15px; font-weight: 700; }}
        QPushButton#mergeOption {{ background: transparent; border: 0; border-radius: 12px; text-align: left;
            padding: 7px 10px; color: {t.text}; font-weight: 700; min-height: 22px; }}
        QPushButton#mergeOption:hover {{ background: {t.selected}; }}
        QPushButton#mergeOption:checked {{ background: {t.accent_soft}; color: {t.accent_text}; }}
        QPushButton#mergeNamePill {{ background: {t.selected}; color: {t.text_secondary}; border: 0; border-radius: 12px;
            padding: 3px 11px; font-size: 12px; font-weight: 600; min-height: 18px; }}
        QPushButton#mergeNamePill:checked {{ background: {t.accent}; color: {t.text_on_accent}; }}
        QLineEdit#mergeName {{ background: {t.input_surface}; border: 1.5px solid transparent; border-radius: 12px;
            padding: 6px 10px; color: {t.text}; }}
        QLineEdit#mergeName:focus {{ border-color: {t.accent}; background: {t.surface_elevated}; }}
        QFrame#speakerFooter {{ border: 0; border-top: 1px solid {blend_hex(t.surface, t.border, 0.7)};
            border-bottom-left-radius: 26px; border-bottom-right-radius: 26px; }}
        QLabel#speakerNamePreview {{ background: {t.media}; color: #ffffff; border-radius: 14px; padding: 4px 13px;
            font-size: 12px; font-weight: 600; }}
        QCheckBox#speakerNameVisibility {{ color: {t.text_secondary}; font-weight: 600; spacing: 9px; }}
        QCheckBox#speakerNameVisibility::indicator {{ width: 34px; height: 20px; border-radius: 10px;
            background: {blend_hex(t.surface, t.border_strong, 0.7)}; image: none; border: 0; }}
        QCheckBox#speakerNameVisibility::indicator:checked {{ background: {t.accent}; }}
        QFrame#speakerBanner {{ background: {t.warning_soft}; border: 0; border-radius: 14px; }}
        QFrame#speakerMoreTools {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 16px; }}
        QFrame#speakerMoreTools QLabel {{ background: transparent; }}
    """


# --------------------------------------------------------------------- avatar
class SpeakerAvatar(QWidget):
    """A round, tinted speaker badge with a number or initial (and state dots)."""

    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self._size = size
        self._color = "#888888"
        self._text = ""
        self._pending = False
        self._host = False
        self.setFixedSize(size + 4, size + 4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_speaker(self, color: str, text: str, *, pending: bool = False, host: bool = False) -> None:
        state = (color, text, pending, host)
        if state != (self._color, self._text, self._pending, self._host):
            self._color, self._text, self._pending, self._host = state
            self.update()

    def paintEvent(self, _event):
        theme = _active_theme(None)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self._size
        rect = QRectF(2, 2, size, size)
        color = QColor(self._color)
        painter.setPen(QPen(QColor(blend_hex(theme.surface_elevated, color.name(), 0.72)), max(1.5, size / 18)))
        painter.setBrush(QColor(blend_hex(theme.surface_elevated, color.name(), 0.3)))
        painter.drawEllipse(rect.adjusted(0.75, 0.75, -0.75, -0.75))
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(9, int(size * (0.4 if len(self._text) < 2 else 0.36))))
        painter.setFont(font)
        painter.setPen(QColor(blend_hex(theme.text, color.name(), 0.62)))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
        ring = QColor(theme.surface_elevated)
        if self._pending:
            dot = max(7.0, size / 3.4)
            painter.setPen(QPen(ring, 2))
            painter.setBrush(QColor(theme.warning))
            painter.drawEllipse(QRectF(2 + size - dot + 1, 2 + size - dot + 1, dot, dot))
        if self._host:
            dot = max(10.0, size / 2.4)
            painter.setPen(QPen(ring, 2))
            painter.setBrush(QColor(theme.warning))
            box = QRectF(2 + size - dot + 2, 0, dot, dot)
            painter.drawEllipse(box)
            painter.setPen(QColor("#ffffff"))
            star = QFont(font)
            star.setPixelSize(int(dot * 0.7))
            painter.setFont(star)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "★")
        painter.end()


class ColorStack(QWidget):
    """Up to three overlapping colour dots and "+N" (like the timeline group)."""

    def __init__(self, dot: int = 18, parent=None):
        super().__init__(parent)
        self._dot = dot
        self._colors: list[str] = []
        self._more = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(dot + 4)

    def set_colors(self, colors, limit: int = 3) -> None:
        colors = list(colors)
        self._colors, self._more = colors[:limit], max(0, len(colors) - limit)
        step = self._dot - 7
        width = (self._dot + step * max(0, len(self._colors) - 1) + 4) if self._colors else 0
        if self._more:
            width += self.fontMetrics().horizontalAdvance(f"+{self._more}") + 6
        self.setFixedWidth(max(1, width))
        self.setVisible(bool(self._colors))
        self.update()

    def paintEvent(self, _event):
        theme = _active_theme(None)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = self._dot - 7
        for index, color in enumerate(self._colors):
            painter.setPen(QPen(QColor(theme.panel), 2))
            painter.setBrush(QColor(blend_hex(theme.surface_elevated, QColor(color).name(), 0.78)))
            painter.drawEllipse(QRectF(2 + index * step, 2, self._dot, self._dot))
        if self._more:
            painter.setPen(QColor(theme.text_muted))
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(11)
            painter.setFont(font)
            left = 2 + step * (len(self._colors) - 1) + self._dot + 4
            painter.drawText(QRectF(left, 0, self.width() - left, self.height()),
                             Qt.AlignmentFlag.AlignVCenter, f"+{self._more}")
        painter.end()


# --------------------------------------------------------------------- layout
class FlowLayout(QLayout):
    """Wrapping rows. ``column_min`` > 0: equal columns at least that wide
    (the main cards). ``uniform`` sizes chip columns from the widest chip;
    otherwise every item keeps its own width."""

    def __init__(self, parent=None, spacing: int = 8, column_min: int = 0, *, uniform: bool = False):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._column_min = column_min
        self._uniform = uniform
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width):  # noqa: N802 - Qt override
        return self._place(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self):  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802 - Qt override
        size = QSize(0, 0)
        for item in self._visible():
            hint = item.minimumSize()
            size = size.expandedTo(QSize(min(hint.width(), self._column_min or hint.width()), hint.height()))
        return size

    def setGeometry(self, rect):  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def _visible(self):
        return [item for item in self._items if item.widget() is None or not item.widget().isHidden()]

    def _place(self, rect: QRect, *, apply: bool) -> int:
        items = self._visible()
        if not items:
            return 0
        gap = self._spacing
        if self._column_min or self._uniform:
            column_min = self._column_min or max(item.sizeHint().width() for item in items)
            columns = max(1, (rect.width() + gap) // (column_min + gap))
            width = max(1, (rect.width() - gap * (columns - 1)) // columns)
            y = rect.y()
            for start in range(0, len(items), columns):
                row = items[start:start + columns]
                height = max(item.widget().heightForWidth(width) if item.widget() is not None and
                             item.widget().hasHeightForWidth() else item.sizeHint().height() for item in row)
                if apply:
                    for column, item in enumerate(row):
                        item.setGeometry(QRect(rect.x() + column * (width + gap), y, width, height))
                y += height + gap
            return y - gap - rect.y()
        x, y, line = rect.x(), rect.y(), 0
        for item in items:
            hint = item.sizeHint()
            width = min(hint.width(), rect.width())
            if x > rect.x() and x + width > rect.right() + 1:
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, hint.height())))
            x += width + gap
            line = max(line, hint.height())
        return y + line - rect.y()


class FlowHost(QWidget):
    """Holds a FlowLayout and keeps its own height equal to the wrapped rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def fit(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        height = max(1, layout.heightForWidth(max(1, self.width())))
        if self.height() != height or self.minimumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.fit()


def _polish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _set_flag(widget, name: str, value: bool) -> None:
    if bool(widget.property(name)) != bool(value):
        widget.setProperty(name, bool(value))
        _polish(widget)


# ----------------------------------------------------------------------- tile
class SpeakerTile(QFrame):
    """One speaker in a box: a card in 主要角色, a chip elsewhere."""

    def __init__(self, key: str, owner, *, main: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self.owner = owner
        self.main = main
        self.data: dict = {}
        self._press: QPoint | None = None
        self.setObjectName("speakerTile")
        self.setProperty("main", main)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.avatar = SpeakerAvatar(36 if main else 28, self)
        self.name_label = QLabel(self)
        self.name_label.setObjectName("speakerTileName")
        self.play_button = QToolButton(self)
        self.play_button.setObjectName("speakerTilePlay")
        self.play_button.setFixedSize(26 if main else 22, 26 if main else 22)
        self.play_button.setIconSize(QSize(10 if main else 9, 10 if main else 9))
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(lambda: owner._card_preview(self))
        if main:
            self._build_main()
        else:
            self._build_chip()
        self.set_playing(False)

    def _build_chip(self) -> None:
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 0, 7, 0)
        row.setSpacing(6)
        row.addWidget(self.avatar)
        row.addWidget(self.name_label)
        self.count_label = QLabel(self)
        self.count_label.setObjectName("speakerTileCount")
        row.addWidget(self.count_label)
        row.addWidget(self.play_button)
        self.name_label.setMaximumWidth(120)

    def _build_main(self) -> None:
        from .studio_speaker_cards import ElidedLabel, RoleSegment, TimeStrip
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        column = QVBoxLayout(self)
        column.setContentsMargins(12, 10, 12, 12)
        column.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.avatar)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.name_label)
        self.meta_label = QLabel(self)
        self.meta_label.setObjectName("speakerTileMeta")
        names.addWidget(self.meta_label)
        top.addLayout(names)
        self.pill = QLabel(self)
        self.pill.setObjectName("speakerPill")
        self.pill.setProperty("tone", "warn")
        top.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        top.addStretch(1)
        from .studio_speaker_cards import SpeakerCard
        self.host_button = SpeakerCard._icon_button(self, checkable=True)
        self.host_button.clicked.connect(lambda checked: self.owner._card_set_host(self, checked))
        self.visible_button = SpeakerCard._icon_button(self, checkable=True)
        self.visible_button.clicked.connect(lambda checked: self.owner._card_set_visible(self, checked))
        top.addWidget(self.host_button, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.visible_button, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(top)
        self.strip = TimeStrip(self)
        self.strip.seek_requested.connect(lambda ms: self.owner._card_preview_at(self, ms))
        column.addWidget(self.strip)
        excerpt = QHBoxLayout()
        excerpt.setSpacing(8)
        excerpt.addWidget(self.play_button)
        self.time_label = QLabel(self)
        self.time_label.setObjectName("speakerTime")
        excerpt.addWidget(self.time_label)
        self.excerpt_label = ElidedLabel(parent=self)
        self.excerpt_label.setObjectName("speakerTileExcerpt")
        excerpt.addWidget(self.excerpt_label, 1)
        self.roles = RoleSegment(self)
        self.roles.role_clicked.connect(lambda role: self.owner._card_role_clicked(self, role))
        excerpt.addWidget(self.roles)
        column.addLayout(excerpt)

    # ---------------------------------------------------------------- data
    def update_data(self, data: dict) -> None:
        self.data = data
        theme = _active_theme(None)
        present = bool(data.get("present"))
        name = str(data.get("name") or self.key)
        self.avatar.set_speaker(data.get("color") or "#888888", short_label(name, self.key),
                                pending=bool(data.get("pending")), host=bool(data.get("host")))
        self.name_label.setText(name)
        _set_flag(self.name_label, "dim", bool(data.get("hidden")) or not present)
        _set_flag(self, "folded", not present)
        count = int(data.get("count") or 0)
        tip = [f"{name}（{self.key}）" if name != self.key else name, str(data.get("meta") or "")]
        if data.get("status"):
            tip.append(str(data["status"]))
        self.setToolTip("\n".join(part for part in tip if part))
        self.play_button.setEnabled(bool(data.get("excerpt_range")))
        if not self.main:
            self.count_label.setText(str(count))
            self.adjustSize()
            return
        self.meta_label.setText(str(data.get("meta") or ""))
        pill = str(data.get("pill") or "")
        self.pill.setText(pill)
        self.pill.setProperty("tone", data.get("pill_tone") or "warn")
        self.pill.setVisible(bool(pill))
        _polish(self.pill)
        from PySide6.QtGui import QColor as _QColor
        self.strip.set_data(data.get("intervals") or (), int(data.get("duration_ms") or 1), _QColor(data.get("color") or "#888888"))
        self.strip.setToolTip(str(data.get("strip_tip") or ""))
        self.time_label.setText(str(data.get("excerpt_time") or ""))
        self.excerpt_label.set_full_text(str(data.get("excerpt") or tr("还没有字幕")))
        host = bool(data.get("host"))
        self.host_button.setChecked(host)
        self.host_button.setIcon(themed_icon("fa5s.star", "warning" if host else "muted", theme))
        bind_text(self.host_button, "主播（再点一下取消）" if host else "设为主播", property="toolTip")
        self.host_button.setVisible(present and not data.get("group"))
        visible = not data.get("hidden")
        self.visible_button.setChecked(visible)
        self.visible_button.setIcon(themed_icon("fa5s.eye" if visible else "fa5s.eye-slash",
                                                "secondary" if visible else "warning", theme))
        bind_text(self.visible_button, "在成片和导出里显示（点一下隐藏）" if visible else "已隐藏：成片和导出不含这位（点一下显示）",
                  property="toolTip")
        self.visible_button.setVisible(present)
        role = data.get("role")
        self.roles.setVisible(role is not None)
        self.roles.set_role(str(role or ""))
        self.updateGeometry()

    def set_playing(self, playing: bool) -> None:
        self.play_button.setProperty("playing", playing)
        self.play_button.setIcon(themed_icon("fa5s.stop" if playing else "fa5s.play", "on_accent" if playing else "accent"))
        bind_text(self.play_button, "停止试听" if playing else "试听这一句（约 3 秒）", property="toolTip")
        _polish(self.play_button)

    def set_selected(self, selected: bool) -> None:
        _set_flag(self, "selected", selected)

    def set_drop_target(self, value: bool) -> None:
        _set_flag(self, "dropTarget", value)

    def set_dragging(self, value: bool) -> None:
        _set_flag(self, "dragging", value)

    # --------------------------------------------------------------- input
    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt override
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.owner._start_drag(self)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            self.owner._tile_clicked(self.key, event.modifiers())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt override
        self.owner._tile_rename(self.key)

    def contextMenuEvent(self, event):  # noqa: N802 - Qt override
        self.owner._tile_menu(self, event.globalPos())


def drag_pixmap(text: str) -> QPixmap:
    theme = _active_theme(None)
    font = QFont(QApplication.font())
    font.setBold(True)
    font.setPixelSize(13)
    from PySide6.QtGui import QFontMetrics
    width = QFontMetrics(font).horizontalAdvance(text) + 30
    ratio = 2
    pixmap = QPixmap(width * ratio, 34 * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, 34), 17, 17)
    painter.fillPath(path, QColor(theme.accent))
    painter.setPen(QColor(theme.text_on_accent))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, width, 34), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def speaker_drag(source: QWidget, keys: list[str], label: str) -> QDrag:
    drag = QDrag(source)
    mime = QMimeData()
    mime.setData(SPEAKER_MIME, "\n".join(keys).encode("utf-8"))
    drag.setMimeData(mime)
    pixmap = drag_pixmap(label)
    drag.setPixmap(pixmap)
    drag.setHotSpot(QPoint(22, 17))
    return drag


def dragged_keys(event) -> list[str]:
    mime = event.mimeData()
    if not mime.hasFormat(SPEAKER_MIME):
        return []
    return [key for key in bytes(mime.data(SPEAKER_MIME)).decode("utf-8").split("\n") if key]


# ------------------------------------------------------------------------ box
class SpeakerBox(QFrame):
    """One of the four boxes; it also receives every drop inside it."""

    def __init__(self, kind: str, owner, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.owner = owner
        self.tiles: list[SpeakerTile] = []
        self._hover_tile: SpeakerTile | None = None
        self.setObjectName("speakerBox")
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        compact = kind in {"game", "ignore"}
        outer = QHBoxLayout(self) if compact else QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12) if not compact else outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.stack = ColorStack(18, self)
        head.addWidget(self.stack)
        self.icon = QLabel(self)
        self.icon.setObjectName("speakerBoxIcon")
        self.icon.setFixedSize(30, 30)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setProperty("game", kind == "game")
        icon_name = {"main": "fa5s.user", "secondary": "fa5s.users", "game": "fa5s.gamepad", "ignore": "fa5s.ban"}[kind]
        self.icon.setPixmap(themed_icon(icon_name, "accent" if kind == "game" else "muted").pixmap(15, 15))
        head.addWidget(self.icon)
        self.title = QLabel(self)
        self.title.setObjectName("speakerBoxTitle")
        bind_text(self.title, BOX_TITLES[kind])
        head.addWidget(self.title)
        self.count = QLabel(self)
        self.count.setObjectName("speakerBoxCount")
        head.addWidget(self.count)
        self.desc = QLabel(self)
        self.desc.setObjectName("speakerBoxDesc")
        self.desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        head.addWidget(self.desc, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        head.addLayout(self.actions)
        outer.addLayout(head) if not compact else outer.addLayout(head, 0)
        self.body = FlowHost(self)
        self.flow = FlowLayout(self.body, spacing=8 if kind != "main" else 10,
                               column_min=300 if kind == "main" else 0, uniform=kind == "secondary")
        self.hint = QLabel(self.body)
        self.hint.setObjectName("speakerDropHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(False)
        outer.addWidget(self.body, 1 if compact else 0)
        if compact:
            self.desc.hide()

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget

    def set_tiles(self, tiles: list[SpeakerTile], hint: str) -> None:
        if tiles != self.tiles:
            while self.flow.count():
                self.flow.takeAt(0)
            for tile in tiles:
                tile.setParent(self.body)
                self.flow.addWidget(tile)
                tile.show()
            self.tiles = list(tiles)
        if hint:
            bind_text(self.hint, hint)
        if self.hint not in [self.flow.itemAt(i).widget() for i in range(self.flow.count())]:
            self.flow.addWidget(self.hint)
        self.refresh_hint()

    def refresh_hint(self) -> None:
        empty = not any(not tile.isHidden() for tile in self.tiles)
        self.hint.setVisible(empty)
        if empty:
            self.hint.setMinimumWidth(max(120, self.body.width() - 2))
        self.flow.invalidate()
        self.body.fit()

    def set_summary(self, count: int, desc: str, colors=()) -> None:
        self.count.setText(str(count))
        self.desc.setText(desc)
        self.desc.setToolTip(desc)
        if self.kind == "secondary":
            self.stack.set_colors(colors)
            self.icon.setVisible(not colors)
        else:
            self.stack.set_colors(())

    # ---------------------------------------------------------------- drops
    def _tile_at(self, pos) -> SpeakerTile | None:
        widget = self.childAt(pos)
        while widget is not None and widget is not self:
            if isinstance(widget, SpeakerTile):
                return widget
            widget = widget.parentWidget()
        return None

    def _clear_hover(self) -> None:
        if self._hover_tile is not None:
            try:
                self._hover_tile.set_drop_target(False)
            except RuntimeError:
                pass
            self._hover_tile = None
        _set_flag(self, "dropTarget", False)

    def dragEnterEvent(self, event):  # noqa: N802 - Qt override
        if dragged_keys(event):
            event.acceptProposedAction()
            self.dragMoveEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802 - Qt override
        keys = dragged_keys(event)
        if not keys:
            event.ignore()
            return
        pos = event.position().toPoint()
        self.owner._autoscroll(self.mapToGlobal(pos))
        tile = self._tile_at(pos)
        self._clear_hover()
        if tile is not None and tile.key not in keys and self.owner._can_merge(keys, tile.key):
            self._hover_tile = tile
            tile.set_drop_target(True)
            event.acceptProposedAction()
            return
        if self.owner._can_move(keys, self.kind):
            _set_flag(self, "dropTarget", True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802 - Qt override
        self._clear_hover()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802 - Qt override
        keys = dragged_keys(event)
        target = self._hover_tile.key if self._hover_tile is not None else ""
        self._clear_hover()
        if not keys:
            event.ignore()
            return
        event.acceptProposedAction()
        self.owner._drop(keys, self.kind, target)


# ---------------------------------------------------------------- merge panel
class MergePanel(QWidget):
    """Right column when several speakers are selected: merge them or treat them together."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self._keys: list[str] = []
        self._shown = 6
        self._name_touched = False
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 4, 0, 4)
        column.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.stack = ColorStack(20, self)
        head.addWidget(self.stack)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel(self)
        self.title.setObjectName("mergeTitle")
        titles.addWidget(self.title)
        self.summary = QLabel(self)
        self.summary.setObjectName("speakerMeta")
        titles.addWidget(self.summary)
        head.addLayout(titles, 1)
        column.addLayout(head)
        self.target_label = self._section("沿用谁的颜色和样式")
        column.addWidget(self.target_label)
        self.options_host = QWidget(self)
        self.options = QVBoxLayout(self.options_host)
        self.options.setContentsMargins(0, 0, 0, 0)
        self.options.setSpacing(2)
        column.addWidget(self.options_host)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.buttonClicked.connect(self._target_changed)
        self.more_button = QPushButton(self)
        self.more_button.setObjectName("speakerGhostButton")
        self.more_button.clicked.connect(self._show_all)
        column.addWidget(self.more_button)
        self.name_section = self._section("合并后叫")
        column.addWidget(self.name_section)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("mergeName")
        self.name_edit.textEdited.connect(self._name_edited)
        column.addWidget(self.name_edit)
        self.pills_host = QWidget(self)
        self.pills = FlowLayout(self.pills_host, spacing=6)
        column.addWidget(self.pills_host)
        self.note = QLabel(self)
        self.note.setObjectName("speakerMeta")
        self.note.setWordWrap(True)
        column.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.cancel_button = QPushButton(self)
        self.cancel_button.setObjectName("speakerGhostButton")
        bind_text(self.cancel_button, "取消选择")
        self.cancel_button.clicked.connect(owner._clear_selection)
        buttons.addWidget(self.cancel_button)
        self.confirm_button = QPushButton(self)
        self.confirm_button.setObjectName("speakerPrimarySmall")
        self.confirm_button.setIcon(themed_icon("fa5s.compress-arrows-alt", "on_accent"))
        self.confirm_button.clicked.connect(self._confirm)
        buttons.addWidget(self.confirm_button, 1)
        column.addLayout(buttons)
        self.batch_label = self._section("也可以一起")
        column.addWidget(self.batch_label)
        self.batch_host = QWidget(self)
        self.batch_flow = FlowLayout(self.batch_host, spacing=6)
        column.addWidget(self.batch_host)
        column.addStretch(1)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def _section(self, text: str) -> QLabel:
        label = QLabel(self)
        label.setObjectName("speakerSection")
        bind_text(label, text)
        return label

    def add_batch_button(self, button: QWidget) -> None:
        button.setParent(self.batch_host)
        self.batch_flow.addWidget(button)

    def keys(self) -> list[str]:
        return list(self._keys)

    def target(self) -> str:
        button = self.group.checkedButton()
        return str(button.property("key")) if button is not None else ""

    def name(self) -> str:
        return self.name_edit.text().strip()

    def populate(self, keys: list[str], *, data: dict, targets: list[str], cues: int, seconds_text: str,
                 mergeable: list[str]) -> None:
        """``keys``: the selection; ``mergeable``: those that can be merged; ``targets``:
        speakers every other mergeable one can merge into (largest first)."""
        same = keys == self._keys
        self._keys = list(keys)
        if not same:
            self._shown = 6
            self._name_touched = False
        current = self.target()
        self.stack.set_colors([data[key].get("color") or "#888" for key in keys], limit=4)
        bind_text(self.title, "把 {count} 位合成一位", count=len(mergeable)) if len(mergeable) >= 2 \
            else bind_text(self.title, "已选 {count} 位", count=len(keys))
        bind_text(self.summary, "{cues} 条字幕，共 {duration}", cues=cues, duration=seconds_text)
        for button in list(self.group.buttons()):
            self.group.removeButton(button)
            button.deleteLater()
        from .studio_speaker_cards import color_dot_icon
        if current not in targets:
            current = targets[0] if targets else ""
        for index, key in enumerate(targets):
            item = data[key]
            button = QPushButton(self.options_host)
            button.setObjectName("mergeOption")
            button.setCheckable(True)
            button.setProperty("key", key)
            button.setIcon(color_dot_icon(item.get("color") or "#888", 16))
            button.setText(f"{item.get('name') or key}    {tr('{count} 条', count=item.get('count') or 0)}")
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setVisible(index < self._shown or key == current)
            self.group.addButton(button)
            self.options.addWidget(button)
            button.setChecked(key == current)
        hidden = sum(not button.isVisibleTo(self) for button in self.group.buttons())
        self.more_button.setVisible(hidden > 0)
        bind_text(self.more_button, "还有 {count} 位", count=hidden)
        can_merge = len(mergeable) >= 2 and bool(targets)
        for widget in (self.target_label, self.options_host, self.name_section, self.name_edit, self.pills_host,
                       self.confirm_button):
            widget.setVisible(can_merge)
        if can_merge and not self._name_touched:
            self.name_edit.setText(tr("次要角色") if len(mergeable) > 3 else str(data[current].get("name") or current))
        self._fill_pills(data.get(current, {}).get("name") or current)
        bind_text(self.confirm_button, "合并 {count} 位", count=len(mergeable))
        if can_merge:
            skipped = len(keys) - len(mergeable)
            bind_text(self.note, "原文和时间都保留，可 Ctrl+Z 一次撤销。" if not skipped else
                      "原文和时间都保留，可 Ctrl+Z 一次撤销。另有 {count} 位不能合并，会保持原样。", count=skipped)
        else:
            bind_text(self.note, "选中的人里能合并的不到两位（已忽略或已并入别人的不能直接合并）。")

    def _fill_pills(self, target_name: str) -> None:
        while self.pills.count():
            item = self.pills.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for text in dict.fromkeys([tr("次要角色"), tr("路人"), "NPC", str(target_name)]):
            pill = QPushButton(text, self.pills_host)
            pill.setObjectName("mergeNamePill")
            pill.setCheckable(True)
            pill.setChecked(text == self.name_edit.text())
            pill.setAutoDefault(False)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(lambda _=False, value=text: self._pick_name(value))
            self.pills.addWidget(pill)
        self.pills_host.setMinimumHeight(self.pills.heightForWidth(max(200, self.width())))

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        for host, flow in ((self.pills_host, self.pills), (self.batch_host, self.batch_flow)):
            host.setMinimumHeight(flow.heightForWidth(max(1, self.width())))

    def _pick_name(self, value: str) -> None:
        self.name_edit.setText(value)
        self._name_touched = True
        for index in range(self.pills.count()):
            widget = self.pills.itemAt(index).widget()
            if widget is not None:
                widget.setChecked(widget.text() == value)

    def _name_edited(self, _text: str) -> None:
        self._name_touched = True
        for index in range(self.pills.count()):
            widget = self.pills.itemAt(index).widget()
            if widget is not None:
                widget.setChecked(widget.text() == self.name_edit.text())

    def _target_changed(self, button) -> None:
        if not self._name_touched and len(self._keys) <= 3:
            name = button.text().split("    ")[0]
            self.name_edit.setText(name)
        self._fill_pills(button.text().split("    ")[0])

    def _show_all(self) -> None:
        self._shown = 10_000
        for button in self.group.buttons():
            button.show()
        self.more_button.hide()

    def _confirm(self) -> None:
        self.owner._merge_selection(self.target(), self.name())
