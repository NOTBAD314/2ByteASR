"""Opt-in real-project timeline paints, input latency, CPU and page lifecycle.

Qt paint completion is reported as such. It is not a physical display FPS.
No product timers are replaced. cProfile runs are kept separate.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import statistics
import time
import traceback


def distribution(values):
    v = sorted(values)
    if not v:
        return {'n': 0}
    def q(f):
        return round(v[min(len(v)-1, max(0, __import__('math').ceil(len(v)*f)-1))], 3)
    return dict(n=len(v), p50=q(.5), p95=q(.95), p99=q(.99), max=round(v[-1], 3), mean=round(statistics.fmean(v), 3))


def start(window, out):
    import psutil
    from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = None
            self.phase = ''
            self.frames = []
            self.inputs = []
            self.update_callers = {}
            self.result = dict(phases={}, checks={}, error='', lifecycle=[], av=[], source_sha256={})
            self.process = psutil.Process()
            self.sequence = self.run()
            self.pending = 0
            self.started = time.perf_counter()
            if os.environ.get('TIMELINE_AUDIT_PROFILE')=='1':
                import faulthandler
                self.stack_file=(out/'all-thread-stacks.txt').open('w')
                faulthandler.dump_traceback_later(.5,repeat=True,file=self.stack_file)
            self.last_beat = self.started
            self.beats = []
            self.timer = QTimer(self)
            self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.timeout.connect(self.tick)
            self.timer.start(4)

        def tick(self):
            now = time.perf_counter()
            self.beats.append((now, (now-self.last_beat)*1000))
            self.last_beat = now
            try:
                if self.page is not None and window.isMinimized():
                    raise RuntimeError('Audit window was minimized; its presentation measurements are invalid')
                if now-self.started > 540:
                    raise TimeoutError('timeline audit')
                if now < self.pending:
                    return
                # Preserve the requested 60 Hz cadence without adding handler
                # time to every interval. Bound catch-up after a real stall.
                due = self.pending if 0 < now-self.pending < .03 else now
                self.pending = due + next(self.sequence)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def state(self):
            t = self.page.timeline
            return [t.visible_start_ms, t.visible_duration_ms, t.playhead_ms, sorted(t.selected_ids),
                [(key,value.start_ms,value.end_ms) for key,value in sorted(t._timing_preview.items())]]

        def paint(self, kind, action):
            begin = time.perf_counter()
            action()
            self.frames.append(dict(at=time.perf_counter(), ms=(time.perf_counter()-begin)*1000,
                phase=self.phase, kind=kind, state=self.state()))

        def action(self, name, fn):
            begin = time.perf_counter()
            fn()
            self.inputs.append(dict(at=begin, end=time.perf_counter(), name=name, phase=self.phase, state=self.state()))

        def mouse(self, kind, x, y, modifiers=Qt.NoModifier):
            t = self.page.timeline
            point = QPointF(x, y)
            button = Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton
            buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
            QApplication.sendEvent(t, QMouseEvent(kind, point, QPointF(t.mapToGlobal(point.toPoint())), button, buttons, modifiers))

        def wheel(self, delta, ctrl=False):
            from PySide6.QtCore import QPoint
            t = self.page.timeline
            point = QPointF(t.TRACK_HEADER_WIDTH+400, t.RULER_HEIGHT+80)
            event = QWheelEvent(point, QPointF(t.mapToGlobal(point.toPoint())), QPoint(), QPoint(0, delta),
                Qt.NoButton, Qt.ControlModifier if ctrl else Qt.AltModifier, Qt.NoScrollPhase, False)
            QApplication.sendEvent(t, event)

        def phase_run(self, name, body):
            self.phase = name
            print('TIMELINE_PHASE', name, flush=True)
            start = time.perf_counter()
            cpu = sum(self.process.cpu_times()[:2])
            profiler = None
            if os.environ.get('TIMELINE_AUDIT_PROFILE') == '1':
                import cProfile
                profiler = cProfile.Profile()
                profiler.enable()
            yield from body()
            yield .15
            if profiler:
                import io, pstats
                profiler.disable()
                stream = io.StringIO()
                pstats.Stats(profiler, stream=stream).sort_stats('cumtime').print_stats(70)
                (out / (name+'-profile.txt')).write_text(stream.getvalue(), 'utf8')
            end = time.perf_counter()
            frames = [f for f in self.frames if f['phase'] == name]
            # Cursor overlay and parent can paint the same state. Count distinct
            # state changes once, keeping parent/overlay durations separately.
            changes = []
            for f in frames:
                if not changes or f['state'] != changes[-1]['state']:
                    changes.append(f)
            inputs = [i for i in self.inputs if i['phase'] == name]
            active_start = inputs[0]['at'] if inputs else start+1.5
            active_end = inputs[-1]['end']+.02 if inputs else end-.4
            active = [f for f in changes if active_start <= f['at'] <= active_end]
            intervals = [(b['at']-a['at'])*1000 for a,b in zip(active,active[1:])]
            latencies = []
            for i in inputs:
                if i['name'] in {'horizontal-wheel','ctrl-wheel'}:
                    matches=lambda f:f['kind']=='base' and f['state'][:2]==i['state'][:2]
                elif i['name'] in {'ruler-drag','ruler-release','jump-seek'}:
                    matches=lambda f:f['state'][2]==i['state'][2]
                else:
                    matches=lambda f:f['state']==i['state']
                frame = next((f for f in frames if f['at'] >= i['at'] and matches(f)), None)
                if frame:
                    latencies.append((frame['at']-i['at'])*1000)
            self.result['phases'][name] = dict(seconds=end-start, cpu_s=sum(self.process.cpu_times()[:2])-cpu,
                painted_state_changes=len(changes), changes_per_second=len(changes)/max(.001,end-start),
                active_seconds=active_end-active_start, active_changes_per_second=len(active)/max(.001,active_end-active_start),
                update_intervals_ms=distribution(intervals), input_to_paint_ms=distribution(latencies),
                input_handler_ms=distribution([(i['end']-i['at'])*1000 for i in inputs]),
                coalesced_or_unpainted_inputs=len(inputs)-len(latencies),
                main_thread_gaps_ms=distribution([ms for at,ms in self.beats if start <= at <= end]),
                gaps_over_50ms=sum(ms>50 for at,ms in self.beats if start <= at <= end),
                gaps_over_100ms=sum(ms>100 for at,ms in self.beats if start <= at <= end),
                parent_paint_ms=distribution([f['ms'] for f in frames if f['kind']=='base']),
                cursor_paint_ms=distribution([f['ms'] for f in frames if f['kind']=='cursor']))
            self.result['phases'][name]['base_invalidations'] = self.update_callers.get(name,{})
            self.result['phases'][name]['timeline_visible']=self.page.timeline.isVisible()
            self.result['phases'][name]['window_minimized']=window.isMinimized()
            self.result['phases'][name].update(start=start,end=end)
            self.save()

        def gesture(self, kind):
            t = self.page.timeline
            t.set_visible_window(120000, int(os.environ.get('TIMELINE_AUDIT_SPAN','60000')))
            yield .3
            if kind == 'scroll':
                for i in range(100):
                    self.action('horizontal-wheel', lambda i=i:self.wheel(-120 if i<50 else 120))
                    yield 1/60
            elif kind == 'zoom':
                for i in range(60):
                    self.action('ctrl-wheel', lambda i=i:self.wheel(120 if i%2==0 else -120,True))
                    yield 1/60
            elif kind == 'scrub':
                self.mouse(QEvent.MouseButtonPress, t.TRACK_HEADER_WIDTH+70, 15)
                for i in range(100):
                    self.action('ruler-drag', lambda i=i:self.mouse(QEvent.MouseMove,t.TRACK_HEADER_WIDTH+70+i*6,15))
                    yield 1/60
                self.action('ruler-release', lambda:self.mouse(QEvent.MouseButtonRelease,t.TRACK_HEADER_WIDTH+664,15))
                yield .8
            else:
                tracks,_,_ = t._track_layout()
                items = [(c,t._cue_band(c,tracks[c.speaker_id])) for c in t.visible_cues()
                    if c.speaker_id in tracks and c.end_ms-c.start_ms>800]
                def movable(item):
                    cue,rect=item
                    point=QPointF((t._time_to_x(cue.start_ms)+t._time_to_x(cue.end_ms))/2,rect.center().y())
                    hit,mode=t._cue_at(point)
                    return hit is not None and hit.id==cue.id and mode=='move' and t._caption_seam_at(point) is None
                items=[item for item in items if movable(item)]
                if not items:
                    raise AssertionError('No visible caption')
                c,rect = items[len(items)//2]
                x = (t._time_to_x(c.start_ms)+t._time_to_x(c.end_ms))/2
                y = rect.center().y()
                if kind == 'multidrag':
                    ids=list(dict.fromkeys([c.id,*[item.id for item,_ in items]]))[:8]
                    t.set_selected_ids(ids,c.id)
                    yield .15
                else:
                    ids=[c.id]
                    t.set_selected_ids(ids,c.id)
                    yield .15
                before={item.id:(item.start_ms,item.end_ms,item.speaker_id) for item in self.page.project.cues if item.id in ids}
                untouched={item.id:(item.start_ms,item.end_ms,item.speaker_id) for item in self.page.project.cues if item.id not in ids}
                self.action('caption-press',lambda:self.mouse(QEvent.MouseButtonPress,x,y))
                for i in range(70):
                    self.action('caption-drag',lambda i=i:self.mouse(QEvent.MouseMove,x+i*1.2,y))
                    yield 1/60
                self.result.setdefault('timing_preview',{})[self.phase] = list(t.timing_preview_metrics)
                self.action('caption-release',lambda:self.mouse(QEvent.MouseButtonRelease,x+82.8,y))
                yield .3
                after={item.id:(item.start_ms,item.end_ms,item.speaker_id) for item in self.page.project.cues if item.id in ids}
                shifts={after[key][0]-value[0] for key,value in before.items()}
                self.result['checks'][self.phase+'_rigid_move']=len(shifts)==1 and next(iter(shifts),0)!=0 and all(
                    after[key][1]-value[1]==after[key][0]-value[0] for key,value in before.items())
                self.result['checks'][self.phase+'_only_selected_move']=all((item.start_ms,item.end_ms,item.speaker_id)==untouched[item.id]
                    for item in self.page.project.cues if item.id in untouched)
                self.result.setdefault('selection_moves',{})[self.phase]=dict(selected=len(ids),before=before,after=after)
                if self.page.undo_stack.canUndo():
                    self.page._undo_interactive()
                yield .3
                self.result['checks'][self.phase+'_undo_restores_ranges']=all((item.start_ms,item.end_ms,item.speaker_id)==before[item.id]
                    for item in self.page.project.cues if item.id in before)

        def playback(self, follow):
            page,t = self.page,self.page.timeline
            page.video.set_paused(True)
            page.follow_playhead_toggle.setChecked(follow)
            page._set_speed(1.)
            page._seek(180.)
            t.set_visible_window(176000 if follow else 178000, 5000 if follow else 60000)
            t._follow_suspended_until = 0
            yield .7
            page._toggle_playback()
            deadline=time.perf_counter()+12
            while page.video._paused and time.perf_counter()<deadline:yield .05
            if page.video._paused:raise RuntimeError('Playback never left its startup/seek hold')
            begin = time.perf_counter()
            while time.perf_counter()-begin < (3 if os.environ.get('TIMELINE_AUDIT_QUICK')=='1' else 7):
                snap = page.video._playback_clock.sample_presentation(source='timeline-audit')
                tele = dict(getattr(getattr(page,'audio_engine',None),'_telemetry',{}) or {})
                self.result['av'].append(dict(at=time.perf_counter(),phase=self.phase,
                    playhead_ms=t.playhead_ms,presentation_ms=snap.presentation_media_ms,audio=tele,
                    timeline_visible=t.isVisible(),video_paused=page.video._paused,
                    video_timer=page.video._timer.isActive(),window_minimized=window.isMinimized()))
                yield .1
            controller = page.video.controller
            self.result.setdefault('video',{})[self.phase] = {key:controller.observed_property(key,None) for key in
                ('time-pos','frame-drop-count','decoder-frame-drop-count','avsync','estimated-vf-fps')}
            page.video.set_paused(True)
            yield .2

        def seeks(self):
            page=self.page
            page.video.set_paused(True)
            for target in (90.,181.,247.):
                self.action('jump-seek',lambda target=target:page._seek(target))
                deadline=time.perf_counter()+5
                while time.perf_counter()<deadline:
                    snap=page.video._playback_clock.sample_presentation(source='timeline-audit-seek')
                    if abs(snap.presentation_media_ms-target*1000)<100:break
                    yield .05
                yield .15
                value=page.timeline.playhead_ms
                self.result['checks']['seek_'+str(target)+'_'+self.phase]=abs(value-target*1000)<100
                yield .1

        def real_controls(self):
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QPushButton
            from ..glossary.proofread_policy import repetition_cleanup
            page=self.page
            original={c.id:c.text for c in page.project.cues}
            self.result['cues']=len(original)
            window._show_glossary_proofread(page.project_path,page.project,studio=page)
            review=window.glossary_proofread_page
            if not review.stutter_toggle.isChecked():QTest.mouseClick(review.stutter_toggle,Qt.LeftButton)
            deadline=time.perf_counter()+120
            while review.checks_running() and time.perf_counter()<deadline:yield .05
            self.result['checks']['real_checks_finished']=not review.checks_running()
            self.result['checks']['real_batch_visible_initial']=not review._batch_selected and not any(
                b.text()=='批量选择' for b in review.findChildren(QPushButton))
            targets=('153','170','292')
            self.result['real_cleanup']={c:dict(text=review._by_id[c]['base'],
                before=[i['kind'] for i in review._unresolved(review._by_id[c])]) for c in targets}
            self.result['checks']['three_real_samples_have_cleanup']=all(any(repetition_cleanup(i,review._by_id[c]['base'])
                for i in review._unresolved(review._by_id[c])) for c in targets)
            review._batch_selected=set(targets);review._batch_update()
            QTest.mouseClick(review.stutter_toggle,Qt.LeftButton)
            yield .1
            self.result['checks']['real_disabled_selection_pruned']=review._batch_selected=={
                c for c in targets if review._unresolved(review._by_id[c])}
            self.result['checks']['real_all_effective_sets_exclude_cleanup']=all(not repetition_cleanup(i,row['base'])
                for row in review._rows for i in review._unresolved(row))
            cleanup_only={c for c in targets if not review._unresolved(review._by_id[c])}
            review.filter_buttons['suggested'].click();review._apply_filter()
            visible={review._rows[n]['cue_id'] for n in review.list.visible}
            self.result['checks']['real_suggested_filter_matches_remaining_issues']=all((c in visible)==bool(
                review._unresolved(review._by_id[c])) for c in targets)
            review.filter_buttons['all'].click();review._apply_filter()
            for adopt in (review._batch_adopt,lambda:review._set_all(True)):
                review._batch_select_all();index=review._stack.index();adopt()
                self.result['checks']['real_bulk_preserves_reported_repeats_'+str(index)]=all(
                    next(c.text for c in page.project.cues if c.id==identity)==original[identity] for identity in cleanup_only)
                if review._stack.index()>index:review._undo()
            self.result['checks']['real_document_text_restored']={c.id:c.text for c in page.project.cues}==original
            self.result['checks']['real_term_rows_are_words_only']=all(review.term_list.item(i).text()==
                review.term_list.item(i).data(Qt.UserRole+1).canonical for i in range(review.term_list.count()))
            for c in targets:
                self.result['real_cleanup'][c]['after']=[i['kind'] for i in review._unresolved(review._by_id[c])]
                review.list.ensure_visible(c);yield .1
                _capture(window,out/('real-cleanup-'+c+'.png'))
            review._back();yield .2
            self.result['checks']['real_returned_to_workbench']=page.isVisible() and not review.isVisible()

        def run(self):
            from ..test_isolation import require_isolated_paths
            self.result['isolated_paths']={k:str(v) for k,v in require_isolated_paths('controls-timeline',emit=lambda *_:None).items()}
            yield .5
            window.open_studio_project(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            deadline = time.perf_counter()+80
            while time.perf_counter()<deadline:
                self.page = window.built_page('studio')
                if self.page and self.page.project and self.page._readiness.ready:
                    break
                yield .1
            page = self.page
            self.result['checks']['ready'] = bool(page and page.project and page._readiness.ready)
            if not self.result['checks']['ready']:
                raise AssertionError('Studio not ready')
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            if os.environ.get('TIMELINE_AUDIT_REVIEW_ONLY')=='1':
                yield from self.real_controls()
                self.result['finished']=True
                return
            t = page.timeline
            original = t._paint_timeline
            t._paint_timeline = lambda event:self.paint('base',lambda:original(event))
            import sys
            original_update = t.update
            def update(*args):
                caller = sys._getframe(1)
                key = Path(caller.f_code.co_filename).name+':'+str(caller.f_lineno)+':'+caller.f_code.co_name
                counts = self.update_callers.setdefault(self.phase,{})
                counts[key] = counts.get(key,0)+1
                return original_update(*args)
            t.update = update
            overlay = type(t._transport_overlay)
            original_cursor = overlay.paintEvent
            overlay.paintEvent = lambda obj,event:self.paint('cursor',lambda:original_cursor(obj,event)) if obj is t._transport_overlay else original_cursor(obj,event)
            import hashlib,sys
            for name,module in tuple(sys.modules.items()):
                file = getattr(module,'__file__',None)
                if name.startswith('twobyteasr') and file and file.endswith('.py'):
                    self.result['source_sha256'][name] = hashlib.sha256(Path(file).read_bytes()).hexdigest()
            self.result.update(cues=len(page.project.cues),window=[window.width(),window.height()],
                timeline=[t.width(),t.height()],dpr=t.devicePixelRatioF(),screen_hz=window.screen().refreshRate(),
                measurement='Qt completed paint/state changes; not physical scan FPS',profile=os.environ.get('TIMELINE_AUDIT_PROFILE')=='1')
            self.result['initial_timers']=len(page.findChildren(QTimer))
            yield 6
            self.result['checks']['waveform_ready'] = t.waveform_state == 'READY'
            _capture(window,out/'01-before.png')
            self.probe = None
            if os.environ.get('TIMELINE_AUDIT_VISIBLE') == '1':
                import ctypes,subprocess,sys
                from ctypes import wintypes as W
                from PySide6.QtCore import QPoint
                from PySide6.QtGui import QColor
                if os.environ.get('TIMELINE_AUDIT_STRIP')=='1':
                    from PySide6.QtCore import QRect
                    from PySide6.QtGui import QRegion
                    window.setMask(QRegion(QRect(t.mapTo(window,QPoint()),t.size())))
                    api=ctypes.windll.user32
                    api.SetWindowPos.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
                    if not api.SetWindowPos(ctypes.c_void_p(int(window.winId())),ctypes.c_void_p(-1),0,0,0,0,0x0013):
                        raise ctypes.WinError()
                    self.result['timeline_only_topmost']=True
                window.raise_();window.activateWindow()
                rect=W.RECT();origin=W.POINT(0,0)
                user=ctypes.windll.user32
                user.GetClientRect(ctypes.c_void_p(int(window.winId())),ctypes.byref(rect))
                user.ClientToScreen(ctypes.c_void_p(int(window.winId())),ctypes.byref(origin))
                scale=rect.right/window.width()
                pos=t.mapTo(window,QPoint(0,0));x=origin.x+round(pos.x()*scale);y=origin.y+round(pos.y()*scale)
                width=round(t.width()*scale);height=round(t.height()*scale)
                left=round(t.TRACK_HEADER_WIDTH*scale)
                # Sample the actual playhead below its ruler label. No
                # painted counters are added; video telemetry is separate.
                color=QColor(t._timeline_palette().playhead)
                config={'pid':os.getpid(),'bgr':[color.blue(),color.green(),color.red()],
                    'rects':{'cursor':[x+left,y+round((t.RULER_HEIGHT+8)*scale),width-left-24,5],
                        'timeline':[x,y,width,height]}}
                (out/'pixel-config.json').write_text(json.dumps(config),'utf8')
                self.probe=subprocess.Popen([sys.executable,'-B','-m','twobyteasr.acceptance.timeline_pixel_probe',str(out)],
                    creationflags=0x08000000,stdout=subprocess.DEVNULL,stderr=(out/'pixel-error.txt').open('w'))
                deadline=time.perf_counter()+5
                while not (out/'pixel-ready').exists() and time.perf_counter()<deadline:yield .05
                (out/'visible-ready').touch()
                # Permit foreground selection before measuring; UI Automation
                # snapshots taken mid-playback can themselves stall Qt.
                if os.environ.get('TIMELINE_AUDIT_WAIT_FOREGROUND')=='1':
                    deadline=time.perf_counter()+45
                    while not (out/'visible-start').exists() and time.perf_counter()<deadline:yield .05
                (out/'pixel-still').touch()
                yield .25
            for cycle in range(int(os.environ.get('TIMELINE_AUDIT_CYCLES','2'))):
                if cycle:
                    window._show_glossary_proofread(page.project_path,page.project,studio=page)
                    yield .2
                    review = window.glossary_proofread_page
                    review._back()
                    yield .1
                    self.result['lifecycle'].append(dict(cycle=cycle,visible=review.isVisible(),
                        local_threads=len(getattr(review,'_stutter_threads',())),worker=review._worker is not None,
                        libraries=len(review._selected_ids()),terms=len(review._snapshot.canonical_terms) if review._snapshot else 0,
                        player_idle=not review._player.cue_id and not review._player._wants_play,
                        local_timer=bool(getattr(review,'_local_timer',None) and review._local_timer.isActive()),
                        studio_timers=len(page.findChildren(QTimer)),
                        rematch_timer=review._rematch_timer.isActive(),switch_interval=__import__('sys').getswitchinterval()))
                quick=os.environ.get('TIMELINE_AUDIT_QUICK')=='1'
                requested=set(filter(None,os.environ.get('TIMELINE_AUDIT_PHASES','').split(',')))
                if not quick and (not requested or 'seek' in requested):yield from self.phase_run(str(cycle)+'-seek',self.seeks)
                for kind in (('scroll',) if quick else ('scroll','zoom','scrub','drag','multidrag')):
                    if requested and kind not in requested:continue
                    yield from self.phase_run(str(cycle)+'-'+kind,lambda kind=kind:self.gesture(kind))
                for follow in (False,True):
                    if requested and ('follow' if follow else 'play') not in requested:continue
                    yield from self.phase_run(str(cycle)+('-follow' if follow else '-play'),lambda follow=follow:self.playback(follow))
            _capture(window,out/'02-after.png')
            t._thumbnails.set_paused(True)
            # Fence queued refinements before comparing identical static data.
            t._thumbnails.set_view([])
            yield .2
            cached=t.grab().toImage()
            t._static_timeline_dirty=True
            fresh=t.grab().toImage()
            cached.save(str(out/'cached-timeline.png'));fresh.save(str(out/'fresh-timeline.png'))
            self.result['checks']['cached_pixels_equal_fresh_render']=cached==fresh
            self.result['checks']['paint_geometry_released']=getattr(t,'_paint_geometry_cache',None) is None
            errors=[abs(s['playhead_ms']-s['presentation_ms']) for s in self.result['av']]
            self.result['playhead_clock_error_ms']=distribution(errors)
            if errors:self.result['checks']['playhead_tracks_clock']=max(errors)<150
            cycles=self.result['lifecycle']
            self.result['checks']['timers_do_not_grow']=len(cycles)<2 or cycles[-1]['studio_timers']==cycles[0]['studio_timers']
            self.result['checks']['document_retained'] = len(page.project.cues)==743
            self.result['finished'] = True
            (out/'interactive-ready').touch()
            hold=float(os.environ.get('TIMELINE_AUDIT_HOLD','0'))
            deadline=time.perf_counter()+hold
            while time.perf_counter()<deadline and not (out/'interactive-finish').exists():yield .1

        def save(self):
            (out/'result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2,default=str),'utf8')

        def finish(self):
            self.timer.stop()
            if hasattr(self,'stack_file'):
                import faulthandler
                faulthandler.cancel_dump_traceback_later()
                self.stack_file.close()
            if getattr(self,'probe',None) is not None:
                (out/'pixel-stop').touch()
            self.save()
            (out/'raw-frames.json').write_text(json.dumps(dict(frames=self.frames,inputs=self.inputs,beats=self.beats)),'utf8')
            if self.page:
                self.page.video.set_paused(True)
            window.close()
            self.result['gui_shutdown']=not window.isVisible()
            self.save()
            QTimer.singleShot(100,QApplication.instance().quit)

    window._controls_timeline_audit = Audit()
