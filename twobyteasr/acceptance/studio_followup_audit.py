"""In-process evidence: real project, actual list paint, local match, navigation and export."""
import copy,json,os,sys,time,traceback
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QEvent,QObject,QPoint,Qt,QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .studio_acceptance_audit import require
    from .blank_project_audit import _capture
    from . import blank_project_audit as guards
    out=Path(output);clock=time.perf_counter
    baseline=bool(os.environ.get('STUDIO_FOLLOWUP_BASELINE_SOURCE'))
    try:page=window.studio_page
    except RuntimeError:
        QTimer.singleShot(100,lambda:start(window,out));return
    result=dict(checks=[],timings=[],phases=[],resources=[],passed=False,baseline=baseline,pid=os.getpid(),
        executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)))
    def receipt(): (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(name,passed,detail=None):
        result['checks'].append(dict(name=name,passed=bool(passed),detail=detail));receipt()
        if not baseline:require(passed,name)
    def wait(predicate,seconds=90):
        end=clock()+seconds
        while not predicate() and clock()<end:
            QApplication.processEvents()
            time.sleep(.01)  # release the GIL for real Python/QThread work
        require(predicate(),'wait timed out')
    intervals=[];last=[clock()]
    heartbeat=QTimer(window)
    def beat():
        now=clock();intervals.append((now-last[0])*1000);last[0]=now
    heartbeat.timeout.connect(beat);heartbeat.start(16)
    def resources(name):
        import threading
        row=dict(name=name,at=clock(),python_threads=len(threading.enumerate()),
            qobjects=len(window.findChildren(QObject)))
        try:
            import psutil
            proc=psutil.Process();row.update(rss=proc.memory_info().rss,os_threads=proc.num_threads(),
                handles=proc.num_handles(),children=[p.pid for p in proc.children(recursive=True) if p.is_running()])
        except Exception as exc:row['resource_error']=type(exc).__name__
        result['resources'].append(row);receipt()
    class PaintProbe(QObject):
        def __init__(self):super().__init__(window);self.started=None;self.first=None
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Paint and self.started is not None and self.first is None:
                self.first=(clock()-self.started)*1000
            return False
    probe=PaintProbe()
    def shot(name):QTest.qWait(100);_capture(window,out/(name+'.png'))
    def wrap(owner,name):
        original=getattr(owner,name)
        def measured(*args,**kwargs):
            start=clock()
            try:
                if os.environ.get('STUDIO_FOLLOWUP_PROFILE') and name=='_write' and not getattr(owner,'_profiled_write',False):
                    import cProfile,pstats
                    owner._profiled_write=True;profile=cProfile.Profile()
                    value=profile.runcall(original,*args,**kwargs)
                    with (out/'profile-write.txt').open('w',encoding='utf-8') as stream:
                        pstats.Stats(profile,stream=stream).sort_stats('cumtime').print_stats(65)
                    return value
                return original(*args,**kwargs)
            finally:result['phases'].append(dict(name=name,ms=(clock()-start)*1000,at=start))
        setattr(owner,name,measured)
    def measured_edit(proof,cue_id,text,name):
        proof.list.ensure_visible(cue_id);proof._edit(cue_id)
        proof.list.editor.setText(text)
        QTest.qWait(40);probe.started=clock();probe.first=None
        before=len(intervals);QTest.keyClick(proof.list.editor,Qt.Key.Key_Return)
        returned=(clock()-probe.started)*1000
        wait(lambda:probe.first is not None,10)
        paint=probe.first;live=proof._by_id[cue_id]['base']
        QTest.qWait(1)
        interactive=(clock()-probe.started)*1000
        wait(lambda:not proof.checks_running(),180)
        row=dict(name=name,command_ms=returned,first_paint_ms=paint,interactive_ms=interactive,
            local_quiet_ms=(clock()-probe.started)*1000,max_gui_interval_ms=max(intervals[before:] or [0]),
            text_correct=live==text,visible=proof.list.slot_of(cue_id)>=0)
        result['timings'].append(row);probe.started=None;receipt()
        check(name+'_text',live==text)
        return row
    def functional():
        p=page.project
        translations_before=copy.deepcopy(p.generation_metadata.get('translations',{}))
        from ..recognition.service import MediaResult
        # Same live completion-task binding as a completed recognition run,
        # without performing or fabricating a new ASR/provider request.
        window._completion_tasks=[(MediaResult(media_path=p.media.path,status='success',project_path=str(page.project_path),project_id=p.project_id),p)]
        window._completion_task_evidence={}
        selector=window.result_task_selector
        selector.blockSignals(True);selector.clear();selector.addItem('Copied problem project');selector.setCurrentIndex(0);selector.blockSignals(False)
        completion_refreshes=[];refresh=window._refresh_completion_preview
        def count_completion_refresh():
            completion_refreshes.append(window.result_preview.isVisible())
            return refresh()
        window._refresh_completion_preview=count_completion_refresh
        target=p.cues[len(p.cues)//2]
        page.select_cue(target.id);page.timeline.setFocus()
        QTest.keyClick(page.timeline,Qt.Key.Key_R);QTest.qWait(150)
        check('R_explicit_middle',page._review_mode and page.selected_cue_id==target.id,dict(expected=target.id,actual=page.selected_cue_id))
        if page._review_mode:page._set_review_mode(False)
        page.timeline.explicit_subtitle_id='';page.timeline.set_playhead(target.start_ms+20)
        page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key.Key_R);QTest.qWait(150)
        check('R_playhead_middle',page.selected_cue_id==target.id,dict(expected=target.id,actual=page.selected_cue_id))
        if page._review_mode:page._set_review_mode(False)
        window._open_studio_glossary_proofread()
        proof=window.glossary_proofread_page
        wait(lambda:not proof.checks_running(),240)
        from ..glossary.term_editing import library_terms
        result['project']['current_terms']=len(library_terms(proof._snapshot)) if proof._snapshot else 0
        result['project']['initial_local_suggestions']=proof.proposal_counts()
        proof.list.installEventFilter(probe)
        for name in ('_write','_sync_from_project','_apply_filter','_read_snapshot','_run','_show_result','_persist_soon','_save_now'):
            wrap(proof,name)
        proof.filter_buttons['all'].click();proof._apply_filter()
        text=proof._by_id[target.id]['base']
        for i in range(2 if os.environ.get('STUDIO_FOLLOWUP_PROFILE') else 8):
            measured_edit(proof,target.id,text+('！' if i%2==0 else ''),'manual_'+str(i))
        bursts=[];final=text
        for i in range(20):
            final=text+' 连续'+str(i)
            proof._edit(target.id);proof.list.editor.setText(final)
            started=clock();QTest.keyClick(proof.list.editor,Qt.Key.Key_Return)
            bursts.append((clock()-started)*1000)
            QApplication.processEvents();time.sleep(.005)
        wait(lambda:not proof.checks_running(),180)
        check('burst_last_edit_preserved',proof._by_id[target.id]['base']==final and next(c.text for c in p.cues if c.id==target.id)==final)
        result['burst_command_ms']=bursts
        check('hidden_completion_not_rebuilt',not completion_refreshes,completion_refreshes)
        # Controlled proposals in one real row exercise deterministic offsets;
        # the preceding whole-project local match and all 565+ rows remain.
        from ..glossary.glossary_proofread import _issue
        proof._edit_committed(target.id,'古龙和火龙古龙')
        wait(lambda:not proof.checks_running(),180)
        row=proof._by_id[target.id]
        row['issues']=[_issue('term',(0,2),'古龙','大骨龙',checked=False),
                       _issue('near',(3,5),'火龙','火笼',checked=False)]
        proof.filter_buttons['suggested'].click();proof._apply_filter()
        proof.list.current=target.id;proof.list.ensure_visible(target.id);QTest.qWait(80)
        slot=proof.list.slot_of(target.id);offset=proof.list.bar.value()
        box=next((rect for rect,action,identity,index in proof.list._hit_boxes
                  if action=='check' and identity==target.id and index==0),None)
        require(box is not None,'visible first suggestion check box')
        QTest.mouseClick(proof.list,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,box.center().toPoint())
        QTest.mouseMove(proof.list,QPoint(proof.list.width()-5,5))
        proof.list.setFocus();QTest.keyClick(proof.list,Qt.Key.Key_R,Qt.KeyboardModifier.ShiftModifier);QTest.qWait(80)
        check('adopt_two_offsets',row['base']=='大骨龙和火笼古龙',row['base'])
        check('adopted_row_retained',proof.list.slot_of(target.id)==slot)
        check('focus_stable',proof.list.current==target.id)
        before=row['base'];proof._toggle_issue(target.id,0)
        check('repeat_adopt_idempotent',row['base']==before)
        proof.replace_everywhere('古龙','古龙王')
        check('batch_replace_retains_review_row',proof.list.slot_of(target.id)>=0 and row['base']=='大骨龙和火笼古龙王')
        proof._undo();row=proof._by_id[target.id]
        check('undo_batch_replace_keeps_adoption',row['base']==before and proof.list.slot_of(target.id)>=0)
        shot('adopted-retained')
        proof._dismiss_group(target.id,-1)
        check('dismiss_retained_row',proof.list.slot_of(target.id)<0 and row['base']==before)
        proof._undo();check('undo_dismiss_retains_edit',proof.list.slot_of(target.id)>=0 and row['base']==before)
        proof._redo();check('redo_dismiss',proof.list.slot_of(target.id)<0)
        proof.filter_buttons['all'].click();proof._apply_filter()
        check('dismissed_in_all',proof.list.slot_of(target.id)>=0)
        resources('proofread_complete');shot('proofread-all')
        proof.back_button.click();QTest.qWait(200)
        check('return_canonical_document',page.project is p)
        window._open_studio_glossary_proofread();again=window.glossary_proofread_page
        again.filter_buttons['suggested'].click();again._apply_filter()
        check('return_to_proofread_keeps_dismissal',again.list.slot_of(target.id)<0 and again._by_id[target.id]['base']==before)
        again.back_button.click();QTest.qWait(150)
        window._switch_page(window.pages.widget(2));QApplication.processEvents()
        check('completion_rebuilt_once_when_shown',len(completion_refreshes)==1,completion_refreshes)
        window._switch_page(page);QApplication.processEvents()
        from ..projects.studio_project import load_project
        import shutil
        path=out/'edited.2byteproj';t=clock();page.save()
        result['save_ms']=(clock()-t)*1000
        check('normal_save_clean',page.undo_stack.isClean())
        shutil.copy2(page.project_path,path)
        restored=load_project(path)
        check('saved_text_reopens',next(c.text for c in restored.cues if c.id==target.id)==before)
        check('all_translation_texts_preserved',p.generation_metadata.get('translations',{})==translations_before
              and restored.generation_metadata.get('translations',{})==translations_before)
        if not baseline:
            from ..glossary.proofread_retention import REVIEW_KEY
            saved=restored.studio_state[REVIEW_KEY]['rows'][target.id]
            check('saved_review_state',saved['dismissed'] and not saved['retained'] and saved['origin']!=before)
        if not baseline:
            shown={c.id:c.text for c in page._revision_store.render.timeline_cues}
            check('return_publishes_latest_text',shown.get(target.id)==before)
    def stability():
        original=page.project;path=page.project_path
        for i in range(10):
            window._return_to_settings();QTest.qWait(100)
            window.open_studio_project(path)
            wait(lambda:page.project is not None and page._readiness.ready,120)
            QTest.qWait(200);resources('navigation_'+str(i))
            check('navigation_'+str(i),page.project.project_id==original.project_id)
        # Preview construction/teardown is separate from an encoder run.
        for i in range(10):
            page._open_render_dialog();QTest.qWait(100)
            check('export_preview_'+str(i),page.export_workspace is not None)
            page._close_export_workspace();QTest.qWait(100)
        resources('export_preview_cycles');shot('after-export-preview')
    def export():
        import subprocess,psutil
        from dataclasses import replace,asdict
        from ..studio.studio_video_track import ffmpeg_executable
        from ..projects.project_range import set_range
        from ..timeline.studio_edit_sequence import timeline_duration_ms
        ffmpeg=Path(ffmpeg_executable());ffprobe=ffmpeg.with_name('ffprobe.exe')
        p=page.project;cue=p.cues[len(p.cues)//2]
        result['exports']=[]
        for label in ('success','cancel','failure'):
            page.select_cue(cue.id);page._seek(cue.start_ms/1000)
            set_range(p,cue.start_ms,min(timeline_duration_ms(p),cue.start_ms+(60000 if label=='cancel' else 3000)),page.undo_stack)
            page._open_render_dialog();ui=page.export_workspace
            require(ui is not None,'export workspace missing')
            ui.directory.setText(str(out));ui.filename.setText('real-project-'+label)
            ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
            encoder=ui.encoder.findData('libx264')
            if encoder>=0:ui.encoder.setCurrentIndex(encoder)
            ui.resolution.setCurrentIndex(0)
            if label=='failure':
                original_job=ui._job
                def faulty(output,settings=None):
                    job=original_job(output,settings=settings)
                    job.settings=replace(job.settings,profile='2byte-controlled-invalid-profile')
                    return job
                ui._job=faulty
            cancel_progress=[]
            if label=='cancel':
                from ..exports.studio_export_ui import STAGE_ENCODE
                def cancel_during_encoding(percent,data):
                    if str(data.get('stage',''))==STAGE_ENCODE and (percent>0 or any(k in data for k in ('out_time','out_time_ms','out_time_us'))):
                        if not cancel_progress:
                            cancel_progress.append(dict(percent=percent,stage=data.get('stage'),keys=list(data)))
                            QTimer.singleShot(0,ui._cancel_export)
                ui.progress_updated.connect(cancel_during_encoding)
            ui._target_changed();QApplication.processEvents()
            started=clock();QTest.mouseClick(ui.export_button,Qt.MouseButton.LeftButton)
            encoder_pids=[]
            if label=='cancel':
                wait(lambda:bool(cancel_progress) or not ui._running,120)
                check('cancel_encoding_progress_observed',bool(cancel_progress),cancel_progress)
            wait(lambda:not ui._running,180)
            target=Path(ui.export_target().full_path)
            record=dict(label=label,elapsed_s=clock()-started,failure=ui._last_failure,output=str(target),
                encoder_pids=encoder_pids,success=ui.pages.currentWidget() is ui.success_page,
                cancel_progress=cancel_progress,
                settings=asdict(ui._last_job.settings) if getattr(ui,'_last_job',None) else None)
            result['exports'].append(record);receipt()
            expected=ui.success_page if label=='success' else ui.setup_page if label=='cancel' else ui.failure_page
            check('export_'+label+'_terminal',ui.pages.currentWidget() is expected,record)
            if label=='success':
                probe=subprocess.run([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(target)],
                    capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
                record['probe']=json.loads(probe.stdout) if probe.returncode==0 else dict(error=probe.stderr)
                decoded=subprocess.run([str(ffmpeg),'-v','error','-i',str(target),'-f','null','-'],
                    capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
                record['decode_exit']=decoded.returncode;record['decode_error']=decoded.stderr
                duration=float(record['probe'].get('format',{}).get('duration',0))
                check('actual_file_decodes',target.is_file() and decoded.returncode==0)
                check('actual_duration',abs(duration-3.0)<.35,duration)
                subprocess.run([str(ffmpeg),'-v','error','-y','-ss','1','-i',str(target),'-frames:v','1',str(out/'export-frame.png')],
                    capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
            shot('export-'+label)
            ui._back();QApplication.processEvents();time.sleep(.1);QApplication.processEvents()
            check('export_'+label+'_player_returned',page.video.parentWidget() is page.video_overlay_host and bool(page.video.controller and page.video.controller.running))
            page._seek((cue.start_ms+500)/1000)
            wait(lambda:abs(page.timeline.playhead_ms-(cue.start_ms+500))<100,15)
            check('export_'+label+'_seek_works',abs(page.timeline.playhead_ms-(cue.start_ms+500))<100)
            check('export_'+label+'_project_unchanged',page.project is p)
            resources('export_'+label+'_returned')

    def idle():
        seconds=int(os.environ.get('STUDIO_FOLLOWUP_IDLE_SECONDS','600'))
        result['idle']=dict(seconds_per_page=seconds//2,segments=[])
        for label in ('studio','proofread'):
            if label=='proofread':
                window._open_studio_glossary_proofread();proof=window.glossary_proofread_page
                wait(lambda:not proof.checks_running(),240)
            segment=dict(page=label,started=time.time());result['idle']['segments'].append(segment)
            resources('idle_'+label+'_start');end=clock()+seconds/2;sample=clock()+30
            while clock()<end:
                QApplication.processEvents();time.sleep(.02)
                if clock()>=sample:resources('idle_'+label+'_sample');sample=clock()+30
            segment['finished']=time.time();resources('idle_'+label+'_end');shot('idle-'+label+'-end')
    def execute():
        try:
            wait(lambda:page.project is not None and page._readiness.ready,180)
            window.resize(1600,950);window.show();QApplication.setActiveWindow(window)
            page.video.set_paused(True)
            result['project']=dict(id=page.project.project_id,cues=len(page.project.cues),
                translations=len(page.project.generation_metadata.get('translations',{})))
            from ..diagnostics.build_identity import load_build_identity
            try:result['build']=load_build_identity().to_dict()
            except Exception:pass
            modules=('twobyteasr.glossary.glossary_proofread','twobyteasr.projects.studio_revisions',
                     'twobyteasr.studio.studio_ui','twobyteasr.studio.studio_review_ui')
            import importlib
            for name in modules:importlib.import_module(name)
            result['module_paths']={name:str(getattr(sys.modules.get(name),'__file__','')) for name in modules}
            if result['frozen']:
                import hashlib
                result['exe_sha256']=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
                check('loaded_from_bundle',all(Path(p).resolve().is_relative_to(Path(sys.executable).resolve().parent)
                                               for p in result['module_paths'].values()))
            wait(lambda:hasattr(page.project,'_qc_result'),120)
            resources('ready')
            {'functional':functional,'stability':stability,'idle':idle,'export':export}[os.environ.get('STUDIO_FOLLOWUP_PHASE','functional')]()
            check('no_AI_requests',guards._provider_calls==0,guards._provider_calls)
            result['passed']=all(c['passed'] for c in result['checks'])
        except BaseException:
            result['error']=traceback.format_exc();result['passed']=False
        finally:
            # The normal dirty guard must not strand a successful audit in a
            # save question on its private desktop. Save through production UI.
            try:
                proof=getattr(window,'glossary_proofread_page',None)
                if proof is not None:proof.list.commit_pending_edit()
                if page.project is not None and not page.undo_stack.isClean():page.save()
                result['close_saved']=page.undo_stack.isClean()
            except Exception:result['close_save_error']=traceback.format_exc()
            receipt()
            def closed():result['gui_shutdown']=True;receipt()
            QApplication.instance().aboutToQuit.connect(closed)
            QTimer.singleShot(0,window.close)
    QTimer.singleShot(0,execute)
