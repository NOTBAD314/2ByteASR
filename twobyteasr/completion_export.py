"""Explicit subtitle delivery from a frozen task result, independent of Studio."""
from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .studio_edit_sequence import projected_cues
from .studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts

from .i18n import bind_text, tr


def selected_result(project, speaker_ids):
    result = copy.deepcopy(project)
    result.cues = [c for c in result.cues if c.speaker_id in speaker_ids]
    for speaker in result.speakers:
        speaker.hidden = False
    return result


class CompletionExportDialog(QDialog):
    def __init__(self, project, name, parent=None, language="zh"):
        super().__init__(parent)
        self.project = copy.deepcopy(project)
        self.artifacts = ()
        lang = {"zh": 0, "en": 1, "ja": 2}.get(language, 0)
        self.t = lambda zh, en, ja: (zh, en, ja)[lang]
        t = self.t
        bind_text(self, t('导出字幕', 'Export subtitles', '字幕を書き出す'), property='windowTitle')
        self.setMinimumWidth(480)
        self.resize(580, 430)
        layout = QVBoxLayout(self)
        title = QLabel(name)
        title.setWordWrap(True)
        layout.addWidget(title)
        note = QLabel(t("选择要导出的说话人。时间位置与空白均保留。",
            "Choose speakers. Timing and gaps are preserved.", "話者を選択。時刻と空白は保持されます。"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.all_speakers = QCheckBox(t("全部说话人", "All speakers", "すべての話者"))
        self.all_speakers.setChecked(True)
        layout.addWidget(self.all_speakers)
        self.speakers = QListWidget()
        counts = Counter(c.speaker_id for c in projected_cues(self.project))
        names = {s.id: s.name for s in self.project.speakers}
        for sid, count in counts.items():
            label = names.get(sid, sid) or t("未判定", "Unassigned", "未判定")
            if sid == "S00":
                label = t("未判定", "Unassigned", "未判定")
            identity = label if label == sid else f"{label} ({sid})"
            item = QListWidgetItem(f"{identity} · {count} " + t("条字幕", "subtitles", "件"))
            item.setData(Qt.ItemDataRole.UserRole, sid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.speakers.addItem(item)
        self.speakers.setMinimumHeight(70)
        self.speakers.setMaximumHeight(min(230,max(80,len(counts)*38+16)))
        layout.addWidget(self.speakers)
        self.all_speakers.toggled.connect(self._select_all)
        self.speakers.itemChanged.connect(self._selection_changed)
        form = QFormLayout()
        self.name = QLineEdit(Path(name).stem)
        form.addRow(t("文件名", "File name", "ファイル名"), self.name)
        formats = QHBoxLayout()
        self.formats = {}
        for fmt in ("srt", "ass", "txt", "json"):
            box = QCheckBox(fmt.upper())
            box.setChecked(fmt == "srt")
            self.formats[fmt] = box
            formats.addWidget(box)
        form.addRow(t("格式", "Formats", "形式"), formats)
        self.mode = QComboBox()
        for key, label in (("combined", t("合并文件", "Combined", "結合ファイル")),
                           ("per_speaker", t("按说话人分文件", "Separate by speaker", "話者別ファイル")),
                           ("both", t("合并及分文件", "Both", "両方"))):
            self.mode.addItem(label, key)
        form.addRow(t("导出方式", "Output", "出力"), self.mode)
        layout.addLayout(form)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        bind_text(buttons.button(QDialogButtonBox.StandardButton.Cancel), t('取消', 'Cancel', 'キャンセル'))
        export = buttons.addButton(t("选择目录并导出", "Choose folder and export", "保存先を選んで書き出す"),
                                   QDialogButtonBox.ButtonRole.AcceptRole)
        export.setObjectName("primary")
        export.clicked.connect(self._export)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_all(self, checked):
        self.speakers.blockSignals(True)
        for i in range(self.speakers.count()):
            self.speakers.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.speakers.blockSignals(False)

    def _selection_changed(self, _item):
        self.all_speakers.blockSignals(True)
        self.all_speakers.setChecked(all(self.speakers.item(i).checkState() == Qt.CheckState.Checked
                                        for i in range(self.speakers.count())))
        self.all_speakers.blockSignals(False)

    def _export(self):
        selected = {self.speakers.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.speakers.count())
                    if self.speakers.item(i).checkState() == Qt.CheckState.Checked}
        formats = frozenset(f for f, box in self.formats.items() if box.isChecked())
        if not selected or not formats or not self.name.text().strip():
            bind_text(self.status, self.t('请选择说话人、格式并填写文件名。', 'Select speakers, formats and a file name.', '話者、形式、ファイル名を指定してください。'))
            return
        folder = QFileDialog.getExistingDirectory(self, self.windowTitle())
        if not folder:
            return
        try:
            self.artifacts = export_subtitle_artifacts(selected_result(self.project, selected), folder,
                self.name.text(), SubtitleExportOptions(formats, self.mode.currentData()))
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.accept()
