"""Undoable repair of old range-task rosters and their automatic empty lanes."""
from PySide6.QtGui import QUndoCommand

from ..projects.range_speakers import capture_roster, restore_roster, clean_range_speakers
from ..projects.studio_runtime_state import DirtyDomain
from .studio_commands import _commit_mutation


class CleanRangeSpeakersCommand(QUndoCommand):
    def __init__(self, project, changed=None):
        super().__init__('整理局部识别空人物（可撤销）')
        self.project = project
        self.changed = changed
        self.before = capture_roster(project)
        self.after = None
        self.removed_ids = ()
        self.outcome = {"applied": False, "error": "", "ui_error": ""}

    def _apply(self, forward):
        from ..projects.studio_runtime_state import state_for
        revision = state_for(self.project).revision
        previous = capture_roster(self.project)
        def mutate():
            if forward and self.after is None:
                self.removed_ids = clean_range_speakers(self.project)
                self.after = capture_roster(self.project)
            else:
                restore_roster(self.project, self.after if forward else self.before)
        try:
            _commit_mutation(self.project, action_id=self.text(),
                dirty=DirtyDomain.PROJECT_METADATA | DirtyDomain.TIMELINE_INDEX | DirtyDomain.TIMELINE_PIXELS
                      | DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.ADVANCED_PREVIEW | DirtyDomain.AUTOSAVE,
                cue_ids=(), mutate=mutate, changed=self.changed, snapshot_cues=False)
            self.outcome.update(applied=True, error="")
        except Exception as exc:
            if state_for(self.project).revision != revision:
                self.outcome.update(applied=True, ui_error=str(exc))
                return
            restore_roster(self.project, previous)
            self.outcome.update(applied=False, error=str(exc))
            self.setObsolete(True)

    def redo(self):
        self._apply(True)

    def undo(self):
        self._apply(False)
