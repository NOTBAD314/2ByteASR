"""The home page AI card and the frosted lock over 内容与术语 (2026-10-22, design B).

User (10-22): 「AI 智能断句」 drives many features and must stand out; while no
AI is connected the AI card and 内容与术语 take another colour (blue-grey,
not the first draft's sand), only the way to set it up stays readable, and
everything else is grey under frosted glass. Once connected both return to
the page's own colours.

``HomeAiCard`` replaces the one-line ``SettingTile`` row. It keeps the tile's
small surface (``clicked``, ``set_summary``, ``apply_density``, ``title_label``,
``summary_label``, ``icon_label``, ``chevron``) so ``setting_tiles["ai"]``
callers keep working. ``FrostOverlay`` covers a widget with a grey, blurred
picture of it and one line saying what unlocks it; clicking it asks for setup.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..design.presentation import button_role
from ..design.themed_icons import install_themed_icon
from ..design.home_qss import AI_LOCK_HUE, ai_lock_palette
from ..design.ui_widgets import AnimatedButton
from ..i18n import bind_text
from . import ui_zoom
from .home_widgets import MarkedPill
from .main_ui_helpers import _active_theme_definition

# feature_gate() answers plus the running test (ai_connection_record).
READY, OFF, NO_KEY, UNTESTED, FAILED, TESTING = "ready", "off", "no_key", "untested", "failed", "testing"

STATE_CHIP = {READY: "已连接", NO_KEY: "未连接", UNTESTED: "还没测试", FAILED: "测试没通过",
              OFF: "已关闭", TESTING: "正在测试…"}
SUMMARY = {
    NO_KEY: "选一家服务、贴上 Key 就能用（推荐 DeepSeek）。没连也能开始：这批先用本地规则断句。",
    UNTESTED: "Key 已经填好，测一次连接就能用。测好之前这批先用本地规则断句。",
    FAILED: "上次测试没通过：检查 Key 或换一家服务再试。连好之前这批先用本地规则断句。",
    OFF: "AI 已关闭，这批用本地规则断句。打开后能按意思断句、校对错字和翻译字幕。",
    TESTING: "正在用已保存的服务和 Key 测试连接…",
}
# The locked 内容与术语 (user, 10-23, design G = canvas F2 + F3): a big lock, one
# heading and a button on the left, then the three things that wait for the AI,
# all on a blue-grey frosted panel under which nothing can be read.
FROST_NOTE = {
    OFF: "打开 AI 才能用",
}
FROST_NOTE_DEFAULT = "连上 AI 才能用"
FROST_SUB = "游戏名也是连上后再填"
FROST_BUTTON = {OFF: "打开 AI"}
FROST_BUTTON_DEFAULT = "连接 AI"
# Use lines of at most seven characters: a third of the band is narrow (10-23).
FROST_FEATURES = (
    ("术语库校对", "fa5s.book", "人名术语都写对"),
    ("联网补充核验", "fa5s.globe", "生词上网查一遍"),
    ("翻译字幕", "fa5s.language", "双语或只看译文"),
)


@dataclass(frozen=True)
class AiCardView:
    """What the card shows: the gate state and, once ready, who does the work."""
    state: str
    service: str = ""
    model: str = ""
    tested_at: str = ""
    polish_on: bool = True
    group_on: bool = True

    @property
    def locked(self) -> bool:
        return self.state != READY


class HomeAiCard(QFrame):
    """The fourth card under the recognition plan (role line, state, icon, name, one plain line,
    the features it powers and one action). Locked states show only the way to set it up."""

    clicked = Signal(bool)
    toggled = Signal(bool)   # SettingTile surface; the card never toggles
    connect_requested = Signal()
    test_requested = Signal()
    settings_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeAiCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind_text(self, 'AI 智能断句', property='accessibleName')
        self._view = AiCardView(NO_KEY)
        self._compact = False
        self._pressed = False
        self._detail = ""

        outer = self._outer = QVBoxLayout(self)
        # The band's own margins, like a model card (no inner frame since 10-23).
        outer.setContentsMargins(18, 14, 18, 16)
        outer.setSpacing(6)
        self.role_label = QLabel("AI 文字处理")
        self.role_label.setObjectName("homeAiRole")
        outer.addWidget(self.role_label)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.icon_label = QLabel()
        self.icon_label.setObjectName("homeAiIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(54, 54)
        body.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.title_label = QLabel("AI 智能断句")
        self.title_label.setObjectName("homeAiTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        title_row.addWidget(self.title_label)
        self.state_chip = MarkedPill(mark="dot")   # 2026-10-23 (design A): a pill with a dot
        self.state_chip.setObjectName("homeAiState")
        title_row.addWidget(self.state_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        text.addLayout(title_row)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("homeAiSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text.addWidget(self.summary_label)
        self.feature_row = QWidget()
        self.feature_row.setObjectName("homeAiFeatures")
        features = QHBoxLayout(self.feature_row)
        features.setContentsMargins(0, 4, 0, 0)
        features.setSpacing(6)
        self.features: dict[str, QLabel] = {}
        for key in ("group", "polish", "terms", "translate"):
            chip = MarkedPill(mark="fa5s.check")
            chip.setObjectName("homeAiFeature")
            features.addWidget(chip)
            self.features[key] = chip
        features.addStretch(1)
        text.addWidget(self.feature_row)
        body.addLayout(text, 1)

        actions = QVBoxLayout()
        actions.setSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.connect_button = AnimatedButton("连接 AI")
        self.connect_button.setObjectName("homeAiPrimary")
        button_role(self.connect_button, "primary", icon="fa5s.plug")
        self.connect_button.clicked.connect(self.connect_requested.emit)
        self.test_button = AnimatedButton("测试连接")
        self.test_button.setObjectName("homeAiPrimary")
        button_role(self.test_button, "primary", icon="fa5s.plug")
        bind_text(self.test_button, '用已保存的服务和 Key 测试一次；通过后才能用翻译和术语库校对', property='toolTip')
        self.test_button.clicked.connect(self.test_requested.emit)
        self.settings_button = AnimatedButton("AI 设置")
        self.settings_button.setObjectName("homeAiSettings")
        install_themed_icon(self.settings_button, "fa5s.cog", "zone_ai")
        self.settings_button.setProperty("flexibleWidth", True)   # its icon and weight decide the width
        self.settings_button.clicked.connect(self.settings_requested.emit)
        for button in (self.connect_button, self.test_button, self.settings_button):
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            buttons.addWidget(button)
        actions.addLayout(buttons)
        self.help_button = AnimatedButton("API Key 是什么？")
        self.help_button.setObjectName("linkButton")
        install_themed_icon(self.help_button, "fa5s.question-circle", "accent")
        self.help_button.clicked.connect(self.help_requested.emit)
        actions.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignRight)
        body.addLayout(actions)
        outer.addLayout(body)

        # SettingTile surface: the chevron is gone in this card.
        self.chevron = QLabel(self)
        self.chevron.hide()
        for child in (self.role_label, self.icon_label, self.title_label, self.state_chip,
                      self.summary_label, self.feature_row, *self.features.values()):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.set_view(self._view)

    # ---- SettingTile surface -------------------------------------------------
    def set_summary(self, text: str) -> None:
        """The saved/draft detail line from ``_refresh_ai_summary``: kept as the hover text."""
        self._detail = str(text or "")
        self.setToolTip(self._detail)

    def apply_density(self, comfortable: bool) -> None:  # width tiers do not change this card
        return None

    def isChecked(self) -> bool:
        return False

    def setChecked(self, _checked: bool) -> None:
        return None

    # ---- state ---------------------------------------------------------------
    @property
    def view(self) -> AiCardView:
        return self._view

    def set_compact(self, compact: bool) -> None:
        """Short windows (home tier 0): no role line and no feature row, a smaller icon."""
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.set_view(self._view)

    def set_view(self, view: AiCardView) -> None:
        self._view = view
        locked = view.locked
        self.setProperty("aiLock", locked)
        self.state_chip.setProperty("state", "ready" if view.state == READY else
                                    "warn" if view.state == FAILED else "lock")
        bind_text(self.state_chip, STATE_CHIP.get(view.state, "未连接"))
        if locked:
            bind_text(self.title_label, 'AI 智能断句')
            bind_text(self.summary_label, SUMMARY.get(view.state, SUMMARY[NO_KEY]))
        else:
            name = view.service or "AI"
            if view.model:
                bind_text(self.title_label, '{service} · {model}', service=name, model=view.model)
            else:
                bind_text(self.title_label, '{service} · 默认模型', service=name)
            if view.tested_at:
                bind_text(self.summary_label, '{time} 测试通过 · 下面这些都由它负责', time=view.tested_at)
            else:
                bind_text(self.summary_label, '测试通过 · 下面这些都由它负责')
        self._set_feature("group", view.group_on, '按意思断句', '断句：本地规则')
        self._set_feature("polish", view.polish_on, '字幕校对', '字幕校对：已关闭')
        self._set_feature("terms", True, '术语库校对', '')
        self._set_feature("translate", True, '翻译字幕', '')
        self.role_label.setVisible(not self._compact)
        self.feature_row.setVisible(not locked and not self._compact)
        self.connect_button.setVisible(view.state in (NO_KEY, OFF))
        bind_text(self.connect_button, '打开 AI' if view.state == OFF else '连接 AI')
        self.test_button.setVisible(view.state in (UNTESTED, FAILED, TESTING))
        self.test_button.setEnabled(view.state != TESTING)
        bind_text(self.test_button, {FAILED: '重新测试', TESTING: '正在测试…'}.get(view.state, '测试连接'))
        self.settings_button.setVisible(view.state in (READY, UNTESTED, FAILED, TESTING))
        self.help_button.setVisible(view.state == NO_KEY)
        size = 44 if self._compact else 54
        self.icon_label.setFixedSize(ui_zoom.px(size), ui_zoom.px(size))
        self.refresh_theme()
        for widget in (self, self.state_chip, *self.features.values()):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _set_feature(self, key: str, on: bool, on_text: str, off_text: str) -> None:
        chip = self.features[key]
        chip.setProperty("on", bool(on))
        chip.set_mark("fa5s.check" if on else "fa5s.minus")
        bind_text(chip, on_text if on or not off_text else off_text)

    def refresh_theme(self) -> None:
        import qtawesome as qta
        theme = _active_theme_definition()
        locked = self._view.locked
        color = ai_lock_palette(theme)["title"] if locked else theme.text_on_accent
        glyph = 20 if self._compact else 24
        self.icon_label.setPixmap(qta.icon("fa5s.project-diagram", color=color).pixmap(QSize(glyph, glyph)))

    # ---- whole-card click and keyboard ----------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(False)
        self._pressed = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.hasFocus():
            self.clicked.emit(False)
            return
        super().keyPressEvent(event)


class LockTile(QWidget):
    """A filled accent square with a white lock in a soft ring (canvas F3)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeFrostLock")
        ui_zoom.set_size(self, fixed_w=60, fixed_h=60)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event):
        import qtawesome as qta
        theme = _active_theme_definition()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect())
        ring = QColor(theme.accent)
        ring.setAlphaF(0.20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ring)
        painter.drawRoundedRect(outer, outer.width() * 0.3, outer.height() * 0.3)
        inset = outer.width() * 0.1
        inner = outer.adjusted(inset, inset, -inset, -inset)
        painter.setBrush(QColor(theme.accent))
        painter.drawRoundedRect(inner, inner.width() * 0.27, inner.height() * 0.27)
        side = round(inner.width() * 0.46)
        icon = qta.icon("fa5s.lock", color=theme.text_on_accent).pixmap(QSize(side, side))
        painter.drawPixmap(round(inner.center().x() - side / 2), round(inner.center().y() - side / 2), icon)
        painter.end()


