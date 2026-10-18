"""Language badge row shared by the model cards and the home role cards (2026-10-18).

Six badges in a fixed order (中文 粤语 方言 英语 日语 韩语) and a "more"
badge, styled by tier: filled = main language, dashed = usable but weaker,
struck through = not supported, dotted = the official sources do not say.
The same position on every card lets people scan one column (e.g. 日语) down
the picker. Data: ``model_languages``.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from .i18n import bind_text, current_language, tr, translate
from .model_languages import BADGE_LANGUAGES, LANGUAGE_NAMES, TIER_NAMES, more_text, short_name


def language_badge_qss(theme) -> str:
    """Badge rules for one theme; the row applies them to itself."""
    from .ui_theme import blend_hex
    if theme.is_light:
        strong_bg = blend_hex(theme.surface, theme.success, 0.18)
        strong_fg = blend_hex(theme.success, theme.text, 0.35)
    else:
        strong_bg = blend_hex(theme.surface, theme.success, 0.24)
        strong_fg = theme.success
    return f"""
QLabel#languageBadge {{
    border-radius: 6px; padding: 1px 7px; font-size: 12px; font-weight: 500;
    border: 1px solid transparent; background: transparent; color: {theme.text_secondary};
}}
QLabel#languageBadge[short="true"] {{ padding: 0px 4px; }}
QLabel#languageBadge[tier="strong"] {{ background: {strong_bg}; color: {strong_fg}; font-weight: 700; }}
QLabel#languageBadge[tier="usable"] {{ color: {theme.text_secondary}; border: 1px dashed {theme.border_strong}; }}
QLabel#languageBadge[tier="no"] {{ color: {theme.text_muted}; }}
QLabel#languageBadge[tier="unknown"] {{ color: {theme.text_muted}; border: 1px dotted {theme.border_strong}; }}
QLabel#languageBadge[tier="more"] {{
    background: {theme.surface_elevated}; color: {theme.accent_text}; border: 1px solid {theme.border};
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
    from .theme_manager import theme_key
    from .ui_theme import theme_definition
    return theme_definition(theme_key())


class LanguageBadgeRow(QWidget):
    """One row of language badges. ``short`` uses one-character labels (home cards)."""

    def __init__(self, parent=None, *, short: bool = False, caption: bool = False):
        super().__init__(parent)
        self.setObjectName("languageBadgeRow")
        self.short = bool(short)
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
        for code, badge in self.badges.items():
            name = LANGUAGE_NAMES[code]
            badge.setText(short_name(code, language) if self.short else translate(name, language))
            bind_text(badge, "{language}：{tier}", property="toolTip",
                      language=tr(name), tier=tr(TIER_NAMES[str(badge.property("tier"))]))
        more = support.get("more")
        template = more_text(more, short=self.short)
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


class LanguageLegend(QWidget):
    """The four badge styles, each with its meaning (top of the model pickers)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("languageBadgeLegend")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.samples: dict[str, QLabel] = {}
        for tier in ("strong", "usable", "no", "unknown"):
            sample = bind_text(_Badge(), LANGUAGE_NAMES["ja"])
            sample.setObjectName("languageBadge")
            sample.setProperty("tier", tier)
            sample.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            meaning = bind_text(QLabel(), TIER_NAMES[tier])
            meaning.setObjectName("languageBadgeCaption")
            layout.addWidget(sample)
            layout.addWidget(meaning)
            layout.addSpacing(8)
            self.samples[tier] = sample
        layout.addStretch(1)
        self.refresh_theme_palette()

    def refresh_theme_palette(self) -> None:
        self.setStyleSheet(language_badge_qss(_theme()))
