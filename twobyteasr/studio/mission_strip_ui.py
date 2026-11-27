"""Left-tab Studio ``专名与方案`` panel + Action-First ``MicroUpgradePill``.

2026-11-25 v5 refinement:
  - Single-page, zero redundant status banners (no ``finishPipelineBanner``).
  - No box-in-box: whitespace + 1px thin dividers + borderless tonal surfaces.
  - Short labels <= 6 chars with full explanations in hover ``toolTip``:
      - Header: ``专名与方案`` + ``⚙ 自动开关``
      - Section 1: ``本片重复错词`` (``替换并加入`` / ``跳过``)
      - Optional 1-line link: ``待确认 N 处 → 字幕列表``
      - Section 2: ``常用方案`` (inline 3 <=6-char auto switches + ``加入常用方案``)
"""
from __future__ import annotations

from html import escape
from typing import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..app.micro_upgrade import MicroUpgradeOffer
from ..design.soft_qss import control_icons, soft_tokens
from ..design.theme_manager import theme_key
from ..design.typography import PLAYFUL_FONT_STACK, TITLE_FONT_STACK, UI_FONT_STACK
from ..design.ui_theme import blend_hex, theme_definition
from ..i18n import tr
from ..projects.auto_pipeline import AutoPipelineConfig
from ..projects.mission_plan import MissionItem, MissionPlan


def _theme():
    return theme_definition(theme_key())


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("finishDivider")
    line.setFixedHeight(1)
    return line


