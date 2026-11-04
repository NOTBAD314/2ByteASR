"""The guide column of the AI settings dialog (2026-10-22, design D2 refined).

User (10-22): a beginner first needs 「申请教程」, so it carries the accent
colour while there is no key; 「测试连接」 turns pink only once a key is in;
nothing may sit in a row of a few words or leave empty space. The left column
says what to do now and ticks off the three steps (get a key, paste it, test
it). The editor's own 「申请教程」 button is lent to this column
(``EndpointEditor.host_guide``), so the tutorial and the tests keep pointing at
the same widget.

Once the test passes (user, 10-23: the connected column was empty and dull, a
beginner should feel it worked) the column turns into a success card: a large
check that pops in after a fresh test, the four things the AI now does as
tiles, and the one step left (save, then drop a video on the home page).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..i18n import bind_text
from . import ui_zoom
from .main_ui_helpers import _active_theme_definition

# Guide states (ui._refresh_ai_dialog_state): the AI gate as the dialog sees it.
NO_KEY, UNTESTED, FAILED, READY, OFF = "no_key", "untested", "failed", "ready", "off"

STEPS = ("跟着教程注册、复制 Key", "贴到右边", "测试连接")
GUIDE = {
    NO_KEY: ("第一次用？", "先拿到一把 API Key", "服务商给你的一串密码，App 用它替你调用 AI。"),
    UNTESTED: ("Key 已贴上", "下一步：测试连接", "点右边的「测试连接」，几秒就知道这把 Key 能不能用。"),
    FAILED: ("没连上", "测试没通过", "看看 Key 有没有贴全、余额够不够，或换一家服务再试。"),
    OFF: ("AI 已关闭", "按意思断句和校对都关着", "在「更多选项」里打开它们，就能用 AI 断句、校对和翻译。"),
}
# What a connected AI does (key, name, icon, what it does for you, tooltip).
# Four-character names: a tile half the column wide wrapped 按意思断句 mid-word
# (user, 10-23); the line under each name says what the user gets.
FEATURES = (
    ("group", "AI 断句", "fa5s.cut", "按意思切长句", "长句按意思切成好读的字幕"),
    ("polish", "字幕校对", "fa5s.pen", "改错字统一专名", "改错字、统一专名"),
    ("terms", "术语校对", "fa5s.book", "游戏名词不写错", "术语库校对、联网补充核验"),
    ("translate", "翻译字幕", "fa5s.language", "一键出双语字幕", "在字幕编辑器里一键翻译"),
)


class NoteLabel(QLabel):
    """A note beside a switch or a field (2026-10-25): one line while there is
    room, wrapped when there is not. As one fixed line, the notes in 更多选项
    made the form wider than the dialog and its right side was cut off (user,
    0.8.5); a plain wrapping label would break even when the line fits."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def sizeHint(self):
        margins = self.contentsMargins()
        width = (self.fontMetrics().horizontalAdvance(self.text()) + margins.left() + margins.right()
                 + 2 * self.margin() + 2)
        return QSize(width, self.heightForWidth(width))


class YieldingBox(QWidget):
    """Asks for no more width than its minimum (2026-10-25). Beside 「让 AI 负责」
    it holds the model and address group: a row short of room otherwise takes
    the shortfall from both columns alike and the notes on the left wrap
    while this side still has room to spare."""

    def sizeHint(self):
        return QSize(self.minimumSizeHint().width(), super().sizeHint().height())


def keep_label_width(widget: QWidget) -> QWidget:
    """A row may not squeeze ``widget`` below its size hint (a switch's label was cut, 2026-10-25)."""
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Minimum)
    widget.setSizePolicy(policy)
    return widget


