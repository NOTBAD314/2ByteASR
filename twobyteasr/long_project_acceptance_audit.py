"""Headed long-source audit; invoked only by the guarded tmp acceptance entry."""
from __future__ import annotations
import json
import os
import time
import traceback
import threading
from collections import defaultdict
from pathlib import Path


def distribution(values):
    values=sorted(values)
    return {'n':len(values),'p50':values[len(values)//2] if values else None,
        'p95':values[min(len(values)-1,int(len(values)*.95))] if values else None,
        'max':max(values) if values else None}


def mpv_timecode_ms(value, fps=60):
    """Decode mpv's estimated SMPTE label, including dropped frame numbers.

    This is a frame-info estimate, not a decoded PTS. Keep that distinction in
    evidence; the long fixture is 60fps and mpv emits semicolon labels.
    """
    import re
    h,m,s,f=map(int,re.split('[:;]',value))
    count=((h*60+m)*60+s)*fps+f
    if ';' in value:
        minutes=h*60+m
        count-=round(fps*.0666666667)*(minutes-minutes//10)
    return count*1000/fps


def start_long_project_acceptance(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt, QPoint, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent, QWheelEvent, QCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import psutil
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page
            self.phase='settle';self.rows=[];self.operations=[];self.paints=[];self.events=[];self.seeks=[]
            self.frames=[];self.publications=[];self.connected=set();self.resources=[];self.resource_stop=threading.Event()
            self.pending=0;self.last=time.perf_counter();self.phase_start=self.last
            self.started=self.last;self.process=psutil.Process();self.process.cpu_percent()
            self.phase_windows={'settle':[self.started,None]}
            self.result={'checks':{},'summary':{},'build':str(load_build_identity()),'real_user_click':False}
            self.page.timeline.installEventFilter(self)
            original=self.page.timeline._paint_timeline
            def paint(event):
                start=time.perf_counter();original(event)
                self.paints.append({'phase':self.phase,'at':start,'ms':(time.perf_counter()-start)*1000,
                    'visible_cues':len(self.page.timeline.visible_cues()),
                    'contents':dict(getattr(self.page.timeline,'_last_paint_stats',{})),
                    'timing_redraw_items':dict(getattr(self.page.timeline,'_paint_item_counts',{})),
                    'envelope_hits':getattr(self.page.timeline,'_paint_envelope_hits',0),
                    'envelope_misses':getattr(self.page.timeline,'_paint_envelope_misses',0),
                    'waveform_tiles':{str(id(c)):dict(c.stats) for c in self.page.timeline.waveform_caches.values()}})
            self.page.timeline._paint_timeline=paint
            seek=self.page.video.seek
            def measured_seek(*args,**kwargs):
                start=time.perf_counter();result=seek(*args,**kwargs)
                self.seeks.append({'phase':self.phase,'at':start,'ms':(time.perf_counter()-start)*1000,
                    'args':args,'kwargs':kwargs})
                return result
            self.page.video.seek=measured_seek
            publish=self.page.video.publish_compositor_overlay
            def published(slot,*args,**kwargs):
                active_clips={layer['clip_id'] for layer in self.page.video_compositor._layers}
                kwargs['context'] = {**kwargs.get('context',{}), 'audit_phase':self.phase,
                    'followers':{key:dict(pts=p.pts_ms,requested=p.requested_ms,generation=p.generation,
                        epoch=p._epoch) for key,p in self.page.video_compositor._players.items() if key in active_clips and not p._suspended}}
                result=publish(slot,*args,**kwargs)
                if slot==0:self.publications.append({'phase':self.phase,'at':time.perf_counter(),
                    'pts':{key:p.pts_ms for key,p in self.page.video_compositor._players.items() if not p._suspended}})
                return result
            self.page.video.publish_compositor_overlay=published
            threading.Thread(target=self.resources_loop,name='audit-resources',daemon=True).start()
            self.sequence=self.run()
            self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(10)

        def resources_loop(self):
            from .processes import run_hidden_subprocess
            processes={}
            while not self.resource_stop.wait(1):
                row={'phase':self.phase,'at':time.perf_counter(),'cpu':[]}
                try:
                    for proc in [self.process,*self.process.children(recursive=True)]:
                        tracked=processes.setdefault(proc.pid,proc)
                        row['cpu'].append({'pid':proc.pid,'name':tracked.name(),'percent':tracked.cpu_percent(),
                            'rss':tracked.memory_info().rss})
                    gpu=run_hidden_subprocess(['nvidia-smi','--query-gpu=utilization.gpu,utilization.decoder,memory.used',
                        '--format=csv,noheader,nounits'],purpose='read-only audit GPU telemetry',timeout=2,capture_output=True)
                    row['gpu']=gpu.stdout.decode(errors='replace').strip()
                except Exception as exc:row['error']=str(exc)
                self.resources.append(row)
                # psutil recursively enumerates Windows processes and can take
                # hundreds of milliseconds. The telemetry thread already owns
                # that work; never repeat it on the Qt presentation thread.
                (output/'progress.json').write_text(json.dumps({'phase':self.phase,
                    'seconds':time.perf_counter()-self.started,
                    'cpu_percent':next((p['percent'] for p in row.get('cpu',[]) if p['pid']==self.process.pid),None),
                    'children':max(0,len(row.get('cpu',[]))-1),
                    'child_names':[p['name'] for p in row.get('cpu',[]) if p['pid']!=self.process.pid]}),encoding='utf8')

        def eventFilter(self, watched, event):
            if event.type() in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonRelease,QEvent.Type.Wheel):
                self.events.append({'phase':self.phase,'at':time.perf_counter(),'type':int(event.type())})
            return False

        def tick(self):
            now=time.perf_counter();page=self.page
            for key,source in page.video_compositor._players.items():
                if id(source) not in self.connected:
                    self.connected.add(id(source))
                    def received(key=key,source=source):
                        self.frames.append({'phase':self.phase,'clip_id':key,'at':time.perf_counter(),
                            'pts':source.pts_ms,'requested':source.requested_ms,'generation':source.generation,
                            'epoch':source._epoch,'presentation_ms':page.video.visual_position()*1000})
                    source.frame_updated.connect(received)
            self.rows.append({'phase':self.phase,'at':now,'gap_ms':(now-self.last)*1000,
                'presentation_ms':page.video.visual_position()*1000,
                'followers':{k:v.performance_snapshot() for k,v in page.video_compositor._players.items()}
                if len(self.rows)%100==0 else None})
            self.last=now
            try:
                if now-self.started>max(580,float(os.environ.get('TWOBYTEASR_LONG_SECONDS','300'))+220):
                    raise TimeoutError('long-project audit timeout')
                if callable(self.pending):
                    if not self.pending():return
                elif now<self.pending:return
                value=next(self.sequence)
                self.pending=value if callable(value) else time.perf_counter()+value
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()

        def set_phase(self,name):
            self.phase_windows[self.phase][1]=time.perf_counter()
            self.phase=name;self.phase_start=time.perf_counter()
            self.phase_windows[name]=[self.phase_start,None]
            print('LONG_PHASE',name,flush=True)

        def mouse(self, kind, x, y, button, buttons, modifier=Qt.KeyboardModifier.NoModifier):
            widget=self.page.timeline;point=QPointF(x,y)
            global_point=widget.mapToGlobal(point.toPoint());QCursor.setPos(global_point)
            QApplication.sendEvent(widget,QMouseEvent(kind,point,QPointF(global_point),button,buttons,modifier))

        def target_gate(self,target_ms,started,label,timeout=3.):
            page=self.page
            expected_generation=page.video._playback_clock.generation
            result={'phase':label,'target_ms':target_ms,'first_ms':{},'strict_tolerance_ms':34}
            expected=page._multitrack_preview_layers(target_ms)
            def ready():
                now=time.perf_counter()
                details={}
                traces=page.video.seek_latency_traces()
                trace=traces[-1] if traces else {}
                for layer in expected:
                    key=layer['key']
                    if layer.get('primary_media'):
                        info=page.video.controller.observed_property('video-frame-info',{}) or {}
                        accepted=page.video.controller.applied_seek_state()
                        target=trace.get('decoder_target_seconds',target_ms/1000)*1000
                        pts=float(info.get('pts',-100))*1000
                        signal='video-frame-info/pts'
                        if pts<0 and info.get('estimated-smpte-timecode'):
                            pts=mpv_timecode_ms(info['estimated-smpte-timecode'])
                            signal='video-frame-info/estimated-smpte-timecode (60fps, drop-frame labels)'
                        good=accepted.get('generation')==expected_generation and abs(pts-target)<=34
                        details[key]={'pts':pts,'signal':signal,'target':target,'generation':accepted.get('generation'),'good':good}
                    else:
                        p=page.video_compositor._players.get(layer['clip_id'])
                        good=bool(p and p._image_generation==p.generation
                            and p._published_epoch==p._epoch and abs(p.pts_ms-layer['source_ms'])<=34)
                        details[key]={'target':layer['source_ms'],'good':good,'decoder':p.performance_snapshot() if p else None}
                    if good and key not in result['first_ms']:result['first_ms'][key]=(now-started)*1000
                success=bool(details) and all(d['good'] for d in details.values())
                if success or now-started>timeout:
                    result.update(passed=success,elapsed_ms=(now-started)*1000,details=details,seek_trace=trace)
                    self.operations.append(result)
                    self.result['checks'][label]=success
                    return True
                return False
            return ready

        def run(self):
            page=self.page;timeline=page.timeline
            page.video.set_paused(True)
            # Wait for the existing waveform job; this is excluded from gesture timing.
            yield 5.
            mode=os.environ.get('TWOBYTEASR_LONG_MODE','timeline')
            if mode=='timeline':
                timeline.set_visible_window(600_000,600_000)
                yield 1.
                for phase in ('pan','scrub','wheel','shift-wheel','zoom-pan'):
                    self.set_phase(phase)
                    timeline.set_visible_window(600_000,60_000 if phase=='zoom-pan' else 600_000)
                    for operation in range(60):
                        width=timeline._content_right()-timeline.TRACK_HEADER_WIDTH
                        left=timeline.TRACK_HEADER_WIDTH+width*.08;right=timeline._content_right()-width*.08
                        x0,x1=(left,right) if operation%2 else (right,left)
                        if 'wheel' in phase:
                            modifier=Qt.KeyboardModifier.ShiftModifier if phase=='shift-wheel' else Qt.KeyboardModifier.NoModifier
                            point=QPointF((left+right)/2,10)
                            QApplication.sendEvent(timeline,QWheelEvent(point,QPointF(timeline.mapToGlobal(point.toPoint())),
                                QPoint(),QPoint(0,120 if operation%2 else -120),Qt.MouseButton.NoButton,
                                modifier,Qt.ScrollPhase.ScrollUpdate,False))
                            yield .03;continue
                        modifier=Qt.KeyboardModifier.NoModifier if phase=='scrub' else Qt.KeyboardModifier.ShiftModifier
                        self.mouse(QEvent.Type.MouseButtonPress,x0,10,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,modifier)
                        for step in range(1,9):
                            self.mouse(QEvent.Type.MouseMove,x0+(x1-x0)*step/8,10,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,modifier)
                            yield .016
                        released=time.perf_counter()
                        self.mouse(QEvent.Type.MouseButtonRelease,x1,10,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,modifier)
                        self.operations.append({'phase':phase,'released':released,'target_ms':timeline.playhead_ms})
                        yield .025
                    yield .3
                for auto_resume in (False,True):
                    self.set_phase('scrub-release-auto' if auto_resume else 'scrub-release-play')
                    page.video.set_paused(not auto_resume)
                    timeline.set_visible_window(600000,600000)
                    left=timeline.TRACK_HEADER_WIDTH+60;right=timeline._content_right()-70
                    self.mouse(QEvent.Type.MouseButtonPress,left,10,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton)
                    yield .04
                    self.mouse(QEvent.Type.MouseMove,right,10,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton)
                    yield .04
                    start=time.perf_counter()
                    self.mouse(QEvent.Type.MouseButtonRelease,right,10,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)
                    if not auto_resume:page._toggle_playback()
                    clicked=time.perf_counter();before=len(self.frames)
                    target=timeline.playhead_ms
                    yield lambda:any(f['at']>=clicked and f['pts']>target+30 for f in self.frames[before:]) or time.perf_counter()-start>3
                    self.operations.append(dict(phase=self.phase,target_ms=target,released=start,play_clicked=clicked,
                        release_to_click_ms=(clicked-start)*1000,first_progress_ms=(time.perf_counter()-start)*1000,
                        frames=self.frames[before:]))
                    self.result['checks'][self.phase]=bool(self.frames[before:])
                    yield .5
                    page.video.set_paused(True)
            elif mode=='transitions':
                for track in page.project.video_tracks:track.enabled=True
                self.set_phase('boundary-prepare');page._seek(1.5)
                start=time.perf_counter();yield self.target_gate(1500,start,'boundary-target')
                self.set_phase('boundary-cross');page.video.set_paused(False)
                yield 3.
                right_ids={clip.id for track in page.project.video_tracks[1:] for clip in track.clips if clip.timeline_in_ms==2000}
                crossed=next(r['at'] for r in self.rows if r['phase']=='boundary-cross' and r['presentation_ms']>=2000)
                uploads=[r for r in page.video._video_upload_samples if r.get('applied') or r.get('accepted')]
                first={key:next((r['applied_at'] for r in uploads if r.get('applied_at',0)>=crossed
                    and key in r.get('followers',{})),None) for key in right_ids}
                self.result['boundary_first_native_ms']={key:(value-crossed)*1000 if value else None for key,value in first.items()}
                self.result['checks']['boundary_warm_first_native_250ms']=all(value is not None and value<=250 for value in self.result['boundary_first_native_ms'].values())
                self.result['boundary_mapping']=page._multitrack_preview_layers(int(page.video.visual_position()*1000))
                page.video.controller.screenshot_to_file(output/'boundary-native.png',mode='window')
                page.video.set_paused(True)
                # Hot rates use the full-duration V1 plus the two mapped clips;
                # stay within clip bounds by seeking back between test groups.
                page._seek(2.1);yield .3
                for rate in (1.,2.,3.,4.,1.):
                    self.set_phase(f'hot-{rate:g}')
                    before={k:p.performance_snapshot() for k,p in page.video_compositor._players.items()}
                    page.video.set_speed(rate);page.video.set_paused(False)
                    yield .35
                    self.operations.append(dict(phase=self.phase,before=before,
                        after={k:p.performance_snapshot() for k,p in page.video_compositor._players.items()}))
                page.video.set_paused(True);page._seek(2.2);yield .3
                track_id=page.project.video_tracks[-1].id
                self.set_phase('hide-v3');page._video_track_action(track_id,'enabled');yield .5
                self.result['hidden_layers']=page._multitrack_preview_layers(2200)
                self.result['checks']['v3-hidden']=not any(l['track_id']==track_id for l in self.result['hidden_layers'])
                self.set_phase('show-v3');start=time.perf_counter();page._video_track_action(track_id,'enabled')
                yield self.target_gate(2200,start,'v3-restored')
            else:
                cases=[('v1',(0,)),('v2',(1,)),('v3',(2,)),('v1-v2',(0,1)),('v1-v2-v3',(0,1,2))]
                if mode=='endurance':cases=cases[-1:]
                targets=(0,) if mode=='endurance' else tuple(map(int,os.environ.get('TWOBYTEASR_LONG_TARGETS','0,611234,5080167').split(',')))
                for target_ms in targets:
                    for name,enabled in cases:
                        for i,track in enumerate(page.project.video_tracks):track.enabled=i in enabled
                        for rate in ((4.,) if mode=='endurance' else (1.,2.,3.,4.)):
                            label=f'{name}-{rate:g}x-at-{target_ms}'
                            self.set_phase('prepare-'+label)
                            page.video.set_paused(True);page._seek(target_ms/1000);page._shuttle_speed=rate;page.video.set_speed(rate)
                            start=time.perf_counter()
                            yield self.target_gate(target_ms,start,'target-'+label)
                            self.set_phase('start-'+label)
                            playback_started=time.perf_counter()
                            page.video.set_paused(False)
                            def started(label=label,target_ms=target_ms,at=playback_started):
                                elapsed=(time.perf_counter()-at)*1000
                                advanced=page.video.visual_position()*1000>target_ms+34
                                if advanced or elapsed>10000:
                                    self.operations.append(dict(phase='start-'+label,first_progress_ms=elapsed,
                                        advanced=advanced,audio=page.audio_engine.telemetry_snapshot()))
                                    self.result['checks']['started-'+label]=advanced
                                    return True
                                return False
                            yield started
                            # Full steady duration starts only when the shared
                            # clock moves. Startup remains a separately timed,
                            # fully sampled phase, never erased from evidence.
                            self.set_phase(label)
                            yield float(os.environ.get('TWOBYTEASR_LONG_SECONDS','300')) if mode=='endurance' else 5.
                            self.set_phase('capture-'+label)
                            page.video.controller.screenshot_to_file(output/f'{label}.png',mode='window')
                            page.video.set_paused(True)
                            yield .1
            self.set_phase('finish');page.video.set_paused(True)

        def finish(self):
            self.timer.stop()
            self.phase_windows[self.phase][1]=time.perf_counter()
            self.result['phase_windows']=self.phase_windows
            scrub=getattr(self.page,'_timeline_scrub',None)
            if scrub is not None:
                self.result['scrub_scheduler']={'pointer_replaced':scrub.replaced,
                    'pending_discarded_on_release':scrub.pending_discarded_on_release,
                    'samples':list(scrub.samples)}
            self.resource_stop.set()
            self.result.update(samples=self.rows,paints=self.paints,events=self.events,seeks=self.seeks,operations=self.operations,
                seek_traces=self.page.video.seek_latency_traces(),
                decoded_frames=self.frames,publications=self.publications,resources=self.resources,
                upload_ack=list(self.page.video._video_upload_samples),
                stalls={k:list(v.stall_events) for k,v in self.page.video_compositor._players.items()},
                followers={k:list(v.samples) for k,v in self.page.video_compositor._players.items()})
            for phase in dict.fromkeys(r['phase'] for r in self.rows):
                paints=[r['ms'] for r in self.paints if r['phase']==phase]
                gaps=[r['gap_ms'] for r in self.rows if r['phase']==phase]
                seeks=[r for r in self.seeks if r['phase']==phase]
                self.result['summary'][phase]={'paint_ms':distribution(paints),'gui_gap_ms':distribution(gaps),'seeks':len(seeks)}
                per_clip={}
                for key in {f['clip_id'] for f in self.frames if f['phase']==phase}:
                    frames=[f for f in self.frames if f['phase']==phase and f['clip_id']==key]
                    intervals=[(b['at']-a['at'])*1000 for a,b in zip(frames,frames[1:])]
                    per_clip[key]={'fps':(len(frames)-1)/(frames[-1]['at']-frames[0]['at']) if len(frames)>1 else 0,
                        'interval_ms':distribution(intervals),'lag_ms':distribution([f['requested']-f['pts'] for f in frames])}
                self.result['summary'][phase]['followers']=per_clip
                uploads=[r for r in self.page.video._video_upload_samples if r.get('audit_phase')==phase
                         and r['overlay_id']==0 and r.get('accepted') and r.get('applied_at')
                         and self.phase_windows[phase][0]<=r['applied_at']<=self.phase_windows[phase][1]]
                intervals=[(b['applied_at']-a['applied_at'])*1000 for a,b in zip(uploads,uploads[1:])]
                self.result['summary'][phase]['upload_ack']={
                    'fps':(len(uploads)-1)/(uploads[-1]['applied_at']-uploads[0]['applied_at']) if len(uploads)>1 else 0,
                    'interval_ms':distribution(intervals),'total_ms':distribution([r['total_ms'] for r in uploads])}
                independent = {}
                for upload in uploads:
                    for clip,frame in upload.get('followers',{}).items():
                        identity=(frame.get('generation'),frame.get('epoch'),frame.get('pts'))
                        records=independent.setdefault(clip,[])
                        if not records or records[-1][1]!=identity:
                            records.append((upload['applied_at'],identity))
                self.result['summary'][phase]['distinct_pts_ack']={clip:{
                    'fps':(len(records)-1)/(records[-1][0]-records[0][0]) if len(records)>1 else 0,
                    'interval_ms':distribution([(b[0]-a[0])*1000 for a,b in zip(records,records[1:])])}
                    for clip,records in independent.items()}
                if (phase.startswith(('v1-','v2-','v3-')) and '-at-' in phase):
                    for clip,metrics in self.result['summary'][phase]['distinct_pts_ack'].items():
                        self.result['checks'][f'cadence-{phase}-{clip}']=bool(
                            metrics['fps']>=29 and metrics['interval_ms']['p95'] is not None
                            and metrics['interval_ms']['p95']<=50 and metrics['interval_ms']['max']<=250)
            self.result['checks']['pan_no_seek']=not any(r['phase'] in ('pan','wheel','shift-wheel','zoom-pan') for r in self.seeks)
            (output/'long-project-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
            self.page.undo_stack.setClean()
            # MainWindow owns asynchronous Studio/audio/player shutdown. Keep
            # the event loop alive until its close_ready_signal completes it.
            self.page.close_ready_signal.connect(self.closed)
            self.result['checks']['close_cleanup_completed']=False
            window.close()

        def closed(self, profile):
            self.result['close_profile']=dict(profile)
            self.result['checks']['close_cleanup_completed']=bool(self.page._close_complete)
            self.result['checks']['close_audio_idle']=profile.get('audio_idle') is True
            (output/'long-project-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
    window._long_project_audit=Audit()
