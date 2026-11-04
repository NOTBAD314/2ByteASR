"""Actual MainWindow lifecycle probes using copied projects only."""
import json,os,sys,time,traceback
from pathlib import Path

def start(window,output):
    from PySide6.QtCore import QTimer,QEventLoop
    from PySide6.QtWidgets import QApplication
    from ..studio.studio_ui import SubtitleStudioPage
    from .blank_project_audit import _capture
    out=Path(output);clock=time.perf_counter
    result=dict(passed=False,events=[],samples=[],errors=[],checks=[],pid=os.getpid(),
        frozen=bool(getattr(sys,'frozen',False)),executable=sys.executable,
        source=__import__('twobyteasr.studio.studio_ui',fromlist=['x']).__file__)
    original=SubtitleStudioPage._enqueue_library_cover
    def enqueue(self,*args,**kw):
        try:return original(self,*args,**kw)
        except Exception:
            result['errors'].append(''.join(traceback.format_stack())+traceback.format_exc());save();raise
    SubtitleStudioPage._enqueue_library_cover=enqueue
    original_finish=SubtitleStudioPage._finish_workspace_initialization
    scenario=os.environ.get('LIBRARY_LIFECYCLE_SCENARIO','baseline')
    if scenario == 'retry':
        fail_once=[True]
        def finish(self):
            if fail_once[0]:
                fail_once[0]=False
                raise RuntimeError('controlled initialization failure')
            return original_finish(self)
        SubtitleStudioPage._finish_workspace_initialization=finish
    if scenario == 'native-resize':
        from PySide6.QtCore import QCoreApplication,QSize
        from PySide6.QtGui import QResizeEvent
        def finish(self):
            QCoreApplication.sendEvent(self.project_library_scroll.viewport(),QResizeEvent(QSize(1000,600),QSize(900,600)))
            return original_finish(self)
        SubtitleStudioPage._finish_workspace_initialization=finish
    def save(): (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def pause(ms):
        loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()
    def wait(predicate,seconds=30):
        if predicate():return True
        loop=QEventLoop();timer=QTimer();timer.setInterval(20);limit=QTimer();limit.setSingleShot(True)
        timer.timeout.connect(lambda:loop.quit() if predicate() else None);limit.timeout.connect(loop.quit)
        timer.start();limit.start(int(seconds*1000));loop.exec();timer.stop();limit.stop()
        return predicate()
    def check(name,value):
        result['checks'].append(dict(name=name,passed=bool(value)));save()
        if not value:raise AssertionError(name)
    def sample():
        s=window.__dict__.get('_studio_loading_session');p=window.__dict__.get('_studio_page_building')
        result['samples'].append(dict(at=clock(),state=getattr(s,'state',None),generation=getattr(s,'generation',None),
            label=s.view.label.text() if s else '',queued=window.__dict__.get('_studio_entry_start_queued'),
            building=bool(p),discarding=window.__dict__.get('_studio_entry_discarding'),
            build_timer=p._workspace_build_timer.isActive() if p else None,
            cover=s.native_cover_state() if s else None));save()
    pulse=QTimer(window);pulse.setInterval(250);pulse.timeout.connect(sample);pulse.start()
    def execute():
        try:
            window.open_studio_project(None,mode='hub')
            wait(lambda:window._studio_loading_session.state in {'failed','ready'},30)
            s=window._studio_loading_session;result['first']=s.snapshot();sample();_capture(window,out/'first.png')
            if s.state=='failed':
                wait(lambda:not window.__dict__.get('_studio_entry_discarding'),10)
                s.view.retry.click();pause(12000);result['retry']=s.snapshot();sample();_capture(window,out/'retry.png')
            page=window.built_page('studio')
            if page is not None:
                result['library']=dict(index=len(getattr(page,'_hub_library_records',[]) or []),
                    filtered=len(getattr(page,'_hub_display_records',[]) or []),cards=len(page._hub_card_widgets),
                    signature=repr(getattr(page,'_hub_render_signature',None))[:100],
                    labels=hasattr(page,'_library_cover_labels'),visible=page.studio_empty.isVisible())
            if scenario == 'full':
                check('first_ready',s.state=='ready')
                check('scan_completed',wait(lambda:not page._hub_scan_pending,60))
                pause(250)
                initial={row['path'] for row in page._hub_library_records}
                result['library_before']=sorted(initial)
                check('indexed_library_visible',len(initial)>0 and bool(page._hub_card_widgets))
                # Scroll until every record has an actual Qt card.
                def all_cards():return len(page._hub_card_widgets)==len(page._hub_display_records)
                for _ in range(30):
                    if all_cards():break
                    bar=page.project_library_scroll.verticalScrollBar();bar.setValue(bar.maximum());page._library_scrolled();pause(100)
                check('all_records_bound',all_cards())
                result['full_counts']=dict(index=len(initial),filtered=len(page._hub_display_records),submitted=len(page._hub_display_records),cards=len(page._hub_card_widgets))
                page.project_library_scroll.verticalScrollBar().setValue(0)
                _capture(window,out/'library-complete.png')
                target=Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
                import hashlib
                before=hashlib.sha256(target.read_bytes()).hexdigest()
                def opened():return page.project is not None and str(page.project_path)==str(target) and page._readiness.ready
                # Real background project read, deliberately held for 10 s.
                from ..projects import studio_project as project_module
                load=project_module.load_project;delayed=[True]
                def slow_load(path,*a,**kw):
                    if delayed[0] and str(path)==str(target):
                        delayed[0]=False;time.sleep(10)
                    return load(path,*a,**kw)
                project_module.load_project=slow_load
                began=clock();start_sample=len(result['samples'])
                window.open_studio_project(str(target));pause(7000)
                check('delay_still_loading',s.active)
                texts=[x['label'] for x in result['samples'][start_sample:] if x['state']=='preparing']
                check('elapsed_updates_without_progress',len(set(texts))>=15)
                _capture(window,out/'delay-7s.png')
                check('delayed_read_recovered',wait(opened,45));project_module.load_project=load
                result['delayed_open_ms']=(clock()-began)*1000
                check('original_cue_count',len(page.project.cues)==128)
                _capture(window,out/'studio.png')
                result['cycles']=[]
                for cycle in range(10):
                    began=clock();page.show_project_hub(skip_dirty_guard=True)
                    check(f'return_{cycle}',wait(lambda:page.studio_empty.isVisible() and bool(page._hub_card_widgets)))
                    return_ms=(clock()-began)*1000
                    page.project_search.setText('Getting Started');pause(100)
                    check(f'filter_{cycle}',len(page._hub_display_records)==1)
                    page.project_list_view_button.click();pause(100)
                    check(f'list_{cycle}',len(page._hub_row_widgets)==1 and page.all_projects_stack.currentIndex()==1)
                    page.project_card_view_button.click();page.project_search.clear();pause(100)
                    check(f'cards_{cycle}',bool(page._hub_card_widgets))
                    check(f'hero_{cycle}','128' in page.resume_meta.text())
                    began=clock();window.open_studio_project(str(target));check(f'open_{cycle}',wait(opened,45))
                    result['cycles'].append(dict(cycle=cycle,return_ms=return_ms,open_ms=(clock()-began)*1000));save()
                page.show_project_hub(skip_dirty_guard=True);pause(200)
                _capture(window,out/'returned-ten-times.png')
                # A cancelled background read completes after a newer navigation.
                from ..projects import project_read_cache
                project_read_cache.clear()
                second=out/'library/cancel-copy.2byteproj'
                import shutil
                shutil.copy2(target,second)
                def cancelled_load(path,*a,**kw):
                    if str(path)==str(second):time.sleep(3)
                    return load(path,*a,**kw)
                project_module.load_project=cancelled_load
                window.open_studio_project(str(second));pause(200);cancelled_epoch=s.generation
                s.view.back.click();window.open_studio_project(None,mode='hub');pause(4000)
                project_module.load_project=load
                check('cancel_reenter_generation',s.generation>cancelled_epoch and s.state=='ready')
                check('cancel_late_read_ignored',page.project is None and page.studio_empty.isVisible() and bool(page._hub_card_widgets))
                second.unlink()
                # UI states are exercised through real asynchronous scans with
                # isolated data providers, avoiding mutation of the input library.
                scan=page._project_library_records
                def scan_as(fn):
                    check('old_scan_settled',wait(lambda:not page._hub_scan_pending,60))
                    page._project_library_records=fn;page._hub_scan_started=-10
                    page._request_library_scan();check('scenario_scan_settled',wait(lambda:not page._hub_scan_pending,30));pause(150)
                def broken():raise OSError('controlled unreadable library')
                scan_as(broken)
                check('read_failure_keeps_cards',bool(page._hub_card_widgets) and page.hub_loading_label.isVisible() and not page.project_library_empty.isVisible())
                _capture(window,out/'read-failure.png')
                scan_as(lambda:[])
                check('true_empty',page.project_library_empty.isVisible() and '还没有工程' in page.project_library_empty.text())
                _capture(window,out/'empty.png')
                scan_as(scan)
                page.project_search.setText('NO_SUCH_PROJECT_9ec342');pause(150)
                check('no_search_results',page.project_library_empty.isVisible() and '匹配' in page.project_library_empty.text())
                _capture(window,out/'no-results.png');page.project_search.clear();pause(150)
                # A malformed project and unavailable source/cover remain local
                # entries; none can hide the healthy 128-cue project.
                bad=out/'library/broken.2byteproj';bad.write_text('{invalid','utf-8')
                scan_as(scan)
                check('malformed_project_partial_warning',bool(page._library_read_warnings) and bool(page._hub_card_widgets))
                check('healthy_project_survives_bad_neighbor',str(target) in {r['path'] for r in page._hub_library_records})
                _capture(window,out/'partial-failure.png');bad.unlink()
                scan_as(scan)
                records=[dict(r) for r in page._hub_library_records]
                records[0]['cover_path']=str(out/'missing-cover.png')
                records[0]['source_media']=str(out/'missing-media.mp4')
                page._hub_library_records=records;page._rebuild_project_library();page._start_library_presence(records);pause(400)
                check('missing_cover_media_keeps_cards',bool(page._hub_card_widgets))
                check('missing_media_explicit',page._project_status(records[0])[1]=='offline')
                _capture(window,out/'missing-media.png')
                scan_as(scan)
                check('library_count_preserved',initial=={r['path'] for r in page._hub_library_records})
                check('project_copy_unchanged',before==hashlib.sha256(target.read_bytes()).hexdigest())
                result['library_after']=sorted(r['path'] for r in page._hub_library_records)
                result['passed']=True
            result['passed']=True if scenario=='baseline' else s.state=='ready'
        except BaseException:result['error']=traceback.format_exc()
        finally:
            pulse.stop();save();SubtitleStudioPage._enqueue_library_cover=original
            SubtitleStudioPage._finish_workspace_initialization=original_finish
            QApplication.instance().aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),save()))
            window.result_exit_code=0 if result['passed'] else 1;window.close()
    QTimer.singleShot(50,execute)
