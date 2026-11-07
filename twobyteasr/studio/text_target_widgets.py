"""Shared, always-visible object/language-track choice for text operations.

``compact=True`` (批量替换, 2026-11-02 draft B): the 原文 / 译文 / 原文＋译文
choice is a row of segment buttons; the track list only shows when a
translation is chosen; the note leaves the layout and becomes the buttons'
tooltip, and :meth:`summary` gives the short "原文 · 148 条文本" line for the
title bar. The ``mode`` and ``track`` combo boxes stay the model in both
forms: callers, tests and acceptance scripts drive the selector through them.
"""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QWidget, QComboBox, QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QFrame, QButtonGroup
from ..i18n import bind_text, tr
from .subtitle_text_targets import text_entries
from ..projects.subtitle_import import language_label

MODES = (("原文", "original"), ("译文", "translation"), ("原文＋译文", "both"))


class TextTargetSelector(QWidget):
    changed = Signal()

    def __init__(self, parent=None, *, compact=False, defer_entries=False):
        super().__init__(parent)
        self.compact = compact
        self.defer_entries = defer_entries
        self._count = 0
        self.mode = QComboBox()
        for label, value in MODES:
            self.mode.addItem(tr(label), value)
        self.track = QComboBox()
        self.note = QLabel()
        self.note.setWordWrap(True)
        if compact:
            self._build_compact()
        else:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            row = QHBoxLayout()
            row.addWidget(QLabel(tr("操作对象")))
            row.addWidget(self.mode)
            row.addWidget(QLabel(tr("译文语言 / 轨道")))
            self.track.setMinimumWidth(170)
            row.addWidget(self.track, 1)
            layout.addLayout(row)
            layout.addWidget(self.note)
        self.mode.currentIndexChanged.connect(self._changed)
        self.track.currentIndexChanged.connect(self._changed)

    def _build_compact(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.segments = QFrame()
        self.segments.setObjectName("targetSegments")
        segment_row = QHBoxLayout(self.segments)
        segment_row.setContentsMargins(3, 3, 3, 3)
        segment_row.setSpacing(2)
        self.segment_group = QButtonGroup(self)
        self.segment_group.setExclusive(True)
        self.segment_buttons = {}
        for index, (label, value) in enumerate(MODES):
            button = QPushButton(tr(label))
            button.setObjectName("targetSegment")
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self.mode.setCurrentIndex(i))
            self.segment_group.addButton(button, index)
            self.segment_buttons[value] = button
            segment_row.addWidget(button)
        row.addWidget(self.segments)
        self.track.setObjectName("targetTrackTag")
        self.track.setProperty("fieldWidth", "tag")
        self.track.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        bind_text(self.track, "译文语言 / 轨道", property="toolTip")
        row.addWidget(self.track)
        self.mode.setParent(self)
        self.mode.hide()
        self.note.setParent(self)
        self.note.hide()

    def bind(self, project, page=None):
        self._project = project
        self.mode.blockSignals(True)
        self.track.blockSignals(True)
        previous = self.track.currentData()
        self.track.clear()
        self.track.addItem(tr("全部译文轨道"), "")
        speakers = {s.id: s.name for s in project.speakers} if project else {}
        if self.defer_entries:
            from types import SimpleNamespace
            from .subtitle_text_targets import discover_text_targets
            entries=[SimpleNamespace(target=ref) for ref in discover_text_targets(project)]
        else:entries = text_entries(project, mode="translation")
        timeline = getattr(page, "timeline", None)
        selected = getattr(getattr(page, "session", None), "selected_cue_id", "")
        current = next((e for e in entries if e.target.cue_id == selected and
                        (e.target.storage == "translation") == (getattr(timeline, "active_subtitle_layer", "") == "translation")), None)
        if self.defer_entries and project is not None:
            from ..subtitle_rules.subtitle_translation import translation_view
            from ..subtitle_rules.language_rules import project_language
            cue=next((c for c in project.cues if c.id==selected),None)
            imported=project.generation_metadata.get('subtitle_imports',{}).get('tracks',{})
            info=imported.get(cue.speaker_id,{}) if cue is not None else {}
            foreign=(info.get('role')=='translation' or info.get('role')=='independent'
                and bool(info.get('language')) and str(info['language']).split('-')[0]!=str(project_language(project)).split('-')[0])
            if getattr(timeline,'active_subtitle_layer','')=='translation':
                record=translation_view(project,include_status=False,cue_ids=[selected]).get(selected,{})
                current=next((e for e in entries if e.target.storage=='translation'
                    and e.target.language==record.get('target')),None)
            else:
                current=next((e for e in entries if foreign and cue is not None
                    and e.target.storage=='cue' and e.target.track_id==cue.speaker_id),None)
        # Unclassified imports remain original on entry; they may be chosen
        # explicitly as a translation track without altering their metadata.
        if project is not None:
            imported = project.generation_metadata.get('subtitle_imports', {}).get('tracks', {})
            explicit = {key for key, info in imported.items() if info.get('role') == 'independent'}
            available = {entry.target.track_id for entry in entries}
            entries += text_entries(project, mode='translation', tracks=explicit-available) if explicit-available and not self.defer_entries else []
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
        project = project or self._project
        runtime = getattr(project,'_studio_state_runtime',None)
        key = (id(project),getattr(runtime,'revision',None),self.mode_value(),tuple(sorted(self.tracks())))
        cached = getattr(self,'_turn_entries',None)
        if cached is not None and cached[0] == key:
            return cached[1]
        entries = text_entries(project,mode=self.mode_value(),tracks=self.tracks())
        self._turn_entries=(key,entries)
        QTimer.singleShot(0,lambda:setattr(self,'_turn_entries',None))
        return entries

    def summary(self):
        """(label, count): what the next operation reads, e.g. ("原文", 148)."""
        label = self.mode.currentText()
        if self.mode_value() != "original":
            label += " · " + self.track.currentText()
        return label, self._count

    def _changed(self, *_args, emit=True):
        if self.defer_entries:self._count_ready=False
        has_translation = self.track.count() > 1
        self.track.setEnabled(self.mode_value() != "original" and has_translation)
        if not self.defer_entries:
            entries = self.entries() if hasattr(self, "_project") else []
            self._count = len(entries)
        label, count = self.summary()
        note = tr("当前对象：{scope} · {count} 条文本。", scope=label, count=count)
        if self.mode_value() != 'original':
            note += tr('空译文已跳过；补译请使用翻译功能。')
        if not has_translation:
            note = tr("暂无译文；仍可校对或替换原文。") + " " + note
        self.note.setText(note)
        if self.compact:
            self._sync_segments(has_translation)
        if emit:
            self.changed.emit()

    def _sync_segments(self, has_translation):
        mode = self.mode_value()
        for value, button in self.segment_buttons.items():
            button.setChecked(value == mode)
            # Translation segments wait for a translation, unless one is already chosen.
            button.setEnabled(value == "original" or has_translation or value == mode)
            button.setToolTip("" if button.isEnabled() else tr("暂无译文；仍可校对或替换原文。"))
        self.track.setVisible(mode != "original" and has_translation)