class SuccessBadge(QWidget):
    """A filled check in a soft ring; ``scale`` drives the pop-in."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiWinBadge")
        ui_zoom.set_size(self, fixed_w=46, fixed_h=46)
        self.scale = 1.0

    def paintEvent(self, _event):
        theme = _active_theme_definition()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.translate(center)
        painter.scale(self.scale, self.scale)
        ring = QColor(theme.success)
        ring.setAlphaF(0.18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ring)
        painter.drawEllipse(QRectF(-side / 2, -side / 2, side, side))
        inner = side * 0.74
        painter.setBrush(QColor(theme.success))
        painter.drawEllipse(QRectF(-inner / 2, -inner / 2, inner, inner))
        path = QPainterPath(QPointF(-inner * 0.22, inner * 0.01))
        path.lineTo(QPointF(-inner * 0.05, inner * 0.17))
        path.lineTo(QPointF(inner * 0.24, -inner * 0.15))
        pen = QPen(QColor(theme.text_on_accent), max(2.0, inner * 0.09))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class AiGuidePanel(QFrame):
    """What to do now (eyebrow, heading, one line), the three steps and the lent
    「申请教程」 button; once connected, the success card (``win_box``). 「API Key
    是什么？」 sits beside the key box (``EndpointEditor.key_help_button``)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiGuide")
        self.setProperty("state", NO_KEY)
        ui_zoom.set_size(self, fixed_w=270)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(0)

        self.steps_box = QWidget()
        self.steps_box.setObjectName("aiGuideSteps")
        steps = QVBoxLayout(self.steps_box)
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(8)
        self.eyebrow = QLabel()
        self.eyebrow.setObjectName("aiGuideEyebrow")
        self.heading = QLabel()
        self.heading.setObjectName("aiGuideHeading")
        self.heading.setWordWrap(True)
        self.text = QLabel()
        self.text.setObjectName("aiGuideText")
        self.text.setWordWrap(True)
        for widget in (self.eyebrow, self.heading, self.text):
            steps.addWidget(widget)
        self.rows: list[tuple[QLabel, QLabel]] = []
        rows = QVBoxLayout()
        rows.setSpacing(6)
        rows.setContentsMargins(0, 2, 0, 2)
        for _ in range(3):
            row = QHBoxLayout()
            row.setSpacing(9)
            badge = QLabel()
            badge.setObjectName("aiGuideBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ui_zoom.set_size(badge, fixed_w=20, fixed_h=20)
            line = QLabel()
            line.setObjectName("aiGuideStep")
            line.setWordWrap(True)
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(line, 1)
            rows.addLayout(row)
            self.rows.append((badge, line))
        steps.addLayout(rows)
        # The column is as tall as the success card; the spare height goes above
        # the button, so 「申请教程」 sits level with 取消 / 保存设置 on the right.
        steps.addStretch(1)
        # The editor's 「申请教程」 button is lent here (EndpointEditor.host_guide).
        self.guide_slot = QVBoxLayout()
        self.guide_slot.setContentsMargins(0, 2, 0, 0)
        steps.addLayout(self.guide_slot)
        layout.addWidget(self.steps_box, 1)

        self.win_box = self._build_win_box()
        self.win_box.hide()
        layout.addWidget(self.win_box, 1)
        self._celebration = None
        self.set_state(NO_KEY)

    def _build_win_box(self) -> QWidget:
        box = QWidget()
        box.setObjectName("aiWin")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.win_badge = SuccessBadge()
        head.addWidget(self.win_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.win_eyebrow = QLabel()
        self.win_eyebrow.setObjectName("aiWinEyebrow")
        self.win_heading = QLabel()
        self.win_heading.setObjectName("aiWinHeading")
        self.win_heading.setWordWrap(True)
        self.win_meta = QLabel()
        self.win_meta.setObjectName("aiWinMeta")
        # The column has a fixed width: longer languages wrap here instead of
        # being cut off (2026-10-25: Spanish / Russian test times, French caption).
        self.win_meta.setWordWrap(True)
        titles.addWidget(self.win_eyebrow)
        titles.addWidget(self.win_heading)
        titles.addWidget(self.win_meta)
        head.addLayout(titles, 1)
        layout.addLayout(head)
        layout.addSpacing(2)
        self.win_caption = QLabel()
        self.win_caption.setObjectName("aiWinCaption")
        self.win_caption.setWordWrap(True)
        layout.addWidget(self.win_caption)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.win_tiles: dict[str, QFrame] = {}
        for index, (key, name, icon, use, tip) in enumerate(FEATURES):
            tile = QFrame()
            tile.setObjectName("aiWinTile")
            tile.setProperty("on", True)
            column = QVBoxLayout(tile)
            column.setContentsMargins(9, 7, 8, 7)
            column.setSpacing(4)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            mark = QLabel()
            mark.setObjectName("aiWinTileIcon")
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ui_zoom.set_size(mark, fixed_w=24, fixed_h=24)
            mark.setProperty("icon", icon)
            label = QLabel()
            label.setObjectName("aiWinTileName")
            label.setWordWrap(True)   # other languages' names are longer than four characters
            bind_text(label, name)
            bind_text(tile, tip, property="toolTip")
            row.addWidget(mark)
            row.addWidget(label, 1)
            column.addLayout(row)
            note = QLabel()
            note.setObjectName("aiWinTileUse")
            note.setWordWrap(True)
            bind_text(note, use)
            column.addWidget(note)
            tile.mark, tile.label, tile.note = mark, label, note
            grid.addWidget(tile, index // 2, index % 2)
            self.win_tiles[key] = tile
        layout.addLayout(grid)
        layout.addStretch(1)
        self.win_next = QFrame()
        self.win_next.setObjectName("aiWinNext")
        next_row = QHBoxLayout(self.win_next)
        next_row.setContentsMargins(0, 10, 0, 0)
        next_row.setSpacing(8)
        self.win_next_icon = QLabel()
        self.win_next_icon.setObjectName("aiWinNextIcon")
        ui_zoom.set_size(self.win_next_icon, fixed_w=16, fixed_h=18)
        self.win_next_text = QLabel()
        self.win_next_text.setObjectName("aiWinNextText")
        self.win_next_text.setWordWrap(True)
        bind_text(self.win_next_text, '保存后回首页，拖进视频就能用')
        next_row.addWidget(self.win_next_icon, 0, Qt.AlignmentFlag.AlignTop)
        next_row.addWidget(self.win_next_text, 1)
        layout.addWidget(self.win_next)
        return box

    # One height in every state (user, 10-23: 测试连接 / 保存设置 must not move or
    # change size between states, only their colour): the column is as tall as
    # its tallest state, so the dialog keeps its size while the user goes from
    # no key to connected.
    def _content_height(self, width: int) -> int:
        margins = self.layout().contentsMargins()
        inner = max(1, width - margins.left() - margins.right())

        def height(box):
            layout = box.layout()
            if layout.hasHeightForWidth():
                return layout.totalHeightForWidth(inner)
            return layout.totalSizeHint().height()
        return margins.top() + margins.bottom() + max(height(self.steps_box), height(self.win_box))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._content_height(width)

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(hint.width(), self._content_height(self.width() if self.width() > 0 else hint.width()))

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(hint.width(), self._content_height(self.width() if self.width() > 0 else hint.width()))

    def set_state(self, state: str, *, service: str = "", detail: str = "",
                  features: dict | None = None, fresh: bool = False) -> None:
        """``service`` names the connected service; ``detail`` says when the test
        passed; ``features`` says which of FEATURES are switched on; ``fresh`` (a test
        just passed) plays the pop-in once."""
        import qtawesome as qta
        previous = self.property("state")
        self.setProperty("state", state)
        theme = _active_theme_definition()
        ready = state == READY
        self.steps_box.setVisible(not ready)
        self.win_box.setVisible(ready)
        if ready:
            bind_text(self.win_eyebrow, '连接成功')
            bind_text(self.win_heading, '{service} 接好了', service=service or "AI")
            self.win_meta.setText(detail)
            self.win_meta.setVisible(bool(detail))
            on = {key: bool((features or {}).get(key, True)) for key, *_ in FEATURES}
            bind_text(self.win_caption, 'AI 现在能帮你做这 {count} 件事', count=sum(on.values()))
            side = ui_zoom.px(13)
            for key, tile in self.win_tiles.items():
                tile.setProperty("on", on[key])
                color = theme.success if on[key] else theme.text_muted
                tile.mark.setPixmap(qta.icon(tile.mark.property("icon"), color=color).pixmap(QSize(side, side)))
            arrow = ui_zoom.px(13)
            self.win_next_icon.setPixmap(qta.icon("fa5s.arrow-right", color=theme.success).pixmap(QSize(arrow, arrow)))
            if fresh and previous != READY:
                self._celebrate()
        else:
            self._stop_celebration()
            eyebrow, heading, text = GUIDE.get(state, GUIDE[NO_KEY])
            bind_text(self.eyebrow, eyebrow)
            bind_text(self.heading, heading)
            bind_text(self.text, text)
            # Which step is current: get a key, (paste it,) test it.
            current = 0 if state in (NO_KEY, OFF) else 2
            done = ui_zoom.px(12)
            for index, ((badge, line), text) in enumerate(zip(self.rows, STEPS)):
                bind_text(line, text)
                if index < current:
                    badge.setProperty("step", "done")
                    badge.setPixmap(qta.icon("fa5s.check", color=theme.text_on_accent).pixmap(QSize(done, done)))
                else:
                    badge.setProperty("step", "now" if index == current else "next")
                    badge.clear()
                    badge.setText(str(index + 1))
                line.setProperty("step", "next" if index > current else "")
        for widget in (self, self.eyebrow, *[part for row in self.rows for part in row], *self.win_tiles.values(),
                       *[tile.note for tile in self.win_tiles.values()], *[tile.label for tile in self.win_tiles.values()]):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.win_badge.update()

    def _celebrate(self) -> None:
        """The check pops in, then the tiles light up one by one (skipped when the
        app asks for less motion)."""
        self._stop_celebration()
        app = QApplication.instance()
        if app is not None and app.property("reduceMotion"):
            return
        tiles = list(self.win_tiles.values())
        effects = []
        for tile in tiles:
            effect = QGraphicsOpacityEffect(tile)
            effect.setOpacity(0.0)
            tile.setGraphicsEffect(effect)
            effects.append(effect)
        total = 760.0
        pop = QEasingCurve(QEasingCurve.Type.OutBack)
        pop.setOvershoot(2.2)

        def step(value):
            elapsed = float(value) * total
            self.win_badge.scale = 0.35 + 0.65 * pop.valueForProgress(min(1.0, elapsed / 380.0))
            self.win_badge.update()
            for index, effect in enumerate(effects):
                effect.setOpacity(max(0.0, min(1.0, (elapsed - 240.0 - index * 90.0) / 220.0)))

        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(int(total))
        animation.valueChanged.connect(step)
        animation.finished.connect(self._stop_celebration)
        self._celebration = animation
        step(0.0)
        animation.start()

    def _stop_celebration(self) -> None:
        animation, self._celebration = self._celebration, None
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        self.win_badge.scale = 1.0
        self.win_badge.update()
        for tile in self.win_tiles.values():
            if tile.graphicsEffect() is not None:
                tile.setGraphicsEffect(None)
