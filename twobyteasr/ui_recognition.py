"""识别方案区：三张角色模型卡（UI IMPLEMENTATION 批准图 #1/#2；2026-10-18 版面 A）。

角色卡是首页第一视觉焦点：
- 顶行 role + [本地/在线] + 状态；模型标志 + 大号模型名（视觉主体）+ 「›」；
  模型的语言与用途一行；底部六格语言徽章
- 整卡可点击（鼠标 / Enter / Space）→ 发出 role_requested，由 MainWindow
  打开模型工坊并 focus 对应角色
- 缺模型 / API 未配置 → 卡内状态提示 + 唯一恢复动作
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from twobyteasr.ui_theme import (
    AMBER,
    AMBER_SOFT as WARM,
    BORDER_STRONG as WARM_BORDER,
    CORAL,
    GREEN,
    GREEN_SOFT,
    GREEN_SUBTLE,
    INK,
    MUTED,
)
from twobyteasr.i18n import current_language, translate
from twobyteasr.theme_manager import theme_key
from twobyteasr.ui_theme import theme_definition

from .i18n import bind_text

from .i18n import tr

# role → (图标字符, 卡底色, 边框色)
_ROLE_STYLES = {
    "primary": ("主", GREEN_SOFT, GREEN),
    "timeline": ("轴", WARM, WARM_BORDER),
    "review": ("核", GREEN_SOFT, GREEN),
}
_ROLE_LABELS = {"primary": "主力转写", "timeline": "字幕时间轴", "review": "文字复核"}
_ROLE_DESCRIPTIONS = {
    "primary": "把语音转成文字，作为字幕初稿",
    "timeline": "断句、时间轴与字幕节奏校准",
    "review": "错词复核、专名与上下文纠正",
}


class _LineLabel(QLabel):
    """The description: wraps, or (compact cards) one line ending in "…"."""

    def paintEvent(self, event):
        if self.wordWrap():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        self.style().drawItemText(painter, rect, int(self.alignment()), self.palette(), self.isEnabled(),
                                  text, self.foregroundRole())
        painter.end()


def home_plan_height(tier: int) -> int:
    """Height (100% px) of the three compact model cards on home (C′,
    2026-10-17) per window-height tier: < 900, 900–1149, ≥ 1150."""
    return {0: 152, 1: 170, 2: 200}.get(tier, 170)


class RecognitionRoleCard(QFrame):
    """单张角色模型卡。整卡 clickable + 键盘可触发。

    2026-10-18 (layout A): role and status share the top line; the model's own
    logo sits beside its name; the line under the name comes from the chosen
    model (its languages and its task, ``model_role_line``) instead of a fixed
    role sentence; the six language badges close the card. "点击更换 / 详情"
    became one chevron beside the name (the whole card still opens the picker).
    """

    clicked = Signal(str)  # role
    recovery_requested = Signal(str, str)  # role, action: install/api

    # role → (qtawesome 图标, 卡底色, 边框/强调色): the chip shown before a
    # model is chosen (or when the role is off).
    _ROLE_STYLES = {
        "primary": ("fa5s.wave-square", GREEN_SOFT, GREEN),
        "timeline": ("fa5s.clock", WARM, WARM_BORDER),
        "review": ("fa5s.check-circle", GREEN_SOFT, GREEN),
    }
    _ROLE_LABELS = {"primary": "主力转写", "timeline": "字幕时间轴", "review": "文字复核"}

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        import qtawesome as qta
        from .model_language_badges import LanguageBadgeRow

        self.role = role
        self.setObjectName("recognitionRoleCard")
        self.setProperty("role", role)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(228)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bind_text(self, '{value0} 模型卡', property='accessibleName', value0=_ROLE_LABELS.get(role, role))
        bind_text(self, '点击更换模型', property='toolTip')
        self._responsive_profile = ""
        self._responsive_apply_count = 0
        self._identity_centered = False
        self._model = None
        self._model_line = None
        self._note = None
        self._glyph_size = 19
        self._name_px = None  # a smaller name size when a name needs a third line
        self._name_base = 0

        icon_name, _card_bg, _border = self._ROLE_STYLES.get(
            role, ("fa5s.circle", GREEN_SOFT, GREEN)
        )
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(6)

        # Top line: role on the left, local/online and readiness on the right;
        # a fix (安装模型 / 配置 API) takes the local/online chip's place. The
        # chips drop under the role when a narrow card cannot hold both.
        top = self._top_layout = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setHorizontalSpacing(6)
        top.setVerticalSpacing(4)
        self.role_label = QLabel(_ROLE_LABELS.get(role, role))
        self.role_label.setObjectName("recognitionRoleLabel")
        top.addWidget(self.role_label, 0, 0)
        top.setColumnStretch(1, 1)
        self.kind_badge = QLabel("")
        self.kind_badge.setObjectName("recognitionKindBadge")
        self.kind_badge.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.kind_badge.hide()
        self.status_badge = QLabel("")
        self.status_badge.setObjectName("recognitionStatusGood")
        self.status_badge.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        chips = self._chips = QWidget()
        chips_layout = QHBoxLayout(chips)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(6)
        chips_layout.addWidget(self.kind_badge)
        chips_layout.addWidget(self.status_badge)
        self.recovery = QPushButton("")
        self.recovery.setObjectName("recognitionRecovery")
        self.recovery.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recovery.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # The button must not pin the card's minimum width: otherwise a card
        # widened once (maximized window) can never narrow again.
        self.recovery.setProperty("flexibleWidth", True)
        self.recovery.setMinimumWidth(1)
        self.recovery.hide()
        self.recovery.clicked.connect(
            lambda: self.recovery_requested.emit(self.role, self._recovery_action)
        )
        chips_layout.addWidget(self.recovery)
        top.addWidget(chips, 0, 2, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(top)

        self._leading_space_index = layout.count()
        self._leading_space = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        layout.addSpacerItem(self._leading_space)

        identity = self._identity_layout = QHBoxLayout()
        identity.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("recognitionRoleIcon")
        self.icon_label.setFixedSize(44, 44)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(qta.icon(icon_name, color=self._icon_color()).pixmap(20, 20))
        identity.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.model_label = QLabel("—")
        self.model_label.setProperty("uiZoomOwnSize", True)  # height measured from its own text
        self.model_label.setObjectName("recognitionModelName")
        self.model_label.setWordWrap(True)
        self.model_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.model_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        identity.addWidget(self.model_label, 1)
        self.change_hint = QLabel()
        self.change_hint.setObjectName("recognitionChangeHint")
        self.change_hint.setFixedWidth(10)
        self.change_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        identity.addWidget(self.change_hint, 0, Qt.AlignmentFlag.AlignVCenter)
        self.detail_hint = self.change_hint  # one chevron replaces 点击更换 + 详情 ›
        layout.addLayout(identity)

        self._upper_gap = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        layout.addSpacerItem(self._upper_gap)
        self.description_label = _LineLabel(_ROLE_DESCRIPTIONS.get(role, ""))
        self.description_label.setObjectName("recognitionModelDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.description_label)
        self._body_stretch_index = layout.count()
        layout.addStretch(3)

        # Bottom: the model's languages, always one line.
        self.language_row = LanguageBadgeRow(short=True)
        # Hidden (no model chosen) it keeps its line, so the three cards'
        # names stay level.
        policy = self.language_row.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.language_row.setSizePolicy(policy)
        self.language_row.hide()
        layout.addWidget(self.language_row)

        for child in (
            self.icon_label,
            self.role_label,
            self.model_label,
            self.description_label,
            self.kind_badge,
            self.status_badge,
            self.change_hint,
            chips,
        ):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._recovery_action = ""
        self._paint_chevron()
        self.apply_responsive_profile("compact")

    def retranslate(self, language: str | None = None):
        language = language or current_language()
        role_text = translate(_ROLE_LABELS.get(self.role, self.role), language)
        self.role_label.setText(role_text)
        self.setAccessibleName(
            f"{role_text} " + ("model card" if language == "en" else "模型卡")
        )
        self._layout_status()

    def refresh_theme_palette(self) -> None:
        self._paint_icon()
        self._paint_chevron()
        self._sync_model_slot_height()

    def _icon_color(self):
        theme = theme_definition(theme_key())
        # Light themes paint the chip with the role's identity hue
        # (theme.role_colors) and the glyph on top; dark themes use a soft chip
        # with the glyph in that hue (2026-10-17, calmer on dark).
        if theme.is_light:
            return theme.on_vivid
        return theme.role_colors.get(self.role, theme.accent_text)

    def _paint_chevron(self) -> None:
        import qtawesome as qta
        from . import ui_zoom
        color = theme_definition(theme_key()).text_muted
        self.change_hint.setPixmap(qta.icon("fa5s.chevron-right", color=color).pixmap(ui_zoom.px(10), ui_zoom.px(12)))

    def _paint_icon(self) -> None:
        """The chosen model's logo tile, or the role chip when none is chosen."""
        import qtawesome as qta
        from . import ui_zoom
        size = self.icon_label.width()
        if self._model is None:
            self.icon_label.setStyleSheet("")
            glyph = ui_zoom.px(self._glyph_size)
            self.icon_label.setPixmap(qta.icon(self._icon_name, color=self._icon_color()).pixmap(glyph, glyph))
            return
        self.icon_label.setStyleSheet("background: transparent;")
        self.icon_label.setPixmap(model_tile_pixmap(self._model, size, self.devicePixelRatioF()))

    # ------------------------------------------------------------ 事件

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.role)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.clicked.emit(self.role)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 状态

    def set_state(self, model_name: str, kind: str, status: str, tone: str, recovery: str = ""):
        """model_name 主值；kind=本地/在线；status=已就绪/需要下载/未配置/已关闭；
        tone=good/warn/muted；recovery=唯一恢复动作文案（空=无）。"""
        self.model_label.setText(model_name)
        if kind:
            self.kind_badge.setText(kind)
        else:
            self.kind_badge.clear()
        self.kind_badge.setVisible(bool(kind) and not recovery)  # _layout_status may hide it
        self.status_badge.setText(status)
        self.status_badge.setVisible(bool(status))
        self.status_badge.setObjectName(
            {"good": "recognitionStatusGood", "warn": "recognitionStatusWarn",
             "muted": "recognitionStatusMuted"}.get(tone, "recognitionStatusMuted")
        )
        self._recovery_action = recovery
        if recovery:
            self.recovery.setText(recovery)
            self.recovery.show()
        else:
            self.recovery.hide()
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_badge.update()
        self._sync_model_slot_height()
        self._layout_status()

    def set_model(self, model=None, line=None):
        """The catalog model this role runs (None: nothing chosen or off) and its line.

        ``line`` (``model_role_line``) replaces the role sentence under the
        name; the logo and the language badges come from the same model.
        """
        from .model_languages import language_support
        self._model = model
        self._model_line = line if model is not None else None
        self._paint_icon()
        if model is None:
            self.language_row.set_support(None)
            self.language_row.hide()
        else:
            self.language_row.set_support(language_support(model.key))
            self.language_row.show()
        self._show_description()
        self._layout_status()

    def set_note(self, note=None):
        """Show a short reason in place of the description line (None: the description).

        2026-10-18: the timeline card says when the chosen model is not used
        for the spoken language, so the card and the model picker agree.
        """
        self._note = note
        self._show_description()

    def _show_description(self) -> None:
        text = self._note or self._model_line or _ROLE_DESCRIPTIONS.get(self.role, "")
        bind_text(self.description_label, text)
        self._sync_model_slot_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_model_slot_height()
        self._layout_status()

    def retranslate_ui(self):
        self._layout_status()

    def _layout_status(self):
        """Fit the top line. When it is short of room the local/online chip
        goes first (its text moves to the status tooltip), then, beside a fix
        button, the status chip (the button says what to do); only then do
        the chips drop under the role."""
        if not hasattr(self, '_chips'):
            return
        margins = self.layout().contentsMargins()
        available = self.width() - margins.left() - margins.right()
        # A card with a fix button and one without keep the same top line
        # (compact cards have no height to spare for it).
        compact = self._responsive_profile == "compact"
        self._chips.setMinimumHeight(0 if compact else self.recovery.sizeHint().height())

        def needed(*widgets):
            chips = sum(w.sizeHint().width() + 6 for w in widgets if w is not None)
            return self.role_label.sizeHint().width() + chips + 12

        recovery = None if self.recovery.isHidden() else self.recovery
        kind = self.kind_badge if self.kind_badge.text() and recovery is None else None
        status = self.status_badge if self.status_badge.text() else None
        if kind is not None and needed(kind, status, recovery) > available:
            kind = None
        if recovery is not None and status is not None and needed(None, status, recovery) > available:
            status = None
        self.kind_badge.setVisible(kind is not None)
        self.status_badge.setVisible(status is not None)
        self.status_badge.setToolTip(self.kind_badge.text() if kind is None and recovery is None else "")
        self.recovery.setToolTip(self.status_badge.text() if status is None else "")
        wrapped = needed(kind, status, recovery) > available
        if wrapped == getattr(self, '_status_wrapped', None):
            return
        self._status_wrapped = wrapped
        self._top_layout.removeWidget(self._chips)
        if wrapped:
            self._top_layout.addWidget(self._chips, 1, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
        else:
            self._top_layout.addWidget(self._chips, 0, 2, Qt.AlignmentFlag.AlignRight)

    def apply_ui_zoom(self, _factor):
        """Interface zoom changed: re-apply the current profile (glyph size)."""
        profile, self._responsive_profile = self._responsive_profile, None
        self.apply_responsive_profile(profile or "normal")

    def apply_responsive_profile(self, profile: str):
        """Apply one of three bounded density profiles.

        This is deliberately threshold-based. Continuous window resizing does
        not rebuild QSS or repolish the card until the profile actually changes.
        """
        profile = profile if profile in {
            "compact", "normal", "large", "extra_large"
        } else "normal"
        if profile == self._responsive_profile:
            return False

        config = {
            # 2026-10-17 (home C′): compact tiles — the icon sits beside the
            # name; home gives them a fixed height per window tier
            # (home_plan_height), each profile's minimum fits its band.
            "compact": {"margins": (16, 9, 16, 8), "spacing": 4, "icon": 40, "glyph": 19, "gap": 0, "minimum": 130},
            "normal": {"margins": (16, 13, 16, 12), "spacing": 6, "icon": 44, "glyph": 21, "gap": 0, "minimum": 150},
            "large": {"margins": (20, 15, 20, 13), "spacing": 7, "icon": 50, "glyph": 24, "gap": 0, "minimum": 176},
            "extra_large": {"margins": (22, 18, 22, 15), "spacing": 8, "icon": 54, "glyph": 26, "gap": 2, "minimum": 220},
        }[profile]
        self._responsive_profile = profile
        self._responsive_apply_count += 1
        self._glyph_size = config["glyph"]
        self.setProperty("density", profile)
        layout = self.layout()
        from . import ui_zoom
        # Logical px: the interface zoom scales them (ui_zoom).
        ui_zoom.set_layout(layout, config["margins"], config["spacing"])
        self._upper_gap.changeSize(
            0,
            config["gap"],
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        self._apply_identity_balance(profile != "compact")
        ui_zoom.set_size(self.icon_label, fixed_w=config["icon"], fixed_h=config["icon"])
        self.description_label.setVisible(True)  # compact tiles keep their line, on one line
        self.description_label.setWordWrap(profile != "compact")
        self._paint_icon()
        ui_zoom.set_size(self, min_h=config["minimum"])
        self.set_name_px(None)  # the profile's own size first; the plan steps down if needed
        self.style().unpolish(self)
        self.style().polish(self)
        # Qt does not always invalidate child rules that depend on a dynamic
        # property of the parent. Refresh only the responsive labels when
        # the bounded profile changes, never on every resize pixel.
        for label in (self.role_label, self.model_label, self.description_label):
            label.style().unpolish(label)
            label.style().polish(label)
        # Every card owns the same top-aligned model slot. A one-line name
        # never recenters itself and cannot move the rows below it.
        self._sync_model_slot_height()
        self._status_wrapped = None
        self._layout_status()
        layout.invalidate()
        self.update()
        return True

    def _sync_model_slot_height(self) -> None:
        """Keep the name and description slots valid after application QSS changes."""
        parent = self.parentWidget()
        sync = getattr(parent, "_sync_identity_height", None)
        if callable(sync):
            sync()
        else:
            self.model_label.setFixedHeight(self._required_model_slot_height())

    def name_base_px(self) -> int:
        """The profile's name size (before any step down)."""
        if self._name_px is None:
            self.model_label.ensurePolished()
            self._name_base = self.model_label.font().pixelSize()
        return self._name_base

    def name_lines(self, px: int) -> int:
        """How many lines the name takes beside the logo at ``px``."""
        font = QFont(self.model_label.font())
        font.setPixelSize(px)
        metrics = QFontMetrics(font)
        margins = self.layout().contentsMargins()
        beside = self.icon_label.width() + self.change_hint.width() + self._identity_layout.spacing() * 2
        width = max(80, self.width() - margins.left() - margins.right() - beside)
        height = metrics.boundingRect(0, 0, width, 2000, Qt.TextFlag.TextWordWrap, self.model_label.text()).height()
        return max(1, round(height / max(1, metrics.lineSpacing())))

    def set_name_px(self, px) -> None:
        if px == self._name_px:
            return
        self._name_px = px
        self.model_label.setStyleSheet("" if px is None else f"font-size: {px}px;")

    def _required_description_height(self) -> int:
        """Lines the description needs at this width (the plan takes the tallest card)."""
        label = self.description_label
        label.ensurePolished()
        metrics = QFontMetrics(label.font())
        if not label.wordWrap():
            return metrics.lineSpacing()
        margins = self.layout().contentsMargins()
        width = max(80, self.width() - margins.left() - margins.right())
        height = metrics.boundingRect(0, 0, width, 2000, Qt.TextFlag.TextWordWrap, label.text()).height()
        return max(metrics.lineSpacing(), height)

    def _required_model_slot_height(self) -> int:
        self.model_label.ensurePolished()
        metrics = QFontMetrics(self.model_label.font())
        # Long names wrap beside the logo; the slot is as tall as the label
        # needs (the plan widget takes the tallest card).
        margins = self.layout().contentsMargins()
        identity = self._identity_layout
        beside = self.icon_label.width() + self.change_hint.width() + identity.spacing() * 2
        width = max(80, self.width() - margins.left() - margins.right() - beside)
        height = metrics.boundingRect(0, 0, width, 2000, Qt.TextFlag.TextWordWrap, self.model_label.text()).height()
        return max(metrics.lineSpacing(), height)

    def _apply_identity_balance(self, centered: bool):
        centered = bool(centered)
        if centered == self._identity_centered:
            return False
        self._identity_centered = centered
        layout = self.layout()
        self._leading_space.changeSize(
            0,
            0,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Expanding if centered else QSizePolicy.Policy.Fixed,
        )
        # The top line stays on top and the languages at the bottom; the name
        # and its line float between equal flexible spaces.
        layout.setStretch(self._leading_space_index, 1 if centered else 0)
        layout.setStretch(self._body_stretch_index, 1)
        layout.invalidate()
        return True


def model_tile_pixmap(model, size: int, ratio: float = 1.0):
    """A rounded tile with the model's logo (on white) or glyph (on its colour)."""
    from pathlib import Path
    import qtawesome as qta
    from PySide6.QtCore import QRect, QRectF
    from PySide6.QtGui import QPixmap

    pixels = max(1, round(size * ratio))
    tile = QPixmap(pixels, pixels)
    tile.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tile)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    radius = pixels * 0.26
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, pixels, pixels), radius, radius)
    logo = None
    if model.logo_asset:
        # From the install root (like the app icon), whatever the package layout.
        from .main_ui_helpers import APP_ROOT
        file = APP_ROOT / "assets" / "model_logos" / model.logo_asset
        if file.is_file():
            from PySide6.QtGui import QImage
            image = QImage(str(file))
            logo = None if image.isNull() else image
    painter.fillPath(path, QColor("#ffffff" if logo is not None else model.icon_background))
    painter.setClipPath(path)
    if logo is not None:
        inner = round(pixels * 0.78)
        scaled = logo.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        painter.drawImage((pixels - scaled.width()) // 2, (pixels - scaled.height()) // 2, scaled)
    else:
        glyph = round(pixels * 0.5)
        offset = (pixels - glyph) // 2
        qta.icon(model.icon_name, color=model.icon_color).paint(painter, QRect(offset, offset, glyph, glyph))
    painter.end()
    tile.setDevicePixelRatio(ratio)
    return tile


class RecognitionPlanWidget(QWidget):
    """识别方案：三张角色卡横排。"""

    role_requested = Signal(str)          # 点击卡 → 打开工坊该角色
    recovery_requested = Signal(str, str)  # role, action → MainWindow 处理

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.cards: dict[str, RecognitionRoleCard] = {}
        for role in ("primary", "timeline", "review"):
            card = RecognitionRoleCard(role)
            card.clicked.connect(self.role_requested.emit)
            card.recovery_requested.connect(self.recovery_requested.emit)
            layout.addWidget(card, 12 if role == "primary" else 10)
            self.cards[role] = card
        self._responsive_profile = ""

    def apply_density(self, comfortable: bool):
        self._update_responsive_profile(comfortable)

    def _sync_identity_height(self) -> None:
        if not self.cards or getattr(self, "_syncing_identity_height", False):
            return
        self._syncing_identity_height = True
        try:
            self._fit_names()
            height = max(card._required_model_slot_height() for card in self.cards.values())
            for card in self.cards.values():
                card.model_label.setFixedHeight(height)
            # 2026-10-18: equal description slots too, so a one-line line does
            # not move that card's name off the others' row.
            height = max(card._required_description_height() for card in self.cards.values())
            for card in self.cards.values():
                card.description_label.setFixedHeight(height)
        finally:
            self._syncing_identity_height = False

    def _fit_names(self) -> None:
        """A name needing a third line (e.g. the Japanese stage name in a
        narrow window) steps all three names down together, to at most 0.6 of the size."""
        cards = list(self.cards.values())
        base = cards[0].name_base_px()
        if base <= 0:
            return
        chosen = None
        for scale in (1.0, 0.86, 0.76, 0.68, 0.6):
            size = round(base * scale)
            if all(card.name_lines(size) <= 2 for card in cards):
                chosen = None if scale == 1.0 else size
                break
            chosen = size
        for card in cards:
            card.set_name_px(chosen)

    def retranslate(self, language: str | None = None):
        for card in self.cards.values():
            card.retranslate(language)
        # The bound texts change after this call; size the slots afterwards.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._sync_identity_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_profile()

    def _update_responsive_profile(self, comfortable: bool | None = None):
        layout = self.layout()
        spacing = layout.spacing() if layout is not None else 10
        calculated_width = max(0, (self.width() - spacing * 2) // 3)
        card_widths = [card.width() for card in self.cards.values() if card.width() > 0]
        available_width = min(card_widths) if card_widths else calculated_width
        # During a resize event child geometries can still describe the
        # previous layout pass.  The calculated width is the actual per-card
        # allocation for the new size, so use the smaller value.
        if calculated_width > 0:
            available_width = min(available_width, calculated_width) if available_width else calculated_width
        card_heights = [card.height() for card in self.cards.values() if card.height() > 0]
        available_height = min(card_heights) if card_heights else self.height()
        available_height = min(available_height, self.height())
        # Thresholds are in 100% pixels: at a larger interface zoom the cards
        # take the profile of a correspondingly smaller window.
        from .ui_zoom import logical
        available_width, available_height = logical(available_width), logical(available_height)

        if available_height < 150 or available_width < 175:
            profile = "compact"
        elif available_height < 180 or available_width < 250:
            profile = "normal"
        elif available_height < 240 or available_width < 300:
            profile = "large"
        else:
            profile = "extra_large"
        if available_height <= 0:
            profile = "normal" if comfortable else "compact"
        if profile == self._responsive_profile:
            return False
        self._responsive_profile = profile
        for card in self.cards.values():
            card.apply_responsive_profile(profile)
        return True
