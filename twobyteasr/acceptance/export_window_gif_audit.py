"""Actual export lifecycle, input and decoded-frame evidence on an isolated desktop."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
import traceback
import sys
import hashlib
from dataclasses import asdict


def start(window, out):
    from PySide6.QtCore import QObject, QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from .blank_project_audit import _capture
    # The daily constructs Studio incrementally. Never force hydration from
    # the audit before its normal ready callback has installed the page.
    if window.built_page('studio') is None:
        QTimer.singleShot(100, lambda: start(window, out))
        return

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = dict(checks={}, events=[], error='', pid=os.getpid())
            from ..diagnostics.build_identity import load_build_identity
            from ..test_isolation import require_isolated_paths
            self.result['runtime']=dict(frozen=bool(getattr(sys,'frozen',False)),pid=os.getpid(),
                executable=sys.executable,exe_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                build=load_build_identity().to_dict())
            self.result['isolated_paths']={k:str(v) for k,v in require_isolated_paths('export-gif-package',emit=lambda _s:None).items()}
            def quit_receipt():
                self.result['gui_shutdown']=True
                self.save()
            QApplication.instance().aboutToQuit.connect(quit_receipt)
            self.started = time.monotonic()
            self.waiting = 0.
            self.steps = self.run()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(30)

        def check(self, key, value):
            self.result['checks'][key] = bool(value)

        def tick(self):
            if time.monotonic() < self.waiting:
                return
            try:
                if time.monotonic() - self.started > 240:
                    raise TimeoutError('export/window/GIF audit')
                self.waiting = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def save(self):
            critical=('twobyteasr.studio.studio_ui','twobyteasr.app.window_constraints',
                'twobyteasr.exports.studio_export_ui','twobyteasr.media.animated_gif')
            self.result['runtime']['module_paths']={name:str(getattr(sys.modules[name],'__file__',''))
                for name in critical if name in sys.modules}
            if getattr(sys,'frozen',False):
                bundle=Path(sys.executable).resolve().parent
                self.result['checks']['runtime-modules-from-bundle']=all(Path(p).resolve().is_relative_to(bundle)
                    for p in self.result['runtime']['module_paths'].values())
            (out / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

        def finish(self):
            self.timer.stop()
            self.save()
            window.close()
            self.result['gui_shutdown'] = not window.isVisible()
            (out / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')
            QTimer.singleShot(100, QApplication.instance().quit)

        def observe(self, label):
            p = self.page
            c = p.video.controller
            self.result['events'].append(dict(label=label, playhead=p.timeline.playhead_ms,
                enabled=p.timeline.isEnabled(), paused=p.video._paused, attached=p.video._media_attached,
                controller=bool(c and c.running), canvas_parent=p.video.parentWidget().objectName(),
                mpv=c.get_property('time-pos') if c else None,
                clock=asdict(p.video.playback_position_snapshot()),
                audio=dict(getattr(p.audio_engine, '_last_payload', {}) or {})))
            self.result['events'][-1]['audio_observation'] = dict(p.audio_engine.clock_observation() or {})
            self.result['events'][-1]['audio_state'] = dict(p.audio_engine.telemetry_snapshot() or {})

        def inputs(self, label):
            p = self.page
            t = p.timeline
            t.set_visible_window(0, 8000)
            yield .15
            for kind, target in [('ruler', 2200), ('drag', 5100), ('seek', 3400), ('shortcut', 4400), ('subtitle', 6200)]:
                if kind == 'ruler':
                    QTest.mouseClick(t, Qt.LeftButton, Qt.NoModifier,
                        QPoint(round(t._time_to_x(target)), 10))
                elif kind == 'drag':
                    QTest.mousePress(t, Qt.LeftButton, Qt.NoModifier,
                        QPoint(round(t._time_to_x(t.playhead_ms)), 10))
                    QTest.mouseMove(t, QPoint(round(t._time_to_x(target)), 10), 30)
                    QTest.mouseRelease(t, Qt.LeftButton, Qt.NoModifier,
                        QPoint(round(t._time_to_x(target)), 10))
                elif kind == 'subtitle':
                    p._table_activated(p.cue_model.index(4, 0))
                elif kind == 'shortcut':
                    t.setFocus()
                    QTest.keyClick(t, Qt.Key_Right, Qt.ShiftModifier)
                else:
                    p.timecode_input.setFocus()
                    p.timecode_input.selectAll()
                    QTest.keyClicks(p.timecode_input,'00:00:03.400')
                    QTest.keyClick(p.timecode_input,Qt.Key_Return)
                yield .8
                self.observe(label + '-' + kind)
                c = p.video.controller
                position = c.get_property('time-pos') if c else None
                self.check(label + '-' + kind + '-timeline', abs(t.playhead_ms-target) < 85)
                self.check(label + '-' + kind + '-media', position is not None and abs(position*1000-target) < 85)
                visible=p.subtitle_visibility_trace(reason='export_return_audit')
                self.result['events'][-1]['subtitle']=visible
                cue=next((c for c in p.project.cues if c.start_ms<=target<c.end_ms),None)
                if visible.get('owner')=='caption_scene':
                    self.check(label+'-'+kind+'-subtitle-time',set(visible.get('expected_cue_ids',[]))==({cue.id} if cue else set())
                        and set(visible.get('rendered_cue_ids',[]))==set(visible.get('expected_display_cue_ids',[])))
                else:
                    self.check(label+'-'+kind+'-subtitle-time',visible.get('cue_id','')==(cue.id if cue else '')
                        and (not cue or visible.get('foreground_owner_cue_id')==cue.id))
                if c:
                    shot = out / f'{label}-{kind}-video.png'
                    try:
                        c.command('screenshot-to-file', str(shot), 'video')
                    except Exception:
                        pass
                    if shot.is_file():
                        import av
                        import numpy as np
                        from PIL import Image
                        with av.open(p.project.media.path) as container:
                            stream = container.streams.video[0]
                            container.seek(int(target/1000/stream.time_base),stream=stream,backward=True)
                            reference = None
                            for decoded in container.decode(stream):
                                if float(decoded.pts*decoded.time_base)*1000 > target+.1: break
                                reference = decoded.to_ndarray(format='rgb24')
                        actual = np.asarray(Image.open(shot).convert('RGB'))
                        if reference is not None:
                            self.check(label+'-'+kind+'-video-pixels', actual.shape==reference.shape
                                and np.abs(actual.astype(float)-reference.astype(float)).mean()<3)
            p.video.set_paused(False)
            yield .8
            self.observe(label + '-playing')
            audio=self.result['events'][-1]['audio_observation']
            self.check(label+'-audio-position',audio.get('sink_consumed_bytes',0)>0
                and audio.get('sink_consumed_rms',0)>0
                and abs(float(audio.get('estimated_source_ms',0))-float(p.video.controller.get_property('time-pos') or 0)*1000)<100)
            self.check(label + '-play', not p.video._paused and t.playhead_ms > 6400)
            p.video.set_paused(True)
            yield .1
            self.check(label + '-pause', p.video._paused)
            original=p.project.cues[4].text
            p.select_cue(p.project.cues[4].id)
            p.cue_text.setFocus()
            QTest.keyClick(p.cue_text,Qt.Key_End,Qt.ControlModifier)
            QTest.keyClicks(p.cue_text,' edited')
            yield .7
            self.check(label+'-subtitle-edit',p.project.cues[4].text==original+' edited')
            for _ in range(20):
                if p.project.cues[4].text==original or not p.undo_stack.canUndo():break
                p.undo_stack.undo()
            self.check(label+'-subtitle-edit-undo',p.project.cues[4].text==original)
            p._zoom_timeline(.5)
            self.check(label+'-timeline-zoom',t.visible_duration_ms==4000)
            from PySide6.QtCore import QPointF
            from PySide6.QtGui import QWheelEvent
            point=QPointF(t.TRACK_HEADER_WIDTH+120,t.RULER_HEIGHT+10)
            prior=t.visible_start_ms
            QApplication.sendEvent(t,QWheelEvent(point,QPointF(t.mapToGlobal(point.toPoint())),QPoint(),QPoint(0,120),
                Qt.NoButton,Qt.AltModifier,Qt.NoScrollPhase,False))
            self.check(label+'-timeline-scroll',t.visible_start_ms!=prior)

        def run(self):
            p = self.page
            while not p.project or not p.video.controller or not p.video._media_attached or p._readiness.overlay.isVisible():
                yield .1
            yield .5
            window.grab().save(str(out / 'initial-qt.png'))
            _capture(window, out / 'initial-native.png')
            self.result['screens'] = [dict(name=s.name(), geometry=s.geometry().getRect(),
                work=s.availableGeometry().getRect(), dpr=s.devicePixelRatio(), dpi=s.logicalDotsPerInch())
                for s in QApplication.screens()]
            if os.environ.get('EXPORT_GIF_PHASE') in ('window', 'window-debug', 'window-first'):
                yield from self.windows()
                self.result['finished'] = True
                return
            if os.environ.get('EXPORT_GIF_PHASE') == 'gif':
                yield from self.gifs()
                self.result['finished'] = True
                return
            if os.environ.get('EXPORT_GIF_PHASE') == 'gif-solo':
                yield from self.gif_only()
                self.result['finished'] = True
                return
            yield from self.inputs('before')
            from ..timeline.studio_media_pool import create_video_track
            from ..timeline.selection_scope import SelectionScope
            untouched = create_video_track(p.project,'原有隐藏锁定测试轨',enabled=False,muted=True,locked=True)
            flags = lambda: [(t.id,t.enabled,t.muted,t.locked) for t in p.project.video_tracks+p.project.audio_tracks]
            labels = ('pending-cancel-back',) if os.environ.get('EXPORT_GIF_PHASE') == 'race' else ('success1', 'success2', 'cancel', 'failure', 'worker-failure')
            for label in labels:
                p.cue_controller.apply_selection_scope(SelectionScope.explicit(['c0','c1'],'c0'))
                scope_mode={'success1':'all','success2':'speaker','cancel':'current'}.get(label,'selected')
                p.style_scope.setCurrentIndex(p.style_scope.findData(scope_mode))
                p.timeline.set_visible_window(900,5500)
                expected_scope=p.selection_model.scope
                expected_flags=flags()
                expected_view=(p.timeline.visible_start_ms,p.timeline.visible_duration_ms)
                p._open_render_dialog()
                ui = p.export_workspace
                yield .4
                ui.directory.setText(str(out))
                ui.filename.setText(label)
                # Deterministic CPU encoder, short source-size output.
                ui.resolution.setCurrentIndex(0)
                idx = ui.encoder.findData('libx264')
                if idx >= 0:
                    ui.encoder.setCurrentIndex(idx)
                if label == 'failure':
                    (out / 'failure.mp4').write_bytes(b'existing output, intentionally protected')
                if label == 'worker-failure':
                    bad = out/'invalid.ass'
                    bad.write_text('deliberately invalid ASS for controlled FFmpeg failure', 'utf8')
                    original_job = ui._job
                    def faulty_job(output, settings=None):
                        job = original_job(output,settings=settings)
                        job.ass_path = str(bad)
                        return job
                    ui._job = faulty_job
                QTest.mouseClick(ui.export_button, Qt.LeftButton)
                if label == 'pending-cancel-back':
                    # The real worker queues its terminal signal before the GUI
                    # returns to Studio. A busy GUI can produce this ordering.
                    ui._cancel_export()
                    ui._worker.join(timeout=15)
                    ui._back()
                    yield .6
                    from shiboken6 import isValid
                    self.check('canvas-alive-after-pending-completion', isValid(p.video))
                    if not isValid(p.video):
                        self.result['finished'] = True
                        return
                    self.check('canvas-still-in-studio', p.video.parentWidget() is p.video_overlay_host)
                    yield from self.inputs(label)
                    continue
                if label == 'cancel':
                    yield .08
                    ui._cancel_export()
                while ui._running:
                    yield .1
                yield .4
                self.result['events'].append(dict(label=label, state=ui.pages.currentIndex(),
                    failure=ui._last_failure, output=(out / (label + '.mp4')).exists()))
                self.check(label+'-terminal-state', ui.pages.currentWidget() is
                    (ui.success_page if label.startswith('success') else ui.setup_page if label=='cancel' else ui.failure_page))
                _capture(window, out / f'{label}-export-native.png')
                ui._back()
                yield .4
                self.check(label+'-selection-preserved',p.selection_model.scope==expected_scope)
                self.check(label+'-style-scope-preserved',p.style_scope.currentData()==scope_mode)
                self.check(label+'-track-flags-preserved',flags()==expected_flags)
                self.check(label+'-view-preserved',(p.timeline.visible_start_ms,p.timeline.visible_duration_ms)==expected_view)
                self.check(label+'-return-paused',p.video._paused)
                _capture(window, out / f'{label}-return-native.png')
                yield from self.inputs(label)
            self.result['finished'] = True

        def windows(self):
            import ctypes
            from ctypes import wintypes as W
            from ..app.window_constraints import native_frame, place_on_screen
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
            user.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
            user.SetWindowPos.argtypes = [W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT]
            self.result['windows'] = []
            screens = QApplication.screens()[:1] if os.environ.get('EXPORT_GIF_PHASE') in ('window-debug','window-first') else QApplication.screens()
            for i, screen in enumerate(screens):
                place_on_screen(window, screen, Qt.WindowNoState)
                yield .6
                for state in ('normal', 'maximized', 'fullscreen', 'restored', 'resized', 'home', 'studio', 'export-open', 'export-closed'):
                    if state == 'maximized': window.showMaximized()
                    elif state == 'fullscreen': window.showFullScreen()
                    elif state == 'restored': window.showNormal()
                    elif state == 'resized': window.resize(960, 650)
                    elif state == 'home': window._return_to_settings()
                    elif state == 'studio': window._open_subtitle_studio()
                    elif state == 'export-open': self.page._open_render_dialog()
                    elif state == 'export-closed': self.page._close_export_workspace()
                    yield .55
                    if state in ('maximized','fullscreen') and os.environ.get('EXPORT_GIF_PHASE') == 'window-debug':
                        before=native_frame(window)
                        box=before['monitor' if state=='fullscreen' else 'work']
                        left,top,right,bottom=box
                        ok=user.SetWindowPos(int(window.winId()),None,left,top,right-left,bottom-top,0x0014)
                        self.result['events'].append(dict(label=state+'-SetWindowPos',ok=ok,
                            error=ctypes.get_last_error(),immediate=native_frame(window),
                            widget_min_hint=window.minimumSizeHint().toTuple(),
                            layout_min=window.layout().minimumSize().toTuple(),
                            handle_geometry=window.windowHandle().geometry().getRect()))
                        yield .5
                    name = f'window-{i}-{state}'
                    client, origin = W.RECT(), W.POINT(0, 0)
                    user.GetClientRect(int(window.winId()), ctypes.byref(client))
                    user.ClientToScreen(int(window.winId()), ctypes.byref(origin))
                    row = dict(name=name, native=native_frame(window), client=(client.right, client.bottom),
                        client_origin=(origin.x, origin.y), dpr=window.devicePixelRatioF(),
                        rect=window.rect().getRect(), layout=window.layout().contentsRect().getRect(),
                        contents=window.contentsRect().getRect(), margins=window.layout().contentsMargins().left(),
                        minimum=(window.minimumWidth(),window.minimumHeight()), maximized=window.isMaximized(),
                        fullscreen=window.isFullScreen(),
                        qwindow_min=(window.windowHandle().minimumWidth(),window.windowHandle().minimumHeight()),
                        bounds_repairs=getattr(getattr(window,'_window_bounds',None),'repairs',None))
                    dwm = ctypes.WinDLL('dwmapi')
                    dwm.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
                    color = W.DWORD()
                    hr = dwm.DwmGetWindowAttribute(int(window.winId()),34,ctypes.byref(color),ctypes.sizeof(color))
                    row['native_border'] = dict(hresult=hr,color=color.value)
                    if hr == 0:
                        from PySide6.QtGui import QPalette
                        expected = window.palette().color(QPalette.Window)
                        expected = expected.red() | expected.green()<<8 | expected.blue()<<16
                        self.check(name+'-native-border-theme',color.value==expected)
                    if state in ('maximized','fullscreen'):
                        target = row['native']['monitor' if state == 'fullscreen' else 'work']
                        surface=row['native'].get('client') or row['native']['rect']
                        self.check(name+'-screen-bounds',max(abs(a-b) for a,b in zip(surface,target))<=2)
                    self.result['windows'].append(row)
                    _capture(window, out / f'{name}.png')
                    window.grab().save(str(out / f'{name}-qt.png'))
                    outer=row['native']['rect'];surface=(origin.x,origin.y,origin.x+client.right,origin.y+client.bottom)
                    margins=(surface[0]-outer[0],surface[1]-outer[1],outer[2]-surface[2],outer[3]-surface[3])
                    row['native_sizing_margins']=margins
                    allowance=round(32*window.devicePixelRatioF()) if getattr(window,'_native_frame_active',False) else 2
                    self.check(name+'-client-fills-window',all(0<=value<=allowance for value in margins))
                    self.check(name+'-qt-fills-native-client',
                        abs(round(window.width()*window.devicePixelRatioF())-client.right)<=2
                        and abs(round(window.height()*window.devicePixelRatioF())-client.bottom)<=2)
            if os.environ.get('EXPORT_GIF_PHASE') == 'window-debug':
                window._return_to_settings()
                yield .8
                window.showNormal(); window.resize(1320,800)
                yield .5
                window.showMaximized()
                yield .8
                self.result['events'].append(dict(label='home-maximized',native=native_frame(window),
                    geometry=window.geometry().getRect(),minimum=window.minimumSize().toTuple(),
                    hint=window.minimumSizeHint().toTuple()))

        def gifs(self):
            from ..timeline.studio_clip_edit import clip_edit_command
            from ..projects.studio_project import save_project
            from ..media.animated_gif import GifFrames
            from ..timeline.clip_time_mapper import project_to_source
            p = self.page
            self.result['gif_import_ms'] = []
            for disposal in (1, 2, 3):
                before_audio = len(p.project.audio_tracks)
                began = time.perf_counter()
                if disposal == 1:
                    from PySide6.QtCore import QMimeData, QUrl, QPointF
                    from PySide6.QtGui import QDragEnterEvent, QDropEvent
                    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(out/'animation-1.gif'))])
                    enter = QDragEnterEvent(QPoint(10,100),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
                    QApplication.sendEvent(p,enter)
                    drop = QDropEvent(QPointF(10,100),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
                    QApplication.sendEvent(p,drop)
                    self.check('gif-drag-drop-accepted',enter.isAccepted() and drop.isAccepted())
                else:
                    p._begin_media_drop([out / f'animation-{disposal}.gif'], 1000)
                while p._media_ingest_state == 'LOADING':
                    yield .04
                self.result['gif_import_ms'].append((time.perf_counter()-began)*1000)
                self.check(f'gif{disposal}-import-ready', p._media_ingest_state == 'READY')
                self.check(f'gif{disposal}-no-extra-audio', len(p.project.audio_tracks) == before_audio)
                gif_asset = next(a for a in p.project.media_pool if a.canonical_source.endswith(f'animation-{disposal}.gif'))
                track = next(t for t in p.project.video_tracks if any(c.asset_id == gif_asset.asset_id for c in t.clips))
                clip = next(c for c in track.clips if c.asset_id == gif_asset.asset_id)
                self.check(f'gif{disposal}-one-cycle', clip.timeline_out_ms-clip.timeline_in_ms == 600)
                # Production undoable edit commands; source in-point and repeat
                # range must agree with both preview and the export decoder.
                p.undo_stack.push(clip_edit_command(p.project, track.id, 'move', clip_id=clip.id, start=1300))
                p.undo_stack.push(clip_edit_command(p.project, track.id, 'trim', clip_id=clip.id, start=1400, end=3400))
                p.undo_stack.undo(); p.undo_stack.redo()
                track = next(t for t in p.project.video_tracks if t.id == track.id)
                clip = next(c for c in track.clips if c.id == clip.id)
                self.check(f'gif{disposal}-trim-extended', (clip.source_in_ms, clip.source_out_ms) == (100,2100))
                source = GifFrames(gif_asset.canonical_source)
                for point in (1450, 1750, 2050, 2650, 1550):
                    p._seek(point/1000)
                    yield .65
                    runtimes = getattr(p.video_compositor, '_players', {})
                    runtime = runtimes.get(clip.id)
                    self.result['events'].append(dict(label=f'gif{disposal}-{point}',
                        runtime_keys=list(runtimes), composition=p._multitrack_preview_layers(point),
                        runtime=None if runtime is None else dict(state=runtime.state,
                            pts=runtime.pts_ms, requested=runtime.requested_ms,
                            decoder=runtime.decoder_stats() if callable(getattr(runtime,'decoder_stats',None)) else {})))
                    self.check(f'gif{disposal}-{point}-ready', runtime is not None and runtime.state == 'READY')
                    if runtime is not None and not runtime.image.isNull():
                        from PySide6.QtGui import QImage
                        actual = runtime.image.convertToFormat(QImage.Format_ARGB32)
                        (w,h,bgra), start, end, frame = source.frame_at(project_to_source(clip, point),
                            (actual.width(), actual.height()))
                        actual.save(str(out / f'gif{disposal}-{point}-decoded.png'))
                        self.check(f'gif{disposal}-{point}-frame',
                            bytes(actual.constBits()) == bgra and (actual.width(),actual.height()) == (w,h))
                        self.check(f'gif{disposal}-{point}-pts', runtime.pts_ms == start)
                _capture(window, out / f'gif{disposal}-native.png')
                runtime = p.video_compositor._players.get(clip.id)
                before_pixels = bytes(runtime.image.constBits()) if runtime is not None else b''
                yield .35
                self.check(f'gif{disposal}-pause-holds-frame', runtime is not None
                    and bytes(runtime.image.constBits()) == before_pixels and p.video._paused)
                p.video.set_paused(False)
                deadline=time.monotonic()+4
                while p.video._paused and time.monotonic()<deadline:
                    yield .05
                playing_from=p.timeline.playhead_ms
                yield .35
                self.check(f'gif{disposal}-plays', not p.video._paused and p.timeline.playhead_ms > playing_from+150)
                p.video.set_paused(True)
                yield .15
                source.close()
            p._seek(1.75)
            yield .2
            p._video_clip_selected(track.id,clip.id)
            for control,value in ((p.video_position_x,'35'),(p.video_scale_x,'55')):
                control.setFocus()
                control.lineEdit().selectAll()
                QTest.keyClicks(control.lineEdit(),value)
                QTest.keyClick(control.lineEdit(),Qt.Key_Return)
                yield .15
            selected = next(c for t in p.project.video_tracks for c in t.clips if c.id==clip.id)
            self.check('gif-transform-controls',abs(selected.transform.position_x-.35)<.001
                and abs(selected.transform.scale_x-.55)<.001)
            p._video_track_action(track.id,'enabled')
            yield .2
            self.check('gif-track-hide',not any(layer['clip_id']==clip.id for layer in p._multitrack_preview_layers(1750)))
            p.undo_stack.undo()
            yield .2
            self.check('gif-track-show-undo',any(layer['clip_id']==clip.id for layer in p._multitrack_preview_layers(1750)))
            _capture(window,out/'gif-transform-native.png')
            import psutil
            process = psutil.Process()
            memory = process.memory_info().rss
            peak = memory
            ticks = []
            previous = time.perf_counter()
            p._begin_media_drop([out/'large.gif'],4000)
            while p._media_ingest_state == 'LOADING':
                now = time.perf_counter(); ticks.append((now-previous)*1000); previous=now
                peak=max(peak,process.memory_info().rss)
                yield .02
            self.result['gif_large_import'] = dict(rgba_uncompressed_bytes=1024*576*4*120,
                rss_before=memory,rss_peak=peak,max_gui_tick_gap_ms=max(ticks,default=0),samples=len(ticks))
            self.check('gif-large-import',p._media_ingest_state=='READY')
            self.check('gif-large-bounded-memory',peak-memory < 100*1024*1024)
            self.check('gif-large-gui-responsive',max(ticks,default=0)<250)
            large_ids = {c.id for t in p.project.video_tracks for c in t.clips
                if any(a.asset_id==c.asset_id and a.canonical_source.endswith('large.gif') for a in p.project.media_pool)}
            p.undo_stack.undo()
            yield .2
            self.check('gif-delete-releases-decoder',not(large_ids & set(p.video_compositor._players)))
            saved = out / 'with-gifs.2byteproj'
            save_project(p.project, saved)
            p.open_project(saved, skip_dirty_guard=True)
            while not p._readiness.ready:
                if p._readiness.profile.get('error'):
                    raise RuntimeError(str(p._readiness.profile['error']))
                yield .1
            self.check('gif-save-reopen-assets', sum(a.canonical_source.endswith('.gif') for a in p.project.media_pool) == 3)
            selected = next(c for t in p.project.video_tracks for c in t.clips if c.id==clip.id)
            self.check('gif-transform-saved',abs(selected.transform.position_x-.35)<.001
                and abs(selected.transform.scale_x-.55)<.001)
            p._seek(1.75)
            yield .6
            p._open_render_dialog()
            ui = p.export_workspace
            yield .25
            ui.directory.setText(str(out))
            ui.filename.setText('with-gifs')
            ui.resolution.setCurrentIndex(0)
            index = ui.encoder.findData('libx264')
            if index >= 0: ui.encoder.setCurrentIndex(index)
            QTest.mouseClick(ui.export_button, Qt.LeftButton)
            while ui._running:
                yield .1
            self.check('gif-export-created', (out/'with-gifs.mp4').is_file() and not ui._last_failure)
            self.result['gif_export_error'] = ui._last_failure
            _capture(window, out / 'gif-export-native.png')
            ui._back()
            yield .3
            if (out/'with-gifs.mp4').is_file():
                self.compare_export()
            yield from self.gif_only()

        def gif_only(self):
            from ..projects.studio_project import SubtitleProject, StudioMedia, save_project
            from ..timeline.studio_clip_edit import clip_edit_command
            p=self.page
            solo = SubtitleProject(media=StudioMedia(path=str(out/'animation-2.gif'),
                duration_ms=600,width=80,height=60))
            solo.validate()
            from ..timeline.studio_edit_sequence import sequence_of
            sequence_of(solo).video_track_locked=False
            solo.video_tracks[0].locked=False
            track=solo.video_tracks[0]; clip=track.clips[0]
            edit=clip_edit_command(solo,track.id,'trim',clip_id=clip.id,start=0,end=2400)
            edit.redo()
            solo_path=out/'gif-only.2byteproj'; save_project(solo,solo_path)
            p.open_project(solo_path,skip_dirty_guard=True)
            while not p._readiness.ready:
                if p._readiness.profile.get('error'):raise RuntimeError(str(p._readiness.profile['error']))
                yield .1
            p._seek(1.4)
            yield .8
            self.check('gif-only-project-clock',p.video._clock_only and abs(p.timeline.playhead_ms-1400)<40)
            self.check('gif-only-no-audio',not any(t.clips for t in p.project.audio_tracks))
            p.video.set_paused(False)
            yield .4
            self.check('gif-only-plays',not p.video._paused and p.timeline.playhead_ms>1600)
            p.video.set_paused(True)
            _capture(window,out/'gif-only-native.png')
            p._open_render_dialog()
            ui=p.export_workspace
            self.check('gif-only-export-opens',ui is not None)
            if ui is None:return
            ui.directory.setText(str(out));ui.filename.setText('gif-only-video')
            ui.resolution.setCurrentIndex(0)
            index=ui.encoder.findData('libx264')
            if index>=0:ui.encoder.setCurrentIndex(index)
            QTest.mouseClick(ui.export_button,Qt.LeftButton)
            while ui._running:yield .1
            self.result['gif_solo_export_error']=ui._last_failure
            target=out/'gif-only-video.mp4'
            self.check('gif-only-export-created',target.is_file() and not ui._last_failure)
            ui._back()
            if not target.is_file():return
            import av
            import numpy as np
            from PIL import Image
            from ..media.animated_gif import GifFrames
            with av.open(str(target)) as container:
                stream=container.streams.video[0]
                decoded=[(float(f.pts*f.time_base)*1000,f.to_ndarray(format='rgb24')) for f in container.decode(stream)]
                self.check('gif-only-export-no-audio',not container.streams.audio)
            self.check('gif-only-variable-delay-fps',len(decoded)==24)
            source=GifFrames(out/'animation-2.gif')
            for point in (0,100,400,600,700,1400,1900,2300):
                at,pixels=min(decoded,key=lambda row:abs(row[0]-point))
                (w,h,bgra),_,_,_=source.frame_at(point)
                foreground=Image.frombytes('RGBA',(w,h),bgra,'raw','BGRA')
                expected=Image.alpha_composite(Image.new('RGBA',(w,h),(0,0,0,255)),foreground).convert('RGB')
                difference=np.abs(pixels.astype(float)-np.asarray(expected).astype(float)).mean()
                self.check(f'gif-only-{point}-pixels',abs(at-point)<1 and difference<6)
            source.close()

        def compare_export(self):
            import av
            import numpy as np
            from PySide6.QtGui import QImage, QPainter
            from ..exports.video_export import paint_layer
            from ..media.animated_gif import GifFrames
            from ..timeline.clip_time_mapper import project_to_source
            p = self.page
            def frame(path, ms):
                with av.open(str(path)) as container:
                    stream = container.streams.video[0]
                    container.seek(int(ms/1000/stream.time_base), stream=stream, backward=True)
                    chosen = None
                    for value in container.decode(stream):
                        at = float(value.pts*value.time_base)*1000
                        if at > ms+.1: break
                        chosen = value
                    if chosen is None: raise RuntimeError(f'No frame at {ms}')
                    return chosen.to_ndarray(format='bgra')
            self.result['gif_comparison'] = []
            for point in (800, 1400, 1500, 1700, 1900, 2000, 2300, 2900, 3500):
                base = frame(out/'reference.mp4',point)
                expected = QImage(base.data,640,360,640*4,QImage.Format_ARGB32).copy()
                painter = QPainter(expected)
                for layer in p._multitrack_preview_layers(point):
                    if not layer['source_path'].endswith('.gif'): continue
                    source = GifFrames(layer['source_path'])
                    (w,h,bgra),_,_,_ = source.frame_at(layer['source_ms'])
                    paint_layer(painter,640,360,QImage(bgra,w,h,w*4,QImage.Format_ARGB32),layer)
                    source.close()
                painter.end()
                actual = frame(out/'with-gifs.mp4',point)
                reference = np.frombuffer(expected.constBits(),np.uint8).reshape(360,640,4)
                difference = np.abs(actual[:,:,:3].astype(float)-reference[:,:,:3]).mean()
                expected.save(str(out/f'expected-{point}.png'))
                QImage(actual.data,640,360,640*4,QImage.Format_ARGB32).save(str(out/f'exported-{point}.png'))
                self.result['gif_comparison'].append(dict(ms=point,mae=difference))
                self.check(f'gif-export-{point}-pixels',difference<5)

    window._export_window_gif_audit = Audit()
