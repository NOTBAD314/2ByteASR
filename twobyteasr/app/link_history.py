"""Online download records within the recognition history navigation."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLabel, QTableView, QVBoxLayout, QWidget

from ..i18n import tr
from ..media.link_choices import MODES
from .link_download_widgets import STAGES, TaskCard, button
from .project_stage_summary import ProjectStageSummary


def history_status(task):
    state = task["state"]
    if state == "pending_import" and task.get("mode") == "subtitles" and not task.get("import_note"):
        return "字幕已下载"
    return STAGES.get(state, state)


class DownloadHistoryModel(QAbstractTableModel):
    labels = ("影片", "任务", "状态", "字幕", "说明")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def refresh(self, rows):
        self.beginResetModel()
        self.rows = list(reversed(rows))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.labels)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(self.labels[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row = self.rows[index.row()]
        warnings = row.get("error") or row.get("import_note") or ""
        ai = row.get("subtitle_ai")
        if ai:
            notes = {
                "completed": tr("AI 断句采用 {count} 个范围", count=ai["applied"]),
                "partial": tr("AI 断句部分成功，未通过范围保留智能结果"),
                "failed": tr("AI 断句未完成，已保留智能结果"),
                "missing_settings": tr("AI 断句尚未配置，使用智能结果"),
            }
            warnings = " · ".join(filter(None, (warnings, notes.get(ai["status"]))))
        elif row.get("downloaded_subtitles") and row.get("subtitle_mode") == "smart":
            warnings = " · ".join(filter(None, (warnings, tr("智能整句重建"))))
        mode = "下载后识别" if row.get("recognize") else dict(MODES).get(row.get("mode"), row.get("mode", ""))
        return (row.get("title") or row["video_id"], tr(mode), tr(history_status(row)),
                str(row.get("downloaded_subtitles", 0)), warnings)[index.column()]


class DownloadHistoryPage(QWidget):
    def __init__(self, history, controller):
        super().__init__(history)
        self.setObjectName("onlineDownloadHistory")
        self.controller = controller
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        back = button(tr("返回识别记录"))
        back.clicked.connect(history.show_list)
        heading = QLabel(tr("在线下载记录"))
        heading.setObjectName("historyTitle")
        top.addWidget(back)
        top.addWidget(heading)
        top.addStretch(1)
        outer.addLayout(top)

        self.model = DownloadHistoryModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 235)
        self.table.setColumnWidth(1, 117)
        self.table.setColumnWidth(2, 132)
        self.table.setColumnWidth(3, 48)
        self.table.selectionModel().currentRowChanged.connect(self.update_actions)
        self.table.doubleClicked.connect(self.open_row)
        outer.addWidget(self.table, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        outer.addWidget(self.info)
        self.project_stages = ProjectStageSummary(self)
        outer.addWidget(self.project_stages)
        self.controls = QHBoxLayout()
        outer.addLayout(self.controls)
        self._actions = ()
        self._revision = -1
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def row(self):
        index = self.table.currentIndex().row()
        return self.model.rows[index] if 0 <= index < len(self.model.rows) else None

    def refresh(self):
        if not self.isVisible() and self.model.rows:
            return
        current = (self.row() or {}).get("task_id")
        self._revision, rows = self.controller.queue.history_snapshot(self._revision)
        if rows is not None:
            self.model.refresh(rows)
            index = next((i for i, row in enumerate(self.model.rows) if row["task_id"] == current), 0)
            if self.model.rows:
                self.table.selectRow(index)
        self.update_actions()

    def available(self, row):
        values = TaskCard.available_actions(row)
        if row.get("import_result") and not any(action == "edit" for action, _, _ in values):
            values.insert(0, ("edit", "打开已保存工程", True))
        if row.get("downloaded_subtitles") and row["state"] in {"imported", "pending_import", "partial"}:
            values.append(("reprocess", "重新处理字幕…", False))
        return tuple((name, label) for name, label, _ in values)

    def update_actions(self, *_):
        row = self.row()
        if row is None:
            self.info.setText(tr("选择一条记录查看可用操作。") if self.model.rows else tr("还没有在线下载记录。"))
        else:
            self.info.setText(row.get("error") or row.get("import_note") or tr(history_status(row)))
        self.project_stages.set_project((row.get("import_result") or {}).get("project_id", "") if row else "")
        actions = self.available(row) if row else ()
        if actions == self._actions:
            return
        self._actions = actions
        while self.controls.count():
            widget = self.controls.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        for name, label in actions:
            control = button(tr(label))
            control.clicked.connect(lambda _=False, action=name: self.invoke(action))
            self.controls.addWidget(control)
        self.controls.addStretch(1)

    def invoke(self, name):
        row = self.row()
        if row:
            self.controller.task_action(name, row["task_id"])
        self.refresh()

    def open_row(self, *_):
        row = self.row()
        if row:
            self.invoke("edit" if row.get("import_result") else "preview" if row.get("downloaded_subtitles") else "folder")
