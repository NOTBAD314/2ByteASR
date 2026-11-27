"""AI transcript rough cut in Clip Assistant, as three steps (2026-11-26, draft A 三步走).

User (2026-11-26): the 文稿粗剪 buttons were too many and too mixed to understand. From the drafts
(``tmp/cutpanel-terms-drafts-20261126``) the user picked A:

  ① 挑剪法 — three cards, any of them: AI 找废话 (with its 3-step tightness inside the card),
    只留高光, 剪背景人声 (game background by default, the ▾ picks a speaker). One button,
    「标记要剪的句子」, marks the subtitles; nothing is cut yet.
  ② 试听剪口 — one chip per reason (重录废稿 12, 口癖水话 5 …); a click holds that kind back for now.
    ▶ plays every seam with 1.5 s either side.
  ③ 剪掉 — the one filled button, 「剪掉 N 句 · −X 秒」, and 「全部还原」.

「联动剪画面」 is a small switch at the top right, 「删字幕也剪画面」. Only one filled (primary)
button shows at a time: 「标记要剪的句子」 until there are marks, then 「剪掉」.

The signals and the methods ``studio_video_flow`` calls are the ones of the old bar.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..design.soft_qss import control_icons, soft_tokens
from ..design.studio_theme import create_studio_menu
from ..design.theme_manager import theme_key
from ..design.typography import PLAYFUL_FONT_STACK, TITLE_FONT_STACK, UI_FONT_STACK
from ..design.ui_theme import blend_hex, theme_definition
from ..i18n import tr
from .ai_rough_cut import (
    BACKGROUND_SPEAKER_IDS,
    REASON_BACKGROUND,
    REASON_DEAD_AIR,
    REASON_FILLER,
    REASON_MANUAL,
    REASON_NON_HIGHLIGHT,
    REASON_RETAKE,
    REASON_SILENCE,
    TIGHTNESS_PRESETS,
    active_cut_cue_ids,
    is_linked_video_cut_enabled,
    plan_project_rough_cut,
    reason_summary,
)

# The reason chips' dots (the draft's colours; pale enough to read on both themes).
REASON_COLORS = {
    REASON_RETAKE: "#f3866b",
    REASON_FILLER: "#e9b65b",
    REASON_DEAD_AIR: "#c79bf2",
    REASON_SILENCE: "#86b4f7",
    REASON_NON_HIGHLIGHT: "#9aa0a6",
    REASON_BACKGROUND: "#69cf9b",
    REASON_MANUAL: "#d48aa7",
}
WIDE_CARDS_AT = 430          # the panel is at least this wide: the three cards side by side
STEP_GUTTER = 34             # the numbered circles' column
STEP_DOT = 24


def _theme():
    return theme_definition(theme_key())


def _icon_qicon(name: str, color: str):
    from ..design.themed_icons import _prime_platform_font_fallback
    import qtawesome as qta
    _prime_platform_font_fallback()
    return qta.icon(name, color=color)


def _icon(name: str, color: str, size: int = 16):
    return _icon_qicon(name, color).pixmap(QSize(size, size))


class _Step(QWidget):
    """One numbered step: its circle and the rail to the next one are painted in the gutter."""

    def __init__(self, number: int, title: str, *, last: bool = False, parent=None):
        super().__init__(parent)
        self.number = number
        self.last = last
        self.state = "off"                    # off, on, done
        outer = QVBoxLayout(self)
        outer.setContentsMargins(STEP_GUTTER, 0, 0, 0 if last else 12)
        outer.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.title = QLabel(tr(title))
        self.title.setObjectName("roughCutStepTitle")
        head.addWidget(self.title)
        self.sub = QLabel("")
        self.sub.setObjectName("roughCutStepSub")
        head.addWidget(self.sub, 1)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addLayout(self.body)

    def set_state(self, state: str, sub: str = "") -> None:
        self.state = state
        self.sub.setText(sub)
        self.title.setProperty("dim", state == "off")
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre_x = STEP_DOT / 2 + 1
        top = max(0, (self.title.height() - STEP_DOT) // 2)
        if not self.last:
            painter.setPen(QPen(QColor(t.border), 2))
            painter.drawLine(int(centre_x), top + STEP_DOT + 3, int(centre_x), self.height())
        dot = QRectF(1, top, STEP_DOT, STEP_DOT)
        if self.state == "off":
            painter.setPen(QPen(QColor(t.border_strong), 1.6))
            painter.setBrush(QColor(t.panel))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t.accent))
        painter.drawEllipse(dot)
        if self.state == "done":
            pen = QPen(QColor(t.text_on_accent or "#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                       Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x, y = dot.left(), dot.top()
            painter.drawPolyline([QPointF(x + 7, y + 12.5), QPointF(x + 10.5, y + 16), QPointF(x + 17, y + 8.5)])
        else:
            painter.setPen(QColor(t.text_on_accent or "#ffffff") if self.state == "on" else QColor(t.text_muted))
            font = painter.font()
            font.setFamilies(["Source Han Sans SC Heavy", "Source Han Sans SC Medium"])
            font.setPixelSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(dot, Qt.AlignmentFlag.AlignCenter, str(self.number))
        painter.end()


class _MethodCard(QFrame):
    """A way to find what to cut; a click picks it or not (any number of them)."""

    toggled = Signal(bool)

    def __init__(self, icon: str, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setObjectName("roughCutCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.icon_name = icon
        self.picked = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 9, 10, 10)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.icon = QLabel()
        self.icon.setObjectName("roughCutCardIcon")
        top.addWidget(self.icon)
        self.title = QLabel(tr(title))
        self.title.setObjectName("roughCutCardTitle")
        top.addWidget(self.title, 1)
        self.check = QLabel()
        self.check.setObjectName("roughCutCardCheck")
        self.check.setFixedSize(18, 18)
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.check)
        lay.addLayout(top)
        self.desc = QLabel(tr(desc))
        self.desc.setObjectName("roughCutCardDesc")
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        self.extra = QVBoxLayout()
        self.extra.setContentsMargins(0, 2, 0, 0)
        lay.addLayout(self.extra)
        self.lay = lay

    def set_picked(self, picked: bool, *, emit: bool = False) -> None:
        self.picked = bool(picked)
        for widget in (self, self.check):
            widget.setProperty("picked", self.picked)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.refresh_icons()
        if emit:
            self.toggled.emit(self.picked)

    def refresh_icons(self) -> None:
        t = _theme()
        self.icon.setPixmap(_icon(self.icon_name, t.accent_text if self.picked else t.text_secondary, 15))
        self.check.setPixmap(_icon("fa5s.check", t.text_on_accent or "#ffffff", 10) if self.picked else _icon(
            "fa5s.check", t.panel, 10))

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.set_picked(not self.picked, emit=True)
        super().mouseReleaseEvent(event)


class RoughCutControlBar(QWidget):
    """文稿粗剪 in three steps inside Clip Assistant."""

    linked_cut_toggled = Signal(bool)
    ai_analyze_requested = Signal(str)       # tightness key
    keep_highlights_requested = Signal()
    cut_background_requested = Signal(str)   # "" = default GAME_BACKGROUND, else speaker_id
    seam_preview_toggled = Signal(bool)
    apply_cut_requested = Signal()
    clear_marks_requested = Signal()
    fold_changed = Signal(bool)
    reason_toggled = Signal(str, bool)       # 2026-11-26: a reason chip: hold that kind back / bring it back

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("roughCutBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._project: Any = None
        self._busy = False
        self._seam_active = False
        self._tightness = "tight"
        self._bg_target = ""
        self._folded = False
        self._fold_by_user = None          # the user's own choice wins over auto_fold
        self._marked = 0
        self._cut_ms = 0
        self._wide = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(10)

        # Head: the title, how much is marked, and the small 「删字幕也剪画面」 switch.
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.title_label = QLabel(tr("文稿粗剪"))
        self.title_label.setObjectName("roughCutTitle")
        head.addWidget(self.title_label)
        self.count_pill = QLabel("")
        self.count_pill.setObjectName("roughCutCountPill")
        self.count_pill.setVisible(False)
        head.addWidget(self.count_pill)
        head.addStretch(1)
        self.linked_toggle = QCheckBox(tr("删字幕也剪画面"))
        self.linked_toggle.setObjectName("roughCutLinkedToggle")
        self.linked_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.linked_toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.linked_toggle.setToolTip(
            tr(
                "默认关闭（删字幕不动视频）。\n"
                "开启后，在字幕列表删句会标灰并划删除线预览，播放时自动跳过；\n"
                "满意后再点「剪掉」一次性切画面（Ctrl+Z 可撤销）。"
            )
        )
        self.linked_toggle.toggled.connect(self._on_linked_toggled)
        head.addWidget(self.linked_toggle)
        # Folds the steps away to this row (the clip candidates below need the room).
        self.fold_button = QToolButton()
        self.fold_button.setObjectName("roughCutFold")
        self.fold_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fold_button.setAutoRaise(True)
        self.fold_button.setFixedSize(26, 26)
        self.fold_button.clicked.connect(lambda: self.set_folded(not self._folded, by_user=True))
        head.addWidget(self.fold_button)
        root.addLayout(head)

        self.body_scroll = QScrollArea()
        self.body_scroll.setObjectName("roughCutScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setMinimumHeight(76)
        self.body = QWidget()
        self.body.setObjectName("roughCutBody")
        self.body_scroll.setWidget(self.body)
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(10)
        root.addWidget(self.body_scroll, 1)
        steps = QVBoxLayout()
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(0)

        # ① 挑剪法
        self.step_pick = _Step(1, "挑剪法")
        self.card_ai = _MethodCard("fa5s.magic", "AI 找废话", "重录、口癖、冷场，按松紧挑")
        self.card_hl = _MethodCard("fa5s.star", "只留高光", "高光前后各留 2 秒")
        self.card_bg = _MethodCard("fa5s.microphone-alt-slash", "剪背景人声", "默认剪游戏背景声")
        self.card_ai.set_picked(True)
        self.card_ai.setToolTip(tr("复用已有文字 AI，找出重录废稿、口癖水话与冷场过渡，只标删除线不直接切画面"))
        self.card_hl.setToolTip(tr("保留高光区间及前后各 2 秒铺垫，将高光外的其余句子标灰待剪"))
        self.card_bg.setToolTip(tr("标灰游戏背景声；点 ▾ 可选择任意说话人"))
        # The tightness lives inside the AI card.
        self.tightness_track = QFrame()
        self.tightness_track.setObjectName("roughCutTrack")
        track_row = QHBoxLayout(self.tightness_track)
        track_row.setContentsMargins(2, 2, 2, 2)
        track_row.setSpacing(2)
        self.tightness_group = QButtonGroup(self)
        self.tightness_group.setExclusive(True)
        self.tightness_buttons: dict[str, QPushButton] = {}
        for idx, (key, label, tooltip) in enumerate(TIGHTNESS_PRESETS):
            btn = QPushButton(tr(label)[:2])
            btn.setObjectName("roughCutSegBtn")
            btn.setCheckable(True)
            btn.setChecked(key == self._tightness)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setToolTip(f"{tr(label)}：{tr(tooltip)}")
            self.tightness_group.addButton(btn, idx)
            self.tightness_buttons[key] = btn
            track_row.addWidget(btn, 1)
        self.tightness_group.idClicked.connect(self._on_tightness_clicked)
        self.card_ai.extra.addWidget(self.tightness_track)
        # Who counts as background: the ▾ on the background card.
        self.background_button = QToolButton()
        self.background_button.setObjectName("roughCutSpeakerBtn")
        self.background_button.setText(tr("游戏背景声"))
        self.background_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.background_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.background_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.background_button.setToolTip(tr("选择要剪掉谁的声音"))
        self._speaker_menu = create_studio_menu(self.background_button)
        self._speaker_menu.aboutToShow.connect(self._populate_speaker_menu)
        self.background_button.setMenu(self._speaker_menu)
        self.card_bg.extra.addWidget(self.background_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.cards = (self.card_ai, self.card_hl, self.card_bg)
        for card in self.cards:
            card.toggled.connect(lambda _picked: self._sync_buttons())
        self.card_grid = QGridLayout()
        self.card_grid.setContentsMargins(0, 0, 0, 0)
        self.card_grid.setHorizontalSpacing(8)
        self.card_grid.setVerticalSpacing(8)
        self.step_pick.body.addLayout(self.card_grid)
        self.ai_button = QPushButton(tr("标记要剪的句子"))
        self.ai_button.setObjectName("roughCutPrimaryBtn")
        self.ai_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ai_button.setToolTip(tr("按上面挑的剪法在字幕上划删除线；还不会动画面"))
        self.ai_button.clicked.connect(self._mark)
        self.step_pick.body.addWidget(self.ai_button)
        self.highlights_button = self.ai_button    # one button now runs every picked method
        steps.addWidget(self.step_pick)

        # ② 试听剪口
        self.step_listen = _Step(2, "试听剪口")
        self.reason_host = QWidget()
        self.reason_row = _FlowRow(self.reason_host)
        self.reason_chips: dict[str, QPushButton] = {}
        self.step_listen.body.addWidget(self.reason_host)
        seam_bar = QFrame()
        seam_bar.setObjectName("roughCutSeamBar")
        seam_row = QHBoxLayout(seam_bar)
        seam_row.setContentsMargins(6, 5, 10, 5)
        seam_row.setSpacing(8)
        self.seam_button = QPushButton()
        self.seam_button.setObjectName("roughCutPlayBtn")
        self.seam_button.setCheckable(True)
        self.seam_button.setEnabled(False)
        self.seam_button.setFixedSize(30, 30)
        self.seam_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seam_button.setToolTip(tr("只连播每个剪口前后各 1.5 秒；听出不顺手点一下该句标签即可还原"))
        self.seam_button.clicked.connect(self._on_seam_clicked)
        seam_row.addWidget(self.seam_button)
        self.seam_label = QLabel(tr("还没有剪口"))
        self.seam_label.setObjectName("roughCutSeamText")
        self.seam_label.setWordWrap(True)
        seam_row.addWidget(self.seam_label, 1)
        self.step_listen.body.addWidget(seam_bar)
        steps.addWidget(self.step_listen)

        # ③ 剪掉
        self.step_cut = _Step(3, "剪掉", last=True)
        cut_row = QHBoxLayout()
        cut_row.setContentsMargins(0, 0, 0, 0)
        cut_row.setSpacing(8)
        self.apply_button = QPushButton(tr("剪掉"))
        self.apply_button.setObjectName("roughCutCutBtn")
        self.apply_button.setEnabled(False)
        self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button.setToolTip(tr("将所有待剪标记一次性波纹裁剪（保留 150ms 呼吸余量，Ctrl+Z 一次撤销）"))
        self.apply_button.clicked.connect(self.apply_cut_requested.emit)
        cut_row.addWidget(self.apply_button, 1)
        self.clear_button = QPushButton(tr("全部还原"))
        self.clear_button.setObjectName("roughCutGhostBtn")
        self.clear_button.setEnabled(False)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setToolTip(tr("清除全部待剪删除线，还原所有字幕"))
        self.clear_button.clicked.connect(self.clear_marks_requested.emit)
        cut_row.addWidget(self.clear_button)
        self.step_cut.body.addLayout(cut_row)
        steps.addWidget(self.step_cut)
        body_lay.addLayout(steps)

        # Actionable inline note (hidden when idle).
        self.inline_note = QLabel("")
        self.inline_note.setObjectName("roughCutNote")
        self.inline_note.setWordWrap(True)
        self.inline_note.hide()
        body_lay.addWidget(self.inline_note)

        self.divider = QFrame(self)
        self.divider.setObjectName("roughCutDivider")
        self.divider.setFixedHeight(1)
        root.addWidget(self.divider)

        self._place_cards(False)
        self.refresh_theme_palette()
        self.refresh_from_project(None)

    # ------------------------------------------------------------------ layout
    def _place_cards(self, wide: bool) -> None:
        if wide == self._wide:
            return
        self._wide = wide
        for card in self.cards:
            self.card_grid.removeWidget(card)
        for index, card in enumerate(self.cards):
            if wide:
                self.card_grid.addWidget(card, 0, index)
            else:
                self.card_grid.addWidget(card, index, 0)
        for col in range(3):
            self.card_grid.setColumnStretch(col, 1 if wide else (1 if col == 0 else 0))
        # Side by side the tightness steps are two characters each; stacked there is room for the words.
        for key, label, _tip in TIGHTNESS_PRESETS:
            self.tightness_buttons[key].setText(tr(label)[:2] if wide else tr(label))

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        self._place_cards(event.size().width() >= WIDE_CARDS_AT)
        super().resizeEvent(event)

    # ------------------------------------------------------------------ folding
    def set_folded(self, folded: bool, *, by_user: bool = False) -> None:
        self._folded = bool(folded)
        if by_user:
            self._fold_by_user = self._folded
        self.body_scroll.setVisible(not self._folded)
        t = _theme()
        self.fold_button.setIcon(_icon_qicon("fa5s.chevron-down" if self._folded else "fa5s.chevron-up", t.text_secondary))
        self.fold_button.setIconSize(QSize(11, 11))
        self.fold_button.setToolTip(tr("展开文稿粗剪") if self._folded else tr("收起文稿粗剪"))
        self.fold_changed.emit(self._folded)

    def auto_fold(self, folded: bool) -> None:
        """Fold while the clip candidates are listed, unless the user opened or closed it."""
        if self._fold_by_user is None and bool(folded) != self._folded:
            self.set_folded(folded)

    def is_folded(self) -> bool:
        return self._folded

    # ------------------------------------------------------------------ state
    def tightness(self) -> str:
        return self._tightness

    def set_tightness(self, key: str) -> None:
        if key not in self.tightness_buttons:
            return
        self._tightness = key
        btn = self.tightness_buttons[key]
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)

    def _on_tightness_clicked(self, idx: int) -> None:
        if 0 <= idx < len(TIGHTNESS_PRESETS):
            self._tightness = TIGHTNESS_PRESETS[idx][0]
            if not self.card_ai.picked:
                self.card_ai.set_picked(True)
                self._sync_buttons()

    def _on_linked_toggled(self, checked: bool) -> None:
        self.linked_cut_toggled.emit(bool(checked))

    def _mark(self) -> None:
        """Run every picked method: each only marks subtitles (the AI one in the background)."""
        if self.card_hl.picked:
            self.keep_highlights_requested.emit()
        if self.card_bg.picked:
            self.cut_background_requested.emit(self._bg_target)
        if self.card_ai.picked:
            self.ai_analyze_requested.emit(self._tightness)

    def _on_seam_clicked(self, checked: bool) -> None:
        self.set_seam_preview_active(bool(checked))
        self.seam_preview_toggled.emit(bool(checked))

    def set_seam_preview_active(self, active: bool) -> None:
        self._seam_active = bool(active)
        self.seam_button.blockSignals(True)
        self.seam_button.setChecked(self._seam_active)
        self.seam_button.blockSignals(False)
        self._refresh_seam_bar()

    def _refresh_seam_bar(self) -> None:
        t = _theme()
        has = self._marked > 0
        color = (t.text_on_accent or "#ffffff") if has else t.disabled
        self.seam_button.setIcon(_icon("fa5s.stop" if self._seam_active else "fa5s.play", color, 12))
        self.seam_button.setIconSize(QSize(12, 12))
        if self._seam_active:
            text = tr("正在连播剪口…听到不顺，点那句就还原")
        elif has:
            text = tr("连播所有剪口，每个前后 1.5 秒")
        else:
            text = tr("还没有剪口")
        self.seam_label.setText(text)

    def set_busy(self, busy: bool, note: str = "") -> None:
        self._busy = bool(busy)
        self._sync_buttons()
        for btn in self.tightness_buttons.values():
            btn.setEnabled(not self._busy)
        if note:
            self.set_note(note)

    def set_note(self, text: str, *, warn: bool = False) -> None:
        cleaned = " ".join(str(text or "").split()).strip()
        self.inline_note.setProperty("warn", bool(warn))
        self.inline_note.setText(cleaned)
        self.inline_note.setVisible(bool(cleaned))
        self.inline_note.style().unpolish(self.inline_note)
        self.inline_note.style().polish(self.inline_note)

    def set_project(self, project: Any) -> None:
        self._project = project
        self.refresh_from_project(project)

    def refresh_from_project(self, project: Any | None = None) -> None:
        if project is not None:
            self._project = project
        proj = self._project
        has_project = proj is not None

        linked = is_linked_video_cut_enabled(proj)
        self.linked_toggle.blockSignals(True)
        self.linked_toggle.setChecked(linked)
        self.linked_toggle.setEnabled(has_project)
        self.linked_toggle.blockSignals(False)

        marked_ids = active_cut_cue_ids(proj)
        plan = plan_project_rough_cut(proj) if marked_ids else None
        self._marked = len(marked_ids)
        cut_count = len(plan.cut_ranges) if plan is not None else 0
        self._cut_ms = int(plan.total_cut_ms) if plan is not None else 0
        seconds = self._cut_ms / 1000.0

        if self._marked > 0:
            self.count_pill.setText(tr("待剪 {n} 句 · -{s:.1f}s", n=self._marked, s=seconds))
            self.count_pill.setToolTip(
                tr("已标 {n} 句待剪，合并为 {r} 段切口，预计缩短 {s:.1f} 秒", n=self._marked, r=cut_count, s=seconds)
            )
            self.count_pill.show()
            self.apply_button.setText(tr("剪掉 {n} 句 · −{s:.1f} 秒", n=self._marked, s=seconds))
        else:
            self.count_pill.setText("")
            self.count_pill.hide()
            self.apply_button.setText(tr("剪掉"))

        held = reason_summary(proj) if has_project else []
        self._fill_reasons(held)
        any_marks = self._marked > 0 or any(not enabled for _r, _n, enabled in held)
        self.step_pick.set_state("done" if any_marks else "on", tr("可以多选"))
        self.step_listen.set_state("on" if any_marks else "off",
                                   tr("点原因可暂时不剪这类") if any_marks else tr("标记后才会亮"))
        self.step_cut.set_state("on" if self._marked else "off")
        self.seam_button.setEnabled(has_project and (cut_count > 0 or self._seam_active))
        self.apply_button.setEnabled(has_project and cut_count > 0 and not self._busy)
        self.clear_button.setEnabled(has_project and any_marks and not self._busy)
        if cut_count == 0 and self._seam_active:
            self.set_seam_preview_active(False)
        self._sync_buttons()
        self._refresh_seam_bar()

    def _sync_buttons(self) -> None:
        """「标记要剪的句子」 is the filled button until there are marks; then it is 「重新标记」."""
        has_project = self._project is not None
        picked = any(card.picked for card in self.cards)
        for card in self.cards:
            card.setEnabled(has_project and not self._busy)
        self.background_button.setEnabled(has_project and not self._busy)
        if self._busy:
            self.ai_button.setText(tr("正在标记…"))
        else:
            self.ai_button.setText(tr("重新标记") if self._marked else tr("标记要剪的句子"))
        self.ai_button.setObjectName("roughCutTintBtn" if self._marked else "roughCutPrimaryBtn")
        self.ai_button.style().unpolish(self.ai_button)
        self.ai_button.style().polish(self.ai_button)
        self.ai_button.setEnabled(has_project and picked and not self._busy)

    def _fill_reasons(self, rows) -> None:
        for chip in self.reason_chips.values():
            chip.deleteLater()
        self.reason_chips = {}
        self.reason_row.clear()
        t = _theme()
        for reason, count, enabled in rows:
            chip = QPushButton(f"{tr(reason)} {count}")
            chip.setObjectName("roughCutReasonChip")
            chip.setCheckable(True)
            chip.setChecked(enabled)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setIcon(_dot_icon(REASON_COLORS.get(reason, t.accent), enabled, t))
            chip.setIconSize(QSize(8, 8))
            chip.setToolTip(tr("点一下：这类先不剪；再点一下恢复") if enabled else tr("这类先不剪；点一下恢复"))
            chip.toggled.connect(lambda on, value=reason: self.reason_toggled.emit(value, bool(on)))
            self.reason_row.add(chip)
            self.reason_chips[reason] = chip
        self.reason_host.setVisible(bool(rows))

    def _populate_speaker_menu(self) -> None:
        self._speaker_menu.clear()
        proj = self._project
        if proj is None:
            return
        self._speaker_menu.addAction(tr("游戏背景声"), lambda: self._set_bg_target("", tr("游戏背景声")))
        speakers = list(getattr(proj, "speakers", ()) or ())
        extra = [s for s in speakers if str(s.id) not in BACKGROUND_SPEAKER_IDS]
        if extra:
            self._speaker_menu.addSeparator()
            for spk in extra:
                sid = str(spk.id)
                name = str(getattr(spk, "name", "") or sid)
                self._speaker_menu.addAction(
                    tr("剪：{name}", name=name),
                    lambda _checked=False, target=sid, label=name: self._set_bg_target(target, label),
                )

    def _set_bg_target(self, target: str, label: str) -> None:
        self._bg_target = str(target or "")
        self.background_button.setText(label)
        if not self.card_bg.picked:
            self.card_bg.set_picked(True)
            self._sync_buttons()

    def action_labels(self) -> list[str]:
        """The controls' own words (for the <= 6-char contract); counts shown with them are not words."""
        labels = [
            *(btn.text() for btn in self.tightness_buttons.values()),
            *(card.title.text() for card in self.cards),
            self.clear_button.text(),
            tr("剪掉"),
        ]
        return [str(label).strip() for label in labels]

    # ------------------------------------------------------------------ theme
    def refresh_theme_palette(self) -> None:
        t = _theme()
        k = soft_tokens(t)
        icons = control_icons(t)
        pill_bg = blend_hex(t.panel, t.danger, 0.14 if t.is_light else 0.24)
        card_on = blend_hex(t.panel, t.accent, 0.10 if t.is_light else 0.18)
        self.setStyleSheet(
            f"""
            QWidget#roughCutBar {{ background: transparent; border: 0; font-family: {UI_FONT_STACK}; }}
            QLabel#roughCutTitle {{ color: {t.text}; font-family: {PLAYFUL_FONT_STACK}; font-size: 18px;
                background: transparent; border: 0; }}
            QLabel#roughCutCountPill {{ background: {pill_bg}; color: {t.danger}; border: 0; border-radius: 10px;
                padding: 2px 9px; font-family: {TITLE_FONT_STACK}; font-size: 12px; font-weight: 700; }}
            QCheckBox#roughCutLinkedToggle {{ color: {t.text_secondary}; background: transparent; font-size: 13px;
                spacing: 8px; }}
            QCheckBox#roughCutLinkedToggle::indicator {{ width: 36px; height: 20px; border: 0; background: transparent;
                image: url({icons['switch_off']}); }}
            QCheckBox#roughCutLinkedToggle::indicator:checked {{ image: url({icons['switch_on']}); }}
            QLabel#roughCutStepTitle {{ color: {t.text}; font-family: {TITLE_FONT_STACK}; font-size: 15px;
                font-weight: 800; background: transparent; min-height: 26px; }}
            QLabel#roughCutStepTitle[dim="true"] {{ color: {t.text_muted}; }}
            QLabel#roughCutStepSub {{ color: {t.text_muted}; font-size: 12px; background: transparent; }}
            QFrame#roughCutCard {{ background: {k.fill}; border: 1.5px solid transparent; border-radius: 12px; }}
            QFrame#roughCutCard:hover {{ background: {k.fill_hover}; }}
            QFrame#roughCutCard[picked="true"] {{ background: {card_on}; border-color: {t.accent}; }}
            QFrame#roughCutCard:disabled {{ background: {k.fill_disabled}; }}
            QLabel#roughCutCardTitle {{ color: {t.text}; font-family: {TITLE_FONT_STACK}; font-size: 14px;
                font-weight: 700; background: transparent; }}
            QLabel#roughCutCardDesc {{ color: {t.text_secondary}; font-size: 12px; background: transparent; }}
            QLabel#roughCutCardIcon {{ background: transparent; }}
            QLabel#roughCutCardCheck {{ background: {t.panel}; border: 1.5px solid {t.border_strong}; border-radius: 9px; }}
            QLabel#roughCutCardCheck[picked="true"] {{ background: {t.accent}; border-color: {t.accent}; }}
            QFrame#roughCutTrack {{ background: {k.raised}; border: 0; border-radius: 9px; }}
            QPushButton#roughCutSegBtn {{ background: transparent; color: {t.text_secondary}; border: 0;
                border-radius: 7px; min-height: 24px; max-height: 24px; padding: 0 4px; font-size: 12px; }}
            QPushButton#roughCutSegBtn:hover {{ color: {t.text}; background: {k.fill_hover}; }}
            QPushButton#roughCutSegBtn:checked {{ background: {t.accent}; color: {t.text_on_accent};
                font-family: {TITLE_FONT_STACK}; font-weight: 700; }}
            QToolButton#roughCutSpeakerBtn {{ background: {k.raised}; color: {t.text}; border: 0; border-radius: 8px;
                min-height: 24px; padding: 0 22px 0 9px; font-size: 12px; }}
            QToolButton#roughCutSpeakerBtn::menu-indicator {{ image: url({icons['chevron_muted']});
                subcontrol-origin: padding; subcontrol-position: center right; right: 6px; width: 10px; height: 10px; }}
            QPushButton#roughCutPrimaryBtn, QPushButton#roughCutTintBtn, QPushButton#roughCutCutBtn,
            QPushButton#roughCutGhostBtn {{ border: 0; border-radius: 10px; min-height: 36px; max-height: 36px;
                padding: 0 14px; font-family: {TITLE_FONT_STACK}; font-size: 14px; font-weight: 700; }}
            QPushButton#roughCutPrimaryBtn {{ background: {t.accent}; color: {t.text_on_accent}; }}
            QPushButton#roughCutPrimaryBtn:hover {{ background: {t.accent_hover}; }}
            QPushButton#roughCutPrimaryBtn:disabled {{ background: {k.primary_disabled}; color: {t.text_on_accent}; }}
            QPushButton#roughCutTintBtn {{ background: {k.chip}; color: {t.accent_text}; }}
            QPushButton#roughCutTintBtn:hover {{ background: {k.chip_hover}; }}
            QPushButton#roughCutTintBtn:disabled {{ background: {k.fill_disabled}; color: {t.disabled}; }}
            QPushButton#roughCutCutBtn {{ background: {t.accent}; color: {t.text_on_accent}; }}
            QPushButton#roughCutCutBtn:hover {{ background: {t.accent_hover}; }}
            QPushButton#roughCutCutBtn:disabled {{ background: {k.fill_disabled}; color: {t.disabled}; }}
            QPushButton#roughCutGhostBtn {{ background: transparent; color: {t.text_secondary}; }}
            QPushButton#roughCutGhostBtn:hover {{ background: {k.fill}; color: {t.text}; }}
            QPushButton#roughCutGhostBtn:disabled {{ color: {t.disabled}; }}
            QPushButton#roughCutReasonChip {{ background: {k.fill}; color: {t.text}; border: 1px solid {t.border};
                border-radius: 13px; min-height: 26px; max-height: 26px; padding: 0 10px; font-size: 12px; }}
            QPushButton#roughCutReasonChip:hover {{ background: {k.fill_hover}; }}
            QPushButton#roughCutReasonChip:!checked {{ background: transparent; color: {t.text_muted};
                border-style: dashed; }}
            QFrame#roughCutSeamBar {{ background: {k.fill}; border: 0; border-radius: 12px; }}
            QPushButton#roughCutPlayBtn {{ background: {t.accent}; border: 0; border-radius: 15px; }}
            QPushButton#roughCutPlayBtn:hover {{ background: {t.accent_hover}; }}
            QPushButton#roughCutPlayBtn:disabled {{ background: {k.fill_disabled}; }}
            QLabel#roughCutSeamText {{ color: {t.text_secondary}; font-size: 12px; background: transparent; }}
            QLabel#roughCutNote {{ color: {t.text_secondary}; background: transparent; border: 0; font-size: 12px;
                padding: 1px 2px; }}
            QLabel#roughCutNote[warn="true"] {{ color: {t.warning}; }}
            QFrame#roughCutDivider {{ background: {t.hairline}; border: 0; }}
            QToolButton#roughCutFold {{ background: transparent; border: 0; border-radius: 13px; }}
            QToolButton#roughCutFold:hover {{ background: {k.fill}; }}
            """
        )
        for card in self.cards:
            card.refresh_icons()
        self.set_folded(self._folded)
        if self._project is not None or self._marked:
            self._fill_reasons(reason_summary(self._project) if self._project is not None else [])
        self._refresh_seam_bar()


def _dot_icon(color: str, enabled: bool, t):
    from PySide6.QtGui import QIcon, QPixmap
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color if enabled else t.disabled))
    painter.drawEllipse(QRectF(1, 1, 14, 14))
    painter.end()
    return QIcon(pixmap)


class _FlowRow:
    """Chips that wrap onto more lines inside ``host`` (a QWidget)."""

    def __init__(self, host: QWidget):
        from .studio_speaker_board import FlowLayout
        self.layout = FlowLayout(host, 6)

    def clear(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)

    def add(self, widget: QWidget) -> None:
        self.layout.addWidget(widget)



__all__ = ["REASON_COLORS", "RoughCutControlBar"]