class FrostOverlay(QWidget):
    """The locked 内容与术语: a blurred, blue-grey picture of ``target`` under the lock,
    a heading, 「连接 AI」 and the three features that wait for the AI. A click
    anywhere (or the button) asks for setup.

    The picture is taken outside paint events (``QWidget.grab`` renders the
    target synchronously) and kept until the target changes size or the owner
    calls ``refresh``. ``QGraphicsBlurEffect`` is not used: it re-renders the
    whole subtree off-screen on every repaint and clashes with child effects.
    """

    activated = Signal()

    def __init__(self, target: QWidget, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("homeFrost")
        self._target = target
        self._picture: QPixmap | None = None
        self._pending = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)
        self.lock = LockTile()
        layout.addWidget(self.lock, 0, Qt.AlignmentFlag.AlignVCenter)
        lead = QVBoxLayout()
        lead.setSpacing(4)
        lead.addStretch(1)
        self.note = QLabel()            # the heading
        self.note.setObjectName("homeFrostNote")
        self.sub = QLabel()
        self.sub.setObjectName("homeFrostSub")
        self.sub.setWordWrap(True)
        bind_text(self.sub, FROST_SUB)
        self.button = AnimatedButton(FROST_BUTTON_DEFAULT)
        self.button.setObjectName("homeFrostButton")
        button_role(self.button, "primary")
        install_themed_icon(self.button, "fa5s.plug", "on_accent")
        self.button.clicked.connect(self.activated.emit)
        for label in (self.note, self.sub):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            lead.addWidget(label)
        lead.addSpacing(4)
        lead.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        lead.addStretch(1)
        layout.addLayout(lead, 3)
        layout.addSpacing(6)
        self.tiles: list[QFrame] = []
        for name, icon, use in FROST_FEATURES:
            tile = QFrame()
            tile.setObjectName("homeFrostTile")
            tile.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row = QHBoxLayout(tile)
            row.setContentsMargins(12, 10, 12, 10)
            row.setSpacing(10)
            mark = QLabel()
            mark.setObjectName("homeFrostTileIcon")
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ui_zoom.set_size(mark, fixed_w=34, fixed_h=34)
            mark.setProperty("icon", icon)
            words = QVBoxLayout()
            words.setSpacing(3)
            title = QHBoxLayout()
            title.setSpacing(6)
            label = QLabel()
            label.setObjectName("homeFrostTileName")
            label.setWordWrap(True)
            bind_text(label, name)
            small = QLabel()
            small.setObjectName("homeFrostTileLock")
            title.addWidget(label, 1)     # the whole width: no break inside a name
            title.addWidget(small, 0, Qt.AlignmentFlag.AlignTop)
            note = QLabel()
            note.setObjectName("homeFrostTileUse")
            note.setWordWrap(True)
            bind_text(note, use)
            words.addStretch(1)            # name and use line together, level with the icon
            words.addLayout(title)
            words.addWidget(note)
            words.addStretch(1)
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addLayout(words, 1)
            tile.mark, tile.label, tile.small, tile.note = mark, label, small, note
            layout.addWidget(tile, 4)
            self.tiles.append(tile)
        self.set_gate(NO_KEY)
        target.installEventFilter(self)
        self.hide()

    def set_message(self, text: str) -> None:
        bind_text(self.note, text)
        bind_text(self, text, property='accessibleName')

    def set_gate(self, gate: str) -> None:
        """Heading and button for this lock (AI off reads 「打开 AI」)."""
        self.set_message(FROST_NOTE.get(gate, FROST_NOTE_DEFAULT))
        bind_text(self.button, FROST_BUTTON.get(gate, FROST_BUTTON_DEFAULT))

    def _paint_icons(self) -> None:
        import qtawesome as qta
        theme = _active_theme_definition()
        lock = ai_lock_palette(theme)
        side, small = ui_zoom.px(16), ui_zoom.px(11)
        for tile in self.tiles:
            tile.mark.setPixmap(qta.icon(tile.mark.property("icon"), color=lock["title"]).pixmap(QSize(side, side)))
            tile.small.setPixmap(qta.icon("fa5s.lock", color=theme.accent_text).pixmap(QSize(small, small)))
        self.lock.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # A short band (the compact home page) keeps the names and the heading.
        roomy = self.height() >= ui_zoom.px(112)
        self.sub.setVisible(roomy)
        for tile in self.tiles:
            tile.note.setVisible(self.height() >= ui_zoom.px(84))

    def set_active(self, active: bool) -> None:
        """Cover (or uncover) the target; the picture is retaken when it first shows."""
        if active:
            self.sync_geometry()
            self.raise_()
            if self.isHidden():
                self.show()
        elif not self.isHidden():
            self.hide()
            self._picture = None

    def sync_geometry(self) -> None:
        if self._target.parentWidget() is self.parentWidget():
            self.setGeometry(self._target.geometry())

    def refresh(self) -> None:
        """Take a new picture of the target soon (after the current event)."""
        self._paint_icons()
        if self.isHidden() or self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self, self._take_picture)

    def _take_picture(self) -> None:
        self._pending = False
        if self.isHidden() or self._target.width() <= 0 or self._target.height() <= 0:
            return
        grab = self._target.grab()
        if grab.isNull():
            return
        ratio = grab.devicePixelRatio()
        # The columns are drawn on a transparent widget: lay them on the band's
        # colour first, or the clear pixels turn black in the grey picture.
        base = QImage(grab.size(), QImage.Format.Format_ARGB32_Premultiplied)
        base.fill(QColor(ai_lock_palette(_active_theme_definition())["band"]))
        painter = QPainter(base)
        painter.drawPixmap(0, 0, grab)
        painter.end()
        image = base.convertToFormat(QImage.Format.Format_Grayscale8)
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        width, height = image.width(), image.height()
        # Down and up again with smooth scaling: a cheap, even blur, strong
        # enough that the words underneath cannot be read (user, 10-23).
        step = max(4, round(9 * ratio))
        small = image.scaled(max(1, width // step), max(1, height // step),
                             Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        blurred = small.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        picture = QPixmap.fromImage(blurred)
        picture.setDevicePixelRatio(ratio)
        self._picture = picture
        self.update()

    def eventFilter(self, watched, event):
        if watched is self._target and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.sync_geometry()
            self.refresh()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def paintEvent(self, _event):
        from ..design.ui_theme import blend_hex
        theme = _active_theme_definition()
        lock = ai_lock_palette(theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = ui_zoom.px(12)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)
        if self._picture is not None:
            painter.drawPixmap(self.rect(), self._picture)
        # Blue-grey frosted glass, lighter where the lock is (user: no red-blue gradient).
        light = theme.is_light
        start = QColor(blend_hex(lock["frost"], AI_LOCK_HUE, 0.30 if light else 0.22))
        end = QColor(lock["frost"])
        start.setAlphaF(0.86 if light else 0.84)
        end.setAlphaF(0.90 if light else 0.88)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(1.0, end)
        painter.fillPath(path, gradient)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(lock["edge"]), 1))
        painter.drawPath(path)
        painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)
