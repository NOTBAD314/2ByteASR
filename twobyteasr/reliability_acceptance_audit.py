"""Isolated headed evidence for startup, gain and PCM/PTS continuity."""
import hashlib
import json
import os
import time
import traceback


def start_reliability_acceptance(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from .audio_engine import _PcmRingDevice
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = {'build': vars(load_build_identity()), 'checks': {}, 'playback': []}
            self.result['startup'] = dict(getattr(getattr(self.page, '_readiness', None), 'profile', {}))
            self.started = self.last = time.perf_counter()
            self.pending = 0.
            self.capture = False
            self.pcm, self.gaps, self.rows = [], [], []
            self.win_events = []
            self.page.video.installEventFilter(self)
            self.original = _PcmRingDevice.readData
            def read(device, count):
                data = self.original(device, count)
                if self.capture and data:
                    self.pcm.append((time.perf_counter(), device._generation, bytes(data)))
                return data
            _PcmRingDevice.readData = read
            self.sequence = self.run()
            self.timer = QTimer(self)
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.setInterval(10)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def eventFilter(self, obj, event):
            if event.type() in (QEvent.Type.WinIdChange, QEvent.Type.Hide, QEvent.Type.Show):
                self.win_events.append((time.perf_counter(), event.type().name))
            return False

        def check(self, name, passed):
            self.result['checks'][name] = bool(passed)

        def tick(self):
            now = time.perf_counter()
            if self.capture:
                self.gaps.append((now-self.last)*1000)
                row = self.page.audio_engine.telemetry_snapshot()
                self.rows.append({k:row.get(k) for k in ('state','source_generation','transport_generation',
                    'effective_rate','requested_source_ms','estimated_source_ms','drift_ms','buffer_bytes',
                    'sink_consumed_bytes','decoded_bytes','decoder_eof','underruns','output_device')})
            self.last = now
            try:
                if now-self.started > 240:
                    raise TimeoutError('reliability audit timeout')
                if callable(self.pending):
                    if not self.pending(): return
                elif now < self.pending: return
                value = next(self.sequence)
                self.pending = value if callable(value) else time.perf_counter()+float(value)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def run(self):
            page = self.page
            gate = getattr(page, '_readiness', None)
            self.check('readiness_complete', gate is not None and gate.ready)
            # Native/Qt capture and activateWindow enqueue extra paints; keep
            # them outside the first-interaction measurement entirely.
            self.last = time.perf_counter()
            profiler = None
            if os.environ.get('TWOBYTEASR_READINESS_PROFILE') == '1':
                import cProfile
                for widget in QApplication.allWidgets():
                    for key,value in vars(widget).items():
                        if isinstance(value,QTimer):
                            value.setObjectName(f'{widget.metaObject().className()}.{key}')
                class EventProbe(QObject):
                    def __init__(self):
                        super().__init__();self.last=None;self.spans=[]
                    def eventFilter(self, obj, event):
                        now=time.perf_counter()
                        if self.last is not None and now-self.last[0]>.025:
                            self.spans.append({'ms':(now-self.last[0])*1000,'previous':self.last[1],
                                               'next':(obj.metaObject().className(),obj.objectName(),event.type().name)})
                        parent=obj.parent()
                        self.last=(now,(obj.metaObject().className(),obj.objectName(),event.type().name,
                                        parent.metaObject().className() if parent is not None else None))
                        return False
                event_probe=EventProbe()
                QApplication.instance().installEventFilter(event_probe)
                profiler = cProfile.Profile()
                profiler.enable()
            self.capture = True
            page.timeline.set_visible_window(0, 3000)
            yield 1.0
            self.result['first_zoom_gaps_ms'] = list(self.gaps)
            if profiler is not None:
                profiler.disable()
                QApplication.instance().removeEventFilter(event_probe)
                self.result['event_spans']=event_probe.spans
                profiler.dump_stats(str(output/'first-zoom.prof'))
                self.result['profile_only'] = True
                return
            self.check('first_zoom_under_100ms', max(self.gaps, default=0) <= 100)
            self.gaps=[];self.last=time.perf_counter()
            for index in range(30):
                duration=3000+int(2000*(index%10)/9)
                page.timeline.set_visible_window(index*20,duration)
                yield .04
            self.result['continuous_zoom_gaps_ms']=list(self.gaps)
            ordered=sorted(self.gaps)
            self.result['continuous_zoom_p95_ms']=ordered[int(.95*(len(ordered)-1))]
            self.check('continuous_zoom_p95_under_16_7ms',self.result['continuous_zoom_p95_ms']<=16.7)
            self.capture = False
            if os.environ.get('TWOBYTEASR_INTERACTION_ONLY')=='1':
                self.result['interaction_only']=True
                return
            page.timeline.set_visible_window(0, 6000)
            for rate in (1., 2., 4.):
                page.video.set_paused(True)
                page._seek(0.)
                page._shuttle_speed = rate
                page.video.set_speed(rate)
                yield .35
                self.pcm, self.gaps, self.rows = [], [], []
                capture_name=f'endpoint-{rate:g}x'
                page.audio_engine.capture_pcm(capture_name,True)
                yield lambda:(output/f'{capture_name}.started').is_file()
                for player in page.video_compositor._players.values(): player.samples.clear()
                self.capture = True
                self.last = time.perf_counter()
                start = time.perf_counter()
                page.video.set_paused(False)
                yield 6/rate + .65
                self.capture = False
                page.video.set_paused(True)
                page.audio_engine.capture_pcm(capture_name,False)
                yield lambda:(output/f'{capture_name}.json').is_file()
                from .audio_pcm_audit import read_capture
                self.pcm=read_capture(output,capture_name)
                data = b''.join(x[2] for x in self.pcm)
                (output/f'pcm-{rate:g}x.s16le').write_bytes(data)
                frames = {key:list(player.samples) for key,player in page.video_compositor._players.items()}
                monotonic = all(all(b['pts_ms'] >= a['pts_ms'] for a,b in zip(rows,rows[1:])) for rows in frames.values())
                info = {'rate':rate, 'bytes':len(data), 'generations':sorted({x[1] for x in self.pcm}),
                    'startup_ms':(self.pcm[0][0]-start)*1000 if self.pcm else None,
                    'gui_gaps_ms':list(self.gaps), 'audio':list(self.rows), 'video':frames,
                    'chunks':[{'wall_ms':(t-start)*1000,'generation':g,'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for t,g,v in self.pcm]}
                elapsed=0.;first_play=[]
                for gap in self.gaps:
                    if elapsed>=500:break
                    first_play.append(gap);elapsed+=gap
                info['first_play_gui_max_ms']=max(first_play,default=0.)
                self.check(f'first_play_under_100ms_{rate:g}x',info['first_play_gui_max_ms']<=100)
                ordered=sorted(self.gaps)
                info['gui_p95_ms']=ordered[int(.95*(len(ordered)-1))]
                self.check(f'continuous_play_p95_under_16_7ms_{rate:g}x',info['gui_p95_ms']<=16.7)
                self.result['playback'].append(info)
                self.check(f'one_generation_{rate:g}x', len(info['generations']) == 1)
                self.check(f'video_monotonic_{rate:g}x', monotonic)
                self.check(f'pcm_complete_{rate:g}x', abs(len(data)-round(1152000/rate)) <= 4096)
                hashes=[x['sha256'] for x in info['chunks'] if x['wall_ms']<1000/rate and x['bytes']>=512]
                self.check(f'first_second_unique_pcm_{rate:g}x',len(hashes)>3 and len(hashes)==len(set(hashes)))
                yield .1
            window.grab().save(str(output/'ready-ui.png'))
            self.result['transport_matrix']=[]
            for mode in ('v1','v2','both'):
                for index,track in enumerate(page.project.video_tracks):
                    enabled=index<2 and (mode=='both' or index==(0 if mode=='v1' else 1))
                    track.enabled=enabled
                    for group in page.project.av_track_groups:
                        if group.video_track_id==track.id:
                            next(t for t in page.project.audio_tracks if t.id==group.audio_track_id).muted=not enabled
                for rate in (1.,2.,4.):
                    for target in (0.,2.):
                        page.video.set_paused(True);page._seek(target)
                        page._shuttle_speed=rate;page.video.set_speed(rate)
                        yield lambda:page._playback_buffers_ready()
                        capture_name=f'matrix-{mode}-{rate:g}-{target:g}'
                        page.audio_engine.capture_pcm(capture_name,True)
                        yield lambda:(output/f'{capture_name}.started').is_file()
                        self.pcm=[];self.capture=True
                        for player in page.video_compositor._players.values():player.samples.clear()
                        page.video.set_paused(False);yield 1.1/rate
                        page.video.set_paused(True);self.capture=False
                        page.audio_engine.capture_pcm(capture_name,False)
                        yield lambda:(output/f'{capture_name}.json').is_file()
                        self.pcm=read_capture(output,capture_name)
                        frames=[list(p.samples) for p in page.video_compositor._players.values()]
                        monotonic=all(all(b['pts_ms']>=a['pts_ms'] for a,b in zip(rows,rows[1:])) for rows in frames)
                        generations=sorted({x[1] for x in self.pcm})
                        row={'mode':mode,'rate':rate,'start_seconds':target,'bytes':sum(len(x[2]) for x in self.pcm),
                             'generations':generations,'video_monotonic':monotonic}
                        self.result['transport_matrix'].append(row)
                        self.check(f'matrix-{mode}-{rate:g}-{target:g}',row['bytes']>4096 and len(generations)==1 and monotonic)
            # Cut-start, pause/resume and rapid transport toggles on both V2
            # ownership modes. The cut exists in the actual clip/audio graph.
            from dataclasses import replace
            original_clips=page.project.video_tracks[1].clips
            original_clip=original_clips[0]
            page.project.video_tracks[1].clips=[
                replace(original_clip,source_out_ms=2000,timeline_out_ms=2000),
                replace(original_clip,id=original_clip.id+'-cut',source_in_ms=2000,timeline_in_ms=2000)]
            self.result['discontinuity_matrix']=[]
            for mode in ('v2','both'):
                for index,track in enumerate(page.project.video_tracks):
                    enabled=index==1 or (mode=='both' and index==0)
                    track.enabled=enabled
                    for group in page.project.av_track_groups:
                        if group.video_track_id==track.id:
                            next(t for t in page.project.audio_tracks if t.id==group.audio_track_id).muted=not enabled
                for rate in (1.,2.,4.):
                    for action in ('cut','resume','rapid'):
                        page.video.set_paused(True);page._seek(2.)
                        page._shuttle_speed=rate;page.video.set_speed(rate)
                        yield lambda:page._playback_buffers_ready()
                        name=f'{mode}-{rate:g}-{action}'
                        page.audio_engine.capture_pcm(name,True)
                        yield lambda:(output/f'{name}.started').is_file()
                        for player in page.video_compositor._players.values():player.samples.clear()
                        page.video.set_paused(False)
                        if action=='resume':
                            yield .2/rate
                            page.video.set_paused(True);yield .05
                            page.video.set_paused(False)
                        elif action=='rapid':
                            for _ in range(3):
                                yield .02
                                page.video.set_paused(True);yield .02
                                page.video.set_paused(False)
                        yield .65/rate
                        page.video.set_paused(True)
                        page.audio_engine.capture_pcm(name,False)
                        yield lambda:(output/f'{name}.json').is_file()
                        chunks=read_capture(output,name)
                        frames=[list(p.samples) for p in page.video_compositor._players.values()]
                        monotonic=all(all(b['pts_ms']>=a['pts_ms'] for a,b in zip(rows,rows[1:])) for rows in frames)
                        hashes=[hashlib.sha256(x[2]).hexdigest() for x in chunks if len(x[2])>=512]
                        generations=sorted({x[1] for x in chunks})
                        row={'mode':mode,'rate':rate,'action':action,'bytes':sum(len(x[2]) for x in chunks),
                             'generations':generations,'video_monotonic':monotonic,'pcm_unique':len(hashes)==len(set(hashes)),
                             'video_frames':sum(map(len,frames)), 'video_samples':frames,
                             'decoder_state':[p.performance_snapshot() for p in page.video_compositor._players.values()]}
                        self.result['discontinuity_matrix'].append(row)
                        self.check(name,row['bytes']>4096 and len(generations)==1 and monotonic and row['pcm_unique'] and row['video_frames']>0)
            page.project.video_tracks[1].clips=original_clips
            for track in page.project.video_tracks:track.enabled=True
            for track in page.project.audio_tracks:track.muted=False
            for playing in (False, True):
                window.raise_(); window.activateWindow()
                for index in range(15):
                    page._seek(1.)
                    page._shuttle_speed = 1.
                    page.video.set_speed(1.)
                    page.video.set_paused(not playing)
                    yield .15
                    before = int(page.video.winId())
                    self.win_events.clear()
                    from .studio_track_gain import show_track_gain
                    show_track_gain(page, 'A2')
                    yield .15
                    dialog = page._track_gain_dialog
                    self.check(f'G_no_backdrop_{playing}_{index}', dialog._modal_backdrop is None)
                    page.video.controller.screenshot_to_file(output/f'gain-{playing}-{index}-native.png')
                    if index == 0:
                        if os.environ.get('TWOBYTEASR_VISUAL_REVIEW') == '1':
                            (output/'gain-review.txt').write_text(str(playing),encoding='ascii')
                            yield lambda:(output/f'gain-reviewed-{playing}').is_file()
                            if playing:
                                page.video.set_paused(True);page._seek(1.)
                                yield lambda:page._playback_buffers_ready()
                                page.video.set_paused(False);yield .12
                                page.video.controller.screenshot_to_file(output/'gain-playing-reviewed-native.png')
                        from PIL import ImageGrab
                        # Desktop capture includes the native child and modal;
                        # QWidget.grab cannot provide this evidence.
                        import ctypes
                        from ctypes import wintypes
                        bounds=wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(window.winId())),ctypes.byref(bounds))
                        ImageGrab.grab(bbox=(bounds.left,bounds.top,bounds.right,bounds.bottom),all_screens=True).save(output/f'gain-{playing}-desktop.png')
                        from .studio_widgets import ScrubDoubleSpinBox
                        from .studio_track_gain import track_gain_db
                        spin=dialog.findChild(ScrubDoubleSpinBox,'trackGainDb')
                        before_gain=track_gain_db(page.project,'A2')
                        before_undo=page.undo_stack.count()
                        before_generation=page.audio_engine.telemetry_snapshot().get('source_generation')
                        edit=spin.lineEdit();origin=QPointF(edit.rect().center())
                        def mouse(kind,point,mods=Qt.KeyboardModifier.NoModifier):
                            QApplication.sendEvent(edit,QMouseEvent(kind,point,QPointF(edit.mapToGlobal(point.toPoint())),
                                Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,mods))
                        mouse(QEvent.Type.MouseButtonPress,origin)
                        mouse(QEvent.Type.MouseMove,origin+QPointF(24,0))
                        mouse(QEvent.Type.MouseButtonRelease,origin+QPointF(24,0))
                        yield .15
                        self.check(f'G_drag_preview_only_{playing}',spin.value()==before_gain+6 and
                            track_gain_db(page.project,'A2')==before_gain and page.undo_stack.count()==before_undo)
                        self.check(f'G_gain_keeps_decoder_{playing}',
                            page.audio_engine.telemetry_snapshot().get('source_generation')==before_generation)
                        if playing:
                            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
                            yield lambda: page._track_gain_dialog is None
                            self.check('G_apply_one_undo',page.undo_stack.count()==before_undo+1)
                            page.undo_stack.undo()
                            yield .1
                        else:
                            dialog.reject()
                            yield lambda: page._track_gain_dialog is None
                            self.check('G_cancel_restores',track_gain_db(page.project,'A2')==before_gain and not page._gain_preview_values)
                    self.check(f'G_stable_winid_{playing}_{index}', int(page.video.winId()) == before and not self.win_events)
                    if index != 0: dialog.reject()
                    yield .16
            page.video.set_paused(True)
            at = page.video._playback_clock.presentation_position_ms()
            yield .5
            self.result['pause_delta_ms'] = page.video._playback_clock.presentation_position_ms()-at
            self.check('pause_exact_anchor', abs(self.result['pause_delta_ms']) < 1)
            if gate is not None:
                path=gate.path
                identity=id(page.project)
                gate.begin(path)
                self.result['hot_startup']=dict(gate.profile)
                self.check('hot_reentry_reuses_project',id(page.project)==identity and gate.profile['kind']=='hot')
                controller=page.video.controller
                page.show_project_hub(skip_dirty_guard=True)
                window._switch_page(0)
                yield .1
                reopened=time.perf_counter()
                window.open_studio_project(path,mode='edit',source='reliability-home-reentry')
                yield lambda:gate.ready
                self.result['home_reentry']={**gate.profile,
                    'wall_ms':(time.perf_counter()-reopened)*1000,
                    'reused_mpv':page.video.controller is controller}
                self.check('home_reentry_ready',page.project is not None and gate.ready)
                self.check('home_reentry_reuses_mpv',page.video.controller is controller)
                broken=output/'invalid.2byteproj';broken.write_text('{bad json',encoding='utf8')
                gate.begin(broken,skip_dirty_guard=True)
                yield lambda: 'error' in gate.profile
                self.check('load_failure_has_stage_and_retry',gate.retry.isVisible() and not gate.active)
                gate.path=path;gate.retry.click()
                yield lambda: gate.ready
                self.check('load_retry_ready',gate.ready)
            self.result['user_gates'] = ['new OAuth', 'speaker listening; PCM is device submission, not loopback']

        def finish(self):
            self.timer.stop()
            _PcmRingDevice.readData = self.original
            (output/'reliability-acceptance.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf8')
            window._acceptance_closing = True
            self.page.close_page()
            window.hide()
            QTimer.singleShot(200, QApplication.instance().quit)

    window._reliability_audit = Audit()
