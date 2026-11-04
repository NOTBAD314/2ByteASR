"""Home-page widgets.

``QuickPickRow`` came with the 2026-10-08 home redesign.  The workflow strip,
media pick card and name label, collapsible panels and the drag-and-drop
overlay moved here from ``app/ui.py`` on 2026-10-15 (``ui`` still exports them).
``MarkedPill`` and ``LanguageField`` belong to the 2026-10-23 widget redesign
(design A: tonal fills, no hairlines; facts are pills, actions rounded squares).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..design.theme_manager import theme_key
from ..design.ui_theme import AMBER, BLUE, CORAL, GREEN, theme_definition
from ..design.ui_widgets import AnimatedButton
from ..i18n import bind_text
from ..i18n_widgets import user_text
from .main_ui_helpers import _active_theme_definition, _icon


class QuickPickRow(QWidget):
    """Recent content names as one-click chips on a single line.

    Chips that do not fit the current width are hidden instead of wrapping,
    so the content card keeps a stable height at every window size.
    """

    picked = Signal(str)
    GAP = 6

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.caption = QLabel(caption, self)
        self.caption.setObjectName("homeQuickCaption")
        self.chips: list[QPushButton] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_items(self, names, current: str = "") -> None:
        names = [str(name) for name in names if str(name).strip()]
        if names != [chip.property("contentName") for chip in self.chips]:
            for chip in self.chips:
                chip.deleteLater()
            self.chips = []
            for name in names:
                chip = QPushButton(self)
                chip.setObjectName("contentQuickChip")
                chip.setCheckable(True)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setProperty("contentName", name)
                # Names are user data laid out here; skip the i18n width guard.
                chip.setProperty("flexibleWidth", True)
                text = name if len(name) <= 12 else name[:11] + "…"
                user_text(chip).setText(text)
                bind_text(chip, '设为本批内容', property='toolTip')
                chip.clicked.connect(lambda _=False, value=name: self.picked.emit(value))
                self.chips.append(chip)
        for chip in self.chips:
            chip.blockSignals(True)
            chip.setChecked(chip.property("contentName") == current)
            chip.blockSignals(False)
        self.setVisible(bool(self.chips))
        self.updateGeometry()
        self._relayout()

    CHIP = 32

    def _chip_height(self) -> int:
        # The chip's own height (its style sheet min/max-height, scaled by the
        # interface zoom), not a constant: a fixed 32 px row cut the bottom
        # border off 37 px chips at 110% zoom (2026-10-14 user screenshot).
        heights = [chip.sizeHint().expandedTo(chip.minimumSize()).height() for chip in self.chips]
        if not heights:
            from .ui_zoom import px
            return px(self.CHIP)
        return max(heights)

    def sizeHint(self):
        return QSize(320, self._chip_height() + 4)

    def minimumSizeHint(self):
        return QSize(0, self._chip_height() + 4)

    def event(self, event):
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange, QEvent.Type.LayoutRequest):
            self.updateGeometry()
            self._relayout()
        return super().event(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        chip_height = self._chip_height()
        if self.height() and self.height() < chip_height + 4:
            self.updateGeometry()  # the parent layout gives the taller row next pass
        height = self.height() or chip_height + 4
        chip_height = min(chip_height, height)
        caption = self.caption.sizeHint()
        self.caption.setGeometry(0, (height - caption.height()) // 2, caption.width(), caption.height())
        x = caption.width() + 10
        full = False
        for chip in self.chips:
            size = chip.sizeHint().expandedTo(chip.minimumSize())
            full = full or x + size.width() > self.width()
            if full:
                chip.hide()
                continue
            chip.setGeometry(x, (height - chip_height) // 2, size.width(), chip_height)
            chip.show()
            x += size.width() + self.GAP


class FlowStage(QWidget):
    def __init__(self, icon_name: str, title: str, subtitle: str, color: str):
        super().__init__()
        self.color = color
        self._state = ""
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(50, 50)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(_icon(icon_name, color).pixmap(QSize(31, 31)))
        self.title_label = QLabel(title)
        self.title_label.setObjectName("title")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("muted")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.icon_label)
        layout.addLayout(text)
        self.set_state("pending")

    def _stage_fill(self, state: str) -> str:
        theme = _active_theme_definition()
        if state == "done":
            return theme.accent_soft
        if state == "active":
            return theme.warning_soft
        return theme.surface_elevated

    def set_state(self, state: str):
        self._state = state
        opacity = "1.0" if state in {"active", "done"} else "0.68"
        self.setStyleSheet(f"opacity: {opacity};")
        self.icon_label.setStyleSheet(
            f"border: 2px solid {self.color}; border-radius: 25px; background: {self._stage_fill(state)};"
        )

    def refresh_theme_palette(self) -> None:
        self.set_state(self._state or "pending")


class WorkflowStrip(QFrame):
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("workflow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 10, 18, 15)
        outer.setSpacing(7)
        ribbon = QLabel("  字幕生成流程  ")
        ribbon.setObjectName("sectionTitle")
        # P0: keep height minimal but let width breathe; CN text must not truncate.
        ribbon.setMinimumHeight(28)
        ribbon.setMaximumWidth(220)
        outer.addWidget(ribbon, 0, Qt.AlignmentFlag.AlignLeft)
        row = QHBoxLayout()
        row.setSpacing(17)
        specs = [
            ("fa5s.wave-square", "本地识别", "语音转写", GREEN),
            ("fa5s.pen-nib", "字幕校对", "识别错误修正", AMBER),
            ("fa5s.comment-alt", "全文断句", "添加标点与分句", BLUE),
            ("fa5s.file-export", "导出", "生成字幕文件", CORAL),
        ]
        self.stages = []
        for index, spec in enumerate(specs):
            stage = FlowStage(*spec)
            self.stages.append(stage)
            row.addWidget(stage, 1)
            if index < len(specs) - 1:
                arrow = QLabel()
                arrow.setPixmap(_icon("fa5s.arrow-right", "#99978f").pixmap(QSize(22, 22)))
                row.addWidget(arrow)
        outer.addLayout(row)
        self.set_active(0)

    def enterEvent(self, event):
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)

    def set_active(self, index: int, finished: bool = False):
        for stage_index, stage in enumerate(self.stages):
            if finished or stage_index < index:
                state = "done"
            elif stage_index == index:
                state = "active"
            else:
                state = "pending"
            stage.set_state(state)


class MediaPickCard(QFrame):
    """Whole local-media card is one accessible pick/drop target."""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaRow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '选择本地视频或音频', property='accessibleName')
        self.setAccessibleDescription("按回车或空格打开文件选择，也可以把文件拖到这里")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint()) if hasattr(event, "position") else self.childAt(event.pos())
            button = child
            while button is not None and not isinstance(button, QAbstractButton):
                button = button.parentWidget() if button is not self else None
                if button is self:
                    button = None
                    break
            if button is None:
                self.activated.emit()
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MediaNameLabel(QLabel):
    """Media file name that elides in the middle instead of widening the page."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def text(self):
        return self._full_text

    def setText(self, text):
        self._full_text = str(text)
        self._elide()
        self.updateGeometry()

    def sizeHint(self):
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full_text) + margins.left() + margins.right() + 4
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(min(self.sizeHint().width(), 120), super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideMiddle, max(20, self.contentsRect().width())
        )
        if shown != super().text():
            super().setText(shown)


