"""One undo action changes exactly one persisted subtitle-track eye."""
from PySide6.QtGui import QUndoCommand

class VisibilityCommand(QUndoCommand):
    def __init__(self,page,key,visible):
        super().__init__('字幕轨道显隐')
        self.page=page;self.project=page.project;self.key=key;self.after=bool(visible)
        self.before=self.project.studio_state.get('subtitle_track_visibility',{}).get(key,True)
    def _apply(self,value):
        if self.page.project is self.project:
            self.page._apply_subtitle_visibility(self.key,value)
    def redo(self):self._apply(self.after)
    def undo(self):self._apply(self.before)
