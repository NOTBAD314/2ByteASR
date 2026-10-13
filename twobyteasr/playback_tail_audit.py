"""Opt-in normal-entry paint-tail audit. All recording is bounded and in memory.

The native event filter and watchdog observe this test process only. No global
Python profiler, disk writes, screenshots, or synthetic clock run while playing.
"""
from __future__ import annotations

import bisect
import ctypes
import gc
import gzip
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from dataclasses import asdict

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from . import playback_probe as probe
from .cue_boundary_audit import stats


class _NativePaints(QAbstractNativeEventFilter):
    def nativeEventFilter(self, kind, message):
        if sys.platform == 'win32':
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message in (0x000F, 0x0014, 0x0113):  # PAINT, ERASEBKGND, TIMER
                probe.mark('windows_message', message=int(msg.message), hwnd=int(msg.hWnd or 0))
        return False, 0


class _QtEvents(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.UpdateRequest:
            probe.mark('qt_update_request_dispatch', widget=obj.objectName())
        elif event.type() == QEvent.Type.Paint and os.environ.get('TWOBYTEASR_TAIL_WIDGET_PAINT') == '1':
            probe.mark('qt_widget_paint', widget=obj.objectName(), widget_class=obj.metaObject().className(),
                       dirty_width=event.rect().width(), dirty_height=event.rect().height())
        return False


class LayeredProbe:
    def __init__(self, page):
        self.page = page
        self.thread = threading.get_ident()
        self.stopped = threading.Event()
        self.last_heartbeat = time.perf_counter()
        self.native = _NativePaints()
        self.events = _QtEvents()
        self.patched = []
        self.timer = QTimer(page)
        self.timer.setInterval(5)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.beat)
        self.dispatcher = page.thread().eventDispatcher()
        self.awake = lambda: probe.mark('dispatcher_awake')
        self.block = lambda: probe.mark('dispatcher_about_to_block')
        self.gc_callback = lambda phase, info: probe.mark('python_gc_' + phase, **info)

    def wrap(self, obj, name, stage):
        original = getattr(obj, name, None)
        if original is None:
            return
        def call(*args, **kwargs):
            at = time.perf_counter()
            cpu = time.thread_time()
            try:
                return original(*args, **kwargs)
            finally:
                probe.EVENTS.append(dict(at=at, stage=stage,
                    ms=(time.perf_counter()-at)*1000, cpu_ms=(time.thread_time()-cpu)*1000,
                    thread=threading.get_ident(), project_ms=self.page.timeline.playhead_ms))
        setattr(obj, name, call)
        self.patched.append((obj, name, original))

    def start(self):
        gc.callbacks.append(self.gc_callback)
        self.last_heartbeat = time.perf_counter()
        self.timer.start()
        if probe.LIGHT:
            return
        app = QApplication.instance()
        app.installNativeEventFilter(self.native)
        app.installEventFilter(self.events)
        self.dispatcher.awake.connect(self.awake)
        self.dispatcher.aboutToBlock.connect(self.block)
        page = self.page
        for obj, name, stage in (
            (page, '_refresh_selected_cue_properties', 'inspector_refresh'),
            (page, '_load_style_inspector', 'inspector_style'),
            (page, '_ensure_web_live_preview', 'html_prepare_gui'),
            (page, '_caption_window_ready', 'caption_ready_gui'),
            (page, '_commit_advanced_live', 'static_commit_gui'),
            (page.advanced_cue_overlay, '_trace_frame_sample', 'static_frame_trace'),
            (page.advanced_cue_overlay, '_rescale', 'static_rescale'),
            (page.advanced_cue_overlay, 'sync_time', 'static_sync_time'),
            (page.advanced_cue_overlay, '_publish_to_mpv', 'static_publish'),
            (page, '_publish_web_live_frame', 'html_publish_gui'),
            (page, '_sync_video_compositor', 'compositor_sync'),
            (page.cue_table, 'scrollTo', 'list_scroll'),
            (page.cue_table, 'setCurrentIndex', 'list_current'),
            (page.video, '_visual_tick', 'visual_tick'),
            (page.video, '_reconcile_position', 'mpv_reconcile'),
            (page.video.controller, 'observed_property', 'mpv_cached_property'),
            (page.timeline, '_paint_timeline_contents', 'timeline_base_rebuild'),
            (page.timeline, '_paint_active_cues', 'timeline_highlight_paint'),
            (page.timeline, '_paint_edge_feedback', 'timeline_snap_paint'),
        ):
            self.wrap(obj, name, stage)
        self.last_heartbeat = time.perf_counter()
        self.timer.start()
        self.worker = threading.Thread(target=self.watchdog, name='playback-tail-watchdog', daemon=True)
        self.worker.start()

    def beat(self):
        now = time.perf_counter()
        probe.mark('gui_heartbeat', delta_ms=(now-self.last_heartbeat)*1000,
                   project_ms=self.page.timeline.playhead_ms)
        self.last_heartbeat = now

    def watchdog(self):
        previous = time.perf_counter()
        while not self.stopped.wait(.005):
            now = time.perf_counter()
            delay = (now-previous)*1000
            age = (now-self.last_heartbeat)*1000
            if age > 18 or delay > 18:
                # Stack names only: no locals, subtitle text, credentials or paths.
                frames = sys._current_frames()
                stacks = {}
                for ident, frame in frames.items():
                    if ident == threading.get_ident():
                        continue
                    chain = []
                    while frame is not None and len(chain) < 12:
                        chain.append(f'{Path(frame.f_code.co_filename).name}:{frame.f_lineno}:{frame.f_code.co_name}')
                        frame = frame.f_back
                    stacks[str(ident)] = chain
                probe.mark('thread_watchdog', gui_age_ms=age, worker_delta_ms=delay,
                           gui_thread=self.thread, stacks=stacks)
            previous = now

    def stop(self):
        self.timer.stop()
        self.stopped.set()
        gc.callbacks.remove(self.gc_callback)
        if probe.LIGHT:
            return
        self.worker.join(.1)
        QApplication.instance().removeNativeEventFilter(self.native)
        QApplication.instance().removeEventFilter(self.events)
        self.dispatcher.awake.disconnect(self.awake)
        self.dispatcher.aboutToBlock.disconnect(self.block)
        for obj, name, original in self.patched:
            setattr(obj, name, original)


