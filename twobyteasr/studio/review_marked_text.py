"""Review card 1: the caption with its click-to-fix marks drawn as ruby.

User (2026-10-17): the inline "须弥→虚迷 / 须迷" chip broke the sentence, so
it was hard to tell what was wrong and what the alternatives were; show the
fix above the questioned characters and leave a little space around them.

The sentence stays one readable line of text.  A questioned span (``model``
or ``glossary`` mark) keeps its place in the sentence on the yellow
difference highlight, with a small gap on both sides; its alternatives sit
above it as accent chips, one chip per alternative (``MAX_SHOWN`` of them,
the rest behind a "+n" chip).  Chips that would collide with a neighbour's
or leave the card slide sideways and keep a thin leader line to their span.
他/她/它 marks stay underlined in the sentence (P and a click flip them).

The review row has a fixed height (``studio_workspace.REVIEW_DOCK_ROW_HEIGHT``),
so a caption's own line break is drawn as a muted "↵" inside the line instead
of starting a second chip band; the text wraps only when the card is narrow.

The widget only lays out, paints and hit-tests; the card decides what a hit
does (``studio_cards.ReviewCandidateCard``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPalette, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy

BASE = -1   # hit on the questioned characters themselves
MORE = -2   # hit on the "+n" chip

MARK_GAP = 3.0     # space between a questioned span and its neighbours
MARK_PAD = 2.0     # highlight beyond the questioned characters
CHIP_PAD = 5.0     # inside a chip, left and right
CHIP_GAP = 3.0     # between the chips of one span
GROUP_GAP = 6.0    # between the chip groups of neighbouring spans
CHIP_RISE = 2.0    # between the chips and the line they annotate
LINE_GAP = 2.0
LINE_BREAK_SIGN = "↵"
MAX_SHOWN = 2
CHIP_MAX_TEXT = 118.0
_CLOSING = set("，。！？、；：）》」』】,.!?;:)…")
_TOKEN = re.compile(r"\n|[A-Za-z0-9_'’.\-]+ *| +|.", re.S)


@dataclass
class _Chip:
    option: int          # option index, or MORE
    text: str
    rect: QRectF = field(default_factory=QRectF)


@dataclass
class _Mark:
    index: int
    kind: str
    text: str
    line: int
    rect: QRectF = field(default_factory=QRectF)
    chips: list = field(default_factory=list)
    group: QRectF = field(default_factory=QRectF)


@dataclass
class _Layout:
    width: float
    height: float
    runs: list           # (x, baseline, text, muted): plain text and line-break signs
    marks: list          # _Mark, in text order


class ReviewMarkedText(QLabel):
    """Caption text with ruby chips above its questioned spans.

    A QLabel so the card's stylesheet (font, colour) and existing callers
    (``text()``, ``font()``, ``grab()``) keep working; ``text()`` is the
    plain caption."""

    def __init__(self, text: str, suggestions, parent=None) -> None:
        super().__init__(parent)
        self._caption = str(text or "")
        self._suggestions = tuple(suggestions or ())
        self._hover = None       # (mark, option) under the pointer
        self._cache = None       # (key, _Layout)
        self.setText(self._caption)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # layout ---------------------------------------------------------------
    def _fonts(self):
        base = self.font()
        chip = QFont(base)
        if base.pixelSize() > 0:
            chip.setPixelSize(max(11, round(base.pixelSize() * 0.8)))
        else:
            chip.setPointSizeF(max(8.0, base.pointSizeF() * 0.8))
        chip.setWeight(QFont.Weight.DemiBold)
        return base, chip

    def _atoms(self):
        """(kind, text, mark) pieces: ``text`` words/characters, ``mark`` spans,
        ``sep`` (the caption's own line break)."""
        atoms, cursor = [], 0
        for index, row in enumerate(self._suggestions):
            if row.start < cursor or row.end > len(self._caption):
                continue
            atoms.extend(("text", token, -1) for token in _TOKEN.findall(self._caption[cursor:row.start]))
            atoms.append(("mark", self._caption[row.start:row.end], index))
            cursor = row.end
        atoms.extend(("text", token, -1) for token in _TOKEN.findall(self._caption[cursor:]))
        return [("sep", LINE_BREAK_SIGN, -1) if kind == "text" and value == "\n" else (kind, value, mark)
                for kind, value, mark in atoms]

    def _chips_for(self, row, chip_fm: QFontMetricsF, shown: int, max_text: float) -> list:
        options = list(row.options)
        chips = []
        for number, option in enumerate(options[:shown]):
            label = option.text or "∅"
            chips.append(_Chip(number, chip_fm.elidedText(label, Qt.TextElideMode.ElideRight, max_text)))
        if len(options) > shown:
            chips.append(_Chip(MORE, f"+{len(options) - shown}"))
        return chips

    def _layout(self, width: float) -> _Layout:
        width = max(40.0, float(width))
        base_font, chip_font = self._fonts()
        key = (round(width, 1), base_font.key(), self._caption,
               tuple((row.start, row.end, tuple(option.text for option in row.options)) for row in self._suggestions))
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1]
        fm, chip_fm = QFontMetricsF(base_font), QFontMetricsF(chip_font)
        line_height = fm.height()
        chip_height = chip_fm.height() + 1.0

        def ruby(index: int) -> bool:
            row = self._suggestions[index]
            return row.kind != "pronoun" and bool(row.options)

        def advance(kind: str, value: str, index: int) -> float:
            if kind == "mark" and ruby(index):
                return fm.horizontalAdvance(value) + 2 * MARK_PAD + (0 if value else 4.0)
            return fm.horizontalAdvance(value)

        # 1. lines: marks never split; a word wider than the line breaks into characters.
        lines: list[list] = [[]]
        x, gap_after = 0.0, False
        queue = list(self._atoms())
        while queue:
            kind, value, index = queue.pop(0)
            spaced = kind == "sep" or (kind == "mark" and ruby(index))
            w = advance(kind, value, index)
            lead = MARK_GAP if x > 0 and (spaced or gap_after) else 0.0
            if x > 0 and x + lead + w > width and not (kind == "text" and value[:1] in _CLOSING):
                if kind == "text" and len(value) > 1 and w > width:
                    queue[:0] = [("text", char, -1) for char in value]
                    continue
                lines.append([])
                x, lead = 0.0, 0.0
                if kind == "text" and not value.strip():
                    gap_after = False
                    continue
            elif x == 0 and kind == "text" and len(value) > 1 and w > width:
                queue[:0] = [("text", char, -1) for char in value]
                continue
            lines[-1].append((kind, value, index, x + lead, w))
            x += lead + w
            gap_after = spaced

        # 2. vertical positions; a line with ruby marks gets a chip band above it.
        runs, marks, y = [], [], 0.0
        for number, line in enumerate(lines):
            if number:
                y += LINE_GAP
            has_ruby = any(kind == "mark" and ruby(index) for kind, _value, index, _x, _w in line)
            band_top = y
            if has_ruby:
                y += chip_height + CHIP_RISE
            top = y
            baseline = top + fm.ascent()
            line_marks = []
            for kind, value, index, left, w in line:
                if kind in ("text", "sep"):
                    runs.append((left, baseline, value, kind == "sep"))
                    continue
                row = self._suggestions[index]
                mark = _Mark(index, row.kind, value, number, QRectF(left, top, w, line_height))
                marks.append(mark)
                if ruby(index):
                    line_marks.append(mark)
            if line_marks:
                self._place_groups(line_marks, chip_fm, band_top, chip_height, width)
            y = top + line_height
        layout = _Layout(width, max(y, line_height), runs, marks)
        self._cache = (key, layout)
        return layout

    def _place_groups(self, line_marks, chip_fm, top, chip_height, width) -> None:
        """Chip groups centred over their spans; collisions slide right, the
        right edge pushes back left; too little room shows fewer chips."""
        attempts = ((MAX_SHOWN, CHIP_MAX_TEXT), (1, CHIP_MAX_TEXT), (1, 44.0), (0, 0.0))
        for shown, max_text in attempts:
            for mark in line_marks:
                mark.chips = self._chips_for(self._suggestions[mark.index], chip_fm, shown, max_text) \
                    if shown else [_Chip(MORE, "…")]
            widths = [sum(chip_fm.horizontalAdvance(chip.text) + 2 * CHIP_PAD for chip in mark.chips)
                      + CHIP_GAP * (len(mark.chips) - 1) for mark in line_marks]
            lefts, edge = [], 0.0
            for mark, w in zip(line_marks, widths):
                left = max(edge, mark.rect.center().x() - w / 2)
                lefts.append(left)
                edge = left + w + GROUP_GAP
            over = lefts[-1] + widths[-1] - width
            for number in range(len(lefts) - 1, -1, -1):
                if over <= 0:
                    break
                floor = lefts[number - 1] + widths[number - 1] + GROUP_GAP if number else 0.0
                shift = min(over, max(0.0, lefts[number] - floor))
                for later in range(number, len(lefts)):
                    lefts[later] -= shift
                over -= shift
            if over <= 0.5:
                break
        for mark, left, w in zip(line_marks, lefts, widths):
            x = left
            for chip in mark.chips:
                chip_w = chip_fm.horizontalAdvance(chip.text) + 2 * CHIP_PAD
                chip.rect = QRectF(x, top, chip_w, chip_height)
                x += chip_w + CHIP_GAP
            mark.group = QRectF(left, top, w, chip_height)

    def _offset(self, layout: _Layout) -> float:
        return max(0.0, (self.contentsRect().height() - layout.height) / 2)

    # geometry contract -----------------------------------------------------
    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        margins = self.contentsMargins()
        inner = width - margins.left() - margins.right()
        return int(self._layout(inner).height + 0.999) + margins.top() + margins.bottom()

    def sizeHint(self) -> QSize:
        width = min(260, int(QFontMetricsF(self.font()).horizontalAdvance(self._caption) + 40))
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return QSize(60, self.heightForWidth(10_000))

    def changeEvent(self, event) -> None:
        self._cache = None
        super().changeEvent(event)

    def refresh(self) -> None:
        self._cache = None
        self.updateGeometry()
        self.update()

    # hit testing ------------------------------------------------------------
    def hit_at(self, point) -> tuple[int, int] | None:
        """``(mark, option)`` under ``point`` (widget coordinates): option is a
        chip's option index, ``MORE`` for "+n", ``BASE`` for the span itself."""
        if not self._suggestions:
            return None
        rect = self.contentsRect()
        layout = self._layout(rect.width())
        local = QPointF(point) - QPointF(rect.left(), rect.top() + self._offset(layout))
        for mark in layout.marks:
            for chip in mark.chips:
                if chip.rect.adjusted(-1.5, -2, 1.5, 1).contains(local):
                    return mark.index, chip.option
        for mark in layout.marks:
            slack = MARK_GAP / 2 if mark.chips else 1.0
            if mark.rect.adjusted(-slack, -1, slack, 1).contains(local):
                return mark.index, BASE
        return None

    def set_hover(self, hit) -> None:
        if hit != self._hover:
            self._hover = hit
            self.update()

    def chip_rects(self) -> dict:
        """``{(mark, option): QRectF}`` in widget coordinates (tests, audits)."""
        rect = self.contentsRect()
        layout = self._layout(rect.width())
        offset = QPointF(rect.left(), rect.top() + self._offset(layout))
        result = {}
        for mark in layout.marks:
            result[(mark.index, BASE)] = mark.rect.translated(offset)
            for chip in mark.chips:
                result[(mark.index, chip.option)] = chip.rect.translated(offset)
        return result

    # painting -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        theme = theme_definition(theme_key())
        rect = self.contentsRect()
        layout = self._layout(rect.width())
        base_font, chip_font = self._fonts()
        fm = QFontMetricsF(base_font)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.translate(rect.left(), rect.top() + self._offset(layout))
        painter.setFont(base_font)
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        for x, baseline, value, muted in layout.runs:
            painter.setPen(QColor(theme.text_muted) if muted else ink)
            painter.drawText(QPointF(x, baseline), value)

        hover_mark = self._hover[0] if self._hover else -1
        for mark in layout.marks:
            box = mark.rect
            baseline = box.top() + fm.ascent()
            if mark.kind == "pronoun" or not mark.chips:
                painter.setPen(QColor(theme.accent))
                painter.drawText(QPointF(box.left(), baseline), mark.text)
                pen = QPen(QColor(theme.accent), 1.4 if mark.index == hover_mark else 1.0)
                painter.setPen(pen)
                painter.drawLine(QPointF(box.left(), baseline + 3), QPointF(box.right(), baseline + 3))
                continue
            # the questioned span: yellow highlight, underline, a little space around it
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.warning_soft))
            painter.drawRoundedRect(box, 3, 3)
            painter.setBrush(QColor(theme.warning))
            painter.drawRect(QRectF(box.left() + 1, box.bottom() - 2, box.width() - 2, 2))
            if mark.index == hover_mark:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(theme.warning), 1))
                painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            painter.setPen(QColor(theme.warning))
            if mark.text:
                painter.drawText(QPointF(box.left() + MARK_PAD, baseline), mark.text)
            else:  # an insertion point: the other recognizers heard something here
                painter.drawRect(QRectF(box.center().x() - 1, box.top() + 3, 2, box.height() - 6))
            # leader line when the chips had to slide off the span
            centre = box.center().x()
            group = mark.group
            if not group.left() + 4 <= centre <= group.right() - 4:
                leader = QColor(theme.accent)
                leader.setAlphaF(0.65)
                painter.setPen(QPen(leader, 1.2))
                start = QPointF(min(max(centre, group.left() + 4), group.right() - 4), group.bottom())
                painter.drawLine(start, QPointF(centre, box.top()))
            # chips
            painter.setFont(chip_font)
            for chip in mark.chips:
                hovered = self._hover == (mark.index, chip.option)
                if chip.option == MORE:
                    painter.setBrush(QColor(theme.surface))
                    painter.setPen(QPen(QColor(theme.accent_hover if hovered else theme.accent), 1))
                    painter.drawRoundedRect(chip.rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
                    painter.setPen(QColor(theme.text))
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(theme.accent_hover if hovered else theme.accent))
                    painter.drawRoundedRect(chip.rect, 4, 4)
                    if hovered:
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QPen(QColor(theme.text_on_accent), 1))
                        painter.drawRoundedRect(chip.rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
                    painter.setPen(QColor(theme.text_on_accent))
                painter.drawText(chip.rect, Qt.AlignmentFlag.AlignCenter, chip.text)
            painter.setFont(base_font)
        painter.end()


__all__ = ["BASE", "MORE", "ReviewMarkedText"]
