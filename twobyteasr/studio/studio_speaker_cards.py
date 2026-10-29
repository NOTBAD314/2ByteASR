"""Speaker cards for the speaker manager (2026-10-18 redesign).

One card per speaker: name, colour, host and visibility on the card, a
one-click preview of a representative line, a strip that shows where the
speaker talks, and the three common roles. The cards only present data and
forward clicks; the dialog owns every project change.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from ..design.studio_theme import _active_theme, create_studio_menu
from ..design.themed_icons import themed_icon
from ..i18n import bind_text, tr

ROLE_BUTTONS = (("main", "主要"), ("game", "游戏声"), ("ignore", "忽略"))


def build_speaker_manager_qss(theme) -> str:
    """Card, banner and segment rules; appended to the dialog's own sheet."""
    return f"""
        QWidget#speakerManagerBody, QScrollArea#speakerCardScroll, QWidget#speakerCardHost {{
            background: {theme.surface}; border: 0; }}
        QFrame#speakerCard {{ background: {theme.surface_elevated}; border: 1px solid {theme.border};
            border-radius: 10px; }}
        QFrame#speakerCard[pending="true"] {{ border-color: {theme.warning}; }}
        QFrame#speakerCard[folded="true"] {{ background: {theme.panel}; border-style: dashed; }}
        QFrame#speakerCard[group="true"] {{ background: {theme.panel}; }}
        QFrame#speakerCard QLabel {{ background: transparent; }}
        QLineEdit#speakerName {{ font-size: 15px; font-weight: 700; color: {theme.text};
            background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 2px 6px; }}
        QLineEdit#speakerName:hover {{ border-color: {theme.border}; }}
        QLineEdit#speakerName:focus {{ border-color: {theme.accent}; background: {theme.input_surface}; }}
        QLineEdit#speakerName:disabled {{ color: {theme.text_secondary}; border-color: transparent; }}
        QLabel#speakerId {{ color: {theme.text_muted}; font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; }}
        QLabel#speakerMeta, QLabel#speakerTime {{ color: {theme.text_muted}; font-size: 12px; }}
        QLabel#speakerExcerpt {{ color: {theme.text_secondary}; }}
        QLabel#speakerStatus {{ color: {theme.text_secondary}; font-size: 12px; }}
        QLabel#speakerPill {{ border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 700; }}
        QLabel#speakerPill[tone="warn"] {{ background: {theme.warning_soft}; color: {theme.warning}; }}
        QLabel#speakerPill[tone="quiet"] {{ background: {theme.selected}; color: {theme.text_muted}; }}
        QToolButton#speakerIcon, QToolButton#speakerSwatch {{ background: transparent; border: 1px solid transparent;
            border-radius: 7px; padding: 3px; }}
        QToolButton#speakerIcon:hover, QToolButton#speakerSwatch:hover {{ background: {theme.selected}; }}
        QToolButton#speakerIcon::menu-indicator, QToolButton#speakerSwatch::menu-indicator {{ image: none; width: 0; }}
        QToolButton#speakerPlay {{ background: {theme.accent_tint}; border: 0; border-radius: 13px; }}
        QToolButton#speakerPlay:hover {{ background: {theme.accent}; }}
        QToolButton#speakerPlay[playing="true"] {{ background: {theme.accent}; }}
        QPushButton#roleSegment {{ background: {theme.input_surface}; color: {theme.text_secondary};
            border: 1px solid {theme.border_strong}; border-radius: 0; padding: 3px 12px; min-height: 22px; font-size: 12px; }}
        QPushButton#roleSegment[segment="first"] {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
        QPushButton#roleSegment[segment="last"] {{ border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
        QPushButton#roleSegment[segment="middle"], QPushButton#roleSegment[segment="last"] {{ border-left: 0; }}
        QPushButton#roleSegment:hover {{ color: {theme.text}; background: {theme.selected}; }}
        QPushButton#roleSegment:checked {{ background: {theme.accent}; color: {theme.text_on_accent};
            border-color: {theme.accent}; font-weight: 700; }}
        QPushButton#roleSegment:disabled {{ color: {theme.disabled}; }}
        QToolButton#speakerMerge {{ background: {theme.input_surface}; color: {theme.text_secondary};
            border: 1px solid {theme.border_strong}; border-radius: 7px; padding: 3px 10px; min-height: 22px; font-size: 12px; }}
        QToolButton#speakerMerge:hover {{ color: {theme.text}; border-color: {theme.accent}; }}
        QToolButton#speakerMerge::menu-indicator {{ image: none; width: 0; }}
        QFrame#speakerBanner {{ background: {theme.warning_soft}; border: 1px solid {theme.warning}; border-radius: 8px; }}
        QFrame#speakerBanner QLabel {{ background: transparent; color: {theme.text}; }}
        QFrame#speakerBatchBar {{ background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 8px; }}
        QFrame#speakerBatchBar QLabel {{ background: transparent; }}
        QToolButton#speakerMoreToggle {{ background: transparent; border: 0; color: {theme.text_secondary};
            padding: 4px 2px; font-size: 13px; }}
        QToolButton#speakerMoreToggle:hover {{ color: {theme.text}; }}
        QFrame#speakerMoreTools {{ background: transparent; border-top: 1px dashed {theme.border}; }}
        QFrame#speakerMoreTools QLabel {{ background: transparent; }}
        QLabel#speakerFooterStatus {{ color: {theme.text_muted}; }}
        QWidget#speakerSwatchGrid {{ background: transparent; }}
        QToolButton#speakerSwatchChoice {{ border: 2px solid transparent; border-radius: 12px; }}
        QToolButton#speakerSwatchChoice:hover {{ border-color: {theme.text}; }}
        QToolButton#speakerSwatchChoice[current="true"] {{ border-color: {theme.text}; }}
    """


