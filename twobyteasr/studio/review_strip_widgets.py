"""Small widgets of the review strip (2026-11-16, user picked design A 糖果条).

The strip keeps its layout (status + actions on top, candidates, keys below);
these give it rounded pills, keycaps and a one-row key legend whose height
never changes (the row under the video must not re-lay out per caption).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from ..i18n import bind_text, tr


def keycap(text: str, parent=None, *, on_accent: bool = False) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("reviewKeycapOnAccent" if on_accent else "reviewKeycap")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return label


class ReviewPillButton(QPushButton):
    """A rounded pill: themed icon, text and an optional keycap on the right."""

    _KEY_GAP = 8

    def __init__(self, text: str, icon: str | None = None, *, icon_role: str = "secondary",
                 key: str | None = None, primary: bool = False, parent=None):
        super().__init__(parent)
        bind_text(self, text)
        self.setObjectName("reviewPillPrimary" if primary else "reviewPill")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon:
            from ..design.themed_icons import install_themed_icon
            install_themed_icon(self, icon, "on_accent" if primary else icon_role)
            self.setIconSize(QSize(13, 13))
        self.key_label = keycap(key, self, on_accent=primary) if key else None
        self._sync_key_space()

    def set_key(self, key: str) -> None:
        if self.key_label is not None:
            self.key_label.setText(key)
            self._sync_key_space()

    def _sync_key_space(self) -> None:
        if self.key_label is None:
            return
        self.key_label.adjustSize()
        # The widget's own sheet only adds room on the right; colours, radius
        # and the other paddings stay with the Studio sheet. A selector keeps
        # the padding off the keycap label itself.
        self.setStyleSheet("QPushButton { padding-right: %dpx; }"
                           % (self.key_label.sizeHint().width() + 2 * self._KEY_GAP))
        self.updateGeometry()

    def showEvent(self, event):
        # The keycap's padding comes from the strip's sheet, known only once
        # the button sits inside the strip; measure the room again then.
        if self.key_label is not None and not getattr(self, "_key_measured", False):
            self._key_measured = True
            self.key_label.ensurePolished()
            self._sync_key_space()
        super().showEvent(event)

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(hint.width(), max(hint.height(), 32))

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.key_label is not None:
            size = self.key_label.sizeHint()
            self.key_label.setGeometry(self.width() - size.width() - self._KEY_GAP,
                                       (self.height() - size.height()) // 2, size.width(), size.height())


# What the legend shows (keys, meaning). The first five stay in the row; the
# rest are one click away so the row never wraps.
LEGEND = (
    (("1–4",), "采用并下一条"),
    (("Enter",), "当前正确"),
    (("E",), "改字"),
    (("W", "S"), "下一条 / 上一条"),
    (("Space",), "重听"),
    (("D", "A"), "下一条 / 上一条"),
    (("↓", "↑"), "下一条 / 上一条"),
    (("Shift+R",), "采纳建议"),
    (("P",), "他 / 她"),
    (("R",), "退出审核"),
)
LEGEND_ROW = 5


class ReviewKeyLegend(QWidget):
    """One row of keycaps plus 全部快捷键, which lists the rest in a menu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewLegend")
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(5)
        for keys, meaning in LEGEND[:LEGEND_ROW]:
            for index, key in enumerate(keys):
                if index:
                    slash = QLabel("/")
                    slash.setObjectName("reviewLegendText")
                    row.addWidget(slash)
                row.addWidget(keycap(key))
            text = QLabel()
            bind_text(text, meaning)
            text.setObjectName("reviewLegendText")
            row.addWidget(text)
            row.addSpacing(9)
        self.more_button = QToolButton()
        self.more_button.setObjectName("reviewLegendMore")
        self.more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.more_button, "全部快捷键")
        self.more_button.clicked.connect(self._show_all)
        row.addWidget(self.more_button)
        row.addStretch(1)

    def text(self) -> str:
        """The legend as plain text (assistive tools and older callers)."""
        return "   ".join(f"[{'/'.join(keys)}] {tr(meaning)}" for keys, meaning in LEGEND)

    def _show_all(self) -> None:
        from ..design.studio_theme import create_studio_menu
        menu = create_studio_menu(self)
        for keys, meaning in LEGEND:
            action = menu.addAction(f"{' / '.join(keys)}    {tr(meaning)}")
            action.setEnabled(False)
        menu.exec(self.more_button.mapToGlobal(QPoint(0, self.more_button.height())))
