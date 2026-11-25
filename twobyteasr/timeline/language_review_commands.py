"""Undoable confirmation of mixed-language source without changing subtitles."""
from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from ..i18n import tr
from ..projects.studio_runtime_state import DirtyDomain
from ..recognition.transcript_acceptance import KEY
from .studio_commands import _commit_mutation


class ConfirmMixedLanguageCommand(QUndoCommand):
    def __init__(self, project, region_id, changed=None):
        super().__init__(tr('确认这段混语'))
        self.project, self.region_id, self.changed = project, str(region_id), changed

    def _apply(self, value):
        state = self.project.generation_metadata.get(KEY) or {}
        region = next((row for row in state.get('observed_ranges', [])
                       if str(row.get('id')) == self.region_id and row.get('reason') == 'language_guard_pending'), None)
        if region is None:
            return

        def mutate():
            if value:
                region.update(confirmed_mixed_language=True, resolved=True)
            else:
                region.pop('confirmed_mixed_language', None)
                region.pop('resolved', None)

        _commit_mutation(self.project, action_id='confirm_mixed_language', dirty=DirtyDomain.AUTOSAVE | DirtyDomain.PROJECT_METADATA,
                         cue_ids=(), mutate=mutate, changed=self.changed, snapshot_cues=False,
                         studio_state_keys=(), generation_metadata_keys=(KEY,))

    def redo(self):
        self._apply(True)

    def undo(self):
        self._apply(False)
