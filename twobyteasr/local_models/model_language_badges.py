"""Language badge row shared by the model cards and the home role cards (2026-10-18).

Six badges in a fixed order (中文 粤语 方言 英语 日语 韩语) and a "more"
badge, coloured by tier: green = supported, orange = not sure, red (struck
through) = not supported (2026-10-19; was four outline styles with a "日语"
sample in the legend, which read as a statement about Japanese). The same
position on every card lets people scan one column (e.g. 日语) down the
picker. Data: ``model_languages``.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..i18n import bind_text, current_language, tr, translate
from .model_languages import BADGE_LANGUAGES, LANGUAGE_NAMES, LEGEND, TIER_COLORS, TIER_NAMES, more_text, short_name


# Traffic-light hues, fixed across themes so green / orange / red always read
# the same; the badge fill is the hue blended into the card surface.
_HUES = {
    "dark": {"yes": "#5fd38d", "unsure": "#f5a142", "no": "#f26b63"},
    "light": {"yes": "#1b7f45", "unsure": "#b45309", "no": "#c0352b"},
}


def tier_hue(theme, color: str) -> str:
    return _HUES["light" if theme.is_light else "dark"][color]


def language_badge_qss(theme) -> str:
    """Badge rules for one theme; the row applies them to itself."""
    from ..design.ui_theme import blend_hex
    fill = 0.14 if theme.is_light else 0.2
    edge = 0.32 if theme.is_light else 0.42
    rules = []
    for tier, color in TIER_COLORS.items():
        hue = tier_hue(theme, color)
        weight = 700 if color == "yes" else 500
        rules.append(
            f'QLabel#languageBadge[tier="{tier}"] {{ background: {blend_hex(theme.surface, hue, fill)}; '
            f"color: {hue}; border: 1px solid {blend_hex(theme.surface, hue, edge)}; font-weight: {weight}; }}"
        )
        # Home model cards (short labels, 2026-10-23 design A): filled rounded
        # squares, no outline, a little more fill instead.
        rules.append(
            f'QLabel#languageBadge[short="true"][tier="{tier}"] {{ border-color: transparent; '
            f"background: {blend_hex(theme.surface, hue, fill + (0.04 if theme.is_light else 0.02))}; }}"
        )
    for color, _meaning in LEGEND:
        rules.append(
            f'QLabel#languageLegendSwatch[color="{color}"] {{ background: {tier_hue(theme, color)}; border-radius: 3px; }}'
        )
    tier_rules = "\n".join(rules)
    return f"""
