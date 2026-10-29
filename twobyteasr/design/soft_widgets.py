"""Soft filled building blocks for the Studio tool panels (2026-10-23).

Looks come from :mod:`twobyteasr.design.soft_qss`; these widgets only give
the controls their shape. Existing controls are wrapped, never replaced: the
dropdown inside a :class:`CaptionField` or behind a :class:`SegmentedControl`
stays the object the rest of Studio (and its tests) reads and connects to.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractSpinBox, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QLayout, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..i18n import bind_text
from .themed_icons import install_themed_icon


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class _FocusMark(QObject):
    """Mark the field frame while its control has keyboard focus (accent edge)."""

    def __init__(self, frame: QFrame, field: QWidget):
        super().__init__(frame)
        self.frame = frame
        field.installEventFilter(self)
        line = None
        getter = getattr(field, "lineEdit", None)
        if callable(getter):
            try:
                line = getter()
            except (RuntimeError, TypeError):
                line = None
        if line is not None:
            line.installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.frame.setProperty("focused", kind == QEvent.Type.FocusIn)
            _repolish(self.frame)
        elif kind == QEvent.Type.EnabledChange and watched is self.frame.field:
            # The field is disabled, not the frame: show it on the frame too.
            self.frame.setProperty("off", not watched.isEnabled())
            _repolish(self.frame)
        return False


def flexible_combo(combo: QComboBox) -> QComboBox:
    """A dropdown whose long item (a full model id, say) elides instead of
    widening the tool panel past its drawer."""
    combo.setProperty("fieldWidth", "flexible")
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(4)
    combo.setMinimumWidth(0)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


def _flexible(field: QWidget) -> None:
    # prepare_controls() pins plain combos to 180 px and spins to 80 px; a
    # wrapped field takes the width of its frame instead.
    if isinstance(field, QComboBox):
        flexible_combo(field)
    field.setProperty("fieldWidth", "caption")
    field.setMinimumWidth(0)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def soft_popup(combo: QComboBox) -> QComboBox:
    """Let the list rows take the soft popup style (a styled delegate)."""
    from PySide6.QtWidgets import QStyledItemDelegate
    if not isinstance(combo.itemDelegate(), QStyledItemDelegate) or type(combo.itemDelegate()).__name__ == "QComboMenuDelegate":
        combo.setItemDelegate(QStyledItemDelegate(combo.view()))
    return combo


class CaptionField(QFrame):
    """A filled field with its caption inside, above the value (design B).

    A click anywhere on the frame opens the dropdown or focuses the box.
    """

    def __init__(self, caption: str, field: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("softCaptionField")
        self.field = field
        self.setCursor(Qt.CursorShape.PointingHandCursor if isinstance(field, QComboBox) else Qt.CursorShape.IBeamCursor)
        lines = QVBoxLayout(self)
        lines.setContentsMargins(11, 5, 9, 6)
        lines.setSpacing(0)
        self.caption = QLabel()
        self.caption.setObjectName("softCaption")
        bind_text(self.caption, caption)
        # A long caption (other interface languages) clips; it never widens the panel.
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lines.addWidget(self.caption)
        _flexible(field)
        if isinstance(field, QComboBox):
            soft_popup(field)
            # A long typed value (a model name) shows its start, not its end,
            # whenever it is filled in from code. The line edit's own signal:
            # the panel refresh fills the box with the combo's signals blocked.
            if field.lineEdit() is not None:
                field.lineEdit().textChanged.connect(self._show_start)
            self._show_start()
        lines.addWidget(field)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _FocusMark(self, field)
        self.setProperty("off", not field.isEnabled())

    def _show_start(self, *_args) -> None:
        edit = self.field.lineEdit()
        if edit is not None and not edit.hasFocus():
            edit.setCursorPosition(0)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.field.isEnabled():
            if isinstance(self.field, QComboBox) and not self.field.isEditable():
                self.field.showPopup()
            else:
                self.field.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            _repolish(self)


class UnitField(QFrame):
    """A filled number box with a quiet axis letter and unit inside (A).

    The spin box keeps its value API; only a trailing suffix moves into the
    quiet unit label (``keep_suffix`` leaves the spin box untouched).
    ``sample`` is the widest value the box must show in full; the box never
    gets narrower than that.
    """

    def __init__(self, field: QAbstractSpinBox, *, axis: str = "", unit: str = "",
                 keep_suffix: bool = False, sample: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("softCaptionField")
        self.setProperty("inline", True)
        self.field = field
        self._sample = sample
        self.setCursor(Qt.CursorShape.IBeamCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(6)
        if not unit and not keep_suffix and hasattr(field, "suffix"):
            unit = field.suffix().strip()
            if unit:
                field.setSuffix("")
        self.axis = QLabel(axis, self)
        self.axis.setObjectName("softAxis")
        self.axis.setVisible(bool(axis))
        self.axis.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.axis)
        _flexible(field)
        row.addWidget(field, 1)
        self.unit = QLabel(unit, self)
        self.unit.setObjectName("softUnit")
        self.unit.setVisible(bool(unit))
        self.unit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.unit)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _FocusMark(self, field)
        self.setProperty("off", not field.isEnabled())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        if not self._sample:
            return hint
        row = self.layout()
        margins = row.contentsMargins()
        # The spin box's frame, plus the line edit's 2 px on each side and
        # room for the cursor.
        chrome = max(0, self.field.width() - self.field.lineEdit().width()) + 6
        width = (margins.left() + margins.right() + chrome
                 + self.field.fontMetrics().horizontalAdvance(self._sample))
        for label in (self.axis, self.unit):
            if not label.isHidden():
                width += label.sizeHint().width() + row.spacing()
        # Not the spin box's own minimum: that one reserves room for the
        # step buttons, which these boxes never show.
        return QSize(width, hint.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.field.isEnabled():
            self.field.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)


class SegmentedControl(QFrame):
    """Choices in one filled track, the chosen one in the accent (A).

    Bound to an existing combo box, which stays the model: a click sets its
    index and emits ``activated`` like a user pick; a change made in code
    shows here. When the words do not fit the width (a long interface
    language, a narrow drawer) the same combo box is shown in its place.
    """

    def __init__(self, combo: QComboBox, parent: QWidget | None = None, *, emit_activated: bool = True):
        super().__init__(parent)
        self.setObjectName("softSegmented")
        self.combo = combo
        self._emit_activated = emit_activated
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(3, 3, 3, 3)
        self._row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.idClicked.connect(self._picked)
        self.buttons: list[QPushButton] = []
        self._collapsed = False
        flexible_combo(combo)
        self._row.addWidget(combo, 1)
        combo.hide()
        model = combo.model()
        model.rowsInserted.connect(self.rebuild)
        model.rowsRemoved.connect(self.rebuild)
        model.dataChanged.connect(self.rebuild)
        combo.currentIndexChanged.connect(self.sync)
        # The combo stays the model: the buttons follow its enabled state. The
        # frame itself is never disabled, so the combo (its child) can always
        # be enabled again by the code that disabled it.
        combo.installEventFilter(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rebuild()

    def _follow_combo(self) -> None:
        enabled = not self.combo.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled)
        for button in self.buttons:
            button.setEnabled(enabled)

    def eventFilter(self, watched, event):
        if watched is self.combo and event.type() == QEvent.Type.EnabledChange:
            self._follow_combo()
        return False

    def minimumSizeHint(self):
        # Never wider than the combo fallback needs: the drawer decides.
        return QSize(60, super().minimumSizeHint().height())

    def _needed_width(self) -> int:
        margins = self._row.contentsMargins()
        widths = [button.sizeHint().width() for button in self.buttons]
        return sum(widths) + self._row.spacing() * max(0, len(widths) - 1) + margins.left() + margins.right()

    def _fit(self) -> None:
        collapsed = bool(self.buttons) and self._needed_width() > self.width()
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        for button in self.buttons:
            button.setVisible(not collapsed)
        self.combo.setVisible(collapsed)
        self._row.setContentsMargins(*((0, 0, 0, 0) if collapsed else (3, 3, 3, 3)))
        self.setProperty("collapsed", collapsed)
        _repolish(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def rebuild(self, *_):
        texts = [self.combo.itemText(index) for index in range(self.combo.count())]
        if texts == [button.text() for button in self.buttons]:
            # A language switch translates the buttons before the combo's
            # items, so the words can be new here: measure again.
            self.sync()
            self._collapsed = not self._collapsed
            self._fit()
            return
        for button in self.buttons:
            self.group.removeButton(button)
            self._row.removeWidget(button)
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self.buttons = []
        for index in range(self.combo.count()):
            button = QPushButton(self.combo.itemText(index), self)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setProperty("flexibleWidth", True)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            tip = self.combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
            if tip:
                button.setToolTip(str(tip))
            button.setVisible(not self._collapsed)
            self.group.addButton(button, index)
            self._row.addWidget(button, 1)
            self.buttons.append(button)
        self.sync()
        self._follow_combo()
        self._collapsed = not self._collapsed  # force a fresh decision
        self._fit()

    def sync(self, *_):
        current = self.combo.currentIndex()
        for index, button in enumerate(self.buttons):
            button.blockSignals(True)
            button.setChecked(index == current)
            button.blockSignals(False)

    def _picked(self, index: int):
        if index != self.combo.currentIndex():
            self.combo.setCurrentIndex(index)
        if self._emit_activated:
            self.combo.activated.emit(index)
        self.sync()


class WrapLayout(QLayout):
    """A row of buttons that wraps onto further lines when the panel is too
    narrow for their words (Russian, a narrow drawer) instead of clipping
    them or letting them overlap. ``fill`` widens each line's buttons to the
    full width; ``center`` centres a line that does not fill it.
    ``by_minimum`` breaks lines on the items' minimum widths (groups of a
    label and fields) rather than their preferred widths (buttons)."""

    def __init__(self, parent=None, *, spacing: int = 6, fill: bool = True, center: bool = False,
                 by_minimum: bool = False):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._fill, self._center = fill, center
        self._by_minimum = by_minimum
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:
        from PySide6.QtWidgets import QWidgetItem
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

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
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        sizes = [item.sizeHint() for item in self._items if not item.isEmpty()]
        width = sum(size.width() for size in sizes) + self._spacing * max(0, len(sizes) - 1)
        return QSize(width, max((size.height() for size in sizes), default=0))

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, *, apply):
        lines, line, used = [], [], 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if self._by_minimum:
                hint = QSize(item.minimumSize().width(), hint.height())
            if line and used + self._spacing + hint.width() > rect.width():
                lines.append((line, used))
                line, used = [], 0
            used += (self._spacing if line else 0) + hint.width()
            line.append((item, hint))
        if line:
            lines.append((line, used))
        y = rect.y()
        for number, (line, used) in enumerate(lines):
            height = max(hint.height() for _item, hint in line)
            extra = max(0, rect.width() - used)
            x = rect.x() + (extra // 2 if self._center and not self._fill else 0)
            share, rest = divmod(extra, len(line)) if self._fill else (0, 0)
            for index, (item, hint) in enumerate(line):
                width = min(rect.width(), hint.width() + share + (1 if index < rest else 0))
                if apply:
                    item.setGeometry(QRect(x, y + (height - hint.height()) // 2, width, hint.height()))
                x += width + self._spacing
            y += height + (self._spacing if number < len(lines) - 1 else 0)
        return y - rect.y()


class SoftTrack(QFrame):
    """A group of top-bar commands in one tonal track (top bar B).

    Hidden while every command in it is hidden (a narrow window, or the
    project library), so no empty track is left on the bar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("studioToolTrack")
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(3, 3, 3, 3)
        self._row.setSpacing(2)
        self.members: list[QWidget] = []

    def add(self, widget: QWidget) -> QWidget:
        self._row.addWidget(widget)
        widget.installEventFilter(self)
        self.members.append(widget)
        self._refresh()
        return widget

    def insert_after(self, anchor: QWidget, widget: QWidget) -> QWidget:
        """Place ``widget`` right after ``anchor``, a command already in this track."""
        index = self.members.index(anchor) + 1
        self._row.insertWidget(index, widget)
        widget.installEventFilter(self)
        self.members.insert(index, widget)
        self._refresh()
        return widget

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self._refresh()
        return False

    def _refresh(self) -> None:
        wanted = any(not member.isHidden() for member in self.members)
        if wanted == self.isHidden():
            self.setVisible(wanted)


