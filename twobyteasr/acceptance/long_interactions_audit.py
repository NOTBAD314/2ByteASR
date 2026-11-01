"""Bounded opt-in long-media GUI timings, separate from profiling runs."""
from collections import deque
from pathlib import Path
import json, os, sys, time, traceback

def start(window, output):
    from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from .blank_project_audit import _capture

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            import psutil
            self.proc=psutil.Process();self.page=None;self.pending=None
            self.r=dict(pid=os.getpid(),identity=load_build_identity().to_dict(),
                executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)),
                samples=[],resources=[],checks={},error='',profile=bool(int(os.environ.get('LONG_AUDIT_PROFILE','0'))))
            self.deadline=time.perf_counter()+240;self.last=time.perf_counter();self.gaps=deque(maxlen=6000)
            self.started=self.last;self.wait_until=0;self.sequence=self.run();self.busy=False;self.phase='initial'
            self.profile=None;self.stack_file=None
            if self.r['profile']:
                import threading
                self.stack_samples=deque(maxlen=1000);self.sample_stop=threading.Event()
                main_id=threading.get_ident()
                def sample():
                    while not self.sample_stop.wait(.025):
                        frame=sys._current_frames().get(main_id);rows=[]
                        while frame is not None and len(rows)<16:
                            rows.append((frame.f_code.co_filename,frame.f_code.co_name,frame.f_lineno));frame=frame.f_back
                        self.stack_samples.append((time.perf_counter(),rows))
                threading.Thread(target=sample,name='bounded-main-sampler',daemon=True).start()
            self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(8)
            self.resource_busy=False
            self.resource_timer=QTimer(self);self.resource_timer.timeout.connect(self.request_resources);self.resource_timer.start(5000)
            import gc,threading
            self.gc_start={};self.gc_samples=deque(maxlen=200)
            def gc_observer(phase,info):
                key=threading.get_ident()
                if phase=='start':self.gc_start[key]=time.perf_counter()
                elif key in self.gc_start:self.gc_samples.append(dict(thread=key,generation=info['generation'],ms=(time.perf_counter()-self.gc_start.pop(key))*1000))
            self.gc_observer=gc_observer;gc.callbacks.append(gc_observer)
            QApplication.instance().aboutToQuit.connect(self.shutdown)

        def save(self):
            temporary=output/'result.pending.json'
            temporary.write_text(json.dumps(self.r,ensure_ascii=False,indent=2,default=str),'utf8')
            temporary.replace(output/'result.json')

        def resources(self):
            procs=[self.proc]+self.proc.children(recursive=True)
            rows=[]
            for p in procs:
                try:
                    m=p.memory_info();cpu=p.cpu_times();io=p.io_counters()
                    rows.append(dict(pid=p.pid,name=p.name(),rss=m.rss,private=getattr(m,'private',None),cpu_s=cpu.user+cpu.system,read=io.read_bytes,write=io.write_bytes,threads=p.num_threads()))
                except Exception:pass
            self.r['resources'].append(dict(at=time.perf_counter()-self.started,processes=rows))
            self.r['resources']=self.r['resources'][-300:]

        def request_resources(self):
            if os.environ.get('LONG_AUDIT_EXTERNAL_RESOURCES')=='1':return
            if self.resource_busy:return
            import threading
            self.resource_busy=True
            def work():
                try:self.resources()
                finally:self.resource_busy=False
            threading.Thread(target=work,name='long-audit-resources',daemon=True).start()

        def tick(self):
            now=time.perf_counter();self.gaps.append((now,(now-self.last)*1000));self.last=now
            if self.busy:return
            if now<self.wait_until:return
            if self.pending is not None:
                if self.pending.get('paint_ms') is None and now-self.pending['at']<2:return
                self.r['samples'].append(self.pending);self.pending=None;self.save()
            try:
                self.busy=True
                self.wait_until=time.perf_counter()+next(self.sequence)
            except StopIteration:self.finish()
            except BaseException:
                self.r['error']=traceback.format_exc();self.finish()
            finally:self.busy=False

        def eventFilter(self,obj,event):
            if self.pending is not None and event.type()==QEvent.Type.Paint and self.pending.get('paint_ms') is None:
                sample=self.pending
                if sample['name'] in ('warm-input','warm-open-editor') and obj is not self.page.subtitle_edit_input.viewport():
                    return False
                # Queued marker runs after this real Qt paint. It includes any
                # work already queued before that marker; no physical scan claim.
                QTimer.singleShot(0,lambda:self.painted(sample))
            return False

        def painted(self,sample):
            if sample.get('paint_ms') is None:sample['paint_ms']=(time.perf_counter()-sample['at'])*1000

        def action(self,name,fn,**detail):
            sample=dict(name=name,at=time.perf_counter(),phase=self.phase,**detail)
            profile=None
            if self.r['profile']:
                import cProfile
                profile=cProfile.Profile();profile.enable()
            self.pending=sample
            answer=fn()
            sample['handler_ms']=(time.perf_counter()-sample['at'])*1000
            if profile:
                import pstats,io
                profile.disable();s=io.StringIO();pstats.Stats(profile,stream=s).sort_stats('cumtime').print_stats(65)
                (output/(str(len(self.r['samples']))+'-'+name+'-profile.txt')).write_text(s.getvalue(),'utf8')
            # Selection/input might cause only the table/editor to repaint.
            return answer

        def check(self,name,value):
            self.r['checks'][name]=bool(value)
            if not value:raise AssertionError(name)

        def run(self):
            while window.built_page('studio') is None or window.studio_page.project is None or not window.studio_page._readiness.ready:
                built=window.built_page('studio')
                if built is not None and getattr(built._readiness,'failure_reason',''):
                    raise RuntimeError(built._readiness.failure_reason)
                if time.perf_counter()>self.deadline:raise TimeoutError('Long project did not become ready')
                yield .1
            p=self.page=window.studio_page;project=p.project
            p.video.set_paused(True);p.volume_slider.setValue(0)
            for widget in (p.timeline,p.cue_table.viewport(),p.subtitle_edit_card):widget.installEventFilter(self)
            self.r['project']=dict(cues=len(project.cues),translations=len(project.generation_metadata.get('translations',{})),
                duration_ms=project.media.duration_ms,media=project.media.path,speakers=len(project.speakers),
                video_tracks=len(project.video_tracks),audio_tracks=len(project.audio_tracks),
                dpr=window.devicePixelRatioF(),size=[window.width(),window.height()])
            self.request_resources();yield 3
            if os.environ.get('LONG_AUDIT_PREPARATION_OFF')=='1':
                p._waveform_cancel_event.set();p._waveform_generation+=1;p._waveform_pending_media=[]
                p.timeline._thumbnails.close()
                deadline=time.perf_counter()+5
                while any(th.is_alive() for th in p._waveform_threads) and time.perf_counter()<deadline:yield .1
                self.r['preparation_control']=dict(wave_threads_alive=sum(th.is_alive() for th in p._waveform_threads),
                    thumbnail_closed=p.timeline._thumbnails.closed)
            t=p.timeline;t.set_visible_window(0,60000);yield .4
            # Use distinct real corpus text and stable IDs; fixed viewport for
            # the screen-off object count control.
            cues=project.cues[:12]
            for i,cue in enumerate(cues):
                self.action('select',lambda c=cue:p.select_cue(c.id),cue_id=cue.id)
                yield .18
            for cue in cues[:6]:
                self.action('open-editor',lambda c=cue:p._open_caption_editor(c.id,'original'),cue_id=cue.id)
                yield .18
                self.check('editor_bound_'+cue.id,p._caption_draft is not None)
                self.action('input',lambda:QTest.keyClicks(p.subtitle_edit_input,' test'))
                yield .15
                p._cancel_canvas_inline_edit();yield .1
            cue=cues[2];old=cue.text
            for i in range(3):
                self.action('text-edit',lambda i=i:p.cue_controller.set_text(cue.id,old+' '+str(i)))
                yield .3
                self.action('undo',p.undo_stack.undo);yield .2
                self.check('undo_original_'+str(i),cue.text==old)
                self.action('redo',p.undo_stack.redo);yield .2
                p.undo_stack.undo();yield .2
            for i in range(16):
                self.action('scroll',lambda i=i:t.set_visible_window(60000+i*1500,60000));yield .05
            for i in range(12):
                self.action('zoom',lambda i=i:t.set_visible_window(0,60000+(i%3)*30000));yield .05
            from ..timeline.selection_scope import SelectionScope
            self.action('select-all',lambda:p.cue_controller.apply_selection_scope(SelectionScope.all(len(project.cues),cue.id)))
            yield .3
            p.select_cue(cue.id);yield .2
            self.action('save',p.save);yield .4
            reloaded=load_project(p.project_path)
            self.check('saved_original',next(c for c in reloaded.cues if c.id==cue.id).text==old)
            self.r['media_targets']=[]
            for target in (1000,int(project.media.duration_ms/2),max(0,project.media.duration_ms-8000)):
                self.action('seek',lambda target=target:p._seek(target/1000),target_ms=target)
                yield 2
                self.r['media_targets'].append(dict(target=target,observed=p.video.controller.observed_position()))
            _capture(window,output/'long-window.png')
            until=time.perf_counter()+int(os.environ.get('LONG_AUDIT_SECONDS','0'))
            cycle=0
            self.phase='steady'
            if int(os.environ.get('LONG_AUDIT_SECONDS','0')):
                import hashlib,marshal
                def appearance_hash():
                    return hashlib.sha256(marshal.dumps([(c.id,c.style_id,c.transform,c.appearance_override) for c in project.cues])).hexdigest()
                before_style=appearance_hash()
                p.style_scope.setCurrentIndex(p.style_scope.findData('all'))
                p.style_layer.setCurrentIndex(p.style_layer.findData('group'))
                before_index=p.undo_stack.index();began=time.perf_counter()
                self.action('all-batch-position',lambda:p.caption_transform_panel.edit('position_x',35.0));yield .03
                deadline=time.perf_counter()+150
                while getattr(p,'_style_application_busy',False):
                    if time.perf_counter()>deadline:raise TimeoutError('Full batch did not settle')
                    yield .03
                self.r['all_batch_completion_ms']=(time.perf_counter()-began)*1000
                self.check('all_batch_created_one_undo',p.undo_stack.index()==before_index+1)
                p.undo_stack.undo();yield .3
                self.check('all_batch_undo_restores_every_cue',appearance_hash()==before_style)
                p.cue_controller.apply_selection_scope(SelectionScope.explicit((project.cues[0].id,),project.cues[0].id))
                p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
                t.set_visible_window(0,60000);p._seek(1);yield 3
                p.subtitle_edit_input.viewport().installEventFilter(self)
                for cue in project.cues[:24]:
                    self.action('warm-select',lambda cue=cue:p.select_cue(cue.id));yield .12
                for cue in project.cues[:10]:
                    self.action('warm-open-editor',lambda cue=cue:p._open_caption_editor(cue.id,'original'));yield .12
                    self.action('warm-input',lambda:QTest.keyClicks(p.subtitle_edit_input,' warm'));yield .12
                    p._cancel_canvas_inline_edit();yield .1
            while time.perf_counter()<until:
                p.video.set_paused(False);yield 4
                playing_position=p.timeline.playhead_ms
                self.action('playing-select',lambda:p.select_cue(project.cues[(cycle*31)%len(project.cues)].id));yield 6
                self.r.setdefault('playback_progress_ms',[]).append(p.timeline.playhead_ms-playing_position)
                p.video.set_paused(True);yield .3
                cue=project.cues[(cycle*31)%len(project.cues)]
                self.action('mixed-select',lambda cue=cue:p.select_cue(cue.id));yield .2
                self.action('mixed-edit',lambda cue=cue:p.cue_controller.set_text(cue.id,cue.text+' [观察]'));yield .3
                p.undo_stack.undo();yield .2
                t.set_visible_window(cue.start_ms,60000+(cycle%4)*30000);yield .2
                p._seek(min(project.media.duration_ms-2000,cue.start_ms+100)/1000);yield .8
                cycle+=1
                if cycle%5==0:
                    selected=project.cues[cycle:cycle+21]
                    p.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in selected],selected[0].id))
                    p.style_scope.setCurrentIndex(p.style_scope.findData('selected'))
                    p.style_layer.setCurrentIndex(p.style_layer.findData('group'))
                    before=p.undo_stack.index();began=time.perf_counter()
                    self.action('mixed-batch-position',lambda:p.caption_transform_panel.edit('position_x',35.0));yield .2
                    while getattr(p,'_style_application_busy',False):yield .05
                    self.r.setdefault('batch_completion_ms',[]).append((time.perf_counter()-began)*1000)
                    if p.undo_stack.index()>before:p.undo_stack.undo()
                    yield .3
            if int(os.environ.get('LONG_AUDIT_SECONDS','0')):
                self.r['qc_before_close']=getattr(p,'_qc_worker',None).snapshot() if getattr(p,'_qc_worker',None) else None
                self.r['qc_timings_before_close']=dict(getattr(p,'_qc_worker_timings',{}))
                self.action('final-save',p.save);yield .3
                path=p.project_path;expected=[(c.id,c.text) for c in project.cues]
                translations=dict(project.generation_metadata.get('translations',{}))
                p.undo_stack.setClean();p._close_project_session('long-audit-reopen');p.open_project(path)
                deadline=time.perf_counter()+150
                while p.project is None or p.project is project or not p._readiness.ready:
                    if time.perf_counter()>deadline:raise TimeoutError('Reopen did not settle')
                    yield .1
                self.check('reopened_all_text',[(c.id,c.text) for c in p.project.cues]==expected)
                self.check('reopened_all_translations',p.project.generation_metadata.get('translations',{})==translations)
                _capture(window,output/'reopened-window.png');yield 5
            self.request_resources();self.r['finished']=True
            self.r['max_gui_gap_ms']=max((ms for _,ms in self.gaps),default=0)

        def finish(self):
            self.timer.stop();self.resource_timer.stop()
            import gc
            if self.gc_observer in gc.callbacks:gc.callbacks.remove(self.gc_observer)
            self.r['gc']=list(self.gc_samples)
            if self.r['profile']:
                self.sample_stop.set()
                (output/'gui-stacks.json').write_text(json.dumps(list(self.stack_samples),indent=2),'utf8')
            self.save()
            if self.page:self.page.undo_stack.setClean()
            QTimer.singleShot(100,window.close)

        def shutdown(self):
            self.r['gui_shutdown']=True;self.save()

    window._long_interactions_audit=Audit()
