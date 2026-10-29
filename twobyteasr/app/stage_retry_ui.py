"""A visible task list/progress and persisted results behind completion retry."""
from __future__ import annotations
import copy
from pathlib import Path
from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QTreeWidget,QTreeWidgetItem
from ..recognition.processing_recovery import recover_units,failure_summary,TERMINAL,input_matches,save_unit_states,capture_unit,ACTIVE_KEYS

STAGES={'polish':'文字校对','grouping':'断句','translation':'翻译'}
STATES={'running':'处理中','failed':'未完成','blocked':'缺少输入','completed':'已保存',
        'completed_no_change':'完成，无需修改','proposals_pending':'完成，建议待确认'}


class StageRetryThread(QThread):
    progress=Signal(int,int,object)
    unit_ready=Signal(object)
    ready=Signal(object)
    failed=Signal(str)
    def __init__(self,project,report,options,parent=None):
        super().__init__(parent)
        from ..recognition.service import CancellationToken
        self.token=CancellationToken();self.inputs=(project,copy.deepcopy(report),options)
    def run(self):
        try:
            from .stage_retry import execute_failed_units
            result=execute_failed_units(*self.inputs,cancel_token=self.token,
                progress=self.progress.emit,unit_ready=self.unit_ready.emit)
            self.token.raise_if_cancelled();self.ready.emit(result)
        except Exception as exc:self.failed.emit(str(exc))


