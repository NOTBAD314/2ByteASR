"""Normal-entry, bounded playback audit. No nested event loop or GUI polling IPC."""
from __future__ import annotations
import csv
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

def video_viewport(controller):
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
    user.IsWindowVisible.argtypes=[W.HWND]
    user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
    found=[];callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    pid=controller._process.pid
    def visit(hwnd,_):
        owner=W.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            r=W.RECT();user.GetWindowRect(hwnd,ctypes.byref(r))
            if r.right>r.left and r.bottom>r.top:found.append([r.left,r.top,r.right-r.left,r.bottom-r.top])
        return True
    user.EnumWindows(callback(visit),0)
    # Embedded windows are children of Qt top levels, not EnumWindows entries.
    def children(hwnd,_):user.EnumChildWindows(hwnd,callback(visit),0);return True
    user.EnumWindows(callback(children),0)
    if not found:raise RuntimeError('No visible native window belonging to the audited mpv PID')
    return max(found,key=lambda r:r[2]*r[3])

def start(window,out):
    from PySide6.QtCore import QTimer,Qt,qVersion
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..diagnostics.playback_metrics import distribution,desktop_cadence,system_cadence,read_system_trace
    from ..diagnostics import playback_probe
    from ..studio.studio_performance import performance_snapshot
    import PySide6
    spec=json.loads((out/'cadence-input.json').read_text('utf8'))
    result={'schema':1,'functional_pass':False,'measurement_valid':False,'performance_pass':'UNVERIFIED',
            'identity':load_build_identity().to_dict(),'frozen':bool(getattr(sys,'frozen',False)),
            'executable':sys.executable,'checks':{},'errors':[],'phases':[],
            'environment':{'Qt':qVersion(),'PySide6':PySide6.__version__,'python':sys.version,
            'screens':[{'name':s.name(),'geometry':s.geometry().getRect(),'refresh_hz':s.refreshRate(),
                        'dpr':s.devicePixelRatio()} for s in QApplication.screens()]}}
    heartbeat=[];telemetry=[];previous=[time.perf_counter()];phase=[''];owned=[];page=[None]
    beat=QTimer(window);beat.setTimerType(Qt.PreciseTimer);beat.setInterval(8)
    def on_beat():
        now=time.perf_counter()
        if phase[0]:heartbeat.append({'at':now,'phase':phase[0],'delay_ms':max(0,(now-previous[0])*1000-8)})
        previous[0]=now
    beat.timeout.connect(on_beat)
    snapshots=QTimer(window);snapshots.setInterval(500)
    def sample():
        if page[0] and phase[0]:telemetry.append({'at':time.perf_counter(),'phase':phase[0],**performance_snapshot(page[0],compact=True)})
    snapshots.timeout.connect(sample)
    def save():
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def steps():
        window.showNormal();window.resize(*spec.get('size',[1440,900]));window.move(30,30);window.show()
        if spec.get('maximized'):window.showMaximized()
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.SetWindowPos.argtypes=[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT]
        user.SetWindowPos(int(window.winId()),W.HWND(-1),0,0,0,0,0x0001|0x0002|0x0040)
        window.open_studio_project(str(out/'project.2byteproj'),mode='edit',source='cadence-audit')
        yield lambda:window.built_page('studio') is not None and window.built_page('studio')._readiness.ready
        p=page[0]=window.built_page('studio')
        result['checks']['initially_paused']=bool(p.video._paused)
        p.follow_playhead_toggle.setChecked(spec.get('follow',False))
        # Volume zero retains the PCM transport and clock; it is not an
        # audio-disabled baseline and must be reported as muted output.
        p.volume_slider.setValue(70 if spec.get('audio')=='audible' else 0)
        yield float(spec.get('settle',5))
        if not p.video._paused:p._toggle_playback()
        p._set_speed(float(spec.get('rate',1)));p._seek(float(spec.get('start',5)))
        yield lambda:not p.video._playback_clock.exact_seek_pending
        yield 1.
        c=p.video.controller
        result['mpv_pid']=c._process.pid;result['viewport']=video_viewport(c)
        result['window']={'logical_size':[window.width(),window.height()],'dpr':window.devicePixelRatioF(),'screen':window.screen().name()}
        result['before']=c.observed_properties()
        initial_binding=getattr(p,'_active_video_preview_key','')
        result['media']={'path':p.project.media.path,'metadata':vars(p.project.media),'cues':len(p.project.cues),'tracks':len(p.project.video_tracks),'rate':spec.get('rate',1),'audio_route':'Studio independent PCM; mpv aid=no','audio_test':spec.get('audio','muted')}
        from .blank_project_audit import _capture
        _capture(window,out/'window.png')
        presentmon=None
        if spec.get('presentmon'):
            args=['--process_id',str(c._process.pid),'--session_name','2ByteASR-cadence-'+str(os.getpid()),
                '--timed',str(round(spec['seconds']+6)),'--terminate_after_timed','--no_console_stats',
                '--qpc_time_ms','--v2_metrics','--output_file',str(out/'presentmon.csv')]
            log=(out/'presentmon-launch.log').open('wb')
            if spec.get('elevate_presentmon'):
                quote=lambda value:"'"+str(value).replace("'","''")+"'"
                script=out/'start-presentmon.ps1'
                script.write_text("$ErrorActionPreference='Stop'\n$p=Start-Process -FilePath "+quote(spec['presentmon'])+
                    " -ArgumentList "+quote(subprocess.list2cmdline(args))+" -Verb RunAs -WindowStyle Hidden -PassThru\n"+
                    "[IO.File]::WriteAllText("+quote(out/'presentmon-ready')+",[string]$p.Id)\n$p.WaitForExit()\n",'utf8')
                command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)]
            else:command=[spec['presentmon'],*args]
            presentmon=subprocess.Popen(command,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            owned.append((presentmon,log))
            if spec.get('elevate_presentmon'):
                yield lambda:(out/'presentmon-ready').exists() or presentmon.poll() is not None
            yield 2.
            if presentmon.poll() is not None:
                result['presentmon_error']=(out/'presentmon-launch.log').read_text('utf8',errors='replace')
        capture=None
        if spec.get('capture'):
            log=(out/'capture.log').open('wb')
            capture=subprocess.Popen([spec['capture'],*map(str,result['viewport']),str(spec['seconds']+3),str(spec.get('barcode_y',-1)),str(out/'desktop.csv')],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            owned.append((capture,log))
            yield lambda:(out/'desktop.csv.ready').exists() or capture.poll() is not None
            if capture.poll() is not None:raise RuntimeError('desktop capture failed: '+(out/'capture.log').read_text('utf8',errors='replace'))
            if spec.get('capture_capabilities',{}).get('multi_region'):
                yield lambda:all((out/(r['name']+'-desktop.csv.ready')).exists() for r in spec.get('regions',[])) or capture.poll() is not None
        result['checks']['correct_speed']=abs(float(c.observed_property('speed',0))-float(spec.get('rate',1)))<.001
        beat.start();snapshots.start();phase[0]='start';begin=time.perf_counter();p._toggle_playback()
        result['play_start_qpc']=begin
        yield 1.
        phase[0]='steady';steady=time.perf_counter()
        saved_text=None
        if spec.get('phase')=='background':
            def background():
                began=time.perf_counter()
                p._start_chunked_qc_scan()
                result.setdefault('operations',[]).append({'kind':'full_qc_request','at':began,'gui_ms':(time.perf_counter()-began)*1000})
            QTimer.singleShot(3000,background)
        elif spec.get('phase')=='seek':
            for index in range(4):
                def seek(index=index):
                    began=time.perf_counter();p._seek(10+index*2)
                    result.setdefault('operations',[]).append({'kind':'seek','target':10+index*2,'at':began,'gui_ms':(time.perf_counter()-began)*1000})
                QTimer.singleShot(3000+index*2000,seek)
        elif spec.get('phase')=='resize':
            for index in range(6):
                QTimer.singleShot(3000+index*1000,lambda index=index:window.resize(1360+(index%2)*80,860+(index%2)*40))
        yield float(spec['seconds'])-1
        end=time.perf_counter();phase[0]=''
        # Pausing aligns the paused frame with the presentation cursor via a
        # seek. Read the running backend first, or that seek can hide a slow
        # decoder behind an optimistically advanced UI cursor.
        result['after']=c.observed_properties()
        result['project_end_ms']=int(p.timeline.playhead_ms)
        result['play_end_qpc']=end;beat.stop();snapshots.stop();p.video.set_paused(True)
        (out/'video-upload-samples.json').write_text(json.dumps(list(p.video._video_upload_samples.copy()),default=str),'utf8')
        result['desktop_mode']=spec.get('desktop','foreground')
        result['checks']['advanced_at_rate']=abs(float(result['after'].get('time-pos',0))-float(result['before'].get('time-pos',0))-(end-begin)*float(spec.get('rate',1)))<.4
        bindings={x.get('preview_key') for x in telemetry if x.get('preview_key')}
        if len(bindings)>1 or getattr(p,'_active_video_preview_key','')!=initial_binding:
            result['checks'].pop('advanced_at_rate',None)
            result['rate_measurement']='source binding changed; source-position subtraction cannot certify project speed'
        if spec.get('phase')=='seek':
            result['checks'].pop('advanced_at_rate',None)
            result['checks']['last_seek_completed']=not p.video._playback_clock.exact_seek_pending
        interrupted=any(x['clock'].get('paused') for x in telemetry if x['phase']=='steady')
        result['interrupted']=interrupted
        if capture:yield lambda:capture.poll() is not None
        if presentmon:yield lambda:presentmon.poll() is not None
        stable=[x['delay_ms'] for x in heartbeat if steady<=x['at']<end]
        result['ui_delay_ms']=distribution(stable)
        result['ui_start_ms']=distribution([x['delay_ms'] for x in heartbeat if begin<=x['at']<steady])
        result['functional_pass']=all(result['checks'].values())
        # Preserve raw timing even if a later external capture cannot be read.
        result['telemetry']=telemetry;result['heartbeat']=heartbeat
        save()
        events=playback_probe.take()
        result['callback_ms']={name:distribution([e['ms'] for e in events if e.get('stage')==name and steady<=e['at']<end and 'ms' in e]) for name in ('apply_playhead','timeline_paint','ensure_renderer','active_cues')}
        if (out/'desktop.csv').is_file():
            rows=list(csv.DictReader((out/'desktop.csv').open(encoding='utf8')))
            result['desktop']=desktop_cadence(rows,steady,end,source_fps=spec['source_fps'],display_hz=window.screen().refreshRate(),rate=spec.get('rate',1),barcode=spec.get('barcode_y',-1)>=0)
            result['measurement_valid']=result['desktop']['measurement_valid'];result['performance_pass']=result['desktop']['performance_pass']
        if interrupted:
            result['measurement_valid']=False;result['performance_pass']='UNVERIFIED'
            result['measurement_reason']='playback paused or window hidden during steady acquisition'
        result['system_present']='UNVERIFIED: no analyzed PID-matched ETW display samples'
        if (out/'presentmon.csv').is_file():
            result['presentmon_raw']=str(out/'presentmon.csv')
            rows=read_system_trace(out/'presentmon.csv')
            result['system_present']=system_cadence(rows,steady,end,process_id=result['mpv_pid'],
                source_fps=spec['source_fps'],display_hz=window.screen().refreshRate(),rate=spec.get('rate',1))
            if not interrupted:
                result['measurement_valid']=result['system_present']['measurement_valid']
                result['performance_pass']=result['system_present']['performance_pass']
        result['physical_scanout']='UNVERIFIED';result['human_audio']='UNVERIFIED'
        result['telemetry']=telemetry;result['heartbeat']=heartbeat
        (out/'playback-probe.json').write_text(json.dumps(events,default=str),'utf8')
        result['finished']=True;save()
    sequence=steps();waiting=[None];deadline=[time.perf_counter()+180];busy=[False]
    driver=QTimer(window);driver.setInterval(15)
    def finish(error=None):
        driver.stop();beat.stop();snapshots.stop()
        if error:result['errors'].append(error);save()
        for process,log in owned:
            if process.poll() is None:process.terminate()
            log.close()
        if page[0] is not None:page[0].undo_stack.setClean()
        window.close()
    def advance():
        if busy[0]:return
        busy[0]=True
        try:
            now=time.perf_counter()
            if now>deadline[0]:raise TimeoutError('bounded cadence audit deadline')
            if window.isMinimized():raise RuntimeError('measurement interrupted: test window was minimized')
            pending=waiting[0]
            if pending is not None and not (pending() if callable(pending) else now>=pending):return
            value=next(sequence)
            waiting[0]=value if callable(value) else time.perf_counter()+float(value)
        except StopIteration:finish()
        except Exception:finish(traceback.format_exc())
        finally:busy[0]=False
    driver.timeout.connect(advance);driver.start();window._cadence_audit_timers=(driver,beat,snapshots)
