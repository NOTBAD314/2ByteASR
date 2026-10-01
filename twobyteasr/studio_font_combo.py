"""Lazy font combo box and its contrast-aware popup delegate."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import QListView, QStyle, QStyleOptionViewItem, QStyledItemDelegate

from .font_system import system_font_inventory
from .studio_theme import StudioComboBox, apply_secondary_surface_theme

from .i18n import bind_text

class FontFamilyDelegate(QStyledItemDelegate):
    """Renders each font row in its own family, theme-readable."""

    def __init__(self, combo: "LazyFontComboBox", parent=None):
        super().__init__(parent)
        self._combo = combo

    def sizeHint(self, option, index) -> QSize:
        return QSize(240, 34)

    @staticmethod
    def _channel_luminance(value: int) -> float:
        channel = max(0.0, min(1.0, value / 255.0))
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    @classmethod
    def _contrast_ratio(cls, foreground: QColor, background: QColor) -> float:
        foreground_luminance = (
            0.2126 * cls._channel_luminance(foreground.red())
            + 0.7152 * cls._channel_luminance(foreground.green())
            + 0.0722 * cls._channel_luminance(foreground.blue())
        )
        background_luminance = (
            0.2126 * cls._channel_luminance(background.red())
            + 0.7152 * cls._channel_luminance(background.green())
            + 0.0722 * cls._channel_luminance(background.blue())
        )
        lighter = max(foreground_luminance, background_luminance)
        darker = min(foreground_luminance, background_luminance)
        return (lighter + 0.05) / (darker + 0.05)

    @staticmethod
    def _blend(foreground: QColor, background: QColor, weight: float) -> QColor:
        weight = max(0.0, min(1.0, weight))
        return QColor(
            round(foreground.red() * weight + background.red() * (1.0 - weight)),
            round(foreground.green() * weight + background.green() * (1.0 - weight)),
            round(foreground.blue() * weight + background.blue() * (1.0 - weight)),
        )

    @classmethod
    def _readable_disabled_text(cls, palette: QPalette, background: QColor) -> QColor:
        disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        if cls._contrast_ratio(disabled, background) >= 3.0:
            return disabled
        enabled = palette.color(QPalette.ColorRole.Text)
        for weight in (0.64, 0.72, 0.82, 1.0):
            candidate = cls._blend(enabled, background, weight)
            if cls._contrast_ratio(candidate, background) >= 3.0:
                return candidate
        return enabled

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        family = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        selected = enabled and bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = enabled and not selected and bool(opt.state & QStyle.StateFlag.State_MouseOver)
        base = opt.palette.color(QPalette.ColorRole.Base)
        if selected:
            background = opt.palette.color(QPalette.ColorRole.Highlight)
            color = opt.palette.color(QPalette.ColorRole.HighlightedText)
        elif hovered:
            background = opt.palette.color(QPalette.ColorRole.AlternateBase)
            color = opt.palette.color(QPalette.ColorRole.Text)
        elif enabled:
            background = base
            color = opt.palette.color(QPalette.ColorRole.Text)
        else:
            background = base
            color = self._readable_disabled_text(opt.palette, background)

        # QSS/native item controls can disagree about the popup palette. Own
        # the complete row so a dark theme can never leave a native white fill
        # behind light preview text.
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawRect(opt.rect)
        if background != base:
            state_rect = QRectF(opt.rect).adjusted(1.0, 1.0, -1.0, -1.0)
            painter.setBrush(background)
            painter.drawRoundedRect(state_rect, 4.0, 4.0)
        painter.restore()
        if not family:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = opt.rect.adjusted(10, 0, -8, 0)
        font = QFont(family)
        font.setPointSize(max(10, opt.font.pointSize() + 1))
        painter.setFont(font)
        painter.setPen(color)
        recent = family in self._combo.recent_families()
        tag_width = 0
        if recent:
            tag_text = "最近"
            tag_font = QFont(opt.font)
            tag_font.setPointSize(max(8, opt.font.pointSize() - 2))
            metrics = QFontMetrics(tag_font)
            tag_width = metrics.horizontalAdvance(tag_text) + 12
            tag_rect = QRectF(rect.right() - tag_width, rect.center().y() - 9, tag_width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            accent = opt.palette.color(QPalette.ColorRole.Link)
            painter.setBrush(accent)
            painter.drawRoundedRect(tag_rect, 4, 4)
            painter.setFont(tag_font)
            painter.setPen(opt.palette.color(QPalette.ColorRole.BrightText))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)
        name_rect = QRectF(rect.left(), rect.top(), rect.width() - tag_width, rect.height())
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, family)
        painter.restore()


class LazyFontComboBox(StudioComboBox):
    """Searchable in-inspector font dropdown.

    No top-level dialog: typing in the combo filters the list, each row is
    rendered in its own family, and recent picks stay pinned with a badge.
    """

    fontPicked = Signal(str, int)

    MAX_RECENT = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts_loaded = False
        self._font_load_pending = True
        self._recent_fonts = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"]
        self._all_families: list[str] = []
        self._suppress_filter = False
        view = QListView()
        view.setObjectName("fontFamilyPopup")
        view.setItemDelegate(FontFamilyDelegate(self, view))
        view.setMinimumHeight(340)
        apply_secondary_surface_theme(view)
        self.setView(view)
        self.refresh_theme_palette()
        self.setMaxVisibleItems(18)
        self.addItem("Microsoft YaHei UI")
        self.activated.connect(lambda index: self.commit_family(self.itemText(index)))

    def recent_families(self) -> set[str]:
        return set(self._recent_fonts)

    def setEditable(self, editable: bool) -> None:
        super().setEditable(editable)
        if editable and self.lineEdit() is not None:
            bind_text(self.lineEdit(), '输入或搜索字体…', property='placeholderText')
            self.lineEdit().textChanged.connect(self._filter_families)
            self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        # The whole combo frame must open the list: clicking the text field is
        # the largest target, not only the arrow button. Consume the press and
        # hand focus back to the edit so typing still filters the open list.
        if watched is self.lineEdit() and event.type() == QEvent.Type.MouseButtonPress:
            if not self.view().isVisible():
                editor = self.lineEdit()
                editor.setFocus(Qt.FocusReason.MouseFocusReason)
                self.showPopup()
                return True
        return super().eventFilter(watched, event)

    def showPopup(self) -> None:
        audit = getattr(self, "interaction_runtime_audit", None)
        if audit is None:
            self._show_font_popup()
            return
        with audit.measure("Font", allow_new_top_levels=True):
            self._show_font_popup()

    def _show_font_popup(self) -> None:
        self._load_full_font_list()
        # Opening the list must show every font. Filtering by the current text
        # here forced users to delete the field content before other families
        # became visible.
        current = self.currentText()
        self.refresh_theme_palette()
        apply_secondary_surface_theme(self.view())
        self._suppress_filter = True
        if self._fonts_loaded:
            self._rebuild_items("")
            self.setEditText(current)
        try:
            super().showPopup()
        finally:
            # Qt may emit textChanged while creating/selecting the popup view.
            # Keep that programmatic emission from narrowing the freshly
            # opened all-font list back to the current family.
            self._suppress_filter = False

    def hidePopup(self) -> None:
        super().hidePopup()

    def _load_full_font_list(self) -> None:
        if self._fonts_loaded:
            return
        inventory = system_font_inventory()
        families = [entry.family for entry in inventory]
        if not families:
            families = sorted(
                {str(item).strip() for item in QFontDatabase().families() if str(item).strip()},
                key=str.casefold,
            )
        self._all_families = families
        self._fonts_loaded = True
        self._suppress_filter = True
        self._rebuild_items("")
        self._suppress_filter = False

    def _filter_families(self, text: str) -> None:
        if self._suppress_filter or not self._fonts_loaded:
            return
        self._rebuild_items(text, keep_popup=True)

    def _rebuild_items(self, filter_text: str, keep_popup: bool = False) -> None:
        needle = str(filter_text).strip().casefold()
        current = str(filter_text)
        candidates = [family for family in self._all_families if not needle or needle in family.casefold()]
        if not needle:
            recent = [family for family in self._recent_fonts if family in self._all_families or family in ("Microsoft YaHei UI",)]
            rest = [family for family in candidates if family not in self._recent_fonts]
            ordered = recent + rest
        else:
            recent = [family for family in self._recent_fonts if needle in family.casefold()]
            rest = [family for family in candidates if family not in self._recent_fonts]
            ordered = recent + rest
        previous_suppression = self._suppress_filter
        self._suppress_filter = True
        popup_visible = self.view().isVisible() if keep_popup else False
        self.blockSignals(True)
        self.clear()
        self.addItems(ordered[:400] if needle else ordered)
        self.setEditText(current)
        self.blockSignals(False)
        self._suppress_filter = previous_suppression

    def commit_family(self, family: str) -> None:
        family = str(family).strip()
        if not family:
            return
        if self.findText(family) < 0:
            self._suppress_filter = True
            self.addItem(family)
            self._suppress_filter = False
        self._suppress_filter = True
        self.setCurrentText(family)
        self.setEditText(family)
        self._suppress_filter = False
        self._recent_fonts[:] = [family] + [value for value in self._recent_fonts if value != family][: self.MAX_RECENT - 1]
        self.fontPicked.emit(family, 400)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and self.findText(self.currentText().strip()) >= 0:
            self.commit_family(self.currentText().strip())
            event.accept()
            return
        super().keyPressEvent(event)
