"""GUI command adopts a private worker plan after its revision guard passes."""
from PySide6.QtGui import QUndoCommand
from ..timeline.studio_commands import SetCuesPresentationCommand


class PreparedPresentationCommand(SetCuesPresentationCommand):
    def __init__(self,project,plan,changed):
        QUndoCommand.__init__(self,'批量应用字幕样式')
        self.project=project
        self.before=plan['before'];self.after=plan['after']
        self.before_styles=plan['before_styles'];self.after_styles=plan['styles']
        self.before_effects=plan['before_effects'];self.after_effects=plan['effects']
        self.before_style_recipes=plan['before_recipes'];self.after_style_recipes=plan['recipes']
        self.changed=changed;self.merge_enabled=False
        self.group_changed=plan.get('group_changed',False)
        self.group_command=None
        if self.group_changed:
            from .caption_group_transform import GroupTransformCommand
            self.group_command=GroupTransformCommand(project,plan['group_after'])

    def redo(self):
        self._combined(False)

    def undo(self):
        self._combined(True)

    def _combined(self,undo):
        if self.group_command is None:
            return super().undo() if undo else super().redo()
        from ..projects.studio_runtime_state import state_for
        from ..subtitle_rules.current_issues import LEGACY_INPUTS
        from .caption_group_transform import KEY
        with state_for(self.project).transaction(self.project,action_id=self.text(),
                affected_cue_ids=self.after,studio_state_keys=(KEY,LEGACY_INPUTS)):
            if undo:
                self.group_command.undo();super().undo()
            else:
                super().redo();self.group_command.redo()
