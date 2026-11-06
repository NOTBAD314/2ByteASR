"""Real normal-window, clock/data/paint and isolated endpoint fault acceptance."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
    from ..studio.studio_performance import performance_snapshot
    result=dict(passed=False,checks=[],cycles=[],frozen=bool(getattr(sys,'frozen',False)),
                executable=sys.executable,cwd=os.getcwd())
    def save():(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));save()
        if not value:raise RuntimeError(name)
    def pump(seconds=.05):
        end=time.monotonic()+seconds
        while time.monotonic()<end:QApplication.processEvents();time.sleep(.005)
    def wait(predicate,seconds=10):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            pump()
            if predicate():return True
        return False
    def run():
        page=getattr(window,'_studio_page_instance',None)
        if page is None:QTimer.singleShot(100,run);return
        other=None
        try:
            check('normal project startup',wait(lambda:page.project is not None and page._project_view_state=='open'
                and page.video._startup_state=='READY' and not page._readiness.active,60))
            window._switch_page(page)
            page.volume_slider.setValue(0)
            if os.environ.get('STABILITY_AUDIO_ONLY')=='1':
                from .audio_only_stability_checks import run as audio_only
                audio_only(page,output,check,pump,wait)
                result['passed']=True
                return
            page._seek(1.)
            check('real initial seek settles',wait(lambda:not page.video._playback_clock.exact_seek_pending,15))
            controller=page.video.controller
            original_pid=controller._process.pid
            initial_media_epoch=controller._subtitle_binding_epoch
            media_path=page.video._media_path
            other=QWidget();other.setWindowTitle('2ByteASR owned focus verification')
            other.resize(480,240);other.setLayout(QVBoxLayout());other.layout().addWidget(QLabel('Owned focus target'))
            other.show();pump(.1)
            user=ctypes.WinDLL('user32') if os.name=='nt' else None
            native_focus=os.environ.get('TWOBYTEASR_ACCEPTANCE_NATIVE_FOCUS')=='1'
            if user is not None:
                user.SetForegroundWindow.argtypes=[ctypes.c_void_p]
                user.GetForegroundWindow.restype=ctypes.c_void_p
            def alt_tab(expected):
                owned={int(window.winId()),int(other.winId())}
                check('native input remains in owned windows',int(user.GetForegroundWindow() or 0) in owned)
                user.keybd_event(0x12,0,0,0);user.keybd_event(0x09,0,0,0)
                user.keybd_event(0x09,0,2,0);user.keybd_event(0x12,0,2,0)
                check('OS Alt+Tab changes the foreground',wait(lambda:int(user.GetForegroundWindow() or 0)==int(expected.winId()),2))
            def activate(widget):
                widget.showNormal();widget.raise_();widget.activateWindow()
                if user is not None:user.SetForegroundWindow(int(widget.winId()))
                QApplication.setActiveWindow(widget)
                pump(.15)
            for paused in (False,True):
                activate(window)
                page.video.set_paused(paused)
                check('requested transport intent reached '+str(paused),wait(lambda:page.video._paused==paused,15))
                if not paused:check('real PCM is consumed',wait(lambda:page.audio_engine.telemetry_snapshot().get('sink_consumed_bytes',0)>0,10))
                for index in range(20):
                    kind=('window_activation','minimize_restore','studio_navigation')[index%3]
                    before=page.timeline.playhead_ms
                    if kind=='window_activation':
                        if native_focus:
                            activate(other);activate(window);alt_tab(other);alt_tab(window)
                            kind='OS_AltTab'
                        else:activate(other);activate(window)
                    elif kind=='minimize_restore':window.showMinimized();pump(.15);activate(window)
                    else:
                        # Same real window/page routing as the sidebar.
                        target=window._home_page if hasattr(window,'_home_page') else None
                        if target is None:
                            page.hide();pump(.15);page.show()
                        else:window._switch_page(target);pump(.15);window._switch_page(page)
                        activate(window)
                    pump(.2)
                    if not paused and page.video._paused:
                        # Studio navigation deliberately pauses by contract;
                        # focus/minimize must preserve the live intent.
                        check('only navigation may pause',kind=='studio_navigation')
                        page.video.set_paused(False)
                        check('navigation play resumes',wait(lambda:not page.video._paused,10))
                        pump(.15)
                    sample=performance_snapshot(page,compact=True)
                    paint=sample['playhead_display']['last_paint'] or {}
                    clock_ms=page.video.visual_position()*1000
                    expected_x=page.timeline._time_to_x(page.timeline.playhead_ms)
                    row=dict(paused=paused,index=index,kind=kind,clock_ms=clock_ms,
                        timeline_ms=page.timeline.playhead_ms,paint=paint,scrub=page.timeline._scrub_drag)
                    result['cycles'].append(row)
                    check(f'paint follows effective clock {paused}/{index}',
                        abs(clock_ms-page.timeline.playhead_ms)<180 and
                        abs(float(paint.get('project_ms',-9999))-page.timeline.playhead_ms)<180 and
                        abs(float(paint.get('x',-9999))-expected_x)<3 and
                        time.perf_counter()-float(paint.get('monotonic',0))<1.5 and not page.timeline._scrub_drag,row)
                    check(f'no media reload {paused}/{index}',page.video.controller is controller
                        and controller._process.pid==original_pid and page.video._media_path==media_path
                        and controller._subtitle_binding_epoch==initial_media_epoch)
            page.video.set_paused(True)
            window.grab().save(str(output/'window-after-focus.png'))
            result['focus_scope']=('20 playing +20 paused; '+('OS Alt+Tab' if native_focus else 'native activation')
                +', minimize/restore, Studio navigation; physical multi-screen separately required')
            controller._needs_media_reload=True
            page.video._request_player_recovery('mpv_transport_stalled')
            controller._subtitle_file_loaded()
            pump(.4)
            check('verified late file-loaded supersedes stale recovery',page.video.controller is controller
                and controller._process.pid==original_pid and not controller._needs_media_reload
                and page.video._recovery_request is None)
            # Real child faults exercise the same facade/IPC used by Studio.
            for fault in ('delay','exit','no-device'):
                page.audio_engine.unload();pump(.25)
                os.environ['TWOBYTEASR_TEST_AUDIO_FAULT']=fault
                page._retry_audio_output()
                if fault=='delay':
                    pump(.3);started=time.monotonic();page.video.set_paused(True);page.audio_engine.unload()
                    pump(.5)
                    check('delayed handshake cancels without GUI wait',time.monotonic()-started<1.5)
                    pump(3.1);check('late handshake cannot autoplay',page.video._paused and not page.video._buffered_play_pending)
                else:
                    check('endpoint failure becomes explicit',wait(lambda:page.audio_engine.playback_readiness().failed,12),page.audio_engine.telemetry_snapshot())
                    pump(.4)
                    check('failed endpoint stops pending play',page.video._paused and not page.video._buffered_play_pending)
                    bridge=page.audio_engine._worker;attempts=bridge._recovery.attempts
                    pump(2.)
                    check('automatic endpoint recovery is bounded',bridge._recovery.attempts<=3,bridge._recovery.attempts)
                    check('audio failure retains video instance',page.video.controller is controller and controller._process.pid==original_pid)
                    if fault=='no-device':
                        dialog=getattr(page,'_audio_failure_dialog',None)
                        if dialog is not None:
                            button=next(x for x in dialog.buttons() if x.text()=='无声预览')
                            button.click()
                        else:page.audio_silent_button.click()
                        check('explicit silent-preview action starts without false audio readiness',
                            wait(lambda:bool(getattr(page,'_silent_preview_selected',False)) and not page.video._paused,10)
                            and page.audio_engine._output_suppressed and '无声预览' in page.audio_status_label.text())
                        check('silent preview retains the same video instance',page.video.controller is controller)
                dialog=getattr(page,'_audio_failure_dialog',None)
                if dialog is not None:dialog.reject()
                page.video.set_paused(True)
            os.environ.pop('TWOBYTEASR_TEST_AUDIO_FAULT',None)
            page._retry_audio_output()
            check('explicit audio-only retry restores playback',wait(lambda:not page.video._paused
                and page.audio_engine.telemetry_snapshot().get('sink_consumed_bytes',0)>0,20),page.audio_engine.telemetry_snapshot())
            check('recovery retained video and project',page.video.controller is controller and controller._process.pid==original_pid)
            page.video.set_paused(True)
            from .media_loading_checks import run as media_checks
            media_checks(output,check,pump)
            import shutil
            replacement=output/'switch-target.2byteproj'
            shutil.copyfile(output/'project.2byteproj',replacement)
            previous=page.project
            old_session=page.audio_engine._session_generation
            os.environ['TWOBYTEASR_TEST_AUDIO_FAULT']='delay'
            page._retry_audio_output();pump(.2)
            os.environ.pop('TWOBYTEASR_TEST_AUDIO_FAULT',None)
            page.open_project(replacement,skip_dirty_guard=True)
            check('switching projects cancels old loading ownership',wait(lambda:page.project is not previous
                and page._project_view_state=='open' and not page._readiness.active,45))
            pump(3.2)
            check('late old endpoint cannot autoplay the next project',page.video._paused
                and not page.video._buffered_play_pending and page.audio_engine._session_generation>old_session)
            os.environ['TWOBYTEASR_TEST_AUDIO_FAULT']='delay'
            page._retry_audio_output();pump(.2)
            check('close begins with a cancellable owned audio startup',bool(page.video._buffered_play_pending or page.video._startup_play_requested))
            result['passed']=True
        except Exception:
            result['error']=traceback.format_exc()
            try:result['failure_state']=performance_snapshot(page,compact=True)
            except Exception:pass
        finally:
            os.environ.pop('TWOBYTEASR_TEST_AUDIO_FAULT',None)
            if other is not None:other.close()
            save();page.video.set_paused(True);window.close();QTimer.singleShot(200,QApplication.instance().quit)
    def shutdown():result['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    QTimer.singleShot(500,run)