def soft_card(*, margins=(14, 12, 14, 12), spacing: int = 10,
              parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """A settings card: a raised fill, rounded, no frame line (A)."""
    card = QFrame(parent)
    card.setProperty("softCard", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return card, layout


def soft_label(text: str, name: str = "softMeta", *, wrap: bool = True) -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    bind_text(label, text)
    label.setWordWrap(wrap)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return label


def soft_pill(text: str = "", tone: str = "off", *, dot: bool = True) -> QLabel:
    """A fact as a pill (● 会话就绪); ``tone`` is ok / warn / off / accent."""
    pill = QLabel()
    pill.setProperty("softPill", tone)
    pill.setProperty("softDot", dot)
    if text:
        set_pill(pill, text, tone)
    pill.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return pill


def set_pill(pill: QLabel, text: str, tone: str | None = None, **arguments) -> None:
    bind_text(pill, ("● " if pill.property("softDot") else "") + text, **arguments)
    if tone is not None and pill.property("softPill") != tone:
        pill.setProperty("softPill", tone)
        _repolish(pill)


def step_badge(number: int) -> QLabel:
    badge = QLabel(str(number))
    badge.setObjectName("softStep")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return badge


class FoldCard(QFrame):
    """A card whose header folds the body away and shows a one-line summary
    while folded (视频 C). ``trailing`` (a switch, say) sits at the right of
    the header and keeps its own clicks."""

    toggled = Signal(bool)

    def __init__(self, title: str, *, summary: str = "", expanded: bool = True,
                 trailing: QWidget | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("softCard", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 8, 12, 8)
        outer.setSpacing(8)
        self.header = QPushButton(self)
        self.header.setObjectName("softFoldHeader")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.header.setProperty("flexibleWidth", True)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setMinimumHeight(30)
        self.header.setCheckable(True)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.arrow = QToolButton(self.header)
        self.arrow.setObjectName("softFoldArrow")
        self.arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.arrow.setAutoRaise(True)
        self.arrow.setFixedSize(16, 16)
        row.addWidget(self.arrow)
        self.title = QLabel(self.header)
        self.title.setObjectName("softCardTitle")
        bind_text(self.title, title)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.title)
        row.addStretch(1)
        from .elided_label import ElidedLabel
        # A long summary (Russian) ends in "…" instead of being cut off.
        self.summary = ElidedLabel("", self.header, mode=Qt.TextElideMode.ElideRight, minimum=40)
        self.summary.setObjectName("softCardSummary")
        self.summary.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.summary, 2)
        if trailing is not None:
            row.addWidget(trailing)
        self.trailing = trailing
        outer.addWidget(self.header)
        self.body = QWidget(self)
        self.body.setObjectName("softFoldBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 4)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body)
        self.header.toggled.connect(lambda checked: self.set_expanded(checked))
        self._expanded = True
        self._summary_source = ("", {})
        if summary:
            self.set_summary(summary)
        self.set_expanded(expanded, notify=False)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, *, notify: bool = True) -> None:
        self._expanded = bool(expanded)
        if self.header.isChecked() != self._expanded:
            self.header.blockSignals(True)
            self.header.setChecked(self._expanded)
            self.header.blockSignals(False)
        self.body.setVisible(self._expanded)
        install_themed_icon(self.arrow, "fa5s.chevron-down" if self._expanded else "fa5s.chevron-right", "muted")
        self.summary.setVisible(not self._expanded or bool(self.property("summaryWhenOpen")))
        if notify:
            self.toggled.emit(self._expanded)

    def set_summary(self, text: str, **arguments) -> None:
        bind_text(self.summary, text, **arguments)
