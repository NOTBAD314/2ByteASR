"""Real Qt/mpv/browser evidence for source and the same frozen entry point."""
from pathlib import Path
import time,json,traceback,statistics,os


def start_web_clock_acceptance(window, output: Path):
    from PySide6.QtCore import QObject,QTimer,Qt,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .build_identity import load_build_identity
    from .web_theme import builtin_web_themes
    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.result={'build':vars(load_build_identity()),'checks':{},'publishes':[],'operations':[]}
            gate=getattr(self.page,'_readiness',None)
            self.result['startup_profile']=dict(gate.profile) if gate is not None else {}
            self.result['checks']['startup_ready']=bool(gate is not None and gate.ready)
            self.start=time.monotonic();self.wait=0;self.sequence=self.run()
            self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(5)
        def tick(self):
            try:
                if time.monotonic()-self.start>150:raise TimeoutError('web clock audit deadline')
                if callable(self.wait):
                    if not self.wait():return
                elif time.monotonic()<self.wait:return
                value=next(self.sequence)
                self.wait=value if callable(value) else time.monotonic()+value
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
        def check(self,key,value):self.result['checks'][key]=bool(value)
        def run(self):
            page=self.page
            yield lambda: page.project is not None and page.video._startup_state=='READY'
            for track in page.project.video_tracks[1:]:track.enabled=False
            # Five seconds at each rate measures sustained presentation; the
            # original 1.7 s windows contained only about 65 native frames.
            # Keep the author HTML/CSS unchanged and extend only this cue span.
            phase_seconds=5.
            cue=page.project.cues[0];cue.start_ms=500;cue.end_ms=11500
            if os.environ.get('TWOBYTEASR_WEB_CLOCK_ORIGINAL')!='1':
                cue.text='跳过几个条件'
            self.result['continuous_sample_text']=cue.text
            theme=page.project.style_recipes.get(cue.style_id,{}).get('webTheme') or builtin_web_themes()['balatro-joker'].to_dict()
            page.cue_controller.model_changed();page.select_cue(cue.id)
            page._seek(1.7);yield .3
            original=page._publish_web_live_frame
            web_started=False
            def publish(*args,**kwargs):
                nonlocal web_started
                web_started=True
                t=time.perf_counter();posted=original(*args,**kwargs)
                if posted:
                    self.result['publishes'].append({'wall':time.perf_counter(),'ms':(time.perf_counter()-t)*1000,
                        'cue_ms':args[1],'owner':page.subtitle_visibility_trace()['foreground_owner']})
            page._publish_web_live_frame=publish
            native_events=[]
            record_applied=page.video.controller._record_visual_applied
            def recorded(target,visible):
                record_applied(target,visible)
                if web_started and target==1 and visible:native_events.append(time.perf_counter())
            page.video.controller._record_visual_applied=recorded
            # An imported theme can already be visible before these hooks.
            # Create a new consumer explicitly; a no-op apply must not be
            # mistaken for a missing frame when normal deduplication fires.
            page._stop_web_live_preview('audit-cold-start')
            t=time.perf_counter();page._apply_web_theme(cue.id,theme);page._seek(1.7)
            def current_ack(expected_cue=1200, since=None):
                since=t if since is None else since
                worker=page._web_live_worker
                if worker is None:return None
                records=list(page.video.web_publication_metrics)+list(page.video.web_initial_publication_metrics)
                fast=next((row for row in reversed(records)
                    if row.get('applied') and (row.get('applied_at') or 0)>=since
                    and row.get('web_worker_id')==id(worker)
                    and row.get('web_content_key')==worker.strip_key
                    and row.get('web_clock_generation')==page.video.playback_position_snapshot().playback_generation
                    and abs(row.get('web_cue_ms',-10000)-expected_cue)<2),None)
                if fast:return fast
                return None
            def first_frame():
                if current_ack():return True
                if time.perf_counter()-t>10:raise TimeoutError('new Web consumer did not acknowledge the requested frame')
                return False
            yield first_frame
            self.result['cold_first_ms']=(current_ack()['applied_at']-t)*1000
            self.result['first_frame_ack']=current_ack()
            self.result['cold_measurement']='new consumer/page, shared browser already initialized'
            yield .25
            self.check('web-owner-paused',page.subtitle_visibility_trace()['foreground_owner']=='advanced_live')
            page.video.controller.screenshot_to_file(output/'web-native-paused.png')
            window.grab().save(str(output/'web-studio-paused.png'))
            # No capture calls during throughput windows: native screenshot
            # synchronization itself changes scheduling and cannot measure FPS.
            self.result['rates']=[]
            for rate in (1.,2.):
                page.video.set_paused(True);page._seek(.6);yield .2
                page._set_speed(rate)
                before=len(self.result['publishes'])
                t=time.perf_counter();page.video.set_paused(False)
                yield phase_seconds
                end=time.perf_counter()
                page.video.set_paused(True)
                frames=self.result['publishes'][before:]
                intervals=[(b['wall']-a['wall'])*1000 for a,b in zip(frames,frames[1:])]
                self.result['rates'].append({'rate':rate,'frames':len(frames),
                    'first_ms':(frames[0]['wall']-t)*1000 if frames else None,
                    'p95_ms':statistics.quantiles(intervals,n=100)[94] if len(intervals)>1 else None,
                    'max_ms':max(intervals,default=0)})
                # Time identities remain valid when the bounded deque wraps.
                applied=[x for x in list(page.video.web_publication_metrics)
                    if x['applied'] and x.get('applied_at') and t<=x['applied_at']<=end]
                self.result['rates'][-1].update(start_perf=t,end_perf=end,
                    wall_seconds=end-t,native_frames=applied,
                    worker_metrics=list(page._web_live_worker.metrics))
                gaps=[(b['applied_at']-a['applied_at'])*1000 for a,b in zip(applied,applied[1:])]
                self.result['rates'][-1]['native_applied']={'frames':len(applied),
                    'fps':(len(applied)-1)/(applied[-1]['applied_at']-applied[0]['applied_at']) if len(applied)>1 else 0,
                    'p95_ms':statistics.quantiles(gaps,n=100)[94] if len(gaps)>1 else None,
                    'max_ms':max(gaps,default=0)}
                self.check(f'frames-{rate}',len(frames)>=30)
                native=self.result['rates'][-1]['native_applied']
                self.check(f'native-cadence-{rate}',native['fps']>=29
                    and native['p95_ms'] is not None and native['p95_ms']<=40
                    and native['max_ms']<=250)
            page._set_speed(1.)
            for i in range(30):
                page.video.set_paused(True)
                before=len(self.result['publishes']);t=time.perf_counter()
                profiler=None
                if i==5 and os.environ.get('TWOBYTEASR_PROFILE_WEB_EDIT')=='1':
                    import cProfile
                    profiler=cProfile.Profile();profiler.enable()
                if i%5==0:
                    cue.text='第'+str(i)+'次换字与时长';cue.end_ms=5200+(i%2)*300
                    page.cue_controller.model_changed();page._schedule_advanced_preview(page.project.style_recipes[cue.style_id],force=True)
                target=.7+(i*137%3200)/1000
                prepared_at=time.perf_counter()
                page._seek(target)
                seek_returned_at=time.perf_counter()
                if profiler is not None:
                    profiler.disable();profiler.dump_stats(str(output/'edit-profile.pstats'))
                def operation_ready():
                    if current_ack(target*1000-cue.start_ms,t):return True
                    if time.perf_counter()-t>3:raise TimeoutError(f'operation {i} received no current native target frame')
                    return False
                yield operation_ready
                ack=current_ack(target*1000-cue.start_ms,t)
                self.result['operations'].append({'index':i,'response_ms':(ack['applied_at']-t)*1000,
                    'prepare_ms':(prepared_at-t)*1000,'seek_call_ms':(seek_returned_at-prepared_at)*1000,
                    'native_ack':ack,
                    'owner':page.subtitle_visibility_trace()['foreground_owner']})
                if i%5==0:page.video.controller.screenshot_to_file(output/f'web-operation-{i}.png')
                yield .015
            self.check('thirty-operations-native-targets',len(self.result['operations'])==30)
            self.check('warm-native-change-200ms',max(x['response_ms'] for x in self.result['operations'])<=200)
            worker=page._web_live_worker
            self.result['worker_metrics']=list(worker.metrics)
            self.result['native_publication_metrics']=list(page.video.web_publication_metrics)
            observed_metrics={ (x['wall'],x['phase']):x for rate in self.result['rates']
                for x in rate['worker_metrics'] }
            observed_metrics.update({(x['wall'],x['phase']):x for x in worker.metrics})
            self.check('same-page-cue-swaps',sum(x['phase']=='page_load' for x in observed_metrics.values())==1)
            self.check('no-runtime-errors',not any(x['phase']=='error' for x in worker.metrics))
            # A live HTML cue keeps its real page during a timeline resize.
            page._seek(2.);yield .2
            tl=page.timeline;tl.set_visible_window(0,6000);tl.snap_enabled=False
            cue=page.project.cues[0]
            origin=QPointF(tl._time_to_x(cue.end_ms),tl._track_layout()[0][cue.speaker_id].center().y())
            def mouse(kind,point):
                QApplication.sendEvent(tl,QMouseEvent(kind,point,QPointF(tl.mapToGlobal(point.toPoint())),
                    Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
            mouse(QEvent.Type.MouseButtonPress,origin);yield .08
            target=QPointF(tl._time_to_x(1500),origin.y())
            mouse(QEvent.Type.MouseMove,target);yield .15
            self.check('web-timing-hides-at-temporary-boundary',page.subtitle_visibility_trace()['foreground_owner']=='none')
            QTest.keyClick(tl,Qt.Key.Key_Escape);yield .3
            self.check('web-timing-cancel-restores-owner',page.subtitle_visibility_trace()['foreground_owner']=='advanced_live')
            mouse(QEvent.Type.MouseButtonPress,origin);yield .08
            target=QPointF(tl._time_to_x(4500),origin.y())
            mouse(QEvent.Type.MouseMove,target);yield .15
            self.check('web-timing-retains-page',page._web_live_worker is worker and worker._strip_span_ms==4000.)
            QTest.keyClick(tl,Qt.Key.Key_Escape);yield .2
            for track in page.project.video_tracks[1:]:track.enabled=True
            page._sync_video_compositor(page.timeline.playhead_ms);yield .3
            page.video.controller.screenshot_to_file(output/'web-with-4by3-native.png')
            self.result['geometry']={'video_widget':page.video.rect().getRect(),
                'browser_viewport':[worker._width,worker._height],
                'composition':page.video_compositor.geometry().getRect(),
                'theme_canvas':page.advanced_cue_overlay.geometry().getRect()}
            self.check('multi-track-owner',page.subtitle_visibility_trace()['foreground_owner']=='advanced_live')
        def finish(self):
            self.timer.stop()
            worker=self.page._web_live_worker
            self.result['worker_metrics_at_finish']=list(worker.metrics) if worker else []
            self.result['native_publication_metrics']=list(self.page.video.web_publication_metrics)
            self.result['native_initial_publication_metrics']=list(self.page.video.web_initial_publication_metrics)
            self.result['checks']['close_cleanup_completed']=False
            (output/'web-clock-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf-8')
            self.page.undo_stack.setClean()
            self.page.close_ready_signal.connect(self.closed)
            window.close()
        def closed(self,profile):
            self.result['close_profile']=dict(profile)
            self.result['checks']['close_cleanup_completed']=bool(self.page._close_complete)
            self.result['checks']['close_audio_idle']=profile.get('audio_idle') is True
            (output/'web-clock-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf-8')
    window._acceptance_audit=Audit()
