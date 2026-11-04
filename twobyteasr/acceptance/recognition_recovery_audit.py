"""Isolated Windows UI/worker fault audit; never used by ordinary jobs."""
from __future__ import annotations
import json,os,time,traceback
from pathlib import Path


def worker_fixture(request,emit):
    from dataclasses import asdict
    from ..recognition.task_journal import TaskJournal
    from ..recognition.service import RunOptions,MediaResult,QueueResult,PipelineEvent
    from ..recognition.recognition_result import media_identity_for_task
    from ..projects.studio_project import create_studio_outputs
    from types import SimpleNamespace
    options=RunOptions(**request['options']);mode=os.environ['TWOBYTEASR_QUEUE_AUDIT_MODE']
    journal=TaskJournal(options.job_id).create(request['paths'],options).acquire(resume=options.resume)
    journal.event('stage_started',{'index':1,'label':'测试分片处理','resource':'隔离模拟 worker'})
    emit('event',asdict(PipelineEvent(kind='stage_started',timestamp=time.strftime('%Y-%m-%dT%H:%M:%S%z'),label='测试分片处理',stage_index=1,
                                    stage_total=2,job_id=options.job_id)))
    if mode=='cancel':
        journal.publish('asr:0',{'text':'取消前已保存'},{'source':'isolated-wave'})
        while not Path(request['cancel_path']).is_file():time.sleep(.05)
        item=MediaResult(request['paths'][0],'cancelled',job_id=options.job_id,error='用户主动取消')
        journal.finish((item,));journal.close()
        emit('result',asdict(QueueResult((item,),.5,job_id=options.job_id)))
        return 0
    if mode=='crash':
        journal.publish('asr:0',{'text':'已经保存的测试结果'},{'source':'isolated-wave'})
        began=time.monotonic()
        while not (journal.directory/'release-crash').is_file() or time.monotonic()-began<5:
            if time.monotonic()-began>45:raise RuntimeError('Navigation audit did not release the crash fixture')
            time.sleep(.05)
        # Win32's documented last-chance exception bypasses Python's signal
        # handlers, so the external observer captures a real native context.
        import ctypes
        fail=ctypes.WinDLL('kernel32').RaiseFailFastException
        fail.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
        fail.restype=None
        fail(None,None,1)
    if journal.load_artifact('asr:0',{'source':'isolated-wave'}) is None:
        raise RuntimeError('The saved shard was not recovered')
    media=request['paths'][0]
    output=create_studio_outputs(media,[SimpleNamespace(cue_id=1,start=.2,end=1.2,text='已经保存的测试结果',speaker='S00')],
        txt_path='',generation_metadata={'job_id':options.job_id,'media_identity':media_identity_for_task(media)},
        target_project_path=journal.directory/'result/project.2byteproj')
    ref=json.loads(output['result_ref_json'])
    result=MediaResult(media,'success',job_id=options.job_id,project_path=output['project'],
        project_id=ref['project_id'],result_revision=ref['result_revision'],media_fingerprint=ref['media_fingerprint'],
        result_ref_json=json.dumps(ref),report_json_path=str(journal.path))
    journal.event('studio_project_saved',{'project_path':output['project'],'cue_count':1})
    journal.finish((result,));journal.close()
    emit('result',asdict(QueueResult((result,),.5,job_id=options.job_id)))
    return 0


