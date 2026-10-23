"""Model role rows of the Studio 识别字幕 sheet (2026-10-23, layout C).

One thin row per role (主力转写 / 字幕时间轴 / 文字复核): the model's logo,
the role in its identity hue, the model name with its languages right after
it, and the readiness chip. The interface language's badge comes first (so
people see at once whether their language is supported), then the other
supported languages while they fit, then "+N" for the rest (user, 10-23:
no repeated description of what the model does). The whole row opens the
home model picker. Facts come from ``MainWindow.recognition_role_state``;
without a main window (tests, a bare page) the catalog alone gives the logo
and languages, and no readiness is claimed.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..i18n import bind_text, current_language, tr, translate

ROLE_LABELS = {"primary": "主力转写", "timeline": "字幕时间轴", "review": "文字复核"}
# The glyph shown before a model is chosen or when the role is off (home card icons).
ROLE_GLYPHS = {"primary": "fa5s.wave-square", "timeline": "fa5s.clock", "review": "fa5s.check-circle"}
TONES = ("good", "warn", "muted")
# Readiness is said by the chip's words and its icon, not by colour alone.
TONE_ICONS = {"good": "fa5s.check-circle", "warn": "fa5s.exclamation-circle", "muted": "fa5s.minus-circle"}
ICON_SIZE = 32
# Interface language -> the badge language that is "theirs".
UI_BADGE = {"zh": "zh", "zh-Hant": "zh", "en": "en", "ja": "ja", "ko": "ko"}
SUPPORTED = {"strong", "usable"}


def catalog_facts(role: str, backend: str, name: str, provider: str = "") -> dict:
    """The facts the catalog alone can give (no readiness): logo and languages."""
    model = None
    if backend not in ("", "off", "none"):
        try:
            from ..local_models.model_workshop import model_for_backend
            model = model_for_backend(role, backend, provider or "qwen31_filetrans")
        except Exception:  # noqa: BLE001 - a missing catalog entry only drops the logo
            model = None
    return {"backend": backend, "name": name, "status": "", "tone": "muted", "model": model,
            "line": None, "note": None}


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _px(value: int) -> int:
    try:
        from ..app import ui_zoom
        return ui_zoom.px(value)
    except Exception:  # noqa: BLE001 - no zoom module: plain pixels
        return value


def badge_plan(support: dict | None, ui_language: str) -> tuple[list[tuple[str, str]], object]:
    """(badges in display order as (code, tier), the model's extra-language count or "50+").

    The interface language's badge first whatever its tier (a struck badge
    says plainly that it is not supported), then the other supported ones in
    the usual order.
    """
    if not support:
        return [], None
    from ..local_models.model_languages import BADGE_LANGUAGES
    tiers = support.get("tiers") or {}
    own = UI_BADGE.get(ui_language)
    order = ([own] if own in BADGE_LANGUAGES else []) + [code for code in BADGE_LANGUAGES if code != own]
    badges = [(code, tiers.get(code, "unknown")) for code in order
              if code == own or tiers.get(code, "unknown") in SUPPORTED]
    return badges, support.get("more")


class LanguageBadges(QWidget):
    """Badges painted in one line; those that do not fit become "+N".

    Painted, not child labels: fitting the line to the width changes no
    size hint, so a resize can never feed back into the layout.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sheetLanguageBadges")
        self._badges: list[tuple[str, str]] = []
        self._more = None
        self._summary = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_support(self, support: dict | None) -> None:
        self._badges, self._more = badge_plan(support, current_language())
        self._summary = str((support or {}).get("summary") or "")
        self.setToolTip(str(tr(self._summary)) if self._summary else "")
        self.updateGeometry()
        self.update()

    def has_badges(self) -> bool:
        return bool(self._badges)

    # ------------------------------------------------------------ geometry

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(_px(12))
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _label(self, code: str) -> str:
        from ..local_models.model_languages import short_name
        return short_name(code, current_language())

    def _badge_width(self, metrics: QFontMetrics, text: str) -> int:
        return metrics.horizontalAdvance(text) + _px(10)

    def _gap(self) -> int:
        return _px(4)

    def _more_text(self, hidden: int) -> str:
        extra = self._more
        if isinstance(extra, str):           # a published total such as "50+"
            return str(translate("共 {count} 种", current_language()).format(count=extra))
        count = int(extra or 0) + hidden
        return f"+{count}" if count else ""

    def layout_badges(self, width: int) -> tuple[list[tuple[str, str]], str]:
        """The badges that fit ``width`` and the "+N" text after them."""
        metrics = QFontMetrics(self._font())
        gap = self._gap()
        for shown in range(len(self._badges), 0, -1):
            more = self._more_text(len(self._badges) - shown)
            need = sum(self._badge_width(metrics, self._label(code)) + gap for code, _tier in self._badges[:shown])
            if more:
                need += self._badge_width(metrics, more)
            if need <= width:
                return self._badges[:shown], more
        first = self._badges[:1]
        return first, self._more_text(len(self._badges) - len(first))

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self._font())
        width = sum(self._badge_width(metrics, self._label(code)) + self._gap() for code, _tier in self._badges)
        more = self._more_text(0)
        if more:
            width += self._badge_width(metrics, more)
        return QSize(width, metrics.height() + _px(4))

    def minimumSizeHint(self) -> QSize:
        metrics = QFontMetrics(self._font())
        if not self._badges:
            return QSize(0, metrics.height() + _px(4))
        first = self._badge_width(metrics, self._label(self._badges[0][0]))
        more = self._more_text(len(self._badges) - 1)
        return QSize(first + self._gap() + (self._badge_width(metrics, more) if more else 0),
                     metrics.height() + _px(4))

    # ------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:
        if not self._badges:
            return
        from ..design.ui_theme import blend_hex
        from ..local_models.model_language_badges import tier_hue
        from ..local_models.model_languages import TIER_COLORS
        theme = _theme()
        font = self._font()
        metrics = QFontMetrics(font)
        shown, more = self.layout_badges(self.width())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(font)
        height = metrics.height() + _px(4)
        top = (self.height() - height) / 2
        x = 0.0
        fill, edge = (0.14, 0.32) if theme.is_light else (0.2, 0.42)
        for code, tier in shown:
            text = self._label(code)
            width = self._badge_width(metrics, text)
            hue = tier_hue(theme, TIER_COLORS.get(tier, "unsure"))
            rect = QRectF(x + 0.5, top + 0.5, width - 1, height - 1)
            painter.setPen(QPen(QColor(blend_hex(theme.surface, hue, edge)), 1))
            painter.setBrush(QColor(blend_hex(theme.surface, hue, fill)))
            painter.drawRoundedRect(rect, _px(5), _px(5))
            painter.setPen(QColor(hue))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            if tier == "no":
                middle = rect.center().y() + 1
                advance = metrics.horizontalAdvance(text)
                left = rect.center().x() - advance / 2 - 1
                painter.drawLine(int(left), int(middle), int(left + advance + 2), int(middle))
            x += width + self._gap()
        if more:
            width = self._badge_width(metrics, more)
            rect = QRectF(x + 0.5, top + 0.5, width - 1, height - 1)
            painter.setPen(QPen(QColor(theme.border), 1))
            painter.setBrush(QColor(theme.surface_elevated))
            painter.drawRoundedRect(rect, _px(5), _px(5))
            painter.setPen(QColor(theme.accent_text))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, more)
        painter.end()


