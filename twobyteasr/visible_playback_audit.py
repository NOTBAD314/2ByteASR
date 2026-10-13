"""Opt-in <=30 second screen-content audit; no Qt grab or upload-count FPS."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import threading
import time
import traceback


class ScreenPixels:
    """Reuse one top-down DIB to sample actual desktop composition, not QWidget."""
    def __init__(self, x, y, width, height):
        import numpy as np
        self.x, self.y, self.width, self.height = x, y, width, height
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        self.user.GetDC.argtypes = [wintypes.HWND]; self.user.GetDC.restype = wintypes.HDC
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]; self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; self.gdi.SelectObject.restype = wintypes.HANDLE
        self.gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi.BitBlt.argtypes = [wintypes.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HDC,ctypes.c_int,ctypes.c_int,wintypes.DWORD]
        self.gdi.CreateDIBSection.argtypes = [wintypes.HDC,ctypes.c_void_p,wintypes.UINT,ctypes.POINTER(ctypes.c_void_p),wintypes.HANDLE,wintypes.DWORD]
        self.gdi.CreateDIBSection.restype = wintypes.HBITMAP
        import struct
        info = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0))
        self.source = self.user.GetDC(None)
        self.dest = self.gdi.CreateCompatibleDC(self.source)
        pointer = ctypes.c_void_p()
        self.bitmap = self.gdi.CreateDIBSection(self.dest,info,0,ctypes.byref(pointer),None,0)
        if not pointer.value: raise ctypes.WinError(ctypes.get_last_error())
        self.old = self.gdi.SelectObject(self.dest,self.bitmap)
        self.pixels = np.ctypeslib.as_array((ctypes.c_ubyte*(width*height*4)).from_address(pointer.value)).reshape(height,width,4)

    def grab(self):
        if not self.gdi.BitBlt(self.dest,0,0,self.width,self.height,self.source,self.x,self.y,0x00CC0020|0x40000000):
            raise ctypes.WinError(ctypes.get_last_error())
        self.gdi.GdiFlush()
        return self.pixels

    def close(self):
        self.gdi.SelectObject(self.dest,self.old); self.gdi.DeleteObject(self.bitmap)
        self.gdi.DeleteDC(self.dest); self.user.ReleaseDC(None,self.source)


def decode_barcode(pixels, rect, barcode_y=890):
    x,y,w,h = rect
    bits=[]
    for i in range(16):
        px=round(x+(128+64*i)/1920*w); py=round(y+barcode_y/1080*h)
        block=pixels[max(0,py-1):py+2,max(0,px-1):px+2,:3]
        bits.append(int(block.mean()>150) if block.size else 0)
    if bits[12:] != [0,1,0,1]: return None
    return sum(b<<i for i,b in enumerate(bits[:12]))


def summarize(rows, start, end):
    import numpy as np
    steady=[r for r in rows if start+1 <= r['at'] < end]
    result={'measurement':'GDI desktop pixels, binary frame number; first second separated',
        'steady_seconds':end-start-1, 'samples':len(steady), 'capture_p95_ms':float(np.percentile([r['capture_ms'] for r in steady],95)) if steady else None}
    gaps=[(b['at']-a['at'])*1000 for a,b in zip(steady,steady[1:])]
    result.update(probe_max_gap_ms=max(gaps,default=0),probe_gaps_over_100ms=sum(g>100 for g in gaps))
    for layer in ('V1','V2'):
        good=[r for r in steady if r[layer] is not None]
        changes=[];last=None
        for row in good:
            if row[layer] != last: changes.append(row); last=row[layer]
        times=[start+1]+[r['at'] for r in changes]+[end]
        observed=0.;run_start=None;previous=None
        for row in good:
            if previous is None or row['at']-previous['at']>.1 or row[layer]!=previous[layer]:run_start=row['at']
            else:observed=max(observed,(row['at']-run_start)*1000)
            previous=row
        per_second=[sum(start+i <= r['at'] < start+i+1 for r in changes) for i in range(1,int(end-start))]
        result[layer]={'different_frames':len(changes),'visible_fps':len(changes)/max(.001,end-start-1),
            'longest_repeat_ms':max((b-a)*1000 for a,b in zip(times,times[1:])),
            'observed_same_code_ms':observed,
            'repeat_upper_bound_includes_sampling_gaps':bool(result['probe_gaps_over_100ms']),
            'per_second':per_second,'valid_fraction':len(good)/max(1,len(steady))}
    return result


def start(window, out):
    from PySide6.QtCore import QObject,QTimer,Qt,QPoint,QPointF,QMimeData,QUrl
    from PySide6.QtGui import QDragEnterEvent,QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QInputDialog,QComboBox
    from .studio_performance import performance_snapshot

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page=window.studio_page;self.result={'checks':{},'error':'','telemetry':[],'real_user_click':False}
            self.rows=[];self.stop=threading.Event();self.capture_error='';self.thread=None
            self.seconds=float(os.environ['TWOBYTEASR_VISIBLE_SECONDS']);self.rate=float(os.environ['TWOBYTEASR_VISIBLE_RATE'])
            self.ablation=os.environ['TWOBYTEASR_VISIBLE_ABLATION'];self.start_at=self.end_at=0
            self.started=time.perf_counter();self.pending=0;self.busy=False;self.last=0;self.profile=None
            self.recorder=None
            self.probe=None
            import faulthandler
            self.stack_log=(out/'blocked-stacks.txt').open('w')
            faulthandler.dump_traceback_later(45,repeat=True,file=self.stack_log)
            self.sequence=self.run();self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(20)

        def tick(self):
            if self.busy:return
            self.busy=True
            try:
                now=time.perf_counter()
                if self.start_at and now-self.last>=.2:
                    state=performance_snapshot(self.page,compact=True);state['at']=now
                    native_pts=self.page.video.controller.observed_property('time-pos',None)
                    state['native_v1_pts_ms']=float(native_pts)*1000 if native_pts is not None else None
                    state['window_id']=int(window.winId())
                    state['recorder_exit']=self.recorder.poll() if self.recorder else None
                    self.result['telemetry'].append(state);self.last=now
                if now-self.started>115:raise TimeoutError('short audit budget exceeded')
                if now>=self.pending:self.pending=now+float(next(self.sequence))
            except StopIteration:self.finish()
            except Exception:self.result['error']=traceback.format_exc();self.finish()
            finally:self.busy=False

        def play(self,value):
            if self.page.video.playback_position_snapshot().paused == bool(value):
                QTest.mouseClick(self.page.play_button,Qt.LeftButton)

        def drop(self,name):
            def accept():
                d=QApplication.activeModalWidget()
                if isinstance(d,QInputDialog):QTest.keyClick(d,Qt.Key_Return)
            QTimer.singleShot(250,accept)
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(Path(os.environ['TWOBYTEASR_VISIBLE_MEDIA'])/name))])
            QApplication.sendEvent(self.page,QDragEnterEvent(QPoint(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
            QApplication.sendEvent(self.page,QDropEvent(QPointF(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))

        def field(self,widget,text):
            if hasattr(widget,'lineEdit'):widget=widget.lineEdit()
            QTest.mouseClick(widget,Qt.LeftButton);QTest.keyClick(widget,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClicks(widget,text);QTest.keyClick(widget,Qt.Key_Return)

        def reopen_project(self,path):
            from .studio_project import SubtitleProject,StudioMedia,save_project
            blank=out/'empty-reopen.2byteproj'
            save_project(SubtitleProject(media=StudioMedia(path='')),blank)
            for target in (blank,path):
                old=self.page.project
                mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(target))])
                QApplication.sendEvent(self.page,QDragEnterEvent(QPoint(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
                QApplication.sendEvent(self.page,QDropEvent(QPointF(300,300),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
                deadline=time.perf_counter()+10
                while (self.page.project is old or self.page._readiness.active) and time.perf_counter()<deadline:yield .1
                assert self.page.project is not old,'Project reopen did not replace in-memory project'

        def capture(self, geometry, rects):
            from PIL import Image
            surface=None
            try:
                surface=ScreenPixels(*geometry)
                next_image=0
                while not self.stop.is_set():
                    begin=time.perf_counter();pixels=surface.grab();now=time.perf_counter()
                    row={'at':now,'capture_ms':(now-begin)*1000}
                    row.update({layer:decode_barcode(pixels,rect) for layer,rect in rects.items()})
                    self.rows.append(row)
                    if now>=next_image:
                        Image.fromarray(pixels[:,:,[2,1,0]].copy()).save(out/f'screen-{len(self.rows):05d}.png')
                        next_image=now+5
                    self.stop.wait(max(0,.008-(time.perf_counter()-begin)))
            except Exception:self.capture_error=traceback.format_exc()
            finally:
                if surface:surface.close()

        def run(self):
            yield 1
            window.showMaximized();window.raise_();window.activateWindow();yield .5
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            # Only this isolated test window; closing it restores the previous desktop.
            user.SetWindowPos(int(window.winId()),-1,0,0,0,0,0x0001|0x0002|0x0040)
            real=os.environ.get('TWOBYTEASR_VISIBLE_REAL')=='1'
            self.result['real_media']=real
            if real:
                while self.page._readiness.active:yield .1
                assert len(self.page.project.video_tracks)>=2
                self.play(False);yield .5
            else:
                duration='1200s' if os.environ.get('TWOBYTEASR_VISIBLE_MODE')=='filmstrip' else '120s'
                self.drop(f'V1-{duration}.mp4');yield 2
                while not self.page.project.media.path:yield .2
                self.play(False);yield .3
                self.field(self.page.timecode_input,'00:00:00.000');yield .5
                self.drop(f'V2-{duration}.mp4');yield 2
                while len(self.page.project.video_tracks)<2:yield .2
                self.play(False);yield .5
                rect=self.page.timeline._video_track_rect('V2')
                QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=QPoint(round(self.page.timeline._time_to_x(3000)),int(rect.center().y())));yield .3
                assert self.page.timeline.selected_video_clip_id,'Clip selection did not succeed'
                # Standard fixture keeps two independent visible frame codes.
                for name,value in [('video_scale_x','45'),('video_scale_y','45'),('video_position_x','72'),('video_position_y','30')]:
                    self.field(getattr(self.page,name),value);yield .1
                selected=self.page._selected_video_clip()[1]
                assert abs(selected.transform.scale_x-.45)<.001 and abs(selected.transform.position_x-.72)<.001,vars(selected.transform)
            captions=os.environ.get('TWOBYTEASR_VISIBLE_CAPTIONS','none')
            if captions!='none' and not real:
                self.drop('captions.srt');yield 1
                assert len(self.page.project.cues)==600
                if captions=='web':
                    from .local_subtitle_theme import local_subtitle_theme
                    from .style_recipe import StyleRecipe
                    design=json.loads((Path.cwd()/'tests/fixtures/polar_bear_f38c393_concepts.json').read_text('utf8'))
                    design.setdefault('selected_concept_id',design['concepts'][0]['id'])
                    theme=local_subtitle_theme(design)
                    self.page.project.style_recipes['default']=StyleRecipe(name='Fixed load fixture',engine='remotion',web_theme=theme).to_dict()
                    for cue in self.page.project.cues:cue.style_id='default'
                    self.result['theme_setup']='Explicit local fixed theme fixture; no Provider call'
                # Real cue-table event activates subtitle follow, rather than leaving video selection locked.
                cell=self.page.cue_model.index(0,0)
                QTest.mouseClick(self.page.cue_table.viewport(),Qt.LeftButton,pos=self.page.cue_table.visualRect(cell).center())
                yield .3
            self.field(self.page.timecode_input,'00:00:01.000');yield .5
            w=self.page.speed_box;index=w.findData(self.rate);assert index>=0
            QTest.mouseClick(w,Qt.LeftButton);QTest.qWait(60);view=w.view()
            QTest.keyClick(view,Qt.Key_Home)
            for _ in range(index):QTest.keyClick(view,Qt.Key_Down)
            QTest.keyClick(view,Qt.Key_Return);yield .3
            assert w.currentData()==self.rate
            self.result['events']=[]
            self.result['thumbnails']=os.environ.get('TWOBYTEASR_VISIBLE_THUMBNAILS','on')
            if self.result['thumbnails']=='off' and self.page.filmstrip_toggle.isChecked():
                QTest.mouseClick(self.page.filmstrip_toggle,Qt.LeftButton);yield .2
            self.result['tracks']=[{'id':t.id,'clips':[vars(c.transform) for c in t.clips]} for t in self.page.project.video_tracks]
            if os.environ.get('TWOBYTEASR_VISIBLE_MODE')=='placement':
                yield from self.placement_checks()
                return
            if os.environ.get('TWOBYTEASR_VISIBLE_MODE')=='filmstrip':
                yield from self.filmstrip_checks()
                return
            if self.ablation in ('web-off','video-only'):
                self.page._stop_web_live_preview('explicit short ablation')
                self.page._schedule_advanced_preview=lambda *a,**k:None
                self.page._ensure_web_live_preview=lambda *a,**k:False
            if self.ablation in ('selection-off','video-only'):
                self.page._follow_playhead_selection=lambda *a:None
            if self.ablation in ('audio-off','video-only'):
                for track in self.page.project.audio_tracks:
                    if not track.muted:
                        r=self.page.timeline._audio_track_rects()[track.id]
                        QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=QPoint(120,int(r.center().y())))
            if self.ablation in ('waveform-off','video-only') and self.page.waveform_toggle.isChecked():
                QTest.mouseClick(self.page.waveform_toggle,Qt.LeftButton)
            yield .5
            from .studio_project import save_project
            save_project(self.page.project,out/'imported.2byteproj')
            scene=self.page.video_compositor
            origin=scene.mapToGlobal(QPoint(0,0));width,height=scene.width(),scene.height()
            self.result['geometry']=[origin.x(),origin.y(),width,height]
            # Both video frames are 16:9; compositor viewport is the letterboxed video rectangle.
            rects={'V1':(0,0,width,height),'V2':(.495*width,.075*height,.45*width,.45*height)}
            if real:rects={'V2':(0,0,width,height)}
            self.result['barcode_rects']=rects
            self.result['device_pixel_ratio']=scene.devicePixelRatioF()
            # Windows Graphics Capture includes the native D3D video surface;
            # GDI may expose only a black hardware-overlay hole on this driver.
            from .processes import popen_hidden_subprocess
            import subprocess
            root=Path.cwd();self.capture_log=(out/'capture.log').open('wb')
            self.result['record_started']=time.perf_counter()
            dpr=scene.devicePixelRatioF()
            physical=[round(v*dpr) for v in self.result['geometry']]
            physical[2]-=physical[2]%2;physical[3]-=physical[3]%2
            self.result['record_crop']=physical
            wgc=os.environ.get('TWOBYTEASR_VISIBLE_CAPTURE')=='wgc'
            if wgc:
                self.result['record_crop']=None;self.result['barcode_y']=710
            self.recorder=popen_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','warning','-y',
                '-f','lavfi','-i',f'gfxcapture=hwnd={int(window.winId())}:max_framerate=60:capture_cursor=0' if wgc else f'ddagrab=framerate=60:draw_mouse=0:offset_x={physical[0]}:offset_y={physical[1]}:video_size={physical[2]}x{physical[3]}',
                '-t',str(self.seconds+4),'-fps_mode','vfr',
                '-c:v','h264_nvenc','-preset','p1','-cq','16','-b:v','0',str(out/'screen.mp4')],
                purpose='short GPU-direct WGC capture of the foreground Studio window',stdin=subprocess.PIPE,stdout=self.capture_log,stderr=self.capture_log) if wgc or os.environ.get('TWOBYTEASR_GPU_CAPTURE')=='1' else None
            self.result['window_geometry']=[window.x(),window.y(),window.width(),window.height()]
            window.grab().save(str(out/'setup-qt.png'))
            self.page.video.controller.screenshot_to_file(out/'setup-native.png')
            yield 1.5
            if self.recorder:assert self.recorder.poll() is None,'Graphics Capture failed; inspect capture.log'
            if not self.recorder:
                rects={'V1':(0,0,physical[2],physical[3]),'V2':(.495*physical[2],.075*physical[3],.45*physical[2],.45*physical[3])}
                (out/'capture-config.json').write_text(json.dumps(dict(geometry=physical,rects=rects,seconds=self.seconds,barcode_y=710)),encoding='utf8')
                import sys
                probe_command=([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-B',str(root/'quick_start.py')])+['--studio-screen-probe',str(out)]
                self.probe=popen_hidden_subprocess(probe_command,
                    purpose='independent-process Studio pixel probe',stdout=self.capture_log,stderr=self.capture_log)
                deadline=time.perf_counter()+5
                while not (out/'capture-ready').exists() and time.perf_counter()<deadline:yield .05
                assert (out/'capture-ready').exists(),'Pixel probe did not initialize'
            if os.environ.get('TWOBYTEASR_VISIBLE_PROFILE')=='1':
                import cProfile
                self.profile=cProfile.Profile();self.profile.enable()
            self.result['events'].append(dict(name='play',at=time.perf_counter(),target_ms=1000))
            self.play(True)
            while self.page.video.playback_position_snapshot().paused:yield .02
            self.start_at=time.perf_counter()
            if real:
                yield 8
                self.result['events'].append(dict(name='seek',at=time.perf_counter(),target_ms=90000))
                self.field(self.page.timecode_input,'00:01:30.000')
                self.play(True)
                yield max(0,self.seconds-8)
            else:yield self.seconds
            self.end_at=time.perf_counter();self.stop.set();self.play(False)
            (out/'capture-stop').touch()
            if self.profile:self.profile.disable();self.profile.dump_stats(str(out/'gui.prof'))
            yield .3
            if self.recorder and self.recorder.poll() is None:
                self.recorder.stdin.write(b'q\n');self.recorder.stdin.flush()
                deadline=time.perf_counter()+5
                while self.recorder.poll() is None and time.perf_counter()<deadline:yield .1
            self.result['recorder_exit']=self.recorder.poll() if self.recorder else None
            if self.thread:self.thread.join(2)
            if self.probe:
                deadline=time.perf_counter()+5
                while self.probe.poll() is None and time.perf_counter()<deadline:yield .05
                probe=json.loads((out/'probe.json').read_text('utf8'))
                self.rows=probe['rows'];self.capture_error=probe['error']
            self.result['play_window']=[self.start_at,self.end_at]
            self.result['screen']=(dict(measurement='WGC recording complete; actual game source matching pending') if real else summarize(self.rows,self.start_at,self.end_at))
            self.result['checks']['actual_rate']=all(abs(r['clock']['playback_rate']-self.rate)<.001 for r in self.result['telemetry'])
            for layer in (() if self.recorder else ('V1','V2')):
                data=self.result['screen'][layer]
                self.result['checks'][layer+'-visible-30fps']=data['visible_fps']>=30 and data['valid_fraction']>.98
            self.result['uploads']=list(self.page.video._video_upload_samples)
            self.result['decoder_samples']={key:list(source.samples) for key,source in scene._players.items()}
            self.result['decoder_transport_stats']={key:source._pipe.snapshot() for key,source in scene._players.items() if source._pipe is not None}
            self.result['primary_decoder']={key:self.page.video.controller.get_property(key,None) for key in ('hwdec-current','hwdec-interop','video-codec','path')}
            self.result['filmstrip_metrics']=dict(self.page.timeline._thumbnails.metrics)
            self.result['error']=self.capture_error
            if os.environ.get('TWOBYTEASR_VISIBLE_RECOVER')=='1':
                track=self.page.timeline._video_track_rect('V2')
                eye=QPoint(143,round(track.center().y()))
                QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=eye);yield .3
                self.play(True);yield .6
                self.result['checks']['hidden-worker-revoked']=not scene._async_video_active
                self.page.video.controller.screenshot_to_file(out/'hidden-recovery.png')
                self.play(False);yield .2
                QTest.mouseClick(self.page.timeline,Qt.LeftButton,pos=eye);yield .3
                self.field(self.page.timecode_input,'00:00:05.000');yield .5
                self.play(True);yield .7
                state=scene.performance_snapshot()
                self.result['checks']['show-resumes-worker']=scene._async_video_active and state['worker_submitted_frames']>0
                clock=self.page.video.playback_position_snapshot()
                self.result['checks']['seek-resumes-current-time']=5000<clock.presentation_media_ms<10000
                self.page.video.controller.screenshot_to_file(out/'shown-after-seek.png')
                self.play(False)

        def finish(self):
            import faulthandler
            faulthandler.cancel_dump_traceback_later()
            self.timer.stop();self.stop.set()
            if self.profile:self.profile.disable()
            self.result['elapsed']=time.perf_counter()-self.started
            (out/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            with (out/'screen-samples.jsonl').open('w',encoding='utf8') as stream:
                for row in self.rows:stream.write(json.dumps(row)+'\n')
            self.page.undo_stack.setClean()
            QTimer.singleShot(200,window.close)

        def filmstrip_checks(self):
            from PySide6.QtWidgets import QToolButton,QStyleOptionSlider,QStyle
            from .theme_manager import apply_theme
            from .video_filmstrip import filmstrip_tiles
            from .studio_project import load_project
            timeline=self.page.timeline;cache=timeline._thumbnails
            assert self.page.project.media.duration_ms>=1199000
            self.result['filmstrip']={'interaction':[],'source_duration_ms':self.page.project.media.duration_ms}
            data=self.result['filmstrip']
            def timing(name):
                row={'name':name};data['interaction'].append(row)
                timeline._timing_paint_input=(time.perf_counter(),row)
                (out/'filmstrip-progress.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
            def zoom(label,count):
                button=next(b for b in self.page.findChildren(QToolButton) if b.toolTip().startswith(label))
                for _ in range(count):QTest.mouseClick(button,Qt.LeftButton)
            def scroll(fraction):
                bar=timeline.horizontal_scrollbar;option=QStyleOptionSlider();bar.initStyleOption(option)
                handle=bar.style().subControlRect(QStyle.CC_ScrollBar,option,QStyle.SC_ScrollBarSlider,bar)
                groove=bar.style().subControlRect(QStyle.CC_ScrollBar,option,QStyle.SC_ScrollBarGroove,bar)
                target=QPoint(round(groove.left()+handle.width()/2+(groove.width()-handle.width())*fraction),handle.center().y())
                QTest.mousePress(bar,Qt.LeftButton,pos=handle.center())
                QTest.mouseMove(bar,target);QTest.mouseRelease(bar,Qt.LeftButton,pos=target)
            deadline=time.perf_counter()+10
            while len(cache.memory)<15 and time.perf_counter()<deadline:yield .1
            data['initial']=dict(cache.metrics,memory_bytes=cache.bytes,wanted=len(cache.wanted))
            self.result['checks']['initial-background-images']=cache.metrics['decoded']>0
            self.result['checks']['bounded-long-source']=len(cache.wanted)<1200
            timing('zoom-to-seconds');zoom('放大时间轴',8);yield 1
            timeline.grab().save(str(out/'filmstrip-seconds.png'))
            data['zoomed_visible_ms']=timeline.visible_duration_ms
            timing('zoom-to-minutes');zoom('缩小时间轴',12);yield .6
            timeline.grab().save(str(out/'filmstrip-minutes.png'))
            data['wide_visible_ms']=timeline.visible_duration_ms
            timing('return-dense');zoom('放大时间轴',6);yield .3
            starts=[]
            for i,fraction in enumerate((.52,.05,.83,.51,0)):
                timing('scroll-'+str(i));scroll(fraction);yield .25
                starts.append(timeline.visible_start_ms)
            data['scroll_starts_ms']=starts
            self.result['checks']['ten-minute-pan']=max(starts)-min(starts)>600000
            QTest.keyClick(timeline.horizontal_scrollbar,Qt.Key_Home)
            yield 1
            # Real trim handle and body drag, then a rate fixture (no rate UI exists).
            clip=self.page.project.video_tracks[1].clips[0]
            track=timeline._video_track_rect('V2');before=clip.source_in_ms
            a=QPoint(max(timeline.TRACK_HEADER_WIDTH+3,round(timeline._time_to_x(clip.timeline_in_ms))+3),round(track.center().y()))
            b=a+QPoint(85,0);timing('clip-trim')
            QTest.mousePress(timeline,Qt.LeftButton,pos=a);QTest.mouseMove(timeline,b);QTest.mouseRelease(timeline,Qt.LeftButton,pos=b);yield .6
            clip=self.page.project.video_tracks[1].clips[0]
            data['trim']={'before_source_in_ms':before,'after_source_in_ms':clip.source_in_ms}
            self.result['checks']['actual-trim']=clip.source_in_ms>before
            before=clip.timeline_in_ms
            a=QPoint(round(timeline._time_to_x(clip.timeline_in_ms))+60,round(track.center().y()))
            b=a+QPoint(75,0);timing('clip-move')
            QTest.mousePress(timeline,Qt.LeftButton,pos=a);QTest.mouseMove(timeline,b);QTest.mouseRelease(timeline,Qt.LeftButton,pos=b);yield .6
            clip=self.page.project.video_tracks[1].clips[0]
            self.result['checks']['actual-move']=clip.timeline_in_ms>before
            clip.playback_rate=2.;clip.timeline_out_ms=clip.timeline_in_ms+round((clip.source_out_ms-clip.source_in_ms)/2)
            self.page._changed();yield .8
            data['rate_fixture']='2x VideoClip data fixture; trim and move above use real widgets'
            left=timeline._time_to_x(clip.timeline_in_ms);right=timeline._time_to_x(clip.timeline_out_ms)
            tiles=filmstrip_tiles(left,right,max(left,timeline.TRACK_HEADER_WIDTH),min(right,timeline.width()),clip.source_in_ms,clip.source_out_ms,track.height())
            data['rate_tiles']=tiles
            self.result['checks']['trim-rate-mapping']=bool(tiles and tiles[0][2]>=clip.source_in_ms-1000 and all(b[2]>a[2] for a,b in zip(tiles,tiles[1:])))
            apply_theme('warm');yield .8
            timeline.grab().save(str(out/'filmstrip-warm.png'))
            apply_theme('slate');yield .6
            timeline.grab().save(str(out/'filmstrip-dark.png'))
            toggle=self.page.filmstrip_toggle
            QTest.mouseClick(toggle,Qt.LeftButton);yield .2
            self.result['checks']['toggle-off']=not timeline.filmstrip_visible
            QTest.mouseClick(toggle,Qt.LeftButton);yield .4
            QTest.mouseClick(self.page.save_button,Qt.LeftButton);yield .4
            path=Path(self.page.project_path)
            self.result['checks']['saved-toggle']=load_project(path).studio_state.get('video_thumbnails_visible') is True
            data['before_reopen']=dict(cache.metrics,memory_bytes=cache.bytes)
            old_cache=cache;cache.close()
            yield from self.reopen_project(path)
            cache=timeline._thumbnails;deadline=time.perf_counter()+5
            while cache.metrics['disk_hits']<5 and time.perf_counter()<deadline:yield .1
            data['reopened']=dict(cache.metrics,memory_bytes=cache.bytes)
            self.result['checks']['disk-reuse']=cache is not old_cache and cache.metrics['disk_hits']>=5
            self.result['checks']['bounded-memory']=cache.bytes<=cache.limit
            timeline.grab().save(str(out/'filmstrip-reopened.png'))
            measured=[r['input_to_paint_ms'] for r in data['interaction'] if 'input_to_paint_ms' in r]
            self.result['checks']['no-two-second-block']=bool(measured and max(measured)<2000)
            assert all(self.result['checks'].values()),self.result['checks']

        def placement_checks(self):
            from .studio_project import StudioCue,save_project,load_project
            from .studio_commands import ReplaceCuesCommand
            from .local_subtitle_theme import local_subtitle_theme
            from .style_recipe import StyleRecipe
            design=json.loads((Path.cwd()/'tests/fixtures/polar_bear_f38c393_concepts.json').read_text('utf8'))
            design['selected_concept_id']=design['concepts'][0]['id'];theme=local_subtitle_theme(design)
            if os.environ.get('TWOBYTEASR_VISIBLE_THEME'):
                theme=json.loads(Path(os.environ['TWOBYTEASR_VISIBLE_THEME']).read_text('utf8'))
                theme=theme.get('theme',theme)
                self.result['theme_setup']='User-selected real Grok 4.6 artifact, loaded for placement regression'
            # Explicit fixed-theme fixture; the interaction below is real UI.
            cue=StudioCue('placement-cue',0,30000,'北极熊也要认真滑雪')
            self.page.undo_stack.push(ReplaceCuesCommand(self.page.project,[cue],'Placement fixture',self.page._changed))
            self.page.project.style_recipes[cue.style_id]=StyleRecipe(name='Placement fixture',engine='remotion',web_theme=theme).to_dict()
            self.page.cue_model.set_project(self.page.project);self.page.timeline.set_project(self.page.project)
            cell=self.page.cue_model.index(0,0)
            QTest.mouseClick(self.page.cue_table.viewport(),Qt.LeftButton,pos=self.page.cue_table.visualRect(cell).center())
            self.field(self.page.timecode_input,'00:00:01.000');yield 1.5
            overlay=self.page.position_overlay
            assert overlay.isVisible(),'Subtitle placement overlay is not visible'
            self.result['placement_operations']=[]
            for name,x,y in [('left-bottom',.27,.90),('right-bottom',.73,.90),('middle',.50,.56)]:
                start=overlay._subtitle_rect().center().toPoint();content=overlay._content_rect()
                target=QPoint(start.x()+round((x-overlay.position_x/overlay.play_res_x)*content.width()),
                    start.y()+round((y-overlay.position_y/overlay.play_res_y)*content.height()))
                before=self.page.undo_stack.index()
                QTest.mousePress(overlay,Qt.LeftButton,Qt.AltModifier,start)
                for i in range(1,7):
                    QTest.mouseMove(overlay,start+(target-start)*i/6);yield .025
                QTest.mouseRelease(overlay,Qt.LeftButton,Qt.AltModifier,target);yield .8
                moved=dict(self.page.project.cues[0].transform)
                self.result['checks'][name+'-one-command']=self.page.undo_stack.index()==before+1
                assert 'web_placement' in moved,moved
                placement=dict(moved['web_placement'])
                assert abs(placement['x']-x)<.02 and abs(placement['y']-y)<.02,placement
                self.page.video.controller.screenshot_to_file(out/(name+'-drag.png'))
                self.play(True);yield .65
                self.play(False);yield .25
                self.field(self.page.timecode_input,'00:00:01.000');yield .65
                self.page.video.controller.screenshot_to_file(out/(name+'-after-play-seek.png'))
                self.result['checks'][name+'-data-kept']=self.page.project.cues[0].transform==moved
                live=self.page._web_live_snapshot.style_recipe.get('layout',{}).get('webPlacement')
                self.result['checks'][name+'-live-placement']=live==placement
                self.result['placement_operations'].append(dict(name=name,placement=placement))
            self.page.undo_stack.undo();yield .3
            self.result['checks']['undo-position']=self.page.project.cues[0].transform['web_placement']!=placement
            self.page.undo_stack.redo();yield .4
            self.result['checks']['redo-position']=self.page.project.cues[0].transform['web_placement']==placement
            QTest.mouseClick(self.page.save_button,Qt.LeftButton);yield .5
            project_path=Path(self.page.project_path)
            assert project_path.resolve().is_relative_to(out.resolve()),project_path
            self.result['saved_project']=str(project_path)
            self.result['checks']['saved-position']=load_project(project_path).cues[0].transform['web_placement']==placement
            yield from self.reopen_project(project_path)
            self.result['checks']['reopened-position']=self.page.project.cues[0].transform['web_placement']==placement
            self.field(self.page.timecode_input,'00:00:01.000');yield .8
            self.page.video.controller.screenshot_to_file(out/'reopened-native.png')
            (out/'theme.json').write_text(json.dumps(theme,ensure_ascii=False,indent=2),encoding='utf8')
            from .web_theme import export_theme_archive
            folder=export_theme_archive(theme,out/'export',sample_text=cue.text,placement=placement)
            self.result['html_export']=str(folder)
            self.result['checks']['html-placement']=json.loads((folder/'placement.json').read_text('utf8'))==placement
            assert all(self.result['checks'].values()),self.result['checks']

    window._visible_playback_audit=Audit()
