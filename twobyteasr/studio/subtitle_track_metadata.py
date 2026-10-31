"""Explicitly edit an imported track's labels without changing its identity."""
from __future__ import annotations

import copy
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit

from ..i18n import tr
from ..projects.subtitle_import import IMPORT_KEY, imported_track, language_label, normalize_language, normalize_speaker
from ..projects.studio_runtime_state import DirtyDomain as D, state_for


class SetSubtitleTrackMetadataCommand(QUndoCommand):
    def __init__(self, project, track_id, speaker, language, changed=None):
        super().__init__(tr("字幕轨道的说话人和语言…"))
        self.project, self.track_id, self.changed = project, track_id, changed
        self.before_name = next(s.name for s in project.speakers if s.id == track_id)
        self.before = copy.deepcopy(imported_track(project, track_id))
        self.after = dict(self.before, speaker=normalize_speaker(speaker), language=normalize_language(language))
        if language and not self.after["language"]:
            raise ValueError("无效的语言代码")
        base = f"{self.after['speaker'] or self.before_name.split(' · ', 1)[0]} · {language_label(self.after['language'])}"
        used = {s.name.casefold() for s in project.speakers if s.id != track_id}
        self.after_name, counter = base, 2
        while self.after_name.casefold() in used:
            self.after_name = f"{base}（{counter}）"
            counter += 1

    def _apply(self, forward):
        with state_for(self.project).transaction(self.project, action_id=self.text(), dirty=(
                D.PROJECT_METADATA | D.CUE_MODEL | D.TIMELINE_PIXELS | D.AUTOSAVE)):
            speaker = next(s for s in self.project.speakers if s.id == self.track_id)
            speaker.name = self.after_name if forward else self.before_name
            tracks = self.project.generation_metadata.setdefault(IMPORT_KEY, {"version": 1}).setdefault("tracks", {})
            if not forward and not self.before:
                tracks.pop(self.track_id, None)
            else:
                tracks[self.track_id] = copy.deepcopy(self.after if forward else self.before)
        if self.changed:
            self.changed()

    def redo(self): self._apply(True)
    def undo(self): self._apply(False)


def edit_track_metadata(page, track_id):
    from ..subtitle_rules.language_rules import TASK_LANGUAGES
    track = imported_track(page.project, track_id)
    dialog = QDialog(page)
    dialog.setWindowTitle(tr("字幕轨道的说话人和语言…"))
    form = QFormLayout(dialog)
    speaker = QLineEdit(track.get("speaker", ""))
    language = QComboBox()
    language.setEditable(True)
    for code in ("", *TASK_LANGUAGES, "zh-Hans", "zh-Hant"):
        language.addItem(language_label(code), code)
    selected = language.findData(track.get("language", ""))
    language.setCurrentIndex(max(0, selected))
    if selected < 0:
        language.setEditText(track.get("language", ""))
    form.addRow(tr("说话人"), speaker)
    form.addRow(tr("语言"), language)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.Accepted:
        return
    value = language.currentData() if language.currentText() == language.itemText(language.currentIndex()) else language.currentText()
    try:
        page.undo_stack.push(SetSubtitleTrackMetadataCommand(page.project, track_id, speaker.text(), value,
                                                             page._populate_speakers))
    except ValueError as exc:
        page._show_studio_hint(str(exc))
