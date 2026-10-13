"""Headed/frozen acceptance for timing gestures and subtitle foreground races."""
from __future__ import annotations
import json
import os
import sys
import time


def start_live_edit_acceptance(window, output):
    import numpy as np
    from PySide6.QtCore import QObject, QTimer, Qt, QPoint, QPointF, QEvent
    from PySide6.QtGui import QImage, QMouseEvent
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from .build_identity import load_build_identity
    from .studio_project import StudioCue
    from .selection_scope import SelectionScope

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.results = dict(runtime='frozen' if getattr(sys,'frozen',False) else 'source',
                                build=vars(load_build_identity()), checks={}, timing=[], shadow=[])
            self.sequence = self.scenario()
            self.waiting = 0.
            self.started = time.perf_counter()
            self.timer = QTimer(self)
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.setInterval(5)
            self.timer.timeout.connect(self.tick)
            self.timer.start()
            from . import visual_design_graph
            self.compiler = visual_design_graph.compile_live_scene
            self.drag_compiles = 0
            def compile_scene(*args,**kwargs):
                if self.page.timeline._drag:self.drag_compiles+=1
                return self.compiler(*args,**kwargs)
            visual_design_graph.compile_live_scene=compile_scene
            from . import studio_project
            self.persist=studio_project._atomic_json_blob_write
            self.drag_writes=0
            def persist(*args,**kwargs):
                if self.page.timeline._drag:self.drag_writes+=1
                return self.persist(*args,**kwargs)
            studio_project._atomic_json_blob_write=persist
            self.ass_submits=0;self.ass_completions=0
            from .ass_compile_actor import AssCompileActor
            self.ass_submit=AssCompileActor.submit
            def submit(actor,*args,**kwargs):
                if self.page.timeline._drag:self.ass_submits+=1
                return self.ass_submit(actor,*args,**kwargs)
            AssCompileActor.submit=submit
            self.ass_ready=self.page._ass_actor_ready
            def ass_ready(result):
                if self.page.timeline._drag and not result.cache_hit:self.ass_completions+=1
                return self.ass_ready(result)
            self.page._ass_actor_ready=ass_ready
            if self.page._ass_actor is not None:self.page._ass_actor._on_ready=ass_ready

        def tick(self):
            try:
                now=time.perf_counter()
                if now-self.started>180: raise TimeoutError('live edit audit exceeded 180 seconds')
                if callable(self.waiting):
                    if not self.waiting(): return
                elif now<self.waiting: return
                pending=next(self.sequence)
                self.waiting=pending if callable(pending) else time.perf_counter()+float(pending)
            except StopIteration: self.finish()
            except Exception:
                import traceback
                self.results['error']=traceback.format_exc()
                self.finish()

        def check(self,key,value):
            self.results['checks'][key]=bool(value)

        def mouse(self, widget, kind, point, modifiers=Qt.KeyboardModifier.NoModifier):
            point=QPointF(point)
            QApplication.sendEvent(widget,QMouseEvent(kind,point,QPointF(widget.mapToGlobal(point.toPoint())),
                Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,modifiers))

        def native(self,name):
            target=output/f'{name}.png'
            self.page.video.controller.screenshot_to_file(target)
            image=QImage(str(target)).convertToFormat(QImage.Format.Format_RGBA8888)
            arr=np.frombuffer(image.bits(),dtype=np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4]
            rgb=arr.reshape(image.height(),image.width(),4)[:,:,:3].copy()
            return rgb

        def shadow_score(self,rgb):
            ys,xs=np.where(rgb.min(axis=2)>225)
            if not len(xs):return 0
            band=rgb[max(0,ys.min()-8):min(rgb.shape[0],ys.max()+32),
                max(0,xs.min()-10):min(rgb.shape[1],xs.max()+32)]
            return int((band.max(axis=2)<36).sum())

        def scenario(self):
            page=self.page
            yield lambda: page.project is not None and page.video.controller is not None and page.video._startup_state=='READY'
            for track in page.project.video_tracks[1:]: track.enabled=False
            cue=page.project.cues[0]
            cue.start_ms,cue.end_ms,cue.text=1000,4000,'阴影与时间边界'
            page.project.cues.append(StudioCue('second',4300,5800,'第二条字幕',speaker_id='S02'))
            page.project.validate()
            page.cue_controller.model_changed()
            page._sync_video_compositor(2000)
            page._seek(2)
            yield .8
            page.select_cue('cue')
            tl=page.timeline
            tl.set_visible_window(0,8000); tl.snap_enabled=False
            yield .4
            for mode in ('move','left','right'):
                for zoom in (6000,3000):
                    tl.set_visible_window((1500 if mode=="right" else 500) if zoom==3000 else 0,zoom)
                    cue=page.project.cues[0]
                    times=(cue.start_ms,cue.end_ms)
                    x=tl._time_to_x(cue.start_ms if mode=='left' else cue.end_ms if mode=='right' else sum(times)/2)
                    y=tl._track_layout()[0][cue.speaker_id].center().y()
                    origin=QPointF(x,y)
                    undo=page.undo_stack.index()
                    ass=page._ass_generation
                    save=page._autosave_generation
                    self.mouse(tl,QEvent.Type.MouseButtonPress,origin)
                    yield .15
                    # Exclude preparation from steady pointer-frame timing, and
                    # report it separately rather than hiding setup latency.
                    for i in range(1,21):
                        point=origin+QPointF(i*3,0)
                        self.mouse(tl,QEvent.Type.MouseMove,point)
                        yield .006
                    value=tl._timing_preview.get(cue.id)
                    delta=tl._x_to_time(point.x())-tl._x_to_time(origin.x())
                    prefix=f'{mode}-{zoom}'
                    self.check(prefix+'-project-unchanged',(cue.start_ms,cue.end_ms)==times)
                    self.check(prefix+'-live-boundary',value is not None and
                        (value.end_ms-times[1] if mode=='right' else value.start_ms-times[0])==delta)
                    self.check(prefix+'-no-undo-save-ass',(page.undo_stack.index(),page._autosave_generation,page._ass_generation)==(undo,save,ass))
                    tl.grab().save(str(output/f'{prefix}-during.png'))
                    self.results['timing'].append(dict(case=prefix,frames=tl.timing_preview_metrics))
                    self.mouse(tl,QEvent.Type.MouseButtonRelease,point)
                    yield .35
                    self.check(prefix+'-one-undo',page.undo_stack.index()==undo+1)
                    page.undo_stack.undo()
                    yield .3
                    self.check(prefix+'-undo-restores',(page.project.cues[0].start_ms,page.project.cues[0].end_ms)==times)
            # A right edge crossing the paused playhead must hide the pixels
            # before release. Escape restores both bytes and foreground.
            tl.set_visible_window(0,6000); tl.snap_enabled=False
            cue=page.project.cues[0]
            origin=QPointF(tl._time_to_x(cue.end_ms),tl._track_layout()[0][cue.speaker_id].center().y())
            undo=page.undo_stack.index()
            self.native('timing-visible-before')
            self.mouse(tl,QEvent.Type.MouseButtonPress,origin)
            yield .2
            target=QPointF(tl._time_to_x(1500),origin.y())
            self.mouse(tl,QEvent.Type.MouseMove,target)
            yield .1
            hidden=self.native('timing-hidden-during')
            self.check('boundary-crossing-hides-before-release',int((hidden.min(axis=2)>225).sum())<50)
            QTest.keyClick(tl,Qt.Key.Key_Escape)
            yield .4
            restored=self.native('timing-cancel-restored')
            self.check('cancel-restores-visible-pixels',int((restored.min(axis=2)>225).sum())>100 and page.undo_stack.index()==undo)
            tl.set_selection_scope(SelectionScope.explicit({'cue','second'},'cue'))
            cue=page.project.cues[0]
            origin=QPointF(tl._time_to_x(2500),tl._track_layout()[0][cue.speaker_id].center().y())
            originals=[(c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues]
            self.mouse(tl,QEvent.Type.MouseButtonPress,origin)
            yield .1
            self.mouse(tl,QEvent.Type.MouseMove,origin+QPointF(30,0))
            yield .1
            self.check('multi-track-preview',len(tl._timing_preview)==2 and
                len({v.speaker_id for v in tl._timing_preview.values()})==2)
            self.mouse(tl,QEvent.Type.MouseButtonRelease,origin+QPointF(30,0))
            yield .3
            page.undo_stack.undo(); yield .3
            self.check('multi-track-undo',[(c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues]==originals)
            tl.set_selection_scope(SelectionScope.explicit({'cue'},'cue'))
            for name,target_ms,snap in [('minimum',900,False),('snap',4290,True),('overlap',4700,False)]:
                cue=page.project.cues[0]
                origin=QPointF(tl._time_to_x(cue.end_ms),tl._track_layout()[0][cue.speaker_id].center().y())
                tl.snap_enabled=snap
                self.mouse(tl,QEvent.Type.MouseButtonPress,origin);yield .08
                target=QPointF(tl._time_to_x(target_ms),origin.y())
                self.mouse(tl,QEvent.Type.MouseMove,target);yield .08
                value=tl._timing_preview[cue.id]
                expected=1050 if name=='minimum' else 4300 if name=='snap' else target_ms
                self.check(name+'-live-rule',abs(value.end_ms-expected)<=2)
                self.mouse(tl,QEvent.Type.MouseButtonRelease,target);yield .15
                if name=='overlap':
                    from .studio_project import autosave_path,load_project,recoverable_autosave
                    expected_cues=[(c.id,c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues]
                    page._start_autosave_worker(page._autosave_generation)
                    yield lambda: not page._autosave_worker_running
                    candidate=recoverable_autosave(page.project_path)
                    restored=load_project(candidate) if candidate else None
                    self.check('autosave-recovery-matches-committed-timing',restored is not None and
                        [(c.id,c.start_ms,c.end_ms,c.speaker_id) for c in restored.cues]==expected_cues)
                page.undo_stack.undo();yield .2
            tl.snap_enabled=False
            # Visible dark offset shadow over a flat real video makes any old
            # position/renderer alternation observable across complete frames.
            from .visual_design_graph import clean_subtitle_graph,style_recipe_from_graph,MotionTrack,MotionKeyframe
            graph=clean_subtitle_graph()
            graph.text_layer.shadow={"enabled":True,"color":"#DD000000","offset_x":18,"offset_y":24,"blur":10}
            graph.motion_graph.tracks.append(MotionTrack("group","x",[
                MotionKeyframe(0,0,"linear"),MotionKeyframe(600,12,"linear"),
                MotionKeyframe(1200,-12,"linear"),MotionKeyframe(1800,12,"linear"),MotionKeyframe(2400,0,"linear")]))
            graph.validate()
            recipe=style_recipe_from_graph(graph).to_dict()
            page.project.style_recipes[page.project.cues[0].style_id]=recipe
            style=page.project.styles[0]
            style.shadow=12.; style.font_size=62.
            page.cue_controller.model_changed()
            page.select_cue('cue'); page._seek(2)
            page._schedule_advanced_preview(recipe,force=True)
            page.position_edit_button.setChecked(True)
            yield .5
            overlay=page.position_overlay
            iterations=int(os.environ.get('TWOBYTEASR_AUDIT_SHADOW_ITERATIONS','20'))
            self.results['shadow_iterations']=iterations
            for iteration in range(iterations):
                if iteration==iterations//2:
                    for track in page.project.video_tracks[1:]:
                        track.enabled=True
                        for clip in track.clips: clip.transform.opacity=0.
                    page._sync_video_compositor(2000)
                    yield .3
                origin=overlay._subtitle_rect().center().toPoint()
                self.mouse(overlay,QEvent.Type.MouseButtonPress,origin,Qt.KeyboardModifier.AltModifier)
                yield .1
                target=origin+QPoint(22,-10)
                self.mouse(overlay,QEvent.Type.MouseMove,target,Qt.KeyboardModifier.AltModifier)
                yield .08
                self.mouse(overlay,QEvent.Type.MouseButtonRelease,target,Qt.KeyboardModifier.AltModifier)
                transition=[]
                shadow_scores=[]
                for frame in range(6):
                    rgb=self.native(f'handoff-{iteration:02d}-{frame}')
                    shadow_scores.append(self.shadow_score(rgb))
                    canvas=page.advanced_cue_overlay
                    if frame in (0,5) and iteration==iterations//2:
                        canvas._source_image.save(str(output/f'handoff-source-{iteration}-{frame}.png'))
                        for key,image in canvas._layer_images.items():
                            image.save(str(output/f'handoff-layer-{key}-{iteration}-{frame}.png'))
                    transition.append(dict(wall=time.perf_counter(),visibility=page.subtitle_visibility_trace(),
                        snapshot_shadow=getattr(canvas._snapshot,'shadow',None),
                        source_kind=page._advanced_canvas_source_kind,
                        layer_generation=canvas._layer_generation,
                        layer_ids=list(canvas._layer_images)))
                    yield .016
                self.results.setdefault('handoffs',[]).append(transition)
                self.results.setdefault('handoff_shadow_scores',[]).append(shadow_scores)
                self.check(f'handoff-{iteration:02d}-shadow-retained',min(shadow_scores)>200 and min(shadow_scores)>=max(shadow_scores)*.7)
                frames=[]
                for frame in range(5):
                    frames.append(self.native(f'shadow-{iteration:02d}-{frame}'))
                    yield .025
                diffs=[int(np.count_nonzero(np.max(np.abs(f.astype(int)-frames[0].astype(int)),axis=2)>12)) for f in frames[1:]]
                self.results['shadow'].append(dict(iteration=iteration,differences=diffs,
                    owner=page.subtitle_visibility_trace()['foreground_owner']))
                self.check(f'shadow-{iteration:02d}-graph-owner',page.subtitle_visibility_trace()['foreground_owner']=='advanced_live')
                self.check(f'shadow-{iteration:02d}-stable',max(diffs)<20)
                page.undo_stack.undo(); yield .18
                page.undo_stack.redo(); yield .18
                page.undo_stack.undo(); yield .18
                page._seek(2.2); yield .08
                page.video.set_paused(False)
                for frame in range(6):
                    self.native(f'playing-shadow-{iteration:02d}-{frame}')
                    yield .016
                page.video.set_paused(True); page._seek(2); yield .18
            window.grab().save(str(output/'live-edit-final.png'))
            self.results['formal_live_compiles_during_drag']=self.drag_compiles
            self.check('zero-formal-live-compiles-during-drag',self.drag_compiles==0)
            self.results['project_disk_writes_during_drag']=self.drag_writes
            self.check('zero-project-disk-writes-during-drag',self.drag_writes==0)
            self.results['ass_during_drag']={'submitted':self.ass_submits,'completed_cache_misses':self.ass_completions}
            self.check('zero-formal-ass-submits-during-drag',self.ass_submits==0)
            self.check('zero-formal-ass-completes-during-drag',self.ass_completions==0)

        def finish(self):
            self.timer.stop()
            from . import visual_design_graph
            visual_design_graph.compile_live_scene=self.compiler
            from . import studio_project
            studio_project._atomic_json_blob_write=self.persist
            from .ass_compile_actor import AssCompileActor
            AssCompileActor.submit=self.ass_submit
            self.page.close_page()
            (output/'live-edit-acceptance.json').write_text(json.dumps(self.results,ensure_ascii=False,indent=2),encoding='utf-8')
            window.hide()
            QTimer.singleShot(200,QApplication.instance().quit)
    window._acceptance_audit=Audit()