QLabel#languageBadge {{
    border-radius: 6px; padding: 1px 7px; font-size: 12px; font-weight: 500;
    border: 1px solid transparent; background: transparent; color: {theme.text_secondary};
}}
QLabel#languageBadge[short="true"] {{ padding: 0px 4px; border-radius: 7px; min-width: 14px; min-height: 20px; }}
{tier_rules}
QLabel#languageBadge[tier="more"] {{
    background: {theme.surface_elevated}; color: {theme.accent_text}; border: 1px solid {theme.border};
}}
QLabel#languageBadge[short="true"][tier="more"] {{
    background: {blend_hex(theme.surface, theme.text, 0.07 if theme.is_light else 0.1)}; color: {theme.text_secondary};
    border-color: transparent; padding: 0px 6px;
}}
QLabel#languageBadgeCaption {{ color: {theme.text_muted}; font-size: 12px; }}
"""


class _Badge(QLabel):
    """One badge; a "not supported" one is struck through.

    Painted here: the badge stylesheet sets the font, which drops both a
    font's strikeOut and QSS text-decoration.
    """

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property("tier") != "no" or not self.text():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().color(QPalette.ColorRole.WindowText))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        width = self.fontMetrics().horizontalAdvance(self.text())
        rect = self.contentsRect()
        left = rect.center().x() - width / 2 - 1
        middle = rect.center().y() + 1
        painter.drawLine(QPointF(left, middle), QPointF(left + width + 2, middle))
        painter.end()


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


class LanguageBadgeRow(QWidget):
    """One row of language badges. ``short`` uses one-character labels (home cards).

    A full-name row whose names do not fit its width (Русский / Deutsch
    interface, narrow card; 2026-10-19) shows the short labels instead of
    clipping them; the tooltips keep the full names. Its size hints stay
    those of the full names either way, so switching labels never changes
    the card layout (no resize feedback).
    """

    def __init__(self, parent=None, *, short: bool = False, caption: bool = False):
        super().__init__(parent)
        self.setObjectName("languageBadgeRow")
        self.short = bool(short)
        self._compact = False
        self._fit_pending = False
        self._support = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3 if self.short else 4)
        self.caption = None
        if caption:
            self.caption = bind_text(QLabel(), "语言")
            self.caption.setObjectName("languageBadgeCaption")
            layout.addWidget(self.caption)
            layout.addSpacing(2)
        self.badges: dict[str, QLabel] = {}
        for code in BADGE_LANGUAGES:
            badge = self._badge()
            self.badges[code] = badge
            layout.addWidget(badge)
        self.more = self._badge()
        self.more.setProperty("tier", "more")
        self.more.hide()
        layout.addWidget(self.more)
        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.set_support(None)
        self.refresh_theme_palette()

    def _badge(self) -> QLabel:
        badge = _Badge()
        badge.setObjectName("languageBadge")
        badge.setProperty("short", self.short)
        badge.setProperty("i18nUserText", True)  # retranslate_ui sets the label
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return badge

    def set_support(self, support: dict | None) -> None:
        """``model_languages.language_support(key)``; None shows every language as unknown."""
        self._support = support
        tiers = (support or {}).get("tiers") or {}
        for code, badge in self.badges.items():
            tier = tiers.get(code, "unknown")
            if badge.property("tier") != tier:
                badge.setProperty("tier", tier)
                badge.style().unpolish(badge)
                badge.style().polish(badge)
        self.retranslate_ui()

    def tier(self, code: str) -> str:
        return str(self.badges[code].property("tier"))

    def retranslate_ui(self) -> None:
        language = current_language()
        support = self._support or {}
        summary = support.get("summary") or ""
        if not self.short and self.isVisible():
            self._compact = self.width() < self.full_names_width()
        short = self.short or self._compact
        for code, badge in self.badges.items():
            name = LANGUAGE_NAMES[code]
            badge.setText(short_name(code, language) if short else translate(name, language))
            bind_text(badge, "{language}：{tier}", property="toolTip",
                      language=tr(name), tier=tr(TIER_NAMES[str(badge.property("tier"))]))
        more = support.get("more")
        template = more_text(more, short=short)
        if template:
            count = more if isinstance(more, str) else str(more)
            self.more.setText(translate(template, language).format(count=count))
            bind_text(self.more, summary or "{count}", property="toolTip", count=count)
            self.more.show()
        else:
            self.more.clear()
            self.more.hide()

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(language_badge_qss(_theme()))

    def full_names_width(self) -> int:
        """Width the row needs with full language names (badge padding included)."""
        language = current_language()
        layout = self.layout()
        width = sum(badge.fontMetrics().horizontalAdvance(translate(LANGUAGE_NAMES[code], language)) + 18
                    for code, badge in self.badges.items())
        width += layout.spacing() * len(self.badges)
        if self.caption is not None:
            width += self.caption.sizeHint().width() + 2 + layout.spacing()
        more = (self._support or {}).get("more")
        template = more_text(more, short=False)
        if template:
            count = more if isinstance(more, str) else str(more)
            width += self.more.fontMetrics().horizontalAdvance(translate(template, language).format(count=count)) + 18
        return width

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return hint if self.short else QSize(self.full_names_width(), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return hint if self.short else QSize(self.full_names_width(), hint.height())

    def _schedule_fit(self) -> None:
        # Outside the layout pass that resized the row.
        if not self.short and not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._fit_names)

    def _fit_names(self) -> None:
        self._fit_pending = False
        if self.isVisible() and (self.width() < self.full_names_width()) != self._compact:
            self.retranslate_ui()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_fit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_fit()


class LanguageLegend(QWidget):
    """What the three badge colours mean (top of the model pickers).

    Plain colour swatches, no language name inside: a sample reading "日语"
    looked like a claim about Japanese.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("languageBadgeLegend")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.swatches: dict[str, QLabel] = {}
        for color, meaning_text in LEGEND:
            swatch = QLabel()
            swatch.setObjectName("languageLegendSwatch")
            swatch.setProperty("color", color)
            swatch.setFixedSize(12, 12)
            meaning = bind_text(QLabel(), meaning_text)
            meaning.setObjectName("languageBadgeCaption")
            layout.addWidget(swatch)
            layout.addWidget(meaning)
            layout.addSpacing(10)
            self.swatches[color] = swatch
        layout.addStretch(1)
        self.refresh_theme_palette()

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(language_badge_qss(_theme()))
