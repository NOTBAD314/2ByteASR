"""Resolve template labels from live speaker identity, never from caption text."""
from copy import deepcopy
from PySide6.QtGui import QUndoCommand


def template_speaker(project, cue):
    from .style_resolution import _payload
    if _payload(getattr(cue,'appearance_override',{})).get('_translation_display'): return ''
    settings = project.studio_state.get('speaker_labels', {})
    if settings.get(cue.speaker_id, True) is False: return ''
    speaker = next((s for s in project.speakers if s.id == cue.speaker_id), None)
    if speaker is None or speaker.hidden: return ''
    from ..projects.speaker_names import display_speaker_name
    return display_speaker_name(project, speaker)


class SetSpeakerLabelCommand(QUndoCommand):
    def __init__(self, project, speaker_id, visible, changed=None):
        super().__init__('显示／隐藏模板姓名')
        self.project, self.speaker_id, self.visible, self.changed = project, speaker_id, bool(visible), changed
        self.before = project.studio_state.get('speaker_labels', {}).get(speaker_id)

    def apply(self, value):
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        def mutate():
            settings = self.project.studio_state.setdefault('speaker_labels', {})
            if value is None: settings.pop(self.speaker_id, None)
            else: settings[self.speaker_id] = value
        _commit_mutation(self.project, action_id=self.text(),
            dirty=DirtyDomain.ADVANCED_PREVIEW|DirtyDomain.NATIVE_SUBTITLE|DirtyDomain.AUTOSAVE,
            cue_ids=tuple(c.id for c in self.project.cues if c.speaker_id==self.speaker_id),
            mutate=mutate, changed=self.changed)

    def redo(self): self.apply(self.visible)
    def undo(self): self.apply(self.before)
