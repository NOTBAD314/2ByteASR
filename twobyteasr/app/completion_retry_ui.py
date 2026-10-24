"""UI adapter for scoped retry proposals and the established Studio review."""
from __future__ import annotations

import copy
from PySide6.QtCore import QThread, Signal
from ..i18n import bind_text, tr


class CompletionRetryThread(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, project, report, options, stage, parent=None):
        super().__init__(parent)
        from ..recognition.service import CancellationToken
        self.token = CancellationToken()
        self.inputs = (project, copy.deepcopy(report), options)
        self.stage = stage

    def run(self):
        try:
            from .completion_retry import completion_retry_preview
            result = completion_retry_preview(*self.inputs, stage=self.stage, cancel_token=self.token)
            self.token.raise_if_cancelled()
            self.ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


def open_completion_retry_review(studio, report, options, *, stage='polish'):
    from ..studio.studio_find_replace import GlossaryReviewDialog, PreviewBinding
    from ..projects.studio_project import SubtitleProject
    project = studio.session.project
    if project is None:
        return
    binding = PreviewBinding.capture(project)
    copied = SubtitleProject.from_dict(copy.deepcopy(project.to_dict()))
    dialog = GlossaryReviewDialog(studio, studio)
    generation = dialog._review_generation
    bind_text(dialog, '重试未完成 AI 校对' if stage == 'polish' else '重试联网核验', property='windowTitle')
    dialog._preview_library_ids = tuple(project.glossary_ids)
    dialog._preview_snapshot_digest = None
    dialog.terms_libraries.setEnabled(False)
    dialog.terms_scope.setEnabled(False)
    dialog.terms_ai_button.setEnabled(False)
    dialog.project_entities_button.setEnabled(False)
    dialog.preview_button.setEnabled(False)
    dialog.all_button.setEnabled(False)
    bind_text(dialog.status_label, '只重试原任务未完成范围，完成后显示差异；原字幕尚未修改。')
    worker = CompletionRetryThread(copied, report, options, stage, dialog)
    dialog._glossary_review_worker = worker
    dialog._completion_retry_receipt = None

    def ready(result):
        if dialog._review_close_pending:
            return
        if dialog._review_generation != generation or not binding.matches(studio.session.project):
            bind_text(dialog.status_label, '工程或文字已改变；重试结果未应用，请重新预览。')
            return
        dialog._fill_preview(list(result.hits), binding)
        dialog._glossary_review_receipt = result.receipt
        dialog._completion_retry_receipt = result.receipt
        scope = result.receipt.get('scope_ids') or []
        failed = result.receipt.get('failed_ids') or []
        pending = result.receipt.get('pending_projection') or []
        bind_text(dialog.status_label, '本次处理 {scope} 条原记录 · 未完成 {failed} 条 · 建议修改 {edits} 条字幕 · 待确认投影 {pending} 项；未核验原音。',
            scope=len(scope), failed=len(failed), edits=len(result.hits), pending=len(pending))
        if pending:
            dialog.status_label.setToolTip('\n'.join(str(row) for row in pending))
        dialog.all_button.setEnabled(bool(result.hits))

    def failed(message):
        if not dialog._review_close_pending:
            bind_text(dialog.status_label, '重试未完成：{reason}。原字幕保持不变。', reason=message)

    def finished():
        dialog._glossary_review_worker = None
        worker.deleteLater()
        if dialog._review_close_pending:
            GlossaryReviewDialog.reject(dialog)

    worker.ready.connect(ready)
    worker.failed.connect(failed)
    worker.finished.connect(finished)
    worker.start()
    dialog.exec()
    return dialog._completion_retry_receipt
