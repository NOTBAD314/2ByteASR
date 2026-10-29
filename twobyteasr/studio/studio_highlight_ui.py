"""Clip assistant panel, highlight bin, and analysis worker."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, Signal, QEvent, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QBoxLayout,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..timeline.studio_edit_sequence import HighlightCandidate, sequence_of
from .studio_highlight_analyzer import HighlightSkillAdapter, analyze_highlights, highlight_transcript_project
from ..projects.studio_project import SubtitleProject, analysis_transcript_cues
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition

from ..i18n_widgets import add_combo_item
from ..i18n import bind_text
from ..design.soft_widgets import (SegmentedControl, UnitField, WrapLayout, flexible_combo, set_pill, soft_card,
                                   soft_pill)
from ..design.themed_icons import install_themed_icon

from ..i18n import tr


class HighlightAnalyzeWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int)

    def __init__(self, project: SubtitleProject, options: dict, parent=None) -> None:
        super().__init__(parent)
        self._project = project
        self._options = dict(options)

    def run(self) -> None:
        try:
            from ..system.processes import process_action_scope

            with process_action_scope("studio.clip-assistant.analyze"):
                result = analyze_highlights(
                    self._project,
                    cancel_check=self.isInterruptionRequested,
                    progress=self.progress.emit,
                    **self._options,
                )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)


class SmoothCardList(QListWidget):
    """Tall card lists must not inherit Qt's item-height singleStep.

    ScrollPerPixel mode derives singleStep from sizeHintForRow (≈ one card),
    so a wheel notch scrolled singleStep × wheelScrollLines ≈ 960px — the
    user's "one notch skips 2–3 cards". Notches scroll a fixed ~110px here;
    trackpad pixelDelta keeps Qt's native pixel scrolling (smooth).
    """

    WHEEL_NOTCH_PX = 110

    def wheelEvent(self, event):
        pixel = event.pixelDelta()
        if pixel is not None and not pixel.isNull():
            super().wheelEvent(event)
            return
        notches = event.angleDelta().y() / 120.0
        if not notches:
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        bar.setValue(int(round(bar.value() - notches * self.WHEEL_NOTCH_PX)))
        event.accept()


def _clamp_label_lines(label: QLabel, max_lines: int) -> None:
    """Cap a wrapped label's height to a few lines; details hold the rest."""
    metrics = label.fontMetrics()
    label.setMaximumHeight(max(1, max_lines) * metrics.lineSpacing() + metrics.descent())


def _section_frame(title: str, body_text: str, theme, *, accent: bool):
    """Light section card: thin left accent + soft tint, never a heavy panel."""
    from PySide6.QtWidgets import QFrame, QVBoxLayout

    frame = QFrame()
    suffix = "Why" if accent else "What"
    frame.setObjectName(f"highlightSection{suffix}")
    edge = getattr(theme, "accent", "#33CC66")
    soft = getattr(theme, "surface", "#1E1E22")
    border = getattr(theme, "border", "#3A3A40")
    # 2026-10-11: a left rule only; the card is the single box (no box-in-box).
    if accent:
        # 为什么值得剪：主题 accent 左缘 + 同族浅底，视觉权重最高但不做重色块。
        frame.setStyleSheet(
            f"QFrame#highlightSectionWhy {{"
            f" background: {soft}; border: none;"
            f" border-left: 3px solid {edge}; border-radius: 0; }}"
            " QLabel { background: transparent; border: none; }"
        )
    else:
        # 发生了什么：轻一档——无填充、无 accent，避免与上方 section 同级。
        frame.setStyleSheet(
            f"QFrame#highlightSectionWhat {{"
            f" background: transparent; border: none;"
            f" border-left: 3px solid {border}; border-radius: 0; }}"
            " QLabel { background: transparent; border: none; }"
        )
    box = QVBoxLayout(frame)
    box.setContentsMargins(8, 3, 4, 3)
    box.setSpacing(2)
    head = QLabel(title)
    head.setObjectName("contextEmpty")
    box.addWidget(head)
    body = QLabel(body_text)
    body.setObjectName("highlightReason" if accent else "highlightDetails")
    body.setWordWrap(True)
    box.addWidget(body)
    frame.body = body
    frame.head = head
    return frame