def summarize(events, boundaries, requested):
    events = sorted(events, key=lambda row: row['at'])
    paints = [r for r in events if r['stage'] == 'playhead_paint']
    moving = [r for i, r in enumerate(paints) if not i or r['project_ms'] != paints[i-1]['project_ms']]
    intervals = []
    for a, b in zip(moving, moving[1:]):
        # ±33.4ms around BOTH ends and starts; crossing a boundary counts too.
        index = bisect.bisect_left(boundaries, a['project_ms']-33.4)
        near = index < len(boundaries) and boundaries[index] <= b['project_ms']+33.4
        intervals.append(dict(at=a['at'], end=b['at'], ms=(b['at']-a['at'])*1000,
                              project_ms=a['project_ms'], next_ms=b['project_ms'], boundary=near))
    by_stage = {}
    for event in events:
        if 'ms' in event:
            by_stage.setdefault(event['stage'], []).append(event['ms'])
    heartbeat = [r['delta_ms'] for r in events if r['stage'] == 'gui_heartbeat']
    bstats = stats([r['ms'] for r in intervals if r['boundary']])
    ostats = stats([r['ms'] for r in intervals if not r['boundary']])
    allstats = stats([r['ms'] for r in intervals])
    crossed = sorted({v for v in boundaries if moving and moving[0]['project_ms'] < v <= moving[-1]['project_ms']})
    checks = dict(boundaries_crossed=len(crossed) >= requested,
                  boundary_p99_le_20=bool(bstats['n']) and bstats['p99_ms'] <= 20,
                  moving_paint_max_le_33_4=bool(allstats['n']) and allstats['max_ms'] <= 33.4,
                  heartbeat_max_le_50=bool(heartbeat) and max(heartbeat) <= 50,
                  boundary_ordinary_p95_delta_le_4=bool(bstats['n'] and ostats['n']) and bstats['p95_ms']-ostats['p95_ms'] <= 4)
    worst = max(intervals, key=lambda row: row['ms']) if intervals else None
    timeline = [{**r, 'relative_ms': (r['at']-worst['at'])*1000}
                for r in events if worst and worst['at']-.050 <= r['at'] <= worst['end']+.050]
    targets = [r for r in events if r['stage']=='playhead_update_request']
    target_by_ms = {r['project_ms']: r for r in targets}
    paint_by_ms = {r['project_ms']: r for r in paints}
    latency = [(paint_by_ms[key]['at']-row['at'])*1000 for key,row in target_by_ms.items()
               if key in paint_by_ms and paint_by_ms[key]['at']>=row['at']]
    pixel_changes = [r for i,r in enumerate(paints) if 'pixel_x' in r and
                     (not i or r['pixel_x'] != paints[i-1].get('pixel_x'))]
    return dict(checks=checks, passed=all(checks.values()), boundary_paint_intervals=bstats,
                target_intervals=stats([(b['at']-a['at'])*1000 for a,b in zip(targets,targets[1:])]),
                target_to_paint=stats(latency), targets_without_paint=len(set(target_by_ms)-set(paint_by_ms)),
                pixel_change_intervals=stats([(b['at']-a['at'])*1000 for a,b in zip(pixel_changes,pixel_changes[1:])]),
                ordinary_paint_intervals=ostats, moving_paint_intervals=allstats,
                heartbeat=stats(heartbeat), stages={k: stats(v) for k, v in by_stage.items()},
                crossed_boundary_times=len(crossed), worst_interval=worst,
                worst_timeline=timeline, event_count=len(events))


