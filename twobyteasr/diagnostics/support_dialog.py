"""The same local report workflow from Studio, Help and settings.

2026-10-21 layout: a timeline centred on the moment the person pressed the
report button, the person's own steps below it (newest first, the one to look
at first marked), and three views — timeline, detailed log, summary — over one
footer that writes the description and exports the ZIP. Lifecycle (one window
per main window, background jobs, delayed disposal) is unchanged.
"""
from __future__ import annotations
import json
from pathlib import Path
import threading
import uuid
import weakref
import time


def settings_summary(window):
    """Whitelist only. Never dump settings, environment or a project file."""
    settings=getattr(getattr(window,"legacy",None),"RUNTIME_SETTINGS",{}) or {}
    models=settings.get("models",{})
    allowed=("primary_asr_backend","firered_asr_backend","qwen_asr_backend","polish_provider","polish_model","group_provider","group_model")
    return {"models":{k:models.get(k) for k in allowed},
            "language":(settings.get("subtitle_language") or {}).get("recognition_language"),
            "switches":{k:settings.get("switches",{}).get(k) for k in
                        ("use_ai_grouping","use_ai_polish","subtitle_punctuation","use_ja_ctc_aligner")}}


SCOPES = (("最近 15 分钟", "recent"), ("本次运行", "session"),
          ("上次没有正常结束的运行", "previous"), ("指定时间范围", "range"))
PAGE_ROWS = 100


