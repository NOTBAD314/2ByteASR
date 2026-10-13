"""In-product approval of an external AI change (2026-10-12).

The only way an MCP plan is applied or undone: the user reads the request
here and clicks. Everything shown comes from the client or the project and
is rendered as plain text (no markup, no links), so subtitle text that looks
like an instruction stays text.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .i18n import tr


def describe(plan) -> str:
    lines = [tr("请求：{summary}", summary=plan.summary), tr("工程：{project}（修订 {revision}）",
                                                              project=plan.project_id, revision=plan.revision), ""]
    for change in plan.changes[:200]:
        if plan.kind == "text":
            for name, title in (("text", tr("原文")), ("translation", tr("译文"))):
                if name in change:
                    lines.append(f"#{change['cue_id']} {title}：{change[name]['before']}  →  {change[name]['after']}")
        elif plan.kind == "roles":
            lines.append(f"{change['speaker_id']}：{change['before']} → {change['role']}")
        elif plan.kind == "punctuation":
            from .punctuation_style import MODE_LABELS
            lines.append(tr("字幕标点：{before} → {after}（只影响显示与导出，文稿、时间、说话人不变）",
                            before=tr(MODE_LABELS.get(change["before"], change["before"])),
                            after=tr(MODE_LABELS.get(change["after"], change["after"]))))
            for before, after in change.get("examples") or ():
                lines.append(f"  {before}  →  {after}")
        else:
            lines.append(tr("显示 {mode} · 顺序 {order} · 紧凑排版 {compact}", mode=change["mode"],
                            order=change["order"], compact=tr("是") if change["compact"] else tr("否")))
    if len(plan.changes) > 200:
        lines.append(tr("……另有 {count} 项", count=len(plan.changes) - 200))
    return "\n".join(lines)


class ApprovalDialog(QDialog):
    decided = Signal(bool)

    def __init__(self, parent, plan, *, undo: bool):
        super().__init__(parent)
        self.setObjectName("mcpApprovalDialog")
        self.setWindowTitle(tr("外部 AI 请求撤销修改") if undo else tr("外部 AI 请求修改工程"))
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(640, 420)
        self._answered = False
        layout = QVBoxLayout(self)
        intro = QLabel(tr("一个本机 MCP 客户端请求撤销它套用过的修改。批准后执行一次撤销。") if undo else
                       tr("一个本机 MCP 客户端请求修改当前工程。以下内容来自客户端或字幕本身，只作为数据显示；"
                          "批准后作为一个可撤销的步骤套用。"))
        intro.setTextFormat(Qt.TextFormat.PlainText)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.details = QPlainTextEdit()
        self.details.setObjectName("mcpApprovalDetails")
        self.details.setReadOnly(True)
        self.details.setPlainText(describe(plan))
        layout.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.reject_button = QPushButton(tr("拒绝"))
        self.reject_button.setObjectName("mcpRejectButton")
        self.approve_button = QPushButton(tr("批准撤销") if undo else tr("批准并套用"))
        self.approve_button.setObjectName("mcpApproveButton")
        self.reject_button.setAutoDefault(False)
        self.approve_button.setAutoDefault(False)   # Enter alone never approves
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.approve_button)
        layout.addLayout(buttons)
        self.reject_button.clicked.connect(lambda: self._answer(False))
        self.approve_button.clicked.connect(lambda: self._answer(True))

    def _answer(self, approved: bool) -> None:
        if self._answered:
            return
        self._answered = True
        self.decided.emit(bool(approved))
        self.close()

    def closeEvent(self, event):
        if not self._answered:
            self._answered = True
            self.decided.emit(False)
        super().closeEvent(event)
