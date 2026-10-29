"""Owned real-window lifecycle and preview measurements; no user-state writes."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import cProfile
import json
import math
import os
from pathlib import Path
import statistics
import sys
import threading
import time
import traceback
from collections import deque


def stats(values):
    rows=sorted(float(v) for v in values if v is not None)
    if not rows:return {'n':0}
    return {'n':len(rows),'p50':round(statistics.median(rows),3),
        'p95':round(rows[max(0,math.ceil(len(rows)*.95)-1)],3),
        'p99':round(rows[max(0,math.ceil(len(rows)*.99)-1)],3),'max':round(rows[-1],3)}


def native_tree(window, page):
    from PySide6.QtCore import Qt
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetParent.argtypes=[W.HWND];user.GetParent.restype=W.HWND
    user.GetWindowLongW.argtypes=[W.HWND,ctypes.c_int];user.GetWindowLongW.restype=W.LONG
    user.IsWindowVisible.argtypes=[W.HWND];user.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
    rows=[]
    callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    def visit(hwnd,_):
        rect=W.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect));pid=W.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        name=ctypes.create_unicode_buffer(256);user.GetClassNameW(hwnd,name,256)
        rows.append(dict(hwnd=int(hwnd),parent=int(user.GetParent(hwnd) or 0),pid=pid.value,
            class_name=name.value,visible=bool(user.IsWindowVisible(hwnd)),
            style=hex(user.GetWindowLongW(hwnd,-16)&0xffffffff),
            rect=[rect.left,rect.top,rect.right,rect.bottom]))
        return True
    hwnd=int(window.winId());visit(hwnd,0);user.EnumChildWindows(W.HWND(hwnd),callback(visit),0)
    widgets={}
    for name in ('video','advanced_cue_overlay','position_overlay','video_compositor','video_overlay_host','workspace_splitter','studio_empty'):
        w=getattr(page,name,None)
        if w is None:continue
        parent=w.parentWidget()
        widgets[name]=dict(object_id=id(w),object_name=w.objectName(),parent_id=id(parent),
            parent_name=parent.objectName() if parent else None,visible=w.isVisible(),hidden=w.isHidden(),
            window=bool(w.isWindow()),flags=int(w.windowFlags()),rect=list(w.geometry().getRect()),
            hwnd=int(w.winId()) if w.testAttribute(Qt.WidgetAttribute.WA_NativeWindow) else None)
    return dict(native=rows,widgets=widgets,view=getattr(page,'_project_view_state',''),
                project_id=getattr(page.project,'project_id',None),session=getattr(page.session,'generation',None))


class FrameObserver:
    """Second read-only IPC client. Arrival timing is NOT physical scanout timing."""
    def __init__(self, controller):
        self.rows=deque(maxlen=100000);self.pts=deque(maxlen=100000);self.errors=[];self.stop=threading.Event()
        self.lock=threading.Lock()
        self.path=controller._pipe_path
        self.thread=threading.Thread(target=self.run,name='acceptance-video-pts',daemon=True)
        self.thread.start()
    def run(self):
        import msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.PeekNamedPipe.argtypes=[W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.c_void_p,ctypes.POINTER(W.DWORD),ctypes.c_void_p]
        try:
            with open(self.path,'r+b',buffering=0) as pipe:
                for key,name in ((700,'video-pts'),(701,'video-frame-info')):
                    pipe.write((json.dumps({'command':['observe_property',key,name],'request_id':key})+'\n').encode())
                buffer=b'';handle=msvcrt.get_osfhandle(pipe.fileno())
                while not self.stop.wait(.002):
                    available=W.DWORD()
                    if not kernel.PeekNamedPipe(W.HANDLE(handle),None,0,None,ctypes.byref(available),None):break
                    if not available.value:continue
                    buffer+=pipe.read(available.value)
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        row=json.loads(line);at=time.perf_counter()
                        if row.get('event')=='property-change' and row.get('name')=='video-pts':
                            with self.lock:self.pts.append((at,row.get('data')))
                        elif row.get('event')=='property-change' and row.get('name')=='video-frame-info':
                            info=row.get('data') or {}
                            with self.lock:self.rows.append((at,info.get('estimated-smpte-timecode')))
                        elif row.get('error') not in (None,'success'):self.errors.append(row)
        except Exception as exc:self.errors.append(str(exc))
    def snapshot(self):
        with self.lock:return list(self.rows),list(self.pts)
    def close(self):self.stop.set();self.thread.join(1)


def start(window,out):
    from PySide6.QtCore import QTimer
    def execute():
        try:run(window,Path(out))
        except Exception:
            (Path(out)/'error.txt').write_text(traceback.format_exc(),'utf8')
        finally:
            page=window.built_page('studio')
            if page is not None:page.undo_stack.setClean()
            window.close()
    QTimer.singleShot(100,execute)


def run(window,out):
    import psutil
    import PySide6
    from PySide6.QtCore import Qt,QTimer,QCoreApplication,QEvent,QObject,QPoint,QPointF,qVersion
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QKeyEvent,QWheelEvent
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..studio.studio_performance import performance_snapshot
    from ..diagnostics import playback_probe
    result=dict(checks=[],windows=[],phases=[],operations=[],errors=[],
        identity=load_build_identity().to_dict(),executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)),
        environment=dict(python=sys.version,PySide6=PySide6.__version__,Qt=qVersion(),
            screens=[dict(name=s.name(),size=[s.size().width(),s.size().height()],dpr=s.devicePixelRatio(),refresh=s.refreshRate()) for s in QApplication.screens()]),
        video_interval_measurement='mpv video-frame-info estimated timecode change reception on independent IPC thread; not DWM Present or physical scanout',
        ui_measurement='10ms GUI event-loop heartbeat delay; operation handler duration and exact-seek acknowledgement separately',
        physical_presentation='NOT VERIFIED',started=time.time())
    def save(): (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,ok,detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail));save()
    def pump(seconds):QTest.qWait(round(seconds*1000))
    def wait(test,label,seconds=90):
        end=time.perf_counter()+seconds
        while not test():
            if time.perf_counter()>end:raise TimeoutError(label)
            pump(.01)
    def opened():
        p=window.built_page('studio')
        return p is not None and getattr(p,'_readiness',None) is not None and p._readiness.ready
    import weakref,gc
    retired_projects=[]
    fixture=out/'project.2byteproj'
    window.showNormal();window.resize(1440,900);window.show()
    window.open_studio_project(str(fixture),mode='edit',source='preview-repair-audit')
    wait(opened,'initial project')
    page=window.built_page('studio');page.follow_playhead_toggle.setChecked(False)
    result['window']={'width':window.width(),'height':window.height(),'dpr':window.devicePixelRatioF()}
    result['fixture']={'cues':len(page.project.cues),'media':page.project.media.path,'duration_ms':page.project.media.duration_ms,
                       'translations':len(page.project.generation_metadata.get('translations') or {})}
    check('open.paused',page.video._paused)
    retired_projects.append(weakref.ref(page.project))
    observer=FrameObserver(page.video.controller)
    proc=psutil.Process(); heart=[]; old=[time.perf_counter()]
    heartbeat=QTimer(window);heartbeat.setTimerType(Qt.TimerType.PreciseTimer);heartbeat.setInterval(10)
    def beat():
        now=time.perf_counter();heart.append((now,(now-old[0])*1000));old[0]=now
    heartbeat.timeout.connect(beat);heartbeat.start()
    def snap(label):
        state=native_tree(window,page);state['label']=label
        state['resources']=dict(mpvs=sum(p.name().lower()=='mpv.exe' for p in proc.children(recursive=True) if p.is_running()),
            widgets=len(QApplication.allWidgets()),timers=len(page.findChildren(QTimer)),rss_mib=proc.memory_info().rss/1024**2)
        result['windows'].append(state);save()
        if os.environ.get('TWOBYTEASR_PREVIEW_SNAPSHOTS','1')!='0' or not label.startswith('library-'):
            _capture(window,out/(label+'.png'))
        return state
    def phase(label,rate=1,seconds=8,interact=None):
        page.video.set_paused(True)
        sample_start=max(5., min((c.start_ms for c in page.project.cues),default=5000)/1000+.2)
        page._seek(sample_start);pump(.5);page._set_speed(rate)
        before=page.video.controller.observed_properties();cpu=proc.cpu_times();memory=[];states=[]
        begin=time.perf_counter();page.video.set_paused(False);index=0
        profile=cProfile.Profile() if os.environ.get('TWOBYTEASR_PREVIEW_PROFILE')=='1' else None
        if profile:profile.enable()
        while time.perf_counter()-begin<seconds:
            if interact:interact(index)
            index+=1;pump(.05);memory.append(proc.memory_info().rss/1024**2)
            if index%10==0:
                states.append(dict(at=time.perf_counter()-begin,properties=page.video.controller.observed_properties(),
                    audio_clock=page.audio_engine.clock_observation(),
                    video_frame_source_ms=page.video._last_video_frame_pts_ms,
                    project_clock_ms=page.video.playback_position_snapshot().presentation_media_ms))
        if profile:profile.disable();profile.dump_stats(str(out/(label+'.pstats')))
        end=time.perf_counter();after=page.video.controller.observed_properties();cpu2=proc.cpu_times()
        page.video.set_paused(True)
        observed_rows,observed_pts=observer.snapshot()
        rows=[(at,v) for at,v in observed_rows if begin<=at<=end and v is not None]
        distinct=[r for i,r in enumerate(rows) if i==0 or r[1]!=rows[i-1][1]]
        gaps=[v for at,v in heart if begin<=at<=end]
        row=dict(label=label,rate=rate,duration_s=round(end-begin,3),profiling=bool(profile),
            mpv_frame_info_intervals_ms=stats([(b[0]-a[0])*1000 for a,b in zip(distinct,distinct[1:])]),
            mpv_pts_steps_ms=stats([(b[1]-a[1])*1000 for a,b in zip(observed_pts,observed_pts[1:]) if begin<=a[0]<=end and isinstance(a[1],(int,float)) and isinstance(b[1],(int,float)) and b[1]>a[1]]),
            ui_delay_ms=stats([max(0,v-10) for v in gaps]),ui_over_100ms=sum(v>110 for v in gaps),
            cpu_one_core_percent=round(((cpu2.user+cpu2.system)-(cpu.user+cpu.system))/(end-begin)*100,2),
            rss_mib=stats(memory),before=before,after=after,samples=states,
            drops={k:(after[k]-before[k]) if isinstance(after.get(k),(int,float)) and isinstance(before.get(k),(int,float)) else None for k in ('decoder-frame-drop-count','frame-drop-count','vo-delayed-frame-count','mistimed-frame-count')},
            audio=page.audio_engine.telemetry_snapshot(),performance=performance_snapshot(page,compact=True))
        if label in ('steady-original-1x','post-navigation-1x'):
            try:
                page.video.controller.screenshot_to_file(out/(label+'-native.png'))
                row['native_screenshot']=label+'-native.png'
            except Exception as exc:row['native_screenshot_error']=str(exc)
        result['phases'].append(row);save();print('PREVIEW',label,row['ui_delay_ms'],row['drops'],flush=True)
    try:
        snap('opened')
        if os.environ.get('TWOBYTEASR_PREVIEW_MODE')=='speed':
            for rate in (1,2,4):
                phase('speed-'+str(rate)+'x',rate,8)
                observed=result['phases'][-1]['audio'].get('effective_rate')
                check('audio-rate-'+str(rate),observed is not None and abs(float(observed)-rate)<.01,observed)
                check('video-rate-'+str(rate),abs(page.video._playback_rate-rate)<.01)
            result['finished']=True;result['passed']=all(c['passed'] for c in result['checks']);save();return
        if os.environ.get('TWOBYTEASR_PREVIEW_MODE','all')=='all':
            phase('cold-original',1,10)
            # Wait for the same complete quality scan before comparing steady modes.
            pump(1)
            phase('steady-original-1x',1)
            for rate in (2,4):phase('steady-original-'+str(rate)+'x',rate)
            def interaction(i):
                if i%7==0:page.upper_splitter.setSizes([260+(i%4)*15,650-(i%4)*15,320])
                if i%13==0 and page.project.cues:page.select_cue(page.project.cues[i%len(page.project.cues)].id)
                if i%5==0:
                    timeline=page.timeline
                    point=QPoint(timeline.TRACK_HEADER_WIDTH+120,timeline.RULER_HEIGHT//2)
                    wheel=QWheelEvent(QPointF(point),QPointF(timeline.mapToGlobal(point)),QPoint(),
                        QPoint(0,120 if (i//5)%2 else -120),Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
                    QApplication.sendEvent(timeline,wheel)
            phase('interaction-1x',1,8,interaction)
            # Remove publication only for this diagnostic comparison, then restore exactly.
            original=dict(page._subtitle_track_visibility)
            for speaker in page.project.speakers:page._subtitle_visibility_changed(speaker.id,False)
            pump(.7)
            phase('subtitles-hidden',1)
            for speaker in page.project.speakers:page._subtitle_visibility_changed(speaker.id,original.get(speaker.id,True))
            pump(.7)
            # Restore/save the owned copy before testing navigation guards.
            page.save();wait(lambda:not getattr(page,'_manual_save_in_progress',False),'save restored view')
            for target in (11.2,24.8,14.5):
                began=time.perf_counter();page._seek(target);handler=(time.perf_counter()-began)*1000
                wait(lambda:not page.video.playback_position_snapshot().exact_seek_pending,'seek settle',5)
                result['operations'].append(dict(kind='seek',target=target,handler_ms=handler,settle_ms=(time.perf_counter()-began)*1000,
                    traces=page.video.seek_latency_traces()[-1:]));save()
        # Pointer-driven scrub: intermediate seeks may coalesce; release owns the final target.
        if os.environ.get('TWOBYTEASR_PREVIEW_MODE','all')!='lifecycle':
            timeline=page.timeline
            timeline.set_visible_window(0,240000);pump(.1)
            for playing in (False,True):
                page.video.set_paused(not playing);pump(.3)
                def point(ms):return QPoint(round(timeline._time_to_x(ms)),round(timeline.RULER_HEIGHT/2))
                began=time.perf_counter()
                QTest.mousePress(timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(45000))
                for index in range(12):
                    QTest.mouseMove(timeline,point(45000+index*7500));pump(.025)
                QTest.mouseRelease(timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(127500))
                target=timeline.playhead_ms
                wait(lambda:not page.video.playback_position_snapshot().exact_seek_pending and page.video._paused==(not playing),'drag exact settle',8)
                pump(.15)
                clock=page.video.playback_position_snapshot()
                result['operations'].append(dict(kind='pointer-drag',playing=playing,target_ms=target,
                    final_ms=clock.presentation_media_ms,elapsed_ms=(time.perf_counter()-began)*1000,
                    trace=page.video.seek_latency_traces()[-1:]))
                check('drag.paused-state.'+str(playing),clock.paused== (not playing))
                if not playing:check('drag.exact-final-target',abs(clock.presentation_media_ms-target)<60)
                page.video.set_paused(True)
        page.video.set_paused(False);pump(.3);page._request_return_home();pump(.6)
        home=snap('home-playing')
        check('home.video-hidden',not page.video.isVisible())
        check('home.paused',page.video._paused)
        window.open_studio_project(str(fixture));wait(opened,'resume');pump(.2)
        check('resume.paused',page.video._paused)
        for i in range(int(os.environ.get('TWOBYTEASR_PREVIEW_CYCLES','2'))):
            page.undo_stack.setClean()
            if i%2:page.video.set_paused(False);pump(.2)
            page._request_return_library();pump(.4)
            state=snap('library-'+str(i))
            check('library.video-hidden.'+str(i),not page.video.isVisible(),state['widgets'].get('video'))
            check('library.pause.'+str(i),page.video._paused)
            check('library.no-active-poll.'+str(i),not page.video._timer.isActive() and not page.video._sync_timer.isActive())
            next_path=out/'other.2byteproj' if i%2 and (out/'other.2byteproj').exists() else fixture
            window.open_studio_project(str(next_path));wait(opened,'reenter');pump(.2)
            check('reenter.paused.'+str(i),page.video._paused)
            retired_projects.append(weakref.ref(page.project))
        # Direct replacement keeps the NEW readiness request while retiring the old project.
        import shutil
        direct=out/'direct.2byteproj';shutil.copy2(fixture,direct)
        page.undo_stack.setClean();window.open_studio_project(str(direct))
        wait(lambda:opened() and str(page.project_path)==str(direct),'direct project replacement')
        check('direct-switch.ready-and-paused',page.video._paused and page._project_view_state=='open')
        # Two requests without pumping: only the latest request may publish.
        page.undo_stack.setClean();window.open_studio_project(str(fixture));window.open_studio_project(str(direct))
        wait(lambda:opened() and str(page.project_path)==str(direct),'latest direct replacement')
        pump(.3)
        check('direct-switch.latest-request-wins',str(page.project_path)==str(direct) and page.video._paused)
        window.open_studio_project(str(fixture));wait(opened,'direct switch back')
        window.showMaximized();pump(.2);window.showMinimized();pump(.3);window.showNormal();window.resize(1440,900);pump(.3)
        page.undo_stack.setClean();page._request_return_library();pump(.4);snap('library-resized')
        check('library.resized-video-hidden',not page.video.isVisible())
        # Reenter then cancel the existing guard; no close is allowed before approval.
        window.open_studio_project(str(fixture));wait(opened,'final reopen');pump(.2)
        from PySide6.QtWidgets import QMessageBox
        page._recovered_autosave_pending=True
        cancel=QTimer(page);cancel.setInterval(25)
        def cancel_prompt():
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):
                cancel.stop();_capture(modal,out/'leave-cancel-prompt.png')
                modal.button(QMessageBox.StandardButton.Cancel).click()
        cancel.timeout.connect(cancel_prompt);cancel.start()
        page._request_return_library();cancel.stop();cancel.deleteLater()
        page._recovered_autosave_pending=False
        check('leave-cancel.retains-project',page.project is not None and page.video.isVisible())
        page.video.set_paused(False);start_pos=page.video.visual_position();pump(.6)
        check('leave-cancel.playable',page.video.visual_position()>start_pos+.1)
        page.video.set_paused(True)
        # A new path forces an actual in-flight reader, rather than the retained hot path.
        import shutil
        loading=out/'loading.2byteproj';shutil.copy2(fixture,loading)
        page.undo_stack.setClean();window.open_studio_project(str(loading))
        page._request_return_library();pump(1.0)
        check('loading.leave-invalidates-reader',page.project is None and page._project_view_state=='hub',dict(has_project=page.project is not None,view=page._project_view_state,generation=page._readiness.generation))
        check('loading.leave-hides-video',not page.video.isVisible())
        window.open_studio_project(str(fixture));wait(opened,'after loading cancellation');pump(.2)
        check('loading.reenter-paused',page.video._paused)
        if os.environ.get('TWOBYTEASR_PREVIEW_MODE','all')=='all' and int(os.environ.get('TWOBYTEASR_PREVIEW_CYCLES','2'))>0:
            phase('post-navigation-1x',1,8)
        # Observe the normal idle settle; do not force collections or mask a leak.
        page.video.set_paused(True);pump(2.5)
        result['idle_memory']=dict(rss_mib=proc.memory_info().rss/1024**2,
            old_projects_alive=len({id(ref()) for ref in retired_projects if ref() is not None and ref() is not page.project}),
            collections=gc.get_stats(),project_settles=page._project_heap.settles)
        check('closed-project-references-retired',result['idle_memory']['old_projects_alive']==0)
        result['processes']=[dict(pid=p.pid,name=p.name()) for p in proc.children(recursive=True) if p.is_running()]
        result['frame_observer_errors']=observer.errors
        result['observed_video_pts_available']=any(v is not None for _,v in observer.snapshot()[1])
        snap('final-reopened')
        result['finished']=True;result['passed']=all(c['passed'] for c in result['checks']);save()
    finally:
        observer.close();heartbeat.stop();page.video.set_paused(True);save()