class CollapsibleFrame(QFrame):
    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        icon_name: str,
        summary: str = "",
        expanded: bool = False,
        action_text: str = "",
    ):
        super().__init__()
        self.setObjectName("accordion")
        self._expanded = bool(expanded)
        # B3：整行都是 hit target。header 自身接收空白区/摘要点击，
        # title/chevron 子按钮 accept 自己的事件不会冒泡，天然单次 toggle。
        self.header = QWidget()
        self.header.setObjectName("accordionHeader")
        self.header.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.mousePressEvent = lambda event: (
            self.set_expanded(not self._expanded) if event.button() == Qt.MouseButton.LeftButton else None
        )
        self.header.keyPressEvent = lambda event: (
            self.set_expanded(not self._expanded)
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Space)
            else QWidget.keyPressEvent(self.header, event)
        )
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 2, 8, 2)
        header_layout.setSpacing(10)
        self.title_button = AnimatedButton(title)
        self.title_button.setObjectName("accordionButton")
        self.title_button.setIcon(_icon(icon_name))
        self.title_button.setIconSize(QSize(21, 21))
        self.title_button.clicked.connect(lambda: self.set_expanded(not self._expanded))
        header_layout.addWidget(self.title_button)
        header_layout.addStretch(1)
        self.summary_label = QLabel(summary)
        self.summary_label.setObjectName("accordionSummary")
        self.summary_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(self.summary_label)
        if action_text:
            self.action_button = AnimatedButton(action_text)
            self.action_button.clicked.connect(lambda: self.set_expanded(True))
            header_layout.addWidget(self.action_button)
        else:
            self.action_button = None
        self.chevron = AnimatedButton()
        self.chevron.setObjectName("flat")
        self.chevron.setFixedSize(30, 30)
        self.chevron.clicked.connect(lambda: self.set_expanded(not self._expanded))
        header_layout.addWidget(self.chevron)
        self._title = title
        self._summary = summary
        self.content = QWidget()
        # Its maximum height follows its own size hint (interface zoom: own size).
        self.content.setProperty("uiZoomOwnSize", True)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 3, 16, 12)
        self.content_layout.setSpacing(8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self.animation = QPropertyAnimation(self.content, b"maximumHeight", self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.set_expanded(expanded, animate=False)

    def set_summary(self, summary: str):
        self._summary = summary
        self._refresh_header()

    def _refresh_header(self):
        self.summary_label.setText(self._summary)
        icon_name = "fa5s.chevron-up" if self._expanded else "fa5s.chevron-down"
        self.chevron.setIcon(_icon(icon_name))
        self.chevron.setIconSize(QSize(14, 14))

    def set_expanded(self, expanded: bool, animate: bool = True):
        from ..design.ui_motion import MOTION_STANDARD_MS, motion_duration
        self._expanded = bool(expanded)
        # 留 6px 余量：不同系统字体度量差异会导致 sizeHint 低估、内容被截
        target = self.content.sizeHint().height() + 6 if expanded else 0
        self.content.setVisible(True)
        self.content.setMinimumHeight(0)
        # 展开 180ms / 收起 150ms：收起不承载阅读内容，短一档让连续开关更干脆。
        duration = motion_duration(MOTION_STANDARD_MS if expanded else 150)
        if animate and duration and self.isVisible() and target <= 360:
            self.animation.stop()
            self.animation.setDuration(duration)
            self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.animation.setStartValue(min(self.content.height(), self.content.maximumHeight(), 360))
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self.animation.stop()
            self.content.setMaximumHeight(target)
        self._refresh_header()
        self.toggled.emit(bool(expanded))

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示后字体/布局已定型，重算展开高度，防止内容被截
        if self._expanded:
            self.content.setMaximumHeight(self.content.sizeHint().height() + 6)


class DropOverlay(QFrame):
    """Full-window drag target that dims the workbench without stealing drops."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 64, 64, 64)
        layout.addStretch(1)
        self.target = QFrame(self)
        self.target.setObjectName("dropTarget")
        self.target.setMinimumSize(420, 220)
        self.target.setMaximumSize(680, 320)
        target_layout = QVBoxLayout(self.target)
        target_layout.setContentsMargins(36, 30, 36, 30)
        target_layout.addStretch(1)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_layout.addWidget(self.icon)
        target_layout.addSpacing(12)
        self.title = QLabel("把文件放入这里")
        self.title.setObjectName("dropOverlayTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_layout.addWidget(self.title)
        self.hint = QLabel("松开鼠标即可添加视频或音频 · 支持多选")
        self.hint.setObjectName("dropOverlayHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_layout.addWidget(self.hint)
        target_layout.addStretch(1)
        layout.addWidget(self.target, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._finish_animation)
        self._requested_visible = False
        self.refresh_theme_palette()
        self.hide()

    def refresh_theme_palette(self):
        theme = theme_definition(theme_key())
        self.icon.setPixmap(_icon("fa5s.file-upload", theme.accent).pixmap(QSize(82, 82)))
        # A light theme scrim dims the page without covering it; the drop card
        # itself carries the themed surface and accent border from APP_QSS.
        self.setStyleSheet(
            f"QFrame#dropOverlay {{ background: {theme.overlay_scrim}; border: 0; }}"
        )

    def set_file_count(self, count: int):
        (bind_text(self.hint, '松开鼠标即可放入 {value0} 个可用文件', value0=count) if count > 1 else bind_text(self.hint, '松开鼠标即可添加这个视频或音频'))

    def set_active(self, active: bool):
        self._requested_visible = bool(active)
        self.animation.stop()
        if active:
            from ..design.native_surfaces import cover_native_video
            cover_native_video(self)
            self.show()
            self.raise_()
            start = max(0.0, float(self.opacity.opacity()))
            self.animation.setDuration(150)
            self.animation.setStartValue(start)
            self.animation.setEndValue(1.0)
        else:
            self.animation.setDuration(105)
            self.animation.setStartValue(float(self.opacity.opacity()))
            self.animation.setEndValue(0.0)
        self.animation.start()

    def _finish_animation(self):
        if not self._requested_visible:
            self.hide()


class MarkedPill(QLabel):
    """A pill label with a mark before its text: a status dot (``mark="dot"``)
    or a qtawesome glyph (``mark="fa5s.check"``), both in the label's own text
    colour, which the stylesheet sets (2026-10-23, design A).

    The mark sits in a left contents margin, so the stylesheet keeps the
    plain ``padding`` of a text-only pill and ``text()`` stays the words."""

    def __init__(self, text: str = "", mark: str = "dot", parent=None):
        super().__init__(text, parent)
        self._mark = ""
        self._pixmaps: dict[tuple, object] = {}
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_mark(mark)

    def set_mark(self, mark: str) -> None:
        mark = str(mark or "")
        if mark == self._mark:
            return
        self._mark = mark
        from . import ui_zoom
        self.setContentsMargins(ui_zoom.px(0 if not mark else 22 if mark == "dot" else 26), 0, 0, 0)
        self.update()

    def mark(self) -> str:
        return self._mark

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._mark:
            return
        from . import ui_zoom
        color = self.palette().color(QPalette.ColorRole.WindowText)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        middle = self.height() / 2
        left = ui_zoom.px(10)
        if self._mark == "dot":
            side = ui_zoom.px(7)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(left, middle - side / 2, side, side))
        else:
            side = ui_zoom.px(12)
            key = (self._mark, color.name(), side, self.devicePixelRatioF())
            pixmap = self._pixmaps.get(key)
            if pixmap is None:
                import qtawesome as qta
                self._pixmaps.clear()
                pixmap = self._pixmaps[key] = qta.icon(self._mark, color=QColor(color)).pixmap(QSize(side, side))
            painter.drawPixmap(round(left - 1), round(middle - side / 2), pixmap)
        painter.end()


class LanguageField(QFrame):
    """One filled 字幕语言与输出 field: its caption inside, over the dropdown,
    and a round chevron; a click anywhere opens the dropdown (2026-10-23)."""

    def __init__(self, caption: str, combo, parent=None):
        super().__init__(parent)
        self.setObjectName("homeLanguageField")
        self.combo = combo
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 5, 8, 5)
        row.setSpacing(8)
        lines = QVBoxLayout()
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(0)
        self.caption = QLabel(" ")
        if caption:
            bind_text(self.caption, caption)
        self.caption.setObjectName("homeLanguageCaption")
        # A long caption (other interface languages) may clip; it never widens the row.
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lines.addWidget(self.caption)
        lines.addWidget(combo)
        row.addLayout(lines, 1)
        self.chevron = QLabel()
        self.chevron.setObjectName("homeLanguageChevron")
        self.chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from . import ui_zoom
        ui_zoom.set_size(self.chevron, fixed_w=26, fixed_h=26)
        self.chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        from . import ui_zoom
        theme = theme_definition(theme_key())
        locked = bool(self.combo.property("aiLock"))
        color = theme.text_muted if locked or not self.combo.isEnabled() else theme.accent_text
        side = ui_zoom.px(11)
        self.chevron.setPixmap(_icon("fa5s.chevron-down", color).pixmap(QSize(side, side)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.combo.isEnabled():
            self.combo.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)
