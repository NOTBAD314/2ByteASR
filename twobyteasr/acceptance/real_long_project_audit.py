"""Opt-in real-project loading, cache, seek and identity acceptance.

Normal MainWindow, real mpv and production commands. Only the runner's copied
project/profile may be written. Timings are GUI Paint/observed player timings,
not claims about physical display scanout or physical keyboard/audio devices.
"""
from __future__ import annotations

from collections import deque
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication


def start(window, output):
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..studio.loading_faces import ReadinessSteps

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.phase='initial';self.page=None;self.started=time.perf_counter();self.last=self.started
            self.pending=0;self.error='';self.operation=None;self.paints=[];self.heartbeats=[];self.operations=[]
            self.checks={};self.loads=[];self.seek_rows=[];self.resources=[];self.recorder=None
            self.frames={};self.closed=False;self.record_log=None
            self.project_path=Path(os.environ['REAL_LONG_PROJECT']).resolve()
            self.result=dict(pid=os.getpid(),hwnd=int(window.winId()),frozen=bool(getattr(__import__('sys'),'frozen',False)),
                             build=str(load_build_identity()),input=str(self.project_path))
            self._profile_count={};self._profile_lock=threading.Lock()
            if os.environ.get('REAL_LONG_RENDER_PROFILE')=='1':
                self.install_render_profiler()
            self.stack_samples=[];self.sampler_stop=threading.Event()
            if os.environ.get('REAL_LONG_PROFILE')=='1':
                main_id=threading.get_ident()
                def sample():
                    while not self.sampler_stop.wait(.02):
                        frame=sys._current_frames().get(main_id);frames=[]
                        while frame is not None and len(frames)<35:
                            frames.append([frame.f_code.co_filename,frame.f_lineno,frame.f_code.co_name]);frame=frame.f_back
                        self.stack_samples.append(dict(at=time.perf_counter(),phase=self.phase,frames=frames))
                threading.Thread(target=sample,name='audit-stack-sampler',daemon=True).start()
            self.write_progress()
            QApplication.instance().installEventFilter(self)
            self.sequence=self.run()
            self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer);self.timer.setInterval(10)
            self.timer.timeout.connect(self.tick);self.timer.start()
            window.destroyed.connect(self.shutdown)

        def write_progress(self):
            (output/'result.json').write_text(json.dumps(dict(self.result,phase=self.phase),ensure_ascii=False,indent=2),'utf8')

        def install_render_profiler(self):
            """Diagnostic run only; normal latency/recording runs do not profile."""
            import cProfile,pstats,functools
            from ..caption_style import visual_snapshot
            from ..rendering.caption_scene import SceneRasterizer
            def wrap(original,kind,select):
                @functools.wraps(original)
                def measured(*args,**kwargs):
                    wanted=set(getattr(self,'complex_ids',()))
                    if not wanted or not select(args,wanted):return original(*args,**kwargs)
                    with self._profile_lock:
                        count=self._profile_count.get(kind,0)
                        selected=count<6
                        if selected:self._profile_count[kind]=count+1
                    if not selected:return original(*args,**kwargs)
                    profile=cProfile.Profile()
                    result=profile.runcall(original,*args,**kwargs)
                    target=output/f'{kind}-profile-{count+1}'
                    profile.dump_stats(str(target.with_suffix('.pstats')))
                    rows=[dict(file=key[0],line=key[1],function=key[2],calls=value[1],
                        self_ms=value[2]*1000,total_ms=value[3]*1000) for key,value in pstats.Stats(profile).stats.items()]
                    target.with_suffix('.json').write_text(json.dumps(sorted(rows,key=lambda x:x['total_ms'],reverse=True),indent=2),'utf8')
                    return result
                return measured
            visual_snapshot.build_visual_cue_snapshot=wrap(visual_snapshot.build_visual_cue_snapshot,'preparation',
                lambda args,ids:str(args[1]).split('#tr')[0] in ids)
            SceneRasterizer.frame=wrap(SceneRasterizer.frame,'raster',
                lambda args,ids:any(str(key).split('#tr')[0] in ids for key,_ in args[1]))

        def check(self,name,value):
            self.checks[name]=bool(value)
            if not value:raise AssertionError(name)

        def set_phase(self,name):
            self.phase=name;self.write_progress();print('REAL_LONG_PHASE',name,flush=True)

        def eventFilter(self,obj,event):
            if event.type()==QEvent.Paint:
                now=time.perf_counter()
                if isinstance(obj,ReadinessSteps) and obj.isVisible():
                    session=window.__dict__.get('_studio_loading_session')
                    identity=(id(obj),session.generation if session else 0)
                    previous=self.frames.get(identity);self.frames[identity]=now
                    card=session.view.card if session is not None else obj
                    point=card.mapToGlobal(card.rect().topLeft())
                    self.paints.append(dict(at=now,phase=self.phase,kind='loading',
                        gap_ms=(now-previous)*1000 if previous else None,
                        current=obj.current,completed=sorted(obj.completed),
                        geometry=[point.x(),point.y(),card.width(),card.height()],
                        surface=[session.view.width(),session.view.height()] if session else [],
                        generation=session.generation if session else 0))
                elif self.page is not None and obj is self.page.timeline:
                    self.paints.append(dict(at=now,phase=self.phase,kind='timeline'))
                    if self.operation is not None:
                        self.operation.setdefault('paint_ms',(now-self.operation['at'])*1000)
                        self.operation=None
            return False

        def tick(self):
            now=time.perf_counter()
            self.heartbeats.append(dict(phase=self.phase,at=now,gap_ms=(now-self.last)*1000));self.last=now
            try:
                if now-self.started>660:raise TimeoutError('real long audit exceeded 660 seconds')
                if callable(self.pending):
                    if not self.pending():return
                elif now<self.pending:return
                value=next(self.sequence)
                self.pending=value if callable(value) else time.perf_counter()+float(value or 0)
            except StopIteration:self.finish()
            except Exception:self.error=traceback.format_exc();self.finish()

        def wait(self,condition,label,seconds=60):
            deadline=time.perf_counter()+seconds
            def ready():
                if condition():return True
                if time.perf_counter()>deadline:raise TimeoutError(label)
                return False
            return ready

        def action(self,name,callback,**fields):
            row=dict(name=name,phase=self.phase,at=time.perf_counter(),**fields)
            result=callback();row['handler_ms']=(time.perf_counter()-row['at'])*1000
            self.operations.append(row);self.operation=row
            return result

        def ready(self):
            page=window.built_page('studio');session=window.__dict__.get('_studio_loading_session')
            if page is None:return False
            gate=page._readiness
            if getattr(gate,'failure_reason',''):raise RuntimeError(gate.failure_reason)
            return bool(page.project is not None and gate.ready and session and session.state=='ready' and not session.active)

        def cache(self):
            page=self.page;scene=getattr(page,'_caption_scene',None);cache=getattr(page,'_caption_playback_cache',None)
            return dict(scene=scene.trace() if scene else {},
                        preparation=cache.stats() if cache is not None and hasattr(cache,'stats') else {},
                        scene_metrics=list(scene.metrics) if scene else [])

        def seek_ready(self,target):
            p=self.page;v=p.video;clock=v._playback_clock
            preparing=getattr(p,'_caption_seek_preparation',None)
            if preparing is not None and preparing.pending is not None:return False
            if clock.exact_seek_pending:return False
            if abs(p.timeline.playhead_ms-target)>250:return False
            from ..rendering.caption_scene import active_cues
            cues=active_cues(p,p._caption_sample_ms());scene=getattr(p,'_caption_scene',None)
            if scene is not None and scene.active and cues:
                if scene.token is None or not scene.still_current(scene.token):return False
                trace=scene.trace()
                if set(trace['expected_cue_ids'])!=set(c.id for c in cues):return False
                if not trace['cue_pixels'] or any(row['status']=='pending' for row in trace['cue_pixels']):return False
            from ..studio.studio_readiness import player_surface_ready
            return player_surface_ready(p)

        def seek(self,target,label):
            p=self.page;p.video.set_paused(True)
            began=time.perf_counter();self.action(label,lambda:p._seek(target/1000),target_ms=target)
            yield self.wait(lambda:self.seek_ready(target),label+' presentation',20)
            if os.environ.get('REAL_LONG_BASELINE')!='1':
                def scene_receipt_ready():
                    traces=p.video.seek_latency_traces()
                    return bool(traces and traces[-1].get('T8_passed') is True)
                yield self.wait(scene_receipt_ready,label+' visual owner receipt',4)
            self.seek_rows.append(dict(label=label,target_ms=target,presented_ms=p.timeline.playhead_ms,
                complete_ms=(time.perf_counter()-began)*1000,
                generation=p.video._playback_clock.generation,
                frame_witness=p.video.controller.observed_frame(),
                presentation_requests=list(getattr(getattr(p,'_caption_seek_preparation',None),'samples',()))[-1:],
                trace=p.video.seek_latency_traces()[-1:] if hasattr(p.video,'seek_latency_traces') else [],
                cache=self.cache()))

        def record(self):
            if os.environ.get('REAL_LONG_RECORD')!='1':return
            from ..system.platform_media import ffmpeg_tool
            from ..system.processes import popen_hidden_subprocess
            ffmpeg=ffmpeg_tool()
            command=[str(ffmpeg),'-v','warning','-y','-f','lavfi','-i',
                f'gfxcapture=hwnd={int(window.winId())}:max_framerate=60:capture_cursor=0',
                '-c:v','h264_nvenc','-preset','p1','-cq','20','-movflags','frag_keyframe+empty_moov+default_base_moof',
                str(output/'real-long-project.mp4')]
            self.record_log=(output/'capture.log').open('wb')
            self.recorder=popen_hidden_subprocess(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
                stderr=self.record_log,purpose='real long project continuous window recording')
            self.result['recording']=dict(pid=self.recorder.pid,command=command)

        def apply_styles(self):
            from ..projects.studio_project import SubtitleStyle
            from ..timeline.studio_commands import SetCuePresentationCommand
            p=self.page
            choices=[p.project.cues[index] for index in (3040,3041,3042)]
            self.complex_ids=[c.id for c in choices]
            for i,cue in enumerate(choices):
                key='acceptance-style-'+str(i)
                style=SubtitleStyle(key,key,font_family='Source Han Sans SC Heavy' if i!=1 else 'Source Han Sans SC Medium',
                    font_size=56+i*4,outline_width=4+i,shadow=3+i,bold=i!=1,
                    outline2_width=2,outline2_color='#804060')
                recipes=copy.deepcopy(p.project.style_recipes)
                recipes[key]={'name':key,'engine':'remotion','typography':{'fontFamily':style.font_family,'fontSize':style.font_size},
                    'effects':{'glow':{'enabled':True,'color':'#F78CC7','radius':10,'strength':.8}}}
                changes={'style_id':key,'base_preset_id':key}
                if i==2 and 'word_pulse' in p.project.effects:changes['effect_id']='word_pulse'
                command=SetCuePresentationCommand(p.project,cue.id,cue_changes=changes,
                    styles=[*p.project.styles,style],style_recipes=recipes,text='真实副本的复杂样式验收',changed=p._changed)
                p.undo_stack.push(command)
            self.result['complex_styles']='Three existing cues in a copied real project; not claimed to be saved in the original.'

        def run(self):
            if os.environ.get('REAL_LONG_MAXIMIZED')=='1':window.showMaximized()
            else:window.resize(1440,900)
            from ..design.theme_manager import apply_application_theme
            apply_application_theme(QApplication.instance(),'grape')
            yield .4
            if os.environ.get('REAL_LONG_FOREGROUND_GATE')=='1':
                self.set_phase('awaiting-foreground')
                yield self.wait(lambda:(output/'foreground-ready').exists(),'foreground observation',180)
            self.record();yield .5
            for name in ('cold-open','hot-open'):
                self.set_phase(name);began=time.perf_counter()
                self.action(name,lambda:window.open_studio_project(str(self.project_path)))
                yield self.wait(self.ready,name,100)
                self.page=p=window.built_page('studio')
                p.video.set_paused(True);p.volume_slider.setValue(0)
                session=window._studio_loading_session
                self.loads.append(dict(name=name,total_ms=(time.perf_counter()-began)*1000,
                    session=session.snapshot(),profile=copy.deepcopy(p._readiness.profile)))
                self.check(name+'-real-cues',len(p.project.cues)==6962)
                if not os.environ.get('REAL_LONG_BASELINE'):
                    events=session.snapshot()['events']
                    terminal=[e for e in events if e['event']=='completion_animation_finished']
                    self.check(name+'-complete-progress-before-reveal',
                        bool(terminal) and terminal[-1].get('progress_shown')==1.)
                _capture(window,output/(name+'.png'))
                yield .4
                if name=='cold-open':
                    p.undo_stack.setClean();p.show_project_hub(skip_dirty_guard=True);yield .4
            self.original_text=[(c.id,c.text,c.original_text,c.start_ms,c.end_ms,c.speaker_id) for c in p.project.cues]
            if os.environ.get('REAL_LONG_LOADING_ONLY')=='1':
                self.set_phase('done')
                return
            self.original_translations=dict(p.project.generation_metadata.get('translations',{}))
            self.result['project']=dict(cues=len(p.project.cues),translations=len(self.original_translations),
                speakers=[s.id for s in p.project.speakers],duration_ms=p.project.media.duration_ms,
                video_tracks=len(p.project.video_tracks),audio_tracks=len(p.project.audio_tracks),dpr=window.devicePixelRatioF())
            self.set_phase('overview-expand')
            p.workspace_splitter.setSizes([350,520])
            t=p.timeline;t.set_visible_window(0,p.project.media.duration_ms);yield .3
            for expanded in (True,False,True):
                self.action('expand' if expanded else 'collapse',lambda v=expanded:t.set_group_expanded(v))
                yield .2
            self.result['overview_paint_stats']=dict(getattr(t,'_last_paint_stats',{}))
            _capture(window,output/'all-tracks.png')
            self.set_phase('complex-style-setup');self.apply_styles();yield .6
            cue=next(c for c in p.project.cues if c.id==self.complex_ids[0]);target=cue.start_ms+min(500,(cue.end_ms-cue.start_ms)//2)
            self.set_phase('complex-cold');yield from self.seek(target,'complex-cold')
            _capture(window,output/'complex-subtitles-active.png')
            self.set_phase('complex-replay')
            for i in range(2):
                yield from self.seek(target,'complex-repeat-'+str(i))
                p.video.set_paused(False);yield 3;p.video.set_paused(True);yield .2
            _capture(window,output/'complex-subtitles.png')
            if hasattr(getattr(p,'_caption_scene',None),'warm_completed'):
                from ..studio.caption_range_preparation import start_range_preparation
                self.set_phase('range-preparation')
                end=next(c.end_ms for c in p.project.cues if c.id==self.complex_ids[-1])
                task=start_range_preparation(p,cue.start_ms,end)
                yield self.wait(lambda:not task.active,'range preparation',60)
                self.result['range_preparation']=task.snapshot()
                self.check('range-preparation-complete',task.index==len(task.times))
            self.set_phase('one-cue-edit')
            another=p.project.cues[50];old=another.text
            self.action('one-cue-edit',lambda:p.cue_controller.set_text(another.id,old+' [验收]'))
            yield .3
            yield from self.seek(target,'unaffected-complex-after-edit')
            p.undo_stack.undo();yield .3
            self.check('one-cue-undo',p.session.runtime.cue_by_id[another.id].text==old)
            self.set_phase('thirty-mixed-operations')
            background=None
            if hasattr(getattr(p,'_caption_scene',None),'warm_completed'):
                from ..studio.caption_range_preparation import start_range_preparation
                background=start_range_preparation(p,cue.start_ms,min(p.project.media.duration_ms,cue.start_ms+300000))
            targets=[1000,p.project.media.duration_ms//2,p.project.media.duration_ms-8000,5368430,6182049,9211325,target]
            for i in range(30):
                if i==2:
                    self.action('background-autosave-edit',lambda:p.cue_controller.set_text(another.id,old+' [后台验收]'))
                if i==22:
                    p.undo_stack.undo()
                    self.check('background-edit-restored',p.session.runtime.cue_by_id[another.id].text==old)
                if i%3==0:
                    t.set_group_expanded(i%2==0)
                    self.action('overview-zoom',lambda i=i:t.set_visible_window(0,p.project.media.duration_ms if i%2 else 120000))
                    yield .08
                at=targets[i%len(targets)]
                yield from self.seek(at,'mixed-'+str(i+1))
                if i%5==0:
                    p.video.set_paused(False);yield .5;p.video.set_paused(True)
                if i%6==0:
                    # Query the actual Qt accessibility table while identities
                    # and target selection are changing, as in the native stack.
                    interface=QAccessible.queryAccessibleInterface(p.cue_table)
                    if interface and interface.childCount():
                        cell=interface.child(min(interface.childCount()-1,3041*5+3))
                        if cell:cell.state();cell.rect()
                yield .08
            if background is not None:
                self.result['background_preparation']=background.snapshot();background.cancel()
            self.check('thirty-seeks-complete',len([r for r in self.seek_rows if r['label'].startswith('mixed-')])==30)
            self.set_phase('rapid-latest-target')
            for at in (1000,18000000,300000,9211325):p._seek(at/1000,accurate=False)
            p._seek(9211325/1000,accurate=True)
            yield self.wait(lambda:self.seek_ready(9211325),'latest drag target',20)
            self.check('latest-target-wins',abs(p.timeline.playhead_ms-9211325)<250)
            self.set_phase('single-speaker')
            from ..projects.single_speaker import confirm_single_speaker_command
            before=[(c.id,c.text,c.start_ms,c.end_ms,c.style_id,copy.deepcopy(c.appearance_override)) for c in p.project.cues]
            old_speakers=[c.speaker_id for c in p.project.cues]
            command=self.action('confirm-single',lambda:confirm_single_speaker_command(p.project,changed=p._speaker_structure_changed))
            p.undo_stack.push(command);yield .4
            self.check('single-confirmed',not command.error and len(p.project.speakers)==1)
            self.check('single-preserves-content-and-style',before==[(c.id,c.text,c.start_ms,c.end_ms,c.style_id,c.appearance_override) for c in p.project.cues])
            self.check('single-preserves-translations',p.project.generation_metadata['translations']==self.original_translations)
            p.undo_stack.undo();yield .3
            self.check('single-undo-restores-identities',[c.speaker_id for c in p.project.cues]==old_speakers)
            p.undo_stack.redo();yield .3
            self.set_phase('save-reopen')
            self.action('save-confirmed-copy',p.save);yield .5
            self.result['saved_copy']=str(p.project_path)
            p.undo_stack.setClean();p._close_project_session('real-long-audit-reopen');p.open_project(self.project_path)
            yield self.wait(self.ready,'saved single speaker reopen',100)
            self.check('single-persisted',len(p.project.speakers)==1)
            self.check('translations-persisted',p.project.generation_metadata['translations']==self.original_translations)
            yield from self.seek(9211325,'reopened-jump')
            _capture(window,output/'single-reopened.png')
            self.result['final_cache']=self.cache()
            self.set_phase('cancel-and-reopen')
            p.undo_stack.setClean();p.show_project_hub(skip_dirty_guard=True);yield .2
            window.open_studio_project(str(self.project_path))
            session=window._studio_loading_session;cancelled=session.generation
            session.request_cancel();yield .3
            self.check('cancel-rejects-old-delivery',not session.deliver(cancelled))
            window.open_studio_project(str(self.project_path))
            yield self.wait(self.ready,'reopen after cancellation',80)
            self.check('cancel-reopen-keeps-project',str(p.project_path)==str(self.project_path) and len(p.project.cues)==6962)
            self.set_phase('steady-paused');yield 8
            if os.environ.get('REAL_LONG_HOLD')=='1':
                self.set_phase('manual-inspection')
                yield self.wait(lambda:(output/'release-manual').exists(),'manual inspection',240)
            self.check('no-python-failure',not self.error)
            self.set_phase('done');yield .3

        def finish(self):
            if self.closed:return
            self.closed=True;self.timer.stop()
            self.sampler_stop.set()
            if self.stack_samples:
                (output/'main-thread-stacks.json').write_text(json.dumps(self.stack_samples),'utf8')
            QApplication.instance().removeEventFilter(self)
            if self.page is not None:
                self.page.video.set_paused(True);self.page.undo_stack.setClean()
            self.result.update(passed=not self.error,error=self.error,checks=self.checks,loads=self.loads,
                paints=self.paints,heartbeats=self.heartbeats,operations=self.operations,seeks=self.seek_rows,
                elapsed_ms=(time.perf_counter()-self.started)*1000)
            loader=getattr(window,'_studio_module_preloader',None)
            if loader is not None:self.result['module_preload']=list(loader.timings)
            (output/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')
            if self.recorder is not None:
                try:self.recorder.stdin.write(b'q\n');self.recorder.stdin.flush()
                except (BrokenPipeError,OSError):pass
            QTimer.singleShot(300,window.close)

        def shutdown(self):
            (output/'gui-closed').touch()

    window._real_long_project_audit=Audit()
