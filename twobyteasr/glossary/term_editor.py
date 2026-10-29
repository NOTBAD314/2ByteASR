"""Small, modeless editor for a real selected-library term."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout

from .term_editing import edit_term
from ..i18n import tr


class TermEditor(QDialog):
    saved = Signal(object)

    def __init__(self, record, parent):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle(tr("编辑词库条目"))
        self.setObjectName("proofreadTermEditor")
        self.setStyleSheet(parent.styleSheet())
        self.resize(500, 410)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("所属词库：{name}", name=record.library_name)))
        layout.addWidget(QLabel(tr("规范词")))
        self.canonical_input = QLineEdit(record.canonical)
        self.canonical_input.setObjectName("proofreadSearch")
        layout.addWidget(self.canonical_input)
        layout.addWidget(QLabel(tr("别名（每行一个；删去一行只删除该别名映射）")))
        self.alias_input = QPlainTextEdit("\n".join(record.aliases))
        self.alias_input.setObjectName("proofreadInput")
        layout.addWidget(self.alias_input, 1)
        self.note = QLabel(tr("内置词的修改保存为用户覆盖，立即参与后续匹配。") if record.builtin else "")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(tr("取消")); cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.save_button = QPushButton(tr("保存词条")); self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

    def save(self):
        import subtitle_core as legacy
        try:
            change = edit_term(legacy, self.record, self.canonical_input.text(), self.alias_input.toPlainText().splitlines())
        except (ValueError, OSError) as exc:
            self.note.setText(str(exc))
            return
        self.saved.emit(change)
        self.accept()