def start(window,out):
    from PySide6.QtCore import QObject,QTimer
    from PySide6.QtWidgets import QApplication,QLabel,QScrollArea
    from .blank_project_audit import _capture
    from .studio_acceptance_audit import require
    from ..recognition.service import RunOptions
    from ..recognition.task_journal import TaskJournal,read_record
    from ..recognition.recognition_history import parse_recognition_report,RecognitionHistoryDetail
    out=Path(out)
    class Driver(QObject):
        def __init__(self):
            super().__init__(window);self.start=time.monotonic();self.state=0;self.checks={};self.beats=0
            self.beat=QTimer(self);self.beat.setInterval(20);self.beat.timeout.connect(self.heartbeat);self.beat.start()
            self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.step);self.timer.start()
        def heartbeat(self):self.beats+=1
        def check(self,key,value):
            self.checks[key]=bool(value);require(value,key)
        def finish(self,error=''):
            self.timer.stop();self.beat.stop()
            (out/'result.json').write_text(json.dumps({'finished':True,'checks':self.checks,'beats':self.beats,
                'seconds':time.monotonic()-self.start,'error':error},ensure_ascii=False,indent=2),encoding='utf-8')
            os.environ.pop('TWOBYTEASR_QUEUE_AUDIT_MODE',None)
            window._suppress_close_prompt=True
            QTimer.singleShot(100,window.close)
            QTimer.singleShot(1500,QApplication.instance().quit)
        def inspect_real_dialog(self):
            try:
                require(time.monotonic()-self.start<70,'real history dialog timeout')
                dialog=next((w for w in QApplication.topLevelWidgets() if w.isVisible()
                    and w.findChild(RecognitionHistoryDetail)),None)
                if dialog is None:
                    QTimer.singleShot(150,self.inspect_real_dialog);return
                detail=dialog.findChild(RecognitionHistoryDetail)
                labels='\n'.join(label.text() for label in detail.findChildren(QLabel))
                expected=self.real_record.outcome
                self.check('real_history_interrupted',self.real_record.status=='interrupted' and '意外中断' in labels)
                self.check('real_history_cue_count',str(expected.final_cues) in labels)
                self.check('real_history_failed_polish_count',str(expected.fallback_records) in labels and '校对待重试' in labels)
                self.check('real_history_zero_range_and_order','0:00–18:43、18:43–39:58、39:58–60:01' in labels)
                self.check('real_history_resume_visible',detail.resume_button.isVisible() and detail.resume_button.isEnabled())
                self.check('real_history_existing_result_available',detail.open_result_button.isEnabled())
                dialog.findChild(QScrollArea).ensureWidgetVisible(detail.open_result_button)
                _capture(dialog,out/'real-interrupted-detail.png')
                detail.open_result_button.click()
            except BaseException:
                for widget in QApplication.topLevelWidgets():
                    if widget is not window and widget.isVisible():widget.close()
                self.finish(traceback.format_exc())
        def step(self):
            try:
                require(time.monotonic()-self.start<70,'audit timeout')
                if self.state==0:
                    os.environ['TWOBYTEASR_QUEUE_AUDIT_MODE']='crash'
                    window.media_paths=[str(out/'fixture.wav')]
                    window._run_in_progress=True
                    window._launch_pipeline_worker(RunOptions())
                    self.job=window._active_job_id;self.journal=TaskJournal(self.job)
                    self.check('record_before_worker_completion',self.journal.path.is_file())
                    window._open_recognition_history();self.state=1
                elif self.state==1:
                    self.check('worker_survives_history_page',window.worker.isRunning())
                    window.open_studio_project(source='recognition_recovery_library_navigation')
                    self.state=10
                elif self.state==10:
                    page=window.built_page('studio')
                    if page is None or not getattr(page,'_hub_ui_ready',False):return
                    self.check('worker_survives_project_library',window.worker.isRunning())
                    window._return_to_settings()
                    window.showMinimized();self.changed=time.monotonic();self.state=2
                elif self.state==2 and time.monotonic()-self.changed>.7:
                    window.showNormal();window._open_recognition_history();self.state=3
                    (self.journal.directory/'release-crash').write_text('navigation checked',encoding='utf-8')
                elif self.state==3 and not window.worker.isRunning():
                    row=read_record(self.journal.path)
                    self.check('main_alive_after_child_exit',window.isVisible())
                    self.check('interrupted_visible',row['status']=='interrupted')
                    self.check('saved_shard_survives',self.journal.load_artifact('asr:0',{'source':'isolated-wave'}) is not None)
                    self.check('event_loop_live',self.beats>50)
                    receipts=[]
                    for path in (self.journal.directory/'native-faults').glob('*/*.json'):
                        value=json.loads(path.read_text(encoding='utf-8-sig'))
                        if value.get('exception_code'):receipts.append(value)
                    self.check('native_module_and_stack_captured',any(r.get('fault_module') and r.get('native_frames') for r in receipts))
                    window._open_recognition_history();window.history_page.refresh();self.changed=time.monotonic();self.state=4
                elif self.state==4 and time.monotonic()-self.changed>1:
                    self.check('history_page_visible_after_exit',window.pages.currentWidget() is window.history_page)
                    _capture(window,out/'interrupted-history.png')
                    record=parse_recognition_report(self.journal.path)
                    self.detail=RecognitionHistoryDetail(record);self.detail.resize(1100,800);self.detail.show()
                    self.check('continue_button_present',hasattr(self.detail,'resume_button'))
                    self.detail.resume_requested.connect(lambda r:window._resume_recognition_task(r))
                    self.detail.grab().save(str(out/'interrupted-detail.png'))
                    os.environ['TWOBYTEASR_QUEUE_AUDIT_MODE']='resume'
                    self.detail.resume_button.click();self.detail.close();self.state=5
                elif self.state==5 and not window.worker.isRunning():
                    row=read_record(self.journal.path)
                    self.check('same_task_id',window._active_job_id==self.job)
                    self.check('resumed_completed',row['status']=='completed')
                    self.check('one_task_record',len(list(self.journal.directory.parent.glob('*/task.json')))==1)
                    self.check('two_execution_attempts',len(row['task']['attempts'])==2)
                    self.check('project_saved',Path(row['result']['outputs']['project']).is_file())
                    window._open_recognition_history();self.changed=time.monotonic();self.state=6
                elif self.state==6 and time.monotonic()-self.changed>1:
                    _capture(window,out/'recovered-history.png')
                    window._open_completion_from_history(parse_recognition_report(self.journal.path))
                    self.check('history_result_opens_after_prior_job',any(project is not None for item,project in window._completion_tasks))
                    os.environ['TWOBYTEASR_QUEUE_AUDIT_MODE']='cancel'
                    window._run_in_progress=True;window._launch_pipeline_worker(RunOptions())
                    self.cancel_job=window._active_job_id;self.changed=time.monotonic();self.state=7
                elif self.state==7 and time.monotonic()-self.changed>1:
                    window._cancel_run();self.state=8
                elif self.state==8 and not window.worker.isRunning():
                    from ..recognition.task_journal import reconcile
                    cancelled=TaskJournal(self.cancel_job)
                    self.check('cancelled_durable',reconcile(cancelled.path)['status']=='cancelled')
                    self.check('cancel_preserves_result',cancelled.load_artifact('asr:0',{'source':'isolated-wave'}) is not None)
                    if not (out/'real-history-input.json').is_file():self.finish();return
                    inputs=json.loads((out/'real-history-input.json').read_text('utf-8'))
                    self.real_record=parse_recognition_report(Path(inputs['record']))
                    self.real_project_path=inputs['project']
                    window._open_recognition_history()
                    self.state=9
                elif self.state==9:
                    self.timer.stop()
                    QTimer.singleShot(500,self.inspect_real_dialog)
                    window.history_page._show_detail(self.real_record)
                    if (out/'result.json').is_file():return
                    self.changed=time.monotonic();self.state=11;self.timer.start()
                elif self.state==11 and time.monotonic()-self.changed>.7:
                    loaded=[project for item,project in window._completion_tasks if project is not None]
                    self.check('real_history_opens_saved_project',len(loaded)==1 and len(loaded[0].cues)==self.real_record.outcome.final_cues)
                    self.check('real_history_opens_isolated_copy',Path(window._last_studio_project).resolve()==Path(self.real_project_path).resolve())
                    _capture(window,out/'real-recovered-completion.png')
                    self.finish()
            except BaseException:
                self.finish(traceback.format_exc())
    window._recognition_recovery_driver=Driver()