class ElidedLabel(QLabel):
    """A one-line label that shows "…" instead of being cut; its hints never change with the width."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.fontMetrics().horizontalAdvance("…") * 6), hint.height())

    def is_elided(self) -> bool:
        return self.fontMetrics().horizontalAdvance(self.text()) > self.contentsRect().width()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.setFont(self.font())
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        painter.end()


class StatusChip(QFrame):
    """Readiness chip: icon + words (已就绪 / 需要下载 / 未配置 / 已关闭)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sheetRoleStatus")
        self.setProperty("tone", "muted")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 9, 2)
        layout.setSpacing(5)
        self.icon = QLabel()
        self.icon.setObjectName("sheetRoleStatusIcon")
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel("")
        self.label.setObjectName("sheetRoleStatusText")
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def text(self) -> str:
        return self.label.text()

    def set_state(self, text: str, tone: str) -> None:
        import qtawesome as qta
        tone = tone if tone in TONES else "muted"
        self.label.setText(text)
        self.setProperty("tone", tone)
        theme = _theme()
        colour = {"good": theme.success, "warn": theme.warning}.get(tone, theme.text_secondary)
        size = _px(13)
        self.icon.setPixmap(qta.icon(TONE_ICONS[tone], color=colour).pixmap(size, size))
        for widget in (self, self.label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class MenuComboBox(QComboBox):
    """Looks and sizes exactly like the other dropdowns, but opens a menu of its own.

    The glossary is a checklist (QMenu with check boxes that stay open);
    a plain QComboBox list closes on every click (四十三轮).
    """

    def __init__(self, open_menu, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._open_menu = open_menu
        self.addItem("")

    def set_text(self, text: str) -> None:
        self.setItemText(0, text)

    def text(self) -> str:
        return self.itemText(0)

    def showPopup(self) -> None:
        self._open_menu()

    def wheelEvent(self, event) -> None:
        event.ignore()


class RecognitionRoleRow(QFrame):
    """A clickable thin row: logo | role | model name · languages | readiness | chevron."""

    clicked = Signal(str)  # role

    def __init__(self, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self._model = None
        self._facts: dict = {}
        self.setObjectName("sheetRoleRow")
        self.setProperty("role", role)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bind_text(self, '点击更换模型', property='toolTip')
        bind_text(self, '{value0} 模型卡', property='accessibleName', value0=ROLE_LABELS.get(role, role))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setObjectName("sheetRoleIcon")
        self.icon.setFixedSize(ICON_SIZE, ICON_SIZE)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.role_label = bind_text(QLabel(), ROLE_LABELS.get(role, role))
        self.role_label.setObjectName("sheetRoleName")
        layout.addWidget(self.role_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.name = ElidedLabel("—")
        self.name.setObjectName("sheetModelName")
        layout.addWidget(self.name, 0, Qt.AlignmentFlag.AlignVCenter)
        self.languages = LanguageBadges()
        layout.addWidget(self.languages, 1, Qt.AlignmentFlag.AlignVCenter)
        self.status = StatusChip()
        self.status.hide()
        layout.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.chevron = QLabel()
        self.chevron.setObjectName("sheetRoleChevron")
        self.chevron.setFixedWidth(12)
        layout.addWidget(self.chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        for child in (self.icon, self.role_label, self.status, self.name, self.languages, self.chevron):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._paint_chevron()
        self._paint_icon()

    def _align_role_width(self) -> None:
        """Every row gives its role the width of the widest role label, so the names line up.

        Measured with the label's own (styled) font once the row is shown; the
        rows share the font and the three texts, so they land on one width.
        """
        self.role_label.ensurePolished()
        metrics = self.role_label.fontMetrics()
        language = current_language()
        width = max(metrics.horizontalAdvance(translate(text, language)) for text in ROLE_LABELS.values())
        self.role_label.setFixedWidth(width + 8)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._align_role_width()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange, QEvent.Type.LanguageChange):
            self._align_role_width()

    # ------------------------------------------------------------ facts

    def set_facts(self, facts: dict) -> None:
        """Show one role's facts (``recognition_role_state()["roles"][role]`` or ``catalog_facts``)."""
        from ..local_models.model_languages import language_support

        self._facts = dict(facts)
        # The short name (MOSS Pro 云端, not its model id); the full one in the tooltip.
        full = str(facts.get("name") or "—")
        self.name.setText(str(facts.get("short") or full))
        note = facts.get("note")
        self.name.setToolTip(f"{full}\n{note}" if note else full)
        status = str(facts.get("status") or "")
        self.status.set_state(status, str(facts.get("tone") or "muted"))
        # 已关闭 / 未选择 as the name already says it; no second chip with the same words.
        self.status.setVisible(bool(status) and status != self.name.text())
        self._model = facts.get("model")
        self.languages.set_support(language_support(self._model.key) if self._model is not None else None)
        self._paint_icon()

    def facts(self) -> dict:
        return dict(self._facts)

    # ------------------------------------------------------------ painting

    def _role_colour(self) -> str:
        theme = _theme()
        return theme.role_colors.get(self.role, theme.accent_text)

    def _paint_chevron(self) -> None:
        import qtawesome as qta
        self.chevron.setPixmap(qta.icon("fa5s.chevron-right", color=_theme().text_muted).pixmap(10, 12))

    def _paint_icon(self) -> None:
        ratio = self.devicePixelRatioF() or 1.0
        if self._model is not None:
            from ..app.ui_recognition import model_tile_pixmap
            self.icon.setPixmap(model_tile_pixmap(self._model, ICON_SIZE, ratio))
            return
        # No model (off / nothing chosen): the role glyph on a soft chip in its hue.
        import qtawesome as qta
        from ..design.ui_theme import blend_hex
        theme = _theme()
        colour = self._role_colour()
        pixels = max(1, round(ICON_SIZE * ratio))
        tile = QPixmap(pixels, pixels)
        tile.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tile)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, pixels, pixels), pixels * 0.26, pixels * 0.26)
        painter.fillPath(path, QColor(blend_hex(theme.surface, colour, 0.35 if theme.is_light else 0.22)))
        glyph = round(pixels * 0.45)
        offset = (pixels - glyph) // 2
        qta.icon(ROLE_GLYPHS.get(self.role, "fa5s.circle"), color=colour).paint(
            painter, QRect(offset, offset, glyph, glyph))
        painter.end()
        tile.setDevicePixelRatio(ratio)
        self.icon.setPixmap(tile)

    # ------------------------------------------------------------ events

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.role)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.clicked.emit(self.role)
            return
        super().keyPressEvent(event)