def open_failed_stage_review(studio,report,options=None):
    from ..studio.studio_find_replace import GlossaryReviewDialog,PreviewBinding
    from ..studio.studio_text_tools import TextOccurrence
    from ..projects.studio_project import SubtitleProject
    from .stage_retry_commit import commit_unit_result
    project=studio.session.project
    if project is None:return
    path=getattr(studio,'project_path',None) or getattr(studio.session,'project_path',None)
    path=Path(path).resolve() if path is not None else None
    def owns_project():
        current=getattr(studio,'project_path',None) or getattr(studio.session,'project_path',None)
        current=Path(current).resolve() if current is not None else None
        return studio.session.project is project and current==path
    active=getattr(studio,'_stage_retry_dialog',None)
    if active is not None:
        active.show();active.raise_();return
    dialog=GlossaryReviewDialog(studio,studio);studio._stage_retry_dialog=dialog
    dialog.setMinimumSize(700,320);dialog.resize(820,420)
    dialog.setWindowTitle('重试失败任务 · 保留已完成结果')
    dialog._preview_library_ids=tuple(project.glossary_ids);dialog._preview_snapshot_digest=None
    for control in (dialog.terms_libraries,dialog.terms_scope,dialog.terms_ai_button,
                    dialog.project_entities_button,dialog.preview_button,dialog.all_button):control.setEnabled(False)
    def hide_controls(layout):
        for index in range(layout.count()):
            item=layout.itemAt(index)
            if item.widget():item.widget().hide()
            elif item.layout():hide_controls(item.layout())
    hide_controls(dialog.layout().itemAt(0).layout())
    dialog.preview_button.hide()
    tree=QTreeWidget();tree.setHeaderLabels(['阶段','状态','影响字幕','原因 / 结果']);tree.setMinimumHeight(130)
    tree.setRootIsDecorated(False);tree.setColumnWidth(0,110);tree.setColumnWidth(1,160);tree.setColumnWidth(2,90)
    dialog.layout().insertWidget(1,tree);dialog._retry_tasks=tree
    dialog._completion_retry_receipt={'kind':'stable_failed_stage_retry','units':[],'asr_run':False,'saved':False}
    items={};hits=[];errors=[]
    def show_unit(unit):
        item=items.get(unit['key'])
        if item is None:item=QTreeWidgetItem(tree);items[unit['key']]=item
        for i,text in enumerate((STAGES.get(unit['stage'],unit['stage']),STATES.get(unit.get('status'),unit.get('status','')),
                                str(len(unit.get('cue_ids',()))),unit.get('reason',''))):item.setText(i,text)
        item.setToolTip(3,unit.get('reason',''))
        item.setData(0,256,unit.get('cue_ids',[]))
    def locate(item,*_):
        ids=item.data(0,256) or []
        if ids and owns_project():
            studio.select_cue(ids[0])
            cue=next((c for c in project.cues if c.id==ids[0]),None)
            if cue is not None and hasattr(studio,'_seek'):studio._seek(cue.start_ms/1000)
    tree.itemClicked.connect(locate)
    units=recover_units(project,report)
    for unit in units:show_unit(unit)
    first=next((u for u in units if u.get('cue_ids') and u.get('status') not in TERMINAL),None)
    if first is not None:tree.setCurrentItem(items[first['key']]);locate(items[first['key']])
    def refresh_preview():
        hits.clear()
        for unit in recover_units(project,report):
            if unit.get('status')=='proposals_pending' and input_matches(project,unit['input']):
                hits.extend(TextOccurrence(**row) for row in unit.get('proposals',()))
        dialog._fill_preview(hits,PreviewBinding.capture(project))
        dialog.all_button.setEnabled(bool(hits))
        dialog.preview.setVisible(bool(hits));dialog.all_button.setVisible(bool(hits))
        dialog.select_all_button.setVisible(bool(hits));dialog.select_none_button.setVisible(bool(hits))
        if hits:
            dialog.setMinimumHeight(520)
            if dialog.height()<600:dialog.resize(dialog.width(),660)
        dialog._glossary_review_receipt=dialog._completion_retry_receipt
    def status():
        summary=failure_summary(project,report)
        dialog.status_label.setText(f"失败任务 {summary['failed_tasks']} 项 · 影响字幕 {summary['affected_cues']} 条 · "
            f"校对建议 {len(hits)} 条"+(' · 见未保存原因' if errors else ''))
        dialog.status_label.setToolTip('\n'.join(errors) if errors else '断句和译文通过校验并保存后更新；文字校对建议需确认。')
    def unit_ready(unit):
        if dialog._review_close_pending:return
        if not owns_project():
            errors.append('当前工程或保存路径已切换，结果未写入');dialog.all_button.setEnabled(False);return
        try:
            saved=commit_unit_result(studio,report,unit)
            dialog._completion_retry_receipt['units'].append(saved);dialog._completion_retry_receipt['saved']=True
            show_unit(saved);refresh_preview();status()
        except Exception as exc:
            errors.append(str(exc));failed_unit={**unit,'status':'failed','reason':str(exc),'last_attempt_input':unit.get('input')}
            if owns_project():
                failed_unit['input']=capture_unit(project,failed_unit)
                try:save_unit_states(project,report,[failed_unit],path=studio.project_path)
                except Exception as save_error:errors.append(str(save_error))
            show_unit(failed_unit);status()
    def progress(done,total,unit):
        if not dialog._review_close_pending:
            dialog.status_label.setText(f"正在重试 {done}/{total}：{STAGES.get(unit['stage'],unit['stage'])} · "
                f"影响 {len(unit.get('cue_ids',()))} 条字幕")
    def failed(message):
        errors.append(message);status()
    def ready(_):
        if not owns_project():
            dialog.all_button.setEnabled(False);dialog._preview_binding=None
            dialog.status_label.setText('工程或保存路径已切换；未写回旧对象，可重新打开原任务继续重试。');return
        refresh_preview();status()
    worker=None
    try:
        running=[{**u,'status':'running'} for u in units if u.get('retryable') and u.get('status') not in TERMINAL]
        if running:
            if path is None:raise ValueError('工程没有保存路径，不能标记成功或开始重试')
            ACTIVE_KEYS.update(u['key'] for u in running)
            save_unit_states(project,report,running,path=path)
            for unit in running:show_unit(unit)
            copied=SubtitleProject.from_dict(copy.deepcopy(project.to_dict()))
            worker=StageRetryThread(copied,report,options,dialog);dialog._glossary_review_worker=worker
            worker.unit_ready.connect(unit_ready);worker.progress.connect(progress)
            worker.ready.connect(ready);worker.failed.connect(failed)
            def finished():
                dialog._glossary_review_worker=None
                cancelled=[{**u,'input':capture_unit(project,u),'status':'failed','reason':'本次重试已取消，保留原文，可继续重试'}
                    for u in recover_units(project,report) if owns_project() and u.get('status')=='running']
                if cancelled:
                    try:save_unit_states(project,report,cancelled,path=path)
                    except Exception as exc:errors.append(str(exc))
                ACTIVE_KEYS.difference_update(u['key'] for u in running)
                if dialog._review_close_pending:GlossaryReviewDialog.reject(dialog)
                worker.deleteLater()
            worker.finished.connect(finished);worker.start()
        else:refresh_preview();status()
        dialog.exec()
    except Exception as exc:
        errors.append(str(exc));status();dialog.exec()
    finally:
        ACTIVE_KEYS.difference_update(u['key'] for u in units)
        studio._stage_retry_dialog=None
    return dialog._completion_retry_receipt
