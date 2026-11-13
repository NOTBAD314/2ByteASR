"""Pieces of the translation dialog (2026-11-11 方案 A, 三步卡片).

Range cards, the step badges, the coloured status bar and the dialog's style
sheet. The cards only present numbers and forward clicks; the dialog owns
every count and every project change.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from ..design.typography import emphasized

STEP_SIZE = 22


def passive(widget: QWidget) -> QWidget:
    """Child labels of a button let the click reach the button."""
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return widget


def step_badge(number: int) -> QLabel:
    badge = QLabel(str(number))
    badge.setObjectName("translationStep")
    badge.setFixedSize(STEP_SIZE, STEP_SIZE)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return passive(badge)


def chip(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("translationChip")
    return passive(label)


class LayoutButton(QPushButton):
    """A push button whose face is a child layout; its size follows that layout."""

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        layout = self.layout()
        return layout.sizeHint() if layout is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        layout = self.layout()
        return layout.minimumSize() if layout is not None else super().minimumSizeHint()


class ScopeCard(LayoutButton):
    """One range choice: a big number, a title and a short breakdown."""

    def __init__(self, tone: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("translationScopeCard")
        self.setProperty("tone", tone)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 2026-11-11 (user): cards keep the compact height of 方案 A. The row takes the tallest card;
        # spare dialog height goes to the stretch under the steps, never into the cards.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 12)
        layout.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(0)
        self.number = passive(QLabel("0"))
        self.number.setObjectName("translationScopeNumber")
        self.number.setProperty("tone", tone)
        self.check = passive(QLabel("✓"))
        self.check.setObjectName("translationScopeCheck")
        self.check.setProperty("tone", tone)
        self.check.setFixedSize(18, 18)
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.hide()
        top.addWidget(self.number)
        top.addStretch(1)
        top.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        self.title = passive(QLabel(title))
        self.title.setObjectName("translationScopeTitle")
        self.detail = passive(QLabel())
        self.detail.setObjectName("translationScopeDetail")
        self.detail.setWordWrap(True)
        layout.addLayout(top)
        layout.addWidget(self.title)
        layout.addSpacing(2)
        layout.addWidget(self.detail)
        layout.addStretch(1)  # a shorter card keeps its text at the top of the row
        self.toggled.connect(self.check.setVisible)

    def count(self) -> int:
        return int(self.property("count") or 0)

    def set_values(self, count: int, detail: str) -> None:
        self.setProperty("count", int(count))
        self.number.setText(str(int(count)))
        # 方案 A: “失败 23 · 未译 0” then “需更新 0” on its own line; never break inside an item.
        items = [item.replace(" ", "\u00a0") for item in str(detail).split(" · ")]
        lines = [" · ".join(items[:2]), *items[2:]] if len(items) > 2 else [" · ".join(items)]
        self.detail.setText("\n".join(lines))
        self.updateGeometry()
        self.setAccessibleName(f"{self.title.text()} {int(count)}")


class StatusBar(QWidget):
    """Rounded segments, one per translation state; a non-zero state is never invisible."""

    MIN_SEGMENT = 10
    GAP = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("translationStatusBar")
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._segments: list[tuple[int, QColor]] = []
        self._track = QColor("#000000")

    def set_segments(self, segments, track) -> None:
        self._segments = [(int(count), QColor(color)) for count, color in segments if int(count) > 0]
        self._track = QColor(track)
        self.update()

    def segment_widths(self, width: float) -> list[float]:
        counts = [count for count, _color in self._segments]
        if not counts:
            return []
        usable = max(0.0, width - self.GAP * (len(counts) - 1))
        total = sum(counts)
        widths = [max(float(self.MIN_SEGMENT), usable * count / total) for count in counts]
        excess = sum(widths) - usable
        if excess > 0:
            largest = max(range(len(widths)), key=widths.__getitem__)
            widths[largest] = max(float(self.MIN_SEGMENT), widths[largest] - excess)
        return widths

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        height = float(self.height())
        radius = height / 2
        painter.setBrush(self._track)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), height), radius, radius)
        x = 0.0
        for (_count, color), width in zip(self._segments, self.segment_widths(float(self.width()))):
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, 0, width, height), radius, radius)
            x += width + self.GAP
        painter.end()


@emphasized
def build_translation_dialog_qss(t) -> str:
    """Rules for the translation dialog; appended after the secondary-surface sheet."""
    return f"""
QDialog#translationDialog, QWidget#translationBody {{ background: {t.surface}; color: {t.text}; }}
QFrame#translationHeader {{ border: 0;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {t.accent_soft}, stop:1 {t.surface}); }}
QFrame#translationHeader QLabel, QWidget#translationBody QLabel {{ background: transparent; }}
QScrollArea#translationScroll, QWidget#translationScrollViewport {{ background: {t.surface}; border: 0; }}
QDialog#translationDialog QLabel#translationBadge {{ background: {t.accent}; border-radius: 12px; }}
QLabel#translationTitle {{ color: {t.text}; font-size: 20px; font-weight: 800; }}
QFrame#translationLangPill {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 22px; }}
QFrame#translationLangPill[target="true"] {{ border-color: {t.accent}; }}
QDialog#translationDialog QLabel#translationLangFlag {{ background: {t.panel}; color: {t.text_secondary}; border-radius: 15px;
    font-size: 11px; font-weight: 800; }}
