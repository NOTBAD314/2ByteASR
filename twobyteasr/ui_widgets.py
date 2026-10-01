"""首页/术语库共用的原子 UI 控件（UI IMPLEMENTATION 轮）。

- ThemedCheckBox：绿主题勾选（禁止 Windows 蓝色系统复选框）
- CategoryChip：内容宽度自适应分类 pill（角色 / Boss / 物品 / 方块…）
- SettingTile：首页三设置卡（AI 与密钥 / 任务选项 / 缓存与覆盖）
- StatusBadge：绿/琥珀/灰小状态标签

全部使用暖色视觉体系，不引入新的样式系统。
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from twobyteasr.ui_theme import GREEN, INK  # for defaults if needed
from twobyteasr.ui_theme import (
    AMBER,
    CORAL,
    GREEN,
    GREEN_SOFT,
    GREEN_SUBTLE,
    INK,
    MUTED,
)

from .i18n import bind_text

TRACK = "#e8e2d8"

_CATEGORY_LABELS = {
    "character": "角色",
    "skill": "技能",
    "item": "物品",
    "weapon": "武器",
    "location": "地点",
    "enemy": "Boss",
    "faction": "阵营",
    "mechanic": "机制",
    "quest": "任务",
    "common": "常用词",
    "block": "方块",
    "other": "其他",
}

_VISIBLE_CATEGORIES = {
    "角色", "Boss", "物品", "方块", "阵营", "地点",
    "模型", "人物", "事件", "其他",
}


def category_label(category: str) -> str:
    """短分类标签：Boss/物品/方块等（批准图用短词，不用长胶囊）。"""
    value = str(category or "").strip()
    if value == "其它":
        return "其他"
    if value in _VISIBLE_CATEGORIES:
        return value
    return _CATEGORY_LABELS.get(value, "其他")


class SwitchControl(QAbstractButton):
    """Accessible animated switch that keeps QAbstractButton's checked API."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(34)
        self._hovered = False
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_progress)
        self.toggled.connect(self._animate_to_state)
        self.setAccessibleName(text)

    def sizeHint(self):
        width = 62 + self.fontMetrics().horizontalAdvance(self.text())
        return QSize(max(155, width), 36)

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    def _animate_to_state(self, checked: bool):
        from .ui_motion import MOTION_FAST_MS, motion_duration
        target = 1.0 if checked else 0.0
        duration = motion_duration(MOTION_FAST_MS)
        self._animation.stop()
        if not self.isVisible() or not duration:
            self._set_progress(target)
            return
        self._animation.setDuration(duration)
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            from .theme_manager import theme_key
            from .ui_theme import theme_definition
            theme = theme_definition(theme_key())
            label_color = QColor(theme.text if self.isEnabled() else theme.disabled)
            hover_fill = QColor(theme.selected)
            off_fill = QColor(theme.input_surface)
            off_edge = QColor(theme.border_strong)
            off_thumb = QColor(theme.text_muted)
            accent = QColor(theme.accent)
        except Exception:
            theme = None
            label_color = QColor(INK if self.isEnabled() else "#99958d")
            hover_fill = QColor("#fff9ef")
            off_fill = QColor("#eee9df")
            off_edge = QColor("#aaa69d")
            off_thumb = QColor("#7f7c75")
            accent = QColor(GREEN)
        if self._hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hover_fill)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)

        track = QRectF(2, (self.height() - 24) / 2, 44, 24)
        if self.isChecked():
            fill, edge, thumb = QColor(theme.accent_soft if theme else "#dcebdc"), accent, accent
        else:
            fill, edge, thumb = off_fill, off_edge, off_thumb
        if not self.isEnabled():
            fill, edge, thumb = QColor(theme.panel), QColor(theme.border), QColor(theme.disabled)
        painter.setPen(QPen(edge, 1.4))
        painter.setBrush(fill)
        painter.drawRoundedRect(track, 12, 12)

        knob_x = 5 + self._progress * 20
        knob = QRectF(knob_x, track.y() + 3, 18, 18)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(thumb)
        painter.drawEllipse(knob)

        font = painter.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(label_color)
        painter.drawText(QRectF(58, 0, self.width() - 58, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            focus_pen = QPen(accent, 1)
            focus_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(focus_pen)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)


class ThemedCheckBox(QAbstractButton):
    """Theme-token checkbox. Fusion/native Win11 indicators are never drawn.

    禁止使用 QCheckBox 原生（Win11 蓝底白勾）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(20, 20)
        bind_text(self, '选择', property='accessibleName')

    def paintEvent(self, _event):
        from twobyteasr.theme_manager import theme_key
        from twobyteasr.ui_theme import theme_definition

        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(2.0, 2.0, 16.0, 16.0)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent))
            painter.drawRoundedRect(rect, 4.0, 4.0)
            path = QPainterPath()
            path.moveTo(5.5, 9.5)
            path.lineTo(8.5, 12.5)
            path.lineTo(14.5, 5.5)
            painter.setPen(QColor(theme.text_on_accent))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            painter.setPen(QColor(theme.border_strong if self.underMouse() else theme.border))
            painter.setBrush(QColor(theme.surface_elevated))
            painter.drawRoundedRect(rect, 4.0, 4.0)


class CategoryChip(QLabel):
    """内容宽度自适应分类 pill；短标签，不做固定长胶囊。
    Size is determined by text + stylesheet padding only.
    """

    def __init__(self, category: str, parent=None):
        super().__init__(parent)
        self.setObjectName("categoryChip")
        txt = category_label(category)
        self.setText(txt)
        self.setToolTip(txt)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def sizeHint(self):
        sh = super().sizeHint()
        try:
            from PySide6.QtCore import QSize
            return sh + QSize(6, 0)
        except Exception:
            return sh

    def minimumSizeHint(self):
        return self.sizeHint()


class PillLabel(QLabel):
    """Shared auto-sizing pill/badge.

    - Width is purely text width + padding (from QSS or style).
    - Never clips Chinese or long size strings like "安装约 4.7 GB".
    - Use setObjectName to apply different visual styles (e.g. "workshopSizeBadge", "langPill", "recTag", "workshopBadge").
    - Always Maximum size policy horizontally.
    """

    def __init__(self, text: str = "", object_name: str | None = None, parent=None):
        super().__init__(text, parent)
        if object_name:
            self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def sizeHint(self):
        # Compute width from actual text metrics + padding so long labels like
        # "安装约 4.7 GB", "★ 2ByteASR 推荐", categories, languages never clip.
        fm = self.fontMetrics()
        text = self.text() or ""
        # Account for typical QSS horizontal padding (left+right ~12-16px total + border).
        w = fm.horizontalAdvance(text) + 18
        h = max(super().sizeHint().height(), fm.height() + 8)
        from PySide6.QtCore import QSize
        return QSize(w, h)

    def minimumSizeHint(self):
        return self.sizeHint()


class StatusBadge(QLabel):
    """状态小标签：已就绪（绿）/ 需要下载（琥珀）/ 已关闭（灰）。"""

    def __init__(self, text: str = "", tone: str = "muted", parent=None):
        super().__init__(text, parent)
        self.setObjectName(f"statusBadge{tone.capitalize()}")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class SettingTile(QFrame):
    """首页三设置卡：图标 + 标题 + 一行摘要 + chevron。整卡可点展开。"""

    # QFrame 无原生 checked：setProperty + unpolish/polish 驱动 QSS
    clicked = Signal(bool)
    toggled = Signal(bool)

    def __init__(self, title: str, summary: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("settingTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(88)
        self._checked = False
        self._pressed = False
        self.setProperty("checked", False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(40, 40)
        self.icon_label.setObjectName("settingTileIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from qtawesome import icon as qta_icon

        self.icon_label.setPixmap(qta_icon(icon_name, color=GREEN).pixmap(19, 19))
        layout.addWidget(self.icon_label)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("settingTileTitle")
        text_box.addWidget(self.title_label)
        self.summary_label = QLabel(summary)
        self.summary_label.setObjectName("settingTileSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        text_box.addWidget(self.summary_label)
        layout.addLayout(text_box, 1)

        self.chevron = QLabel("›")
        self.chevron.setObjectName("settingTileChevron")
        self.chevron.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self.chevron)

        # 子控件不截获鼠标，保证整卡可点
        for child in (
            self.icon_label,
            self.title_label,
            self.summary_label,
            self.chevron,
        ):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_summary(self, text: str) -> None:
        """更新摘要文案。"""
        self.summary_label.setText(text)

    def apply_density(self, comfortable: bool) -> None:
        """Keep cards readable without forcing a scroll at 1366x768."""
        self.setMinimumHeight(104 if comfortable else 88)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.setProperty("checked", checked)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._pressed
            and self.rect().contains(event.position().toPoint())
        ):
            self.setChecked(not self._checked)
            self.clicked.emit(self._checked)
        self._pressed = False
        super().mouseReleaseEvent(event)


def make_tile_row(tiles) -> QHBoxLayout:
    """把 3 张 SettingTile 排成等宽一行。"""
    row = QHBoxLayout()
    row.setSpacing(10)
    for tile in tiles:
        row.addWidget(tile, 1)
    return row


class AnimatedButton(QPushButton):
    """Native state feedback without per-button graphics effects or shadows."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