def role_row_rules(palette, light: bool, radius: int, type_scale: dict) -> str:
    """The rows' QSS inside ``QWidget#studioRecognitionSheet`` (identity hue per role)."""
    from ..design.ui_theme import blend_hex
    rest, hover, _edge = palette.role_wash  # rows sit inside a card: tint only, the hover shows the edge
    scope = "QWidget#studioRecognitionSheet"
    rules = [
        f"{scope} QLabel#sheetRoleName {{ font-size: {type_scale['small']}px; font-weight: 700; background: transparent; }}",
        f"{scope} QLabel#sheetModelName {{ color: {palette.text}; font-size: {type_scale['heading2']}px;"
        f" font-weight: 700; background: transparent; }}",
        f"{scope} QFrame#sheetRoleStatus {{ border: 0; border-radius: 7px; }}",
        f"{scope} QFrame#sheetRoleStatus QLabel {{ background: transparent; }}",
        f"{scope} QLabel#sheetRoleStatusText {{ font-size: {type_scale['small']}px; font-weight: 600; }}",
        f"{scope} QFrame#sheetRoleStatus[tone=\"good\"] {{ background: {palette.success_soft}; }}",
        f"{scope} QFrame#sheetRoleStatus[tone=\"good\"] QLabel#sheetRoleStatusText {{ color: {palette.success}; }}",
        f"{scope} QFrame#sheetRoleStatus[tone=\"warn\"] {{ background: {palette.warning_soft}; }}",
        f"{scope} QFrame#sheetRoleStatus[tone=\"warn\"] QLabel#sheetRoleStatusText {{ color: {palette.warning}; }}",
        f"{scope} QFrame#sheetRoleStatus[tone=\"muted\"] {{ background: {palette.surface_elevated}; }}",
        f"{scope} QFrame#sheetRoleStatus[tone=\"muted\"] QLabel#sheetRoleStatusText {{ color: {palette.text_secondary}; }}",
    ]
    for role, colour in palette.role_colors.items():
        rules.append(
            f"{scope} QFrame#sheetRoleRow[role=\"{role}\"] {{ background: {blend_hex(palette.surface, colour, rest)};"
            f" border: 1px solid transparent; border-radius: {radius}px; }}"
            f"{scope} QFrame#sheetRoleRow[role=\"{role}\"]:hover {{"
            f" background: {blend_hex(palette.surface, colour, hover)}; border-color: {colour}; }}"
            f"{scope} QFrame#sheetRoleRow[role=\"{role}\"]:focus {{ border: 1px solid {palette.focus}; }}"
            f"{scope} QFrame#sheetRoleRow[role=\"{role}\"] QLabel#sheetRoleName {{ color: {colour}; }}"
        )
    return "".join(rules)
