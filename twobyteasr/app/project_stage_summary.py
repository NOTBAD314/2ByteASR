"""Compact asynchronous project phase status shared by the history pages."""
from datetime import datetime
from html import escape
from time import monotonic

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableView, QVBoxLayout

from ..i18n import tr


_LABELS = {"translation": "翻译", "proofread": "校对", "alignment": "字词对齐",
           "grouping": "断句", "re_asr": "重新识别", "recognition": "识别",
           "download": "下载", "json3": "JSON3 解析", "reconstruction": "智能重建",
           "import": "工程导入", "export": "导出", "vad": "人声检测", "enhancement": "人声增强",
           "lyrics_draft": "歌词草稿", "song_presence": "歌唱检测", "retry": "局部重试"}
_OUTCOMES = {"completed": "完成", "partial": "部分完成", "suggestion": "待采用",
             "failed": "失败", "cancelled": "已取消", "unchanged": "无需调整"}
_SOURCES = {"youtube": "YouTube", "bilibili": "Bilibili", "online_media": "在线媒体", "json3": "JSON3",
            "studio": "Studio", "firered_vad": "FireRedVAD", "lightweight_vad": "轻量 VAD",
            "htdemucs_cpu": "HTDemucs CPU", "htdemucs_cuda": "HTDemucs CUDA",
            "whisper": "Whisper", "sylla": "Sylla-600M", "yamnet": "YAMNet",
            "qwen_local": "Qwen3-ASR", "qwen_ultra_aligner": "Qwen3 Ultra",
            "qwen_aligner": "Qwen3 Forced Aligner", "mfa_aligner": "MFA", "moss": "MOSS",
            "firered_aed": "FireRed AED", "paraformer": "Paraformer",
            "cloud_asr": "云端识别", "multiple_backends": "多个模型", "recognition_pipeline": "识别流程",
            "alignment_retry": "字词对齐", "grouping_retry": "断句", "re_asr_retry": "重新识别"}
_COUNTS = {"cues": "字幕", "tracks": "轨道", "clips": "局部音频", "chunks": "分片", "applied": "已写回",
           "suggested": "建议", "failed": "失败", "total": "范围总数", "drafts": "草稿",
           "lyrics_cues": "歌词", "media": "影音", "subtitle_files": "字幕文件",
           "video_files": "视频文件", "audio_files": "音频文件", "checked": "已检查",
           "missing_translations": "缺少译文", "stale_translations": "译文待更新"}


class _ReceiptsModel(QAbstractTableModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(("时间", "处理阶段", "状态", "来源", "结果数量")[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        column = index.column()
        if column == 0:
            return datetime.fromtimestamp(row["finished"]).strftime("%m-%d %H:%M:%S")
        if column == 1:
            return tr(_LABELS.get(row["stage"], "其他处理"))
        if column == 2:
            return tr(_OUTCOMES.get(row["outcome"], "未知"))
        if column == 3:
            return tr(_SOURCES.get(row.get("source"), "—"))
        return " · ".join(f"{tr(_COUNTS[key])} {value}" for key, value in row["counts"].items()
                        if key in _COUNTS and value)


class _ProjectReceiptsDialog(QDialog):
    def __init__(self, project_id, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("处理阶段记录"))
        self.setObjectName("projectStageReceipts")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(790, 420)
        self.project_id = project_id
        self._cursors = [None]
        self.next_cursor = None
        layout = QVBoxLayout(self)
        table = QTableView(self)
        self.model = _ReceiptsModel(table)
        table.setModel(self.model)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 128)
        table.setColumnWidth(1, 115)
        table.setColumnWidth(2, 100)
        table.setColumnWidth(3, 110)
        layout.addWidget(table)
        controls = QHBoxLayout()
        self.status = QLabel(self)
        controls.addWidget(self.status)
        controls.addStretch(1)
        self.previous = QPushButton(tr("上一页"), self)
        self.following = QPushButton(tr("下一页"), self)
        controls.addWidget(self.previous)
        controls.addWidget(self.following)
        layout.addLayout(controls)
        self.previous.clicked.connect(self._back)
        self.following.clicked.connect(self._forward)
        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._collect)
        self._load()

    def _back(self):
        if len(self._cursors) > 1:
            self._cursors.pop()
            self._load()

    def _forward(self):
        if self.next_cursor is not None:
            self._cursors.append(self.next_cursor)
            self._load()

    def _load(self):
        from ..storage.project_stage_history import stage_page

        self.previous.setEnabled(False)
        self.following.setEnabled(False)
        self.status.setText(tr("正在读取…"))
        self._pending = stage_page(self.project_id, self._cursors[-1])
        self._timer.start()

    def _collect(self):
        if not self._pending.done():
            return
        self._timer.stop()
        try:
            rows, self.next_cursor = self._pending.result()
        except Exception:
            self.status.setText(tr("阶段记录未能读取"))
            return
        self.model.replace(rows)
        self.status.setText(tr("第 {page} 页", page=len(self._cursors)) if rows else tr("没有处理阶段记录"))
        self.previous.setEnabled(len(self._cursors) > 1)
        self.following.setEnabled(self.next_cursor is not None)


class ProjectStageSummary(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setOpenExternalLinks(False)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.linkActivated.connect(self._open_receipts)
        self.setObjectName("projectStageSummary")
        self.hide()
        self._project_id = ""
        self._pending = None
        self._next_read = 0.0
        self._timer = QTimer(self, interval=350)
        self._timer.timeout.connect(self._refresh)

    def set_project(self, project_id):
        project_id = str(project_id or "")
        if project_id == self._project_id:
            return
        self._project_id = project_id
        if self._pending is not None:
            self._pending.cancel()
        self._pending = None
        self._next_read = 0.0
        self.hide()
        if not self._project_id:
            self._timer.stop()
            return
        self._timer.start()
        self._refresh()

    def _refresh(self):
        if not self.parentWidget().isVisible():
            return
        pending = self._pending
        if pending is not None and pending.done():
            self._pending = None
            rows = [] if pending.cancelled() or pending.exception() else pending.result()
            lines = [f"{tr(_LABELS[row['stage']])} {tr(_OUTCOMES[row['outcome']])}"
                     for row in rows if row["stage"] in _LABELS and row["outcome"] in _OUTCOMES]
            text = " · ".join(escape(line) for line in lines)
            if lines:
                text += f' · <a href="stages">{escape(str(tr("查看阶段记录")))}</a>'
            if self.text() != text:
                self.setText(text)
            self.setVisible(bool(lines))
        if self._pending is None and monotonic() >= self._next_read:
            from ..storage.project_stage_history import latest_stages

            self._next_read = monotonic() + 3
            self._pending = latest_stages(self._project_id)

    def _open_receipts(self, target):
        if target == "stages" and self._project_id:
            dialog = _ProjectReceiptsDialog(self._project_id, self.window())
            from ..design.studio_theme import apply_secondary_surface_theme

            apply_secondary_surface_theme(dialog)
            dialog.show()
