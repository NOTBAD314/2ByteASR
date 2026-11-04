"""Reproducible navigation and ownership audit; no paid/provider requests."""
import json,os,sys,time,traceback,threading
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QObject,QEvent,QTimer,QEventLoop,Qt,QCoreApplication
    from PySide6.QtWidgets import QApplication
    from .studio_acceptance_audit import require
    from .blank_project_audit import _capture
    import psutil
    out=Path(output);clock=time.perf_counter
    result=dict(passed=False,operations=[],reads=[],resources=[],checks=[],pid=os.getpid(),
                frozen=bool(getattr(sys,'frozen',False)),executable=sys.executable)
    active={};gaps=[];last=[clock()];proc=psutil.Process();animation=[]
    if os.environ.get('LIBRARY_PAINT_PROFILE')=='1':
        from ..design.bunny_mascot import BunnyMascot
        from ..studio.loading_faces import CoverPane,RecentFan,ReadinessSteps
        from ..studio.studio_loading import StudioLoadingView
        result['paint_costs']={}
        for cls,method in [(BunnyMascot,'paintEvent'),(CoverPane,'paintEvent'),(RecentFan,'paintEvent'),
                (ReadinessSteps,'paintEvent'),(StudioLoadingView,'paintEvent'),(StudioLoadingView,'fit_card')]:
            original=getattr(cls,method);key=cls.__name__+'.'+method
            def measured(self,*a,_original=original,_key=key,**kw):
                began=clock()
                try:return _original(self,*a,**kw)
                finally:
                    row=result['paint_costs'].setdefault(_key,dict(count=0,ms=0,max_ms=0))
                    elapsed=(clock()-began)*1000;row['count']+=1;row['ms']+=elapsed;row['max_ms']=max(row['max_ms'],elapsed)
            setattr(cls,method,measured)

    try:
        from ..projects.project_read_cache import stats as cache_stats
        from ..system.memory_budget import memory_status
    except ImportError:
        cache_stats=lambda:dict(reads=0,inflight=0,baseline_cache_unavailable=True)
        memory_status=lambda:dict(available=psutil.virtual_memory().available,total=psutil.virtual_memory().total)
    original_read=Path.read_text
    def read(path,*args,**kwargs):
        if path.suffix!='.2byteproj':return original_read(path,*args,**kwargs)
        began=clock()
        try:return original_read(path,*args,**kwargs)
        finally:result['reads'].append(dict(path=str(path),size=path.stat().st_size if path.exists() else None,
            thread=threading.current_thread().name,ms=(clock()-began)*1000))
    Path.read_text=read
    def receipt():
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)));receipt();require(value,name)
    def wait(predicate,seconds=180):
        if predicate():return
        loop=QEventLoop();poll=QTimer();poll.setInterval(10);limit=QTimer();limit.setSingleShot(True)
        def failed():
            session=getattr(window,'_studio_loading_session',None)
            return session is not None and session.state=='failed'
        poll.timeout.connect(lambda:loop.quit() if predicate() or failed() else None);limit.timeout.connect(loop.quit)
        poll.start();limit.start(round(seconds*1000))
        try:loop.exec()
        finally:poll.stop();limit.stop()
        require(predicate(),'wait timed out or loading reported failure')
    def pause(ms):
        loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()
    class Probe(QObject):
        def eventFilter(self,obj,event):
            if active and event.type()==QEvent.Type.Paint:
                if type(obj).__name__=='BunnyMascot' and obj.isVisible():animation.append(clock())
                active.setdefault('feedback_ms',(clock()-active['start'])*1000)
                name=obj.objectName()
                if name in ('studioLoadingSurface','studioLoadingCard'):
                    active.setdefault('loading_paint_ms',(clock()-active['start'])*1000)
            return False
    probe=Probe(window);QApplication.instance().installEventFilter(probe)
    pulse=QTimer(window);pulse.setTimerType(Qt.TimerType.PreciseTimer);pulse.setInterval(16)
    def beat():
        now=clock();gaps.append((now-last[0])*1000);last[0]=now
    pulse.timeout.connect(beat);pulse.start()
    def resources(name):
        result['cache']=cache_stats()
        result['system_memory']=memory_status()
        children=[]
        for child in proc.children(recursive=True):
            try:children.append(dict(pid=child.pid,rss=child.memory_info().rss,name=child.name()))
            except psutil.Error:pass
        mem=psutil.virtual_memory();swap=psutil.swap_memory()
        result['resources'].append(dict(name=name,rss=proc.memory_info().rss,
            private=getattr(proc.memory_info(),'private',None),peak=getattr(proc.memory_info(),'peak_wset',None),
            threads=proc.num_threads(),handles=proc.num_handles(),qobjects=len(window.findChildren(QObject)),
            available=mem.available,total=mem.total,swap_used=swap.used,children=children));receipt()
    def measure(name,action,ready):
        active.clear();active.update(name=name,start=clock());gaps.clear();animation.clear();last[0]=clock();read_start=len(result['reads']);cache_before=cache_stats()
        action();active['handler_ms']=(clock()-active['start'])*1000
        wait(ready)
        active['ready_ms']=(clock()-active['start'])*1000;pause(45)
        # A nested audit event loop must explicitly deliver the deletes that
        # an ordinary return to the outer application loop would process.
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        pause(16)
        row={k:v for k,v in active.items() if k!='start'}
        ordered=sorted(gaps);row.update(max_gap_ms=max(gaps,default=0),p95_gap_ms=ordered[int(.95*(len(ordered)-1))] if ordered else 0,
            file_reads=len(result['reads'])-read_start,complete_json_reads=cache_stats()['reads']-cache_before['reads'])
        frames=sorted((b-a)*1000 for a,b in zip(animation,animation[1:]))
        row.update(animation_frames=len(animation),animation_max_ms=max(frames,default=0),
                   animation_p95_ms=frames[int(.95*(len(frames)-1))] if frames else None)
        result['operations'].append(row);active.clear();receipt();return row
    def execute():
        try:
            window.resize(1600,950);window.show()
            def hub_ready():
                p=window.built_page('studio')
                return p is not None and p.studio_empty.isVisible() and bool(getattr(p,'_hub_card_widgets',()))
            measure('library_cold_first_screen',lambda:window.open_studio_project(mode='hub'),hub_ready)
            page=window.built_page('studio');wait(lambda:not getattr(page,'_hub_scan_pending',False),300)
            pause(500);resources('library_cold');_capture(window,out/'library.png')
            target=out/'library/stress-4484.2byteproj'
            def opened():return page.project is not None and str(page.project_path)==str(target) and page._readiness.ready
            measure('project_cold',lambda:window.open_studio_project(str(target)),opened)
            result['readiness_cold']=dict(page._readiness.profile);result['prepared_open_ms']=getattr(page.project,'_prepared_open_ms',None);resources('project_cold');_capture(window,out/'workspace.png')
            check('large_project',len(page.project.cues)==4484 and len(page.project.speakers)==15)
            for index in range(int(os.environ.get('LIBRARY_PERF_CYCLES','3'))):
                measure(f'return_{index}',lambda:page.show_project_hub(skip_dirty_guard=True),hub_ready)
                measure(f'reopen_{index}',lambda:window.open_studio_project(str(target)),opened)
                if index%5==0:resources(f'cycle_{index}')
            resources('final')
            if os.environ.get('LIBRARY_PERF_FUNCTIONAL')=='1':
                from ..timeline.studio_commands import BatchReplaceTextCommand
                from ..projects.studio_project import load_project
                from dataclasses import asdict
                project=page.project
                source_texts={cue.id:cue.text for cue in project.cues}
                speakers_before=[asdict(item) for item in project.speakers]
                styles_before=[asdict(item) for item in project.styles]
                translations_before=json.dumps(project.generation_metadata.get('translations',{}),sort_keys=True,ensure_ascii=False)
                target_cue=project.cues[10]
                # Run the actual local bilingual review service on its owned
                # snapshot while the live command/autosave path changes text.
                import subtitle_core as legacy
                from ..glossary.terminology import snapshot_glossaries
                from ..glossary.glossary_proofread import _ReviewThread,_review_copy
                from ..studio.subtitle_text_targets import text_entries,review_project
                entries=text_entries(project,mode='both')
                view=review_project(_review_copy(project),entries)
                review_results=[];review_errors=[];review_finished=[]
                review=_ReviewThread(view,[entry.key for entry in entries],snapshot_glossaries(legacy,['洛克王国世界']),{},False,page)
                review.ready.connect(lambda value:review_results.append(len(value.hits) if hasattr(value,'hits') else 1))
                review.failed.connect(review_errors.append);review.finished.connect(lambda:review_finished.append(True))
                review.start()
                check('real_bilingual_preview_running',review.isRunning() and any(entry.target.layer=='translation' for entry in entries))
                measure('one_edit',lambda:page.undo_stack.push(BatchReplaceTextCommand(project,
                    {target_cue.id:source_texts[target_cue.id]+' edit'})),lambda:target_cue.text.endswith(' edit'))
                wait(lambda:page._autosave_deadline.due(time.monotonic()) or page._autosave_worker_running,10)
                page._autosave()
                check('autosave_started',page._autosave_worker_running)
                edits={cue.id:source_texts[cue.id]+' batch' for cue in project.cues[20:70]}
                measure('batch_50_during_autosave',lambda:page.undo_stack.push(BatchReplaceTextCommand(project,edits)),
                    lambda:all(cue.text==edits[cue.id] for cue in project.cues if cue.id in edits))
                measure('undo_50',page.undo_stack.undo,lambda:all(cue.text==source_texts[cue.id] for cue in project.cues if cue.id in edits))
                measure('redo_50',page.undo_stack.redo,lambda:all(cue.text==edits[cue.id] for cue in project.cues if cue.id in edits))
                from ..subtitle_rules.subtitle_translation import snapshot as translation_snapshot
                translation_entries=[entry for entry in text_entries(project,mode='translation') if entry.target.storage!='cue'][:10]
                translation_before=translation_snapshot(project)
                if translation_entries:
                    changes={entry.target.cue_id:(entry.text+' translated edit',entry.target.language) for entry in translation_entries}
                    measure('translation_batch_10',lambda:page.undo_stack.push(BatchReplaceTextCommand(project,{},translation_values=changes)),lambda:True)
                    translation_after=translation_snapshot(project)
                    check('translation_batch_changed',translation_after!=translation_before)
                    page.undo_stack.undo();check('translation_batch_undo',translation_snapshot(project)==translation_before)
                    page.undo_stack.redo();check('translation_batch_redo',translation_snapshot(project)==translation_after)
                    page.undo_stack.undo()
                check('review_snapshot_not_mutated',next(cue.text for cue in view.cues if cue.id==target_cue.id)==source_texts[target_cue.id])
                wait(lambda:bool(review_finished),180)
                check('real_preview_finished',bool(review_results) and not review_errors)
                review.deleteLater()
                wait(lambda:not page._autosave_worker_running,180)
                measure('save',page.save,lambda:page.undo_stack.isClean())
                check('translations_preserved',json.dumps(project.generation_metadata.get('translations',{}),sort_keys=True,ensure_ascii=False)==translations_before)
                check('speaker_style_preserved',speakers_before==[asdict(item) for item in project.speakers] and styles_before==[asdict(item) for item in project.styles])
                expected={cue.id:cue.text for cue in project.cues}
                measure('return_after_save',lambda:page.show_project_hub(skip_dirty_guard=True),hub_ready)
                measure('reopen_saved',lambda:window.open_studio_project(str(target)),opened)
                check('saved_text_roundtrip',expected=={cue.id:cue.text for cue in page.project.cues})
                # A fresh pathname forces a real in-flight reader; cancellation
                # must not bind its eventual result over the selected project.
                import shutil
                other=out/'library/cancel-large.2byteproj';shutil.copy2(target,other)
                window.open_studio_project(str(other));pause(40)
                window._cancel_studio_construction();pause(40)
                window.open_studio_project(str(target));wait(opened)
                pause(1500)
                check('cancel_and_new_request_owns_page',str(page.project_path)==str(target) and page._readiness.ready)
                small=min((p for p in (out/'library').rglob('*.2byteproj') if 'autosave' not in p.parts and 'backup' not in p.parts and p!=target),key=lambda p:p.stat().st_size)
                window.open_studio_project(str(small));pause(15);window.open_studio_project(str(target));wait(opened)
                wait(lambda:cache_stats()['inflight']==0,180)
                check('rapid_switch_late_result_rejected',str(page.project_path)==str(target))
                measure('library_state_setup',lambda:page.show_project_hub(skip_dirty_guard=True),hub_ready)
                page.project_search.setText('stress');pause(100)
                page._library_selected_paths={str(target)}
                mode=page.project_sort.findData('name')
                if mode>=0:page.project_sort.setCurrentIndex(mode)
                window.open_studio_project(str(target));wait(opened)
                page.show_project_hub(skip_dirty_guard=True);wait(hub_ready)
                check('library_filter_selection_restored',page.project_search.text()=='stress' and str(target) in page._library_selected_paths and page.project_sort.currentData()=='name')
                window.open_studio_project(str(target));wait(opened)
                page._seek((page.project.cues[10].start_ms+100)/1000)
                pause(500)
                _capture(window,out/'bilingual-edited.png')
                position=page.video.visual_position()
                measure('actual_play_advance',lambda:page.video.set_paused(False),lambda:page.video.visual_position()>position+.4)
                page.video.set_paused(True)
                resources('functional_final')
            result['passed']=True
        except BaseException:result['error']=traceback.format_exc()
        finally:
            pulse.stop();QApplication.instance().removeEventFilter(probe);Path.read_text=original_read;receipt()
            def stopped():result['gui_shutdown']=True;receipt()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.result_exit_code=0 if result['passed'] else 1
            page=window.built_page('studio')
            if not result['passed'] and page is not None:
                page.undo_stack.setClean()  # only this failed isolated fixture, never a user document
                page._recovered_autosave_pending=False
            window.close()
    QTimer.singleShot(50,execute)
