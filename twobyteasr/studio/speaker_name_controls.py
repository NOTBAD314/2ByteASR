"""Per-project, undoable speaker-name visibility."""
from __future__ import annotations
from PySide6.QtGui import QUndoCommand
from ..caption_style.speaker_names import KEY, enabled
from ..i18n import tr


class SetSpeakerNamesCommand(QUndoCommand):
    def __init__(self, project, shown):
        super().__init__(tr('显示说话人姓名'))
        self.project = project
        self.before = project.studio_state.get(KEY)
        self.after = bool(shown)

    def _apply(self, value):
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        def mutate():
            if value is None:
                self.project.studio_state.pop(KEY, None)
            else:
                self.project.studio_state[KEY] = value
        _commit_mutation(self.project, action_id=self.text(),
            dirty=DirtyDomain.NATIVE_SUBTITLE | DirtyDomain.ADVANCED_PREVIEW | DirtyDomain.TIMELINE_PIXELS | DirtyDomain.AUTOSAVE,
            cue_ids=(), mutate=mutate, changed=None, snapshot_cues=False)

    def redo(self): self._apply(self.after)
    def undo(self): self._apply(self.before)


def add_action(page, menu):
    action = menu.addAction(tr('显示说话人姓名'))
    action.setCheckable(True)
    action.setChecked(bool(page.project and enabled(page.project.studio_state)))
    action.setEnabled(page.project is not None)
    def changed(value):
        if page.project is not None:
            page.undo_stack.push(SetSpeakerNamesCommand(page.project, value))
    action.triggered.connect(changed)
    menu.aboutToShow.connect(lambda: action.setChecked(bool(page.project and enabled(page.project.studio_state))))
    return action
