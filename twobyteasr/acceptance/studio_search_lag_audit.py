"""Report regression in a normal MainWindow, using an isolated project copy."""
import hashlib
import json
import os
import time
import traceback


def start(window,output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance()
    result={'passed':False,'checks':{},'operations':[],'scope':'normal source MainWindow, private desktop, project copy; synthetic Qt input'}
    dialogs=[]
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,condition):
        result['checks'][name]=bool(condition);save()
        if not condition:raise AssertionError(name)
    def wait(predicate,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return True
            time.sleep(.002)
        raise TimeoutError('normal UI wait')
    def quiet(d):
        return not d._search_timer.isActive() and not getattr(d,'_search_pending',False)
    def save_project_and_wait(page):
        page.project_controller.save()
        wait(lambda:not getattr(getattr(page,'_persistence_queue',None),'busy',False))
    def timed(name,fn,d=None):
        ticks=[];last=[time.perf_counter()]
        def tick():
            now=time.perf_counter();ticks.append((now-last[0])*1000);last[0]=now
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(tick);timer.start()
        started=time.perf_counter();value=fn();handler=(time.perf_counter()-started)*1000
        if d is not None:wait(lambda:quiet(d))
        app.processEvents();ticks.append((time.perf_counter()-last[0])*1000);timer.stop()
        row=dict(name=name,handler_ms=handler,total_ms=(time.perf_counter()-started)*1000,max_gui_gap_ms=max(ticks))
        if d is not None:row.update(hits=len(d._preview_hits),work=getattr(d,'_last_search_metrics',{}))
        result['operations'].append(row);save();return value
    def run():
        page=window.studio_page
        try:
            from ..studio.studio_find_replace import FindReplaceDialog
            from ..subtitle_rules import subtitle_translation as st
            from ..projects.studio_project import load_project
            window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['TWOBYTEASR_STARTUP_PROJECT'],single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
            wait(lambda:page.project is not None and page._project_view_state=='open')
            wait(lambda:getattr(page,'_readiness',None) is not None and page._readiness.ready)
            result['startup_ready']=True
            page.video.set_paused(True)
            result['counts']=dict(cues=len(page.project.cues),translations=len(st.records_of(page.project)),speakers=len(page.project.speakers))
            check('long project opened through normal controller',len(page.project.cues)>=5555)
            d=timed('open',lambda:FindReplaceDialog(page,page));dialogs.append(d)
            # The production menu uses QDialog.exec(), which is modal. Match
            # that policy while the audit drives its nested event loop.
            d.setModal(True);d.show();wait(lambda:quiet(d))
            for mode in ('original','translation','both'):
                d.text_targets.mode.setCurrentIndex(d.text_targets.mode.findData(mode))
                d.text_targets.track.setCurrentIndex(0)
                d.find_edit.setText('诊断替换标记');d.replace_edit.setText('诊断替换完成')
                timed(mode+'-cold',d._do_preview,d)
                timed(mode+'-warm',d._do_preview,d)
                check(mode+' correct marker count',len(d._preview_hits)==(0 if mode=='original' else 2))
            for value in ('诊','诊断','诊断替换','诊断替换标记'):
                timed('input',lambda value=value:d.find_edit.setText(value))
            wait(lambda:quiet(d));check('latest rapid query wins',d._preview_query[0]=='诊断替换标记' and len(d._preview_hits)==2)
            d.grab().save(str(output/'search-results.png'))
            target=d._preview_hits[0].target
            timed('navigate',lambda:d._preview_item_clicked(d.preview.item(0)))
            check('actual target navigation',page.session.selected_cue_id==target.cue_id and page.timeline.active_subtitle_layer=='translation')
            d.scope_combo.setCurrentIndex(d.scope_combo.findData('selected'))
            timed('selected-scope',d._do_preview,d)
            check('selected translation scope',len(d._preview_hits)==1)
            d.scope_combo.setCurrentIndex(d.scope_combo.findData('all'));d._do_preview();wait(lambda:quiet(d))
            index=page.undo_stack.index()
            if os.environ.get('STUDIO_SEARCH_PROFILE'):
                import cProfile
                profiler=cProfile.Profile();profiler.enable()
                timed('replace-2',lambda:QTest.mouseClick(d.all_button,Qt.LeftButton),d)
                profiler.disable();profiler.dump_stats(str(output/'replace-profile.pstats'))
            else:timed('replace-2',lambda:QTest.mouseClick(d.all_button,Qt.LeftButton),d)
            check('one undo for two translations',page.undo_stack.index()==index+1)
            check('two records changed',sum('诊断替换完成' in str(r.get('text','')) for r in st.records_of(page.project).values())==2)
            timed('undo',page.undo_stack.undo,d)
            check('undo restores two markers',sum('诊断替换标记' in str(r.get('text','')) for r in st.records_of(page.project).values())==2)
            timed('redo',page.undo_stack.redo,d)
            check('redo restores two changes',sum('诊断替换完成' in str(r.get('text','')) for r in st.records_of(page.project).values())==2)
            d.find_edit.setText('诊断替换完成');wait(lambda:quiet(d))
            d.grab().save(str(output/'replaced-results.png'))
            timed('close-search',d.reject)
            check('search cancellation on close',not getattr(d,'_search_pending',False) and not (getattr(d,'_slice_timer',None) and d._slice_timer.isActive()))
            page.session.project_path=output/'saved.2byteproj'
            if os.environ.get('STUDIO_SEARCH_PROFILE'):
                import cProfile
                profiler=cProfile.Profile();profiler.enable()
                timed('save-first',lambda:save_project_and_wait(page))
                profiler.disable();profiler.dump_stats(str(output/'save-profile.pstats'))
            else:timed('save-first',lambda:save_project_and_wait(page))
            check('formal save succeeded',page.session.project_path.is_file() and page.undo_stack.isClean())
            timed('save-repeat',lambda:save_project_and_wait(page))
            loaded=load_project(page.session.project_path)
            check('save reopen keeps translations',sum('诊断替换完成' in str(r.get('text','')) for r in st.records_of(loaded).values())==2)
            window.grab().save(str(output/'studio-saved.png'))
            import twobyteasr.projects.studio_project as persistence
            before=hashlib.sha256(page.session.project_path.read_bytes()).hexdigest()
            original=persistence._atomic_json_blob_write;errors=[]
            page.cue_controller.set_text(page.project.cues[0].id,page.project.cues[0].text+' 失败验收')
            def failed(*args,**kwargs):raise OSError('owned simulated write failure')
            persistence._atomic_json_blob_write=failed
            try:
                page.project_controller.save(message_box_fn=lambda *args:errors.append(args))
                wait(lambda:not page._persistence_queue.busy)
            finally:persistence._atomic_json_blob_write=original
            check('failed save preserves durable bytes',bool(errors) and hashlib.sha256(page.session.project_path.read_bytes()).hexdigest()==before)
            page.undo_stack.setClean();page.project_dirty=False
            result['passed']=all(result['checks'].values())
        except Exception:result['error']=traceback.format_exc()
        finally:
            for d in dialogs:d.reject()
            save()
            page.undo_stack.setClean();page.project_dirty=False
            window.close()
            result['close_requested']=bool(page._close_requested)
            save()
    app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),save()))
    QTimer.singleShot(1200,run)