def open_support_dialog(owner, page=None):
    from PySide6.QtCore import QObject, Signal, Qt, QDateTime, QUrl, QTimer, QEvent
    from PySide6.QtGui import QDesktopServices, QFontMetrics
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QDateTimeEdit, QDialog,
        QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
        QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
        QInputDialog, QAbstractItemView)
    from ..design.presentation import button_role
    from ..design.studio_theme import StudioComboBox, apply_secondary_surface_theme, create_studio_menu
    from ..i18n import tr
    from ..i18n_widgets import add_combo_item, bind_text
    from . import editor_diagnostics
    from . import support_views as views
    from .event_log import emit, now, recorder
    from .studio_events import page_context
    from .support_bundle import collect, export_report, maintain_sessions, summary
    from .support_triage import (KIND_LABELS, LEVEL_LABELS, ago_text, analyze, event_title, legend, local_clock)
    from shiboken6 import isValid

    entry_owner=owner
    while owner.parentWidget() is not None:
        owner=owner.parentWidget()
    if page is None:
        page=entry_owner if hasattr(entry_owner,"cue_controller") else (owner.built_page("studio") if hasattr(owner,"built_page") else None)
    existing=getattr(owner,"_support_dialog",None)
    if existing is not None and isValid(existing) and not existing._closed:
        existing._link_owner(entry_owner)
        existing.show();existing.raise_();existing.activateWindow();return existing
    instance=editor_diagnostics.install_early()
    report_id="report-"+uuid.uuid4().hex[:16]
    marked={"report_id":report_id,"marked_at":now(),**(page_context(page) if page else {})}
    emit("problem.marked",result="observed",source="report_button",**marked)

    class Signals(QObject):
        loaded=Signal(object)
        exported=Signal(object)
        cleaned=Signal(object)

    class SupportDialog(QDialog):
        def __init__(self):
            super().__init__(owner)
            self.setObjectName("diagnosticsDialog")
            self.setWindowTitle("回报问题")
            self.resize(960,880)
            self.setMinimumWidth(760)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,False)
            self._closed=False;self._jobs=0;self._loading=False;self._reload_requested=False
            self._collect_cancel=threading.Event()
            self._exporting=False;self._cleaning=False;self._owners=[]
            self.finished.connect(self._retire)
            self._signals=Signals(self)
            self._signals.loaded.connect(self._loaded)
            self._signals.exported.connect(self._exported)
            self._signals.cleaned.connect(self._cleaned)
            self._rows=[];self._filtered=[];self._offset=0;self._result=None;self._load_generation=0
            self._search_rows=[];self._analysis=None;self._selected_step=None;self._step_filter=None
            self._only_problems=True;self._theme_key=None;self._filtered_index=[]
            self._filter_timer=QTimer(self);self._filter_timer.setSingleShot(True);self._filter_timer.setInterval(180)
            self._filter_timer.timeout.connect(self._filter)
            self._selected=[]
            if page and page.project:
                ids=page.selected_cue_ids()[:50]
                view=page.project.generation_metadata.get("translations") or {}
                for cue_id in ids:
                    cue=page._cue_lookup.get(cue_id)
                    if cue:self._selected.append(dict(subtitle_id=cue.id,text=cue.text,translation=view.get(cue.id,""),start_ms=cue.start_ms,end_ms=cue.end_ms))
            outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
            self.body=views.PlainPage();self.body.setObjectName("supportBody");outer.addWidget(self.body)
            root=QVBoxLayout(self.body);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
            root.addWidget(self._build_header())
            self.views=QStackedWidget();self.views.setObjectName("supportViews")
            self.views.addWidget(self._build_timeline_view())
            self.views.addWidget(self._build_log_view())
            self.views.addWidget(self._build_summary_view())
            root.addWidget(self.views,1)
            root.addWidget(self._build_footer())
            apply_secondary_surface_theme(self)
            self._apply_theme()
            self._timer=QTimer(self);self._timer.setInterval(1000);self._timer.timeout.connect(self._tick);self._timer.start()
            # The complete form paints and accepts text before any diagnostic
            # worker starts competing for the GIL with the first layout.
            QTimer.singleShot(0,self._load)

        # ---- layout ----------------------------------------------------
        def _build_header(self):
            header=QWidget();layout=QVBoxLayout(header);layout.setContentsMargins(22,14,22,10);layout.setSpacing(8)
            row=QHBoxLayout();row.setSpacing(10)
            titles=QVBoxLayout();titles.setSpacing(0)
            self.title=QLabel();self.title.setObjectName("supportTitle")
            bind_text(self.title,tr("你在 {time} 按下回报",time=local_clock(_stamp(marked["marked_at"]))))
            titles.addWidget(self.title)
            self.identity=QLabel(report_id);self.identity.setObjectName("supportIdentity")
            self.identity.setFont(views.mono_font(11))
            self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.identity.setToolTip(tr("报告编号；发给开发者时可以一起附上。标记时间（UTC）：{time}",time=marked["marked_at"]))
            titles.addWidget(self.identity)
            row.addLayout(titles,1)
            segment=QFrame();segment.setObjectName("supportSegment")
            seg=QHBoxLayout(segment);seg.setContentsMargins(3,3,3,3);seg.setSpacing(2)
            self._view_group=QButtonGroup(self);self._view_buttons={}
            for key,label in (("timeline","时间轴"),("log","详细记录"),("summary","摘要")):
                button=QPushButton(label);button.setObjectName("supportViewButton");button.setCheckable(True)
                button.setProperty("buttonRole","segment")
                button.clicked.connect(lambda _=False,k=key:self.show_view(k))
                self._view_group.addButton(button);seg.addWidget(button);self._view_buttons[key]=button
            self._view_buttons["timeline"].setChecked(True)
            row.addWidget(segment,0,Qt.AlignmentFlag.AlignVCenter)
            self.scope=StudioComboBox();self.scope.setObjectName("diagnosticScope")
            for label,key in SCOPES:add_combo_item(self.scope,label,key)
            self.scope.setToolTip(tr("“最近 15 分钟”也包含同一工程、同一任务更早的相关操作"))
            row.addWidget(self.scope,0,Qt.AlignmentFlag.AlignVCenter)
            self.start=QDateTimeEdit(QDateTime.currentDateTime().addSecs(-900));self.end=QDateTimeEdit(QDateTime.currentDateTime())
            for widget in (self.start,self.end):
                widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss");widget.setCalendarPopup(True);widget.setVisible(False)
                row.addWidget(widget,0,Qt.AlignmentFlag.AlignVCenter)
            self.refresh=QToolButton();self.refresh.setObjectName("diagnosticRefresh")
            self.refresh.setToolTip(tr("重新读取记录"));self.refresh.setAccessibleName(tr("重新读取记录"))
            button_role(self.refresh,"icon",icon="fa5s.sync-alt",size="compact")
            self.refresh.clicked.connect(self._load);row.addWidget(self.refresh,0,Qt.AlignmentFlag.AlignVCenter)
            self.scope.currentIndexChanged.connect(self._scope_changed)
            layout.addLayout(row)
            legend_row=QHBoxLayout();legend_row.setSpacing(8)
            self._legend=[]
            for _ in range(5):
                chip=QLabel();chip.setObjectName("supportLegend");chip.setTextFormat(Qt.TextFormat.RichText)
                legend_row.addWidget(chip);self._legend.append(chip)
            legend_row.addStretch(1)
            layout.addLayout(legend_row)
            return header

        def _build_timeline_view(self):
            view=views.PlainPage();layout=QVBoxLayout(view);layout.setContentsMargins(22,0,22,12);layout.setSpacing(12)
            card=QFrame();card.setObjectName("supportCard")
            inner=QVBoxLayout(card);inner.setContentsMargins(14,10,14,8)
            self.timeline=views.TimelineStrip();self.timeline.stepSelected.connect(self.select_step)
            inner.addWidget(self.timeline);layout.addWidget(card)
            self.banner=QFrame();self.banner.setObjectName("supportBanner");self.banner.hide()
            banner=QHBoxLayout(self.banner);banner.setContentsMargins(14,10,10,10);banner.setSpacing(10)
            text=QLabel("这段时间没有记录到错误、资料异常或明显卡顿。找不到线索时：打开“详细记录 10 分钟”，重做一次出问题的操作，再按刷新。")
            text.setObjectName("supportBannerText");text.setWordWrap(True);banner.addWidget(text,1)
            self.banner_detail=QPushButton("开始详细记录");button_role(self.banner_detail,"secondary",size="compact")
            self.banner_detail.clicked.connect(lambda:self.details_mode.setChecked(True))
            banner.addWidget(self.banner_detail,0,Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(self.banner)
            lower=QHBoxLayout();lower.setSpacing(12)
            trail=QFrame();trail.setObjectName("supportCard");trail.setMinimumWidth(290);trail.setMaximumWidth(360);trail.setMinimumHeight(150)
            trail_layout=QVBoxLayout(trail);trail_layout.setContentsMargins(0,10,0,0);trail_layout.setSpacing(4)
            head=QHBoxLayout();head.setContentsMargins(14,0,14,0);head.setSpacing(8)
            title=QLabel("操作轨迹");title.setObjectName("supportCardTitle");head.addWidget(title)
            hint=QLabel("从你按下回报往前");hint.setObjectName("supportMuted");head.addWidget(hint);head.addStretch(1)
            trail_layout.addLayout(head)
            self.steps=views.StepTrail();self.steps.stepSelected.connect(self.select_step);self.steps.setMinimumHeight(60)
            trail_layout.addWidget(self.steps,1)
            self.running=QLabel();self.running.setObjectName("supportMuted");self.running.setWordWrap(True)
            self.running.setContentsMargins(14,6,14,8)
            trail_layout.addWidget(self.running)
            lower.addWidget(trail,0)
            self.detail=views.StepDetail();self.detail.setMinimumHeight(150)
            self.detail.showStepLog.connect(self.show_step_log)
            self.detail.copyStep.connect(self._copy_step)
            lower.addWidget(self.detail,1)
            layout.addLayout(lower,1)
            return view

        def _build_log_view(self):
            view=views.PlainPage();layout=QVBoxLayout(view);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
            bar=QHBoxLayout();bar.setContentsMargins(22,4,22,10);bar.setSpacing(8)
            segment=QFrame();segment.setObjectName("supportSegment")
            seg=QHBoxLayout(segment);seg.setContentsMargins(3,3,3,3);seg.setSpacing(2)
            self._filter_group=QButtonGroup(self)
            self.only_problems=QPushButton();self.only_problems.setObjectName("supportFilterButton");self.only_problems.setCheckable(True)
            self.all_rows=QPushButton();self.all_rows.setObjectName("supportFilterButton");self.all_rows.setCheckable(True)
            for button,value in ((self.only_problems,True),(self.all_rows,False)):
                button.setProperty("buttonRole","segment")
                self._filter_group.addButton(button);seg.addWidget(button)
                button.clicked.connect(lambda _=False,v=value:self._set_problem_filter(v))
            self.only_problems.setChecked(True)
            bar.addWidget(segment)
            self.step_filter=QPushButton();self.step_filter.setObjectName("supportStepFilter");self.step_filter.hide()
            self.step_filter.setToolTip(tr("取消只看这一步"));self.step_filter.clicked.connect(lambda:self._set_step_filter(None))
            bar.addWidget(self.step_filter)
            self.level=StudioComboBox();self.level.setObjectName("diagnosticLevel")
            for label,key in (("所有等级",""),("错误","ERROR"),("警告","WARN"),("信息","INFO"),("调试","DEBUG")):add_combo_item(self.level,label,key)
            self.level.currentIndexChanged.connect(self._filter);bar.addWidget(self.level)
            self.keyword=QLineEdit();self.keyword.setObjectName("diagnosticKeyword")
            self.keyword.setPlaceholderText("搜索事件、模块、操作 ID 或 #序号")
            self.keyword.textChanged.connect(lambda:self._filter_timer.start());bar.addWidget(self.keyword,1)
            layout.addLayout(bar)
            self.table=QTableWidget(0,6);self.table.setObjectName("diagnosticEvents")
            self.table.setHorizontalHeaderLabels(["时间","距标记","等级","所属步骤","事件","#"])
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.verticalHeader().hide();self.table.setShowGrid(False);self.table.setWordWrap(False)
            self.table.verticalHeader().setDefaultSectionSize(32)
            header=self.table.horizontalHeader();header.setHighlightSections(False)
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
            for column,width in ((0,104),(1,74),(2,70),(3,124),(5,64)):
                header.setSectionResizeMode(column,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(column,width)
            header.setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch)
            self.table.itemSelectionChanged.connect(self._expand)
            layout.addWidget(self.table,1)
            pagination=QHBoxLayout();pagination.setContentsMargins(22,4,22,4)
            self.previous_page=QPushButton("上一页");self.next_page=QPushButton("下一页");self.page_label=QLabel()
            self.page_label.setObjectName("supportMuted")
            for button in (self.previous_page,self.next_page):button_role(button,"ghost",size="compact")
            self.previous_page.clicked.connect(lambda:self._page(-1));self.next_page.clicked.connect(lambda:self._page(1))
            pagination.addWidget(self.previous_page);pagination.addWidget(self.page_label);pagination.addWidget(self.next_page);pagination.addStretch(1)
            self._pagination=QWidget();self._pagination.setLayout(pagination);layout.addWidget(self._pagination)
            detail=QFrame();detail.setObjectName("supportCard")
            detail.setStyleSheet("QFrame#supportCard{border-radius:0;border-left:0;border-right:0;border-bottom:0;}")
            box=QVBoxLayout(detail);box.setContentsMargins(22,10,22,12);box.setSpacing(6)
            head=QHBoxLayout();head.setSpacing(8)
            self.event_pill=QLabel();self.event_pill.setObjectName("supportPill");head.addWidget(self.event_pill)
            self.event_title=QLabel("选一笔记录查看详情");self.event_title.setObjectName("supportCardTitle");head.addWidget(self.event_title,1)
            self.back_to_step=QPushButton("回到时间轴上这一步");button_role(self.back_to_step,"secondary",size="compact")
            self.back_to_step.clicked.connect(self._back_to_step);head.addWidget(self.back_to_step)
            self.copy_event=QPushButton("复制这笔（JSON）");button_role(self.copy_event,"secondary",size="compact")
            self.copy_event.clicked.connect(self._copy_event);head.addWidget(self.copy_event)
            box.addLayout(head)
            self.event_details=QLabel();self.event_details.setObjectName("supportKeyValues");self.event_details.setWordWrap(True)
            self.event_details.setTextFormat(Qt.TextFormat.RichText)
            self.event_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.event_details.setMinimumHeight(96);self.event_details.setAlignment(Qt.AlignmentFlag.AlignTop)
            box.addWidget(self.event_details)
            layout.addWidget(detail)
            self.back_to_step.setEnabled(False);self.copy_event.setEnabled(False)
            return view

        def _build_summary_view(self):
            view=views.PlainPage();layout=QVBoxLayout(view);layout.setContentsMargins(22,0,22,12);layout.setSpacing(8)
            note=QLabel("这段文字会放进诊断包的 README.txt；按下方“复制摘要”可以直接贴到聊天里。")
            note.setObjectName("supportMuted");note.setWordWrap(True);layout.addWidget(note)
            self.summary=QPlainTextEdit();self.summary.setObjectName("diagnosticsText");self.summary.setReadOnly(True)
            self.summary.setFont(views.mono_font(12));self.summary.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            layout.addWidget(self.summary,1)
            return view

        def _build_footer(self):
            footer=QFrame();footer.setObjectName("supportFooter")
            layout=QVBoxLayout(footer);layout.setContentsMargins(22,10,22,10);layout.setSpacing(6)
            self.content_preview=QPlainTextEdit();self.content_preview.setReadOnly(True);self.content_preview.setMaximumHeight(110)
            self.content_preview.setObjectName("diagnosticContentPreview");self.content_preview.hide()
            layout.addWidget(self.content_preview)
            row=QHBoxLayout();row.setSpacing(8)
            label=QLabel("一句话说明");label.setObjectName("supportCardTitle");row.addWidget(label)
            self.description=QLineEdit();self.description.setObjectName("diagnosticDescription")
            self.description.setPlaceholderText("例如：合并这两句后，画面上的译文不见了")
            self.description.setMaxLength(1000);row.addWidget(self.description,1)
            label.setBuddy(self.description)
            self.content=QCheckBox();self.content.setObjectName("diagnosticIncludeContent")
            if self._selected:
                bind_text(self.content,tr("附上选取的 {count} 条字幕（原文＋译文）",count=len(self._selected)))
                self.content.setToolTip(tr("最多 50 条；勾选后会先显示要附上的内容"))
            else:
                self.content.setText("附上选取的字幕（原文＋译文）")
                self.content.setToolTip(tr("先在字幕列表里选取要附上的字幕"))
            self.content.setEnabled(bool(self._selected))
            self.content.toggled.connect(self._content_changed)
            self.more=QToolButton();self.more.setObjectName("diagnosticMore")
            self.more.setText(tr("更多"));self.more.setToolTip(tr("详细记录 10 分钟、编辑草稿、清理旧记录"))
            button_role(self.more,"secondary",icon="fa5s.ellipsis-h")
            self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu=create_studio_menu(self,theme_on_show=True);self.more.setMenu(menu)
            holder=QWidget();holder_layout=QHBoxLayout(holder);holder_layout.setContentsMargins(10,4,10,4)
            self.details_mode=QCheckBox("详细记录 10 分钟（不收集全文，到时自动关闭）")
            self.details_mode.setObjectName("diagnosticDetailedMode");self.details_mode.setChecked(bool(instance and instance.detailed))
            self.details_mode.toggled.connect(self._details_changed)
            holder_layout.addWidget(self.details_mode)
            detail_action=QWidgetAction(menu);detail_action.setDefaultWidget(holder);menu.addAction(detail_action)
            menu.addSeparator()
            self.drafts_action=menu.addAction("查看编辑草稿…");self.drafts_action.triggered.connect(self._drafts)
            self.clear_action=menu.addAction("清理旧记录");self.clear_action.triggered.connect(self._clean)
            self.clear_action.setToolTip("只清理已经结束的诊断记录，保留正在运行的记录与工程数据")
            self.folder_action=menu.addAction("打开诊断包所在文件夹");self.folder_action.setEnabled(False)
            self.folder_action.triggered.connect(self._folder)
            row.addWidget(self.more)
            self.copy=QPushButton("复制摘要");self.copy.setObjectName("diagnosticCopySummary")
            button_role(self.copy,"secondary");self.copy.clicked.connect(self._copy);row.addWidget(self.copy)
            self.export=QPushButton("导出诊断包…");self.export.setObjectName("diagnosticExportButton")
            button_role(self.export,"primary");self.export.setDefault(True)
            self.export.clicked.connect(self._choose_export);row.addWidget(self.export)
            self.export.setEnabled(False);self.copy.setEnabled(False)
            layout.addLayout(row)
            status=QHBoxLayout();status.setSpacing(12)
            status.addWidget(self.content,0,Qt.AlignmentFlag.AlignTop)
            self.note=QLabel("正在后台读取记录…");self.note.setObjectName("supportMuted");self.note.setWordWrap(True)
            self.note.setToolTip(tr("包含：版本与环境、操作与错误记录、工程结构统计、能取得的故障堆栈。\n不含：字幕和译文全文、媒体、提示词、AI 回复、截图、内存转储。"))
            self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            status.addWidget(self.note,1)
            self.folder=QPushButton("打开所在文件夹");self.folder.setObjectName("diagnosticOpenFolder")
            button_role(self.folder,"ghost",size="compact");self.folder.hide();self.folder.setEnabled(False)
            self.folder.clicked.connect(self._folder);status.addWidget(self.folder,0,Qt.AlignmentFlag.AlignTop)
            layout.addLayout(status)
            self.clear=self.clear_action
            return footer

        def _apply_theme(self):
            from ..design.theme_manager import theme_key
            key=theme_key()
            if key==self._theme_key:return
            self._theme_key=key
            self.body.setStyleSheet(views.support_qss(views.active_theme()))
            self._render_legend()
            for widget in (self.timeline,self.steps.viewport()):widget.update()
            if self._analysis is not None:self.select_step(self._selected_step,force=True)

        def changeEvent(self,event):
            if event.type() in (QEvent.Type.StyleChange,QEvent.Type.PaletteChange) and not getattr(self,"_closed",True) and hasattr(self,"body"):
                self._apply_theme()
            super().changeEvent(event)

        # ---- lifecycle (unchanged contract) -----------------------------
        def _link_owner(self,widget):
            if not any(ref() is widget for ref in self._owners):
                self._owners.append(weakref.ref(widget))
            widget._support_dialog=self

        def _retire(self,*_args):
            if self._closed:return
            self._closed=True
            self._collect_cancel.set()
            self._timer.stop();self._filter_timer.stop()
            self._reload_requested=False
            for ref in self._owners:
                widget=ref()
                if widget is not None and getattr(widget,"_support_dialog",None) is self:
                    widget._support_dialog=None
            self._owners.clear()
            self._rows=[];self._filtered=[];self._search_rows=[];self._selected=[]
            self._data=None;self._result=None;self._analysis=None
            emit("report.dialog",result="completed",phase="closed",report_id=report_id)
            if not self._jobs:self.deleteLater()

        def _job_finished(self):
            self._jobs-=1
            if self._closed and not self._jobs:self.deleteLater()
            return self._closed

        def _tick(self):
            if self._closed:return
            if instance:
                self.details_mode.blockSignals(True);self.details_mode.setChecked(instance.detailed);self.details_mode.blockSignals(False)
                if instance.write_error and not getattr(self,"_warned_write",False):
                    self._warned_write=True
                    bind_text(self.note,tr("诊断记录写入失败；工程操作仍可使用。请检查磁盘空间，或换一个可写入的位置导出。错误：{error}",error=instance.write_error))

        def _details_changed(self,checked):
            if instance:instance.set_detailed(600 if checked else 0)
            if checked:
                bind_text(self.note,tr("已开始详细记录 10 分钟：重做一次出问题的操作，再按刷新。"))

        def _scope_changed(self):
            custom=self.scope.currentData()=="range"
            self.start.setVisible(custom);self.end.setVisible(custom);self._load()

        def _options(self):
            return dict(scope=self.scope.currentData(),start=self.start.dateTime().toUTC().toString(Qt.DateFormat.ISODateWithMs),
                        end=self.end.dateTime().toUTC().toString(Qt.DateFormat.ISODateWithMs),report=marked)

        def _load(self):
            if self._closed:return
            self._load_generation+=1
            if self._loading:
                self._reload_requested=True
                return
            generation=self._load_generation;options=self._options()
            description=self.description.text()
            self._loading=True;self._jobs+=1
            self.refresh.setEnabled(False)
            if self._analysis is None:self.timeline.set_message(tr("正在读取记录…"))
            def work():
                began=time.perf_counter();timings={}
                try:
                    answer=collect(editor_diagnostics.root_dir() if instance is None else instance.root,instance=instance,
                        cancelled=self._collect_cancel.is_set,deadline=time.monotonic()+30,**options)
                    timings['collect_ms']=(time.perf_counter()-began)*1000
                    if self._collect_cancel.is_set():raise InterruptedError('closed')
                    phase=time.perf_counter()
                    answer['analysis']=analyze(answer,marked)
                    timings['analyze_ms']=(time.perf_counter()-phase)*1000
                    if self._collect_cancel.is_set():raise InterruptedError('closed')
                    phase=time.perf_counter()
                    answer['summary']=summary(answer,report_id,description,marked)
                    answer['search_rows']=[json.dumps(r,ensure_ascii=False).casefold() for r in answer['events']]
                    answer['event_bytes']=sum(len(s.encode('utf8')) for s in answer['search_rows'])
                    timings['summary_index_ms']=(time.perf_counter()-phase)*1000
                    timings['total_ms']=(time.perf_counter()-began)*1000
                    answer['collection_timings']=timings
                except Exception as exc:answer={"error":type(exc).__name__}
                try:self._signals.loaded.emit((generation,answer))
                except RuntimeError:pass
            try:threading.Thread(target=work,name="diagnostic-view",daemon=True).start()
            except Exception as exc:self._loaded((generation,{"error":type(exc).__name__}))

        def _loaded(self,value):
            generation,data=value
            self._loading=False
            if self._job_finished():return
            if self._reload_requested:
                self._reload_requested=False
                self._load()
                return
            if generation!=self._load_generation:return
            self.refresh.setEnabled(True)
            if data.get("error"):
                bind_text(self.note,tr("读取诊断记录失败（{error}）；请稍后按刷新重试。",error=data["error"]))
                self.timeline.set_message(tr("读取诊断记录失败"))
                return
            self._data=data;self._rows=data["events"];self._search_rows=data['search_rows']
            self.export.setEnabled(True);self.copy.setEnabled(True)
            emit('report.collection',result='completed',report_id=report_id,
                timings=data.get('collection_timings',{}),event_count=len(self._rows))
            self._analysis=data["analysis"]
            self.summary.setPlainText(data['summary'])
            self._render()
            # Populate the 600-cell log table only when its page is requested.
            self._log_pending=True
            if self.views.currentIndex()==1:self._filter()
            size=data['event_bytes']
            bind_text(self.note,tr("{count} 笔记录（约 {size} KiB）。诊断包只在本机生成，不含字幕全文、媒体、提示词与 AI 回复，由你自己发送。",
                                   count=f"{len(self._rows):,}",size=f"{size/1024:.0f}"))

        # ---- presentation -----------------------------------------------
        def _render_legend(self):
            theme=views.active_theme();palette=views.tones(theme)
            analysis=self._analysis
            entries=legend(analysis) if analysis else [("danger",tr("需要处理"),0),("warn",tr("请核对"),0),("warn",tr("卡顿"),0),("info",tr("已自动处理"),0),("muted",tr("可忽略"),0)]
            for chip,(tone,label,number) in zip(self._legend,entries):
                dot=palette[tone][0] if tone!="muted" else theme.text_muted
                value="—" if analysis is None else str(number)
                chip.setText(f"<span style='color:{dot}'>●</span>&nbsp;{label}&nbsp;<b style='color:{theme.text}'>{value}</b>")
                chip.setProperty("i18nUserText",True)

        def _render(self):
            analysis=self._analysis
            self._render_legend()
            if analysis.anchor_is_mark:
                bind_text(self.title,tr("你在 {time} 按下回报",time=local_clock(analysis.anchor)))
            else:
                bind_text(self.title,tr("记录到 {time} 为止",time=local_clock(analysis.anchor)))
            quiet=not any(analysis.counts.get(k) for k in ("act","check","stall"))
            self.banner.setVisible(quiet)
            self.steps.set_analysis(analysis)
            if analysis.running:
                bind_text(self.running,tr("仍在执行：{items}（通常正常）",items=" · ".join(str(n) for n in analysis.running)))
            else:self.running.clear()
            self.running.setVisible(bool(analysis.running))
            choice=analysis.start_step or (analysis.steps[-1] if analysis.steps else None)
            keep=self._selected_step if analysis.step(self._selected_step) else None
            self.select_step(keep or (choice.id if choice else None),force=True)

        def select_step(self,step_id,force=False):
            if self._analysis is None:return
            if step_id==self._selected_step and not force:return
            self._selected_step=step_id
            step=self._analysis.step(step_id) if step_id else None
            self.timeline.set_analysis(self._analysis,step_id)
            if step_id:self.steps.select(step_id)
            count=sum(1 for s in self._analysis.event_steps if s==step_id) if step_id else 0
            self.detail.show_step(self._analysis,step,count)

        def _refresh_summary(self):
            if getattr(self,"_data",None) and not (self._result and not self._result.get("error")):
                self.summary.setPlainText(summary(self._data,report_id,self.description.text(),marked))

        def show_view(self,name):
            index={"timeline":0,"log":1,"summary":2}[name]
            if name=="summary":self._refresh_summary()
            if name=="log" and getattr(self,'_log_pending',False):self._filter()
            self.views.setCurrentIndex(index)
            button=self._view_buttons[name]
            if not button.isChecked():button.setChecked(True)

        def show_step_log(self,step_id):
            self._set_step_filter(step_id,refilter=False)
            self._set_problem_filter(False,refilter=False)
            self._filter()
            self.show_view("log")

        def _set_problem_filter(self,value,refilter=True):
            self._only_problems=value
            (self.only_problems if value else self.all_rows).setChecked(True)
            if refilter:self._filter()

        def _set_step_filter(self,step_id,refilter=True):
            self._step_filter=step_id
            step=self._analysis.step(step_id) if (self._analysis and step_id) else None
            if step is not None:
                bind_text(self.step_filter,tr("只看这一步：{name}（{ago}）  ×",name=step.name,ago=ago_text(self._analysis,step.start)))
            self.step_filter.setVisible(step is not None)
            if refilter:self._filter()

        def _filter(self):
            if self._closed:return
            self._log_pending=False
            analysis=self._analysis
            if analysis is None:return
            problems=sum(analysis.event_problem)
            bind_text(self.only_problems,tr("只看问题 {count}",count=problems))
            bind_text(self.all_rows,tr("全部 {count}",count=f"{len(self._rows):,}"))
            for button in (self.only_problems,self.all_rows):
                font=button.font();font.setBold(True)
                button.setMinimumWidth(QFontMetrics(font).horizontalAdvance(button.text())+34)
            level=self.level.currentData() or "";keyword=self.keyword.text().strip().casefold()
            if keyword.startswith("#"):keyword='"sequence": '+keyword[1:]
            rows=[]
            for index,(row,text) in enumerate(zip(self._rows,self._search_rows)):
                if self._only_problems and not analysis.event_problem[index]:continue
                if self._step_filter and analysis.event_steps[index]!=self._step_filter:continue
                if level and row.get("level")!=level:continue
                if keyword and keyword not in text:continue
                rows.append(index)
            rows.reverse()
            self._filtered_index=rows
            self._filtered=[self._rows[i] for i in rows]
            self._offset=0;self._page(0)

        def _page(self,direction):
            total=len(self._filtered)
            self._offset=max(0,min(max(0,(total-1)//PAGE_ROWS)*PAGE_ROWS,self._offset+direction*PAGE_ROWS))
            indexes=self._filtered_index[self._offset:self._offset+PAGE_ROWS]
            theme=views.active_theme();palette=views.tones(theme)
            analysis=self._analysis
            self.table.setRowCount(len(indexes))
            from PySide6.QtGui import QColor
            for line,index in enumerate(indexes):
                row=self._rows[index];stamp=_stamp(row.get("time"))
                kind=analysis.event_kind[index]
                if kind:level_text=tr(KIND_LABELS[kind]);tone={"act":"danger","check":"warn","stall":"warn","slow":"warn","auto":"info"}.get(kind,"muted")
                else:
                    level_text=tr(LEVEL_LABELS.get(row.get("level"),str(row.get("level") or "")))
                    tone={"ERROR":"danger","WARN":"warn"}.get(row.get("level"),"muted")
                title,sub=event_title(row)
                step=analysis.step(analysis.event_steps[index])
                cells=(local_clock(stamp,millis=True),str(ago_text(analysis,stamp)),str(level_text),
                       str(step.name) if step else "—",f"{title}  {sub}" if sub else str(title),f"#{row.get('sequence','')}")
                for column,value in enumerate(cells):
                    item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,index)
                    if column==2:item.setForeground(QColor(views.tone_text(theme,tone)))
                    if column in (1,5):item.setForeground(QColor(theme.text_muted))
                    if column in (0,5):item.setFont(views.mono_font(12))
                    if column==4:item.setToolTip(value)
                    self.table.setItem(line,column,item)
            pages=max(1,(total+PAGE_ROWS-1)//PAGE_ROWS)
            bind_text(self.page_label,tr("第 {page}／{pages} 页 · 共 {count} 笔",page=self._offset//PAGE_ROWS+1,pages=pages,count=total))
            self._pagination.setVisible(total>PAGE_ROWS)
            if indexes:
                self.table.selectRow(0);self._expand()
            else:
                self.event_title.setText(tr("没有符合条件的记录"));self.event_details.clear();self.event_pill.hide()
                self.back_to_step.setEnabled(False);self.copy_event.setEnabled(False)

        def _current_row_index(self):
            items=self.table.selectedItems()
            return items[0].data(Qt.ItemDataRole.UserRole) if items else None

        def _expand(self):
            index=self._current_row_index()
            if index is None or self._analysis is None:return
            row=self._rows[index];analysis=self._analysis;theme=views.active_theme()
            title,sub=event_title(row);stamp=_stamp(row.get("time"))
            kind=analysis.event_kind[index]
            tone={"act":"danger","check":"warn","stall":"warn","slow":"warn","auto":"info"}.get(kind) or {"ERROR":"danger","WARN":"warn"}.get(row.get("level"),"muted")
            self.event_pill.setText(str(tr(KIND_LABELS[kind]) if kind else tr(LEVEL_LABELS.get(row.get("level"),str(row.get("level"))))))
            self.event_pill.setStyleSheet(views.pill_style(theme,tone));self.event_pill.show()
            self.event_title.setText(str(title))
            step=analysis.step(analysis.event_steps[index])
            issue=next((i for i in analysis.issues if index in i.members),None)
            from .support_triage import _chain_text
            types,where=_chain_text(row.get("exception"))
            pairs=[(tr("事件"),f"{row.get('event_name')} · #{row.get('sequence')}"),
                   (tr("时间"),f"{local_clock(stamp,millis=True)}（{ago_text(analysis,stamp)}）· {row.get('time')}"),
                   (tr("所属步骤"),(f"{step.name}" + (f"（{issue.relation}）" if issue and issue.relation else "")) if step else "—"),
                   (tr("含义"),str(issue.title) if issue else sub),
                   (tr("结果"),row.get("result")),(tr("模块"),row.get("module")),
                   (tr("操作 ID"),row.get("operation_id")),(tr("任务 ID"),row.get("task_id")),
                   (tr("原因链"),types),(tr("代码位置"),where),
                   (tr("规则")," · ".join(str(x) for x in (row.get("error_code"),row.get("rule_detail")) if x))]
            self.event_details.setText(views.key_values_html(theme,pairs))
            self.back_to_step.setEnabled(step is not None);self.copy_event.setEnabled(True)

        def _back_to_step(self):
            index=self._current_row_index()
            if index is None:return
            step_id=self._analysis.event_steps[index]
            if step_id:
                self.select_step(step_id);self.show_view("timeline")

        def _copy_event(self):
            index=self._current_row_index()
            if index is None:return
            QApplication.clipboard().setText(views.row_json(self._rows[index]))
            bind_text(self.note,tr("已复制这一笔记录（JSON）。"))

        def _copy_step(self,step_id):
            step=self._analysis.step(step_id) if self._analysis else None
            if step is None:return
            QApplication.clipboard().setText(views.step_text(self._analysis,step))
            bind_text(self.note,tr("已复制这一步的说明。"))

        def _content_changed(self,checked):
            self.content_preview.setVisible(checked)
            if checked:
                from .event_log import Sanitizer
                sanitizer=instance.sanitizer if instance else Sanitizer()
                self.content_preview.setPlainText("\n\n".join(f"{r['subtitle_id']}\n{sanitizer.string(r['text'])}\n{sanitizer.string(r['translation'])}" for r in self._selected))

        # ---- export / copy / clean --------------------------------------
        def _choose_export(self):
            target,_=QFileDialog.getSaveFileName(self,tr("导出诊断包"),f"2ByteASR-{report_id}.zip","ZIP (*.zip)")
            if target:self._export_to(target)

        def _export_to(self,target):
            if self._closed or self._exporting:return
            options=self._options();options.update(description=self.description.text(),content=list(self._selected) if self.content.isChecked() else None,
                                                   settings=settings_summary(owner.window()))
            self._exporting=True;self._jobs+=1
            self.export.setEnabled(False);bind_text(self.note,tr("正在后台导出并检查诊断包…"))
            emit("export.start",result="started",report_id=report_id,target_path=target)
            def work():
                try:
                    result=export_report(target,root=instance.root if instance else editor_diagnostics.root_dir(),instance=instance,**options)
                    emit("export.end",result=result["status"],report_id=report_id,bytes=result["bytes"])
                except Exception as exc:
                    result={"error":type(exc).__name__}
                    from .event_log import exception_info
                    emit("export.end",level="ERROR",result="failed",report_id=report_id,exception=exception_info(exc))
                try:self._signals.exported.emit(result)
                except RuntimeError:pass
            try:threading.Thread(target=work,name="diagnostic-export",daemon=True).start()
            except Exception as exc:
                emit("export.end",level="ERROR",result="failed",report_id=report_id,error_code=type(exc).__name__)
                self._exported({"error":type(exc).__name__})

        def _exported(self,result):
            self._exporting=False
            if self._job_finished():return
            self.export.setEnabled(True);self._result=result
            if result.get("error"):
                bind_text(self.note,tr("导出失败（{error}），旧文件没有被替换。请换一个可写入且有空间的文件夹，或缩小时间范围重试。",error=result["error"]))
                return
            self.summary.setPlainText(result["summary"])
            self.folder.setEnabled(True);self.folder.show();self.folder_action.setEnabled(True)
            message=tr("已导出并检查：{name}（{size} KiB），部分记录缺失，原因写在 manifest.json。请自己发送给开发者。") if result["status"]=="partial" \
                else tr("已导出并检查：{name}（{size} KiB）。请自己发送给开发者。")
            bind_text(self.note,tr(message.source,name=Path(result["target"]).name,size=f"{result['bytes']/1024:.1f}"))
            self.note.setToolTip(result["target"])

        def _copy(self):
            from .event_log import Sanitizer
            sanitizer=instance.sanitizer if instance else Sanitizer()
            self._refresh_summary()
            # Per-line sanitization avoids the free-text size limit cutting a full summary.
            value=self._result.get("summary") if self._result and not self._result.get("error") else self.summary.toPlainText()
            QApplication.clipboard().setText("\n".join(sanitizer.string(line) for line in value.splitlines()))
            bind_text(self.note,tr("已复制诊断摘要；没有自动上传。"))

        def _folder(self):
            if self._result and self._result.get("target"):QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._result["target"]).parent)))

        def _clean(self):
            if self._closed or self._cleaning:return
            self._cleaning=True;self._jobs+=1;self.clear_action.setEnabled(False)
            def work():
                try:
                    result=maintain_sessions(instance.root if instance else editor_diagnostics.root_dir(),current=instance.directory if instance else None,clear=True)
                    message=tr("已清理 {count} 份已结束的记录；正在运行的记录保留。",count=result['removed_sessions'])
                except Exception as exc:message=tr("清理失败：{error}",error=type(exc).__name__)
                try:self._signals.cleaned.emit(message)
                except RuntimeError:pass
            try:threading.Thread(target=work,name="diagnostic-cleanup",daemon=True).start()
            except Exception as exc:self._cleaned(tr("清理失败：{error}",error=type(exc).__name__))

        def _cleaned(self,message):
            self._cleaning=False
            if self._job_finished():return
            self.clear_action.setEnabled(True);bind_text(self.note,message)

        def _drafts(self):
            from ..projects.editor_recovery import candidates,show_draft
            rows=candidates()
            if not rows or page is None:
                bind_text(self.note,tr("没有可以恢复的编辑草稿。"));return
            from datetime import datetime
            labels=[f"{i+1} · {datetime.fromtimestamp(r['saved_at']):%m-%d %H:%M:%S}" for i,r in enumerate(rows)]
            choice,ok=QInputDialog.getItem(self,tr('选择编辑草稿'),tr('草稿保存时间'),labels,0,False)
            if not ok:return
            row=rows[labels.index(choice)];path=Path(row.get('project_path') or '');original=path.is_file()
            if not original:path=Path(row.get('autosave') or '')
            if not path.is_file():bind_text(self.note,tr('工程恢复副本不存在；草稿仍保留在本机。'));return
            def opened():
                if not original:page.project_path=None
                show_draft(page,row)
            page.open_project(path,on_ready=opened);self.close()

        def closeEvent(self,event):
            self._retire()
            super().closeEvent(event)

    dialog=SupportDialog();dialog._link_owner(owner);dialog._link_owner(entry_owner)
    emit("report.dialog",result="completed",phase="shown",report_id=report_id)
    dialog.show();dialog.raise_();return dialog


def _stamp(value):
    from datetime import datetime
    try:return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError,ValueError):return None
