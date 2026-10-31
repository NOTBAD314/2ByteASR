"""Undoable review metadata, separate from changing caption text."""
from PySide6.QtGui import QUndoCommand

from ..projects.studio_runtime_state import DirtyDomain, _json_snapshot, notify_legacy_if_unbound, state_for
from .proofread_rules import DECISIONS_KEY


class StartProofreadRoundCommand(QUndoCommand):
    def __init__(self, project, *, changed=None):
        super().__init__('重新开始本轮校对')
        from .proofread_retention import REVIEW_KEY
        from uuid import uuid4
        self.project, self.changed = project, changed
        self.keys = (REVIEW_KEY, DECISIONS_KEY)
        self.before = {key: _json_snapshot(project.studio_state.get(key)) for key in self.keys}
        self.after = {REVIEW_KEY: dict(version=1, round_id=uuid4().hex, rows={}), DECISIONS_KEY: {}}

    def _apply(self, values):
        state = state_for(self.project)
        with state.transaction(self.project, action_id=self.text(), dirty=DirtyDomain.AUTOSAVE, snapshot_cues=False):
            for key, value in values.items():
                if value is None:
                    self.project.studio_state.pop(key, None)
                else:
                    self.project.studio_state[key] = _json_snapshot(value)
        notify_legacy_if_unbound(self.project, self.changed)

    def redo(self): self._apply(self.after)
    def undo(self): self._apply(self.before)


class IgnoreProofreadRowCommand(QUndoCommand):
    def __init__(self, project, cue_id, decisions, *, changed=None, label="忽略本行建议"):
        super().__init__(label)
        self.project, self.cue_id, self.changed = project, cue_id, changed
        self.before = _json_snapshot(project.studio_state.get(DECISIONS_KEY))
        self.after = {**(self.before or {}), cue_id: _json_snapshot(decisions)}
        from .proofread_retention import review_state
        self.review_before = {cue_id: _json_snapshot(review_state(project)['rows'].get(cue_id))}
        self.review_after = {cue_id: dict(self.review_before[cue_id] or {}, retained=False, dismissed=True)}

    def _apply(self, value):
        # No text/QC/render invalidation: only the document's save revision.
        state = state_for(self.project)
        with state.transaction(self.project, action_id=self.text(), dirty=DirtyDomain.AUTOSAVE,
                               affected_cue_ids=(self.cue_id,), snapshot_cues=False):
            from .proofread_retention import put_records
            put_records(self.project, self.review_after if value is self.after else self.review_before)
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
        from .proofread_retention import review_state
        self.review_before = {key: _json_snapshot(review_state(project)['rows'].get(key)) for key in self.cue_ids}
        self.review_after = {key: dict(value or {}, retained=False, dismissed=True) for key, value in self.review_before.items()}

    def _apply(self, value):
        state = state_for(self.project)
        with state.transaction(self.project, action_id=self.text(), dirty=DirtyDomain.AUTOSAVE,
                               affected_cue_ids=self.cue_ids, snapshot_cues=False):
            from .proofread_retention import put_records
            put_records(self.project, self.review_after if value is self.after else self.review_before)
            if value is None:
                self.project.studio_state.pop(DECISIONS_KEY, None)
            else:
                self.project.studio_state[DECISIONS_KEY] = _json_snapshot(value)
        notify_legacy_if_unbound(self.project, self.changed)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)
