"""Clip assistant panel, highlight bin, and analysis worker."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
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
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .studio_edit_sequence import HighlightCandidate, sequence_of
from .studio_highlight_analyzer import HighlightSkillAdapter, analyze_highlights
from .studio_project import SubtitleProject, analysis_transcript_cues
from .theme_manager import theme_key
from .ui_theme import theme_definition

from .i18n_widgets import add_combo_item
from .i18n import bind_text

from .i18n import tr


class HighlightAnalyzeWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, project: SubtitleProject, options: dict, parent=None) -> None:
        super().__init__(parent)
        self._project = project
        self._options = dict(options)

    def run(self) -> None:
        try:
            from .processes import process_action_scope

            with process_action_scope("studio.clip-assistant.analyze"):
                result = analyze_highlights(
                    self._project,
                    cancel_check=self.isInterruptionRequested,
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
    if accent:
        # 为什么值得剪：主题 accent 左缘 + 同族浅底，视觉权重最高但不做重色块。
        frame.setStyleSheet(
            f"QFrame#highlightSectionWhy {{"
            f" background: {soft}; border: 1px solid {border};"
            f" border-left: 3px solid {edge}; border-radius: 6px; }}"
            " QLabel { background: transparent; border: none; }"
        )
    else:
        # 发生了什么：轻一档——无填充、细边、无 accent，避免与上方 section 同级。
        frame.setStyleSheet(
            f"QFrame#highlightSectionWhat {{"
            f" background: transparent; border: 1px solid {border};"
            f" border-left: 3px solid {border}; border-radius: 6px; }}"
            " QLabel { background: transparent; border: none; }"
        )
    box = QVBoxLayout(frame)
    box.setContentsMargins(9, 6, 9, 6)
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

    def __init__(self, candidate: HighlightCandidate, parent=None) -> None:
        super().__init__(parent)
        self._owner_list = parent if isinstance(parent, QListWidget) else None
        self.candidate_id = candidate.id
        self.setObjectName("highlightCandidateCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        theme = theme_definition(theme_key())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(5)
        heading = QHBoxLayout()
        badge = QLabel(f"{candidate.grade or '推荐'}  {round(candidate.score * 100)}")
        badge.setObjectName("highlightGrade")
        heading.addWidget(badge)
        heading.addStretch(1)
        span_ms = max(0, candidate.source_out_ms - candidate.source_in_ms)
        clock = QLabel(
            f"{_clock_range(candidate.source_in_ms, candidate.source_out_ms)} · {_duration_label(span_ms)}"
        )
        clock.setObjectName("contextEmpty")
        bind_text(clock, '建议剪辑范围（包含铺垫、爆点与收尾）', property='toolTip')
        heading.addWidget(clock)
        layout.addLayout(heading)

        # 2026-09-18 信息层级（用户规约）+ 2026-09-19 P1：hook 事件钩子 →
        # 为什么值得剪（视觉最重）→ 发生了什么 → 单行统计（簇级口径）；
        # 行数放宽避免解释被挤没；原始弹幕/引用/完整上下文只进详情。
        hook_text = QLabel(candidate.hook or candidate.title or "等待补充事件摘要")
        hook_text.setObjectName("highlightTitle")
        hook_text.setWordWrap(True)
        _clamp_label_lines(hook_text, 2)
        layout.addWidget(hook_text)

        why = _section_frame(
            "为什么值得剪",
            candidate.clip_reason or candidate.reason or "等待补充编辑判断",
            theme, accent=True,
        )
        _clamp_label_lines(why.body, 6)
        layout.addWidget(why)

        what = _section_frame(
            "发生了什么",
            candidate.event_summary or candidate.hook or candidate.title or "",
            theme, accent=False,
        )
        _clamp_label_lines(what.body, 5)
        layout.addWidget(what)

        # 底部统计=簇级唯一口径（2026-09-19 P1：卡片/详情/文案同源；
        # 422=簇累计有效条数、峰值取簇内最高倍数窗、笑/叹为真实条数——
        # 旧"hits 次数"与 best 单窗 raw 数不再混入）。
        summary_bits = []
        signal = candidate.danmaku_signal or {}
        if isinstance(signal, dict) and (signal.get("usable_total") or signal.get("raw_count")):
            usable = signal.get("usable_total") or signal.get("raw_count")
            bits = [f"弹幕{usable}条"]
            if signal.get("windows", 1) > 1:
                bits.append(f"{signal['windows']}个热窗")
            if signal.get("peak_spike"):
                bits.append(f"峰值{signal['peak_spike']}x")
            if signal.get("chaos_count"):
                bits.append(f"惊叹{signal['chaos_count']}条")
            if signal.get("funny_count"):
                bits.append(f"笑声{signal['funny_count']}条")
            summary_bits.append("观众反应 " + " · ".join(str(bit) for bit in bits))
        elif candidate.danmaku_evidence or candidate.subtitle_evidence:
            summary_bits.append(
                f"证据 弹幕{len(candidate.danmaku_evidence)} · 字幕{len(candidate.subtitle_evidence)}"
            )
        if candidate.origin == "local":
            summary_bits.append("本地分析 · 事件待核实")
        if candidate.context_required:
            summary_bits.append(f"上下文 {candidate.context_required}")
        evidence_summary = QLabel("   ".join(summary_bits))
        evidence_summary.setObjectName("contextEmpty")
        evidence_summary.setWordWrap(True)
        evidence_summary.setVisible(bool(summary_bits))
        bind_text(evidence_summary, '统计为候选范围簇级口径：有效条数已剔除广告/例行弹幕；峰值=簇内最高倍数窗；惊叹/笑声为弹幕条数（非命中次数）。', property='toolTip')
        layout.addWidget(evidence_summary)

        signal_in = candidate.signal_in_ms if candidate.signal_in_ms is not None else candidate.source_in_ms
        signal_out = candidate.signal_out_ms if candidate.signal_out_ms is not None else candidate.source_out_ms
        # 标题行已展示建议保留范围；核心窗与其一致时不再重复整行
        # （三十一轮 agy：时间区间同卡三重机械重复）。
        if (signal_in, signal_out) != (candidate.source_in_ms, candidate.source_out_ms):
            ranges = bind_text(QLabel(), '核心 {value0} · 建议保留 {value1}', value0=_clock_range(signal_in, signal_out), value1=_clock_range(candidate.source_in_ms, candidate.source_out_ms))
            ranges.setObjectName("contextEmpty")
            layout.addWidget(ranges)
        evidence_source = candidate.danmaku_evidence
        if isinstance(evidence_source, str):
            evidence_source = [line for line in evidence_source.splitlines() if line.strip()]
        evidence_lines = [line for line in evidence_source[:3] if str(line).strip()]
        for quote in candidate.quotes[:3]:
            # Skip quotes already surfaced by the evidence rows above.
            if any(quote in line for line in evidence_lines):
                continue
            evidence_lines.append(f"\u201c{quote}\u201d")
        evidence = QLabel("\n".join(evidence_lines))
        evidence.setObjectName("highlightEvidence")
        evidence.setWordWrap(True)
        evidence.setVisible(False)  # 原始弹幕默认不占主卡片，随详情展开
        # 2026-09-19 P1：详情展开时同步显示完整字幕上下文（"发生了什么"
        # 的可追溯证据；此前 evidence 永不可见是存量 bug）。
        context_lines = [line for line in (candidate.subtitle_context or [])[:14] if str(line).strip()]
        context_block = QLabel(
            ("信号范围字幕摘录：\n" + "\n".join(context_lines)) if context_lines else ""
        )
        context_block.setObjectName("highlightEvidence")
        context_block.setWordWrap(True)
        context_block.setVisible(False)
        details = QLabel("\n".join(filter(None, (
            f"建议范围：{_clock_range(candidate.source_in_ms, candidate.source_out_ms)}",
            f"上下文范围：{_clock_range(candidate.context_in_ms, candidate.context_out_ms)}"
            if candidate.context_in_ms is not None and candidate.context_out_ms is not None else "",
            f"信号窗口：{_clock_range(signal_in, signal_out)}",
            f"开头：{candidate.hook}" if candidate.hook else "",
            f"剪辑：{candidate.edit_direction}" if candidate.edit_direction else "",
            f"字幕重点：{'、'.join(candidate.subtitle_emphasis)}" if candidate.subtitle_emphasis else "",
            f"风险：{'、'.join(candidate.risk_notes)}" if candidate.risk_notes else "",
        ))))
        details.setObjectName("highlightDetails")
        details.setWordWrap(True)
        details.hide()
        actions = QGridLayout()
        actions.setSpacing(5)
        preview = QPushButton("预览")
        accept = QPushButton("加入剪辑")
        ignore = QPushButton("忽略")
        detail = QPushButton("详情")
        self._action_buttons=(preview,accept,ignore,detail)
        self._action_grid=actions
        self._action_columns=0
        for button in self._action_buttons:
            button.setObjectName("studioPrimary" if button is accept else "studioButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(0)
        preview.clicked.connect(lambda: self.preview_requested.emit(self.candidate_id))
        accept.clicked.connect(lambda: self.accept_requested.emit(self.candidate_id))
        ignore.clicked.connect(lambda: self.ignore_requested.emit(self.candidate_id))
        detail.clicked.connect(lambda: self._toggle_details(details, evidence, context_block))
        # Footer order: content (title/reason/evidence) first, actions last —
        # buttons mid-card cut the reading flow and orphan the evidence block.
        layout.addWidget(evidence)
        layout.addWidget(context_block)
        layout.addWidget(details)
        layout.addLayout(actions)
        self._reflow_actions()

    def _reflow_actions(self):
        columns=4 if self.width()>=520 else 2
        if columns==self._action_columns:return False
        self._action_columns=columns
        while self._action_grid.count():self._action_grid.takeAt(0)
        for index,button in enumerate(self._action_buttons):
            self._action_grid.addWidget(button,index//columns,index%columns)
        for column in range(4):self._action_grid.setColumnStretch(column,1 if column<columns else 0)
        self.updateGeometry()
        return True

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'_action_grid'):return
        self._reflow_actions()
        self.layout().activate()
        owner=self._owner_list
        if isinstance(owner,QListWidget):
            for index in range(owner.count()):
                item=owner.item(index)
                if owner.itemWidget(item) is self:
                    size=QSize(0,self.sizeHint().height())
                    if item.sizeHint()!=size:item.setSizeHint(size)
                    break

    def _toggle_details(self, details: QLabel, evidence: QLabel | None = None, context_block: QLabel | None = None) -> None:
        visible = not details.isVisible()
        details.setVisible(visible and bool(details.text()))
        # 2026-09-19 P1：原始弹幕证据与完整字幕上下文随详情一起展开。
        if evidence is not None:
            evidence.setVisible(visible and bool(evidence.text()))
        if context_block is not None:
            context_block.setVisible(visible and bool(context_block.text()))
        self.updateGeometry()
        owner = self._owner_list
        if not isinstance(owner, QListWidget):
            return
        for index in range(owner.count()):
            item = owner.item(index)
            if owner.itemWidget(item) is self:
                item.setSizeHint(QSize(0, self.sizeHint().height()))
                break
        owner = self._owner_list
        if not isinstance(owner, QListWidget):
            return
        for index in range(owner.count()):
            item = owner.item(index)
            if owner.itemWidget(item) is self:
                item.setSizeHint(QSize(0, self.sizeHint().height()))
                break

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        owner = self._owner_list
        if isinstance(owner, QListWidget):
            available = owner.viewport().width()
            if available > 0:
                hint.setWidth(min(hint.width(), available))
                wrapped=self.layout().totalHeightForWidth(available)
                if wrapped>0:hint.setHeight(max(hint.height(),wrapped))
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
        layout.setContentsMargins(10, 7, 7, 7)
        layout.setSpacing(6)
        copy_block = QVBoxLayout()
        copy_block.setSpacing(1)
        title = QLabel(f"✓ {candidate.title}")
        title.setObjectName("highlightTitle")
        title.setWordWrap(True)
        clock = QLabel(_clock_range(candidate.source_in_ms, candidate.source_out_ms))
        clock.setObjectName("contextEmpty")
        copy_block.addWidget(title)
        copy_block.addWidget(clock)
        layout.addLayout(copy_block, 1)
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
            button.setFixedSize(34, 34)
            layout.addWidget(button)
        up.setEnabled(index > 0)
        down.setEnabled(index < count - 1)
        up.clicked.connect(lambda: self.move_requested.emit(self.candidate_id, -1))
        down.clicked.connect(lambda: self.move_requested.emit(self.candidate_id, 1))
        remove.clicked.connect(lambda: self.remove_requested.emit(self.candidate_id))


class HighlightAssistantPanel(QWidget):
    preview_requested = Signal(int)
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

        config_header = QHBoxLayout()
        self.config_summary = QLabel("数据与分析设置")
        self.config_summary.setObjectName("contextEmpty")
        config_header.addWidget(self.config_summary, 1)
        self.analyze_button = QPushButton("分析录播")
        self.analyze_button.setObjectName("studioPrimary")
        self.analyze_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.analyze_button.clicked.connect(self._analyze)
        config_header.addWidget(self.analyze_button)
        self.config_toggle = QToolButton()
        self.config_toggle.setObjectName("styleSectionHeader")
        bind_text(self.config_toggle, '分析设置')
        self.config_toggle.setCheckable(True)
        self.config_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.config_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.config_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_toggle.setChecked(True)
        bind_text(self.config_toggle, '收起')
        self.config_toggle.setArrowType(Qt.ArrowType.DownArrow)
        config_header.addWidget(self.config_toggle)
        layout.addLayout(config_header)

        self.config_body = QWidget()
        config_body_layout = QVBoxLayout(self.config_body)
        config_body_layout.setContentsMargins(0, 0, 0, 0)
        config_body_layout.setSpacing(8)
        config_body_layout.addWidget(self.status)

        data = QGroupBox("数据")
        data_layout = QVBoxLayout(data)
        self.subtitle_status = QLabel("字幕：0 条（当前工程）")
        self.subtitle_status.setObjectName("contextEmpty")
        self.subtitle_status.setWordWrap(True)
        data_layout.addWidget(self.subtitle_status)
        self.xml_status = QLabel("弹幕 XML：未匹配")
        self.xml_status.setObjectName("contextEmpty")
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
        xml_actions.addWidget(self.xml_button, 1)
        xml_actions.addWidget(self.xml_unbind_button, 1)
        data_layout.addLayout(xml_actions)
        config_body_layout.addWidget(data)

        setup = QGroupBox("分析")
        form = QFormLayout(setup)
        self.mode = QComboBox()
        self.mode.setObjectName("studioCombo")
        self.mode.addItem("自动", "auto")
        self.mode.addItem("字幕 + 弹幕", "subtitles_xml")
        self.mode.addItem("仅字幕", "subtitles")
        self.mode.addItem("仅弹幕 XML", "xml")
        mode_block = QVBoxLayout()
        mode_block.setSpacing(2)
        mode_block.addWidget(self.mode)
        self.detected_data = QLabel("自动分析：")
        self.detected_data.setObjectName("contextEmpty")
        self.detected_data.setWordWrap(True)
        mode_block.addWidget(self.detected_data)
        form.addRow("分析方式", mode_block)
        self.count_box = QSpinBox()
        self.count_box.setRange(3, 50)
        self.count_box.setValue(20)
        form.addRow("候选数量", self.count_box)
        length = QHBoxLayout()
        self.min_box = QSpinBox()
        self.min_box.setRange(8, 300)
        self.min_box.setValue(30)
        self.max_box = QSpinBox()
        # 3600s：长事件（整局比赛/完整剧情线 30 分钟以上）也要能一键给全范围。
        self.max_box.setRange(10, 3600)
        self.max_box.setValue(180)
        length.addWidget(self.min_box)
        length.addWidget(QLabel("–"))
        length.addWidget(self.max_box)
        length.addWidget(QLabel("秒"))
        form.addRow("建议长度", length)
        self.min_box.valueChanged.connect(self._sync_length_boxes)
        self.max_box.valueChanged.connect(self._sync_length_boxes)
        self.ai_service_combo = QComboBox()
        self.ai_service_combo.setObjectName("studioCombo")
        self.ai_service_combo.currentIndexChanged.connect(self._on_ai_service_changed)
        form.addRow("分析服务", self.ai_service_combo)
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setObjectName("studioCombo")
        self.ai_model_combo.currentIndexChanged.connect(self._on_ai_model_changed)
        form.addRow("分析模型", self.ai_model_combo)
        config_body_layout.addWidget(setup)

        # 四十四轮：自动剪口播气口——长静音（气口）检出+波纹删除（可撤销）。
        autocut = QGroupBox("压缩口播停顿")
        autocut_form = QFormLayout(autocut)
        self.autocut_mode = QComboBox()
        self.autocut_mode.addItem('智能口播 · 本地人声检测', 'smart')
        self.autocut_mode.addItem('仅静音 · 低音量检测', 'silence')
        autocut_form.addRow('检测方式', self.autocut_mode)
        self.autocut_audio_track = QComboBox()
        self.autocut_audio_track.addItem('当前可听音轨混音（保护所有人声）', '')
        autocut_form.addRow('分析音轨', self.autocut_audio_track)
        self.autocut_preset = QComboBox()
        for label, values in [('自然',(1.,.2)),('保守',(1.8,.3)),('紧凑',(.7,.15))]:
            self.autocut_preset.addItem(label, values)
        autocut_form.addRow('停顿节奏',self.autocut_preset)
        advanced_toggle = QToolButton()
        bind_text(advanced_toggle, '调整停顿时长与保护量')
        advanced_toggle.setCheckable(True)
        autocut_form.addRow(advanced_toggle)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced_form.setContentsMargins(0,0,0,0)
        autocut_form.addRow(advanced)
        advanced.hide()
        advanced_toggle.toggled.connect(advanced.setVisible)
        self.autocut_min_silence = QDoubleSpinBox()
        self.autocut_min_silence.setRange(0.5, 60.0)
        self.autocut_min_silence.setDecimals(1)
        self.autocut_min_silence.setValue(1.0)
        self.autocut_min_silence.setSuffix(" 秒")
        bind_text(self.autocut_min_silence, '没有检测到人声的连续停顿至少达到此时长才成为候选', property='toolTip')
        advanced_form.addRow("停顿时长 ≥", self.autocut_min_silence)
        self.autocut_padding = QDoubleSpinBox()
        self.autocut_padding.setRange(0.1, 3.0)
        self.autocut_padding.setDecimals(2)
        self.autocut_padding.setValue(0.20)
        self.autocut_padding.setSuffix(" 秒")
        bind_text(self.autocut_padding, '每个气口两侧保留的呼吸余量', property='toolTip')
        advanced_form.addRow("每侧各保留", self.autocut_padding)
        self.autocut_preset.currentIndexChanged.connect(lambda _: (
            self.autocut_min_silence.setValue(self.autocut_preset.currentData()[0]),
            self.autocut_padding.setValue(self.autocut_preset.currentData()[1])))
        self.autocut_detect_button = QPushButton("检测停顿")
        self.autocut_detect_button.setObjectName("studioButton")
        self.autocut_detect_button.clicked.connect(self._autocut_detect_clicked)
        self.autocut_apply_button = QPushButton("应用已勾选停顿")
        self.autocut_apply_button.setObjectName("studioPrimary")
        self.autocut_apply_button.hide()
        self.autocut_apply_button.clicked.connect(self._autocut_apply_clicked)
        autocut_buttons = QHBoxLayout()
        autocut_buttons.addWidget(self.autocut_detect_button, 1)
        autocut_buttons.addWidget(self.autocut_apply_button, 1)
        self.autocut_cancel_button = QPushButton('取消检测')
        self.autocut_cancel_button.hide()
        self.autocut_cancel_button.clicked.connect(self.autocut_cancel_requested.emit)
        autocut_buttons.addWidget(self.autocut_cancel_button)
        autocut_form.addRow("", autocut_buttons)
        self.autocut_status = QLabel("本地分析当前时间轴；背景声音可保留。先查看/试听候选，再一次应用；Ctrl+Z 撤销整批。混合音轨中的游戏台词同样保护。")
        self.autocut_status.setObjectName("contextEmpty")
        self.autocut_status.setWordWrap(True)
        autocut_form.addRow("", self.autocut_status)
        self.autocut_results = QListWidget()
        self.autocut_results.setMinimumHeight(110)
        self.autocut_results.setMaximumHeight(210)
        self.autocut_results.hide()
        self.autocut_results.itemChanged.connect(self._autocut_selection_changed)
        autocut_form.addRow(self.autocut_results)
        self.autocut_review_controls = QWidget()
        review_buttons = QHBoxLayout(self.autocut_review_controls)
        review_buttons.setContentsMargins(0,0,0,0)
        for label, callback in [('全选',lambda:self._autocut_select_all(True)),
                                 ('全不选',lambda:self._autocut_select_all(False)),
                                 ('试听当前剪口',self._autocut_preview_clicked)]:
            button=QPushButton(label);button.clicked.connect(callback);review_buttons.addWidget(button)
        self.autocut_review_controls.hide()
        autocut_form.addRow(self.autocut_review_controls)
        self._autocut_ranges: list[tuple[int, int]] = []
        layout.addWidget(self.config_body)
        # Audio pause detection remains available without captions/danmaku.
        layout.addWidget(autocut)
        self.config_toggle.toggled.connect(self._toggle_config)
        self._restore_ai_selection()

        self.skill_label = QLabel("Skill：正在查找直播切片规则")
        self.skill_label.setObjectName("contextEmpty")
        self.skill_label.setWordWrap(True)
        config_body_layout.addWidget(self.skill_label)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("studioButton")
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        config_header.addWidget(self.cancel_button)
        self.io_button = QPushButton("将入点/出点选区加入候选")
        self.io_button.setObjectName("studioButton")
        self.io_button.clicked.connect(self.add_mark_in_out_requested.emit)
        config_body_layout.addWidget(self.io_button)

        self.candidates_body = QWidget()
        candidates_layout = QVBoxLayout(self.candidates_body)
        candidates_layout.setContentsMargins(0, 0, 0, 0)
        candidates_layout.setSpacing(7)
        self.candidates_heading = self._heading("剪辑候选")
        candidates_layout.addWidget(self.candidates_heading)
        candidates_separator = QFrame()
        candidates_separator.setFrameShape(QFrame.Shape.HLine)
        candidates_separator.setFrameShadow(QFrame.Shadow.Plain)
        candidates_layout.addWidget(candidates_separator)
        # 候选区常驻：没有候选时也保留分隔与占位说明，而不是整块消失
        # （三十一轮用户反馈：收起后只剩"分析录播"，面板像坏了一样空白）。
        self.candidates_empty = QLabel(
            "暂无剪辑候选。\n点击「分析录播」生成建议片段；满意的片段用「加入剪辑」收进候选箱。"
        )
        self.candidates_empty.setObjectName("contextEmpty")
        self.candidates_empty.setWordWrap(True)
        candidates_layout.addWidget(self.candidates_empty)
        theme = theme_definition(theme_key())
        list_qss = (
            f"QListWidget {{ color: {theme.text}; background: {theme.surface}; "
            f"border: 1px solid {theme.border}; border-radius: 8px; }}"
        )
        self.results = SmoothCardList()
        self.results.setMinimumHeight(190)
        self.results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setStyleSheet(list_qss)
        self.results.itemClicked.connect(self._item_clicked)
        candidates_layout.addWidget(self.results, 1)
        self.bin_header = QWidget()
        bin_header_layout = QHBoxLayout(self.bin_header)
        bin_header_layout.setContentsMargins(0, 0, 0, 0)
        bin_header_layout.setSpacing(6)
        self.bin_label = self._heading("剪辑候选箱")
        bin_header_layout.addWidget(self.bin_label, 1)
        self.clear_bin_button = QPushButton("清空候选")
        self.clear_bin_button.setObjectName("studioButton")
        self.clear_bin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_bin_button.clicked.connect(self.clear_bin_requested.emit)
        bin_header_layout.addWidget(self.clear_bin_button)
        self.bin_header.hide()
        candidates_layout.addWidget(self.bin_header)
        self.bin = SmoothCardList()
        self.bin.setMinimumHeight(72)
        self.bin.setMaximumHeight(190)
        self.bin.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bin.setStyleSheet(list_qss)
        self.bin.hide()
        candidates_layout.addWidget(self.bin)
        self.generate_row_host = QWidget()
        generate_row = QHBoxLayout(self.generate_row_host)
        generate_row.setContentsMargins(0, 0, 0, 0)
        self.generate_button = QPushButton("生成剪辑")
        self.restore_button = QPushButton("返回完整录播")
        self.generate_button.setObjectName("studioPrimary")
        self.restore_button.setObjectName("studioButton")
        self.generate_button.clicked.connect(self.generate_requested.emit)
        self.restore_button.clicked.connect(self.restore_requested.emit)
        generate_row.addWidget(self.generate_button)
        generate_row.addWidget(self.restore_button)
        self.generate_row_host.hide()
        candidates_layout.addWidget(self.generate_row_host)
        self.candidates_body.hide()
        layout.addWidget(self.candidates_body, 1)
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

    def _toggle_config(self, expanded: bool) -> None:
        self._stage = "settings" if expanded else "candidates"
        self.config_body.setVisible(bool(expanded))
        (bind_text(self.config_toggle, '收起') if expanded else bind_text(self.config_toggle, '分析设置'))
        self.config_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
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

    def _apply_stage(self) -> None:
        """Single source of truth for settings/candidates visibility.

        The candidates zone is a permanent section (heading + separator +
        placeholder when empty). Only the settings area folds, driven by the
        low-key 「分析设置」 toggle; every refresh path funnels through here
        so a later set_project_status never re-expands settings on top of a
        candidate list after analysis collapsed it.
        """
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
        self.config_body.setVisible(not compact_empty and form_expanded)
        self.config_summary.setVisible(not compact_empty and not form_expanded)
        self.config_toggle.setVisible(not compact_empty)
        self.analyze_button.setVisible(not compact_empty)

    def active_stage(self) -> str:
        return self._stage

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("contextEmpty")
        return label

    def _refresh_skill(self) -> None:
        skill = HighlightSkillAdapter.discover()
        if skill.found:
            bind_text(self.skill_label, '发现本地切片规则；是否采用以切片分析结果为准。口播停顿使用本地音频检测。')
        else:
            bind_text(self.skill_label, '切片分析使用内置规则；口播停顿使用本地音频检测。')

    def set_project_status(self, project: SubtitleProject | None, danmaku_path: str = "") -> None:
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
        self._danmaku_path = str(danmaku_path or "")
        if project is None:
            bind_text(self.status, '尚未打开工程')
            self._refresh_data_mode()
            return
        if not str(project.media.path or "").strip():
            bind_text(self.status, '空白工程。先导入视频或音频，再导入弹幕 XML 或字幕。')
        else:
            # Asset counts live once in the 数据 group — no triple repetition.
            self.status.setText("")
        self.status.setVisible(bool(self.status.text()))
        self._refresh_skill()
        self._refresh_data_mode()
        candidates = sequence_of(project).clip_candidates
        signature = json.dumps(
            [candidate.to_dict() for candidate in candidates],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if signature != self._candidate_signature:
            self.reload_candidates(candidates)
            self._candidate_signature = signature
        self._append_analysis_note()

    def _refresh_data_mode(self) -> None:
        cue_count = (
            len(analysis_transcript_cues(self._project)) or len(self._project.cues)
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
        bind_text(self.detected_data, '自动分析：{automatic}（{xml_text}）', automatic=tr(automatic), xml_text=tr(xml_text))
        bind_text(self.config_summary, '{automatic} · {value1} 个 · {value2}–{value3} 秒', automatic=tr(automatic), value1=self.count_box.value(), value2=self.min_box.value(), value3=self.max_box.value())
        available = self._auto_mode != "none"
        self.analyze_button.setEnabled(available)
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
        from .llm_config import AI_SERVICE_SPECS
        from .provider_registry import GLOBAL_PROVIDER_REGISTRY

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
            from .provider_registry import GLOBAL_PROVIDER_REGISTRY

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

    def set_analysis_note(self, llm_status: str, llm_error: str = "") -> None:
        """Surface why AI ranking was skipped; shown until the next analysis."""
        if str(llm_status or "") == "local_fallback":
            error = " ".join(str(llm_error or "").split())[:120]
            self._analysis_note = (
                f"AI 排序不可用，已使用本地分析结果（原因：{error or '未知'}）。"
                "候选理由为原始弹幕/字幕证据。"
            )
        else:
            self._analysis_note = ""
        self._append_analysis_note()

    def _append_analysis_note(self) -> None:
        if self._project is None:
            return
        base = self.status.text()
        # Strip the previously embedded note so a cleared note really disappears.
        if self._last_note and self._last_note in base:
            base = base.replace("\n" + self._last_note, "").replace(self._last_note, "")
        if self._analysis_note:
            base = f"{base}\n{self._analysis_note}" if base else self._analysis_note
        self.status.setText(base)
        self.status.setVisible(bool(base))
        self._last_note = self._analysis_note

    def set_xml_discovery(
        self,
        candidates: tuple[str, ...] | list[str],
        bound_path: str = "",
        *,
        automatic: bool = False,
    ) -> None:
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

    def reload_candidates(self, candidates: list[HighlightCandidate]) -> None:
        self.results.clear()
        self.bin.clear()
        accepted = [candidate for candidate in candidates if candidate.status == "accepted"]
        for candidate in candidates:
            candidate.validate()
            if candidate.status == "ignored":
                continue
            clock = _clock_range(candidate.source_in_ms, candidate.source_out_ms)
            spike = ""
            signal = candidate.danmaku_signal or {}
            if signal.get("peak") and signal.get("baseline"):
                try:
                    spike = f" · 弹幕 {float(signal['peak']) / max(1.0, float(signal['baseline'])):.1f}×"
                except (TypeError, ValueError):
                    spike = ""
            label = f"{int(candidate.score * 100):02d}  {candidate.title}\n{clock}{spike}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, candidate.id)
            self.results.addItem(item)
            card = HighlightCandidateCard(candidate, self.results)
            card.preview_requested.connect(self._preview_candidate)
            card.accept_requested.connect(self.add_to_bin_requested.emit)
            card.ignore_requested.connect(self.ignore_requested.emit)
            item.setSizeHint(QSize(0, card.sizeHint().height()))
            self.results.setItemWidget(item, card)
        for index, candidate in enumerate(accepted):
            bin_item = QListWidgetItem()
            bin_item.setData(Qt.ItemDataRole.UserRole, candidate.id)
            self.bin.addItem(bin_item)
            card = HighlightBinCard(candidate, index, len(accepted), self.bin)
            card.remove_requested.connect(self.remove_from_bin_requested.emit)
            card.move_requested.connect(self.candidate_move_requested.emit)
            bin_item.setSizeHint(QSize(0, card.sizeHint().height()))
            self.bin.setItemWidget(bin_item, card)
        bind_text(self.bin_label, '剪辑候选箱  {value0}', value0=self.bin.count())
        has_bin = self.bin.count() > 0
        self.bin_header.setVisible(has_bin)
        self.bin.setVisible(has_bin)
        self.generate_row_host.setVisible(has_bin)
        has_candidates = self.results.count() > 0
        bind_text(self.candidates_heading, '剪辑候选 · {value0} 条（按推荐度排序）', value0=self.results.count())
        self._show_stage("candidates" if has_candidates else "settings")

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
        path, _filter = QFileDialog.getOpenFileName(self, tr('导入弹幕 XML'), "", "Danmaku XML (*.xml);;All files (*.*)")
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
        bind_text(self.analyze_button, '正在分析…')
        self.cancel_button.show()
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
        self.analyze_button.setEnabled(self._auto_mode != "none")
        bind_text(self.analyze_button, '分析录播')
        self.cancel_button.setEnabled(True)
        self.cancel_button.hide()

    def refresh_theme_palette(self) -> None:
        theme = theme_definition(theme_key())
        list_qss = (
            f"QListWidget {{ color: {theme.text}; background: {theme.surface}; "
            f"border: 1px solid {theme.border}; border-radius: 8px; "
            f"padding: 2px 8px 2px 2px; }} "
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
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    return f"{clock(start_ms)} – {clock(end_ms)}"


def _duration_label(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    if seconds < 60:
        return f"{seconds}秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}分{sec:02d}秒" if sec else f"{minutes}分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}小时{minutes:02d}分"