def start(window, out):
    page = window.studio_page
    result = dict(passed=False)
    layered = None
    def pump(seconds):
        loop = QEventLoop()
        QTimer.singleShot(round(seconds*1000), loop.quit)
        loop.exec()
    def run():
        nonlocal layered
        try:
            from .build_identity import load_build_identity
            result['identity'] = load_build_identity().to_dict()
            result['clock_info'] = {name: vars(time.get_clock_info(name)) for name in ('monotonic','perf_counter','thread_time')}
            result['measurement_limits'] = [
                'Windows native messages and Qt dispatcher are observed in this test process; no DWM physical scanout claim.',
                'Windows thread_time has coarse accounting; cpu_ms below its resolution cannot classify a native wait.',
                'Watchdog stack names exclude locals; GC start/stop and callback wall time share perf_counter.',
                'The detailed probe is opt-in, uses bounded memory, and does not write during playback.'
            ]
            result['omitted_probe_stages'] = (
                ['Qt dispatcher/events', 'native messages', 'watchdog/GIL stacks', 'worker/GUI method spans']
                if probe.LIGHT else [])
            requested_dpr = float(os.environ.get('TWOBYTEASR_TAIL_DPR','1.5'))
            screens = QApplication.screens()
            result['display'] = dict(requested_dpr=requested_dpr, initial_dpr=window.devicePixelRatioF(),
                available_screen_dprs=[screen.devicePixelRatio() for screen in screens])
            if abs(window.devicePixelRatioF()-requested_dpr) > .01:
                screen = next((s for s in screens if abs(s.devicePixelRatio()-requested_dpr)<=.01), None)
                if screen is not None:
                    window.windowHandle().setScreen(screen)
                    geometry = screen.availableGeometry()
                    window.move(geometry.x()+16, geometry.y()+16)
                    pump(.25)
            result['display']['actual_dpr']=window.devicePixelRatioF()
            if abs(window.devicePixelRatioF()-requested_dpr) > .01:
                raise AssertionError(f'Requested DPR {requested_dpr}, actual {window.devicePixelRatioF()}; timing aborted')
            window.raise_(); window.activateWindow()
            page.video.controller.set_volume(0)
            page.video.set_paused(True)
            page.video.set_speed(1.0)
            page._set_review_mode(False)
            page.follow_playhead_toggle.setChecked(False)
            selected = os.environ.get('TWOBYTEASR_TAIL_SELECTED', '1') == '1'
            page.select_cue(page.project.cues[0].id if selected else '')
            panels = os.environ.get('TWOBYTEASR_BOUNDARY_PANELS', 'both')
            page._set_major_panel_visible('cue_list', panels in {'both','list'})
            page._set_major_panel_visible('context', panels in {'both','tools'})
            page._fit_timeline()
            window_ms = int(os.environ.get('TWOBYTEASR_TAIL_WINDOW_MS','0'))
            if window_ms:
                page.timeline.set_visible_window(0, window_ms)
                page.follow_playhead_toggle.setChecked(True)
            start_ms = min(c.start_ms for c in page.project.cues)
            page._seek((start_ms+80)/1000); pump(2.5)
            page._seek(0); pump(.4)
            ablation = os.environ.get('TWOBYTEASR_TAIL_ABLATION', 'none')
            if ablation == 'list-highlight': page.cue_model.set_active_cues = lambda ids: None
            elif ablation == 'autoscroll': page.cue_table.scrollTo = lambda *a, **k: None
            elif ablation == 'inspector':
                page._load_style_inspector = lambda *a, **k: None
                page._refresh_selected_cue_properties = lambda *a, **k: None
            elif ablation == 'overlay':
                page._stop_web_live_preview('diagnostic_overlay_ablation')
                page._activate_selected_advanced_if_needed = lambda *a, **k: None
                page.ensure_active_subtitle_renderer = lambda *a, **k: None
                page.advanced_cue_overlay.hide()
            elif ablation == 'html':
                page._stop_web_live_preview('diagnostic_html_ablation')
                page._ensure_web_live_preview = lambda *a, **k: True
            elif ablation == 'waveform': page.timeline.waveform_visible = False; page.timeline.update()
            elif ablation == 'snap': page.timeline._paint_edge_feedback = lambda *a: None
            elif ablation == 'gc': gc.disable()
            elif ablation == 'no-gc-budget':
                page._playback_gc_budget.close()
                page._playback_gc_budget.set_playing = lambda value: None
            elif ablation == 'coarse-elapsed':
                clock = page.video._playback_clock
                original = clock.sample_presentation
                def sample(**kwargs):
                    if kwargs.get('source') == 'ui_flush': kwargs.pop('elapsed_ms', None)
                    return original(**kwargs)
                clock.sample_presentation = sample
            elif ablation == 'opaque': page.timeline.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
            elif ablation == 'workspace-opaque':
                page.workspace_host.setPalette(page.palette())
                page.workspace_host.setAutoFillBackground(True)
                page.workspace_host.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
            elif ablation == 'consumer-8ms':
                # Both existing consumers still sample the unique PlaybackClock.
                # This does not change media FPS, speed, or author animation phase.
                page.video._timer.setInterval(8)
                page._ensure_playhead_flush_timer().setInterval(8)
            elif ablation == 'elapsed-source':
                # Causal experiment only: same PlaybackClock, existing Qt elapsed source.
                clock = page.video._playback_clock
                original = clock.sample_presentation
                def sample(**kwargs):
                    if kwargs.get('source') == 'ui_flush': kwargs['elapsed_ms'] = page.video._clock.elapsed()
                    return original(**kwargs)
                clock.sample_presentation = sample
            pump(.2)
            result['configuration'] = dict(ablation=ablation, selected=selected, panels=panels,
                actual_selected_cue_id=page.selected_cue_id,
                actual_timeline_selected_id=page.timeline.selected_id,
                actual_selection_count=page.selection_model.selected_count(),
                probe_detail='light' if probe.LIGHT else 'detailed',
                dpr=window.devicePixelRatioF(), width=window.width(), height=window.height(),
                playback_rate=page.video.playback_position_snapshot().playback_rate,
                video_fps=[asset.video_metadata.get('fps') for asset in page.project.media_pool],
                visual_timer_ms=page.video._timer.interval(),
                ui_flush_timer_ms=page._ensure_playhead_flush_timer().interval(),
                cues=len(page.project.cues), tracks=len({cue.speaker_id for cue in page.project.cues}),
                speaker_records=len(page.project.speakers),
                timeline_window_ms=page.timeline.visible_duration_ms, follow=page.follow_playhead_toggle.isChecked(),
                list_visible=page.cue_list_panel.isVisible(), inspector_visible=page.context_panel.isVisible())
            config = result['configuration']
            if (bool(config['actual_selected_cue_id']) != selected
                    or bool(config['actual_timeline_selected_id']) != selected
                    or bool(config['actual_selection_count']) != selected):
                raise AssertionError('Actual subtitle selection does not match the requested matrix condition')
            if (config['list_visible'] != (panels in {'both','list'})
                    or config['inspector_visible'] != (panels in {'both','tools'})):
                raise AssertionError('Actual panel visibility does not match the requested matrix condition')
            recipes = [page.project.style_recipes.get(cue.style_id,{}) for cue in page.project.cues]
            result['effective_caption_routes'] = dict(
                engines=sorted({str(recipe.get('engine') or 'native') for recipe in recipes}),
                html_cues=sum(bool(recipe.get('webTheme')) for recipe in recipes),
                visual_graph_cues=sum(bool(recipe.get('visualGraph')) for recipe in recipes))
            requested_caption = os.environ.get('TWOBYTEASR_TAIL_CAPTION','html')
            routes = result['effective_caption_routes']
            route_ok = (routes['html_cues']==len(recipes) if requested_caption=='html' else
                routes['html_cues']==0 and routes['visual_graph_cues']>0 and 'remotion' in routes['engines']
                if requested_caption=='static' else routes['html_cues']==0 and routes['visual_graph_cues']==0)
            if not route_ok:
                raise AssertionError(f'Requested {requested_caption}, effective caption routes {routes}')
            if result['configuration']['tracks'] != int(os.environ.get('TWOBYTEASR_TAIL_TRACKS','2')):
                raise AssertionError('Actual active subtitle tracks do not match the requested matrix condition')
            selection = page.selected_cue_id
            page.timeline.setFocus(); page.undo_stack.setClean()
            probe.EVENTS.clear()
            layered = LayeredProbe(page); layered.start()
            seconds = float(os.environ.get('TWOBYTEASR_TAIL_SECONDS','26'))
            (out/'measurement-start.json').write_text(json.dumps(dict(seconds=seconds,configuration=result['configuration'])),encoding='utf8')
            page.video.set_paused(False)
            pressure = []
            if os.environ.get('TWOBYTEASR_TAIL_GC_PRESSURE') == '1':
                def exhaust_budget():
                    pressure.append(bytearray(129*1024*1024))
                    page._playback_gc_budget.check_budget()
                QTimer.singleShot(2000, exhaust_budget)
            cpu_started = time.process_time()
            started = time.perf_counter(); pump(seconds)
            # Buffered startup is not media progress. Continue the SAME 1x
            # playback until the last cue actually ends; never seek/replay
            # a missing tail to manufacture the requested cue count.
            final_cue_end = max(cue.end_ms for cue in page.project.cues)
            while (page.timeline.playhead_ms < final_cue_end
                   and not page.video.playback_position_snapshot().paused
                   and time.perf_counter()-started < seconds+10):
                pump(.05)
            measured_seconds = time.perf_counter()-started
            result['continuous_measurement_seconds']=measured_seconds
            result['requested_final_cue_end_ms']=final_cue_end
            result['main_process_cpu'] = dict(seconds=time.process_time()-cpu_started,
                one_core_percent=100*(time.process_time()-cpu_started)/measured_seconds,
                excludes='mpv, browser, renderer and audio child processes')
            budget = page._playback_gc_budget
            result['gc_budget'] = dict(held_before_pause=budget.held,
                exhausted=budget.budget_exhausted, peak_growth=budget.peak_growth,
                limit=budget.MAX_PRIVATE_GROWTH, pressure_exercised=bool(pressure))
            page.video.set_paused(True)
            result['gc_budget']['held_after_pause']=budget.held
            layered.stop(); layered = None
            events = probe.take()
            boundaries = sorted({v for cue in page.project.cues for v in (cue.start_ms,cue.end_ms)})
            result.update(summarize(events, boundaries, int(os.environ.get('TWOBYTEASR_BOUNDARY_COUNT','112'))))
            sampled_ms = sorted(r['project_ms'] for r in events if r['stage']=='apply_playhead')
            seen = 0
            for cue in page.project.cues:
                index = bisect.bisect_left(sampled_ms, cue.start_ms)
                if index < len(sampled_ms) and sampled_ms[index] < cue.end_ms: seen += 1
            result['sampled_distinct_cue_entries'] = seen
            result['checks']['sampled_every_cue'] = seen == len(page.project.cues)
            result['playback_seconds'] = time.perf_counter()-started
            result['checks']['selected_unchanged'] = page.selected_cue_id == selection
            result['checks']['paused_final'] = page.video.playback_position_snapshot().paused
            result['checks']['playback_rate_1x'] = page.video.playback_position_snapshot().playback_rate == 1.0
            result['checks']['gc_restored_after_pause'] = not budget.held
            if pressure:
                result['checks']['memory_guard_restored_during_playback'] = budget.budget_exhausted
            result['checks']['no_edit_side_effects'] = page.undo_stack.isClean()
            result['passed'] = all(result['checks'].values())
            worker = getattr(page, '_web_live_worker', None)
            if worker is not None: result['web_metrics'] = list(worker.metrics)
            result['last_position_ms'] = page.timeline.playhead_ms
            # Full raw events and worst ±50ms windows retained, even on failure.
            with gzip.open(out/'events.json.gz', 'wt', encoding='utf8') as stream:
                json.dump(events, stream)
            window.grab().save(str(out/'studio.png'))
            # Native video/bitmap layers are absent from QWidget.grab. Capture
            # them only AFTER timing has stopped, at a paused active cue.
            ordered_cues = sorted(page.project.cues, key=lambda cue: (cue.start_ms, cue.id))
            middle = ordered_cues[len(ordered_cues)//2]
            capture_ms = middle.start_ms + max(1, round((middle.end_ms-middle.start_ms)*.55))
            capture = dict(requested_ms=capture_ms, selected_before=page.selected_cue_id,
                           clock_before=asdict(page.video.playback_position_snapshot()))
            page._seek(capture_ms/1000.)
            pump(1.2)
            deadline = time.perf_counter()+4
            while page.video.playback_position_snapshot().exact_seek_pending and time.perf_counter()<deadline:
                pump(.05)
            capture['clock_after']=asdict(page.video.playback_position_snapshot())
            capture['render_truth']=page.render_truth_probe(force=True)
            page.video.controller.screenshot_to_file(out/'active-caption-native.png')
            window.grab().save(str(out/'active-caption-ui.png'))
            capture['selected_after']=page.selected_cue_id
            result['post_measurement_capture']=capture
            result['checks']['native_capture_written']=(out/'active-caption-native.png').is_file()
            result['checks']['paused_capture_seek_kept_intent']=(capture['clock_after']['paused']
                and not capture['clock_after']['exact_seek_pending']
                and abs(capture['clock_after']['presentation_media_ms']-capture_ms)<=50)
            result['passed']=all(result['checks'].values())
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            if layered is not None: layered.stop()
            page.video.set_paused(True); page.undo_stack.setClean()
            (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            QTimer.singleShot(150, window.close)
    QTimer.singleShot(350, run)
