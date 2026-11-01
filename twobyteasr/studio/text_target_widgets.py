"""Shared, always-visible object/language-track choice for text operations."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QComboBox, QLabel, QHBoxLayout, QVBoxLayout
from ..i18n import tr
from .subtitle_text_targets import text_entries
from ..projects.subtitle_import import language_label


class TextTargetSelector(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("操作对象")))
        self.mode = QComboBox()
        for label, value in (("原文", "original"), ("译文", "translation"), ("原文＋译文", "both")):
            self.mode.addItem(tr(label), value)
        row.addWidget(self.mode)
        row.addWidget(QLabel(tr("译文语言 / 轨道")))
        self.track = QComboBox()
        self.track.setMinimumWidth(170)
        row.addWidget(self.track, 1)
        layout.addLayout(row)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.mode.currentIndexChanged.connect(self._changed)
        self.track.currentIndexChanged.connect(self._changed)

    def bind(self, project, page=None):
        self._project = project
        self.mode.blockSignals(True)
        self.track.blockSignals(True)
        previous = self.track.currentData()
        self.track.clear()
        self.track.addItem(tr("全部译文轨道"), "")
        speakers = {s.id: s.name for s in project.speakers} if project else {}
        entries = text_entries(project, mode="translation")
        timeline = getattr(page, "timeline", None)
        selected = getattr(getattr(page, "session", None), "selected_cue_id", "")
        current = next((e for e in entries if e.target.cue_id == selected and
                        (e.target.storage == "translation") == (getattr(timeline, "active_subtitle_layer", "") == "translation")), None)
        # Unclassified imports remain original on entry; they may be chosen
        # explicitly as a translation track without altering their metadata.
        if project is not None:
            imported = project.generation_metadata.get('subtitle_imports', {}).get('tracks', {})
            explicit = {key for key, info in imported.items() if info.get('role') == 'independent'}
            available = {entry.target.track_id for entry in entries}
            entries += text_entries(project, mode='translation', tracks=explicit-available) if explicit-available else []
        seen = set()
        for entry in entries:
            ref = entry.target
            if ref.track_id not in seen:
                seen.add(ref.track_id)
                name = tr("生成译文") if ref.storage == "translation" else speakers.get(ref.track_id, ref.track_id)
                self.track.addItem(f"{language_label(ref.language)} · {name}", ref.track_id)
        self.mode.setCurrentIndex(1 if current else 0)
        selected_track = current.target.track_id if current else previous
        index = self.track.findData(selected_track)
        self.track.setCurrentIndex(index if index >= 0 and selected_track else (1 if seen else 0))
        self.mode.blockSignals(False)
        self.track.blockSignals(False)
        self._changed(emit=False)

    def mode_value(self):
        return str(self.mode.currentData() or "original")

    def tracks(self):
        value = self.track.currentData()
        return {value} if value else {self.track.itemData(i) for i in range(1,self.track.count())}

    def entries(self, project=None):
        return text_entries(project or self._project, mode=self.mode_value(), tracks=self.tracks())

    def _changed(self, *_args, emit=True):
        self.track.setEnabled(self.mode_value() != "original" and self.track.count() > 1)
        entries = self.entries() if hasattr(self, "_project") else []
        label = self.mode.currentText()
        if self.mode_value() != "original":
            label += " · " + self.track.currentText()
        note = tr("当前对象：{scope} · {count} 条文本。", scope=label, count=len(entries))
        if self.mode_value() != 'original':
            note += tr('空译文已跳过；补译请使用翻译功能。')
        if self.track.count() <= 1:
            note = tr("暂无译文；仍可校对或替换原文。") + " " + note
        self.note.setText(note)
        if emit:
            self.changed.emit()
