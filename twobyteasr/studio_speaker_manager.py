"""Speaker manager dialog (rename/merge speakers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QPointF, QSize, QEvent
from PySide6.QtGui import QColor, QTextLayout, QTextOption, QPalette, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
    QSizePolicy,
    QSpinBox,
)

from .studio_commands import (
    AssignSpeakerCommand,
    MergeSpeakerCommand,
    SetHostSpeakerCommand,
    SetSpeakerCommand,
    SetSpeakersVisibilityCommand,
    RecoverSpeakersCommand,
)
from .studio_cue_table import _speaker_color
from .studio_helpers import _format_ms
from .studio_theme import (
    StudioComboBox,
    apply_secondary_surface_theme,
    studio_message_box,
    _active_theme,
)
from .studio_widgets import _icon

from .i18n import bind_text

from .i18n import tr, join_text
from .i18n_widgets import add_combo_item, bind_item
from .speaker_names import display_speaker_name

if TYPE_CHECKING:
    from .studio_ui import SubtitleStudioPage


class _CandidateExcerptDelegate(QStyledItemDelegate):
    """Single lines center; longer excerpts wrap with their complete measured height."""
    @staticmethod
    def text_layout(text, font, width):
        layout = QTextLayout(text.replace("\n", "\u2028"), font)
        settings = QTextOption()
        settings.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(settings)
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width))
            line.setPosition(QPointF(0, y))
            y += line.height()
        layout.endLayout()
        return layout, y

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        width = self.parent().columnWidth(index.column())
        _layout, height = self.text_layout(opt.text, opt.font, width-16)
        return QSize(width, int(height+13))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        opt.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        rect = opt.rect.adjusted(8, 6, -8, -6)
        layout, _height = self.text_layout(text, opt.font, rect.width())
        painter.save()
        painter.setClipRect(rect)
        painter.setFont(opt.font)
        painter.setPen(opt.palette.color(QPalette.ColorRole.HighlightedText if opt.state & QStyle.StateFlag.State_Selected else QPalette.ColorRole.Text))
        if layout.lineCount() <= 1:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        else:
            layout.draw(painter, QPointF(rect.topLeft()))
        painter.restore()

class SpeakerManagerDialog(QDialog):
    def __init__(self, page: "SubtitleStudioPage"):
        super().__init__(page)
        self.page = page
        bind_text(self, '说话人管理', property='windowTitle')
        self.setObjectName("toolDialog")
        self.setMinimumSize(720, 480)
        self.resize(1040, 740)
        apply_secondary_surface_theme(self)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("contextDrawer")
        root.addWidget(self.tabs)
        existing = QWidget()
        self._style_panel(existing)
        layout = QVBoxLayout(existing)
        self.tabs.addTab(existing, "字幕样式")
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title = QLabel("说话人管理")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        note = QLabel("整理只改变字幕归属，不证明声纹相同。所有批量操作都可一次撤销；原识别记录保留。")
        note.setObjectName("studioSaveState")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(("选择", "ID", "名称", "字幕数", "总时长", "默认样式"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._checking_rows = False
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._load_selected)
        self.table.itemSelectionChanged.connect(self._selection_checks)
        self.table.itemChanged.connect(self._checkbox_selection)
        self.table.installEventFilter(self)
        selection = QHBoxLayout()
        self.speaker_filter = QLineEdit(); bind_text(self.speaker_filter, '筛选名称或标签', property='placeholderText')
        self.speaker_filter.textChanged.connect(self._filter_rows)
        selection.addWidget(self.speaker_filter,1)
        for title, mode in (('全选筛选结果','all'),('取消选择','none'),('反选筛选结果','invert')):
            button=QPushButton(title);button.clicked.connect(lambda _=False,m=mode:self._select_visible(m));selection.addWidget(button)
        self.selection_summary=QLabel();selection.addWidget(self.selection_summary)
        layout.addLayout(selection)
        layout.addWidget(self.table, 1)
        batch=QHBoxLayout()
        for title, action in (('归入游戏背景声','background'),('设为主要说话人','main'),('恢复原归属','restore')):
            button=QPushButton(title);button.clicked.connect(lambda _=False,a=action:self._batch(a));batch.addWidget(button)
        self.delete_identity_button=QPushButton('删除身份，字幕移到统一轨')
        self.delete_identity_button.clicked.connect(lambda:self._batch('identity_delete'));batch.addWidget(self.delete_identity_button)
        self.delete_captions_button=QPushButton('删除所选人物及字幕')
        self.delete_captions_button.clicked.connect(lambda:self._batch('delete'));batch.addWidget(self.delete_captions_button)
        layout.addLayout(batch)
        policy=QHBoxLayout()
        unified=QPushButton('全部合并为单轨');unified.clicked.connect(lambda:self._batch('single',all_rows=True));policy.addWidget(unified)
        policy.addWidget(QLabel('主要候选须超过原始发言数'))
        self.utterance_threshold=QSpinBox();self.utterance_threshold.setRange(1,1000)
        self.utterance_threshold.setValue(int(page.project.generation_metadata.get('speaker_organization',{}).get('threshold',10)))
        policy.addWidget(self.utterance_threshold)
        arrange=QPushButton('按任务原始统计整理');arrange.clicked.connect(self._apply_count_policy);policy.addWidget(arrange)
        policy.addStretch(1);layout.addLayout(policy)

        editor = QGridLayout()
        editor.setHorizontalSpacing(8)
        editor.setVerticalSpacing(7)
        editor.addWidget(QLabel("名称"), 0, 0)
        self.name_edit = QLineEdit()
        editor.addWidget(self.name_edit, 0, 1)
        editor.addWidget(QLabel("颜色"), 0, 2)
        self.color_button = QPushButton("选择颜色")
        self.color_button.setObjectName("studioButton")
        self.color_button.clicked.connect(self._choose_color)
        editor.addWidget(self.color_button, 0, 3)
        editor.addWidget(QLabel("默认样式"), 1, 0)
        self.style_combo = StudioComboBox()
        editor.addWidget(self.style_combo, 1, 1)
        # 三十八轮：diarization 说话人轨控制。隐藏=从成片/导出/高保真预览
        # 排除（编辑器保留可见）；试听=跳到该说话人代表性 Cue；仅保留=隐藏
        # 其它全部说话人（一步撤销）。
        self.visible_check = QCheckBox("在成片中显示此说话人的字幕")
        self.visible_check.stateChanged.connect(self._visibility_toggled)
        editor.addWidget(self.visible_check, 1, 2, 1, 2)
        self.apply_button = QPushButton("应用修改")
        self.apply_button.setObjectName("studioPrimary")
        self.apply_button.clicked.connect(self._apply_changes)
        editor.addWidget(self.apply_button, 2, 3)
        layout.addLayout(editor)

        actions = QHBoxLayout()
        actions.addWidget(QLabel("合并到"))
        self.merge_target = StudioComboBox()
        actions.addWidget(self.merge_target, 1)
        self.merge_button = QPushButton("合并所选说话人")
        self.merge_button.setObjectName("studioButton")
        self.merge_button.setIcon(_icon("fa5s.compress-arrows-alt"))
        self.merge_button.clicked.connect(lambda:self._batch('merge',target=str(self.merge_target.currentData() or '')))
        actions.addWidget(self.merge_button)
        self.assign_button = QPushButton("将选中字幕归给此人")
        self.assign_button.setObjectName("studioButton")
        self.assign_button.setIcon(_icon("fa5s.user-check"))
        self.assign_button.clicked.connect(self._assign_selected_cues)
        actions.addWidget(self.assign_button)
        close = QPushButton("完成")
        close.setObjectName("studioPrimary")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)

        track_actions = QHBoxLayout()
        self.preview_button = QPushButton("试听代表性语音")
        self.preview_button.setObjectName("studioButton")
        self.preview_button.setIcon(_icon("fa5s.play"))
        bind_text(self.preview_button, '跳到该说话人最长的一条字幕并播放', property='toolTip')
        self.preview_button.clicked.connect(self._preview_representative)
        track_actions.addWidget(self.preview_button)
        self.host_button = QPushButton("设为主播")
        self.host_button.setObjectName("studioButton")
        self.host_button.setIcon(_icon("fa5s.star"))
        bind_text(self.host_button, '人工指定主讲说话人（不做自动身份推断）', property='toolTip')
        self.host_button.clicked.connect(self._set_host)
        track_actions.addWidget(self.host_button)
        self.keep_only_button = QPushButton("仅保留此说话人的字幕")
        self.keep_only_button.setObjectName("studioButton")
        self.keep_only_button.setIcon(_icon("fa5s.filter"))
        bind_text(self.keep_only_button, '隐藏其它全部说话人（成片与导出不再包含；可撤销）', property='toolTip')
        self.keep_only_button.clicked.connect(self._keep_only)
        track_actions.addWidget(self.keep_only_button)
        track_actions.addStretch(1)
        layout.addLayout(track_actions)
        self._color = ""
        self.refresh()
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._stop_preview)
        self.finished.connect(self._stop_preview)
        self._preview_video = None
        self._preview_return_rate = 1.0
        self._build_candidates()

    def _build_candidates(self):
        panel = QWidget()
        self._style_panel(panel)
        box = QVBoxLayout(panel)
        self.candidate_note = QLabel()
        self.candidate_note.setWordWrap(True)
        box.addWidget(self.candidate_note)
        self.candidate_table = QTableWidget(0, 6)
        self.candidate_table.setHorizontalHeaderLabels(("显示 / 原始标签", "段数 / 时长", "时间分布（分:秒）", "代表片段", "用途", "试听"))
        self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidate_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidate_table.setAlternatingRowColors(True)
        self.candidate_table.setMouseTracking(True)
        self.candidate_table.setItemDelegateForColumn(3, _CandidateExcerptDelegate(self.candidate_table))
        theme = _active_theme(None)
        light = QColor(theme.surface).lighter(110).name()
        self.candidate_table.setStyleSheet(
            f"QTableWidget {{ background:{light}; alternate-background-color:{theme.panel}; color:{theme.text}; }}"
            f"QTableWidget::item {{ padding:6px; border-bottom:1px solid {theme.border}; }}"
            f"QTableWidget::item:hover {{ background:{theme.surface_elevated}; }}"
            f"QTableWidget::item:selected {{ background:{theme.selected}; color:{theme.text}; }}")
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidate_table.verticalHeader().hide()
        header = self.candidate_table.horizontalHeader()
        for column in (0, 1, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        for column in (2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.candidate_table, 1)
        self.apply_summary = QLabel()
        self.apply_summary.setWordWrap(True)
        box.addWidget(self.apply_summary)
        actions = QHBoxLayout()
        self.load_cache_button = QPushButton("选择本素材 MOSS 缓存")
        self.load_cache_button.setObjectName("studioButton")
        self.load_cache_button.setIcon(_icon("fa5s.folder-open"))
        self.load_cache_button.clicked.connect(self._choose_cache)
        actions.addWidget(self.load_cache_button)
        self.reanalyze_button=QPushButton('用当前方案重新识别…')
        self.reanalyze_button.setObjectName('studioButton')
        bind_text(self.reanalyze_button, '打开当前工程识别设置，可选 Nemotron。会重新生成字幕，不是只补标签；请先保存人工编辑的工程副本。', property='toolTip')
        def open_recognition():
            self.close()
            QTimer.singleShot(0,self.page._open_recognition_sheet)
        self.reanalyze_button.clicked.connect(open_recognition)
        actions.addWidget(self.reanalyze_button)
        actions.addStretch()
        self.rebuild_button = QPushButton("应用选择并从缓存重建轨道")
        self.rebuild_button.setObjectName("studioPrimary")
        self.rebuild_button.clicked.connect(self._apply_candidates)
        actions.addWidget(self.rebuild_button)
        box.addLayout(actions)
        self.tabs.insertTab(0, panel, "候选恢复")
        self.tabs.setCurrentIndex(0)
        self._candidate_snapshot = None
        self._applying = False
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._resize_candidate_rows)
        self.candidate_table.viewport().installEventFilter(self)
        self.candidate_table.horizontalHeader().sectionResized.connect(lambda *_: self._reflow_timer.start(0))
        self._load_candidates()

    def eventFilter(self, watched, event):
        if watched is self.table and event.type()==QEvent.KeyPress and event.key()==Qt.Key_Delete:
            self._batch('delete');return True
        if hasattr(self, "_reflow_timer") and watched is self.candidate_table.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.FontChange):
            self._reflow_timer.start(0)
        return super().eventFilter(watched, event)

    @staticmethod
    def _center_control(control):
        holder = QWidget()
        holder.content_control = control
        holder.setObjectName("speakerCellControl")
        holder.setStyleSheet("QWidget#speakerCellControl {background:transparent;}")
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control.ensurePolished()
        control.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        metrics = control.fontMetrics()
        text = control.text() if isinstance(control, QPushButton) else max((control.itemText(i) for i in range(control.count())), key=metrics.horizontalAdvance)
        icon_width = control.iconSize().width() if isinstance(control, QPushButton) and not control.icon().isNull() else 20
        needed = metrics.horizontalAdvance(text) + icon_width + control.style().pixelMetric(QStyle.PixelMetric.PM_ButtonMargin)*2 + 18
        control.setMinimumWidth(max(control.minimumSizeHint().width(), control.sizeHint().width(), needed))
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignCenter)
        return holder

    def _resize_candidate_rows(self):
        if not hasattr(self, "_role_boxes"):
            return
        table = self.candidate_table
        for col in (4, 5):
            holders=[table.cellWidget(row,col) for row in range(table.rowCount()) if table.cellWidget(row,col) is not None]
            needed=max((max(h.sizeHint().width(),h.content_control.minimumWidth()+16) for h in holders),default=0)
            # QSS item padding is outside the cellWidget geometry. Header's
            # resize-to-contents omits this inset, which clipped text/centering.
            table.setColumnWidth(col,needed+14)
        option = QStyleOptionViewItem()
        option.initFrom(table)
        for row in range(table.rowCount()):
            if any(table.cellWidget(row,col) is None for col in (4,5)):continue
            index = table.model().index(row, 3)
            hint = table.itemDelegateForColumn(3).sizeHint(option, index).height()
            controls = max(max(table.cellWidget(row,col).sizeHint().height(),
                               table.cellWidget(row,col).content_control.minimumSizeHint().height()+10) for col in (4,5))
            label_height = table.fontMetrics().lineSpacing()*2+16
            table.setRowHeight(row, max(hint, controls, label_height)+14)

    @staticmethod
    def _style_panel(panel):
        theme = _active_theme(None)
        panel.setObjectName("speakerManagerPanel")
        panel.setStyleSheet(f"QWidget#speakerManagerPanel {{ background: {theme.surface}; color: {theme.text}; }}")

    def _choose_cache(self):
        directory = QFileDialog.getExistingDirectory(self, tr('选择含 moss.json 的缓存目录'))
        if directory:
            self._load_candidates(directory)

    def _load_candidates(self, directory=None):
        from .speaker_recovery import load_candidate_snapshot, candidate_statistics
        try:
            state = load_candidate_snapshot(self.page.project, directory)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            bind_text(self.candidate_note, str(exc))
            self.rebuild_button.setEnabled(False)
            return
        self._candidate_snapshot = state
        self.rebuild_button.setEnabled(True)
        stats = candidate_statistics(state["raw_segments"])
        self.candidate_table.setRowCount(len(stats))
        self._role_boxes = {}
        self._preview_buttons = {}
        expected = state.get("expected_speakers") or "自动"
        processing = state.get('processing', {})
        source = ('Nemotron 3 本地说话人区分' if processing.get('backend') == 'nemotron' else
                  'ECAPA 声学聚类' if processing.get('backend') == 'ecapa' else
                  'Filetrans 原生标签' if processing.get('status') == 'native' else
                  '完整 MOSS' if processing.get('moss_called') else '原始说话人标签')
        status = "候选身份待确认。" if state.get("needs_confirmation") else "身份选择已保留。"
        if processing.get('status')=='failed':
            status=tr('说话人分析失败，已保留字幕文字。{error} 可用下方重新识别入口重试。', error=str(processing.get('error') or ''))
        bind_text(self.candidate_note, '{value0} · {value1} 预计说话人数：{value2}。标签不等于真人身份，请按原音确认归属。\n先按需试听（每次 2–4 秒，不自动播放），再标记主要说话人 / 游戏或节目声 / 忽略。{value3}应用复用人工字幕；不请求模型。', value0=source, value1=status, value2=expected, value3='匿名标签均待确认，不按编号或发言量认定主播。' if processing.get('mode') in {'nemotron', 'native', 'filetrans'} else '超过10条去重原始发言才默认作为主要候选；其余收进游戏背景声，保留原文与标签。')
        for row, item in enumerate(stats):
            label = item["label"]
            intervals = "、".join(_format_ms(round(start*1000)) for start, _ in item["intervals"])
            interval_excerpt = "、".join(_format_ms(round(start*1000)) for start, _ in item["intervals"][:6]) + ("…" if len(item["intervals"]) > 6 else "")
            samples = sorted((x for x in state["raw_segments"] if x.get("speaker") == label),
                             key=lambda x: (-(x["end"] - x["start"]), x["start"]))[:3]
            samples.sort(key=lambda x: x["start"])
            excerpt = "\n".join(f"{_format_ms(round(x['start']*1000))}  {x['text']}" for x in samples)
            full = "\n\n".join(f"{_format_ms(round(x['start']*1000))}  {x['text']}"
                               for x in state["raw_segments"] if x.get("speaker") == label)
            shown = state.get("display_labels", {}).get(label)
            speaker = next((x for x in self.page.project.speakers if x.id == label), None)
            display = (display_speaker_name(self.page.project, speaker) if speaker else shown) or tr("候选")
            values = (tr('{name}\n原始 {label}', name=display, label=label), tr('{count} 段 / {seconds:.2f}s', count=item['segments'], seconds=item['seconds']), interval_excerpt, excerpt)
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col < 2:
                    bind_item(cell, value)
                cell.setToolTip(full if col == 3 else intervals if col == 2 else value)
                cell.setData(Qt.ItemDataRole.UserRole, label)
                self.candidate_table.setItem(row, col, cell)
            role = StudioComboBox()
            for title, value in (("待确认", "unconfirmed"), ("主要说话人", "main"), ("游戏或节目声", "game"), ("忽略/待恢复", "ignore")):
                role.addItem(title, value)
            for other in stats:
                if other['label'] != label:
                    add_combo_item(role, tr('并入 {name}', name=other['label']), 'merge:'+other['label'])
            role.setCurrentIndex(max(0, role.findData(state["roles"].get(label, "unconfirmed"))))
            self._role_boxes[label] = role
            role.currentIndexChanged.connect(self._candidate_roles_changed)
            self.candidate_table.setCellWidget(row, 4, self._center_control(role))
            preview = QPushButton("试听")
            preview.setObjectName("studioButton")
            preview.setIcon(_icon("fa5s.play"))
            preview.clicked.connect(lambda _checked=False, label=label: self._preview_candidate(label))
            self._preview_buttons[label] = preview
            self.candidate_table.setCellWidget(row, 5, self._center_control(preview))
        self._reflow_timer.start(0)
        self._candidate_roles_changed()

    def _candidate_roles_changed(self, *_args):
        from .speaker_recovery import recovery_preview, selected_display_mapping
        if self._candidate_snapshot is None or self._applying:
            return
        roles = {label: box.currentData() for label, box in self._role_boxes.items()}
        changed = {label for label, role in roles.items() if role != self._candidate_snapshot["roles"].get(label)}
        self.page._speaker_roles_pending = bool(changed)
        self.page._populate_speakers()
        counts = recovery_preview(self.page.project, self._candidate_snapshot, roles)
        mapping = selected_display_mapping(self._candidate_snapshot, roles, self.page.project)
        selected = join_text([tr('原始 {raw} → {name}', raw=raw, name=shown) for raw, shown in mapping.items()], ' / ') if mapping else tr('尚未选择')
        pending = [label for label, role in roles.items() if role == "unconfirmed"]
        prefix = "有未应用修改。" if changed else "当前选择。"
        merged=sum(str(role).startswith('merge:') for role in roles.values())
        ignored=sum(role=='ignore' for role in roles.values())
        bind_text(self.apply_summary, '{value0}主要说话人：{value1}；预计 {value2} 条轨道 / {value3} cue；并入 {value4} 个标签，忽略/待恢复 {value5} 个。\n{value6}', value0=tr(prefix), value1=selected, value2=len(counts), value3=sum(counts.values()), value4=merged, value5=ignored, value6=tr('未确认候选：{names}（保留待确认，不阻止应用）。', names='、'.join(pending)) if pending else '全部候选已分类。')
        self.rebuild_button.setEnabled(bool(counts))
        theme = _active_theme(None)
        for row, label in enumerate(self._role_boxes):
            for col in range(4):
                self.candidate_table.item(row, col).setBackground(QColor(theme.warning_soft) if label in changed else QBrush())
            box = self._role_boxes[label]
            bind_text(box, join_text([tr('有未应用修改。') if label in changed else '', tr(self._candidate_snapshot.get('reasons', {}).get(label, ''))], ''), property='toolTip')
            box.setStyleSheet(f"QComboBox {{ border:2px solid {theme.warning}; }}" if label in changed else "")

    def done(self, result):
        self.page._speaker_roles_pending = False
        self.page._populate_speakers()
        super().done(result)

    def _preview_candidate(self, label):
        from .speaker_recovery import representative_interval
        start, end = representative_interval(self._candidate_snapshot, label)
        self._start_preview(start, end)

    def _start_preview(self, start, end):
        self._stop_preview()
        video = self.page.video
        if not video.controller:
            bind_text(self.candidate_note, '请先等待媒体预览就绪，再点击试听。')
            return
        video.set_paused(True)
        self._preview_return_rate = float(self.page.speed_box.currentData() or 1.)
        self.page._set_speed(1.)
        self.page._seek(start / 1000)
        self._preview_video = video
        video.set_paused(False)
        self._preview_timer.start(end - start)

    def _stop_preview(self, *_args):
        self._preview_timer.stop()
        video = self._preview_video
        self._preview_video = None
        if video is not None and video.controller:
            video.set_paused(True)
            if self._preview_return_rate != 1.:
                self.page._set_speed(self._preview_return_rate)

    def _apply_candidates(self):
        if self._applying:
            return
        self._applying = True
        self.rebuild_button.setEnabled(False)
        bind_text(self.rebuild_button, '正在应用…')
        bind_text(self.candidate_note, '正在从本地缓存恢复已选说话人并刷新当前工程…')
        QTimer.singleShot(50, self._commit_candidates)

    def _commit_candidates(self):
        from .speaker_recovery import rebuild_selected_speakers
        self._stop_preview()
        try:
            recovered = rebuild_selected_speakers(self.page.project, self._candidate_snapshot,
                                                  {label: box.currentData() for label, box in self._role_boxes.items()})
            command = RecoverSpeakersCommand(self.page.project, recovered, self.page._speaker_structure_changed)
            self.page.undo_stack.push(command)
            if command.error:
                raise RuntimeError(command.error)
            self._applying = False
            self._load_candidates()
            self.refresh()
            bind_text(self.candidate_note, '应用成功：当前工程已更新为 {value0} 条主要说话人字幕轨 / {value1} cue。新增原文及时间待复核；可撤销、保存和重开。', value0=len(recovered.speakers), value1=len(recovered.cues))
        except Exception as exc:
            bind_text(self.candidate_note, '应用失败，当前工程已保留原状态：{value0}: {exc}', value0=type(exc).__name__, exc=exc)
        finally:
            self._applying = False
            bind_text(self.rebuild_button, '应用选择并从缓存重建轨道')
            self._candidate_roles_changed()

    def _selected_speaker_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 1)
        return str(item.data(Qt.ItemDataRole.UserRole) or item.text()) if item else ""

    def refresh(self, selected_id: str = "") -> None:
        project = self.page.project
        if project is None:
            return
        selected_id = selected_id or self._selected_speaker_id()
        self._checking_rows=True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for speaker in project.speakers:
            cues = [cue for cue in project.cues if cue.speaker_id == speaker.id]
            duration = sum(max(0, cue.end_ms - cue.start_ms) for cue in cues)
            row = self.table.rowCount()
            self.table.insertRow(row)
            color = _speaker_color(project, speaker.id)
            color_item = QTableWidgetItem("●")
            color_item.setFlags(color_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            color_item.setCheckState(Qt.CheckState.Unchecked)
            color_item.setForeground(color)
            color_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            identity = QTableWidgetItem(display_speaker_name(project, speaker))
            bind_item(identity, tr('{name}', name=display_speaker_name(project, speaker)))
            bind_text(identity, '内部身份：{value0}', property='toolTip', value0=speaker.id)
            identity.setData(Qt.ItemDataRole.UserRole, speaker.id)
            display_name = display_speaker_name(project, speaker)
            if speaker.is_host:
                display_name = tr('★ {name}', name=display_name)
            if speaker.hidden:
                display_name = tr('{name}（已隐藏）', name=display_name)
            values = (
                color_item,
                identity,
                bind_item(QTableWidgetItem(), tr('{name}', name=display_name)),
                QTableWidgetItem(str(len(cues))),
                QTableWidgetItem(_format_ms(duration)),
                QTableWidgetItem(speaker.style_id),
            )
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
            if speaker.id == selected_id:
                self.table.selectRow(row)
        if self.table.rowCount() and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self.table.blockSignals(False)
        self._checking_rows=False
        self._load_selected()
        self._selection_checks()

    def _selected_ids(self):
        return {str(self.table.item(row,1).data(Qt.UserRole)) for row in range(self.table.rowCount())
                if not self.table.isRowHidden(row) and self.table.item(row,0).checkState()==Qt.Checked}

    def _selection_checks(self):
        if self._checking_rows:return
        self._checking_rows=True
        selected={i.row() for i in self.table.selectionModel().selectedRows()}
        for row in range(self.table.rowCount()):
            item=self.table.item(row,0)
            if item:item.setCheckState(Qt.Checked if row in selected and not self.table.isRowHidden(row) else Qt.Unchecked)
        self._checking_rows=False
        self._update_selection_summary()

    def _checkbox_selection(self,item):
        if self._checking_rows or item.column()!=0:return
        from PySide6.QtCore import QItemSelectionModel
        self._checking_rows=True
        flag=QItemSelectionModel.Select if item.checkState()==Qt.Checked else QItemSelectionModel.Deselect
        self.table.selectionModel().select(self.table.model().index(item.row(),0),flag|QItemSelectionModel.Rows)
        self._checking_rows=False;self._update_selection_summary()

    def _select_visible(self,mode):
        from PySide6.QtCore import QItemSelectionModel
        self._checking_rows=True
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):continue
            item=self.table.item(row,0)
            checked=mode=='all' or (mode=='invert' and item.checkState()!=Qt.Checked)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            flag=QItemSelectionModel.Select if checked else QItemSelectionModel.Deselect
            self.table.selectionModel().select(self.table.model().index(row,0),flag|QItemSelectionModel.Rows)
        self._checking_rows=False;self._update_selection_summary()

    def _update_selection_summary(self):
        ids=self._selected_ids()
        count=sum(c.speaker_id in ids for c in self.page.project.cues)
        bind_text(self.selection_summary, '已选 {value0} 人 / {count} 条字幕', value0=len(ids), count=count)

    def _filter_rows(self,text):
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(row,not any(text.casefold() in self.table.item(row,col).text().casefold() for col in (1,2)))
        self._selection_checks()

    def _batch(self,action,target=None,all_rows=False):
        from .speaker_organization import organization_command
        project=self.page.project
        ids={s.id for s in project.speakers} if all_rows else self._selected_ids()
        if not ids:return
        count=sum(c.speaker_id in ids for c in project.cues)
        if action=='delete' and QMessageBox.question(self,tr('删除人物及字幕'),
                tr('删除 {value0} 个身份及 {value1} 条字幕？可在 Studio 撤销。', value0=len(ids), value1=count),QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
        try:
            self.page.undo_stack.push(organization_command(project,ids,action,target,self.page._speaker_structure_changed))
            self.refresh(target or '')
        except ValueError as exc:self.selection_summary.setText(str(exc))

    def _apply_count_policy(self):
        from .speaker_organization import utterance_counts
        project=self.page.project
        counts=utterance_counts(project.generation_metadata.get('speaker_recovery',{}).get('raw_segments',[]))
        if not counts:
            bind_text(self.selection_summary, '没有完整任务的原始发言统计，保留当前整理。');return
        threshold=self.utterance_threshold.value()
        decisions=project.generation_metadata.get('speaker_organization',{}).get('decisions',{})
        ids={s.id for s in project.speakers if not s.is_host and decisions.get(s.id)!='main' and counts.get(s.id,0)<=threshold}
        from .speaker_organization import organization_command
        command=organization_command(project,ids,'background',changed=self.page._speaker_structure_changed,threshold=threshold)
        self.page.undo_stack.push(command)
        self.refresh()

    def _load_selected(self) -> None:
        project = self.page.project
        speaker_id = self._selected_speaker_id()
        speaker = next((item for item in project.speakers if item.id == speaker_id), None) if project else None
        enabled = speaker is not None
        for control in (
            self.name_edit, self.color_button, self.style_combo, self.apply_button,
            self.assign_button, self.visible_check, self.preview_button,
            self.host_button, self.keep_only_button,
        ):
            control.setEnabled(enabled)
        self.visible_check.blockSignals(True)
        self.visible_check.setChecked(not speaker.hidden if speaker else True)
        self.visible_check.blockSignals(False)
        if not speaker or not project:
            return
        self.name_edit.setText(speaker.name or speaker.id)
        self._color = speaker.color or _speaker_color(project, speaker.id).name()
        self._update_color_button()
        self.style_combo.clear()
        for style in project.styles:
            self.style_combo.addItem(style.name or style.id, style.id)
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(speaker.style_id)))
        self.merge_target.clear()
        for candidate in project.speakers:
            if candidate.id != speaker.id:
                self.merge_target.addItem(candidate.name or candidate.id, candidate.id)
        self.merge_button.setEnabled(self.merge_target.count() > 0)

    def _visibility_toggled(self, state: int) -> None:
        project = self.page.project
        speaker_id = self._selected_speaker_id()
        if not project or not speaker_id:
            return
        hidden = int(state) == 0
        self.page.undo_stack.push(SetSpeakerCommand(
            project,
            speaker_id,
            {"hidden": hidden},
            text="隐藏说话人" if hidden else "显示说话人",
            changed=self.page._speaker_structure_changed,
        ))
        self.refresh(speaker_id)

    def _preview_representative(self) -> None:
        project = self.page.project
        speaker_id = self._selected_speaker_id()
        if not project or not speaker_id:
            return
        cues = [cue for cue in project.cues if cue.speaker_id == speaker_id]
        if not cues:
            studio_message_box(
                self, QMessageBox.Icon.Information, tr('无字幕'),
                tr('{value0} 还没有任何字幕，无法试听。', value0=speaker_id),
            )
            return
        representative = max(cues, key=lambda cue: cue.end_ms - cue.start_ms)
        duration = min(4000, max(2000, representative.end_ms-representative.start_ms))
        self._start_preview(representative.start_ms, representative.start_ms+duration)
        self.refresh(speaker_id)

    def _set_host(self) -> None:
        project = self.page.project
        speaker_id = self._selected_speaker_id()
        if not project or not speaker_id:
            return
        self.page.undo_stack.push(SetHostSpeakerCommand(
            project, speaker_id, self.page._speaker_structure_changed
        ))
        self.refresh(speaker_id)

    def _keep_only(self) -> None:
        project = self.page.project
        speaker_id = self._selected_speaker_id()
        if not project or not speaker_id:
            return
        hidden = [
            speaker.id for speaker in project.speakers
            if speaker.id != speaker_id and not speaker.hidden
        ]
        if not hidden:
            self.refresh(speaker_id)
            return
        self.page.undo_stack.push(SetSpeakersVisibilityCommand(
            project, hidden, self.page._speaker_structure_changed
        ))
        self.refresh(speaker_id)

    def _update_color_button(self) -> None:
        color = QColor(self._color)
        (bind_text(self.color_button, color.name()) if color.isValid() else bind_text(self.color_button, '选择颜色'))
        if color.isValid():
            self.color_button.setStyleSheet(f"background:{color.name()}; color:white; border:1px solid {color.darker(130).name()};")

    def _choose_color(self) -> None:
        dialog = QColorDialog(QColor(self._color), self)
        bind_text(dialog, '选择说话人颜色', property='windowTitle')
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        apply_secondary_surface_theme(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selectedColor().isValid():
            self._color = dialog.selectedColor().name()
            self._update_color_button()

    def _apply_changes(self) -> None:
        project = self.page.project
        speaker_id = self._selected_speaker_id()
        if not project or not speaker_id:
            return
        self.page.undo_stack.push(SetSpeakerCommand(
            project,
            speaker_id,
            {
                "name": self.name_edit.text().strip() or speaker_id,
                "color": self._color,
                "style_id": str(self.style_combo.currentData() or "default"),
            },
            changed=self.page._speaker_structure_changed,
        ))
        self.refresh(speaker_id)

    def _merge(self) -> None:
        project = self.page.project
        source_id = self._selected_speaker_id()
        target_id = str(self.merge_target.currentData() or "")
        if not project or not source_id or not target_id:
            return
        answer = studio_message_box(
            self,
            QMessageBox.Icon.Question,
            tr('合并说话人'),
            tr('将 {value0} 的全部 Cue 合并到 {value1}？\n此操作可用 Ctrl+Z 撤销。', value0=source_id, value1=target_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.page.undo_stack.push(MergeSpeakerCommand(
            project, source_id, target_id, self.page._speaker_structure_changed
        ))
        self.refresh(target_id)

    def _assign_selected_cues(self) -> None:
        project = self.page.project
        target_id = self._selected_speaker_id()
        cue_ids = self.page.selected_cue_ids()
        if not project or not target_id or not cue_ids:
            return
        try:
            self.page.undo_stack.push(AssignSpeakerCommand(
                project, cue_ids, target_id, self.page._speaker_structure_changed
            ))
        except ValueError as exc:
            studio_message_box(self, QMessageBox.Icon.Information, tr('无需修改'), str(exc))
        self.refresh(target_id)
