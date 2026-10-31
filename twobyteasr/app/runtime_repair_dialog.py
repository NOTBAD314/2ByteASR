"""Repair exactly the failed role from the GUI's independent runtime."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit
from ..i18n import tr


class _Repair(QThread):
    completed=Signal(object)

    def __init__(self,role,parent):
        super().__init__(parent);self.role=role

    def run(self):
        from ..environment_repair import repair_roles, RepairResult
        from ..system.environment import deep_preflight
        try:
            result=repair_roles([self.role])
            if result.ok:
                checked=deep_preflight(self.role,use_cache=False)
                if not checked.ok:
                    result.ok=False;result.error='；'.join(checked.problems)
            self.completed.emit(result)
        except Exception as exc:
            self.completed.emit(RepairResult(ok=False,kept_old=True,error=str(exc)))


class RuntimeRepairDialog(QDialog):
    def __init__(self,role,parent=None):
        super().__init__(parent);self.setWindowTitle(tr('修复运行环境')+' · '+role)
        self.setMinimumWidth(520);layout=QVBoxLayout(self)
        self.status=QLabel(tr('正在修复 {role}；保留已下载模型、工程和配置。',role=role));self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail)
        self.close_button=QPushButton(tr('关闭'));self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept);layout.addWidget(self.close_button)
        self.worker=_Repair(role,self);self.worker.completed.connect(self.finished_repair)
        self.worker.finished.connect(lambda:self.close_button.setEnabled(True))
        self.worker.start()

    def finished_repair(self,result):
        self.status.setText(tr('运行环境已修复并通过启动和依赖检查。') if result.ok else tr('修复未完成；诊断和旧环境已保留，可关闭后重试。'))
        self.detail.setPlainText(result.success_message if result.ok else result.error)

    def reject(self):
        if not self.worker.isRunning():super().reject()

    def closeEvent(self,event):
        if self.worker.isRunning():event.ignore()
        else:super().closeEvent(event)


def open_runtime_repair(window,role):
    if role not in {'main','moss','firered_llm'}:return False
    dialog=RuntimeRepairDialog(role,window)
    from ..design.studio_theme import apply_secondary_surface_theme
    apply_secondary_surface_theme(dialog)
    dialog.exec()
    dialog.deleteLater()
    return True