class HighlightCandidateCard(QFrame):
    preview_requested = Signal(str)
    accept_requested = Signal(str)
    ignore_requested = Signal(str)
    remove_requested = Signal(str)
    context_requested = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, candidate, parent=None):
        super().__init__(parent)
        self._owner_list = parent if isinstance(parent, QListWidget) else None
        self.candidate_id = candidate.id
        self._candidate = candidate
        self.setObjectName("highlightCandidateCard")
        self.setProperty("softCard", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(8)
        def label(value, name):
            widget=QLabel(value)
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setObjectName(name)
            widget.setWordWrap(True)
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            return widget
        self.title_label=label(candidate.title, 'highlightTitle')
        self.title_label.setToolTip(candidate.title)
        _clamp_label_lines(self.title_label, 2)
        layout.addWidget(self.title_label)
        reason=candidate.clip_reason or candidate.reason
        if not candidate.evidence and candidate.origin!='manual':
            reason=tr('旧建议，待重新确认')
        self.reason_label=label(reason, 'highlightWhy')
        self.reason_label.setToolTip(candidate.clip_reason or candidate.reason)
        # Keep the bounded editorial sentence fully readable at narrow widths;
        # a pixel-height clamp can slice the last glyph when fonts/theme change.
        layout.addWidget(self.reason_label)
        self.range_label=label('', 'highlightRange')
        if candidate.clip_range:
            bind_text(self.range_label, '建议片段：{range} · {duration}',
                range=_clock_range(*candidate.clip_range),
                duration=_duration_label(candidate.source_out_ms-candidate.source_in_ms))
        else:
            bind_text(self.range_label, '待确认剪辑范围')
        layout.addWidget(self.range_label)
        kinds=candidate.evidence_kinds
        basis=('字幕＋弹幕' if kinds == {'subtitle','danmaku'} else '字幕' if 'subtitle' in kinds
               else '仅弹幕，待确认内容' if 'danmaku' in kinds else
               '手动' if candidate.origin=='manual' else '旧建议，待重新确认')
        state=('已加入待生成' if candidate.status == 'accepted' else
               '已忽略' if candidate.status == 'ignored' else
               '人工确认' if candidate.user_confirmed else
               '人工调整起止' if candidate.user_adjusted else '尚未人工确认' if 'subtitle' in kinds else '')
        self.basis_label=label(' · '.join(tr(t) for t in (basis,state) if t), 'softMeta')
        layout.addWidget(self.basis_label)
        self.preview_button=QPushButton(tr('预览片段' if candidate.clip_range else '查看现场'))
        self.accept_button=QPushButton(tr('已加入待生成' if candidate.status=='accepted' else
                                         '加入待生成' if candidate.clip_range else '设置起止'))
        self.more_button=QToolButton()
        self.more_button.setText('•••')
        bind_text(self.more_button, '更多操作', property='accessibleName')
        bind_text(self.more_button, '更多操作', property='toolTip')
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(self.more_button)
        self.details_action=menu.addAction(tr('查看依据'))
        self.details_action.triggered.connect(self.toggle_details)
        menu.addAction(tr('查看前后内容'),lambda:self.context_requested.emit(self.candidate_id))
        menu.addAction(tr('调整起止'),lambda:self.edit_requested.emit(self.candidate_id))
        if candidate.status=='accepted':
            menu.addAction(tr('移出待生成'),lambda:self.remove_requested.emit(self.candidate_id))
        menu.addAction(tr('忽略（可撤销）'),lambda:self.ignore_requested.emit(self.candidate_id))
        self.more_button.setMenu(menu)
        self.preview_button.clicked.connect(lambda:self.preview_requested.emit(self.candidate_id))
        self.accept_button.clicked.connect(lambda:(self.accept_requested if candidate.clip_range
                                                   else self.edit_requested).emit(self.candidate_id))
        self.accept_button.setEnabled(candidate.status != 'accepted')
        self._action_buttons=(self.preview_button,self.accept_button,self.more_button)
        self._action_grid=QGridLayout()
        self._action_grid.setSpacing(6)
        self._action_columns=0
        for b in self._action_buttons:
            b.setObjectName('studioPrimary' if b is self.preview_button else 'studioButton')
            b.setProperty('softSize','sm')
            b.setMinimumWidth(0)
            b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty('candidateId',candidate.id)
        self.preview_button.setObjectName('studioPrimary')
        self.preview_button.setProperty('buttonRole','primary')
        self.accept_button.setObjectName('highlightAccept')
        self.more_button.setObjectName('highlightMore')
        self.preview_button.setProperty('zone','accent')
        layout.addLayout(self._action_grid)
        self.details_body=QWidget()
        detail_layout=QVBoxLayout(self.details_body)
        detail_layout.setContentsMargins(0,6,0,0)
        detail_layout.setSpacing(8)
        for kind,heading in [('subtitle','对应字幕'),('danmaku','观众原话')]:
            rows=[r for r in candidate.evidence if r.get('kind')==kind]
            if rows:
                detail_layout.addWidget(label(tr(heading), 'softLabel'))
                from ..projects.project_range import clock_text
                rendered=['['+clock_text(r['start_ms'])+'] '+r['text'] for r in sorted(rows[:10],key=lambda r:r['start_ms'])]
                detail_layout.addWidget(label('\n'.join(rendered),'highlightEvidence'))
        if len(candidate.clip_reason or candidate.reason)>60:
            detail_layout.addWidget(label(tr('为什么值得剪'), 'softLabel'))
            detail_layout.addWidget(label(candidate.clip_reason or candidate.reason, 'highlightEvidence'))
        if candidate.key_moment_ms is not None:
            detail_layout.addWidget(label(tr('关键话语：{time}（来自字幕）',
                                           time=_clock_range(candidate.key_moment_ms,candidate.key_moment_ms).split('–')[0]),'softMeta'))
        detail_layout.addWidget(label(tr('查看前后：{range}',range=_clock_range(candidate.context_in_ms or 0,
                                                                       candidate.context_out_ms or 0)),'softMeta'))
        detail_layout.addWidget(label(tr('弹幕反应范围：{range}',range=_clock_range(candidate.signal_in_ms or 0,
                                                                              candidate.signal_out_ms or 0)),'softMeta'))
        if candidate.risk_notes:
            detail_layout.addWidget(label(tr('待确认：')+'\n'+'\n'.join(candidate.risk_notes),'highlightEvidence'))
        context=QPushButton(tr('查看前后内容'))
        context.setObjectName('studioButton')
        context.clicked.connect(lambda:self.context_requested.emit(self.candidate_id))
        detail_layout.addWidget(context)
        stats=QToolButton()
        bind_text(stats,'统计与排序依据')
        stats.setCheckable(True)
        stats.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        stats.setArrowType(Qt.ArrowType.RightArrow)
        signal=candidate.danmaku_signal
        diagnostic=label(tr('原始弹幕 {raw} · 去除例行和推广后 {usable} · 热度 {spike} 倍 · 内部排序分 {score}',
            raw=signal.get('raw_total',0),usable=signal.get('usable_total',0),
            spike=signal.get('peak_spike',0),score=round(candidate.score*100)),'softMeta')
        diagnostic.hide()
        stats.toggled.connect(lambda checked:(diagnostic.setVisible(checked),self._resize_row()))
        detail_layout.addWidget(stats)
        detail_layout.addWidget(diagnostic)
        self.details_body.hide()
        layout.addWidget(self.details_body)
        self._reflow_actions()

    def toggle_details(self):
        self.details_body.setVisible(self.details_body.isHidden())
        self._resize_row()

    def _resize_row(self):
        self.updateGeometry()
        self.layout().activate()
        owner=self._owner_list
        if owner:
            for index in range(owner.count()):
                item=owner.item(index)
                if owner.itemWidget(item) is self:
                    hint=QSize(0,self.sizeHint().height())
                    if item.sizeHint()!=hint:item.setSizeHint(hint)
                    break

    def _reflow_actions(self):
        available=max(1,self.width()-24)
        pair=sum(b.sizeHint().width() for b in self._action_buttons[:2])+6
        columns=3 if pair+self.more_button.sizeHint().width()+6<=available else 2 if pair<=available else 1
        if columns==self._action_columns:return
        self._action_columns=columns
        while self._action_grid.count():self._action_grid.takeAt(0)
        for index,b in enumerate(self._action_buttons):
            self._action_grid.addWidget(b,index//columns,index%columns)
        for c in range(3):
            self._action_grid.setColumnMinimumWidth(c,0)
            self._action_grid.setColumnStretch(c,1 if c<min(2,columns) else 0)

    def event(self,event):
        result=super().event(event)
        if (event.type() in (QEvent.Type.LayoutRequest,QEvent.Type.StyleChange,QEvent.Type.FontChange)
                and hasattr(self,'_action_grid') and not getattr(self,'_layout_pending',False)):
            self._layout_pending=True
            QTimer.singleShot(0,self._settle_layout)
        return result

    def _settle_layout(self):
        from shiboken6 import isValid
        if not isValid(self):return
        self._layout_pending=False
        self._reflow_actions()
        self._resize_row()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'_action_grid'):
            self._reflow_actions()
            self._resize_row()

    def sizeHint(self):
        hint=super().sizeHint()
        if self._owner_list:
            width=max(240,self._owner_list.viewport().width()-8)
            hint.setWidth(width)
            wrapped=self.layout().totalHeightForWidth(width)
            if wrapped>0:hint.setHeight(wrapped)
        return hint


class HighlightBinCard(QFrame):
    """Selected-candidate row with explicit remove and ordering controls."""

    remove_requested = Signal(str)
    move_requested = Signal(str, int)

    def __init__(self, candidate: HighlightCandidate, index: int, count: int, parent=None) -> None:
        super().__init__(parent)
        self.candidate_id = candidate.id
        self.setObjectName("highlightBinCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 4, 3)
        layout.setSpacing(4)
        # One compact row: order, kept range (what is generated), title.
        from ..design.elided_label import ElidedLabel
        clock = QLabel(f"{index + 1}. {_clock_range(candidate.source_in_ms, candidate.source_out_ms)}")
        clock.setObjectName("highlightTitle")
        title = ElidedLabel(candidate.title, mode=Qt.TextElideMode.ElideRight, minimum=24)
        title.setObjectName("contextEmpty")
        layout.addWidget(clock)
        layout.addWidget(title, 1)
        up = QPushButton("↑")
        down = QPushButton("↓")
        remove = QPushButton("×")
        for button, tooltip in (
            (up, "上移候选"),
            (down, "下移候选"),
            (remove, "从剪辑候选箱移除"),
        ):
            button.setObjectName("studioButton")
            button.setToolTip(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(28, 28)
            layout.addWidget(button)
        up.setEnabled(index > 0)
        down.setEnabled(index < count - 1)
        up.clicked.connect(lambda: self.move_requested.emit(self.candidate_id, -1))
        down.clicked.connect(lambda: self.move_requested.emit(self.candidate_id, 1))
        remove.clicked.connect(lambda: self.remove_requested.emit(self.candidate_id))


class HighlightAssistantPanel(QWidget):
    preview_requested = Signal(int)
    context_requested = Signal(str)
    edit_requested = Signal(str)
    source_changed = Signal(str)
    candidates_ready = Signal(object)
    add_to_bin_requested = Signal(str)
    ignore_requested = Signal(str)
    generate_requested = Signal()
    restore_requested = Signal()
    analyze_requested = Signal(dict)
    xml_selected = Signal(str)
    xml_unbind_requested = Signal()
    add_mark_in_out_requested = Signal()
    cancel_requested = Signal()
    remove_from_bin_requested = Signal(str)
    candidate_move_requested = Signal(str, int)
    clear_bin_requested = Signal()
    # 四十四轮：自动剪口播气口（min_silence_s, padding_s / timeline ranges）。
    autocut_detect_requested = Signal(float, float)
    autocut_apply_requested = Signal(object)
    autocut_cancel_requested = Signal()
    autocut_preview_requested = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("highlightAssistant")
        self.setMinimumWidth(280)
        self._worker: HighlightAnalyzeWorker | None = None
        self._project: SubtitleProject | None = None
        self._danmaku_path = ""
        self._auto_mode = "none"
        self._stage = "settings"
        self._analysis_note = ""
        self._last_note = ""
        self._candidate_signature = ""
        self._show_all = False
        self._all_candidates = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("剪辑助手")
        title.setObjectName("sectionTitle")
        title.hide()
        self.status = QLabel("尚未打开工程")
        self.status.setObjectName("contextEmpty")
        self.status.setWordWrap(True)

        self.empty_setup = QFrame()
        self.empty_setup.setObjectName("highlightEmptyState")
        empty_layout = QVBoxLayout(self.empty_setup)
        empty_layout.setContentsMargins(14, 12, 14, 12)
        empty_layout.setSpacing(6)
        empty_title = QLabel("剪辑助手")
        empty_title.setObjectName("sectionTitle")
        empty_layout.addWidget(empty_title)
        empty_hint = QLabel("分析字幕、弹幕或直播数据，寻找值得剪辑的片段。")
        empty_hint.setObjectName("contextEmpty")
        empty_hint.setWordWrap(True)
        empty_layout.addWidget(empty_hint)
        empty_actions = QHBoxLayout()
        self.empty_import_xml = QPushButton("导入弹幕 XML")
        self.empty_import_xml.setObjectName("studioButton")
        self.empty_import_xml.clicked.connect(self._pick_xml)
        self.empty_analyze_subtitles = QPushButton("分析当前字幕")
        self.empty_analyze_subtitles.setObjectName("studioPrimary")
        self.empty_analyze_subtitles.clicked.connect(self._analyze_current_subtitles)
        empty_actions.addWidget(self.empty_analyze_subtitles)
        empty_actions.addWidget(self.empty_import_xml)
        empty_layout.addLayout(empty_actions)
        self.empty_summary = QLabel("候选数 20\n建议长度 30–180秒")
        self.empty_summary.setObjectName("cardMeta")
        self.empty_summary.setWordWrap(True)
        empty_layout.addWidget(self.empty_summary)
        self.empty_setup.hide()
        layout.addWidget(self.empty_setup)

        # 2026-10-23 (the user's picks): the two tools as tabs on top (design B)
        # — finding clips and compressing speech pauses — their settings in
        # cards (design A), compact candidate cards (design C).
        self.empty_setup.setProperty("softCard", True)
        self._tool = "clips"
        self.tool_tabs = QFrame()
        self.tool_tabs.setObjectName("softSegmented")
        self.tool_tabs.setProperty("tone", "soft")
        tabs_row = QHBoxLayout(self.tool_tabs)
        self._tabs_row=tabs_row
        tabs_row.setContentsMargins(4, 4, 4, 4)
        tabs_row.setSpacing(2)
        self.clips_tab_button = QPushButton("找值得剪的片段")
        self.pauses_tab_button = QPushButton("压缩口播停顿")
        for button, icon_name, tool in ((self.clips_tab_button, "fa5s.magic", "clips"),
                                        (self.pauses_tab_button, "fa5s.wave-square", "pauses")):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("flexibleWidth", True)
            button.setProperty("softTab", True)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            install_themed_icon(button, icon_name, "accent")
            button.clicked.connect(lambda _checked=False, tool=tool: self.set_tool(tool))
            tabs_row.addWidget(button, 1)
        self.clips_tab_button.setChecked(True)
        layout.addWidget(self.tool_tabs)

        self.config_header_host = QWidget()
        config_header = QHBoxLayout(self.config_header_host)
        self._config_header_row=config_header
        config_header.setContentsMargins(0, 0, 0, 0)
        config_header.setSpacing(8)
        self.config_summary = QLabel("数据与分析设置")
        self.config_summary.setObjectName("softMeta")
        # The summary gives way first; 分析设置 / 收起 keeps its whole label.
        self.config_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        config_header.addWidget(self.config_summary, 1)
        self.analyze_button = QPushButton("分析录播")
        self.analyze_button.setObjectName("studioPrimary")
        self.analyze_button.setProperty("softSize", "lg")
        self.analyze_button.setProperty("flexibleWidth", True)
        self.analyze_button.setCursor(Qt.CursorShape.PointingHandCursor)
        install_themed_icon(self.analyze_button, "fa5s.magic", "on_accent")
        self.analyze_button.clicked.connect(self._analyze)
        config_header.addWidget(self.analyze_button, 1)
        self.config_toggle = QToolButton()
        self.config_toggle.setObjectName("highlightConfigToggle")
        bind_text(self.config_toggle, '分析设置')
        self.config_toggle.setCheckable(True)
        self.config_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.config_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.config_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_toggle.setChecked(True)
        bind_text(self.config_toggle, '收起')
        self.config_toggle.setArrowType(Qt.ArrowType.UpArrow)
        config_header.addWidget(self.config_toggle)
        layout.addWidget(self.config_header_host)
        self.progress_label=QLabel()
        self.progress_label.setObjectName('softMeta')
        self.progress_label.setWordWrap(True)
        self.progress_label.hide()
        self.analysis_progress=QProgressBar()
        self.analysis_progress.hide()
        layout.addWidget(self.progress_label)
        layout.addWidget(self.analysis_progress)
        self.local_hint=QLabel()
        self.local_hint.setObjectName('softMeta')
        self.local_hint.setWordWrap(True)
        self.local_hint.hide()
        layout.addWidget(self.local_hint)


        # 2026-10-11: data and analysis settings share one collapsible scroll
        # area. Once candidates exist it folds away and the candidate list is
        # the panel's only main scroll region.
        self.settings_area = QScrollArea()
        self.settings_area.setObjectName("highlightSettingsArea")
        self.settings_area.setWidgetResizable(True)
        self.settings_area.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_content = QWidget()
        settings_content.setObjectName("contextContent")
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(0, 0, 4, 0)
        settings_layout.setSpacing(10)
        self.settings_area.setWidget(settings_content)

        self.config_body = QWidget()
        config_body_layout = QVBoxLayout(self.config_body)
        config_body_layout.setContentsMargins(0, 0, 0, 0)
        config_body_layout.setSpacing(10)
        self.status.setObjectName("softMeta")
        config_body_layout.addWidget(self.status)

        def card_title(text, icon_name=""):
            row = QHBoxLayout()
            row.setSpacing(8)
            if icon_name:
                mark = QToolButton()
                mark.setObjectName("softFoldArrow")
                mark.setAutoRaise(True)
                mark.setFixedSize(18, 18)
                mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                install_themed_icon(mark, icon_name, "zone_content")
                row.addWidget(mark)
            title = QLabel(text)
            title.setObjectName("softCardTitle")
            row.addWidget(title)
            row.addStretch(1)
            return row

        def labelled(text, *widgets):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(text)
            label.setObjectName("softLabel")
            row.addWidget(label)
            for widget, stretch in widgets:
                row.addWidget(widget, stretch)
            return row

        def data_row(icon_name, text, pill):
            row = QHBoxLayout()
            row.setSpacing(8)
            mark = QToolButton()
            mark.setObjectName("highlightDataIcon")
            mark.setFixedSize(28, 28)
            mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            install_themed_icon(mark, icon_name, "zone_content")
            row.addWidget(mark)
            label = QLabel(text)
            label.setObjectName("softLabel")
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(pill)
            return row

        data, data_layout = soft_card()
        data_layout.addLayout(card_title("数据"))
        self.source_combo=QComboBox()
        flexible_combo(self.source_combo)
        self.source_combo.currentIndexChanged.connect(lambda: self.source_changed.emit(str(self.source_combo.currentData() or '')))
        data_layout.addWidget(QLabel(tr('分析录播来源')))
        data_layout.addWidget(self.source_combo)
        self.offset_box=QDoubleSpinBox()
        self.offset_box.setRange(-86400,86400)
        self.offset_box.setDecimals(3)
        self.offset_box.setSingleStep(1)
        self.offset_box.setSuffix(tr(' 秒'))
        bind_text(self.offset_box,'录播时间 = XML 时间 + 此偏移；这不是观众反应延迟。',property='toolTip')
        data_layout.addWidget(QLabel(tr('弹幕时间偏移')))
        data_layout.addWidget(self.offset_box)
        self.subtitle_status = QLabel("字幕：0 条（当前工程）", data)
        self.subtitle_status.setObjectName("softMeta")
        self.subtitle_status.hide()  # the pill below says it; the text stays for tooltips and checks
        self.subtitle_pill = soft_pill()
        set_pill(self.subtitle_pill, '{cue_count} 条 · 当前工程', 'off', cue_count=0)
        data_layout.addLayout(data_row("fa5s.closed-captioning", "字幕", self.subtitle_pill))
        self.xml_pill = soft_pill("未匹配", "warn")
        data_layout.addLayout(data_row("fa5s.comment-dots", "弹幕 XML", self.xml_pill))
        self.xml_status = QLabel("弹幕 XML：未匹配")
        self.xml_status.setObjectName("softMeta")
        self.xml_status.setWordWrap(True)
        data_layout.addWidget(self.xml_status)
        self.xml_button = QPushButton("导入弹幕 XML")
        self.xml_button.setObjectName("studioButton")
        self.xml_button.clicked.connect(self._pick_xml)
        self.xml_unbind_button = QPushButton("解除匹配")
        self.xml_unbind_button.setObjectName("studioButton")
        self.xml_unbind_button.clicked.connect(self.xml_unbind_requested.emit)
        xml_actions = QHBoxLayout()
        xml_actions.setSpacing(6)
        for button in (self.xml_button, self.xml_unbind_button):
            button.setProperty("softSize", "sm")
            button.setProperty("flexibleWidth", True)
            button.setMinimumWidth(0)
            xml_actions.addWidget(button, 1)
        data_layout.addLayout(xml_actions)
        config_body_layout.addWidget(data)

        setup, setup_layout = soft_card()
        setup_layout.addLayout(card_title("分析"))
        self.mode = QComboBox()
        self.mode.setObjectName("studioCombo")
        self.mode.addItem("自动", "auto")
        self.mode.addItem("字幕 + 弹幕", "subtitles_xml")
        self.mode.addItem("仅字幕", "subtitles")
        self.mode.addItem("仅弹幕 XML", "xml")
        flexible_combo(self.mode)
        setup_layout.addLayout(labelled("分析方式", (self.mode, 1)))
        self.detected_data = QLabel("自动分析：")
        self.detected_data.setObjectName("softMeta")
        self.detected_data.setWordWrap(True)
        self.detected_data.setIndent(0)
        setup_layout.addWidget(self.detected_data)
        self.count_box = QSpinBox()
        self.count_box.setRange(1, 30)
        self.count_box.setValue(8)
        self.min_box = QSpinBox()
        self.min_box.setRange(8, 300)
        self.min_box.setValue(30)
        self.max_box = QSpinBox()
        # 3600s：长事件（整局比赛/完整剧情线 30 分钟以上）也要能一键给全范围。
        self.max_box.setRange(10, 3600)
        self.max_box.setValue(180)
        # Count and length share a line; with longer words (Russian) the
        # length moves under the count instead of widening the panel.
        count_group = QWidget()
        count_field = UnitField(self.count_box, unit=tr("个"))
        count_field.setMinimumWidth(70)
        count_group.setLayout(labelled("最多建议", (count_field, 1)))
        count_group.layout().setContentsMargins(0, 0, 0, 0)
        length_group = QWidget()
        min_field, max_field = UnitField(self.min_box), UnitField(self.max_box, unit=tr("秒"))
        min_field.setMinimumWidth(64)
        max_field.setMinimumWidth(80)
        length_row = labelled("参考长度", (min_field, 1))
        length_row.setContentsMargins(0, 0, 0, 0)
        dash = QLabel("–")
        dash.setObjectName("softMeta")
        length_row.addWidget(dash)
        length_row.addWidget(max_field, 1)
        length_group.setLayout(length_row)
        count_row = WrapLayout(spacing=10, fill=True, by_minimum=True)
        count_row.addWidget(count_group)
        count_row.addWidget(length_group)
        setup_layout.addLayout(count_row)
        self.min_box.valueChanged.connect(self._sync_length_boxes)
        self.max_box.valueChanged.connect(self._sync_length_boxes)
        self.ai_service_combo = QComboBox()
        self.ai_service_combo.setObjectName("studioCombo")
        self.ai_service_combo.currentIndexChanged.connect(self._on_ai_service_changed)
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setObjectName("studioCombo")
        self.ai_model_combo.currentIndexChanged.connect(self._on_ai_model_changed)
        for combo in (self.ai_service_combo, self.ai_model_combo):
            flexible_combo(combo)
        setup_layout.addLayout(labelled("分析服务", (self.ai_service_combo, 1)))
        setup_layout.addLayout(labelled("分析模型", (self.ai_model_combo, 1)))
        self.skill_label = QLabel("Skill：正在查找直播切片规则")
        self.skill_label.setObjectName("softMeta")
        self.skill_label.setWordWrap(True)
        setup_layout.addWidget(self.skill_label)
        self.io_button = QPushButton("将入点/出点选区加入候选")
        self.io_button.setObjectName("studioButton")
        self.io_button.setProperty("softSize", "sm")
        # A long translation (Russian) is cut at the panel edge instead of
        # widening the panel; the tooltip keeps the whole label.
        self.io_button.setProperty("flexibleWidth", True)
        self.io_button.setMinimumWidth(0)
        self.io_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bind_text(self.io_button, '将入点/出点选区加入候选', property='toolTip')
        self.io_button.clicked.connect(self.add_mark_in_out_requested.emit)
        setup_layout.addWidget(self.io_button)
        config_body_layout.addWidget(setup)
        settings_layout.addWidget(self.config_body)
        settings_layout.addStretch(1)
        layout.addWidget(self.settings_area, 1)
        self.config_toggle.toggled.connect(self._toggle_config)
        self._restore_ai_selection()

        # 四十四轮：自动剪口播气口——长静音（气口）检出+波纹删除（可撤销）。
        # 2026-10-23: its own tab (design B), one card (design A).
        self.pause_area = QScrollArea()
        self.pause_area.setObjectName("highlightPauseArea")
        self.pause_area.setWidgetResizable(True)
        self.pause_area.setFrameShape(QFrame.Shape.NoFrame)
        self.pause_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        pause_content = QWidget()
        pause_content.setObjectName("contextContent")
        pause_layout = QVBoxLayout(pause_content)
        pause_layout.setContentsMargins(0, 0, 4, 0)
        pause_layout.setSpacing(10)
        self.pause_area.setWidget(pause_content)
        autocut, autocut_layout = soft_card()
        autocut_layout.addLayout(card_title("压缩口播停顿", "fa5s.wave-square"))
        self.autocut_mode = QComboBox()
        self.autocut_mode.addItem('智能口播 · 本地人声检测', 'smart')
        self.autocut_mode.addItem('仅静音 · 低音量检测', 'silence')
        self.autocut_audio_track = QComboBox()
        self.autocut_audio_track.addItem('当前可听音轨混音（保护所有人声）', '')
        self.autocut_preset = QComboBox(autocut)
        for label, values in [('自然',(1.,.2)),('保守',(1.8,.3)),('紧凑',(.7,.15))]:
            self.autocut_preset.addItem(label, values)
        self.autocut_preset.hide()
        for combo in (self.autocut_mode, self.autocut_audio_track):
            flexible_combo(combo)
        autocut_layout.addLayout(labelled('检测方式', (self.autocut_mode, 1)))
        autocut_layout.addLayout(labelled('分析音轨', (self.autocut_audio_track, 1)))
        self.autocut_preset_segments = SegmentedControl(self.autocut_preset, emit_activated=False)
        autocut_layout.addLayout(labelled('停顿节奏', (self.autocut_preset_segments, 1)))
        advanced_toggle = QToolButton()
        advanced_toggle.setObjectName("highlightLinkToggle")
        bind_text(advanced_toggle, '调整停顿时长与保护量')
        advanced_toggle.setCheckable(True)
        advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        advanced_toggle.toggled.connect(lambda checked: advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow))
        autocut_layout.addWidget(advanced_toggle)
        advanced = QWidget()
        advanced_column = QVBoxLayout(advanced)
        advanced_column.setContentsMargins(0, 0, 0, 0)
        advanced_column.setSpacing(8)
        autocut_layout.addWidget(advanced)
        advanced.hide()
        advanced_toggle.toggled.connect(advanced.setVisible)
        self.autocut_min_silence = QDoubleSpinBox()
        self.autocut_min_silence.setRange(0.5, 60.0)
        self.autocut_min_silence.setDecimals(1)
        self.autocut_min_silence.setValue(1.0)
        self.autocut_min_silence.setSuffix(" 秒")
        bind_text(self.autocut_min_silence, '没有检测到人声的连续停顿至少达到此时长才成为候选', property='toolTip')
        advanced_column.addLayout(labelled("停顿时长 ≥", (UnitField(self.autocut_min_silence), 1)))
        self.autocut_padding = QDoubleSpinBox()
        self.autocut_padding.setRange(0.1, 3.0)
        self.autocut_padding.setDecimals(2)
        self.autocut_padding.setValue(0.20)
        self.autocut_padding.setSuffix(" 秒")
        bind_text(self.autocut_padding, '每个气口两侧保留的呼吸余量', property='toolTip')
        advanced_column.addLayout(labelled("每侧各保留", (UnitField(self.autocut_padding), 1)))
        self.autocut_preset.currentIndexChanged.connect(lambda _: (
            self.autocut_min_silence.setValue(self.autocut_preset.currentData()[0]),
            self.autocut_padding.setValue(self.autocut_preset.currentData()[1])))
        self.autocut_detect_button = QPushButton("检测停顿")
        self.autocut_detect_button.setObjectName("studioPrimary")
        self.autocut_detect_button.clicked.connect(self._autocut_detect_clicked)
        self.autocut_apply_button = QPushButton("应用已勾选停顿")
        self.autocut_apply_button.setObjectName("studioPrimary")
        self.autocut_apply_button.hide()
        self.autocut_apply_button.clicked.connect(self._autocut_apply_clicked)
        autocut_buttons = QHBoxLayout()
        autocut_buttons.setSpacing(6)
        autocut_buttons.addWidget(self.autocut_detect_button, 1)
        autocut_buttons.addWidget(self.autocut_apply_button, 1)
        self.autocut_cancel_button = QPushButton('取消检测')
        self.autocut_cancel_button.hide()
        self.autocut_cancel_button.clicked.connect(self.autocut_cancel_requested.emit)
        autocut_buttons.addWidget(self.autocut_cancel_button)
        autocut_layout.addLayout(autocut_buttons)
        self.autocut_status = QLabel("本地分析当前时间轴；背景声音可保留。先查看/试听候选，再一次应用；Ctrl+Z 撤销整批。混合音轨中的游戏台词同样保护。")
        self.autocut_status.setObjectName("softMeta")
        self.autocut_status.setWordWrap(True)
        autocut_layout.addWidget(self.autocut_status)
        self.autocut_results = QListWidget()
        self.autocut_results.setMinimumHeight(110)
        self.autocut_results.setMaximumHeight(210)
        self.autocut_results.hide()
        self.autocut_results.itemChanged.connect(self._autocut_selection_changed)
        autocut_layout.addWidget(self.autocut_results)
        self.autocut_review_controls = QWidget()
        review_buttons = QHBoxLayout(self.autocut_review_controls)
        review_buttons.setContentsMargins(0,0,0,0)
        review_buttons.setSpacing(6)
        for label, callback in [('全选',lambda:self._autocut_select_all(True)),
                                 ('全不选',lambda:self._autocut_select_all(False)),
                                 ('试听当前剪口',self._autocut_preview_clicked)]:
            button=QPushButton(label);button.setProperty("softSize","sm");button.clicked.connect(callback);review_buttons.addWidget(button)
        self.autocut_review_controls.hide()
        autocut_layout.addWidget(self.autocut_review_controls)
        self._autocut_ranges: list[tuple[int, int]] = []
        # Audio pause detection remains available without captions/danmaku.
        self.autocut_box = autocut
        pause_layout.addWidget(autocut)
        pause_layout.addStretch(1)
        self.pause_area.hide()
        layout.addWidget(self.pause_area, 1)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("studioButton")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        config_header.addWidget(self.cancel_button)

        self.candidates_body = QWidget()
        candidates_layout = QVBoxLayout(self.candidates_body)
        candidates_layout.setContentsMargins(0, 0, 0, 0)
        candidates_layout.setSpacing(7)
        self.candidates_heading = self._heading("剪辑候选")
        candidates_layout.addWidget(self.candidates_heading)
        # Which data really went into these candidates (XML file and count).
        self.analysis_source = QLabel()
        self.analysis_source.setObjectName("softMeta")
        self.analysis_source.setWordWrap(True)
        self.analysis_source.hide()
        config_body_layout.addWidget(self.analysis_source)
        # 候选区常驻：没有候选时也保留分隔与占位说明，而不是整块消失
        # （三十一轮用户反馈：收起后只剩"分析录播"，面板像坏了一样空白）。
        self.candidates_empty = QLabel(
            "暂无剪辑候选。\n点击「分析录播」生成建议片段；满意的片段用「加入剪辑」收进候选箱。"
        )
        self.candidates_empty.setObjectName("highlightEmpty")
        self.candidates_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.candidates_empty.setWordWrap(True)
        candidates_layout.addWidget(self.candidates_empty)
        theme = theme_definition(theme_key())
        list_qss = (
            f"QListWidget {{ color: {theme.text}; background: {theme.surface}; "
            f"border: 1px solid {theme.border}; border-radius: 8px; }}"
        )
        self.results = SmoothCardList()
        self.results.setMinimumHeight(150)
        self.results.setSpacing(3)
        self.results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setStyleSheet(list_qss)
        self.results.itemClicked.connect(self._item_clicked)
        candidates_layout.addWidget(self.results, 1)
        self.more_candidates=QPushButton(tr('展开其余建议'))
        self.more_candidates.setObjectName('studioButton')
        self.more_candidates.setProperty('softSize','sm')
        self.more_candidates.setProperty('softRole','ghost')
        self.more_candidates.clicked.connect(self._toggle_more_candidates)
        self.more_candidates.hide()
        candidates_layout.addWidget(self.more_candidates)

        self.bin_header = QWidget()
        bin_header_layout = QHBoxLayout(self.bin_header)
        bin_header_layout.setContentsMargins(0, 0, 0, 0)
        bin_header_layout.setSpacing(6)
        self.bin_toggle = QToolButton()
        self.bin_toggle.setObjectName("styleSectionHeader")
        self.bin_toggle.setCheckable(True)
        self.bin_toggle.setChecked(False)
        self.bin_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.bin_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.bin_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.bin_toggle, '展开候选箱，调整顺序或移除', property='toolTip')
        self.bin_toggle.toggled.connect(self._toggle_bin)
        bin_header_layout.addWidget(self.bin_toggle, 1)
        self.bin_label = self._heading("剪辑候选箱")
        self.bin_label.setWordWrap(True)
        self.clear_bin_button = QPushButton("清空")
        self.clear_bin_button.setObjectName("studioButton")
        self.clear_bin_button.setProperty("softSize", "sm")
        self.clear_bin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_bin_button.clicked.connect(self.clear_bin_requested.emit)
        bin_header_layout.addWidget(self.clear_bin_button)
        self.bin_header.hide()
        candidates_layout.addWidget(self.bin_header)
        # Collapsed: one wrapped line with the order and kept ranges.
        candidates_layout.addWidget(self.bin_label)
        self.bin_label.hide()
        self.bin = SmoothCardList()
        self.bin.setMinimumHeight(48)
        self.bin.setMaximumHeight(150)
        self.bin.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bin.setStyleSheet(list_qss)
        self.bin.hide()
        candidates_layout.addWidget(self.bin)
        self.generate_row_host = QWidget()
        generate_row = QHBoxLayout(self.generate_row_host)
        self._generate_row=generate_row
        generate_row.setContentsMargins(0, 0, 0, 0)
        self.generate_button = QPushButton("生成清单中的剪辑")
        self.restore_button = QPushButton("返回完整录播")
        self.generate_button.setObjectName("studioPrimary")
        self.restore_button.setObjectName("studioButton")
        generate_row.setSpacing(6)
        for button in (self.generate_button, self.restore_button):
            button.setProperty("softSize", "lg")
        self.generate_button.clicked.connect(self.generate_requested.emit)
        self.restore_button.clicked.connect(self.restore_requested.emit)
        generate_row.addWidget(self.generate_button)
        generate_row.addWidget(self.restore_button)
        self.generate_row_host.hide()
        candidates_layout.addWidget(self.generate_row_host)
        self.edit_result = QLabel()
        self.edit_result.setObjectName("highlightEditResult")
        self.edit_result.setWordWrap(True)
        self.edit_result.hide()
        candidates_layout.addWidget(self.edit_result)
        self._sequence_edited = False
        self.candidates_body.hide()
        layout.addWidget(self.candidates_body, 1)
        self._layout = layout
        for button in (
            self.xml_button,
            self.xml_unbind_button,
            self.io_button,
            self.generate_button,
            self.restore_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_theme_palette()
        self._refresh_skill()

    def _responsive_rows(self):
        from shiboken6 import isValid
        if not isValid(self):return
        self._rows_pending=False
        if not hasattr(self,'_generate_row'):return
        available=max(1,self.width()-28)
        rows=((self._tabs_row,(self.clips_tab_button,self.pauses_tab_button)),
              (self._config_header_row,(self.analyze_button,self.config_toggle)),
              (self._generate_row,(self.generate_button,self.restore_button)))
        for row,buttons in rows:
            shown=[b for b in buttons if not b.isHidden()]
            needed=sum(b.sizeHint().width() for b in shown)+row.spacing()*max(0,len(shown)-1)
            direction=QBoxLayout.Direction.TopToBottom if needed>available else QBoxLayout.Direction.LeftToRight
            if row.direction()!=direction:row.setDirection(direction)

    def event(self,event):
        result=super().event(event)
        if (event.type() in (QEvent.Type.LayoutRequest,QEvent.Type.Resize,QEvent.Type.StyleChange)
                and hasattr(self,'_generate_row') and not getattr(self,'_rows_pending',False)):
            self._rows_pending=True
            QTimer.singleShot(0,self._responsive_rows)
        return result

    def _toggle_config(self, expanded: bool) -> None:
        self._stage = "settings" if expanded else "candidates"
        self.config_body.setVisible(bool(expanded))
        (bind_text(self.config_toggle, '收起') if expanded else bind_text(self.config_toggle, '分析设置'))
        self.config_toggle.setArrowType(
            Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow
        )
        self._apply_stage()

    # ------------------------------------------------ 自动剪口播气口（四十四轮）

    def _autocut_detect_clicked(self) -> None:
        self.autocut_detect_requested.emit(
            float(self.autocut_min_silence.value()),
            float(self.autocut_padding.value()),
        )

    def _autocut_apply_clicked(self) -> None:
        ranges = self._autocut_selected_ranges()
        if not ranges:
            return
        self.autocut_apply_requested.emit(ranges)

    def set_autocut_busy(self, busy: bool, note: str = "") -> None:
        self.autocut_detect_button.setEnabled(not busy)
        self.autocut_apply_button.setEnabled(not busy)
        self.autocut_cancel_button.setVisible(busy)
        for control in (self.autocut_mode,self.autocut_preset,self.autocut_audio_track,self.autocut_min_silence,self.autocut_padding):
            control.setEnabled(not busy)
        if note:
            self.autocut_status.setText(note)

    def show_autocut_preview(self, ranges_ms, total_ms: int, timeline_ms: int, *, analysis=None) -> None:
        self._autocut_ranges = [(int(a), int(b)) for a, b in ranges_ms]
        self._autocut_timeline_ms=timeline_ms
        self._autocut_analysis=analysis or {}
        self.autocut_results.blockSignals(True)
        self.autocut_results.clear()
        for index,(a,b) in enumerate(self._autocut_ranges):
            detail=(analysis or {}).get('candidates',[])
            reason=detail[index].get('reason','停顿候选') if index<len(detail) else '停顿候选'
            confidence=detail[index].get('confidence','请试听') if index<len(detail) else '请试听'
            item=QListWidgetItem(f'{a/1000:.2f}–{b/1000:.2f}s · 删除 {(b-a)/1000:.2f}s\n{confidence}')
            item.setData(Qt.ItemDataRole.UserRole,(a,b))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(reason+'\n'+confidence)
            self.autocut_results.addItem(item)
        self.autocut_results.blockSignals(False)
        self.autocut_results.setVisible(bool(self._autocut_ranges))
        self.autocut_review_controls.setVisible(bool(self._autocut_ranges))
        if not self._autocut_ranges:
            bind_text(self.autocut_status, (analysis or {}).get('diagnostic', '没有检出符合阈值的停顿。'))
            self.autocut_apply_button.hide()
            return
        self.autocut_results.setCurrentRow(0)
        self._autocut_selection_changed()
        self.autocut_apply_button.show()

    def _autocut_selected_ranges(self):
        return [tuple(self.autocut_results.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.autocut_results.count()) if self.autocut_results.item(i).checkState()==Qt.CheckState.Checked]

    def _autocut_selection_changed(self, *_):
        ranges=self._autocut_selected_ranges()
        removed=sum(b-a for a,b in ranges)
        total=getattr(self,'_autocut_timeline_ms',0)
        analysis=getattr(self,'_autocut_analysis',{})
        predicted=max(analysis.get('fixed_end_ms',0),analysis.get('editable_end_ms',total)-removed)
        bind_text(self.autocut_status, '检测完成，尚未应用：{value0} 处候选，已勾选 {value1} 处；预计删除剪辑区间 {value2:.2f} 秒，应用后时间轴 {value3:.2f} 秒。', value0=len(self._autocut_ranges), value1=len(ranges), value2=removed / 1000, value3=max(0, predicted) / 1000)
        self.autocut_apply_button.setEnabled(bool(ranges))

    def _autocut_select_all(self, selected):
        self.autocut_results.blockSignals(True)
        for i in range(self.autocut_results.count()):
            self.autocut_results.item(i).setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
        self.autocut_results.blockSignals(False)
        self._autocut_selection_changed()

    def _autocut_preview_clicked(self):
        item=self.autocut_results.currentItem()
        if item:
            a,b=item.data(Qt.ItemDataRole.UserRole)
            self.autocut_preview_requested.emit(a,b)

    def show_autocut_result(self, note: str) -> None:
        self._autocut_ranges = []
        self.autocut_results.clear()
        self.autocut_results.hide()
        self.autocut_review_controls.hide()
        self.autocut_apply_button.hide()
        self.autocut_status.setText(note)

    def _show_stage(self, stage: str) -> None:
        # The collapse toggle is the only settings entry; "candidates" means
        # the settings area is folded away, so every click has a visible
        # effect (三十一轮：双 tab 点击无视觉变化).
        self.config_toggle.setChecked(stage != "candidates")
        self._stage = "settings" if self.config_toggle.isChecked() else "candidates"
        self._apply_stage()

    def set_tool(self, tool: str) -> None:
        """The two tools of the tab (2026-10-23, design B): clips or pauses."""
        self._tool = "pauses" if tool == "pauses" else "clips"
        self.clips_tab_button.setChecked(self._tool == "clips")
        self.pauses_tab_button.setChecked(self._tool == "pauses")
        self._apply_stage()

    def _apply_stage(self) -> None:
        """Single source of truth for settings/candidates visibility.

        The candidates zone is a permanent section (heading + separator +
        placeholder when empty). Only the settings area folds, driven by the
        low-key 「分析设置」 toggle; every refresh path funnels through here
        so a later set_project_status never re-expands settings on top of a
        candidate list after analysis collapsed it.
        """
        pauses = getattr(self, "_tool", "clips") == "pauses"
        if hasattr(self, "pause_area"):
            self.pause_area.setVisible(pauses)
            self.config_header_host.setVisible(not pauses)
        if pauses:
            for widget in (self.empty_setup, self.settings_area, self.candidates_body):
                widget.setVisible(False)
            return
        has_candidates = self.results.count() > 0
        compact_empty = (
            self._project is not None and self._auto_mode == "none" and not self._danmaku_path
        )
        show_candidates_zone = not compact_empty
        self.empty_setup.setVisible(compact_empty)
        self.candidates_body.setVisible(show_candidates_zone)
        self.candidates_empty.setVisible(show_candidates_zone and not has_candidates)
        self.results.setVisible(show_candidates_zone and has_candidates)
        form_expanded = self.config_toggle.isChecked()
        # Speech-pause detection has its own tab (2026-10-23); analysis
        # settings follow the toggle.
        settings_shown = not compact_empty and form_expanded
        self.settings_area.setVisible(settings_shown)
        self.config_body.setVisible(not compact_empty and form_expanded)
        self.config_summary.setVisible(not compact_empty and not form_expanded and not has_candidates)
        self.config_toggle.setVisible(not compact_empty)
        self.analyze_button.setVisible(not compact_empty)
        if has_candidates and not form_expanded:
            bind_text(self.config_summary, '分析信息')
        self.analyze_button.setObjectName('studioButton' if has_candidates else 'studioPrimary')
        self.analyze_button.setProperty('buttonRole','secondary' if has_candidates else 'primary')
        self.analyze_button.setProperty('softRole','ghost' if has_candidates else 'primary')
        self.analyze_button.setProperty('softSize','sm' if has_candidates else 'lg')
        self.analyze_button.style().unpolish(self.analyze_button)
        self.analyze_button.style().polish(self.analyze_button)
        install_themed_icon(self.analyze_button,'fa5s.redo' if has_candidates else 'fa5s.magic','secondary' if has_candidates else 'on_accent')
        if not getattr(self, "_analyzing", False):
            (bind_text(self.analyze_button, '重新分析') if has_candidates
             else bind_text(self.analyze_button, '分析录播'))
        layout = getattr(self, "_layout", None)
        if layout is not None:
            # Before analysis the settings own the space; afterwards the list.
            layout.setStretchFactor(self.settings_area, (2 if has_candidates else 1) if settings_shown else 0)
            layout.setStretchFactor(self.candidates_body, 3 if has_candidates or not settings_shown else 0)

    def _source_label(self) -> str:
        return {"subtitles_xml": "字幕 + 弹幕", "xml": "弹幕", "subtitles": "字幕"}.get(self._auto_mode, "无法分析")

    def _toggle_bin(self, expanded: bool) -> None:
        self.bin_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        has_bin = self.bin.count() > 0
        self.bin.setVisible(has_bin and expanded)
        self.bin_label.setVisible(has_bin and not expanded)

    def show_edit_result(self, text: str, *, ok: bool = True) -> None:
        """What the last generate/restore actually did (or why it did not)."""
        theme = theme_definition(theme_key())
        self.edit_result.setStyleSheet(
            f"QLabel#highlightEditResult {{ color: {theme.text if ok else theme.warning}; "
            f"background: {theme.accent_soft if ok else theme.warning_soft}; border-radius: 6px; padding: 6px 8px; }}")
        self.edit_result.setText(text)
        self.edit_result.setVisible(bool(text))

    def show_candidates_stage(self) -> None:
        """Fold the settings after an analysis produced candidates."""
        if self.results.count():
            self._show_stage("candidates")

    def _refresh_analysis_source(self) -> None:
        info = (self._project.studio_state.get("highlight_analysis") if self._project is not None else None) or {}
        if not info or not self.results.count():
            self.analysis_source.hide()
            return
        path = str(info.get("danmaku_path") or "")
        count = int(info.get("danmaku_count") or 0)
        if path and count:
            bind_text(self.analysis_source, '依据：弹幕 {count} 条（{name}）', count=f"{count:,}", name=Path(path).name)
        else:
            bind_text(self.analysis_source, '依据：仅字幕（本次分析未使用弹幕 XML）')
        self.analysis_source.setToolTip(path)
        self.analysis_source.show()

    def active_stage(self) -> str:
        return self._stage

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("softCardTitle")
        return label

    def _refresh_skill(self) -> None:
        skill = HighlightSkillAdapter.discover()
        if skill.found:
            bind_text(self.skill_label, '发现本地切片规则；是否采用以切片分析结果为准。口播停顿使用本地音频检测。')
        else:
            bind_text(self.skill_label, '切片分析使用内置规则；口播停顿使用本地音频检测。')

    def set_project_status(self, project: SubtitleProject | None, danmaku_path: str = "") -> None:
        if project is not self._project:
            self.show_edit_result("")
            info=(project.studio_state.get('highlight_analysis') or {}) if project else {}
            self.offset_box.setValue(int(info.get('danmaku_offset_ms') or 0)/1000)
            self._show_all=False
            self._analysis_note=''
        previous = self.autocut_audio_track.currentData()
        self.autocut_audio_track.blockSignals(True)
        self.autocut_audio_track.clear()
        self.autocut_audio_track.addItem('当前可听音轨混音（保护所有人声）','')
        for track in (project.audio_tracks if project else []):
            self.autocut_audio_track.addItem(f'{track.id} · {track.name or "音轨"}',track.id)
        index=self.autocut_audio_track.findData(previous)
        self.autocut_audio_track.setCurrentIndex(max(0,index))
        self.autocut_audio_track.blockSignals(False)
        self._project = project
        from ..media.danmaku_binding import analysis_sources, primary_source
        selected_source=primary_source(project)
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for asset in analysis_sources(project):
            self.source_combo.addItem(asset.display_name or Path(asset.canonical_source).name,asset.canonical_source)
        self.source_combo.setCurrentIndex(max(0,self.source_combo.findData(selected_source)))
        self.source_combo.blockSignals(False)
        self.source_combo.setToolTip(selected_source)
        from ..media.danmaku_binding import binding_of, binding_matches_source, describe
        # An XML recorded for another source recording is never analysed.
        if project is not None and binding_of(project) and not binding_matches_source(project):
            danmaku_path = ""
        self._danmaku_path = str(danmaku_path or "")
        self.set_danmaku_state(*describe(project))
        if project is None:
            bind_text(self.status, '尚未打开工程')
            self._refresh_data_mode()
            return
        if not str(project.media.path or "").strip():
            bind_text(self.status, '空白工程。先导入视频或音频，再导入弹幕 XML 或字幕。')
        else:
            # Asset counts live once in the 数据 group — no triple repetition.
            info=project.studio_state.get('highlight_analysis') or {}
            self.status.setText(str(info.get('llm_error') or '') if info.get('source_path')==selected_source else '')
        self.status.setVisible(bool(self.status.text()))
        self._refresh_skill()
        self._refresh_data_mode()
        sequence = sequence_of(project)
        self._sequence_edited = not sequence.is_identity()
        candidates = sequence.clip_candidates
        signature = json.dumps(
            [selected_source, [candidate.to_dict() for candidate in candidates]],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if signature != self._candidate_signature:
            self.reload_candidates(candidates)
            self._candidate_signature = signature
        else:
            self._refresh_bin_controls()
        self._append_analysis_note()

    def _refresh_data_mode(self) -> None:
        cue_count = (
            len(highlight_transcript_project(self._project).cues)
            if self._project is not None
            else 0
        )
        has_xml = bool(self._danmaku_path)
        if cue_count and has_xml:
            self._auto_mode = "subtitles_xml"
            automatic = "字幕 + 弹幕"
        elif has_xml:
            self._auto_mode = "xml"
            automatic = "弹幕"
        elif cue_count:
            self._auto_mode = "subtitles"
            automatic = "字幕"
        else:
            self._auto_mode = "none"
            automatic = "无法分析"
        xml_text = "✓ 弹幕 XML" if has_xml else "弹幕 XML 未匹配"
        bind_text(self.subtitle_status, '字幕：{cue_count} 条（当前工程）', cue_count=cue_count)
        set_pill(self.subtitle_pill, '{cue_count} 条 · 当前工程', 'ok' if cue_count else 'off', cue_count=cue_count)
        set_pill(self.xml_pill, '已匹配' if has_xml else '未匹配', 'ok' if has_xml else 'warn')
        bind_text(self.detected_data, '自动分析：{automatic}（{xml_text}）', automatic=tr(automatic), xml_text=tr(xml_text))
        bind_text(self.config_summary, '{automatic} · {value1} 个 · {value2}–{value3} 秒', automatic=tr(automatic), value1=self.count_box.value(), value2=self.min_box.value(), value3=self.max_box.value())
        available = self._auto_mode != "none"
        self.analyze_button.setEnabled(available and not getattr(self,"_analyzing",False))
        (bind_text(self.analyze_button, '', property='toolTip') if available else bind_text(self.analyze_button, '请先识别字幕或导入弹幕 XML', property='toolTip'))
        if hasattr(self, "empty_summary"):
            bind_text(self.empty_summary, '候选数 {value0}\n建议长度 {value1}–{value2}秒', value0=self.count_box.value(), value1=self.min_box.value(), value2=self.max_box.value())
        self._apply_stage()

    def _sync_length_boxes(self) -> None:
        min_value = self.min_box.value()
        max_value = self.max_box.value()
        if min_value > max_value:
            if self.sender() is self.min_box:
                self.max_box.setValue(min_value)
            else:
                self.min_box.setValue(max_value)
        self._refresh_data_mode()

    def _clip_settings(self) -> QSettings:
        return QSettings("2ByteASR", "ClipAssistant")

    def _populate_ai_services(self) -> None:
        from ..providers.llm_config import AI_SERVICE_SPECS
        from ..providers.provider_registry import GLOBAL_PROVIDER_REGISTRY

        default_label = "跟随全局设置"
        try:
            selection = GLOBAL_PROVIDER_REGISTRY.selection()
            service = str(selection.service or "")
            if service:
                spec = AI_SERVICE_SPECS.get(service, {})
                name = str(spec.get("label") or service)
                model = str(selection.model or "")
                default_label = tr("跟随全局（当前 {name} · {model}）", name=tr(name), model=model)
        except Exception:
            pass
        combo = self.ai_service_combo
        combo.blockSignals(True)
        combo.clear()
        add_combo_item(combo, default_label, "")
        for service_id, spec in AI_SERVICE_SPECS.items():
            if service_id == "bailian":
                continue
            add_combo_item(combo, str(spec.get("label") or service_id), service_id)
        combo.blockSignals(False)

    def _populate_ai_models(self, service: str, preferred: str = "") -> None:
        combo = self.ai_model_combo
        models: tuple[str, ...] = ()
        if service:
            from ..providers.provider_registry import GLOBAL_PROVIDER_REGISTRY

            try:
                models = GLOBAL_PROVIDER_REGISTRY.models(service)
            except Exception:
                models = ()
        combo.blockSignals(True)
        combo.clear()
        if not service:
            combo.addItem("跟随全局", "")
        else:
            default_label = "默认"
            if models:
                default_label = tr("默认（{model}）", model=models[0])
            add_combo_item(combo, default_label, "")
            for model in models:
                combo.addItem(model, model)
        if preferred:
            index = combo.findData(preferred)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)
        combo.setEnabled(bool(service) and combo.count() > 1)

    def _restore_ai_selection(self) -> None:
        self._populate_ai_services()
        stored = self._clip_settings()
        service = str(stored.value("highlight_ai_service", "") or "")
        model = str(stored.value("highlight_ai_model", "") or "")
        index = self.ai_service_combo.findData(service) if service else -1
        if index >= 0:
            self.ai_service_combo.setCurrentIndex(index)
        else:
            service = ""
        self._populate_ai_models(service, model)

    def _on_ai_service_changed(self) -> None:
        service = str(self.ai_service_combo.currentData() or "")
        self._clip_settings().setValue("highlight_ai_service", service)
        self._populate_ai_models(service, "")
        self._clip_settings().setValue("highlight_ai_model", "")

    def _on_ai_model_changed(self) -> None:
        self._clip_settings().setValue(
            "highlight_ai_model", str(self.ai_model_combo.currentData() or "")
        )

    def selected_ai(self) -> tuple[str, str]:
        """(ai_service, model) the next analysis run should route through."""
        return (
            str(self.ai_service_combo.currentData() or ""),
            str(self.ai_model_combo.currentData() or ""),
        )

    def set_analysis_note(self, llm_status, llm_error=''):
        self._analysis_note=tr('AI 暂不可用，已保留本地建议。') if llm_status=='local_fallback' else ''
        if llm_status=='not_needed':
            self._analysis_note=tr('当前依据是弹幕；补充字幕后，可得到更具体的内容和起止建议。')
        self.local_hint.setText(self._analysis_note)
        self.local_hint.setVisible(bool(self._analysis_note))
        # Technical detail belongs beside analysis information, never on cards.
        self.status.setText(str(llm_error or ''))
        self.status.setVisible(bool(llm_error))

    def _append_analysis_note(self):
        self.local_hint.setText(self._analysis_note)
        self.local_hint.setVisible(bool(self._analysis_note))

    def set_danmaku_state(self, state: str, name: str = "", fields: dict | None = None) -> None:
        """Concrete XML state from danmaku_binding.describe; never a bare 'unmatched'."""
        fields = dict(fields or {})
        count = int(fields.get("count") or 0)
        self._danmaku_state = state
        texts = {
            "no_project": ('弹幕 XML：尚未打开工程', {}),
            "no_media": ('弹幕 XML：先导入录播视频，会自动查找同名 XML', {}),
            "offline": ('弹幕 XML：素材离线，暂时无法查找 {name}', {"name": name}),
            "searching": ('弹幕 XML：正在素材目录查找 {name}…', {"name": name}),
            "none": ('弹幕 XML：素材目录没有同名文件 {name}', {"name": name}),
            "ambiguous": ('弹幕 XML：素材目录有 {count} 个同名 XML，请选择一个',
                          {"count": len(fields.get("candidates") or ())}),
            "invalid": ('弹幕 XML：{name} 无法读取（{error}）', {"name": name, "error": str(fields.get("error") or "")[:80]}),
            "unbound": ('弹幕 XML：已解除匹配，可重新导入', {}),
            "missing": ('弹幕 XML：找不到已绑定的 {name}', {"name": name}),
            "stale": ('弹幕 XML：{name} 属于另一个素材，未使用', {"name": name}),
            "automatic": ('弹幕 XML ✓ 已自动匹配同名文件\n{name} · {count} 条弹幕' if count
                          else '弹幕 XML ✓ 已自动匹配同名文件\n{name}', {"name": name, "count": f"{count:,}"}),
            "manual": ('弹幕 XML ✓ 已手动指定\n{name} · {count} 条弹幕' if count
                       else '弹幕 XML ✓ 已手动指定\n{name}', {"name": name, "count": f"{count:,}"}),
        }
        text, values = texts.get(state, texts["no_project"])
        bind_text(self.xml_status, text, **values)
        self.xml_status.setToolTip(str(fields.get("path") or ""))
        bound = state in {"automatic", "manual"}
        (bind_text(self.xml_button, '更换') if bound
         else bind_text(self.xml_button, '选择…') if state == "ambiguous"
         else bind_text(self.xml_button, '导入弹幕 XML'))
        self.xml_unbind_button.setVisible(bound)

    def set_xml_discovery(
        self,
        candidates: tuple[str, ...] | list[str],
        bound_path: str = "",
        *,
        automatic: bool = False,
    ) -> None:
        if self._project is not None:
            # Legacy callers: the project's binding record is the source of truth.
            self.set_project_status(self._project, bound_path)
            return
        candidates = tuple(str(item) for item in candidates if str(item))
        self._danmaku_path = str(bound_path or "")
        if bound_path:
            prefix = "✓ 已自动匹配" if automatic else "✓ 已匹配"
            bind_text(self.xml_status, '弹幕 XML\n{prefix}\n{value1}', prefix=prefix, value1=Path(bound_path).name)
            bind_text(self.xml_button, '更换')
            self.xml_unbind_button.show()
        elif len(candidates) > 1:
            bind_text(self.xml_status, '发现 {value0} 个可能的弹幕 XML', value0=len(candidates))
            bind_text(self.xml_button, '选择…')
            self.xml_unbind_button.hide()
        else:
            bind_text(self.xml_status, '弹幕 XML：未匹配')
            bind_text(self.xml_button, '导入弹幕 XML')
            self.xml_unbind_button.hide()
        self._refresh_data_mode()

    def reload_candidates(self, candidates):
        from ..media.danmaku_binding import primary_source, normalized_source
        source=normalized_source(primary_source(self._project)) if self._project else ''
        self._all_candidates=list(candidates)
        current=self.current_id()
        scroll=self.results.verticalScrollBar().value()
        expanded={self.results.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.results.count())
                  if not self.results.itemWidget(self.results.item(i)).details_body.isHidden()}
        focus=self.focusWidget()
        focus_key=(focus.property('candidateId'),focus.objectName()) if focus else None
        self.results.clear()
        self.bin.clear()
        visible=[c for c in candidates if c.status!='ignored' and (not source or not c.source_path
                  or normalized_source(c.source_path)==source)]
        accepted=[c for c in candidates if c.status=='accepted' and c.clip_range]
        shown=visible if self._show_all else visible[:5]
        for candidate in shown:
            candidate.validate()
            # The embedded card paints the title. A second DisplayRole title
            # leaks through transparent margins and overlaps narrow cards.
            item=QListWidgetItem()
            item.setData(Qt.ItemDataRole.AccessibleTextRole,candidate.title)
            item.setData(Qt.ItemDataRole.UserRole,candidate.id)
            self.results.addItem(item)
            card=HighlightCandidateCard(candidate,self.results)
            card.preview_requested.connect(self._preview_candidate)
            card.accept_requested.connect(self.add_to_bin_requested.emit)
            card.remove_requested.connect(self.remove_from_bin_requested.emit)
            card.ignore_requested.connect(self.ignore_requested.emit)
            card.context_requested.connect(self.context_requested.emit)
            card.edit_requested.connect(self.edit_requested.emit)
            self.results.setItemWidget(item,card)
            if candidate.id in expanded:card.details_body.show()
            item.setSizeHint(QSize(0,card.sizeHint().height()))
            if candidate.id==current:self.results.setCurrentItem(item)
            if focus_key and focus_key[0]==candidate.id:
                target=card.findChild(QWidget,focus_key[1])
                if target:target.setFocus(Qt.FocusReason.OtherFocusReason)
        self.results.verticalScrollBar().setValue(scroll)
        for index,candidate in enumerate(accepted):
            item=QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,candidate.id)
            self.bin.addItem(item)
            card=HighlightBinCard(candidate,index,len(accepted),self.bin)
            card.remove_requested.connect(self.remove_from_bin_requested.emit)
            card.move_requested.connect(self.candidate_move_requested.emit)
            item.setSizeHint(QSize(0,card.sizeHint().height()))
            self.bin.setItemWidget(item,card)
        rows=sum(self.bin.sizeHintForRow(i)+2*self.bin.spacing() for i in range(self.bin.count()))
        self.bin.setFixedHeight(max(48,min(180,rows+4)))
        total=sum(c.source_out_ms-c.source_in_ms for c in accepted)
        bind_text(self.bin_toggle,'待生成清单 · {count} 段 · {duration}',count=len(accepted),duration=_duration_label(total))
        self.bin_label.setText('  '.join(f'{i}. {_clock_range(*c.clip_range)}' for i,c in enumerate(accepted,1)))
        if accepted and getattr(self,'_bin_count',0)!=len(accepted):self.bin_toggle.setChecked(False)
        self._bin_count=len(accepted)
        self._refresh_bin_controls()
        ready=sum(bool(c.clip_range) for c in visible)
        bind_text(self.candidates_heading,'剪辑建议 {ready} 段 · 待确认 {pending} 处',ready=ready,pending=len(visible)-ready)
        bind_text(self.more_candidates,'收起其余建议' if self._show_all else '展开其余 {count} 条',count=max(0,len(visible)-5))
        self.more_candidates.setVisible(len(visible)>5)
        has_candidates=bool(visible)
        had=getattr(self,'_had_candidates',False)
        self._had_candidates=has_candidates
        if has_candidates and not had:self._show_stage('candidates')
        else:self._apply_stage()
        if not has_candidates:
            bind_text(self.candidates_empty,'没有足够依据的剪辑建议。可以补充字幕，或在时间轴用 I / O 手动选取片段。')
        self._refresh_analysis_source()

    def _toggle_more_candidates(self):
        self._show_all=not self._show_all
        self.reload_candidates(self._all_candidates)

    def set_progress(self, label, percent):
        if not getattr(self,'_analyzing',False):return
        self.progress_label.setText(tr(label))
        self.analysis_progress.setValue(percent)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._project is not None:
            self._refresh_data_mode()

    def _refresh_bin_controls(self) -> None:
        has_bin = self.bin.count() > 0
        self.bin_header.setVisible(has_bin)
        self._toggle_bin(self.bin_toggle.isChecked())
        self.generate_button.setVisible(has_bin)
        self.restore_button.setVisible(bool(self._sequence_edited))
        self.generate_row_host.setVisible(has_bin or bool(self._sequence_edited))

    def current_id(self) -> str:
        item = self.results.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _item_clicked(self, item: QListWidgetItem) -> None:
        self.preview_requested.emit(0)

    def _preview_candidate(self, candidate_id: str) -> None:
        for index in range(self.results.count()):
            item = self.results.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == candidate_id:
                self.results.setCurrentItem(item)
                break
        self.preview_requested.emit(1)

    def _preview_current(self) -> None:
        self.preview_requested.emit(1)

    def _accept_current(self) -> None:
        cue_id = self.current_id()
        if cue_id:
            self.add_to_bin_requested.emit(cue_id)

    def _ignore_current(self) -> None:
        cue_id = self.current_id()
        if cue_id:
            self.ignore_requested.emit(cue_id)

    def _pick_xml(self) -> None:
        # Start beside the original recording, where same-name XML files live.
        start = ""
        if self._project is not None and str(self._project.media.path or ""):
            start = str(Path(self._project.media.path).parent)
        path, _filter = QFileDialog.getOpenFileName(self, tr('导入弹幕 XML'), start, "Danmaku XML (*.xml);;All files (*.*)")
        if path:
            self.xml_selected.emit(path)

    def _analyze(self) -> None:
        mode = str(self.mode.currentData() or "auto")
        if mode == "auto":
            mode = self._auto_mode
        if mode == "none":
            bind_text(self.status, '请先识别字幕或导入弹幕 XML')
            return
        self.analyze_button.setEnabled(False)
        self._analyzing = True
        bind_text(self.analyze_button, '正在分析…')
        self.cancel_button.show()
        self.analysis_progress.show()
        self.progress_label.show()
        self._analysis_note = ""
        ai_service, ai_model = self.selected_ai()
        self.analyze_requested.emit(
            {
                "mode": mode,
                "target_count": int(self.count_box.value()),
                "min_seconds": int(self.min_box.value()),
                "max_seconds": int(self.max_box.value()),
                "ai_service": ai_service,
                "model": ai_model,
                "danmaku_offset_ms": round(self.offset_box.value()*1000),
            }
        )

    def _analyze_current_subtitles(self) -> None:
        """Compact empty-state action for subtitle-only projects."""
        if not self._project or not (analysis_transcript_cues(self._project) or self._project.cues):
            bind_text(self.status, '当前没有可分析的字幕')
            return
        self.mode.setCurrentIndex(max(0, self.mode.findData("subtitles")))
        self._analyze()

    def analysis_finished(self) -> None:
        self._analyzing = False
        self.analysis_progress.hide()
        self.progress_label.hide()
        self.analyze_button.setEnabled(self._auto_mode != "none")
        (bind_text(self.analyze_button, '重新分析') if self.results.count()
         else bind_text(self.analyze_button, '分析录播'))
        self.cancel_button.setEnabled(True)
        self.cancel_button.hide()

    def refresh_theme_palette(self) -> None:
        theme = theme_definition(theme_key())
        # One box per card: the list itself draws no frame or fill.
        list_qss = (
            f"QListWidget {{ color: {theme.text}; background: transparent; "
            f"border: none; padding: 0 4px 0 0; }} "
            f"QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px 1px 2px 0; }} "
            f"QScrollBar::handle:vertical {{ background: {theme.border}; border-radius: 3px; min-height: 28px; }} "
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        self.results.setStyleSheet(list_qss)
        self.bin.setStyleSheet(list_qss)


def _clock_range(start_ms: int, end_ms: int) -> str:
    def clock(ms: int) -> str:
        total = max(0, int(ms)) // 1000
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        fraction=f'.{int(ms)%1000:03d}' if int(ms)%1000 else ''
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}{fraction}"
        return f"{minutes:02d}:{seconds:02d}{fraction}"
    return f"{clock(start_ms)} – {clock(end_ms)}"


def _duration_label(ms: int) -> str:
    if int(ms)%1000:
        return tr('{seconds} 秒',seconds=f'{max(0,int(ms))/1000:.3f}'.rstrip('0').rstrip('.'))
    seconds = max(0, int(ms)) // 1000
    if seconds < 60:
        return tr('{seconds} 秒',seconds=seconds)
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}分{sec:02d}秒" if sec else f"{minutes}分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}小时{minutes:02d}分"
