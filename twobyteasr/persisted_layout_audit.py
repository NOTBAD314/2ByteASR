"""Opt-in normal-entry layout/drag/save/export audit, isolated under cwd/tmp.

The generated fixture is labeled synthetic; GE's existing 43-cue project is
opened and edited only as a private copy. No inference or provider call occurs.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject,QTimer,Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_edit_sequence import projected_cues
    from .style_resolution import resolve_cue_visual
    from .visual_snapshot import _anchor,build_visual_cue_snapshot
    from .studio_project import StudioCue,StudioSpeaker,load_project
    from .studio_commands import add_cue_command
    from .subtitle_stacking import initialize_project_layout
    from .studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions,verify_subtitle_artifact
    from .export_timeline import export_project_snapshot
    from .ass_compiler import compile_ass

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page;self.busy=False;self.waiting=0;self.phase='ready'
            self.plan=json.loads((output/'layout-plan.json').read_text('utf8'))
            self.result=dict(passed=False,checks=[],screenshots=[],positions=[],pid=os.getpid(),
                executable=sys.executable,identity=load_build_identity().to_dict(),
                scope=self.plan['generated_fixture']+'; current GE project private copy',
                gui_shutdown=False,dpr=window.devicePixelRatioF())
            self.steps=self.run();self.deadline=time.monotonic()+90
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(50)

        def check(self,name,value,detail=None):
            self.result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
            (output/'layout-progress.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            if not value:raise AssertionError(name+': '+str(detail))

        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                self.page=window.studio_page
                now=time.monotonic()
                modal=QApplication.activeModalWidget()
                if isinstance(modal,QMessageBox):
                    message=modal.text();modal.reject();raise RuntimeError(message)
                if now>self.deadline:raise TimeoutError('layout audit timeout: '+self.phase)
                if callable(self.waiting):
                    if not self.waiting():return
                elif now<float(self.waiting):return
                step=next(self.steps);self.waiting=step if callable(step) else now+float(step)
                self.deadline=time.monotonic()+150
            except StopIteration:self.result['passed']=True;self.finish()
            except BaseException:
                self.result['error']=traceback.format_exc()
                try:self.shot('failure')
                except Exception:self.result['capture_error']=traceback.format_exc()
                self.finish()
            finally:self.busy=False

        def ready(self,path=None):
            self.page=window.studio_page;p=self.page
            return (p.project is not None and p._readiness.ready and not p._readiness.active
                    and p.video.controller is not None and p.video.controller.running
                    and (path is None or Path(p.project_path).resolve()==path.resolve()))

        def positions(self):
            p=self.page.project;w=int(p.render_settings.get('play_res_x',1920));h=int(p.render_settings.get('play_res_y',1080))
            return {c.id:list(_anchor(resolve_cue_visual(p,c).style,w,h)[:2]) for c in projected_cues(p)}

        def record_positions(self,name,expected=None):
            value=self.positions();self.result['positions'].append(dict(phase=name,anchors=value,
                playhead_ms=self.page.timeline.playhead_ms,viewport=[self.page.video.width(),self.page.video.height()]))
            if expected is not None:self.check('positions stable '+name,value==expected,value)
            for c in projected_cues(self.page.project):
                snapshot=build_visual_cue_snapshot(self.page.project,c.id)
                self.check('snapshot uses saved anchor '+name+' '+c.id,
                           [snapshot.position_x,snapshot.position_y]==value[c.id])
            return value

        def shot(self,name):
            _capture(window,output/(name+'.png'))
            self.result['screenshots'].append(dict(path=str(output/(name+'.png')),method='actual HWND PrintWindow'))
            controller=self.page.video.controller
            if controller and controller.running:
                controller.screenshot_to_file(output/(name+'-mpv.png'))
                self.result['screenshots'].append(dict(path=str(output/(name+'-mpv.png')),method='actual mpv window bitmap'))

        def seek(self,ms):
            box=self.page.timecode_input;box.setFocus()
            QTest.keyClick(box,Qt.Key_A,Qt.ControlModifier)
            seconds,millis=divmod(ms,1000);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
            QTest.keyClicks(box,f'{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}')
            QTest.keyClick(box,Qt.Key_Return)
            receipt=getattr(self.page.video,'_active_seek_trace',None) or {}
            target=receipt.get('decoder_target_seconds',receipt.get('target_seconds'))
            clock_target=receipt.get('target_seconds')
            valid=(isinstance(target,(int,float)) and math.isfinite(target)
                   and isinstance(clock_target,(int,float)) and math.isfinite(clock_target))
            self.seek_expectation=dict(phase=self.phase,requested_project_ms=ms,
                decoder_target_ms=float(target)*1000 if valid else None,
                canvas_clock_target_ms=float(clock_target)*1000 if valid else None,
                generation=receipt.get('generation'),project_path=str(self.page.project_path))
            self.check('production seek target '+self.phase,valid,self.seek_expectation)

        def media_state(self):
            p=self.page;clock=p.video.playback_position_snapshot();controller=p.video.controller
            actual=controller.observed_property('time-pos',None) if controller else None
            valid=isinstance(actual,(int,float)) and math.isfinite(actual)
            value=dict(phase=self.phase,monotonic=time.monotonic(),timeline_ms=p.timeline.playhead_ms,
                mpv_paused=controller.observed_property('pause',None) if controller else None,
                mpv_time_ms=float(actual)*1000 if valid else None,clock_paused=bool(clock.paused),
                clock_observed_ms=clock.observed_media_ms,clock_presentation_ms=clock.presentation_media_ms,
                playback_generation=clock.playback_generation,source_generation=clock.source_generation,
                seeking=clock.seeking,exact_seek_pending=clock.exact_seek_pending,clock_source=clock.source,
                buffered_play_pending=bool(getattr(p.video,'_buffered_play_pending',False)),
                startup_state=getattr(p.video,'_startup_state',None))
            self.result['last_media_state']=value
            return value

        @staticmethod
        def paused_observation(value):
            return (value['mpv_paused'] is True and value['clock_paused'] is True
                    and value['mpv_time_ms'] is not None and not value['seeking']
                    and not value['exact_seek_pending'] and not value['buffered_play_pending']
                    and value['startup_state']=='READY')

        def stable_pause_gate(self):
            """Observe 200ms of settled transport; never force a renderer/clock."""
            sample={}
            def stable():
                value=self.media_state()
                if not self.paused_observation(value):sample.clear();return False
                old=sample.get('value')
                moved=(old is None or old['playback_generation']!=value['playback_generation']
                    or old['source_generation']!=value['source_generation']
                    or any(abs(value[key]-old[key])>2 for key in
                           ('mpv_time_ms','clock_observed_ms','clock_presentation_ms')))
                if moved:sample.update(value=value,since=value['monotonic']);return False
                return value['monotonic']-sample['since']>=.2
            return stable

        def pause(self,label):
            self.phase='pause-'+label
            before=self.media_state()
            def agrees():
                value=self.media_state()
                return isinstance(value['mpv_paused'],bool) and value['mpv_paused']==value['clock_paused']
            yield agrees
            value=self.media_state();clicked=not value['clock_paused'] or value['buffered_play_pending']
            if clicked:QTest.mouseClick(self.page.play_button,Qt.LeftButton)
            yield self.stable_pause_gate()
            after=self.media_state()
            receipt=dict(label=label,action='normal play_button mouse click' if clicked else 'already paused',
                before=before,after=after,stable_ms=200,max_drift_ms=2)
            self.result.setdefault('pauses',[]).append(receipt)
            self.check('real transport stably paused '+label,self.paused_observation(after),receipt)

        def play_for(self,label,seconds):
            self.phase='play-'+label
            before=self.media_state()
            QTest.mouseClick(self.page.play_button,Qt.LeftButton)
            def playing():
                value=self.media_state()
                return value['mpv_paused'] is False and value['clock_paused'] is False and not value['buffered_play_pending']
            yield playing
            yield seconds
            after=self.media_state()
            receipt=dict(label=label,action='normal play_button mouse click',before=before,after=after,
                requested_play_seconds=seconds,media_advance_ms=(after['mpv_time_ms']-before['mpv_time_ms'])
                    if after['mpv_time_ms'] is not None and before['mpv_time_ms'] is not None else None)
            self.result.setdefault('plays',[]).append(receipt)
            self.check('actual media advanced '+label,receipt['media_advance_ms'] is not None
                       and receipt['media_advance_ms']>=100,receipt)
            yield from self.pause(label+'-after-play')

        def active_ids(self,ms):
            from .caption_scene import active_cues
            return [c.id for c in active_cues(self.page,ms)]

        def seek_pixels(self,label,ms,ids):
            self.phase='seek-pixels-'+label
            self.seek(ms)
            yield self.stable_pause_gate()
            yield lambda:self.pixels_ready(ms,ids)
            self.result.setdefault('seeks',[]).append(dict(expectation=dict(self.seek_expectation),
                observation=self.media_state(),visibility=dict(self.result['last_visibility'])))
            self.check('paused actual media and pixels '+label,True,self.result['seeks'][-1])

        def pixels_ready(self,ms,ids):
            p=self.page
            # Production seeking snaps to a video frame. Do not wait forever
            # for a millisecond value that is between frames.
            state=self.media_state()
            trace=p.subtitle_visibility_trace(reason='persisted_layout_pixels')
            trace['requested_ms']=ms;trace['timeline_ms']=p.timeline.playhead_ms;trace['media_observation']=state
            self.result['last_visibility']=trace
            expected=getattr(self,'seek_expectation',{})
            target=expected.get('decoder_target_ms')
            clock_target=expected.get('canvas_clock_target_ms')
            # Primary V1 clock is source time; multitrack clock is project
            # time. The production seek receipt specifies its own domain.
            if (not self.paused_observation(state) or target is None or clock_target is None
                    or abs(p.timeline.playhead_ms-ms)>40
                    or abs(state['clock_presentation_ms']-clock_target)>40
                    or abs(state['mpv_time_ms']-target)>40):return False
            rows=trace.get('cue_pixels',())
            return (trace.get('owner')=='caption_scene' and trace.get('visible') is True
                    and set(trace.get('expected_cue_ids',()))==set(ids)
                    and set(trace.get('rendered_cue_ids',()))==set(ids)
                    and len(rows)==len(ids) and all(r.get('status')=='rendered'
                                                  and r.get('alpha_nonzero',0)>0 for r in rows))

        def edit_y(self,key,y):
            p=self.page;p.select_cue(key)
            p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
            box=p.style_position_y.lineEdit();box.setFocus()
            QTest.keyClick(box,Qt.Key_A,Qt.ControlModifier);QTest.keyClicks(box,str(y));QTest.keyClick(box,Qt.Key_Return)

        def drag_y(self,key,y):
            p=self.page;overlay=p.position_overlay;old=self.positions()[key][1]
            start=overlay._subtitle_rect().center().toPoint()
            target=start+QPoint(0,round((y-old)*overlay._mapper().scale_y))
            QTest.mousePress(overlay,Qt.LeftButton,Qt.AltModifier,start)
            QTest.mouseMove(overlay,target,50)
            QTest.mouseRelease(overlay,Qt.LeftButton,Qt.AltModifier,target)
            self.check('drag target committed '+key,abs(self.positions()[key][1]-y)<=3,self.positions()[key])

        def export_video(self,name,length):
            self.phase='video-export-'+name;p=self.page
            QTest.mouseClick(p.studio_render_button,Qt.LeftButton)
            yield lambda:p.export_workspace is not None
            ui=p.export_workspace;yield .3
            ui.filename.setText(name);ui.filename_prefix.clear();ui.filename_suffix.clear()
            ui.directory.setText(str(output/'video'))
            ui.preset.setCurrentIndex(ui.preset.findData('custom'));ui.quality.setCurrentIndex(ui.quality.findData('custom'))
            if ui.encoder.findData('libx264')<0:ui.encoder.addItem('Software x264','libx264')
            ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'));ui.rate_control.setCurrentIndex(ui.rate_control.findData('crf'))
            ui.quality_value.setValue(20);ui.encoder_preset.setCurrentIndex(ui.encoder_preset.findData('balanced'))
            from .project_range import set_range
            set_range(p.project,0,length,p.undo_stack)
            ui._update_range();ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
            QTest.mouseClick(ui.export_button,Qt.LeftButton)
            yield lambda:ui._last_job is not None
            yield lambda:not ui._running
            self.check('production video export succeeded '+name,ui.pages.currentWidget()==ui.success_page)
            self.check('video output exists '+name,Path(ui._last_job.output_path).is_file())
            self.result.setdefault('videos',[]).append(dict(kind=name,path=str(ui._last_job.output_path),
                ass=str(ui._last_job.ass_path),receipt=ui._last_job.completion_metadata))
            self.shot('video-complete-'+name)
            # Range edits belong to the real project and leave it dirty.
            # Return through the workspace action and save before navigation.
            ui._back();yield .2
            QTest.mouseClick(p.studio_save_button,Qt.LeftButton);yield .3

        def run(self):
            yield self.ready
            window.showNormal();window.resize(1280,820)
            p=self.page;p.volume_slider.setValue(0)
            yield from self.pause('initial-open')
            p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
            yield from self.seek_pixels('initial-two',2800,['initial-earlier','initial-later'])
            yield .3
            initial=self.record_positions('initial-two')
            self.check('first appearance at bottom',initial['initial-earlier'][1]>initial['initial-later'][1],initial)
            self.shot('01-initial-two')
            p.project.speakers.append(StudioSpeaker('layout-third','第三条布局夹具'))
            p.undo_stack.push(add_cue_command(p.project,StudioCue('initial-third',2200,4000,
                '第三位同时说话',speaker_id='layout-third'),p._changed))
            initialize_project_layout(p.project,cue_ids=['initial-third']);p._changed()
            yield from self.seek_pixels('initial-three',2800,['initial-earlier','initial-later','initial-third'])
            triple=self.record_positions('initial-third')
            self.check('adding third leaves first two anchors',all(triple[key]==value for key,value in initial.items()),triple)
            self.check('third allocated above existing',triple['initial-third'][1]<initial['initial-later'][1],triple)
            self.shot('02-initial-three')
            # Real pointer drag on the production measured selection overlay.
            p.select_cue('initial-earlier');p.position_edit_button.setChecked(True)
            yield lambda:p.position_overlay.isVisible() and not p.position_overlay._subtitle_rect().isEmpty()
            yield .2
            self.drag_y('initial-earlier',910);yield .25
            self.check('drag leaves later anchor unchanged',self.positions()['initial-later']==initial['initial-later'])
            self.edit_y('initial-later',1037);yield .3
            yield from self.seek_pixels('manual-swapped',2800,self.active_ids(2800))
            manual=self.record_positions('manual-swapped')
            self.check('manual order swapped',manual['initial-earlier'][1]<manual['initial-later'][1],manual)
            self.shot('03-manual-swapped')
            p.position_edit_button.setChecked(False)
            yield from self.play_for('generated',.65)
            self.record_positions('after-play',manual)
            for ms in (1800,2800,3600):
                yield from self.seek_pixels('scrub-'+str(ms),ms,self.active_ids(ms))
                self.record_positions('scrub-'+str(ms),manual)
            yield from self.seek_pixels('selection-time',2800,self.active_ids(2800))
            p.select_cue('initial-third');p.select_cue('initial-later');yield .2
            self.record_positions('selection-change',manual)
            p.style_font_size.setValue(p.style_font_size.value()+5);p._commit_style_now();yield .3
            self.record_positions('font-change',manual)
            for size in [(1120,760),(1440,900),(1280,820)]:
                window.resize(*size);yield .35;self.record_positions('resize-'+str(size),manual)
            yield from self.seek_pixels('resized-back',2800,self.active_ids(2800))
            self.shot('04-resized-back')
            QTest.mouseClick(p.studio_save_button,Qt.LeftButton);yield .3
            generated_path=Path(p.project_path);self.check('production save readback keeps manual anchors',
                {c.id:list(_anchor(resolve_cue_visual(load_project(generated_path),c).style,1920,1080)[:2])
                 for c in load_project(generated_path).cues}==manual)
            previous_project=p.project
            generated_reopen=output/'generated-reopened.2byteproj';generated_reopen.write_bytes(generated_path.read_bytes())
            window.open_studio_project(generated_reopen,mode='edit',source='persisted-layout-reopen')
            yield lambda:self.ready(generated_reopen);yield .3
            self.check('generated reopened as fresh project object',self.page.project is not previous_project)
            yield from self.pause('generated-reopen')
            self.record_positions('saved-reopen',manual)
            yield from self.seek_pixels('saved-reopen',2800,['initial-earlier','initial-later','initial-third'])
            self.shot('05-reopened')
            snapshot=export_project_snapshot(self.page.project)
            artifacts=export_subtitle_artifacts(snapshot,output/'generated-exports','初始布局人工交换',
                SubtitleExportOptions(frozenset({'ass','srt','json'}),'combined'))
            for item in artifacts:self.check('generated artifact readback '+item.format,verify_subtitle_artifact(item,snapshot).valid)
            if self.plan.get('video'):yield from self.export_video('generated-manual-swap',6000)
            # Now inspect the real project. Its text, times and acoustic records
            # remain the current project's data, independent of the fixture.
            self.phase='real-ge'
            real=output/'real-ge.2byteproj';window.open_studio_project(real,mode='edit',source='persisted-layout-real-ge')
            yield lambda:self.ready(real);yield .3
            yield from self.pause('real-ge-open')
            p=self.page;point=self.plan['real_point_ms'];real_ids=self.plan['real_ids']
            self.check('real current cue count',len(p.project.cues)==self.plan['real_cue_count'],len(p.project.cues))
            real_before=self.record_positions('real-open')
            yield from self.seek_pixels('real-before',point,self.active_ids(point))
            self.shot('06-real-before')
            key=real_ids[0];self.edit_y(key,max(80,round(real_before[key][1]-100)));yield .35
            real_manual=self.record_positions('real-manual')
            self.check('real single-cue scope',all(real_manual[k]==v for k,v in real_before.items() if k!=key))
            yield from self.seek_pixels('real-manual',point,self.active_ids(point))
            self.shot('07-real-after')
            yield from self.play_for('real',.5)
            self.record_positions('real-play',real_manual)
            yield from self.seek_pixels('real-before-save',point,self.active_ids(point))
            QTest.mouseClick(p.studio_save_button,Qt.LeftButton);yield .25
            previous_project=p.project
            real_reopen=output/'real-ge-reopened.2byteproj';real_reopen.write_bytes(real.read_bytes())
            window.open_studio_project(real_reopen,mode='edit',source='persisted-layout-real-ge-reopen')
            yield lambda:self.ready(real_reopen);yield .3
            self.check('real reopened as fresh project object',self.page.project is not previous_project)
            yield from self.pause('real-save-reopen')
            self.record_positions('real-save-reopen',real_manual)
            yield from self.seek_pixels('real-save-reopen',point,self.active_ids(point))
            final=export_project_snapshot(self.page.project)
            actual=[dict(id=c.id,text=c.text,start_ms=c.start_ms,end_ms=c.end_ms,speaker_id=c.speaker_id)
                    for c in self.page.project.cues]
            self.check('real text time identity preserved',actual==self.plan['real_expected'])
            artifacts=export_subtitle_artifacts(final,output/'real-exports','GE人工位置验收',
                SubtitleExportOptions(frozenset({'ass','srt','json'}),'combined'))
            for item in artifacts:self.check('real artifact readback '+item.format,verify_subtitle_artifact(item,final).valid)
            self.result['real_export_ass']=str(next(a.path for a in artifacts if a.format=='ass'))
            self.shot('08-real-reopened')
            if self.plan.get('video'):
                yield from self.export_video('real-GE-manual-layout',max(6000,point+1200))
                self.result['video_path']=self.result['videos'][-1]['path']
            self.check('real original project protected',all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value
                for path,value in self.plan['protected'].items()))

        def finish(self):
            from . import blank_project_audit
            self.result['provider_calls']=blank_project_audit._provider_calls
            self.timer.stop();window.result_exit_code=0 if self.result['passed'] else 1
            def write():(output/'layout-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            write()
            def stopped():self.result['gui_shutdown']=True;write()
            QApplication.instance().aboutToQuit.connect(stopped)
            self.page.video.set_paused(True);self.page.undo_stack.setClean();window.close()
    window._persisted_layout_audit=Audit()
