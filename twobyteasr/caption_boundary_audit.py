"""Opt-in real HWND capture and controller telemetry; bounded to three short cases."""
import json, os, subprocess, time, traceback
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFrame


def start(window, out):
    p = window.studio_page
    config = json.loads((out/'matrix.json').read_text('utf8'))
    result = dict(cases=[], error='', real_user_click=False, fixture='A[0,1000), B[1000+gap,2000), no animation')
    rows=[];events=[];active=[''];recorder=None;commands=[];restore_send=None
    marker=QFrame(window);marker.setGeometry(12,12,12,12)
    def phase_marker(playing):
        marker.setStyleSheet('background:'+('#20e040' if playing else '#e02040')+';border:0;')
        marker.show();marker.raise_()
    phase_marker(False)
    original_trace=p._studio_trace
    def trace(event, **values):
        if active[0]: events.append(dict(at=time.perf_counter(),case=active[0],event=event,**values))
        return original_trace(event, **values)
    p._studio_trace=trace
    timer=QTimer(window);timer.setTimerType(Qt.PreciseTimer);timer.setInterval(8)
    def sample():
        if not active[0]: return
        playback=p.video.playback_position_snapshot()
        overlay=p.advanced_cue_overlay;worker=getattr(p,'_web_live_worker',None)
        current=getattr(p.session,'active_cue_id','')
        from bisect import bisect_right
        runtime=p.session.runtime
        following=bisect_right(runtime._cue_starts,int(playback.presentation_media_ms))
        near=tuple(dict.fromkeys((current,*runtime._cue_order[max(0,following-1):following+3])))
        rows.append(dict(at=time.perf_counter(),case=active[0],clock_ms=playback.presentation_media_ms,
            paused=playback.paused,
            caption_sample_ms=float(p._caption_sample_ms()),clock_observed_ms=playback.observed_media_ms,
            timeline_ms=p.timeline.playhead_ms,controller_cue=current,
            prepared_cues=[cue_id for cue_id in near if cue_id and p._prepared_caption(cue_id) is not None],
            canvas_cue=getattr(getattr(overlay,'_snapshot',None),'cue_id',''),visible=overlay.isVisible(),
            published_web=getattr(p,'_web_live_published_cue',''),
            native_visible=getattr(p.video,'_native_subtitle_visible',None),
            worker_content=worker.strip_key if worker else '',
            worker_generation=worker._configuration_generation if worker else None,
            observed_mpv_time=p.video.controller.observed_property('time-pos',None)))
    timer.timeout.connect(sample)
    def pump(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end: QApplication.processEvents();time.sleep(.003)
    def wait(test, seconds=25):
        end=time.monotonic()+seconds
        while not test() and time.monotonic()<end:pump(.05)
        if not test():raise TimeoutError('caption boundary audit readiness')
    def seek(ms):
        p.timecode_input.setText(f'00:00:{ms//1000:02d}.{ms%1000:03d}')
        QTest.keyClick(p.timecode_input,Qt.Key_Return)
    def run():
        nonlocal recorder,restore_send
        try:
            from .processes import popen_hidden_subprocess
            from .build_identity import load_build_identity
            result['identity']=load_build_identity().to_dict()
            for case in config['cases']:
                p.undo_stack.setClean();p.open_project(out/(case['id']+'.2byteproj'))
                p.video._caption_boundary_metrics=[]
                p._web_live_duplicate_pixels=0
                wait(lambda:not p._readiness.active and p.video.controller and p.video.controller.running)
                if os.environ.get('TWOBYTEASR_BOUNDARY_NATIVE_PROBE')=='1' and restore_send is None:
                    controller=p.video.controller;restore_send=controller._send
                    def observed_send(command,*args,**kwargs):
                        if command and command[0] not in ('get_property','observe_property'):
                            row=dict(at=time.perf_counter(),command=list(command))
                            if command[0]=='sub-add' and Path(command[1]).is_file():
                                row['ass']=Path(command[1]).read_text('utf8')
                            commands.append(row)
                        return restore_send(command,*args,**kwargs)
                    controller._send=observed_send
                window.showNormal();window.resize(1200,820);window.raise_();window.activateWindow()
                p.volume_slider.setValue(0);p.video.set_paused(True);p._set_review_mode(False)
                active[0]=case['id'];p.select_cue('A');seek(500);pump(2)
                if case['route']!='native':wait(lambda:p.advanced_cue_overlay.isVisible(),35)
                p.select_cue(None);p.position_edit_button.setChecked(False);pump(.4)
                content=p.position_overlay._content_rect();origin=p.position_overlay.mapTo(window,QPoint(0,0))
                case=dict(case,window_size=[window.width(),window.height()],
                    viewport=[origin.x()+content.x(),origin.y()+content.y(),content.width(),content.height()],
                    dpr=p.video.devicePixelRatioF(),phases=[],phase_marker=[18,18])
                active[0]=case['id'];timer.start()
                log=(out/(case['id']+'-capture.log')).open('wb')
                recorder=popen_hidden_subprocess([str(Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','warning',
                    '-f','lavfi','-i',f'gfxcapture=hwnd={int(window.winId())}:max_framerate=60:capture_cursor=0',
                    '-t',str(config.get('play_seconds',2.3)+13),'-fps_mode','vfr','-c:v','h264_nvenc','-preset','p1','-cq','12','-b:v','0',
                    str(out/(case['id']+'-screen.mp4'))],stdin=subprocess.PIPE,stdout=log,stderr=log,
                    purpose='short WGC caption pixels and embedded media frame PTS')
                case['record_started']=time.perf_counter();pump(1.5)
                case['phases'].append(dict(name='A-reference',at=time.perf_counter()));pump(.5)
                seek(1500);pump(1.3)
                case['phases'].append(dict(name='B-reference',at=time.perf_counter()));pump(.5)
                seek(0);pump(.9)
                case['phases'].append(dict(name='play',at=time.perf_counter()))
                QTest.mouseClick(p.play_button,Qt.LeftButton);phase_marker(True)
                if os.environ.get('TWOBYTEASR_BOUNDARY_NATIVE_PROBE')=='1':
                    def capture_playing(current_case=case):
                        current_case['playing_capture']=dict(at=time.perf_counter(),clock_ms=p.video.playback_position_snapshot().presentation_media_ms)
                        controller=p.video.controller
                        diagnostics=controller.subtitle_diagnostics()
                        for name in ('video-pts','video-frame-info','estimated-vf-fps','interpolation','blend-subtitles','secondary-sid','sub-text','sub-ass-extradata','vo','video-out-params','display-fps'):
                            try:diagnostics[name]=controller.get_property(name)
                            except RuntimeError as exc:diagnostics[name]={'unavailable':str(exc)}
                        diagnostics['active_compositor_overlays']=list(p.video._active_compositor_overlays)
                        diagnostics['compositor_contexts']=dict(p.video._compositor_overlay_contexts)
                        current_case['native_diagnostics']=diagnostics
                        ass=Path(diagnostics.get('studio_subtitle_path',''))
                        if ass.is_file():(out/(current_case['id']+'-playing.ass')).write_bytes(ass.read_bytes())
                        p.video.controller.screenshot_to_file(out/(current_case['id']+'-playing-mpv.png'))
                        window.grab().save(str(out/(current_case['id']+'-playing-qt.png')))
                        if os.environ.get('TWOBYTEASR_BOUNDARY_HIDE_PROBE')=='1':
                            controller.set_subtitle_visible(False)
                            QTimer.singleShot(80,window,lambda:controller.screenshot_to_file(out/'native-hidden-sub.png'))
                            QTimer.singleShot(180,window,lambda:controller.set_subtitle_visible(True))
                    QTimer.singleShot(1300,window,capture_playing)
                pump(config.get('play_seconds',2.3))
                phase_marker(False)
                case['phases'].append(dict(name='pause-requested',at=time.perf_counter()))
                p.video.set_paused(True);seek(1000);pump(.8)
                case['phases'].append(dict(name='exact-seek-1000',at=time.perf_counter()))
                p.video.controller.screenshot_to_file(out/(case['id']+'-seek1000.png'));pump(.4)
                timeline=p.timeline
                timeline.set_visible_window(0,4000)
                def point(ms):return QPoint(round(timeline._time_to_x(ms)),round(timeline.RULER_HEIGHT/2))
                QTest.mousePress(timeline,Qt.LeftButton,pos=point(500))
                for ms in (1700,400,1300,600,1500):QTest.mouseMove(timeline,point(ms));pump(.025)
                QTest.mouseRelease(timeline,Qt.LeftButton,pos=point(1500));pump(1)
                case['phases'].append(dict(name='rapid-scrub-release',at=time.perf_counter(),
                    timeline_ms=timeline.playhead_ms,controller_cue=p.session.active_cue_id))
                p.video.controller.screenshot_to_file(out/(case['id']+'-scrub-release.png'));pump(.25)
                worker=getattr(p,'_web_live_worker',None)
                case['worker_metrics']=list(worker.metrics) if worker else []
                pixel_cache=getattr(p,'_caption_pixel_cache',None)
                case['pixel_cache_metrics']=list(pixel_cache.metrics) if pixel_cache else []
                case['native_prepared_publications']=list(getattr(p.video,'_prepared_caption_publications',[]))
                case['scheduled_publications']=list(getattr(p.video,'_caption_boundary_metrics',[]))
                case['duplicate_web_pixels_skipped']=getattr(p,'_web_live_duplicate_pixels',0)
                recorder.stdin.write(b'q\n');recorder.stdin.flush()
                wait(lambda:recorder.poll() is not None,8);case['recorder_exit']=recorder.returncode
                log.close();recorder=None;timer.stop();active[0]='';result['cases'].append(case)
        except Exception:
            result['error']=traceback.format_exc()
            worker=getattr(p,'_web_live_worker',None)
            result['failure_worker_metrics']=list(worker.metrics) if worker else []
            result['failure_state']=p.subtitle_visibility_trace(reason='boundary_failure')
            p.video.controller.screenshot_to_file(out/'failure-native.png');pump(.2)
        finally:
            timer.stop();active[0]='';p._studio_trace=original_trace
            if restore_send is not None:p.video.controller._send=restore_send
            if commands:(out/'mpv-commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2),'utf8')
            marker.hide();marker.deleteLater()
            if recorder and recorder.poll() is None:
                recorder.stdin.write(b'q\n');recorder.stdin.flush()
            (out/'telemetry.json').write_text(json.dumps(rows,ensure_ascii=False),'utf8')
            (out/'events.json').write_text(json.dumps(events,ensure_ascii=False,default=str),'utf8')
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf8')
            p.video.set_paused(True);p.undo_stack.setClean();QTimer.singleShot(150,window.close)
    QTimer.singleShot(300,run)
