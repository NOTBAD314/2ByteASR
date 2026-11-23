"""Normal MainWindow, actual Qt events and controlled A/B/C queue ownership."""
import json,os,threading,time,traceback,shutil,copy
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QEvent,QTimer,Qt
    from PySide6.QtGui import QKeyEvent,QInputMethodEvent,QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QWidget
    app=QApplication.instance();output=Path(output)
    result={'passed':False,'checks':{},'limitations':['Synthetic queue, no real ASR/cloud','Qt IME events, not physical IME']}
    gate=threading.Event();started=threading.Event()
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    def check(name,value):
        result['checks'][name]=bool(value);save()
        if not value:raise AssertionError(name)
    def no_queue_bar():
        return not hasattr(window,'background_queue_bar') and window.findChild(QWidget,'backgroundRecognitionBar') is None
    def open_delivery(path):
        from ..recognition.recognition_result import working_reference
        window.open_studio_project(path,source='background_acceptance',expected_result_ref=working_reference(window._background_ready[path]))
    def wait(predicate,seconds=70):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            if predicate():return
            app.processEvents();time.sleep(.003)
        raise TimeoutError('editor/background wait')
    def shifted(key):QTest.keyClick(QApplication.focusWidget(),key,Qt.ShiftModifier)
    def select(editor,at,end=None):
        from ..studio.caption_editor import qt_position
        cursor=editor.textCursor();cursor.setPosition(qt_position(editor.toPlainText(),at))
        if end is not None:cursor.setPosition(qt_position(editor.toPlainText(),end),QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor);QApplication.setActiveWindow(editor.window());editor.setFocus();app.processEvents()
    def run():
        try:
            if os.environ.get('TWOBYTEASR_TUTORIAL_CENTRE_AUDIT') == '1':
                from .tutorial_centre_audit import run as tutorial_audit
                tutorial_audit(window,output,check)
                result['passed']=all(result['checks'].values());save();window.close();QTimer.singleShot(200,app.quit)
                return
            from .synthetic_queue import FakeLegacy,FakePipeline
            from ..recognition import service
            from ..app import pipeline_worker
            from ..projects.studio_project import load_project,save_project,create_studio_outputs
            from types import SimpleNamespace
            from functools import partial
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'],source='background_acceptance')
            wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None
                 and window.built_page('studio')._readiness.ready)
            page=window.built_page('studio')
            wait(lambda:not window._studio_loading_session.active and not page._readiness.overlay.isVisible())
            page.video.set_paused(True)
            if os.environ.get('TWOBYTEASR_SUBTITLE_EVIDENCE_AUDIT') == '1':
                from .subtitle_evidence_audit import run as evidence_audit
                evidence_audit(window, page, output, check, wait)
                result['passed'] = all(result['checks'].values())
                save()
                window.close()
                QTimer.singleShot(200, app.quit)
                return
            if os.environ.get('TWOBYTEASR_REFINE_RECOVERY_AUDIT') == '1':
                from .sentence_bunny_recovery_audit import run as recovery_audit
                recovery_audit(window, page, output, check, wait)
                result['passed'] = all(result['checks'].values())
                save()
                window.close()
                QTimer.singleShot(200, app.quit)
                return
            if os.environ.get('TWOBYTEASR_VM2_CUMULATIVE_AUDIT') == '1':
                from .vm2_cumulative_audit import run as check_cumulative
                check_cumulative(window, page, output, check, wait)
                result['passed'] = all(result['checks'].values())
                save()
                window.close()
                return
            if os.environ.get('TWOBYTEASR_VM2_TEMPLATE_AUDIT') == '1':
                from .vm2_cumulative_audit import render_templates
                render_templates(output, check)
                result['passed'] = all(result['checks'].values())
                save()
                window.close()
                return
            if os.environ.get('TWOBYTEASR_PLAYHEAD_CENTER_AUDIT') == '1':
                from .playhead_center_audit import run as check_center
                check_center(window,page,output,check)
                result['passed']=all(result['checks'].values());save();window.close();QTimer.singleShot(200,app.quit)
                return
            if os.environ.get('TWOBYTEASR_BUNNY_UNIVERSAL_AUDIT') == '1':
                from .bunny_universal_audit import run as check_universal
                check_universal(window,page,output,check)
            if os.environ.get('TWOBYTEASR_BUNNY_HARNESS_AUDIT') == '1':
                from .bunny_harness_audit import run as check_harness
                check_harness(window,page,output,check)
            if os.environ.get('TWOBYTEASR_BUNNY_AGENT_AUDIT') == '1':
                from .bunny_agent_audit import run as check_agent
                check_agent(window,page,output,check)
                from .bunny_round4_audit import run as check_round4
                check_round4(window,page,output,check)
            if os.environ.get('TWOBYTEASR_BUNNY_VISION_OVERLAY_AUDIT') == '1':
                from .bunny_vision_overlay_audit import run as check_overlay
                check_overlay(window,page,output,check)
            if os.environ.get('TWOBYTEASR_BUNNY_PERSONA_PICTURE_AUDIT') == '1':
                from .bunny_persona_picture_audit import run as check_picture
                check_picture(window,page,output,check)
            if os.environ.get('TWOBYTEASR_BUNNY_HARNESS_P2_AUDIT') == '1':
                from .bunny_harness_p2_audit import run as check_harness_p2
                check_harness_p2(window,page,output,check)
            if os.environ.get('TWOBYTEASR_MOTION_TIMELINE_AUDIT') == '1':
                from .motion_timeline_audit import run as check_timeline
                check_timeline(window,page,output,check)
            page._open_caption_editor('a','original');page._lock_caption_editor()
            e=page.subtitle_edit_input;view=page.caption_suggestion_text
            QApplication.setActiveWindow(page.subtitle_edit_dock);e.setFocus();QTest.qWait(250)
            original=e.toPlainText()
            result['initial_text']=original;save()
            select(e,0,1);shifted(Qt.Key_F)
            check('F applies it from she directly',view.current_row().row.options[view.selected[1]].text=='它' and e.toPlainText()=='它'+original[1:])
            page.subtitle_edit_dock.grab().save(str(output/'01-candidate-selected.png'))
            check('F keeps edit draft open',page._caption_draft is not None)
            check('preview matches draft',page._live_edit_text_overrides.get('a')==e.toPlainText())
            page.subtitle_edit_dock.grab().save(str(output/'01b-candidate-applied.png'))
            shifted(Qt.Key_S);QTest.qWait(40)
            check('S returns same caption body and hides candidate',e.hasFocus() and view.isHidden() and page.subtitle_edit_card.bubble.isHidden() and page._caption_draft.target.cue_id=='a')
            QTest.keyClick(e,Qt.Key_Z,Qt.ControlModifier)
            check('candidate replacement is independently undoable',e.toPlainText()==original)
            select(e,0,1);shifted(Qt.Key_F);page._show_editor_pronouns();shifted(Qt.Key_D);shifted(Qt.Key_A)
            check('A D share F highlight',view.selected[1]==2)
            shifted(Qt.Key_S)
            check('return preserves confirmed edit',e.toPlainText()=='它'+original[1:])
            select(e,0,1);shifted(Qt.Key_F);unconfirmed=e.toPlainText();shifted(Qt.Key_S)
            check('unconfirmed S does not change text',e.toPlainText()==unconfirmed)
            select(e,0,1);shifted(Qt.Key_F);choice=view.selected
            QApplication.sendEvent(QApplication.focusWidget(),QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.ShiftModifier,'F',True))
            check('repeat ignored',view.selected==choice)
            shifted(Qt.Key_S);select(e,len(e.toPlainText()))
            for key,letter in ((Qt.Key_A,'A'),(Qt.Key_D,'D')):
                before=e.toPlainText();QApplication.sendEvent(e,QKeyEvent(QEvent.KeyPress,key,Qt.ShiftModifier,letter))
                check('uppercase '+letter+' outside candidate',e.toPlainText()==before+letter)
            for key,symbol in ((Qt.Key_1,'!'),(Qt.Key_2,'@'),(Qt.Key_3,'#')):
                before=e.toPlainText();QApplication.sendEvent(e,QKeyEvent(QEvent.KeyPress,key,Qt.ShiftModifier,symbol))
                check('retired key inputs '+symbol,e.toPlainText()==before+symbol)
            select(e,0);QApplication.sendEvent(e,QInputMethodEvent('ni',[]));before=e.toPlainText()
            handled=page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.ShiftModifier,'F'),text_focus=True)
            check('IME reserved F preserves composition',handled and e._preediting and e.toPlainText()==before)
            QApplication.sendEvent(e,QInputMethodEvent('',[]))
            page._cancel_canvas_inline_edit()
            # Reopen bindings and original/translation identity are independent.
            result['phase']='translation reopen';save()
            for _ in range(5):
                page._open_caption_editor('a','translation');page._lock_caption_editor();e=page.subtitle_edit_input;QTest.qWait(80)
                select(e,0,1);before=e.toPlainText();shifted(Qt.Key_F)
                check('translation layer preserved reopen '+str(_),page._caption_draft.target.layer=='translation' and e.toPlainText()=='它'+before[1:])
                page._cancel_canvas_inline_edit();QTest.qWait(80)
            page._open_caption_editor('b','original');page._lock_caption_editor();e=page.subtitle_edit_input;select(e,len(e.toPlainText()))
            before=e.toPlainText();shifted(Qt.Key_E)
            check('E confirms new caption without old target',page._caption_draft is None and page.project.cues[1].text==before)
            page._cancel_canvas_inline_edit()
            # Use the production PipelineWorker and service with explicit,
            # model-free doubles; B waits while A is edited in real Studio.
            result['phase']='queue start';save()
            from ..design import theme_manager
            theme_manager.apply_theme('warm',app);QTest.qWait(200)
            originals=(window.legacy,window.pipeline,pipeline_worker.run_media_queue)
            pipeline_worker.run_media_queue=partial(service.run_media_queue,_skip_environment_preflight=True)
            paths=[]
            for name in 'ABC':
                path=output/(name+'.mp4');shutil.copyfile(output/'fixture.mp4',path);paths.append(str(path))
            class Pipeline(FakePipeline):
                def process_media(self,path,index,total,legacy,runtime_context=None):
                    if index==2:
                        started.set()
                        while not gate.wait(.02):self.token.raise_if_cancelled()
                        raise RuntimeError('B synthetic failure')
                    cues=[SimpleNamespace(cue_id='q'+str(i),start=.3+i*3,end=2.8+i*3,text=t,speaker='S00')
                          for i,t in enumerate(('她和他一起去营地。','留下来校对这一条。','删除这一条字幕。'))]
                    ref=create_studio_outputs(path,cues,txt_path='',target_project_path=runtime_context.studio_project_path,
                        generation_metadata={'job_id':runtime_context.job_id,'media_identity':runtime_context.media_identity})
                    runtime_context.committed_result_ref=json.loads(ref['result_ref_json'])
                    return '','',.02
            window.legacy=FakeLegacy(output);window.legacy.RUNTIME_SETTINGS=copy.deepcopy(originals[0].RUNTIME_SETTINGS)
            window.pipeline=Pipeline();window.media_paths=paths
            window._run_in_progress=True;window._launch_pipeline_worker(service.RunOptions())
            check('recognition starts without creating queue bar',no_queue_bar())
            window.grab().save(str(output/'02a-recognition-start-without-queue-bar.png'))
            worker=window.worker;wait(lambda:len(window._background_ready)==1 and started.is_set())
            check('A delivered while B thread still running',worker.isRunning() and len(window._background_ready)==1)
            check('running batch has no queue bar',no_queue_bar())
            path=next(iter(window._background_ready));open_delivery(path)
            wait(lambda:str(page.project_path)==path and page._readiness.ready)
            wait(lambda:not window._studio_loading_session.active and not page._readiness.overlay.isVisible())
            QTest.qWait(150)
            check('A opens while B C pending',worker is window.worker and worker.isRunning() and page.project.media.path==paths[0])
            window.grab().save(str(output/'02-A-editing-B-background.png'))
            page.show_project_hub()
            wait(lambda:page._project_view_state=='hub')
            check('project library while B running keeps same worker',window.worker is worker and worker.isRunning())
            window.grab().save(str(output/'02b-library-B-background.png'))
            window._switch_page(window.settings_scroll)
            check('home switch keeps queue and ready A',window.worker is worker and worker.isRunning() and len(window._background_ready)==1)
            check('returning home while running has no queue bar',no_queue_bar())
            window.grab().save(str(output/'02c-home-running-without-queue-bar.png'))
            window._switch_page(1)
            check('task progress from home keeps queue',window.worker is worker and worker.isRunning())
            check('progress page while running has no queue bar',no_queue_bar())
            window.grab().save(str(output/'02d-progress-running-without-queue-bar.png'))
            open_delivery(path)
            wait(lambda:str(page.project_path)==path and page._readiness.ready and not window._studio_loading_session.active)
            check('A reopens from task after library and home',window.pages.currentWidget() is page and window.worker is worker)

            page.video.set_paused(True);cue=page.project.cues[0];page._open_caption_editor(cue.id,'original');page._lock_caption_editor();e=page.subtitle_edit_input
            select(e,0,1);shifted(Qt.Key_F);shifted(Qt.Key_E)
            wait(lambda:page._caption_draft is None)
            # Production command paths for time, split and deletion.
            page._split_at(page.project.cues[1].id,4200)
            check('manual split added a cue',len(page.project.cues)==4)
            page.select_cue(page.project.cues[-1].id);page._delete_current()
            check('manual deletion removed cue',len(page.project.cues)==3)
            from ..timeline.studio_commands import SetCueFieldsCommand
            first=page.project.cues[0];before_time=first.start_ms
            page.undo_stack.push(SetCueFieldsCommand(page.project,first.id,{'start_ms':first.start_ms+30},'调整时间',page.cue_controller.model_changed))
            check('manual timeline edit applied',page.project.cues[0].start_ms==before_time+30)
            changed_id=page.project.cues[0].id
            # Timeline edits use the same transaction/undo stack as dragging.
            # Constructor is obtained below from the public command signature.
            from ..timeline.studio_edit_sequence import projected_cues
            expected=[(c.id,c.text,c.start_ms,c.end_ms) for c in projected_cues(page.project)]
            page.save();wait(lambda:not page.project_controller.dirty_guard.is_dirty())
            before=Path(path).read_bytes()
            window._switch_page(1);check('task view keeps worker',worker is window.worker and worker.isRunning())
            window._back_to_studio_from_progress();check('return from task keeps A',str(page.project_path)==path)
            gate.set();wait(lambda:not worker.isRunning() and not window._background_running)
            check('batch completion keeps current editor page',window.pages.currentWidget() is page)
            check('completion has no modal over editor',not (getattr(window,'_completion_dialog',None) and window._completion_dialog.isVisible()))
            check('B failure C success reflected',len(window._background_ready)==2 and len(window._last_queue_results)==3 and window._last_queue_results[1].status=='failed')
            check('mixed failure completion has no queue bar',no_queue_bar())
            check('queue bar never occupies layout space',all(window.content_layout.itemAt(i).widget() is None or window.content_layout.itemAt(i).widget().objectName()!='backgroundRecognitionBar' for i in range(window.content_layout.count())))
            window._switch_page(2)
            check('results remain accessible without queue bar',window.pages.currentIndex()==2 and no_queue_bar())
            window.grab().save(str(output/'03a-results-without-queue-bar.png'))
            window._switch_page(page)
            check('batch finalization did not rewrite A',Path(path).read_bytes()==before)
            reopened=load_project(path)
            check('saved manual text split deletion survive',[(c.id,c.text,c.start_ms,c.end_ms) for c in projected_cues(reopened)]==expected)
            window.grab().save(str(output/'03-batch-ended-A-preserved.png'))
            result['first_queue_exit_code']=window.result_exit_code
            # A separate retry uses B's own task/path; old attempt callbacks
            # must not target A or the new worker.
            old_worker=worker
            window.media_paths=[paths[1]];window.pipeline=Pipeline();window._run_in_progress=True
            window._launch_pipeline_worker(service.RunOptions());retry_worker=window.worker
            window._back_to_studio_from_progress()
            wait(lambda:not retry_worker.isRunning() and not window._background_running)
            check('B retry completed in independent project',len(window._background_ready)==1 and window._last_queue_results[0].media_path==paths[1])
            check('successful completion has no queue bar',no_queue_bar())
            check('B retry keeps edited A and current page',Path(path).read_bytes()==before and str(page.project_path)==path and window.pages.currentWidget() is page)
            class CancelPipeline(Pipeline):
                def process_media(self,path,index,total,legacy,runtime_context=None):
                    while not self.token.is_cancelled:time.sleep(.01)
                    self.token.raise_if_cancelled()
            window.media_paths=paths[1:];window.pipeline=CancelPipeline();window._run_in_progress=True
            window._launch_pipeline_worker(service.RunOptions());cancel_worker=window.worker
            window._back_to_studio_from_progress();window._cancel_run()
            wait(lambda:not cancel_worker.isRunning() and not window._background_running)
            check('cancel is explicit and remaining videos cancelled',len(window._last_queue_results)==2 and all(row.status=='cancelled' for row in window._last_queue_results))
            check('cancelling other videos preserves A',Path(path).read_bytes()==before and str(page.project_path)==path and window.pages.currentWidget() is page)
            check('cancelled batch has no queue bar',no_queue_bar())
            class FailedPipeline(Pipeline):
                def process_media(self,path,index,total,legacy,runtime_context=None):
                    raise RuntimeError('expected all-failed visibility fixture')
            window.media_paths=[paths[1]];window.pipeline=FailedPipeline();window._run_in_progress=True
            window._launch_pipeline_worker(service.RunOptions());failed_worker=window.worker
            window._back_to_studio_from_progress()
            wait(lambda:not failed_worker.isRunning() and not window._background_running)
            check('all failed batch has no queue bar',no_queue_bar() and all(row.status=='failed' for row in window._last_queue_results))
            window._begin_background_queue('terminal-visibility-fixture')
            check('new batch never recreates queue bar',no_queue_bar())
            window._finish_background_queue(error='expected queue-level failure')
            check('queue error has no queue bar',no_queue_bar())
            window._switch_page(window.settings_scroll)
            check('returning home after queue error has no queue bar',no_queue_bar())
            window.grab().save(str(output/'04a-home-ended-without-queue-bar.png'))
            window.grab().save(str(output/'04-error-without-queue-bar.png'))
            window.legacy,window.pipeline,pipeline_worker.run_media_queue=originals
            result['expected_synthetic_exit_codes']=[result['first_queue_exit_code'],window.result_exit_code]
            window.result_exit_code=0  # audit succeeds after the expected synthetic failure/cancellation
            result['passed']=all(result['checks'].values());save();window.close();QTimer.singleShot(200,app.quit)
        except Exception:
            gate.set();result['error']=traceback.format_exc();window.grab().save(str(output/'failure-window.png'));save()
            try:wait(lambda:not getattr(window,'worker',None) or not window.worker.isRunning(),10)
            except Exception:pass
            app.exit(1)
    QTimer.singleShot(150,run)