QDialog#translationDialog QLabel#translationLangFlag[target="true"] {{ background: {t.accent}; color: {t.text_on_accent}; }}
QLabel#translationLangName {{ color: {t.text}; font-size: 15px; font-weight: 700; }}
QComboBox#translationTargetCombo {{ background: transparent; border: 0; color: {t.text}; font-size: 15px;
    font-weight: 700; padding: 0 4px 0 0; min-height: 30px; }}
QComboBox#translationTargetCombo:disabled {{ color: {t.text_secondary}; }}
QLabel#translationArrow {{ color: {t.accent_text}; font-size: 18px; font-weight: 800; }}
QLabel#translationSafeNote {{ color: {t.text_muted}; font-size: 12px; }}
QDialog#translationDialog QLabel#translationStep {{ background: {t.accent_soft}; color: {t.accent_text}; border-radius: 11px;
    font-size: 12px; font-weight: 800; }}
QLabel#translationSectionTitle {{ color: {t.text}; font-size: 14px; font-weight: 800; }}
QPushButton#translationSectionToggle {{ background: transparent; border: 0; padding: 0; margin: 0;
    min-height: 0; min-width: 0; text-align: left; }}
QDialog#translationDialog QLabel#translationChip {{ background: {t.selected}; color: {t.text_secondary}; border-radius: 10px;
    padding: 2px 9px; font-size: 12px; font-weight: 600; }}
QPushButton#translationScopeCard {{ background: {t.panel}; border: 2px solid {t.border}; border-radius: 18px;
    padding: 0; min-height: 0; min-width: 0; text-align: left; }}
QPushButton#translationScopeCard:hover {{ border-color: {t.border_strong}; }}
QPushButton#translationScopeCard[tone="pending"]:checked {{ border-color: {t.danger}; background: {t.danger_soft}; }}
QPushButton#translationScopeCard[tone="all"]:checked {{ border-color: {t.success}; background: {t.success_soft}; }}
QPushButton#translationScopeCard[tone="selected"]:checked {{ border-color: {t.accent}; background: {t.accent_soft}; }}
QPushButton#translationScopeCard:disabled {{ background: {t.panel}; border-color: {t.border}; }}
QLabel#translationScopeNumber {{ color: {t.text}; font-size: 28px; font-weight: 800; }}
QLabel#translationScopeNumber[tone="pending"] {{ color: {t.danger}; }}
QLabel#translationScopeNumber[tone="all"] {{ color: {t.success}; }}
QLabel#translationScopeNumber[tone="selected"] {{ color: {t.accent_text}; }}
QLabel#translationScopeNumber:disabled, QLabel#translationScopeTitle:disabled,
QLabel#translationScopeDetail:disabled {{ color: {t.disabled}; }}
QLabel#translationScopeTitle {{ color: {t.text}; font-size: 13px; font-weight: 700; }}
QLabel#translationScopeDetail {{ color: {t.text_muted}; font-size: 12px; }}
QDialog#translationDialog QLabel#translationScopeCheck {{ border-radius: 9px; color: {t.text_on_accent}; font-size: 11px; font-weight: 900;
    background: {t.accent}; }}
QDialog#translationDialog QLabel#translationScopeCheck[tone="pending"] {{ background: {t.danger}; color: {t.surface}; }}
QDialog#translationDialog QLabel#translationScopeCheck[tone="all"] {{ background: {t.success}; color: {t.surface}; }}
QFrame#translationAdvanced {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 18px; }}
QFrame#translationLibRow {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
QLabel#translationLibText {{ color: {t.text}; font-size: 13px; font-weight: 600; }}
QLineEdit#translationContext, QPlainTextEdit#translationGlossary {{ background: {t.input_surface}; color: {t.text};
    border: 1px solid {t.border_strong}; border-radius: 12px; padding: 6px 10px; }}
QLineEdit#translationContext {{ min-height: 26px; }}
QLineEdit#translationContext:focus, QPlainTextEdit#translationGlossary:focus {{ border-color: {t.focus}; }}
QLabel#translationLegend {{ color: {t.text_secondary}; font-size: 12px; }}
QFrame#translationAlert {{ background: {t.danger_soft}; border: 0; border-radius: 16px; }}
QDialog#translationDialog QLabel#translationAlertIcon {{ background: {t.danger}; border-radius: 16px; }}
QLabel#translationAlertTitle {{ color: {t.text}; font-size: 13px; }}
QLabel#translationAlertDetail {{ color: {t.text_muted}; font-size: 12px; }}
QPushButton#translationPillButton, QPushButton#translationSecondary {{ background: {t.surface}; color: {t.text};
    border: 1px solid {t.border_strong}; border-radius: 15px; padding: 4px 12px; min-height: 22px; min-width: 0;
    font-size: 12px; font-weight: 700; }}
