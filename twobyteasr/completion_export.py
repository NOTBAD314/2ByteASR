"""Explicit subtitle delivery from a frozen task result, independent of Studio.

2026-10-18: the same format cards, speaker split and file preview as the
Studio “导出字幕” dialog; speakers are chips. The folder is chosen when
exporting and the completion page lists the written files, as before.
"""
from __future__ import annotations

import copy
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .design.presentation import button_role
from .studio_theme import _active_theme, apply_secondary_surface_theme, build_secondary_surface_qss
from .studio_edit_sequence import projected_cues
from .studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts, planned_subtitle_files
from .subtitle_export_widgets import (SPEAKER_CHOICES, ChipFlowLayout, FileList, SegmentedChoice,
                                      build_subtitle_export_qss, chip, footer_frame, format_grid, section_label)

from .i18n import bind_text, tr


def selected_result(project, speaker_ids):
    result = copy.deepcopy(project)
    result.cues = [c for c in result.cues if c.speaker_id in speaker_ids]
    for speaker in result.speakers:
        speaker.hidden = False
    return result


class CompletionExportDialog(QDialog):
    def __init__(self, project, name, parent=None, language="zh"):
        # ``language`` is kept for callers; texts follow the app's UI language.
        super().__init__(parent)
        self.project = copy.deepcopy(project)
        self.artifacts = ()
        bind_text(self, "导出字幕", property="windowTitle")
        self.setObjectName("subtitleExportDialog")
        self.setMinimumWidth(640)
        apply_secondary_surface_theme(self)
        theme = _active_theme(None)
        self.setStyleSheet(build_secondary_surface_qss(theme) + build_subtitle_export_qss(theme))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QVBoxLayout()
        body.setContentsMargins(22, 18, 22, 12)
        body.setSpacing(9)
        root.addLayout(body, 1)
        title = QLabel()
        title.setObjectName("exportDialogTitle")
        bind_text(title, "导出字幕")
        body.addWidget(title)
        source = QLabel(str(name))
        source.setObjectName("exportDialogMeta")
        source.setWordWrap(True)
        body.addWidget(source)
        body.addSpacing(4)

        body.addWidget(section_label("说话人"))
        counts = Counter(c.speaker_id for c in projected_cues(self.project))
        names = {s.id: s.name for s in self.project.speakers}
        chips_host = QWidget()
        chips = ChipFlowLayout(chips_host)
        self.all_speakers = chip("全部说话人", checked=True)
        self.all_speakers.toggled.connect(self._select_all)
        chips.addWidget(self.all_speakers)
        self.speaker_chips: dict[str, QPushButton] = {}
        for sid, count in counts.items():
            label = names.get(sid, sid) or tr("未判定")
            if sid == "S00":
                label = tr("未判定")
            button = chip("")
            button.setChecked(True)
            button.setText(tr("{name} · {count} 条", name=label, count=count))
            button.setToolTip(sid)
            button.setProperty("speakerId", sid)
            button.toggled.connect(self._selection_changed)
            self.speaker_chips[sid] = button
            chips.addWidget(button)
        body.addWidget(chips_host)
        hint = QLabel()
        hint.setObjectName("exportHint")
        bind_text(hint, "只导出选中的说话人；时间位置与空白均保留。")
        body.addWidget(hint)

        body.addWidget(section_label("文件名"))
        # The completion page already supplies the extension-free media name.
        # Dotted identifiers such as .456-467 are part of that name.
        self.name = QLineEdit(str(name))
        self.name.setProperty("fieldWidth", "exportName")
        self.name.textChanged.connect(lambda _text: self._refresh_preview())
        body.addWidget(self.name)

        body.addWidget(section_label("格式（可多选）"))
        self.formats: dict = {}
        body.addWidget(format_grid(self.formats, {"srt"}))
        for card in self.formats.values():
            card.toggled.connect(lambda _checked: self._refresh_preview())

        body.addWidget(section_label("说话人文件"))
        self.mode = SegmentedChoice(SPEAKER_CHOICES)
        self.mode.set_value("combined")
        self.mode.group.buttonToggled.connect(lambda *_args: self._refresh_preview())
        body.addWidget(self.mode)
        self.file_list = FileList()
        body.addWidget(self.file_list)
        self.status = QLabel("")
        self.status.setObjectName("checkWarning")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        body.addStretch(1)

        footer, row = footer_frame()
        row.addStretch(1)
        cancel = QPushButton()
        bind_text(cancel, "取消")
        button_role(cancel, "secondary")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.export_button = QPushButton()
        bind_text(self.export_button, "选择文件夹并导出")
        self.export_button.setObjectName("primary")
        button_role(self.export_button, "primary")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        root.addWidget(footer)
        self._refresh_preview()

    # Chips replace the earlier checkable list; this keeps its reading side.
    @property
    def speakers(self):
        return _ChipList(self.speaker_chips)

    def _selected_speakers(self) -> set[str]:
        return {sid for sid, button in self.speaker_chips.items() if button.isChecked()}

    def _select_all(self, checked):
        for button in self.speaker_chips.values():
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
        self._refresh_preview()

    def _selection_changed(self, _checked=False):
        self.all_speakers.blockSignals(True)
        self.all_speakers.setChecked(all(button.isChecked() for button in self.speaker_chips.values()))
        self.all_speakers.blockSignals(False)
        self._refresh_preview()

    def _options(self) -> SubtitleExportOptions:
        return SubtitleExportOptions(frozenset(f for f, box in self.formats.items() if box.isChecked()),
                                     self.mode.value() or "combined")

    def _refresh_preview(self):
        options = self._options()
        selected = self._selected_speakers()
        ready = bool(selected and options.formats and self.name.text().strip())
        planned = planned_subtitle_files(selected_result(self.project, selected), None, self.name.text(), options) \
            if ready else ()
        self.file_list.set_files(planned)
        if not ready:
            bind_text(self.file_list.header, "请选择说话人、格式并填写文件名。")
        self.export_button.setEnabled(ready)

    def _export(self):
        selected = self._selected_speakers()
        options = self._options()
        if not selected or not options.formats or not self.name.text().strip():
            bind_text(self.status, "请选择说话人、格式并填写文件名。")
            return
        folder = QFileDialog.getExistingDirectory(self, self.windowTitle())
        if not folder:
            return
        try:
            self.artifacts = export_subtitle_artifacts(selected_result(self.project, selected), folder,
                                                       self.name.text(), options)
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.accept()


class _ChipList:
    """Read side of the old QListWidget for scripted acceptance runs."""

    def __init__(self, chips):
        self._chips = list(chips.items())

    def count(self) -> int:
        return len(self._chips)

    def item(self, index: int):
        return _ChipItem(*self._chips[index])


class _ChipItem:
    def __init__(self, sid, button):
        self._sid, self._button = sid, button

    def data(self, _role=None):
        return self._sid

    def checkState(self):
        return Qt.CheckState.Checked if self._button.isChecked() else Qt.CheckState.Unchecked

    def setCheckState(self, state):
        self._button.setChecked(state == Qt.CheckState.Checked)