def _panel_qss(t) -> str:
    k = soft_tokens(t)
    icon = control_icons(t)
    card_bg = blend_hex(t.surface, t.text, 0.045 if t.is_light else 0.065)
    scheme_bg = blend_hex(t.surface, t.accent, 0.13 if t.is_light else 0.22)
    scheme_edge = blend_hex(t.border, t.accent, 0.40)
    stamp_on = blend_hex(t.surface, t.accent, 0.18 if t.is_light else 0.30)
    warn_bg = blend_hex(t.surface, t.warning, 0.14 if t.is_light else 0.22)
    ok_bg = blend_hex(t.surface, t.success, 0.14 if t.is_light else 0.22)
    pill_bg = blend_hex(t.surface, t.danger, 0.14 if t.is_light else 0.24)
    return f"""
    QFrame#finishChecklistPanel {{ background: {t.surface}; border: 0; }}
    QFrame#finishChecklistPanel QLabel {{ background: transparent; color: {t.text}; font-family: {UI_FONT_STACK}; }}
    QFrame#finishChecklistPanel QCheckBox {{ background: transparent; color: {t.text}; font-family: {UI_FONT_STACK};
        font-size: 13px; spacing: 7px; }}
    QFrame#finishChecklistPanel QCheckBox::indicator {{ width: 17px; height: 17px; border: 0; border-radius: 5px;
        background: {k.fill_strong}; image: none; }}
    QFrame#finishChecklistPanel QCheckBox::indicator:hover {{ background: {blend_hex(k.fill_strong, t.text, 0.08)}; }}
    QFrame#finishChecklistPanel QCheckBox::indicator:checked {{ background: {t.accent}; image: url({icon['check']}); }}
    QFrame#finishChecklistPanel QScrollArea, QWidget#finishCardsViewport, QWidget#finishCardsHost {{
        background: transparent; border: 0; }}
    QFrame#finishChecklistPanel QFrame#finishDivider {{ background: {t.border}; border: 0; }}
    QFrame#finishChecklistPanel QLabel#finishPanelTitle {{ font-family: {PLAYFUL_FONT_STACK}; font-size: 18px; }}
    QFrame#finishChecklistPanel QLabel#finishSectionHead {{ font-family: {TITLE_FONT_STACK}; font-size: 15px;
        font-weight: 800; }}
    QFrame#finishChecklistPanel QLabel#finishCountPill {{ background: {pill_bg}; color: {t.danger}; border-radius: 10px;
        padding: 1px 8px; font-family: {TITLE_FONT_STACK}; font-size: 12px; font-weight: 700; }}
    QFrame#finishChecklistPanel QLabel#finishSub {{ color: {t.text_secondary}; font-size: 13px; }}
    QFrame#finishChecklistPanel QFrame#finishFeedCard {{ background: {card_bg}; border: 0; border-radius: 14px; }}
    QFrame#finishChecklistPanel QFrame#finishFeedCard[done="true"] QLabel {{ color: {t.text_muted}; }}
    QFrame#finishChecklistPanel QLabel#finishKicker {{ color: {t.text_muted}; font-family: {TITLE_FONT_STACK};
        font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
    QFrame#finishChecklistPanel QLabel#finishWord {{ font-family: {TITLE_FONT_STACK}; font-size: 15px; font-weight: 800; }}
    QFrame#finishChecklistPanel QLabel#finishDonePill {{ background: {ok_bg}; color: {t.success}; border-radius: 10px;
        padding: 2px 9px; font-family: {TITLE_FONT_STACK}; font-size: 12px; font-weight: 700; }}
    QFrame#finishChecklistPanel QLabel#finishEmptyTick {{ background: {ok_bg}; border-radius: 13px; }}
    QFrame#finishChecklistPanel QFrame#finishEmpty {{ background: {card_bg}; border: 0; border-radius: 14px; }}
    QFrame#finishChecklistPanel QPushButton#finishCardPrimary, QFrame#finishChecklistPanel QPushButton#finishCardSecondary,
    QFrame#finishChecklistPanel QPushButton#finishCardTint {{ border: 0; border-radius: 9px; min-height: 30px;
        padding: 0 12px; font-family: {TITLE_FONT_STACK}; font-size: 13px; font-weight: 700; }}
    QFrame#finishChecklistPanel QPushButton#finishCardPrimary {{ background: {t.accent}; color: {t.text_on_accent}; }}
    QFrame#finishChecklistPanel QPushButton#finishCardPrimary:hover {{ background: {t.accent_hover}; }}
    QFrame#finishChecklistPanel QPushButton#finishCardSecondary {{ background: transparent; color: {t.text_secondary}; }}
    QFrame#finishChecklistPanel QPushButton#finishCardSecondary:hover {{ background: {k.fill}; color: {t.text}; }}
    QFrame#finishChecklistPanel QPushButton#finishCardTint {{ background: {k.chip}; color: {t.accent_text}; }}
    QFrame#finishChecklistPanel QPushButton#finishCardTint:hover {{ background: {k.chip_hover}; }}
    QFrame#finishChecklistPanel QPushButton#finishLinkBtn {{ background: {warn_bg}; color: {t.warning}; border: 0;
        border-radius: 12px; padding: 9px 12px; text-align: left; font-family: {TITLE_FONT_STACK}; font-size: 13px;
        font-weight: 700; }}
    QFrame#finishChecklistPanel QPushButton#finishLinkBtn:hover {{ background: {blend_hex(warn_bg, t.warning, 0.10)}; }}
    QFrame#finishChecklistPanel QLabel#finishTag {{ background: {k.fill}; color: {t.text_muted}; border-radius: 6px;
        padding: 1px 6px; font-family: {TITLE_FONT_STACK}; font-size: 11px; font-weight: 700; }}
    QFrame#finishChecklistPanel QFrame#finishSchemeCard {{ background: {scheme_bg}; border: 1px solid {scheme_edge};
        border-radius: 18px; }}
    QFrame#finishChecklistPanel QLabel#finishSchemeKicker {{ color: {t.accent_text}; font-family: {TITLE_FONT_STACK};
        font-size: 11px; font-weight: 800; letter-spacing: 1px; }}
    QFrame#finishChecklistPanel QLabel#finishSchemeName {{ font-family: {PLAYFUL_FONT_STACK}; font-size: 19px; }}
    QFrame#finishChecklistPanel QLabel#finishAutoBadge {{ color: {t.text_muted}; font-size: 11px; }}
    QFrame#finishChecklistPanel QLabel#finishAutoBadge[active="true"] {{ color: {t.accent_text}; }}
    QFrame#finishChecklistPanel QCheckBox#finishAutoSwitch::indicator {{ width: 36px; height: 20px; border: 0;
        border-radius: 0; background: transparent; image: url({icon['switch_off']}); }}
    QFrame#finishChecklistPanel QCheckBox#finishAutoSwitch::indicator:checked {{ image: url({icon['switch_on']}); }}
    QFrame#finishChecklistPanel QPushButton#finishStamp {{ background: transparent; color: {t.text_muted};
        border: 1.5px dashed {t.border_strong}; border-radius: 12px; min-height: 56px; padding: 0; }}
    QFrame#finishChecklistPanel QLabel#finishStampCount {{ color: {t.text}; font-family: {TITLE_FONT_STACK};
        font-size: 17px; font-weight: 800; }}
    QFrame#finishChecklistPanel QLabel#finishStampLabel {{ color: {t.text_muted}; font-family: {TITLE_FONT_STACK};
        font-size: 12px; font-weight: 700; }}
    QFrame#finishChecklistPanel QLabel#finishStampCount[on="true"],
    QFrame#finishChecklistPanel QLabel#finishStampLabel[on="true"] {{ color: {t.accent_text}; }}
    QFrame#finishChecklistPanel QPushButton#finishStamp:hover {{ background: {blend_hex(scheme_bg, t.text, 0.04)}; }}
    QFrame#finishChecklistPanel QPushButton#finishStamp:checked {{ background: {stamp_on}; color: {t.accent_text};
        border: 1.5px solid {t.accent}; }}
    QFrame#finishChecklistPanel QPushButton#finishGear {{ background: transparent; border: 0; border-radius: 13px;
        min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px; }}
    QFrame#finishChecklistPanel QPushButton#finishGear:hover {{ background: {blend_hex(scheme_bg, t.text, 0.08)}; }}
    """


