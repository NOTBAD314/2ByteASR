"""Undoable review metadata, separate from changing caption text."""
from PySide6.QtGui import QUndoCommand

from ..projects.studio_runtime_state import DirtyDomain, _json_snapshot, notify_legacy_if_unbound, state_for
from .proofread_rules import DECISIONS_KEY


class IgnoreProofreadRowCommand(QUndoCommand):
    def __init__(self, project, cue_id, decisions, *, changed=None, label="忽略本行建议"):
        super().__init__(label)
        self.project, self.cue_id, self.changed = project, cue_id, changed
        self.before = _json_snapshot(project.studio_state.get(DECISIONS_KEY))
        self.after = {**(self.before or {}), cue_id: _json_snapshot(decisions)}

    def _apply(self, value):
        # No text/QC/render invalidation: only the document's save revision.
        state = state_for(self.project)
        with state.transaction(self.project, action_id=self.text(), dirty=DirtyDomain.AUTOSAVE,
                               affected_cue_ids=(self.cue_id,), snapshot_cues=False):
            if value is None:
                self.project.studio_state.pop(DECISIONS_KEY, None)
            else:
                self.project.studio_state[DECISIONS_KEY] = _json_snapshot(value)
        notify_legacy_if_unbound(self.project, self.changed)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class IgnoreProofreadRowsCommand(QUndoCommand):
    """One document transaction/save notification for all selected rows."""
    def __init__(self, project, decisions, *, changed=None, label="忽略所选建议"):
        super().__init__(label)
        self.project, self.changed = project, changed
        self.cue_ids = tuple(decisions)
        self.before = _json_snapshot(project.studio_state.get(DECISIONS_KEY))
        self.after = {**(self.before or {}), **_json_snapshot(decisions)}

    def _apply(self, value):
        state = state_for(self.project)
        with state.transaction(self.project, action_id=self.text(), dirty=DirtyDomain.AUTOSAVE,
                               affected_cue_ids=self.cue_ids, snapshot_cues=False):
            if value is None:
                self.project.studio_state.pop(DECISIONS_KEY, None)
            else:
                self.project.studio_state[DECISIONS_KEY] = _json_snapshot(value)
        notify_legacy_if_unbound(self.project, self.changed)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)
