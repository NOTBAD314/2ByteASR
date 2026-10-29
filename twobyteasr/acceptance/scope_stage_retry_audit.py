"""Actual Qt input, prepared/published glyph pixels and native composed frames."""
import copy,hashlib,json,os,time,traceback,sys,importlib
from pathlib import Path
from dataclasses import asdict

def start(window,out):
    from PySide6.QtCore import QObject,QTimer,Qt,QPoint,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QScrollArea
    from ..projects.studio_project import save_project,load_project
    from ..timeline.selection_scope import SelectionScope
    from ..caption_style.caption_layer_transform import resolved_values
    from .controls_timeline_audit import distribution
    from .blank_project_audit import _capture
    app=QApplication.instance();out=Path(out)
    class Audit(QObject):
        @staticmethod
        def interactive(page):
            gate=getattr(page,'_readiness',None)
            return bool(page and page.project and page.video._startup_state=='READY' and gate and gate.ready
                        and not gate.active and not gate.loading.active and page.isVisible())
        def __init__(self):
            super().__init__(window);self.result={'passed':False,'pid':os.getpid(),'checks':{},'cases':{},'tier':'private desktop Qt input / real glyph raster publish, native composed frame; not physical scan latency'}
            from ..diagnostics.build_identity import load_build_identity
            frozen=bool(getattr(sys,'frozen',False));actual_sha=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
            names=('twobyteasr.studio.presentation_scope','twobyteasr.caption_style.scoped_transform',
                   'twobyteasr.app.stage_retry','twobyteasr.recognition.processing_recovery')
            modules={name:str(getattr(importlib.import_module(name),'__file__','')) for name in names}
            self.result.update(frozen=frozen,executable=sys.executable,gui_sha256=actual_sha,
                build_identity=load_build_identity().to_dict(),module_origins=modules)
            if os.environ.get('SCOPE_AUDIT_EXPECT_FROZEN')=='1':
                self.check('expected_frozen_identity',frozen and actual_sha==os.environ.get('SCOPE_AUDIT_EXPECT_GUI_SHA256'))
                package=str(Path(getattr(sys,'_MEIPASS','')).resolve()).lower()+os.sep
                self.check('packaged_scope_modules',all(str(Path(value).resolve()).lower().startswith(package) for value in modules.values()),modules)
            self.steps=self.run();self.pending=0;self.last=time.perf_counter();self.beats=[];self.phase=''
            self.inputs={};self.latencies=[];self.hashes=[];self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(4)
        def tick(self):
            now=time.perf_counter();self.beats.append((now-self.last)*1000);self.last=now
            if hasattr(self,'page'):
                scene=getattr(self.page,'_caption_scene',None);token=getattr(scene,'last_result_token',None)
                if scene is not None and token is not None and getattr(scene,'published',None) is not None:
                    key=token[5]
                    for serial,stamp in list(self.inputs.items()):
                        if key.startswith('('+str(serial)+','):
                            image=scene.published.image
                            digest=hashlib.sha256(bytes(image.constBits())).hexdigest()
                            self.latencies.append((now-stamp)*1000);self.hashes.append(digest);del self.inputs[serial]
            if now<self.pending:return
            try:self.pending=now+next(self.steps)
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
        def check(self,key,value,detail=None):
            self.result['checks'][key]={'passed':bool(value),'detail':detail}
        def shot(self,name):
            _capture(window,out/(name+'.png'))
        def values(self):return {c.id:resolved_values(self.page.project,c,'original') for c in self.page.project.cues}
        def input_number(self,control,value):
            parent=control.parentWidget()
            while parent and not isinstance(parent,QScrollArea):parent=parent.parentWidget()
            if parent:parent.ensureWidgetVisible(control,0,30)
            editor=control.lineEdit();QTest.mouseClick(editor,Qt.LeftButton);QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(editor,str(value));QTest.keyClick(editor,Qt.Key_Tab)
        def run(self):
            yield .8
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT']);deadline=time.perf_counter()+55
            while time.perf_counter()<deadline:
                page=window.built_page('studio')
                if page and self.interactive(page):break
                yield .1
            self.page=page;self.check('normal_entry_ready',self.interactive(page))
            if not self.interactive(page):return
            window.showMaximized();page.volume_slider.setValue(0);page.video.set_paused(True);page._sync_play_button(True)
            self.result['window']={'size':[window.width(),window.height()],'dpr':window.devicePixelRatioF(),'viewport':[page.video.width(),page.video.height()]}
            if os.environ.get('SCOPE_AUDIT_RETRY_ONLY')=='1':
                yield from self.retry();return
            large=int(os.environ.get('SCOPE_AUDIT_LARGE',0))
            if large:
                original=copy.deepcopy(page.project);source=copy.deepcopy(original.cues);count=len(source);span=max(c.end_ms for c in source)+500
                original.cues=[]
                original.render_settings['_cue_domain']='timeline'
                original.studio_state.pop('caption_timeline',None)
                for i in range(large):
                    cue=copy.deepcopy(source[i%count]);cue.id='large-'+str(i);delta=(i//count)*span
                    cue.start_ms+=delta;cue.end_ms+=delta;original.cues.append(cue)
                old_project=page.project
                destination=save_project(original,out/'large.2byteproj');page.undo_stack.setClean();page.open_project(destination)
                deadline=time.perf_counter()+50
                while time.perf_counter()<deadline and (page.project is old_project or page.project_path!=destination or not self.interactive(page)):yield .1
                self.check('large_interactive',page.project is not old_project and self.interactive(page))
                if not self.interactive(page):return
            p=page.project;self.original=copy.deepcopy(p);page.context_drawer.setCurrentIndex(1);yield .4
            first=p.cues[0];page.select_cue(first.id);page._seek((first.start_ms+min(400,(first.end_ms-first.start_ms)//2))/1000);yield .8
            deadline=time.perf_counter()+8
            while page.position_overlay._subtitle_rect().isEmpty() and time.perf_counter()<deadline:
                page.ensure_active_subtitle_renderer(reason='audit-ready-glyph');yield .1
            for label in os.environ.get('SCOPE_AUDIT_CASES','21,speaker,all').split(','):
                chosen=p.cues[:21] if label=='21' else [c for c in p.cues if c.speaker_id==first.speaker_id] if label=='speaker' else p.cues
                page.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in chosen],first.id))
                page.style_scope.setCurrentIndex(page.style_scope.findData('selected'));page.style_layer.setCurrentIndex(page.style_layer.findData('original'))
                panel=page.caption_transform_panel;panel.refresh();yield .4
                before=self.values();count=page.undo_stack.count();self.latencies=[];self.hashes=[];self.inputs={};self.beats=[];self.last=time.perf_counter()
                profiler=None
                if os.environ.get('SCOPE_AUDIT_PROFILE')=='1':
                    import cProfile
                    profiler=cProfile.Profile();profiler.enable()
                    import sys
                    callers={};update=page.timeline.update
                    def track_update(*args):
                        frame=sys._getframe(1);key=f'{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}'
                        callers[key]=callers.get(key,0)+1;return update(*args)
                    page.timeline.update=track_update
                overlay=page.position_overlay;box=overlay._subtitle_rect();self.check(label+'_visible_drag_box',not box.isEmpty(),box.getRect())
                point=box.center().toPoint();QTest.mousePress(overlay,Qt.LeftButton,Qt.AltModifier,point)
                for i in range(1,31):
                    stamp=time.perf_counter();at=point+QPoint(i*2,-i)
                    app.sendEvent(overlay,QMouseEvent(QEvent.MouseMove,QPointF(at),QPointF(overlay.mapToGlobal(at)),Qt.NoButton,Qt.LeftButton,Qt.AltModifier))
                    serial=getattr(page,'_caption_transform_preview_serial',0);self.inputs[serial]=stamp
                    yield .016
                stamp=time.perf_counter();QTest.mouseRelease(overlay,Qt.LeftButton,Qt.AltModifier,point+QPoint(60,-30));commit=(time.perf_counter()-stamp)*1000
                yield .35
                if profiler:
                    import pstats,io
                    profiler.disable();stream=io.StringIO();pstats.Stats(profiler,stream=stream).sort_stats('cumtime').print_stats(55)
                    (out/(label+'-profile.txt')).write_text(stream.getvalue(),'utf8')
                    page.timeline.update=update;self.result.setdefault('timeline_update_callers',{})[label]=callers
                after=self.values();changed={k for k in before if after[k]!=before[k]};wanted={c.id for c in chosen}
                self.check(label+'_exact_targets',changed==wanted,{'changed':len(changed),'expected':len(wanted)})
                self.check(label+'_one_undo',page.undo_stack.count()==count+1)
                self.check(label+'_selection_retained',len(page.selected_cue_ids())==len(chosen),len(page.selected_cue_ids()))
                self.result['cases'][label]={'targets':len(chosen),'release_commit_ms':commit,'input_to_published_glyph_ms':distribution(self.latencies),
                    'published_unique_images':len(set(self.hashes)),'input_events':30,'gui_beat_ms':distribution(self.beats),
                    'long_stalls_100ms':sum(t>100 for t in self.beats)}
                self.shot(label+'-after-drag');native=out/(label+'-native.png');page.video.controller.screenshot_to_file(native);yield .25
                self.check(label+'_native_frame',native.exists() and native.stat().st_size>1000)
                page.undo_stack.undo();yield .1;self.check(label+'_undo',self.values()==before)
                page.undo_stack.redo();yield .1;self.check(label+'_redo',self.values()==after)
            # Actual number typing follows top all, with one edit transaction.
            page.style_scope.setCurrentIndex(page.style_scope.findData('all'));page.caption_transform_panel.refresh()
            count=page.undo_stack.count()
            self.input_number(page.caption_transform_panel.controls['position_x'],30);yield .3
            self.check('numeric_all',all(abs(v['position_x']-576)<.1 for v in self.values().values()))
            self.check('numeric_one_undo',page.undo_stack.count()==count+1)
            expected=self.values();destination=save_project(p,out/'roundtrip.2byteproj');reopened=load_project(destination)
            self.check('saved_geometry',all(resolved_values(reopened,c,'original')==expected[c.id] for c in reopened.cues))
            for c in (p.cues[0],p.cues[min(20,len(p.cues)-1)],p.cues[min(60,len(p.cues)-1)]):
                page.select_cue(c.id);page._seek((c.start_ms+min(300,(c.end_ms-c.start_ms)//2))/1000);yield .5
                prepared=page._prepared_caption(c.id)
                self.check('different_time_'+c.id,prepared is not None and abs(prepared.snapshot.position_x-576)<.1)
            if not large:
                page.select_cue(first.id);page._seek((first.start_ms+min(400,(first.end_ms-first.start_ms)//2))/1000);yield .6
                page.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in p.cues[:21]],first.id))
                page.style_scope.setCurrentIndex(page.style_scope.findData('selected'));page.caption_transform_panel.refresh();yield .2
                before=self.values();count=page.undo_stack.count();overlay=page.position_overlay
                handle=overlay._handle_centers(overlay._subtitle_rect())['br'].toPoint()
                QTest.mousePress(overlay,Qt.LeftButton,Qt.AltModifier,handle)
                at=handle+QPoint(15,15)
                app.sendEvent(overlay,QMouseEvent(QEvent.MouseMove,QPointF(at),QPointF(overlay.mapToGlobal(at)),Qt.NoButton,Qt.LeftButton,Qt.AltModifier))
                QTest.mouseRelease(overlay,Qt.LeftButton,Qt.AltModifier,at);yield .3
                after=self.values();changed={k for k in before if before[k]!=after[k]}
                self.check('resize_actual_21',changed=={c.id for c in p.cues[:21]},len(changed))
                self.check('resize_one_undo',page.undo_stack.count()==count+1)
                page.undo_stack.undo();yield .2
                page.select_cue(first.id);page.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in p.cues[:21]],first.id))
                page.style_scope.setCurrentIndex(page.style_scope.findData('selected'));page.style_apply_geometry.setChecked(True)
                before=copy.deepcopy({c.id:(c.style_id,c.appearance_override,c.transform) for c in p.cues})
                preset_index=1 if page.style_preset.currentIndex()!=1 else 2
                page.style_preset.setCurrentIndex(preset_index);page._preset_activated(preset_index);yield .5
                changed={c.id for c in p.cues if (c.style_id,c.appearance_override,c.transform)!=before[c.id]}
                self.check('preset_actual_21',changed=={c.id for c in p.cues[:21]},len(changed))
                self.shot('preset-21');page.undo_stack.undo();yield .2
            if os.environ.get('SCOPE_AUDIT_SKIP_RETRY')!='1':yield from self.retry()
        def retry(self):
            from ..app import stage_retry_ui,stage_retry
            from ..recognition.processing_recovery import failure_summary
            from ..recognition.service import RunOptions,MediaResult,QueueResult
            # Local deterministic response exercises real polisher parsing and
            # worker/save/UI plumbing. No second paid request is made here.
            import twobyteasr.providers.ai_providers as providers
            from types import SimpleNamespace
            original_provider=providers.provider_for_stage
            os.environ['DEEPSEEK_API_KEY']='isolated-fixture-key'
            def complete(messages,**kwargs):
                payload=json.loads(messages[1]['content']);ids=[r['id'] for r in payload['cues']]
                return json.dumps({'checked_ids':ids,'cues':[]})
            providers.provider_for_stage=lambda *a,**k:SimpleNamespace(complete=complete)
            report=json.loads((out/'report.json').read_text('utf-8-sig'));page=self.page
            report['result']=dict(report.get('result') or {})
            from ..recognition.processing_recovery import recover_units
            units=recover_units(page.project,report);self.check('real_failure_restored',len(units)==1 and units[0]['original_ids']==[69] and len(units[0]['cue_ids'])==6)
            seen=[]
            deadline=time.perf_counter()+35
            def inspect():
                dialog=getattr(page,'_stage_retry_dialog',None)
                if dialog is None:
                    if time.perf_counter()<deadline:QTimer.singleShot(20,inspect)
                    return
                worker=getattr(dialog,'_glossary_review_worker',None)
                if worker is not None:QTimer.singleShot(20,inspect);return
                dialog.grab().save(str(out/'retry-task-completed.png'));seen.append(dialog._retry_tasks.topLevelItem(0).text(1))
                dialog.accept()
            QTimer.singleShot(20,inspect)
            try:
                save_project(page.project,page.project_path);page.undo_stack.setClean()
                item=MediaResult(page.project.media.path,'success',project_path=str(page.project_path),report_json_path=str(out/'report.json'))
                window._handle_result(QueueResult((item,),1.))
                window._last_run_options=RunOptions(settings_snapshot_json=json.dumps(report['settings']))
                yield .3
                notice=getattr(window,'_completion_dialog',None)
                if notice is not None:notice.accept()
                yield .2
                self.shot('completion-before-retry')
                self.check('completion_retry_button_visible',window.retry_failed_button.isVisible() and window.retry_failed_button.isEnabled(),
                    {'text':window.retry_failed_button.text(),'visible':window.retry_failed_button.isVisible(),'enabled':window.retry_failed_button.isEnabled()})
                QTest.mouseClick(window.retry_failed_button,Qt.LeftButton)
                while time.perf_counter()<deadline and not seen:yield .1
                evidence=window._completion_task_evidence[window._completion_task_key(item)]
                receipts=evidence.get('retry_receipts') or []
                receipt=receipts[-1] if receipts else None
                self.check('retry_worker_saved',bool(receipt and receipt.get('saved')),receipt)
                self.check('retry_no_empty_failure_list',seen==['完成，无需修改'],seen)
                self.check('retry_disk_resolved',failure_summary(load_project(page.project_path),report)['failed_tasks']==0)
                self.check('completion_failure_summary_refreshed',(evidence.get('stage_recovery') or {}).get('failed_tasks')==0,evidence.get('stage_recovery'))
            finally:providers.provider_for_stage=original_provider
            yield .2
        def finish(self):
            self.timer.stop();self.result['passed']=bool(self.result['checks']) and all(v['passed'] for v in self.result['checks'].values()) and 'error' not in self.result
            receipt=out/'result.json';receipt.write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            def closed():
                self.result['gui_shutdown']=True;receipt.write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            app.aboutToQuit.connect(closed)
            page=window.built_page('studio')
            if page:page.undo_stack.setClean()
            window.close()
    window._scope_stage_retry_audit=Audit()
