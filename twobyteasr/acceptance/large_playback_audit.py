"""Bounded real-window playback profiling on an isolated test desktop.

Timer delays and caption submissions are reported as such, never screen FPS.
"""
import cProfile
import bisect
import json
import os
import math
from pathlib import Path
import platform
import statistics
import threading
import time
import traceback
import weakref
from collections import deque


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    def quantile(q):
        return values[min(len(values)-1, max(0, math.ceil(len(values)*q)-1))]
    return {'count': len(values), 'p50_ms': statistics.median(values),
        'p95_ms': quantile(.95), 'p99_ms': quantile(.99), 'max_ms': values[-1],
        'total_ms': sum(values), 'over_50_ms': sum(x > 50 for x in values),
        'over_100_ms': sum(x > 100 for x in values)}


def start(window, output):
    from PySide6.QtCore import QTimer, Qt, qVersion
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics import playback_probe
    from ..rendering.caption_scene import CaptionScene, SceneRasterizer
    from ..projects.studio_runtime_state import ProjectStateRuntime
    import psutil

    try:
        page = window.studio_page
    except RuntimeError:
        QTimer.singleShot(100, lambda: start(window, output))
        return
    output = Path(output)
    spec = json.loads((output / 'input.json').read_text('utf8'))
    try:
        from ..rendering.caption_motion_preheater import CaptionMotionPreheater
        request_original, take_original = CaptionMotionPreheater.request, CaptionMotionPreheater.take
    except ImportError:
        CaptionMotionPreheater = request_original = take_original = None
    result = {'passed': False, 'checks': {}, 'spec': spec,'pid':os.getpid()}
    audio_observations=[]
    clock = time.perf_counter
    active = {'phase': None}
    render, native, posts, heartbeat, warm_calls, memory_samples, resource_samples, queries = [], [], [], [], [], [], [], []
    last_rasterizer = [None]
    pipeline=[]
    if spec.get('seconds',0)>180:
        render,native,posts,heartbeat,warm_calls,queries=(deque(maxlen=10000) for _ in range(6))
        pipeline=deque(maxlen=10000)
    gui_thread = threading.get_ident()
    coverage = []
    previous = [clock()]
    frame_original, native_original, accept_original = SceneRasterizer.frame, SceneRasterizer.native_frame, CaptionScene.accept
    preheat_original = CaptionScene.preheat
    query_original = ProjectStateRuntime.cues_at
    prefetch_events, prefetch_names = [], {}
    profiler = cProfile.Profile() if spec.get('profile') else None
    profile_frames = [0]

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')

    def frame(self, prepared_cues, *args, **kwargs):
        phase = active['phase']
        began = clock()
        if (spec.get('delay_cue_ms') and kwargs.get('retire_web',True)
                and any(key in spec.get('require_cues',[]) for key,_ in prepared_cues)):
            time.sleep(float(spec['delay_cue_ms'])/1000)
        if last_rasterizer[0] is None or last_rasterizer[0]() is not self:
            last_rasterizer[0] = weakref.ref(self)
        try:
            if phase and profiler is not None and profile_frames[0] < 80:
                profiler.enable()
                try:
                    return frame_original(self, prepared_cues, *args, **kwargs)
                finally:
                    profiler.disable()
                    profile_frames[0] += 1
            return frame_original(self, prepared_cues, *args, **kwargs)
        finally:
            if phase:
                render.append((phase, (clock()-began)*1000, len(prepared_cues), len(self.rasters)))

    def native_frame(self, *args, **kwargs):
        phase = active['phase']
        began = clock()
        try:
            return native_original(self, *args, **kwargs)
        finally:
            if phase:
                native.append((phase, (clock()-began)*1000))

    def accept(self, token, pixels, trace):
        old = self.published
        accept_original(self, token, pixels, trace)
        posted=pixels is not None and self.published is pixels and self.published is not old
        if active['phase'] and posted:
            posts.append((active['phase'], clock(), len(token[4]), trace.get('duration_ms'), trace.get('sample_ms'), list(token[4]),
                          (pixels.raw_geometry or {}).get('alpha_nonzero')))
        if active['phase']:
            metric=self.metrics[-1] if posted and self.metrics else trace
            pipeline.append(dict(phase=active['phase'],sample_ms=trace.get('sample_ms'),posted=posted,cue_ids=list(token[4]),
                gui_delivery_ms=(clock()-trace['ready_at'])*1000 if 'ready_at' in trace else metric.get('gui_delivery_ms'),
                packing=metric.get('packing'),
                **{k:metric[k] for k in ('queue_wait_ms','adopt_ms','raster_ms','pixel_pack_ms','submit_ms','media_age_ms') if k in metric}))

    def preheat(self, *args, **kwargs):
        phase = active['phase']
        began = clock()
        try:
            if spec.get('preheat')=='off':return None
            return preheat_original(self, *args, **kwargs)
        finally:
            if phase:
                warm_calls.append((phase, (clock()-began)*1000))

    def query(self, milliseconds):
        phase = active['phase']
        began = clock()
        result = query_original(self, milliseconds)
        if phase and threading.get_ident() == gui_thread:
            queries.append((phase, (clock()-began)*1000, len(result)))
        return result

    def request_prefetch(self, epoch, items, **kwargs):
        if spec.get('preheat')=='motion-off':return None
        items = tuple(items)
        if spec.get('trace_prefetch') and active['phase']:
            for item in items:
                prefetch_names[item[0]] = item[1].snapshot.cue_id
            prefetch_events.append(dict(kind='request', phase=active['phase'], wall=clock(),
                cues=[item[1].snapshot.cue_id for item in items], stats=self.stats()))
        return request_original(self, epoch, items, **kwargs)

    def take_prefetch(self, epoch, keys):
        taken = take_original(self, epoch, keys)
        if spec.get('trace_prefetch') and active['phase']:
            prefetch_events.append(dict(kind='take', phase=active['phase'], wall=clock(),
                cues=[prefetch_names.get(key, '?') for key, _ in taken], stats=self.stats()))
        return taken

    SceneRasterizer.frame, SceneRasterizer.native_frame, CaptionScene.accept = frame, native_frame, accept
    CaptionScene.preheat = preheat
    ProjectStateRuntime.cues_at = query
    if CaptionMotionPreheater is not None:
        CaptionMotionPreheater.request, CaptionMotionPreheater.take = request_prefetch, take_prefetch
    timer = QTimer(window)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(5)
    def tick():
        now = clock()
        if active['phase']:
            heartbeat.append((active['phase'], (now-previous[0])*1000))
            if spec.get('audio') and active['phase']=='first' and len(audio_observations)<2000:
                sample=page.video.playback_position_snapshot()
                audio_observations.append(dict(wall=now,video_pts_ms=getattr(page.video,'_last_video_frame_pts_ms',None),
                    presentation_ms=sample.presentation_media_ms,mpv_ms=getattr(page.video,'_last_mpv_time_pos_ms',None)))
        previous[0] = now
    timer.timeout.connect(tick)
    memory_timer = QTimer(window)
    memory_timer.setInterval(2000)
    def sample_resources():
        if not active['phase']:
            return
        import gc
        from ..rendering import overlay_session
        from ..rendering.live_layer_cache import GLOBAL_LIVE_LAYER_CACHE
        process = psutil.Process()
        scene = getattr(page, '_caption_scene', None)
        raster = last_rasterizer[0]() if last_rasterizer[0] is not None else None
        cache = getattr(page, '_caption_playback_cache', None)
        job_queue = overlay_session._storage_jobs
        rss = process.memory_info().rss/1048576
        memory_samples.append((active['phase'], clock(), rss))
        resource_samples.append(dict(phase=active['phase'], at=clock(), rss_mb=rss,
            threads=process.num_threads(), gc_counts=gc.get_count(),
            full_gc_count=gc.get_stats()[2]['collections'],
            scene_frames=len(scene.frames) if scene is not None else 0,
            scene_warm_pending=len(scene.warm_pending) if scene is not None else 0,
            raster_entries=len(raster.rasters) if raster is not None else 0,
            prepared_entries=len(cache._frames) if cache is not None else 0,
            motion_preheat=scene._motion_preheater.stats() if scene is not None and hasattr(scene, '_motion_preheater') else None,
            live_layers=GLOBAL_LIVE_LAYER_CACHE.stats(),
            storage_queue=job_queue.qsize() if job_queue is not None else 0))
    memory_timer.timeout.connect(sample_resources)

    def wait(predicate, seconds=150):
        until = clock() + seconds
        while clock() < until and not predicate():
            QTest.qWait(20)
        if not predicate():
            raise TimeoutError('Studio readiness timed out')

    def stats():
        controller = page.video.controller
        values = {}
        for key in (
            'container-fps', 'estimated-vf-fps', 'display-fps', 'frame-drop-count',
            'decoder-frame-drop-count', 'mistimed-frame-count', 'hwdec-current', 'current-vo'):
            try:
                values[key] = controller.get_property(key, None)
            except Exception as exc:
                values[key] = {'unavailable': type(exc).__name__}
        return values

    def measure(phase, seconds):
        playback_probe.EVENTS.clear()
        previous[0] = clock()
        cpu0 = psutil.Process().cpu_times()
        memory0 = psutil.Process().memory_info().rss
        before = stats()
        media0 = page.video.playback_position_snapshot().presentation_media_ms
        active['phase'] = phase
        if spec.get('visible'):window.setWindowTitle('2ByteASR QA '+str(os.getpid()))
        (output/'playback-phase.json').write_text(json.dumps(dict(phase=phase,wall=clock(),media_ms=media0,
            rate=spec['rate'],pid=os.getpid(),video_path=page.project.media.path,playback_mode=page._playback_mode)),'utf8')
        began = clock()
        page._toggle_playback()
        QTest.qWait(round(seconds*1000))
        if not page.video._paused:
            page._toggle_playback()
        elapsed = clock()-began
        active['phase'] = None
        end = clock()
        after = stats()
        media1 = page.video.playback_position_snapshot().presentation_media_ms
        cpu1 = psutil.Process().cpu_times()
        rows = playback_probe.take()
        stages = {}
        for stage in sorted({row['stage'] for row in rows if 'ms' in row and began <= row['at'] <= end}):
            stages[stage] = distribution([row['ms'] for row in rows if row['stage'] == stage and 'ms' in row and began <= row['at'] <= end])
            stages[stage]['thread_cpu_ms'] = distribution([row['cpu_ms'] for row in rows if row['stage'] == stage and 'cpu_ms' in row and began <= row['at'] <= end])
        phase_posts = [row for row in posts if row[0] == phase]
        for cue_id in spec.get('require_cues',[]):
            cue=next((c for c in page.project.cues if c.id==cue_id),None)
            if cue is not None and media0<=cue.start_ms and media1>=cue.end_ms:
                visible=[row for row in phase_posts if cue_id in row[5] and len(row)>6 and row[6]
                         and cue.start_ms<=row[4]<cue.end_ms]
                result['checks'][phase+'.visible_cue_'+cue_id]=bool(visible)
        spans = []
        for left, right in zip(phase_posts, phase_posts[1:]):
            a, b = left[4], right[4]
            if a is None or b is None or b < a:
                continue
            index = bisect.bisect_right([start for start, _ in coverage], a) - 1
            if index >= 0 and coverage[index][1] >= b:
                spans.append((right[1]-left[1])*1000)
        return dict(elapsed_s=elapsed, gui_timer_interval=distribution([v for p,v in heartbeat if p == phase]),
            scene_render=distribution([v for p,v,_,_ in render if p == phase]),
            native_frame=distribution([v for p,v in native if p == phase]),
            scene_worker_total=distribution([row[3] for row in posts if row[0] == phase and row[3] is not None]),
            preheat=distribution([v for p,v in warm_calls if p == phase]),
            cue_query=distribution([v for p,v,_ in queries if p == phase]),
            cue_query_max_active=max([count for p,_,count in queries if p == phase], default=0),
            caption_submit_interval=distribution([(b[1]-a[1])*1000 for a,b in zip(phase_posts, phase_posts[1:])]),
            caption_submit_continuous_interval=distribution(spans),
            excluded_gaps=len(phase_posts)-1-len(spans) if phase_posts else 0,
            caption_submit_count=len(phase_posts), maximum_prepared=max([v for p,_,v,_ in render if p == phase], default=0),
            raster_entries_max=max([v for p,_,_,v in render if p == phase], default=0),
            media_advance_ms=media1-media0, process_cpu_s=cpu1.user+cpu1.system-cpu0.user-cpu0.system,
            rss_mb=[memory0/1048576, psutil.Process().memory_info().rss/1048576],
            pipeline={key:distribution([row[key] for row in pipeline if row['phase']==phase and key in row and isinstance(row[key],(int,float))])
                      for key in ('queue_wait_ms','raster_ms','pixel_pack_ms','gui_delivery_ms','submit_ms','media_age_ms')},
            statistics_scope='rolling_last_10000' if spec.get('seconds',0)>180 else 'entire_phase',
            rss_samples_mb=[v for p,_,v in memory_samples if p == phase],
            video_before=before, video_after=after, stages=stages)

    def execute():
        token = None
        try:
            wait(lambda: page.project is not None and page._readiness.ready and not page._readiness.active)
            for font in (Path(os.environ['LOCALAPPDATA']) / 'Microsoft/Windows/Fonts').glob('*'):
                if font.suffix.lower() in {'.ttf', '.otf'}:
                    QFontDatabase.addApplicationFont(str(font))
            if not page.video._paused:
                page._toggle_playback()
            page.volume_slider.setValue(70 if spec.get('audio') else 0)
            page._set_speed(spec['rate'])
            page._seek(spec['start'])
            QTest.qWait(2000)
            if spec.get('wait_scene'):
                from ..rendering.caption_scene import active_cues
                from ..caption_style.bilingual_layout import companion_id, settings_from_state, translations_of
                active_captions = active_cues(page, int(spec['start']*1000))
                ids = [cue.id for cue in active_captions]
                if settings_from_state(page.project.studio_state).mode == 'bilingual':
                    translations = translations_of(page.project.generation_metadata)
                    ids += [companion_id(cue.id) for cue in active_captions if translations.get(cue.id)]
                wait(lambda: getattr(page, '_caption_scene', None) is not None
                    and page._caption_scene.published is not None
                    and set(ids).issubset(page._caption_scene.trace()['rendered_cue_ids']), 30)
            result['project'] = dict(cues=len(page.project.cues), translations=len(page.project.generation_metadata.get('translations', {})),
                speakers=len(page.project.speakers), video_tracks=len(page.project.video_tracks),
                audio_tracks=len(page.project.audio_tracks), bilingual=page.project.studio_state.get('bilingual'),
                visibility=page._subtitle_track_visibility, playback_mode=page._playback_mode,
                media_assets=[dict(path=asset.canonical_source, offline=asset.offline,
                    file_exists=Path(asset.canonical_source).is_file()) for asset in page.project.media_pool])
            if not page.project.media_pool or any(asset.offline or not Path(asset.canonical_source).is_file() for asset in page.project.media_pool):
                raise RuntimeError('Media unavailable; refusing to call timeline-gap playback a video measurement')
            # Keep genuine gaps out of caption pacing statistics. The full
            # interval is also reported separately and neither is screen FPS.
            for cue in sorted(page.session.runtime._view_cues, key=lambda c: (c.start_ms, c.end_ms)):
                if cue.speaker_id in page.timeline.hidden_speakers or not page._subtitle_track_visibility.get(cue.speaker_id, True):
                    continue
                if coverage and cue.start_ms <= coverage[-1][1]:
                    coverage[-1] = (coverage[-1][0], max(coverage[-1][1], cue.end_ms))
                else:
                    coverage.append((cue.start_ms, cue.end_ms))
            result['environment'] = dict(platform=platform.platform(), qt=qVersion(), python=platform.python_version(),
                window=[window.width(), window.height()], dpr=window.devicePixelRatioF(),
                screens=[dict(name=s.name(), geometry=s.geometry().getRect(), refresh_hz=s.refreshRate(), dpr=s.devicePixelRatio()) for s in QApplication.screens()],
                preview_rect=page.position_overlay._content_rect().toRect().getRect(),
                timeline=[page.timeline.visible_start_ms, page.timeline.visible_duration_ms], video=stats())
            initial_scene = getattr(page, '_caption_scene', None)
            if initial_scene is not None and initial_scene.published is not None:
                initial_scene.published.image.save(str(output/'paused-overlay.png'))
                result['initial_scene'] = initial_scene.trace()
            from .blank_project_audit import _capture
            _capture(window, output/'window.png')
            token = playback_probe.configure(enabled=True, light=False)
            timer.start()
            memory_timer.start()
            result['first_playback'] = measure('first', float(spec.get('cold_seconds',4)))
            page._seek(spec['start'])
            QTest.qWait(1500)
            result['performance'] = measure('steady', spec['seconds'])
            if spec.get('repeats', 1) > 1:
                result['repeats'] = []
                for i in range(1, int(spec['repeats'])):
                    page._seek(spec['start'])
                    QTest.qWait(1500)
                    result['repeats'].append(measure('steady-'+str(i), spec['seconds']))
            final_scene = getattr(page, '_caption_scene', None)
            if final_scene is not None and hasattr(final_scene, '_motion_preheater'):
                result['motion_preheat'] = final_scene._motion_preheater.stats()
            timer.stop()
            memory_timer.stop()
            expected = spec['seconds'] * spec['rate'] * 1000
            result['checks']['media_advanced'] = expected*.95 <= result['performance']['media_advance_ms'] <= expected*1.15
            result['checks']['paused_after'] = bool(page.video._paused)
            result['checks']['gui_shutdown_requested'] = True
            result['passed'] = all(result['checks'].values())
            if spec.get('seconds',0)>180:
                import gc
                saved_path=page.project_path
                old_scene=getattr(page,'_caption_scene',None)
                project_ref=weakref.ref(page.project)
                before_close=psutil.Process().memory_info().rss/1048576
                page.undo_stack.setClean();page._close_project_session('endurance-release')
                if old_scene is not None:wait(lambda:not old_scene.thread.is_alive(),15)
                gc.collect();QTest.qWait(2000)
                result['release']=dict(rss_before_mb=before_close,rss_after_close_mb=psutil.Process().memory_info().rss/1048576,
                    project_collected=project_ref() is None,scene_stopped=old_scene is None or not old_scene.thread.is_alive(),
                    preheater_stopped=old_scene is None or old_scene._motion_preheater.thread is None or not old_scene._motion_preheater.thread.is_alive())
                page.open_project(saved_path)
                wait(lambda:page.project is not None and page._readiness.ready and not page._readiness.active,120)
                QTest.qWait(1000)
                result['release']['rss_after_reopen_mb']=psutil.Process().memory_info().rss/1048576
                result['checks']['endurance_close_reopen']=result['release']['scene_stopped'] and result['release']['preheater_stopped']
                result['passed']=all(result['checks'].values())
            if profiler is not None:
                profiler.dump_stats(str(output/'scene.prof'))
        except BaseException:
            result['error'] = traceback.format_exc()
        finally:
            timer.stop()
            memory_timer.stop()
            if token is not None:
                playback_probe.restore(token)
            SceneRasterizer.frame, SceneRasterizer.native_frame, CaptionScene.accept = frame_original, native_original, accept_original
            CaptionScene.preheat = preheat_original
            ProjectStateRuntime.cues_at = query_original
            if CaptionMotionPreheater is not None:
                CaptionMotionPreheater.request, CaptionMotionPreheater.take = request_original, take_original
            (output/'caption-posts.json').write_text(json.dumps(list(posts)), encoding='utf8')
            (output/'pipeline.json').write_text(json.dumps(list(pipeline)), encoding='utf8')
            if spec.get('audio'):(output/'audio-video-observations.json').write_text(json.dumps(audio_observations),'utf8')
            if spec.get('trace_prefetch'):
                (output/'prefetch-events.json').write_text(json.dumps(prefetch_events, indent=2), encoding='utf8')
            (output/'resources.json').write_text(json.dumps(resource_samples, indent=2), encoding='utf8')
            save()
            QApplication.instance().aboutToQuit.connect(lambda: (result.update(gui_shutdown=True), save()))
            page.undo_stack.setClean()
            window.result_exit_code = 0 if result['passed'] else 1
            window.close()
    QTimer.singleShot(250, execute)
