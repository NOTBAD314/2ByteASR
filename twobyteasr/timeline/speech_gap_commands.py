"""Undoable human dispositions in the existing speech coverage metadata."""
import copy

from PySide6.QtGui import QUndoCommand

from ..recognition.speech_coverage import KEY
from ..recognition.speech_recovery_project import audio_version
from ..projects.studio_runtime_state import DirtyDomain
from .studio_commands import _commit_mutation


class ConfirmNoSpeechCommand(QUndoCommand):
    def __init__(self, project, gap_ids, changed=None):
        super().__init__('确认无语音／无需恢复')
        self.project, self.changed = project, changed
        self.before = copy.deepcopy(project.generation_metadata.get(KEY) or {})
        self.after = copy.deepcopy(self.before)
        decisions = self.after.setdefault('decisions', {})
        selected = set(gap_ids)
        version = audio_version(project, self.before)
        for gap in self.before.get('gaps', ()):
            if gap['id'] in selected:
                decisions[gap['id']] = dict(status='non_speech', audio_version=version,
                                           source_identity=self.before.get('identity'),
                                           start=gap['start'], end=gap['end'])

    def _apply(self, state):
        def mutate():
            self.project.generation_metadata[KEY] = copy.deepcopy(state)
        _commit_mutation(self.project, action_id='speech_gap_decision',
            dirty=DirtyDomain.PROJECT_METADATA | DirtyDomain.AUTOSAVE,
            cue_ids=(), mutate=mutate, changed=self.changed, snapshot_cues=False,
            studio_state_keys=(), generation_metadata_keys=(KEY,))

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)
