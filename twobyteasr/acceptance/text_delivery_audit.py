"""Actual terminal counts plus explicitly injected save/recovery UI coverage."""
from pathlib import Path
import copy,hashlib,json,sys,time,traceback


def start(window,out):
    from PySide6.QtCore import QObject,QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..recognition.service import MediaResult,QueueResult
    from ..recognition.processing_recovery import failure_summary
    from ..recognition.recognition_outcome import normalize_recognition_outcome
    from ..projects.studio_project import load_project
    out=Path(out);inputs=json.loads((out/'input.json').read_text('utf8'))
    report_path=Path(inputs['report']);project_path=Path(inputs['project'])
    report=json.loads(report_path.read_text('utf-8-sig'));project=load_project(project_path)
    count=len(project.cues)
    protected={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (project_path,report_path,Path(inputs['source_project']),Path(inputs['source_report']))}
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result={'passed':False,'checks':{},'errors':[],'frozen':bool(getattr(sys,'frozen',False)),
                'executable':sys.executable,'terminal_origin':'actual authorized downstream run',
                'save_failure_origin':'explicit UI injection; production filesystem recovery tested separately'}
            self.steps=self.run();self.pending=0;self.timer=QTimer(self)
            self.timer.timeout.connect(self.tick);self.timer.start(40)
        def write(self):(out/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
        def check(self,key,passed,detail=None):
            self.result['checks'][key]={'passed':bool(passed),'detail':detail};self.write()
            if not passed:raise AssertionError(key+': '+str(detail))
        def tick(self):
            try:
                notice=getattr(window,'_completion_dialog',None)
                if notice and notice.isVisible():QTest.mouseClick(notice.confirm_button,Qt.LeftButton)
                if time.monotonic()<self.pending:return
                delay=next(self.steps);self.pending=time.monotonic()+delay
            except StopIteration:self.finish()
            except Exception:self.result['errors'].append(traceback.format_exc());self.finish()
        def complete(self,path,status,project_value):
            item=MediaResult(project.media.path,status,project_path=project_value,report_json_path=str(path))
            window._handle_result(QueueResult((item,),0.));return item
        def run(self):
            window.resize(1700,1000);window._last_run_options=None
            item=self.complete(report_path,report['status'],str(project_path));yield 1.
            # Notification dismissal can animate its dim overlay after the
            # dialog hides. Wait for it before claiming a visual receipt.
            yield .8
            evidence=window._completion_task_evidence[window._completion_task_key(item)]
            outcome=evidence['outcome'];summary=failure_summary(project,report)
            self.check('real_count',window.result_stat_values['count'].text()==str(count),window.result_stat_values['count'].text())
            self.check('real_result_usable',outcome.result_usable and window.export_result_button.isEnabled() and window.open_studio_result_button.isEnabled())
            self.check('real_no_failed_stage',summary['failed_tasks']==0,summary['failed_tasks'])
            self.check('real_failure_button_hidden',not window.retry_failed_button.isVisible())
            from ..recognition.current_review import current_review
            current=current_review(project,report)
            self.check('real_review_count',outcome.review_issue_count==len(current['items']),outcome.review_issue_count)
            self.check('no_unassigned_metadata_todos',not any(row.get('review_scope')=='unassigned_batch_metadata' for row in current['items']))
            _capture(window,out/'actual-completed.png')
            for panel in (window.result_files_panel,window.result_log_panel):
                QTest.mouseClick(panel.header,Qt.LeftButton)
                if panel.mode=='summary':QTest.mouseClick(panel.header,Qt.LeftButton)
            yield .2
            self.check('details_open',window.result_files_panel.mode=='full' and window.result_log_panel.mode=='full')
            _capture(window,out/'actual-details.png')
            failure=copy.deepcopy(report);failure['status']='failed'
            failure['result'].update(cue_count=count,error='')
            failure['result']['outputs']={'project':'','project_error':'[Errno 2] injected atomic project save failure',
                'recovery_project':str(project_path),'generated_cue_count':count}
            fixture=out/'injected-save-failure.json';fixture.write_text(json.dumps(failure,ensure_ascii=False,indent=2),'utf8')
            item=self.complete(fixture,'failed','');yield .5
            self.check('save_failure_preserves_count',window.result_stat_values['count'].text()==str(count))
            self.check('save_failure_truthful_title','字幕已生成' in window.result_title.text() and '可恢复' in window.result_title.text(),window.result_title.text())
            self.check('save_failure_export_not_enabled',not window.export_result_button.isEnabled())
            _capture(window,out/'injected-save-failure.png')
            window._recover_recognition_output();yield .2
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                page=window.built_page('studio')
                if page and page.project and page._readiness.ready:break
                yield .05
            page=window.built_page('studio')
            self.check('recovery_real_project_open',page is not None and page.project is not None and page._readiness.ready)
            self.check('recovery_preserves_text_and_translations',len(page.project.cues)==count and page.project.cues[5].text==project.cues[5].text
                and page.project.generation_metadata.get('translations')==project.generation_metadata.get('translations'))
            self.check('recovery_in_isolated_profile',Path(page.project_path).resolve().is_relative_to(out))
            _capture(window,out/'recovered-project.png')
            self.check('protected_inputs_unchanged',all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in protected.items()))
            self.result['completed']=True
        def finish(self):
            self.timer.stop()
            from .blank_project_audit import _provider_calls,_blocked_external_connections
            self.result.update(provider_calls=_provider_calls,external_connections_blocked=list(_blocked_external_connections))
            self.result['passed']=bool(self.result.get('completed') and not self.result['errors'] and not _provider_calls and not _blocked_external_connections)
            window.result_exit_code=0 if self.result['passed'] else 1
            self.write()
            def stopped():self.result['gui_shutdown']=True;self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            page=window.built_page('studio')
            if page:page.undo_stack.setClean()
            window.close()
    window._text_delivery_audit=Audit()
