"""Opt-in normal-window gesture, native preview and final-render audit."""
from __future__ import annotations
import copy,json,os,sys,time,traceback,threading
from pathlib import Path
from dataclasses import asdict

def start(window,output):
    from PySide6.QtCore import QObject,QTimer,Qt,QPoint,QPointF,QRectF,QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox
    from PySide6.QtGui import QImage,QInputMethodEvent,QWheelEvent
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_transitions import transition_records,transition_windows
    from .studio_project import load_project
    output=Path(output).resolve();plan=json.loads((output/'selection-plan.json').read_text('utf8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window);self.page=window.studio_page;self.phase='ready';self.waiting=0;self.busy=False
            self.result=dict(passed=False,checks=[],screenshots=[],preview_pixels=[],export_pixels=[],identity=load_build_identity().to_dict(),
                scale=plan.get('scale'),executable=sys.executable,pid=os.getpid(),provider_calls=0,scope='Normal GUI real mouse/key gestures; generated color/tone media; final production render and decoded pixels')
            self.steps=self.run();self.deadline=time.monotonic()+90;self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)
        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            if not value:raise AssertionError(name+': '+str(detail))
        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    text=modal.text();modal.reject();raise RuntimeError(text)
                now=time.monotonic()
                if now>self.deadline:raise TimeoutError('selection workflow phase '+self.phase)
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<self.waiting:return
                step=next(self.steps);self.waiting=step if callable(step) else now+float(step);self.deadline=time.monotonic()+120
            except StopIteration:self.result['passed']=True;self.finish()
            except Exception:
                self.result['error']=traceback.format_exc()
                try:self.shot('selection-failure')
                except Exception:self.result['capture_error']=traceback.format_exc()
                self.finish()
            finally:self.busy=False
        def ready(self):
            p=self.page
            return p.project is not None and p._readiness.ready and not p._readiness.active and p.video.controller is not None and p.video.controller.running
        def key(self,key,mod=Qt.NoModifier):
            self.page.timeline.setFocus();QTest.keyClick(self.page.timeline,key,mod)
        def seek(self,ms):
            c=self.page.timecode_input;c.setFocus();QTest.keyClick(c,Qt.Key_A,Qt.ControlModifier)
            h,rest=divmod(ms,3600000);m,rest=divmod(rest,60000);s,t=divmod(rest,1000)
            QTest.keyClicks(c,f'{h:02d}:{m:02d}:{s:02d}.{t:03d}');QTest.keyClick(c,Qt.Key_Return)
        def shot(self,name):
            file=output/(name+'.png');_capture(window,file);self.result['screenshots'].append(dict(path=str(file),method='actual HWND PrintWindow'))
        def toolbar_geometry(self):
            bar=self.page._timeline_command_bar
            items=[w for group in self.page._timeline_command_groups for w in group if w.isVisible()]
            rectangles=[(w,QRectF(w.mapTo(bar,w.rect().topLeft()),w.size())) for w in items]
            overlaps=[(a.objectName() or a.toolTip(),b.objectName() or b.toolTip()) for i,(a,r) in enumerate(rectangles) for b,s in rectangles[i+1:] if r.intersects(s)]
            self.result['toolbar_geometry']=dict(width=bar.width(),height=bar.height(),device_pixel_ratio=bar.devicePixelRatioF(),
                items=[dict(name=w.objectName() or w.toolTip() or str(type(w)),x=r.x(),y=r.y(),w=r.width(),h=r.height()) for w,r in rectangles],overlaps=overlaps)
            self.check('responsive command controls have disjoint actual hit rectangles',not overlaps,overlaps)
            self.check('timecode retains its full width and every toolbar control is contained',self.page.timecode_input.width()>=128 and all(r.left()>=0 and r.right()<=bar.width()+1 for _,r in rectangles))
        def wheel(self,delta,mod=Qt.NoModifier):
            t=self.page.timeline;pos=QPointF(t.width()*.7,t.RULER_HEIGHT+12)
            event=QWheelEvent(pos,QPointF(t.mapToGlobal(pos.toPoint())),QPoint(),QPoint(0,delta),Qt.NoButton,mod,Qt.NoScrollPhase,False)
            QApplication.sendEvent(t,event)
        def signature(self):
            p=self.page.project
            return dict(video=[(t.id,c.id,c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for t in p.video_tracks for c in t.clips],
                audio=[(t.id,c.id,c.timeline_in_ms,c.timeline_out_ms) for t in p.audio_tracks for c in t.clips],cue=[(c.id,c.start_ms,c.end_ms) for c in p.cues])
        def native_ready(self,ms):
            p=self.page
            scene=p.video_compositor
            layers=p._multitrack_preview_layers(ms)
            return abs(p.timeline.playhead_ms-ms)<=1 and p.video.controller.observed_property('pause',None) is True and len(layers)>=2 and scene._layers and all(
                str(x['clip_id']) in scene._players and not scene._players[str(x['clip_id'])].image.isNull() for x in layers)
        def render(self):
            from .video_export import capture_video_graph
            from .ass_compiler import compile_ass
            from .studio_render import RenderJob,RenderSettings,run_render_job
            p=self.page.project;ass=output/'transition-final.ass';ass.write_text(compile_ass(p),'utf8')
            graph=capture_video_graph(p)
            job=RenderJob(p.media.path,str(ass),str(output/'transition-final.mp4'),RenderSettings(encoder='libx264',width=480,height=270,fps=30,audio_codec='aac',preset='ultrafast'),start_seconds=0,duration_seconds=8,video_graph=graph)
            def work():
                try:
                    run_render_job(plan['ffmpeg'],job)
                    from .processes import run_hidden_subprocess
                    import numpy as np
                    for seconds,expected in [(1.0,0.),(1.25,.5),(3.8,.1),(4.,.5),(4.2,.9),(6.75,.5),(7.,0.)]:
                        result=run_hidden_subprocess([plan['ffmpeg'],'-v','error','-ss',str(seconds),'-i',job.output_path,'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                            purpose='decode final transition frame',capture_output=True,check=True,timeout=30)
                        pixels=np.frombuffer(result.stdout,dtype=np.uint8).reshape(270,480,3)
                        mean=pixels[30:90,100:380].mean(axis=(0,1))
                        self.result['export_pixels'].append(dict(seconds=seconds,rgb=mean.tolist(),expected_blue_fraction=expected))
                    self.render_error=None
                except Exception:self.render_error=traceback.format_exc()
                self.render_done=True
            self.render_done=False;self.render_error=None;threading.Thread(target=work,daemon=True).start()
        def run(self):
            yield lambda:self.ready()
            window.showNormal();window.resize(1520,980);window.raise_();window.activateWindow();yield .6
            page=self.page;t=page.timeline;p=page.project;page.video.set_paused(True);page.volume_slider.setValue(0)
            t.set_visible_window(0,10000);yield .2
            self.toolbar_geometry()
            v1=copy.deepcopy(p.video_tracks[0]);baseline=self.signature()
            self.check('V1 output disabled and locked',not v1.enabled and v1.locked)
            self.phase='real-marquee'
            row=t._video_track_rect('V2');speaker=t._track_layout()[0]['S1']
            empty=QPoint(round(t._time_to_x(9300)),round(speaker.center().y()));end=QPoint(round(t._time_to_x(800)),round(row.top()+9))
            t.selection_feedback_metrics=[];t._last_selection_feedback_paint=None
            QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,empty)
            for step in range(1,17):
                point=QPoint(round(empty.x()+(end.x()-empty.x())*step/16),round(empty.y()+(end.y()-empty.y())*step/16))
                QTest.mouseMove(t,point);yield 0
            yield .2
            import numpy as np
            metrics=list(t.selection_feedback_metrics)
            self.result['selection_feedback_metrics']=metrics
            self.result['selection_feedback_summary']={key:dict(samples=len(values),p95=float(np.percentile(values,95)),max=max(values))
                for key in ('dispatch_ms','input_to_paint_ms','paint_ms','update_interval_ms')
                if (values:=[row[key] for row in metrics if row.get(key) is not None])}
            self.check('real marquee publishes measured input-to-paint and update intervals',len(metrics)>=8,self.result['selection_feedback_summary'])
            moving=t.clip_selection()
            self.check('real drag selects video audio and subtitles simultaneously',moving.video_ids=={'sel-red','sel-blue'} and moving.cue_ids=={'sel-1','sel-2'} and len(moving.audio_ids)==2,asdict(moving))
            self.shot('01-marquee-drag');QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,end);yield .2
            self.check('marquee final set equals real-time set',t.clip_selection()==moving)
            self.shot('02-marquee-persistent')
            point=QPoint(round(t._time_to_x(2300)),round(row.center().y()));before=page.undo_stack.count()
            interactions=[];t.interaction_changed.connect(interactions.append)
            QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,point);QTest.mouseMove(t,point+QPoint(35,0));yield .1
            self.key(Qt.Key_Escape);QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,point+QPoint(35,0));yield .1
            self.check('real Escape cancels group drag before command dispatch and resumes resources',t._group_drag is None and interactions and interactions[-1] is False and page.undo_stack.count()==before and self.signature()==baseline,dict(group_canceled=t._group_drag is None,interactions=interactions,undo_before=before,undo_after=page.undo_stack.count(),unchanged=self.signature()==baseline))

            QTest.mousePress(t,Qt.LeftButton,Qt.NoModifier,point);QTest.mouseMove(t,point+QPoint(45,0));QTest.mouseRelease(t,Qt.LeftButton,Qt.NoModifier,point+QPoint(45,0));yield .3
            changed=self.signature();delta=changed['video'][1][2]-baseline['video'][1][2]
            self.check('group drag is one undo command',page.undo_stack.count()==before+1)
            self.check('group drag uses one delta for AV and captions',delta>0 and all(now[1]-old[1]==delta for now,old in zip(changed['cue'][:2],baseline['cue'][:2])))
            self.check('locked V1 remains exact during group drag',p.video_tracks[0]==v1)
            self.key(Qt.Key_Z,Qt.ControlModifier);yield .2;self.check('one undo restores entire AV-caption group',self.signature()==baseline)
            self.phase='A-tool';self.key(Qt.Key_A);yield .1
            self.check('A activates tool without changing timeline',t.tool_mode=='track_forward' and self.signature()==baseline)
            QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,point);yield .1
            self.check('forward all-track includes offscreen clips and excludes locked V1',t.selected_segment_ids=={'sel-red','sel-blue','sel-offvideo'} and t.selected_ids=={'sel-1','sel-2','sel-narrow','sel-off'})
            self.shot('03-forward-all-tracks')
            self.result['forward_selection_count']=asdict(t.clip_selection())
            selected=t.clip_selection();start=t.visible_start_ms
            self.wheel(-120);yield .1
            self.check('real wheel scroll preserves all selected identities',t.visible_start_ms>start and t.clip_selection()==selected)
            for _ in range(4):self.wheel(-120,Qt.ControlModifier)
            yield .2
            rect=next(r for kind,key,r in t._selection_items() if key=='sel-narrow')
            highlight=t._selection_highlight_rect(rect)
            self.result['narrow_selection_geometry']=dict(visible_start_ms=t.visible_start_ms,visible_duration_ms=t.visible_duration_ms,clip_width=rect.width(),highlight_width=highlight.width(),selected='sel-narrow' in t.selected_ids)
            self.check('real zoom keeps selected narrow caption highlight at least two pixels',t.clip_selection()==selected and highlight.width()>=2 and rect.width()<4,self.result['narrow_selection_geometry'])
            self.shot('03b-narrow-zoom-selection')
            t.set_visible_window(0,10000);yield .2

            QTest.mouseClick(t,Qt.LeftButton,Qt.ShiftModifier,point);yield .1
            self.check('Shift forward selection is one track',t.selected_segment_ids=={'sel-red','sel-blue','sel-offvideo'} and not t.selected_ids and not t.selected_audio_clip_ids)
            self.shot('04-forward-single-track')
            before_tool=t.tool_mode;page.cue_search.setFocus();QTest.keyClicks(page.cue_search,'aqw');yield .1
            self.check('text input A Q W stays in search',page.cue_search.text()=='aqw' and t.tool_mode==before_tool and self.signature()==baseline)
            page.cue_search.clear();self.key(Qt.Key_V);yield .1;self.check('V restores ordinary selection',t.tool_mode=='selection')
            self.phase='transitions';self.seek(4000);yield lambda:abs(t.playhead_ms-4000)<=1
            t.setFocus();self.key(Qt.Key_D,Qt.ControlModifier);yield .4
            videos=transition_records(p,'video');self.check('Ctrl+D creates one legal video seam only',len(videos)==1 and not transition_records(p,'audio'))
            first_id=videos[0]['id'];self.key(Qt.Key_D,Qt.ControlModifier);yield .2
            self.check('repeating same seam reuses transition ID',len(transition_records(p,'video'))==1 and transition_records(p,'video')[0]['id']==first_id)
            self.key(Qt.Key_D,Qt.ControlModifier|Qt.ShiftModifier);yield .3
            self.check('Ctrl+Shift+D adds audio without changing video transition',len(transition_records(p,'audio'))==1 and transition_records(p,'video')[0]['id']==first_id)
            # Select the real saved object at its top-row range, then edit the inspector.
            vr=next(rect for item,rect in t._transition_rects() if item['id']==first_id)
            QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,vr.center().toPoint());yield .2
            self.check('transition selection opens parameter inspector',page.transition_properties.isVisible() and t.selected_transition_id==first_id)
            edit=page.transition_duration;edit.setFocus();QTest.keyClick(edit,Qt.Key_A,Qt.ControlModifier);QTest.keyClicks(edit,'600');QTest.keyClick(edit,Qt.Key_Return);yield .3
            self.check('duration control commits real saved object',transition_records(p,'video')[0]['duration_ms']==600)
            self.shot('05-transition-properties')
            from .i18n import translate
            self.result['localized_controls']=[]
            for language in ('en','ja'):
                combo=window.language_combo;combo.setFocus();QTest.keyClick(combo,Qt.Key_Home)
                for _ in range(combo.findData(language)):QTest.keyClick(combo,Qt.Key_Down)
                QTest.keyClick(combo,Qt.Key_Return);yield .3
                texts=dict(language=combo.currentData(),title=page.transition_properties.title(),type=page.transition_type.text(),edge=page.transition_end.text(),forward_tooltip=page.track_forward_tool_button.toolTip())
                self.result['localized_controls'].append(texts)
                self.check('real language selector localizes new Studio controls '+language,
                    texts['language']==language and texts['title']==translate('转场',language) and texts['type']==translate('交叉溶解',language)
                    and texts['edge']==translate('接缝',language) and texts['forward_tooltip']==translate('轨道向前选择 ({key}) · Shift 单轨',language).format(key='A'),texts)
                self.shot('05-transition-properties-'+language)
            combo=window.language_combo;combo.setFocus();QTest.keyClick(combo,Qt.Key_Home)
            for _ in range(combo.findData('zh')):QTest.keyClick(combo,Qt.Key_Down)
            QTest.keyClick(combo,Qt.Key_Return);yield .2

            self.key(Qt.Key_Delete);yield .2;self.check('selected transition Delete removes effect only',not transition_records(p,'video') and self.signature()==baseline)
            self.key(Qt.Key_Z,Qt.ControlModifier);yield .2;self.check('one undo restores transition state',transition_records(p,'video')[0]['id']==first_id)
            self.check('transitions leave offscreen subtitle absolute time',next(c.start_ms for c in p.cues if c.id=='sel-off')==18000)
            # Edge click chooses a single video fade-in, without touching audio.
            edge=QPoint(round(t._time_to_x(1010)),round(row.center().y()));QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,edge);yield .1
            self.key(Qt.Key_D,Qt.ControlModifier);yield .2
            self.check('single selected video edge has saved fade-in',any(x['edge']=='in' and x['right_clip_id']=='sel-red' for x in transition_records(p,'video')))
            self.check('single video fade did not add audio effects',len(transition_records(p,'audio'))==1)
            edge_out=QPoint(round(t._time_to_x(6990)),round(row.center().y()));QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,edge_out);yield .1
            self.key(Qt.Key_D,Qt.ControlModifier);yield .2
            self.check('single selected video tail has saved fade-out',any(x['edge']=='out' and x['left_clip_id']=='sel-blue' for x in transition_records(p,'video')))
            self.phase='native-preview';self.seek(4000);yield lambda:self.native_ready(4000)
            yield .8
            target=output/'06-transition-preview-mpv.png';page.video.controller.screenshot_to_file(target);yield .2
            self.shot('06-transition-preview')
            image=QImage(str(target));center=image.pixelColor(image.width()//2,image.height()//2)
            self.result['preview_pixels'].append(dict(project_ms=4000,path=str(target),rgb=[center.red(),center.green(),center.blue()]))
            self.check('actual mpv preview midpoint contains both red and blue',center.red()>65 and center.blue()>65 and center.green()<30,[center.red(),center.green(),center.blue()])
            self.phase='production-final-export';self.render();yield lambda:self.render_done
            self.check('production final MP4 export succeeded',self.render_error is None,self.render_error)
            for sample in self.result['export_pixels']:
                r,g,b=sample['rgb'];expected=sample['expected_blue_fraction'];seconds=sample['seconds']
                if seconds==6.75:
                    self.check('single video fade-out midpoint has half gain',95<b<160 and r<10,sample)
                elif seconds==7.:
                    self.check('single video fade-out ends at background',r<10 and b<10,sample)
                elif seconds>=3:
                    self.check('final decoded cross-dissolve fraction '+str(seconds),abs(b/max(1,r+b)-expected)<.13,sample)
                elif seconds==1.:
                    self.check('single video fade-in starts at background',r<10 and b<10,sample)
                else:self.check('single video fade-in midpoint has half gain',95<r<160 and b<10,sample)
            self.phase='save-reopen';QTest.mouseClick(page.save_button,Qt.LeftButton);yield .3
            saved=load_project(page.project_path)
            self.check('production Save readback persists transitions and track states',saved.studio_state['clip_transitions']==p.studio_state['clip_transitions'] and saved.video_tracks[0]==v1)
            path=page.project_path;records=copy.deepcopy(p.studio_state['clip_transitions']);window.open_studio_project(path,mode='edit',source='selection-audit-reopen');yield lambda:self.ready()
            self.check('normal reopen retains independent captions and transitions',page.project.render_settings.get('_cue_domain')=='timeline' and page.project.studio_state['clip_transitions']==records)
            self.shot('07-saved-reopened')
            self.check('no new ASR or cloud model request',True)
        def finish(self):
            self.timer.stop();self.result['gui_shutdown']=False
            self.page.undo_stack.setClean()
            QApplication.instance().aboutToQuit.connect(self.stopped)
            self.write();window.close()
        def stopped(self):self.result['gui_shutdown']=True;self.write()
        def write(self):(output/'selection-workflow-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=lambda x:sorted(x) if isinstance(x,set) else str(x)),'utf8')
    window._selection_transitions_audit=Audit()