def color_dot_icon(color: str, size: int = 16, *, ring: str = ""):
    from PySide6.QtGui import QIcon, QPixmap
    scale = 3
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    pen = QPen(QColor(ring) if ring else QColor(0, 0, 0, 0), 1.5 * scale)
    painter.setPen(pen)
    inset = 1.5 * scale
    painter.drawEllipse(QRectF(inset, inset, size * scale - 2 * inset, size * scale - 2 * inset))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


class ElidedLabel(QLabel):
    """One line that ends in “…” when narrow; the full text is the tooltip."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = str(text or "")
        self.setToolTip(self._full)
        self._refit()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        width = max(10, self.contentsRect().width())
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width))


class TimeStrip(QWidget):
    """Where a speaker talks across the recording; a click previews there."""

    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._intervals: list[tuple[int, int]] = []
        self._duration = 1
        self._color = QColor("#888888")
        self.setMinimumHeight(16)
        self.setMaximumHeight(16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, intervals, duration_ms: int, color: QColor) -> None:
        self._intervals = sorted((int(start), int(end)) for start, end in intervals)
        self._duration = max(1, int(duration_ms), max((end for _start, end in self._intervals), default=1))
        self._color = QColor(color)
        self.update()

    def intervals(self) -> list[tuple[int, int]]:
        return list(self._intervals)

    def time_at(self, x: float) -> int:
        width = max(1.0, float(self.width() - 2))
        return int(max(0.0, min(1.0, (x - 1) / width)) * self._duration)

    def paintEvent(self, _event):
        theme = _active_theme(None)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(frame, 4, 4)
        painter.fillPath(path, QColor(theme.panel))
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawPath(path)
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        inner = frame.adjusted(1, 3, -1, -3)
        for start, end in self._intervals:
            left = inner.left() + inner.width() * start / self._duration
            width = max(1.6, inner.width() * (end - start) / self._duration)
            painter.drawRoundedRect(QRectF(left, inner.top(), width, inner.height()), 1.2, 1.2)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._intervals:
            self.seek_requested.emit(self.time_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)


class RoleSegment(QWidget):
    """主要 / 游戏声 / 忽略 as one segmented control; the dialog applies the click."""

    role_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons: dict[str, QPushButton] = {}
        for index, (role, label) in enumerate(ROLE_BUTTONS):
            button = QPushButton(self)
            bind_text(button, label)
            button.setObjectName("roleSegment")
            button.setProperty("segment", "first" if index == 0 else "last" if index == len(ROLE_BUTTONS) - 1 else "middle")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=role: self.role_clicked.emit(value))
            self.buttons[role] = button
            layout.addWidget(button)

    def set_role(self, role: str) -> None:
        for value, button in self.buttons.items():
            button.blockSignals(True)
            button.setChecked(value == role)
            button.blockSignals(False)

    def role(self) -> str:
        return next((value for value, button in self.buttons.items() if button.isChecked()), "")


def swatch_menu(parent, colors, current: str, on_pick, on_more):
    """Eight preset colours plus “more colours…”; a pick applies at once."""
    menu = create_studio_menu(parent)
    grid_host = QWidget()
    grid_host.setObjectName("speakerSwatchGrid")
    grid = QGridLayout(grid_host)
    grid.setContentsMargins(10, 8, 10, 6)
    grid.setSpacing(6)
    current_name = QColor(current).name() if QColor(current).isValid() else ""
    for index, color in enumerate(colors):
        choice = QToolButton()
        choice.setObjectName("speakerSwatchChoice")
        choice.setProperty("current", QColor(color).name() == current_name)
        choice.setIcon(color_dot_icon(color, 20))
        choice.setIconSize(QSize(20, 20))
        choice.setFixedSize(28, 28)
        choice.setToolTip(QColor(color).name())
        choice.setCursor(Qt.CursorShape.PointingHandCursor)

        def picked(_checked=False, value=color):
            menu.close()
            on_pick(QColor(value).name())
        choice.clicked.connect(picked)
        grid.addWidget(choice, index // 4, index % 4)
    action = QWidgetAction(menu)
    action.setDefaultWidget(grid_host)
    menu.addAction(action)
    menu.addSeparator()
    more = menu.addAction(tr("更多颜色…"))
    more.triggered.connect(on_more)
    return menu


class SpeakerCard(QFrame):
    """One speaker or recognition label. ``key`` is the speaker id / raw label."""

    def __init__(self, key: str, owner, parent=None):
        super().__init__(parent)
        self.key = key
        self.owner = owner
        self.committed_name = ""
        self.preedit = False
        self.data: dict = {}
        self.setObjectName("speakerCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        # 2026-10-22 (26 speakers took ~0.8 s to open): controls are created
        # inside the card and sub-layouts attached first, so no control is
        # built parentless and re-parented (each move re-ran style sheet work);
        # the two menus are themed when first opened.
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 11)
        root.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(4)
        root.addLayout(head)
        self.select_check = QCheckBox(self)
        self.select_check.setToolTip(tr("勾选后可用上方的批量操作"))
        self.select_check.hide()
        self.select_check.toggled.connect(lambda _checked: owner._card_selection_changed())
        head.addWidget(self.select_check)
        self.swatch = QToolButton(self)
        self.swatch.setObjectName("speakerSwatch")
        self.swatch.setIconSize(QSize(16, 16))
        self.swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.swatch, "换颜色", property="toolTip")
        self.swatch.clicked.connect(lambda: owner._card_choose_color(self))
        head.addWidget(self.swatch)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("speakerName")
        self.name_edit.setProperty("fieldWidth", "speakerName")
        bind_text(self.name_edit, "名称", property="placeholderText")
        bind_text(self.name_edit, "直接输入名字，按 Enter 或点别处保存", property="toolTip")
        self.name_edit.returnPressed.connect(lambda: owner._card_commit_name(self))
        self.name_edit.editingFinished.connect(lambda: owner._card_commit_name(self))
        self.name_edit.installEventFilter(owner)
        head.addWidget(self.name_edit, 1)
        self.pill = QLabel(self)
        self.pill.setObjectName("speakerPill")
        self.pill.hide()
        head.addWidget(self.pill)
        self.host_button = self._icon_button(self, checkable=True)
        self.host_button.clicked.connect(lambda checked: owner._card_set_host(self, checked))
        head.addWidget(self.host_button)
        self.visible_button = self._icon_button(self, checkable=True)
        self.visible_button.clicked.connect(lambda checked: owner._card_set_visible(self, checked))
        head.addWidget(self.visible_button)
        self.more_button = self._icon_button(self)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bind_text(self.more_button, "更多操作", property="toolTip")
        self.more_menu = create_studio_menu(self.more_button, theme_on_show=True)
        self.more_menu.aboutToShow.connect(lambda: owner._card_fill_more_menu(self, self.more_menu))
        self.more_button.setMenu(self.more_menu)
        head.addWidget(self.more_button)

        self.name_error = QLabel(self)
        self.name_error.setObjectName("statusWarn")
        self.name_error.setWordWrap(True)
        self.name_error.hide()
        root.addWidget(self.name_error)

        meta = QHBoxLayout()
        meta.setSpacing(10)
        root.addLayout(meta)
        self.id_label = QLabel(self)
        self.id_label.setObjectName("speakerId")
        meta.addWidget(self.id_label)
        self.meta_label = QLabel(self)
        self.meta_label.setObjectName("speakerMeta")
        meta.addWidget(self.meta_label, 1)

        self.strip = TimeStrip(self)
        self.strip.seek_requested.connect(lambda ms: owner._card_preview_at(self, ms))
        root.addWidget(self.strip)

        excerpt = QHBoxLayout()
        excerpt.setSpacing(8)
        root.addLayout(excerpt)
        self.play_button = QToolButton(self)
        self.play_button.setObjectName("speakerPlay")
        self.play_button.setFixedSize(26, 26)
        self.play_button.setIconSize(QSize(11, 11))
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.play_button, "试听这一句（约 3 秒）", property="toolTip")
        self.play_button.clicked.connect(lambda: owner._card_preview(self))
        excerpt.addWidget(self.play_button)
        self.time_label = QLabel(self)
        self.time_label.setObjectName("speakerTime")
        excerpt.addWidget(self.time_label)
        self.excerpt_label = ElidedLabel(parent=self)
        self.excerpt_label.setObjectName("speakerExcerpt")
        excerpt.addWidget(self.excerpt_label, 1)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("speakerStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        root.addWidget(self.status_label)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.roles = RoleSegment(self)
        self.roles.role_clicked.connect(lambda role: owner._card_role_clicked(self, role))
        foot.addWidget(self.roles)
        self.merge_button = QToolButton(self)
        self.merge_button.setObjectName("speakerMerge")
        bind_text(self.merge_button, "合并到 ▾")
        bind_text(self.merge_button, "把这位的字幕并到另一位", property="toolTip")
        self.merge_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.merge_menu = create_studio_menu(self.merge_button, theme_on_show=True)
        self.merge_menu.aboutToShow.connect(lambda: owner._card_fill_merge_menu(self, self.merge_menu))
        self.merge_button.setMenu(self.merge_menu)
        foot.addWidget(self.merge_button)
        foot.addStretch(1)
        root.addLayout(foot)

    @staticmethod
    def _icon_button(parent=None, *, checkable: bool = False) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("speakerIcon")
        button.setCheckable(checkable)
        button.setIconSize(QSize(15, 15))
        button.setFixedSize(28, 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_playing(self, playing: bool) -> None:
        self.play_button.setProperty("playing", playing)
        self.play_button.setIcon(themed_icon("fa5s.stop" if playing else "fa5s.play",
                                             "on_accent" if playing else "accent"))
        bind_text(self.play_button, "停止试听" if playing else "试听这一句（约 3 秒）", property="toolTip")
        self.play_button.style().unpolish(self.play_button)
        self.play_button.style().polish(self.play_button)

    def set_name_text(self, name: str) -> None:
        """Model name; an uncommitted draft in the field is left alone."""
        if self.name_edit.text() == self.committed_name or not self.name_edit.isEnabled():
            self.name_edit.blockSignals(True)
            self.name_edit.setText(name)
            self.name_edit.blockSignals(False)
        self.committed_name = name

    def update_data(self, data: dict) -> None:
        self.data = data
        theme = _active_theme(None)
        present = bool(data.get("present"))
        for name, value in (("pending", bool(data.get("pending"))), ("folded", not present),
                            ("group", bool(data.get("group")))):
            self.setProperty(name, value)
        self.style().unpolish(self)
        self.style().polish(self)
        color = data.get("color") or "#888888"
        self.swatch.setIcon(color_dot_icon(color, 16, ring=theme.border_strong))
        self.swatch.setEnabled(present)
        self.set_name_text(str(data.get("name") or self.key))
        self.name_edit.setEnabled(present)
        self.id_label.setText(self.key)
        self.id_label.setVisible(self.key != data.get("name"))
        self.meta_label.setText(str(data.get("meta") or ""))
        self.strip.set_data(data.get("intervals") or (), int(data.get("duration_ms") or 1), QColor(color))
        self.strip.setToolTip(str(data.get("strip_tip") or ""))
        pill = str(data.get("pill") or "")
        self.pill.setText(pill)
        self.pill.setProperty("tone", data.get("pill_tone") or "warn")
        self.pill.setToolTip(str(data.get("pill_tip") or ""))
        self.pill.setVisible(bool(pill))
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        host = bool(data.get("host"))
        self.host_button.setChecked(host)
        self.host_button.setIcon(themed_icon("fa5s.star", "warning") if host else themed_icon("fa5s.star", "muted"))
        bind_text(self.host_button, "主播（再点一下取消）" if host else "设为主播", property="toolTip")
        self.host_button.setVisible(present and not data.get("group"))
        visible = not data.get("hidden")
        self.visible_button.setChecked(visible)
        self.visible_button.setIcon(themed_icon("fa5s.eye", "secondary") if visible else themed_icon("fa5s.eye-slash", "warning"))
        bind_text(self.visible_button, "在成片和导出里显示（点一下隐藏）" if visible else "已隐藏：成片和导出不含这位（点一下显示）",
                  property="toolTip")
        self.visible_button.setVisible(present)
        self.more_button.setIcon(themed_icon("fa5s.ellipsis-h", "secondary"))
        self.more_button.setVisible(present)
        self.set_playing(False)
        self.play_button.setEnabled(bool(data.get("excerpt_range")))
        self.time_label.setText(str(data.get("excerpt_time") or ""))
        self.excerpt_label.set_full_text(str(data.get("excerpt") or tr("还没有字幕")))
        status = str(data.get("status") or "")
        self.status_label.setText(status)
        self.status_label.setVisible(bool(status))
        role = data.get("role")
        self.roles.setVisible(role is not None)
        self.roles.set_role(str(role or ""))
        self.merge_button.setVisible(bool(data.get("can_merge")))
        self.select_check.setEnabled(present)