SAVE_TAGS = {
    "term_entry": "新词", "glossary_link": "词库", "cast_add": "人名", "cast_update": "人名",
    "visual": "样式", "break_rule": "断句", "export": "导出", "trust_graduate": "自动改",
}


class FinishChecklistPanel(QFrame):
    """The left 「专名与方案」 tab (2026-11-26, draft B 方案卡).

    User (2026-11-26) picked draft B from ``tmp/cutpanel-terms-drafts-20261126``, with two changes:
    the 常用方案 stamps stand straight (not tilted), and the card sits *below* 「本片要处理」.

      本片要处理 — what this episode still needs: each repeated wrong word is a card
        (「重复错词 · N 处」, 错 → 对, 「改 N 处」 / 「跳过」), 「N 句待确认」 jumps to the subtitle
        list, and new changes can be 「收进方案卡」.
      方案卡 — the series' card: its name, three upright stamps (词库 / 人名 / 样式 with their
        counts; a click switches that part on or off), 「新片自动」 at the top right, and
        「现在套用到本片」 while automatic is off. 「自动开关」 lives in the card now (the ⚙ opens
        the full dialog).
    """

    item_action_requested = Signal(str, object)   # ("apply" | "skip", MissionItem)
    save_to_plan_requested = Signal(list)         # checked items to add to saved scheme
    open_review_requested = Signal()              # switch to 字幕列表 + start review
    open_proofread_requested = Signal()           # jump to AI 词库校对
    open_pipeline_config_requested = Signal()     # open 自动开关 dialog
    pipeline_config_changed = Signal(object)      # AutoPipelineConfig from the card's switches
    apply_now_requested = Signal()                # 「现在套用到本片」

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("finishChecklistPanel")
        self._plan: MissionPlan | None = None
        self._save_items: list[dict] = []
        self._save_checks: list[tuple[QCheckBox, dict]] = []
        self._pipeline_config: AutoPipelineConfig = AutoPipelineConfig()
        self._scheme_counts: dict[str, int] = {}
        self._inline_switches: dict[str, QPushButton] = {}
        self._syncing_switches = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(6)
        self.head_label = QLabel(tr("专名与方案"))
        self.head_label.setObjectName("finishPanelTitle")
        head_row.addWidget(self.head_label, 1)
        root.addLayout(head_row)
        # The full 自动开关 dialog: the ⚙ on the scheme card (kept as an attribute for callers).
        self.pipeline_btn = QPushButton()
        self.pipeline_btn.setObjectName("finishGear")
        self.pipeline_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pipeline_btn.setToolTip(tr("自动开关：设置套常用词库、人名、样式，或立即试跑"))
        self.pipeline_btn.clicked.connect(self.open_pipeline_config_requested.emit)
        self.pipeline_btn.hide()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("finishCardsViewport")
        self.cards_host = QWidget()
        self.cards_host.setObjectName("finishCardsHost")
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 2, 2, 4)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_host)
        root.addWidget(self.scroll, 1)

        self.refresh_theme()

    # ------------------------------------------------------------ building
    def _clear_cards(self) -> None:
        self._save_checks.clear()
        self._inline_switches.clear()
        if self.pipeline_btn.parent() is not self:
            self.pipeline_btn.setParent(self)
            self.pipeline_btn.hide()
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _insert(self, widget: QWidget) -> None:
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, widget)

    def set_plan(
        self,
        plan: MissionPlan | None,
        *,
        save_items: Sequence[dict] = (),
        pipeline_config: AutoPipelineConfig | None = None,
        scheme_counts: dict | None = None,
    ) -> None:
        self._plan = plan
        self._save_items = [dict(x) for x in save_items]
        if pipeline_config is not None:
            self._pipeline_config = pipeline_config
        if scheme_counts is not None:
            self._scheme_counts = {str(k): int(v or 0) for k, v in dict(scheme_counts).items()}
        self._render()

    def _render(self) -> None:
        self._clear_cards()
        plan = self._plan
        if plan is None:
            empty = QLabel(tr("打开工程后将自动列出重复错词与常用方案设置。"))
            empty.setObjectName("finishSub")
            empty.setWordWrap(True)
            self._insert(empty)
            return

        terms_st = plan.station("terms")
        term_items = list(terms_st.items) if terms_st is not None else []
        pending = terms_st.remaining if terms_st is not None else 0

        # 本片要处理
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        title = QLabel(tr("本片要处理"))
        title.setObjectName("finishSectionHead")
        head.addWidget(title)
        if pending > 0:
            cnt = QLabel(str(pending))
            cnt.setObjectName("finishCountPill")
            head.addWidget(cnt)
        head.addStretch(1)
        head_host = QWidget()
        head_host.setLayout(head)
        self._insert(head_host)

        if not term_items and not self._save_items:
            self._insert(self._empty_row())
        for item in term_items:
            self._insert(self._build_term_card(item))
        if plan.review_issue_count > 0:
            jump = QPushButton(tr("{n} 句待确认　去字幕列表 ›", n=plan.review_issue_count))
            jump.setObjectName("finishLinkBtn")
            jump.setCursor(Qt.CursorShape.PointingHandCursor)
            jump.setToolTip(tr("切回字幕列表并进入待确认视图逐句确认"))
            jump.clicked.connect(self.open_review_requested.emit)
            self._insert(jump)
        if self._save_items:
            self._insert(self._build_save_card())

        # The scheme card, below what this episode needs.
        self._insert(_divider())
        self._insert(self._build_scheme_card(plan.series_name))

    def _empty_row(self) -> QFrame:
        row = QFrame()
        row.setObjectName("finishEmpty")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 10, 10, 10)
        lay.setSpacing(10)
        tick = QLabel()
        tick.setObjectName("finishEmptyTick")
        tick.setFixedSize(26, 26)
        tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tick.setPixmap(_icon("fa5s.check", _theme().success, 12))
        lay.addWidget(tick)
        text = QLabel(tr("没有重复错词，也没有新改动"))
        text.setObjectName("finishSub")
        text.setWordWrap(True)
        lay.addWidget(text, 1)
        pbtn = QPushButton(tr("词库校对"))
        pbtn.setObjectName("finishCardTint")
        pbtn.setCursor(Qt.CursorShape.PointingHandCursor)
        pbtn.setToolTip(tr("打开 AI 词库校对，支持随手贴词条"))
        pbtn.clicked.connect(self.open_proofread_requested.emit)
        lay.addWidget(pbtn)
        return row

    def _build_term_card(self, item: MissionItem) -> QFrame:
        t = _theme()
        card = QFrame()
        card.setObjectName("finishFeedCard")
        card.setProperty("done", "true" if item.done else "false")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(8)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        kicker = QLabel(tr("重复错词 · {n} 处", n=item.count))
        kicker.setObjectName("finishKicker")
        text.addWidget(kicker)
        src = str(item.payload.get("from") or "")
        dst = str(item.payload.get("to") or "") or item.title
        word = QLabel()
        word.setObjectName("finishWord")
        word.setTextFormat(Qt.TextFormat.RichText)
        word.setWordWrap(True)
        if src and src != dst and not item.done:
            word.setText(f'<span style="color:{t.danger}; font-weight:500; text-decoration:line-through;">'
                         f'{escape(src)}</span>&nbsp;→&nbsp;<span style="color:{t.success};">{escape(dst)}</span>')
        else:
            word.setText(escape(dst))
        text.addWidget(word)
        lay.addLayout(text, 1)
        if item.done:
            done = QLabel(tr("已改"))
            done.setObjectName("finishDonePill")
            done.setToolTip(tr("已全片替换并加入词库，可 Ctrl+Z 撤回"))
            lay.addWidget(done, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            act = QPushButton(tr("改 {n} 处", n=item.count))
            act.setObjectName("finishCardPrimary")
            act.setCursor(Qt.CursorShape.PointingHandCursor)
            act.setToolTip(tr("一键全片替换 {n} 处并加入词库，可 Ctrl+Z 撤回", n=item.count))
            act.clicked.connect(lambda _c=False, it=item: self.item_action_requested.emit("apply", it))
            lay.addWidget(act, 0, Qt.AlignmentFlag.AlignVCenter)
            skip = QPushButton(tr("跳过"))
            skip.setObjectName("finishCardSecondary")
            skip.setCursor(Qt.CursorShape.PointingHandCursor)
            skip.setToolTip(tr("本片暂不替换此词"))
            skip.clicked.connect(lambda _c=False, it=item: self.item_action_requested.emit("skip", it))
            lay.addWidget(skip, 0, Qt.AlignmentFlag.AlignVCenter)
        return card

    def _build_save_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("finishFeedCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 9, 10, 10)
        lay.setSpacing(5)
        kicker = QLabel(tr("新改动 · 收进方案卡"))
        kicker.setObjectName("finishKicker")
        lay.addWidget(kicker)
        for row in self._save_items:
            line = QHBoxLayout()
            line.setContentsMargins(0, 1, 0, 1)
            line.setSpacing(7)
            cb = QCheckBox("")
            cb.setChecked(bool(row.get("checked", True)))
            cb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            line.addWidget(cb, 0, Qt.AlignmentFlag.AlignTop)
            tag_text = SAVE_TAGS.get(str(row.get("kind") or ""), "")
            if tag_text:
                tag = QLabel(tr(tag_text))
                tag.setObjectName("finishTag")
                line.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
            lbl = QLabel(str(row.get("label") or ""))
            lbl.setObjectName("finishSub")
            lbl.setWordWrap(True)
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            lbl.mousePressEvent = lambda _e, box=cb: box.toggle()
            line.addWidget(lbl, 1)
            lay.addLayout(line)
            self._save_checks.append((cb, row))
        commit = QPushButton(tr("收进方案卡"))
        commit.setObjectName("finishCardTint")
        commit.setCursor(Qt.CursorShape.PointingHandCursor)
        commit.setToolTip(tr("将勾选的新词、说话人或样式保存到常用方案，下次同系列直接套用"))
        commit.clicked.connect(self._emit_save)
        lay.addWidget(commit)
        return card

    def _build_scheme_card(self, series_name: str) -> QFrame:
        cfg = self._pipeline_config
        card = QFrame()
        card.setObjectName("finishSchemeCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        kicker = QLabel(tr("常用方案"))
        kicker.setObjectName("finishSchemeKicker")
        names.addWidget(kicker)
        name = QLabel(series_name or tr("还没有方案"))
        name.setObjectName("finishSchemeName")
        name.setWordWrap(True)
        names.addWidget(name)
        top.addLayout(names, 1)
        auto = QVBoxLayout()
        auto.setContentsMargins(0, 0, 0, 0)
        auto.setSpacing(2)
        badge = QLabel(tr("新片自动") if cfg.enabled else tr("手动套用"))
        badge.setObjectName("finishAutoBadge")
        badge.setProperty("active", "true" if cfg.enabled else "false")
        badge.setAlignment(Qt.AlignmentFlag.AlignRight)
        auto.addWidget(badge)
        switch = QCheckBox("")
        switch.setObjectName("finishAutoSwitch")
        switch.setCursor(Qt.CursorShape.PointingHandCursor)
        switch.setChecked(bool(cfg.enabled))
        switch.setToolTip(tr("开着：新片识别完就自动套用下面亮着的几项；关着：只在你点「现在套用到本片」时套"))
        switch.toggled.connect(self._on_auto_toggled)
        auto.addWidget(switch, 0, Qt.AlignmentFlag.AlignRight)
        top.addLayout(auto)
        self.pipeline_btn.setParent(card)
        self.pipeline_btn.setIcon(_icon_qicon("fa5s.cog", _theme().text_secondary))
        self.pipeline_btn.show()
        top.addWidget(self.pipeline_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        stamps = QHBoxLayout()
        stamps.setContentsMargins(0, 0, 0, 0)
        stamps.setSpacing(7)
        counts = self._scheme_counts
        specs = (
            ("run_glossary", "词库", tr("{n} 本", n=counts.get("glossary", 0)), cfg.run_glossary,
             tr("挂上本方案词库预检，并仅自动改「连续 3 期干净采纳且同意」的词")),
            ("run_speakers", "人名", tr("{n} 人", n=counts.get("cast", 0)), cfg.run_speakers,
             tr("按记住的说话人套用名字和颜色，绝不覆盖已手动起好的名字")),
            ("run_style_preset", "样式", tr("{n} 套", n=counts.get("style", 0)), cfg.run_style_preset,
             tr("自动套用本方案记住的字幕样式预设")),
        )
        self._syncing_switches = True
        try:
            for key, label, count, checked, tip in specs:
                stamp = QPushButton()
                stamp.setObjectName("finishStamp")
                stamp.setCheckable(True)
                stamp.setChecked(bool(checked))
                stamp.setCursor(Qt.CursorShape.PointingHandCursor)
                stamp.setToolTip(tip)
                stamp.setAccessibleName(f"{tr('套')}{tr(label)}")
                stamp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                face = QVBoxLayout(stamp)
                face.setContentsMargins(4, 6, 4, 6)
                face.setSpacing(0)
                for object_name, text in (("finishStampCount", count), ("finishStampLabel", "")):
                    part = QLabel(text)
                    part.setObjectName(object_name)
                    part.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    face.addWidget(part)
                stamp.setProperty("stampLabel", tr(label))
                _paint_stamp(stamp)
                stamp.toggled.connect(self._on_inline_switch_toggled)
                stamps.addWidget(stamp, 1)
                self._inline_switches[key] = stamp
        finally:
            self._syncing_switches = False
        lay.addLayout(stamps)

        if not cfg.enabled:
            now = QPushButton(tr("现在套用到本片"))
            now.setObjectName("finishCardTint")
            now.setCursor(Qt.CursorShape.PointingHandCursor)
            now.setToolTip(tr("按亮着的几项，现在就对本片套用一次"))
            now.clicked.connect(self.apply_now_requested.emit)
            lay.addWidget(now, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    # ------------------------------------------------------------ changes
    def _current_config(self, *, enabled: bool | None = None) -> AutoPipelineConfig:
        run_glossary = self._inline_switches["run_glossary"].isChecked()
        run_speakers = self._inline_switches["run_speakers"].isChecked()
        run_style = self._inline_switches["run_style_preset"].isChecked()
        return AutoPipelineConfig(
            enabled=self._pipeline_config.enabled if enabled is None else bool(enabled),
            run_glossary=run_glossary,
            auto_apply_graduated=run_glossary,
            run_speakers=run_speakers,
            run_style_preset=run_style,
        )

    def _on_inline_switch_toggled(self) -> None:
        if self._syncing_switches or not self._inline_switches:
            return
        for stamp in self._inline_switches.values():
            _paint_stamp(stamp)
        updated = self._current_config()
        self._pipeline_config = updated
        self.pipeline_config_changed.emit(updated)

    def _on_auto_toggled(self, checked: bool) -> None:
        if self._syncing_switches or not self._inline_switches:
            return
        updated = self._current_config(enabled=checked)
        self._pipeline_config = updated
        self.pipeline_config_changed.emit(updated)

    def _emit_save(self) -> None:
        chosen = []
        for cb, row in self._save_checks:
            copy_row = dict(row)
            copy_row["checked"] = cb.isChecked()
            chosen.append(copy_row)
        self.save_to_plan_requested.emit(chosen)

    def refresh_theme(self) -> None:
        self.setStyleSheet(_panel_qss(_theme()))


def _paint_stamp(stamp: QPushButton) -> None:
    """A stamp's two lines: the count, big, over 「✓ 套词库」; both take the lit colour when on."""
    on = stamp.isChecked()
    for part in stamp.findChildren(QLabel):
        if part.objectName() == "finishStampLabel":
            part.setText(f"{'✓ ' if on else ''}{tr('套')}{stamp.property('stampLabel')}")
        part.setProperty("on", "true" if on else "false")
        part.style().unpolish(part)
        part.style().polish(part)


def _icon(name: str, color: str, size: int = 14):
    from PySide6.QtCore import QSize
    return _icon_qicon(name, color).pixmap(QSize(size, size))


def _icon_qicon(name: str, color: str):
    import qtawesome as qta
    from ..design.themed_icons import _prime_platform_font_fallback
    _prime_platform_font_fallback()
    return qta.icon(name, color=color)


class MicroUpgradePill(QFrame):
    """Non-blocking inline Action-First micro-upgrade pill + post-click insight line."""

    action_clicked = Signal(object)     # MicroUpgradeOffer
    dismissed = Signal(str)             # offer.kind

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("microUpgradePill")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._offer: MicroUpgradeOffer | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 8, 6)
        row.setSpacing(8)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        row.addWidget(self.message_label, 1)

        self.action_button = QPushButton("")
        self.action_button.setObjectName("microUpgradeAction")
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.clicked.connect(self._on_action)
        row.addWidget(self.action_button)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("microUpgradeClose")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self._on_close)
        row.addWidget(self.close_button)

        self.refresh_theme()
        self.hide()

    def show_offer(self, offer: MicroUpgradeOffer) -> None:
        self._offer = offer
        self.setProperty("mode", "offer")
        self.message_label.setText(offer.message)
        self.action_button.setText(offer.action_label)
        self.action_button.show()
        self.refresh_theme()
        self.show()

    def show_insight(self, text: str) -> None:
        self._offer = None
        self.setProperty("mode", "insight")
        self.message_label.setText(f"💡 {text}")
        self.action_button.hide()
        self.refresh_theme()
        self.show()

    def _on_action(self) -> None:
        if self._offer is not None:
            offer = self._offer
            self.action_clicked.emit(offer)
            self.show_insight(offer.insight_after)

    def _on_close(self) -> None:
        kind = self._offer.kind if self._offer is not None else ""
        self._offer = None
        self.hide()
        if kind:
            self.dismissed.emit(kind)

    def refresh_theme(self) -> None:
        t = _theme()
        is_insight = self.property("mode") == "insight"
        bg = t.success_soft if is_insight else blend_hex(t.surface, t.accent, 0.14 if t.is_light else 0.22)
        self.setStyleSheet(f"""
            QFrame#microUpgradePill {{
                background: {bg};
                border: 0;
                border-radius: 12px;
                min-height: 36px;
            }}
            QFrame#microUpgradePill QLabel {{
                background: transparent;
                color: {t.text};
                font-family: {UI_FONT_STACK};
                font-size: 12px;
            }}
            QFrame#microUpgradePill QPushButton#microUpgradeAction {{
                background: {t.accent};
                color: {t.text_on_accent};
                border: 0;
                border-radius: 9px;
                padding: 4px 11px;
                font-family: {UI_FONT_STACK};
                font-size: 12px;
                font-weight: 600;
            }}
            QFrame#microUpgradePill QPushButton#microUpgradeAction:hover {{ background: {t.accent_hover}; }}
            QPushButton#microUpgradeClose {{
                background: transparent;
                color: {t.text_muted};
                border: 0;
                min-width: 22px; max-width: 22px;
                min-height: 22px; max-height: 22px;
                font-size: 14px;
            }}
        """)


MissionFocusPanel = FinishChecklistPanel

__all__ = ["FinishChecklistPanel", "MicroUpgradePill", "MissionFocusPanel"]