QPushButton#translationPillButton:hover, QPushButton#translationSecondary:hover {{ border-color: {t.accent}; }}
QPushButton#translationPillButton:disabled, QPushButton#translationSecondary:disabled {{ color: {t.disabled};
    border-color: {t.border}; }}
QFrame#translationRunBox {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 18px; }}
QLabel#translationRunPercent {{ color: {t.accent_text}; font-size: 34px; font-weight: 800; }}
QLabel#translationRunDetail, QLabel#translationHint {{ color: {t.text_muted}; font-size: 12px; }}
QLabel#translationRunDetail {{ font-size: 13px; }}
QProgressBar#translationProgress {{ background: {t.selected}; border: 0; border-radius: 6px;
    min-height: 12px; max-height: 12px; }}
QProgressBar#translationProgress::chunk {{ background: {t.accent}; border-radius: 6px; }}
QFrame#translationResultCard {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 18px; }}
QFrame#translationResultCard[tone="bad"] {{ background: {t.danger_soft}; border-color: {t.danger_soft}; }}
QFrame#translationResultCard[tone="ok"] {{ background: {t.success_soft}; border-color: {t.success_soft}; }}
QLabel#translationResultTitle {{ color: {t.text}; font-size: 16px; font-weight: 800; }}
QFrame#translationResultCard[tone="bad"] QLabel#translationResultTitle {{ color: {t.danger}; }}
QFrame#translationResultCard[tone="ok"] QLabel#translationResultTitle {{ color: {t.success}; }}
QLabel#translationStatus {{ color: {t.text_secondary}; font-size: 13px; }}
QPushButton#translationLogToggle {{ background: transparent; border: 0; color: {t.text_muted}; padding: 2px 0;
    min-height: 0; min-width: 0; font-size: 12px; font-weight: 700; text-align: left; }}
QPushButton#translationLogToggle:hover {{ color: {t.text}; }}
QPlainTextEdit#translationLog {{ background: {t.input_surface}; color: {t.text_secondary}; border: 1px solid {t.border};
    border-radius: 14px; padding: 6px 8px; font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px; }}
QFrame#translationFooter {{ background: {t.surface}; border: 0; border-top: 1px solid {t.border}; }}
QLabel#translationServiceDot {{ background: {t.success}; border-radius: 4px; }}
QLabel#translationServiceDot[state="missing"] {{ background: {t.warning}; }}
QLabel#translationServiceDot[state="none"] {{ background: {t.danger}; }}
QLabel#translationService {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
QPushButton#translationLink {{ background: transparent; border: 0; color: {t.accent_text}; padding: 0 2px;
    min-height: 0; min-width: 0; font-size: 12px; font-weight: 700; }}
QPushButton#translationLink:hover {{ text-decoration: underline; }}
QPushButton#translationLink:disabled {{ color: {t.disabled}; }}
QPushButton#translationClose {{ background: transparent; border: 0; color: {t.text_secondary}; border-radius: 20px;
    padding: 0 16px; min-height: 40px; min-width: 0; font-weight: 600; }}
QPushButton#translationClose:hover {{ background: {t.selected}; color: {t.text}; }}
QPushButton#translationClose[stop="true"] {{ background: {t.danger_soft}; color: {t.danger}; border-radius: 23px;
    padding: 0 24px; min-height: 46px; font-size: 15px; font-weight: 800; }}
QPushButton#translationStart {{ background: {t.accent}; color: {t.text_on_accent}; border: 0; border-radius: 23px;
    min-height: 46px; min-width: 0; padding: 0 24px; font-size: 15px; font-weight: 800; }}
QPushButton#translationStart:hover {{ background: {t.accent_hover}; }}
QPushButton#translationStart:pressed {{ background: {t.accent_pressed}; }}
QPushButton#translationStart:disabled {{ background: {t.selected}; color: {t.disabled}; }}
QDialog#translationDialog {{ background: transparent; }}
QFrame#translationCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 26px; }}
QFrame#translationCard QFrame#translationHeader {{ border-top-left-radius: 25px; border-top-right-radius: 25px; }}
QFrame#translationCard QFrame#translationFooter {{ border-bottom-left-radius: 25px; border-bottom-right-radius: 25px; }}
QFrame#translationCard QScrollArea#translationScroll {{ background: transparent; }}
QDialog#translationDialog QPushButton#translationWindowClose {{ background: transparent; border: 0; border-radius: 17px;
    color: {t.text_secondary}; font-size: 20px; font-weight: 600; padding: 0; min-height: 0; min-width: 0; }}
QDialog#translationDialog QPushButton#translationWindowClose:hover {{ background: {t.selected}; color: {t.text}; }}
QDialog#translationDialog QPushButton#translationStart {{ border-radius: 21px; min-height: 48px; padding: 0 28px; }}
QDialog#translationDialog QPushButton#translationClose {{ border-radius: 18px; }}
QDialog#translationDialog QPushButton#translationClose[stop="true"] {{ border-radius: 21px; min-height: 48px; }}
"""
