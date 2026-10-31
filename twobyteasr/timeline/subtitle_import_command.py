"""A whole import is one additive, reversible Studio transaction."""
from __future__ import annotations

import copy
from PySide6.QtGui import QUndoCommand

from ..projects.subtitle_import import IMPORT_KEY
from ..projects.studio_runtime_state import DirtyDomain as D, state_for, notify_legacy_if_unbound


class ImportSubtitlesCommand(QUndoCommand):
    def __init__(self, project, plan, changed=None, tracks_changed=None):
        super().__init__("替换指定字幕轨道" if plan.replace_track_id else "导入字幕（新增轨道）")
        if not plan.cues:
            raise ValueError("没有可导入的字幕")
        self.project, self.plan, self.changed = project, copy.deepcopy(plan), changed
        self.tracks_changed = tracks_changed
        existing_ids = {cue.id for cue in project.cues}
        new_ids = {cue.id for cue in plan.cues}
        if len(new_ids) != len(plan.cues) or new_ids & existing_ids:
            raise ValueError("导入字幕内部 ID 冲突")
        self.ids = new_ids
        self.track_ids = {speaker.id for speaker in plan.speakers}
        if self.track_ids & {s.id for s in project.speakers}:
            raise ValueError("导入轨道内部 ID 冲突")
        self.removed = [(i, copy.deepcopy(cue)) for i, cue in enumerate(project.cues)
                        if plan.replace_track_id and cue.speaker_id == plan.replace_track_id]
        self.before_imports = copy.deepcopy(project.generation_metadata.get(IMPORT_KEY))
        self.before_order = copy.deepcopy(project.studio_state.get("speaker_track_order"))
        self.before_name = next((s.name for s in project.speakers if s.id == plan.replace_track_id), "")
        self.selection = state_for(project).selected_cue_id

    def _apply(self, forward):
        project, plan = self.project, self.plan
        # Only owned deltas are undone; all unrelated cue objects stay intact.
        cue_backup, speaker_backup = project.cues, project.speakers
        dirty = (D.PROJECT_METADATA | D.CUE_MODEL | D.CUE_CONTENT | D.CUE_TIMING | D.TIMELINE_INDEX
                 | D.TIMELINE_PIXELS | D.NATIVE_SUBTITLE | D.ADVANCED_PREVIEW | D.QC | D.AUTOSAVE)
        affected = self.ids | {cue.id for _, cue in self.removed}
        try:
            with state_for(project).transaction(project, action_id=self.text(), dirty=dirty,
                    affected_cue_ids=affected, selection_after=plan.cues[0].id if forward else self.selection):
                if forward:
                    project.cues = [cue for cue in project.cues if not (
                        plan.replace_track_id and cue.speaker_id == plan.replace_track_id)] + copy.deepcopy(plan.cues)
                    project.speakers = project.speakers + copy.deepcopy(plan.speakers)
                    if plan.replace_track_id:
                        project.speakers = [copy.deepcopy(s) if s.id == plan.replace_track_id else s for s in project.speakers]
                        next(s for s in project.speakers if s.id == plan.replace_track_id).name = plan.replacement_name
                    metadata = project.generation_metadata.setdefault(IMPORT_KEY, {"version": 1})
                    for key, values in (("tracks", plan.tracks), ("instances", plan.instances), ("cues", plan.cue_sources)):
                        metadata.setdefault(key, {}).update(copy.deepcopy(values))
                    order = list(project.studio_state.get("speaker_track_order", []))
                    order.extend(s.id for s in project.speakers if s.id not in order)
                    project.studio_state["speaker_track_order"] = order
                else:
                    project.cues = [cue for cue in project.cues if cue.id not in self.ids]
                    for index, cue in self.removed:
                        project.cues.insert(min(index, len(project.cues)), copy.deepcopy(cue))
                    project.speakers = [s for s in project.speakers if s.id not in self.track_ids]
                    if plan.replace_track_id:
                        project.speakers = [copy.deepcopy(s) if s.id == plan.replace_track_id else s for s in project.speakers]
                        next(s for s in project.speakers if s.id == plan.replace_track_id).name = self.before_name
                    if self.before_imports is None:
                        project.generation_metadata.pop(IMPORT_KEY, None)
                    else:
                        project.generation_metadata[IMPORT_KEY] = copy.deepcopy(self.before_imports)
                    if self.before_order is None:
                        project.studio_state.pop("speaker_track_order", None)
                    else:
                        project.studio_state["speaker_track_order"] = copy.deepcopy(self.before_order)
        except Exception:
            project.cues, project.speakers = cue_backup, speaker_backup
            raise
        notify_legacy_if_unbound(project, self.changed)
        if self.tracks_changed:
            self.tracks_changed()

    def redo(self):
        self._apply(True)

    def undo(self):
        self._apply(False)
