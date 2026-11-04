"""An explicit user decision owned by one project-loading request."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ..i18n import tr
from ..design.studio_theme import apply_secondary_surface_theme


class RecoveryCancelled(Exception):
    pass


@dataclass
class RecoveryChoice:
    candidate: Path
    official_path: Path
    error: str = ''
    choice: str = 'cancel'


class RecoveryDialog(QMessageBox):
    def __init__(self, page, request):
        super().__init__(page)
        self.choice = 'cancel'
        self.setObjectName('projectRecoveryChoice')
        self.setIcon(QMessageBox.Warning)
        self.setWindowTitle(tr('发现未保存的自动恢复版本'))
        self.setText(tr('自动恢复包含正式保存之后的实际修改。'))
        def stamp(path):
            try:
                return datetime.fromtimestamp(path.stat().st_mtime).strftime('%H:%M')
            except OSError:
                return '--:--'
        message = tr('正式保存  {value0}\n自动恢复  {value1}\n\n请选择要打开的版本。',
                     value0=stamp(request.official_path), value1=stamp(request.candidate))
        if request.error:
            message += '\n\n' + tr('上次操作失败：{reason}。可以重试或取消打开。', reason=request.error[:200])
        self.setInformativeText(message)
        self._choices = {}
        for text, role, value in (
                ('恢复自动保存', QMessageBox.AcceptRole, 'recover'),
                ('删除恢复点', QMessageBox.DestructiveRole, 'ignore'),
                ('打开正式保存', QMessageBox.ActionRole, 'saved')):
            button = self.addButton(tr(text), role)
            button.setObjectName('recovery_' + value)
            self._choices[button] = value
            if value == 'recover':
                self.setDefaultButton(button)
        self.buttonClicked.connect(self._clicked)
        self._trace = getattr(page, '_studio_trace', lambda *args, **kw: None)
        self._lease = getattr(getattr(getattr(page, '_readiness', None), 'loading', None), '_input_lease', None)
        if self._lease is not None:
            self._lease.allow_dialog(self)
        self.finished.connect(self._finished)
        apply_secondary_surface_theme(self)

    def _clicked(self, button):
        self.choice = self._choices.get(button, 'cancel')
        self._trace('RECOVERY_BUTTON_CLICK', choice=self.choice)

    def _finished(self, result):
        if self._lease is not None:
            self._lease.release_dialog(self)
        self._trace('RECOVERY_CHOICE_SUBMITTED', choice=self.choice, dialog_result=result)

    def showEvent(self, event):
        super().showEvent(event)
        self._trace('RECOVERY_DIALOG_SHOWN', enabled=self.isEnabled())

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._trace('RECOVERY_DIALOG_FOCUS')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.reject()
        event.accept()
