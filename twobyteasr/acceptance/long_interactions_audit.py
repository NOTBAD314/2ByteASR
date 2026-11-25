"""Bounded opt-in long-media GUI timings, separate from profiling runs."""
from collections import Counter, deque
from pathlib import Path
import json, os, sys, time, traceback

def start(window, output):
    from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import load_project
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    from .blank_project_audit import _capture

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            import psutil
            self.proc=psutil.Process();self.page=None;self.pending=None
            self.r=dict(pid=os.getpid(),identity=load_build_identity().to_dict(),
                executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)),
                samples=[],resources=[],checks={},error='',profile=bool(int(os.environ.get('LONG_AUDIT_PROFILE','0'))))
            random_seeks = int(os.environ.get("LONG_AUDIT_RANDOM_SEEKS", "0"))
            self.exact_seeks = tuple(json.loads(os.environ.get('LONG_AUDIT_EXACT_SEEKS', '[]')))
            self.unavailable_seeks = frozenset(json.loads(os.environ.get('LONG_AUDIT_UNAVAILABLE_SEEKS', '[]')))
            self.endurance_seconds = int(os.environ.get("LONG_AUDIT_ENDURANCE_SECONDS", "0"))
            self.endurance_histogram = Counter()
            self.endurance_max_gap = 0.0
            self.full_gap_histogram = Counter()
            self.slow_gaps = deque(maxlen=100)
            self.full_max_gap = 0.0
            self.deadline=time.perf_counter()+max(240, (random_seeks + len(self.exact_seeks)) * 13 + 180,
                                                  self.endurance_seconds + 500)
            self.last=time.perf_counter();self.gaps=deque(maxlen=6000)
            self.started=self.last;self.wait_until=0;self.sequence=self.run();self.busy=False;self.phase='initial'
            self.profile=None;self.stack_file=None
            if self.r['profile']:
                import threading
                self.stack_samples=deque(maxlen=1000);self.sample_stop=threading.Event()
                main_id=threading.get_ident()
                def sample():
                    while not self.sample_stop.wait(.025):
                        frame=sys._current_frames().get(main_id);rows=[]
                        while frame is not None and len(rows)<16:
                            rows.append((frame.f_code.co_filename,frame.f_code.co_name,frame.f_lineno));frame=frame.f_back
                        self.stack_samples.append((time.perf_counter(),rows))
                threading.Thread(target=sample,name='bounded-main-sampler',daemon=True).start()
            self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.timeout.connect(self.tick);self.timer.start(8)
            self.heartbeat=QTimer(self)
            self.heartbeat.setTimerType(Qt.PreciseTimer)
            self.heartbeat.timeout.connect(self.record_gap)
            self.heartbeat.start(8)
            self.resource_busy=False
            self.resource_timer=QTimer(self);self.resource_timer.timeout.connect(self.request_resources);self.resource_timer.start(5000)
            import gc,threading
            self.gc_start={};self.gc_samples=deque(maxlen=200)
            def gc_observer(phase,info):
                key=threading.get_ident()
                if phase=='start':self.gc_start[key]=time.perf_counter()
                elif key in self.gc_start:
                    now = time.perf_counter()
                    self.gc_samples.append(dict(thread=key, generation=info['generation'],
                                                at=now-self.started, ms=(now-self.gc_start.pop(key))*1000))
            self.gc_observer=gc_observer;gc.callbacks.append(gc_observer)
            QApplication.instance().aboutToQuit.connect(self.shutdown)

        def save(self):
            temporary=output/'result.pending.json'
            temporary.write_text(json.dumps(self.r,ensure_ascii=False,indent=2,default=str),'utf8')
            temporary.replace(output/'result.json')

        def resources(self):
            procs=[self.proc]+self.proc.children(recursive=True)
            rows=[]
            for p in procs:
                try:
                    m=p.memory_info();cpu=p.cpu_times();io=p.io_counters()
                    rows.append(dict(pid=p.pid,name=p.name(),rss=m.rss,private=getattr(m,'private',None),cpu_s=cpu.user+cpu.system,read=io.read_bytes,write=io.write_bytes,threads=p.num_threads()))
                except Exception:pass
            self.r['resources'].append(dict(at=time.perf_counter()-self.started,processes=rows))
            self.r['resources']=self.r['resources'][-300:]

        def request_resources(self):
            if os.environ.get('LONG_AUDIT_EXTERNAL_RESOURCES')=='1':return
            if self.resource_busy:return
            import threading
            self.resource_busy=True
            def work():
                try:self.resources()
                finally:self.resource_busy=False
            threading.Thread(target=work,name='long-audit-resources',daemon=True).start()

        def record_gap(self):
            now=time.perf_counter();self.gaps.append((now,(now-self.last)*1000));self.last=now
            elapsed = self.gaps[-1][1]
            bucket = min(60000, round(elapsed))
            self.full_gap_histogram[bucket] += 1
            self.full_max_gap = max(self.full_max_gap, elapsed)
            if elapsed > 100:
                latest = self.pending or (self.r['samples'][-1] if self.r['samples'] else {})
                self.slow_gaps.append(dict(at=round(now - self.started, 3), ms=round(elapsed, 2),
                                           phase=self.phase, nearby_action=latest.get('name', '')))
            if self.phase == "endurance":
                self.endurance_max_gap = max(self.endurance_max_gap, elapsed)
                self.endurance_histogram[bucket] += 1

        def tick(self):
            now=time.perf_counter()
            if self.busy:return
            if now<self.wait_until:return
            if self.pending is not None:
                if self.pending.get('paint_ms') is None and now-self.pending['at']<2:return
                self.r['samples'].append(self.pending);self.pending=None;self.save()
            try:
                self.busy=True
                self.wait_until=time.perf_counter()+next(self.sequence)
            except StopIteration:self.finish()
            except BaseException:
                self.r['error']=traceback.format_exc();self.finish()
            finally:self.busy=False

        def eventFilter(self,obj,event):
            if self.pending is not None and event.type()==QEvent.Type.Paint and self.pending.get('paint_ms') is None:
                sample=self.pending
                if sample['name'] in ('warm-input','warm-open-editor') and obj is not self.page.subtitle_edit_input.viewport():
                    return False
                # Queued marker runs after this real Qt paint. It includes any
                # work already queued before that marker; no physical scan claim.
                QTimer.singleShot(0,lambda:self.painted(sample))
            return False

        def painted(self,sample):
            if sample.get('paint_ms') is None:sample['paint_ms']=(time.perf_counter()-sample['at'])*1000

        def action(self,name,fn,**detail):
            sample=dict(name=name,at=time.perf_counter(),phase=self.phase,**detail)
            profile=None
            if self.r['profile']:
                import cProfile
                profile=cProfile.Profile();profile.enable()
            self.pending=sample
            answer=fn()
            sample['handler_ms']=(time.perf_counter()-sample['at'])*1000
            if profile:
                import pstats,io
                profile.disable();s=io.StringIO();pstats.Stats(profile,stream=s).sort_stats('cumtime').print_stats(65)
                (output/(str(len(self.r['samples']))+'-'+name+'-profile.txt')).write_text(s.getvalue(),'utf8')
            # Selection/input might cause only the table/editor to repaint.
            return answer

        def check(self,name,value):
            self.r['checks'][name]=bool(value)
            if not value:raise AssertionError(name)

        def profile_transform_publication(self, page):
            import cProfile
            import io
            import pstats
            from ..caption_style.bulk_transform_preparation import BulkTransformCommand

            apply = BulkTransformCommand._apply
            measured = set()
            self.r["bulk_transaction_profiles"] = []

            def profiled(command, side):
                if command.project is not page.project or side in measured:
                    return apply(command, side)
                measured.add(side)
                timer = cProfile.Profile()
                began = time.perf_counter()
                timer.enable()
                try:
                    return apply(command, side)
                finally:
                    timer.disable()
                    elapsed = (time.perf_counter() - began) * 1000
                    title = "redo" if side else "undo"
                    stream = io.StringIO()
                    pstats.Stats(timer, stream=stream).sort_stats("cumtime").print_stats(65)
                    name = f"bulk-publication-{title}.txt"
                    (output / name).write_text(stream.getvalue(), encoding="utf-8")
                    self.r["bulk_transaction_profiles"].append(dict(
                        side=title, entries=len(command.entries), elapsed_ms=elapsed, report=name))

            BulkTransformCommand._apply = profiled

        def endurance(self, page, project, duration_ms):
            from bisect import bisect_right
            from random import Random

            self.check("endurance_media_is_long_enough", duration_ms >= (self.endurance_seconds + 10) * 1000)
            page._seek(1)
            seek_deadline = time.perf_counter() + 12
            while time.perf_counter() < seek_deadline:
                ready = page.video.playback_position_snapshot()
                if not ready.seeking and not ready.exact_seek_pending and abs(ready.observed_media_ms - 1000) <= 250:
                    break
                yield .1
            else:
                raise TimeoutError("Endurance opening frame did not settle")
            page.play_button.click()
            starting_position = page.video.playback_position_snapshot().observed_media_ms
            start_deadline = time.perf_counter() + 20
            while time.perf_counter() < start_deadline:
                ready = page.video.playback_position_snapshot()
                if (not ready.paused and not ready.seeking and ready.playback_rate == 1
                        and ready.observed_media_ms > starting_position):
                    break
                yield .2
            else:
                raise TimeoutError("Endurance source never started at 1x")
            initial = time.perf_counter()
            previous_position = int(page.timeline.playhead_ms)
            previous_decoder = ready.observed_media_ms
            previous_source = ready.source_generation
            progressing = 0.0
            stationary = 0.0
            real_advance = 0
            checks = Counter()
            display_checks = []
            starts = [cue.start_ms for cue in project.cues]
            last_tick = initial
            last_progress = initial
            next_interaction = initial + 10
            next_checkpoint = initial
            switch_display_at = initial + 900
            pending_display = None
            minimize_at = initial + 1200
            restore_at = None
            long_workload = self.endurance_seconds >= 3600
            next_seek = initial + 600
            evidence_enabled = False
            pending_seek = None
            seek_results = []
            rng = Random(184064)
            self.r["endurance_fixture"] = {
                "speakers": len(project.speakers),
                "translated_cues": len(project.generation_metadata.get("translations", {})),
            }
            self.phase = "endurance"
            while True:
                now = time.perf_counter()
                observed = page.video.playback_position_snapshot()
                position = int(page.timeline.playhead_ms)
                step_ms = position - previous_position
                same_source = observed.source_generation == previous_source
                decoder_advanced = not same_source or observed.observed_media_ms > previous_decoder
                if (not observed.paused and observed.playback_rate == 1 and not observed.seeking
                        and decoder_advanced and 0 < step_ms < (now - last_tick) * 2000 + 500):
                    progressing += now - last_tick
                    real_advance += step_ms
                    last_progress = now
                else:
                    stationary += now - last_tick
                previous_position, last_tick = position, now
                previous_decoder, previous_source = observed.observed_media_ms, observed.source_generation
                if now - initial >= self.endurance_seconds:
                    break
                if long_workload and not evidence_enabled and now >= initial + 300:
                    evidence_enabled = True
                    page.waveform_toggle.setChecked(True)
                    page.spectrogram_toggle.setChecked(True)
                if evidence_enabled and not checks["spectrogram_decoded"]:
                    tiles = getattr(page.timeline, "_spectrogram_tiles", None)
                    checks["spectrogram_decoded"] = int(bool(tiles and any(
                        tile is not None and not tile.isNull() for tile in tiles._tiles.values())))
                    checks["waveform_visible"] = int(bool(page.timeline.waveform_visible))
                if pending_seek is not None:
                    target, requested_at = pending_seek
                    frame = page.video.controller.observed_frame() if page.video.controller else {}
                    ready = (frame.get("status") == "ready" and not observed.seeking
                             and float(frame.get("command_ack_at") or 0) >= requested_at
                             and target - 250 <= position <= target + (now - requested_at) * 1000 + 650)
                    if ready or now - requested_at >= 12:
                        seek_results.append(dict(target_ms=target, position_ms=position,
                                                 decoded=bool(ready), wait_ms=round((now-requested_at)*1000)))
                        pending_seek = None
                elif long_workload and now >= next_seek and not observed.paused and position > 5000:
                    target = position - rng.randrange(1000, 4000)
                    pending_seek = target, now
                    next_seek = now + 900
                    page._seek(target / 1000)
                if pending_display is not None:
                    screen_after = window.windowHandle().screen() if window.windowHandle() else None
                    if screen_after is pending_display or now >= switch_display_at + 4:
                        display_checks[-1]["reported_new_screen"] = screen_after is pending_display
                        display_checks[-1]["actual_dpr"] = window.devicePixelRatioF()
                        pending_display = None
                elif not display_checks and now >= switch_display_at:
                    screens = QApplication.screens()
                    previous_screen = window.windowHandle().screen() if window.windowHandle() else None
                    target_screen = next((screen for screen in screens if screen is not previous_screen), None)
                    display_checks.append({"screen_count": len(screens), "previous_dpr": window.devicePixelRatioF()})
                    if target_screen is not None:
                        rect = target_screen.availableGeometry()
                        pending_display = target_screen
                        window.resize(min(window.width(), rect.width()), min(window.height(), rect.height()))
                        window.move(rect.center() - QPoint(window.width() // 2, window.height() // 2))
                    else:
                        display_checks[-1]["reason"] = "isolated desktop has one screen"
                if restore_at is not None and now >= restore_at:
                    window.showNormal()
                    checks["restore"] += 1
                    restore_at = None
                elif not checks["minimize"] and now >= minimize_at:
                    window.showMinimized()
                    checks["minimize"] += 1
                    restore_at = now + 2
                if now >= next_interaction and project.cues:
                    next_interaction = now + 120
                    cue = project.cues[max(0, bisect_right(starts, position) - 1)]
                    page.select_cue(cue.id)
                    page.timeline.set_visible_window(max(0, position - 10000), 45000)
                    checks["selected_and_scrolled_during_playback"] += 1
                    if checks["selected_and_scrolled_during_playback"] % 4 == 0:
                        page.cue_controller.set_text(cue.id, cue.text + " [耐久測試]")
                        page.undo_stack.undo()
                        page.undo_stack.redo()
                        page.undo_stack.undo()
                        checks["edit_undo_redo"] += 1
                    if checks["selected_and_scrolled_during_playback"] % 10 == 0:
                        page.save()
                        checks["save"] += 1
                transport_failed = (str(getattr(page.video, '_startup_state', '')) == 'FAILED'
                                    and now - last_progress > 15)
                if now >= next_checkpoint or transport_failed:
                    next_checkpoint = now + 10
                    self.r["endurance"] = dict(requested_seconds=self.endurance_seconds,
                        elapsed_seconds=round(now - initial, 3), observed_progressing_seconds=round(progressing, 3),
                        sampled_nonprogress_seconds=round(stationary, 3), observed_media_advance_ms=real_advance,
                        timeline_position_ms=position, interactions=dict(checks),
                        display_checks=display_checks,
                        random_seeks=seek_results,
                        heartbeat_histogram_ms=dict(self.endurance_histogram),
                        heartbeat_max_ms=self.endurance_max_gap,
                        decoder_paused=observed.paused, decoder_seeking=observed.seeking,
                        decoder_position_ms=observed.observed_media_ms,
                        transport_state=str(getattr(page.video, '_startup_state', '')))
                    self.save()
                if transport_failed:
                    raise RuntimeError("Decoder stopped during endurance and reported a failed transport")
                yield 1
            page.video.set_paused(True)
            self.r["endurance"].update(elapsed_seconds=round(time.perf_counter() - initial, 3),
                observed_progressing_seconds=round(progressing, 3), observed_media_advance_ms=real_advance,
                sampled_nonprogress_seconds=round(stationary, 3), interactions=dict(checks),
                display_checks=display_checks, random_seeks=seek_results,
                heartbeat_histogram_ms=dict(self.endurance_histogram), heartbeat_max_ms=self.endurance_max_gap)
            self.check("endurance_wall_clock_completed", self.r["endurance"]["elapsed_seconds"] >= self.endurance_seconds)
            self.check("endurance_has_actual_1x_progress", progressing >= self.endurance_seconds * 0.98)
            if long_workload:
                self.check("endurance_random_seek_decoder", bool(seek_results) and all(row["decoded"] for row in seek_results))
                self.check("endurance_audio_evidence", bool(checks["waveform_visible"] and checks["spectrogram_decoded"]))

        def run(self):
            previous_startup = None
            while window.built_page('studio') is None or window.studio_page.project is None or not window.studio_page._readiness.ready:
                built=window.built_page('studio')
                readiness = getattr(built, '_readiness', None)
                modal = QApplication.activeModalWidget()
                startup = dict(page_built=built is not None, project_bound=getattr(built, 'project', None) is not None,
                               opening=bool(getattr(readiness, 'active', False)),
                               completed=sorted(getattr(readiness, 'completed', ())),
                               modal_type=type(modal).__name__ if modal else None,
                               modal_object=modal.objectName() if modal else None)
                if startup != previous_startup:
                    previous_startup = startup
                    self.r['startup_readiness'] = startup
                    (output / 'startup-readiness.json').write_text(json.dumps(startup, ensure_ascii=False), 'utf-8')
                failure = (getattr(readiness, 'profile', None) or {}).get('error')
                if failure and readiness and not readiness.active:
                    self.r['startup_failure_stage'] = failure.get('stage')
                    raise RuntimeError(f"Studio could not open the test project at stage {failure.get('stage')}")
                if built is not None and getattr(built._readiness,'failure_reason',''):
                    raise RuntimeError(built._readiness.failure_reason)
                if time.perf_counter()>self.deadline:raise TimeoutError('Long project did not become ready')
                yield .1
            p=self.page=window.studio_page;project=p.project
            duration_ms = timeline_duration_ms(project)
            p.video.set_paused(True);p.volume_slider.setValue(0)
            for widget in (p.timeline,p.cue_table.viewport(),p.subtitle_edit_card):widget.installEventFilter(self)
            self.r['project']=dict(cues=len(project.cues),translations=len(project.generation_metadata.get('translations',{})),
                duration_ms=duration_ms,media=project.media.path,speakers=len(project.speakers),
                video_tracks=len(project.video_tracks),audio_tracks=len(project.audio_tracks),
                dpr=window.devicePixelRatioF(),size=[window.width(),window.height()])
            self.request_resources();yield 3
            if os.environ.get('LONG_AUDIT_PREPARATION_OFF')=='1':
                p._waveform_cancel_event.set();p._waveform_generation+=1;p._waveform_pending_media=[]
                p.timeline._thumbnails.close()
                deadline=time.perf_counter()+5
                while any(th.is_alive() for th in p._waveform_threads) and time.perf_counter()<deadline:yield .1
                self.r['preparation_control']=dict(wave_threads_alive=sum(th.is_alive() for th in p._waveform_threads),
                    thumbnail_closed=p.timeline._thumbnails.closed)
            t=p.timeline;t.set_visible_window(0,60000);yield .4
            # Use distinct real corpus text and stable IDs; fixed viewport for
            # the screen-off object count control.
            cues=project.cues[:12]
            for i,cue in enumerate(cues):
                self.action('select',lambda c=cue:p.select_cue(c.id),cue_id=cue.id)
                yield .18
            for cue in cues[:6]:
                self.action('open-editor',lambda c=cue:p._open_caption_editor(c.id,'original'),cue_id=cue.id)
                yield .18
                self.check('editor_bound_'+cue.id,p._caption_draft is not None)
                self.action('input',lambda:QTest.keyClicks(p.subtitle_edit_input,' test'))
                yield .15
                p._cancel_canvas_inline_edit();yield .1
            cue=cues[2];old=cue.text
            for i in range(3):
                self.action('text-edit',lambda i=i:p.cue_controller.set_text(cue.id,old+' '+str(i)))
                yield .3
                self.action('undo',p.undo_stack.undo);yield .2
                self.check('undo_original_'+str(i),cue.text==old)
                self.action('redo',p.undo_stack.redo);yield .2
                p.undo_stack.undo();yield .2
            for i in range(16):
                self.action('scroll',lambda i=i:t.set_visible_window(60000+i*1500,60000));yield .05
            for i in range(12):
                self.action('zoom',lambda i=i:t.set_visible_window(0,60000+(i%3)*30000));yield .05
            from ..timeline.selection_scope import SelectionScope
            self.action('select-all',lambda:p.cue_controller.apply_selection_scope(SelectionScope.all(len(project.cues),cue.id)))
            yield .3
            p.select_cue(cue.id);yield .2
            self.action('save',p.save);yield .4
            reloaded=load_project(p.project_path)
            self.check('saved_original',next(c for c in reloaded.cues if c.id==cue.id).text==old)
            self.r['media_targets']=[]
            initial_targets = [1000, duration_ms // 2, max(0, duration_ms - 8000)]
            from random import Random
            random_seeks = int(os.environ.get("LONG_AUDIT_RANDOM_SEEKS", "0"))
            planned = Random(184064).sample(range(1000, max(1000, duration_ms - 2500)),
                                           max(0, min(random_seeks, duration_ms - 3500)))
            if any(not 0 <= target < duration_ms for target in self.exact_seeks):
                raise ValueError('Requested audit seek is outside the actual project timeline')
            planned = [*self.exact_seeks, *planned]
            if not self.unavailable_seeks.issubset(set(initial_targets + planned)):
                raise ValueError('Unavailable seek expectations require an explicit test target')

            def seek_and_verify(target, superseded=()):
                from ..media.indexed_media import GLOBAL_INDEXED_MEDIA
                from ..playback.frame_readiness import same_media_path
                from ..playback.playback_plan import playback_plan

                preview_target = p._multitrack_preview_target(target)
                expected_source_ms = int(preview_target["source_ms"]) if preview_target else target
                expected_path = str(preview_target["source_path"]) if preview_target else str(project.media.path)
                asset_id = str(preview_target.get("asset_id", "")) if preview_target else ""
                asset = playback_plan(project).assets.get(asset_id)
                canonical_source = str(asset.canonical_source) if asset else expected_path
                for transient in superseded:
                    p._seek(transient / 1000)
                begun = time.perf_counter()
                self.action('seek',lambda target=target:p._seek(target/1000),target_ms=target)
                yield .1
                observed = {}
                frame = {}
                completed = False
                expected_unavailable = target in self.unavailable_seeks
                while time.perf_counter() - begun < 12:
                    controller = p.video.controller
                    observed = controller.observed_position() or {}
                    frame = controller.observed_frame() or {}
                    position = observed.get("position")
                    position_observed = isinstance(position, (int, float))
                    viewer = getattr(p.video, "_media_path", "")
                    indexed = GLOBAL_INDEXED_MEDIA.optimized_target(canonical_source)
                    source_correct = same_media_path(viewer, expected_path) or bool(
                        indexed and same_media_path(viewer, str(indexed)))
                    newest_frame = (frame.get("status") == "ready" and
                                    float(frame.get("command_ack_at") or 0) >= begun and
                                    same_media_path(frame.get("path"), viewer))
                    completed = (
                        bool(observed.get("seek_completed")) and not observed.get("seeking")
                        and position_observed and abs(position * 1000 - expected_source_ms) <= 250
                        and float(observed.get("observed_perf_counter_ts") or 0) >= begun
                        and source_correct
                        and abs(t.playhead_ms - target) <= 100
                        and (newest_frame or not planned)
                    )
                    if expected_unavailable:
                        completed = (p._active_video_preview_key == '__gap__' and p.video._clock_only
                                     and not p.video._media_attached and abs(t.playhead_ms - target) <= 100)
                    if completed:
                        break
                    yield .1
                return dict(target=target, expected_source_ms=expected_source_ms,
                    expected_path=expected_path, observed=observed,
                    playhead_ms=t.playhead_ms, viewer_source=getattr(p.video, "_media_path", ""),
                    readiness_ms=(time.perf_counter()-begun)*1000,
                    frame=frame, completed=completed, expected_unavailable=expected_unavailable)

            for target in initial_targets + planned:
                self.r["media_targets"].append((yield from seek_and_verify(target)))
            if planned:
                superseded = [initial_targets[0], initial_targets[-1]] * 4
                self.r["rapid_seek"] = yield from seek_and_verify(initial_targets[1], superseded)
                self.r["rapid_seek"]["superseded_requests"] = len(superseded)
                self.check("rapid_seek_keeps_latest_decoder_frame", self.r["rapid_seek"]["completed"])
                self.check("verified_random_seeks",
                           all(row["completed"] for row in self.r["media_targets"]))
            _capture(window,output/'long-window.png')
            if self.endurance_seconds:
                yield from self.endurance(p, project, duration_ms)
            until=time.perf_counter()+int(os.environ.get('LONG_AUDIT_SECONDS','0'))
            cycle=0
            self.phase='steady'
            if int(os.environ.get('LONG_AUDIT_SECONDS','0')):
                from hashlib import blake2b
                if self.r['profile']:
                    self.profile_transform_publication(p)

                def cue_appearance(cue):
                    payload = json.dumps((cue.style_id, cue.transform, cue.appearance_override),
                                         sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    return blake2b(payload, digest_size=32).digest()

                checksum_at = time.perf_counter()
                before_style = {cue.id: cue_appearance(cue) for cue in project.cues}
                self.r['audit_before_geometry_checksum_ms'] = (time.perf_counter() - checksum_at) * 1000
                p.style_scope.setCurrentIndex(p.style_scope.findData('all'))
                p.style_layer.setCurrentIndex(p.style_layer.findData('group'))
                before_index=p.undo_stack.index();began=time.perf_counter()
                self.action('all-batch-position',lambda:p.caption_transform_panel.edit('position_x',35.0));yield .03
                deadline=time.perf_counter()+150
                while getattr(p,'_style_application_busy',False) or getattr(p,'_bulk_transform_busy',False):
                    if time.perf_counter()>deadline:raise TimeoutError('Full batch did not settle')
                    yield .03
                self.r['all_batch_completion_ms']=(time.perf_counter()-began)*1000
                self.r['all_batch_worker_and_publish'] = getattr(p, "_last_bulk_transform_metrics", None)
                self.r['all_batch_ui_work'] = getattr(p, "_last_bulk_transform_ui_work", None)
                self.check('all_batch_created_one_undo',p.undo_stack.index()==before_index+1)
                self.action('all-batch-undo', p.undo_stack.undo);yield .3
                checksum_at = time.perf_counter()
                after_style = {cue.id: cue_appearance(cue) for cue in project.cues}
                self.r['audit_after_geometry_checksum_ms'] = (time.perf_counter() - checksum_at) * 1000
                differing = sorted(cue_id for cue_id in before_style.keys() | after_style.keys()
                                   if before_style.get(cue_id) != after_style.get(cue_id))
                self.r["all_batch_undo_differing_cues"] = {"count": len(differing), "sample_ids": differing[:12]}
                self.check('all_batch_undo_restores_every_cue', not differing)
                p.cue_controller.apply_selection_scope(SelectionScope.explicit((project.cues[0].id,),project.cues[0].id))
                p.style_scope.setCurrentIndex(p.style_scope.findData('current'))
                t.set_visible_window(0,60000);p._seek(1);yield 3
                p.subtitle_edit_input.viewport().installEventFilter(self)
                for cue in project.cues[:24]:
                    self.action('warm-select',lambda cue=cue:p.select_cue(cue.id));yield .12
                for cue in project.cues[:10]:
                    self.action('warm-open-editor',lambda cue=cue:p._open_caption_editor(cue.id,'original'));yield .12
                    self.action('warm-input',lambda:QTest.keyClicks(p.subtitle_edit_input,' warm'));yield .12
                    p._cancel_canvas_inline_edit();yield .1
            while time.perf_counter()<until:
                p.video.set_paused(False);yield 4
                playing_position=p.timeline.playhead_ms
                self.action('playing-select',lambda:p.select_cue(project.cues[(cycle*31)%len(project.cues)].id));yield 6
                self.r.setdefault('playback_progress_ms',[]).append(p.timeline.playhead_ms-playing_position)
                p.video.set_paused(True);yield .3
                cue=project.cues[(cycle*31)%len(project.cues)]
                self.action('mixed-select',lambda cue=cue:p.select_cue(cue.id));yield .2
                self.action('mixed-edit',lambda cue=cue:p.cue_controller.set_text(cue.id,cue.text+' [观察]'));yield .3
                p.undo_stack.undo();yield .2
                t.set_visible_window(cue.start_ms,60000+(cycle%4)*30000);yield .2
                p._seek(min(duration_ms-2000,cue.start_ms+100)/1000);yield .8
                cycle+=1
                if cycle%5==0:
                    selected=project.cues[cycle:cycle+21]
                    p.cue_controller.apply_selection_scope(SelectionScope.explicit([c.id for c in selected],selected[0].id))
                    p.style_scope.setCurrentIndex(p.style_scope.findData('selected'))
                    p.style_layer.setCurrentIndex(p.style_layer.findData('group'))
                    before=p.undo_stack.index();began=time.perf_counter()
                    self.action('mixed-batch-position',lambda:p.caption_transform_panel.edit('position_x',35.0));yield .2
                    while getattr(p,'_style_application_busy',False) or getattr(p,'_bulk_transform_busy',False):
                        yield .05
                    self.r.setdefault('batch_completion_ms',[]).append((time.perf_counter()-began)*1000)
                    if p.undo_stack.index()>before:p.undo_stack.undo()
                    yield .3
            if int(os.environ.get('LONG_AUDIT_SECONDS','0')):
                self.r['qc_before_close']=getattr(p,'_qc_worker',None).snapshot() if getattr(p,'_qc_worker',None) else None
                self.r['qc_timings_before_close']=dict(getattr(p,'_qc_worker_timings',{}))
                self.action('final-save',p.save);yield .3
                path=p.project_path;expected=[(c.id,c.text) for c in project.cues]
                translations=dict(project.generation_metadata.get('translations',{}))
                p.undo_stack.setClean();p._close_project_session('long-audit-reopen');p.open_project(path)
                deadline=time.perf_counter()+150
                while p.project is None or p.project is project or not p._readiness.ready:
                    if time.perf_counter()>deadline:raise TimeoutError('Reopen did not settle')
                    yield .1
                self.check('reopened_all_text',[(c.id,c.text) for c in p.project.cues]==expected)
                self.check('reopened_all_translations',p.project.generation_metadata.get('translations',{})==translations)
                _capture(window,output/'reopened-window.png');yield 5
            self.request_resources();self.r['finished']=True
            self.r['max_gui_gap_ms']=max((ms for _,ms in self.gaps),default=0)
            gaps = sorted(ms for _, ms in self.gaps)
            self.r['gui_gap_ms'] = {f"p{q}": gaps[min(len(gaps) - 1, (len(gaps) * q + 99) // 100 - 1)]
                                    for q in (50, 95, 99)} if gaps else {}
            self.r['whole_run_heartbeat'] = {
                'max_ms': self.full_max_gap, 'histogram_ms': dict(self.full_gap_histogram),
                'slow_gaps': sorted(self.slow_gaps, key=lambda item: item['ms'], reverse=True)[:20],
            }

        def finish(self):
            self.timer.stop();self.heartbeat.stop();self.resource_timer.stop()
            import gc
            if self.gc_observer in gc.callbacks:gc.callbacks.remove(self.gc_observer)
            self.r['gc']=list(self.gc_samples)
            if self.r['profile']:
                self.sample_stop.set()
                (output/'gui-stacks.json').write_text(json.dumps(list(self.stack_samples),indent=2),'utf8')
            self.save()
            if self.page:self.page.undo_stack.setClean()
            QTimer.singleShot(100,window.close)

        def shutdown(self):
            self.r['gui_shutdown']=True;self.save()

    window._long_interactions_audit=Audit()
