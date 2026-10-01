"""Opt-in GUI call-chain evidence, no production work or disk I/O during sample."""
from __future__ import annotations
import bisect
import collections
import json
import os
import sys
import time
import traceback
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


STAGES = {
    'position': {'_position_changed', '_flush_pending_playhead', '_apply_project_playhead'},
    'lookup': {'cues_at', '_renderer_cue_at_playhead', '_follow_playhead_selection', '_update_active_cues'},
    'selection': {'select_cue', '_select_cue_ui', 'set_selected', 'set_selection_scope', 'table_selection_changed', '_cue_table_selection_changed'},
    'inspector': {'_load_style_inspector', '_refresh_selected_cue_properties', '_load_motion_controls', '_refresh_current_review_context'},
    'style': {'resolve_caption_style', 'resolve_cue_visual', 'font_face', 'fit_single_line', 'build_visual_cue_snapshot'},
    'render': {'_activate_selected_advanced_if_needed', 'ensure_active_subtitle_renderer', '_schedule_advanced_preview', '_flush_advanced_preview', '_queue_live_layer_prefetch', '_publish_advanced_live', 'identity', 'stable_hash'},
    'track': {'compile_ass', '_refresh_ass_preview', '_submit_ass_preview', '_start_ass_worker'},
    'autosave': {'_autosave', '_capture_studio_state', '_start_autosave_worker', 'save_project'},
    'seek': {'_seek', 'seek', 'request_seek'},
    'timeline_paint': {'_paint_timeline', '_paint_timeline_contents', 'invalidate_ranges'},
    'media': {'_activate_multitrack_preview', '_refresh_waveform', '_refresh_thumbnails'},
    'nodes': {'_start_live_web_preview', '_ensure_web_live_preview', 'configure', 'configure_prepared', 'theme_archive_html', 'set_snapshot', '_warm_next'},
    'revision': {'_capture_render', 'consume', '_validate_and_commit'},
    'lifecycle': {'hideEvent', 'remove_compositor_overlay', 'revoke', '_trace_compositor_event', 'subtitle_visibility_trace', 'applied_visual_state', 'observed_property', 'active_compositor_overlay_ids', 'recipe_payload_for_style'},
}
NAMES = {name: stage for stage, names in STAGES.items() for name in names}
QT_NAMES = {'selectRow', 'scrollTo', 'setCurrentIndex', 'setSelected', 'clearSelection'}
QT_LIFECYCLE = {'setVisible', 'raise_', 'fromData'}


def stats(values):
    values = sorted(values)
    return {'n': len(values), 'p50_ms': round(values[len(values)//2], 4) if values else None,
            'p95_ms': round(values[min(len(values)-1, int(len(values)*.95))], 4) if values else None,
            'p99_ms': round(values[min(len(values)-1, int(len(values)*.99))], 4) if values else None,
            'max_ms': round(max(values), 4) if values else None}


def start(window, out):
    page = window.studio_page
    result = {'passed': False, 'calls': [], 'frames': [], 'heartbeat': [], 'checks': {}}
    def pump(seconds):
        until = time.perf_counter()+seconds
        while time.perf_counter()<until:
            QApplication.processEvents()
            time.sleep(.001)
    def run():
        count = int(os.environ.get('TWOBYTEASR_BOUNDARY_COUNT', '32'))
        duration = .45 + count * .225
        timer = None
        recorder = capture_log = None
        try:
            from .build_identity import load_build_identity
            result['identity'] = load_build_identity().to_dict()
            result['legacy_playback_module_replay'] = os.environ.get('TWOBYTEASR_BOUNDARY_LEGACY_REPLAY')=='1'
            window.raise_(); window.activateWindow()
            page.volume_slider.setValue(0); page.video.controller.set_volume(0)
            page.video.set_paused(True)
            page._set_review_mode(False)
            page.follow_playhead_toggle.setChecked(True)
            page.select_cue('S1-00')
            panels = os.environ.get('TWOBYTEASR_BOUNDARY_PANELS', 'both')
            page.cue_table.setVisible(panels in {'both', 'list'})
            page.context_drawer.setVisible(panels in {'both', 'tools'})
            result['panels'] = dict(requested=panels, list_visible=page.cue_table.isVisible(), tools_visible=page.context_drawer.isVisible())
            result['tracks'] = len(page.project.speakers)
            page._seek(0); pump(.7)
            if any(recipe.get('webTheme') for recipe in page.project.style_recipes.values()):
                # Prepare the initial theme while paused; no long autoplay.
                page._seek(.3); pump(1.6)
                page._seek(0); pump(.25)
            # Review selection is deliberately separate from currently playing cue.
            selected = page.selected_cue_id
            page._manual_selection_hold = False
            page.timeline.setFocus()
            page.undo_stack.setClean()
            if os.environ.get('TWOBYTEASR_BOUNDARY_CAPTURE')=='1':
                import subprocess
                from .processes import popen_hidden_subprocess
                capture_log=(out/'capture.log').open('wb')
                recorder=popen_hidden_subprocess([str(Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe'),'-v','warning','-y',
                    '-f','lavfi','-i',f'gfxcapture=hwnd={int(window.winId())}:max_framerate=60:capture_cursor=0',
                    '-t',str(duration+5),'-fps_mode','vfr','-c:v','h264_nvenc','-preset','p1','-cq','16','-b:v','0',str(out/'screen.mp4')],
                    purpose='record eight-second dense subtitle playback pixels',stdin=subprocess.PIPE,stdout=capture_log,stderr=capture_log)
                pump(1.2)
                result['capture_running']=recorder.poll() is None
                scene=page.video_compositor; origin=scene.mapToGlobal(QPoint(0,0))
                result['geometry']=[origin.x(),origin.y(),scene.width(),scene.height()]
                result['window_geometry']=[window.x(),window.y(),window.width(),window.height()]
            starts = sorted({cue.start_ms for cue in page.project.cues})
            active, pending, web_workers = {}, {}, {}
            frame_state = [-1, 0., None]
            now0 = time.perf_counter()
            hb = [now0]
            def beat():
                now = time.perf_counter()
                result['heartbeat'].append({'at_ms': (now-now0)*1000, 'delta_ms': (now-hb[0])*1000,
                    'project_ms': page.timeline.playhead_ms})
                hb[0] = now
            timer = QTimer(page); timer.setInterval(5); timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.timeout.connect(beat)
            def profile(frame, event, arg):
                name = frame.f_code.co_name
                isqt = event.startswith('c_') and getattr(arg, '__name__', '') in QT_NAMES | QT_LIFECYCLE
                if event.startswith('c_') and not isqt:
                    return
                if not isqt and (name not in NAMES or not ('twobyteasr' in frame.f_code.co_filename.lower() or 'original_playback' in frame.f_code.co_filename)):
                    return
                key = (id(frame), id(arg)) if isqt else id(frame)
                name = getattr(arg, '__name__', '') if isqt else name
                if event in {'call', 'c_call'}:
                    if name=='configure_prepared':
                        worker=frame.f_locals.get('self')
                        if worker is not None: web_workers[id(worker)]=worker
                    now = time.perf_counter()
                    active[key] = (now, name, frame.f_code.co_filename, time.thread_time())
                    if name == '_apply_project_playhead':
                        ms = int(frame.f_locals.get('milliseconds', 0))
                        cue_index = bisect.bisect_right(starts, ms)-1
                        row = {'at_ms': (now-now0)*1000, 'project_ms': ms, 'boundary': cue_index != frame_state[0],
                               'delta_ms': (now-frame_state[1])*1000 if frame_state[1] else None,
                               'cue_index': cue_index, 'selected': page.selected_cue_id}
                        frame_state[:] = [cue_index, now, row]
                        pending[key] = row
                        result['frames'].append(row)
                elif event in {'return', 'c_return', 'c_exception'} and key in active:
                    at, label, filename, cpu_at = active.pop(key)
                    elapsed = (time.perf_counter()-at)*1000
                    result['calls'].append({'at_ms': (at-now0)*1000, 'name': label,
                        'module': filename.rsplit('\\',1)[-1].rsplit('/',1)[-1],
                        'stage': ('qt_selection_scroll' if label in QT_NAMES else 'gui_image_decode' if label=='fromData' else 'lifecycle') if isqt else NAMES[label], 'ms': elapsed,
                        'project_ms': page.timeline.playhead_ms, 'cpu_ms': (time.thread_time()-cpu_at)*1000})
                    if key in pending: pending.pop(key)['handler_ms'] = elapsed
            page.video.set_paused(False)
            timer.start()
            sys.setprofile(profile)
            pump(duration)
            sys.setprofile(None)
            timer.stop()
            result['playback_seconds'] = time.perf_counter()-now0
            page.video.set_paused(True)
            pump(.08)
            if recorder and recorder.poll() is None:
                recorder.communicate(b'q',timeout=8)
            frames = result['frames']
            boundary = [r for r in frames if r['boundary'] and r['cue_index']>=0]
            ordinary = [r for r in frames if not r['boundary']]
            totals = collections.defaultdict(list)
            for row in result['calls']: totals[row['module']+':'+row['name']].append(row['ms'])
            result['summary'] = {'boundary_handler': stats([r['handler_ms'] for r in boundary]),
                'boundary_frame_delta': stats([r['delta_ms'] for r in boundary if r['delta_ms'] is not None]),
                'ordinary_frame_delta': stats([r['delta_ms'] for r in ordinary if r['delta_ms'] is not None]),
                'gui_heartbeat': stats([r['delta_ms'] for r in result['heartbeat']]),
                'functions': {name: stats(values) for name, values in totals.items()}}
            forbidden = {'selection', 'inspector', 'track', 'autosave', 'seek', 'qt_selection_scroll', 'gui_image_decode'}
            counts = collections.Counter(r['stage'] for r in result['calls'])
            checks = result['checks']
            checks['requested_boundaries'] = len(boundary)>=count-2
            checks['bounded_playback_duration'] = result['playback_seconds']<=duration+.5
            checks['selected_unchanged'] = all(r['selected']==selected for r in frames) and page.selected_cue_id==selected
            checks['no_edit_side_effects'] = all(counts[key]==0 for key in forbidden)
            checks['p95_below_16_7'] = bool(boundary) and result['summary']['boundary_handler']['p95_ms']<16.7
            checks['max_below_50'] = bool(boundary) and result['summary']['boundary_handler']['max_ms']<=50
            result['stage_counts'] = {key:counts[key] for key in (*STAGES,'qt_selection_scroll','gui_image_decode')}
            result['web_workers']=[{'generation':w._configuration_generation,'metrics':list(w.metrics)} for w in web_workers.values()]
            worker = getattr(page,'_web_live_worker',None)
            if worker is not None:
                result['web_worker_alive'] = worker.running
                result['web_configuration_generation'] = worker._configuration_generation
                result['web_metrics'] = list(worker.metrics)
            result['prepared_captions'] = getattr(getattr(page,'_caption_playback_cache',None),'prepared_count',0)
            # Screen capture is outside the measured interval.
            page.video.controller.screenshot_to_file(out/'video-after.png')
            window.grab().save(str(out/'studio-after.png'))
            page._seek(2.55); pump(.4)
            page.video.controller.screenshot_to_file(out/'video-active.png')
            window.grab().save(str(out/'studio-active.png'))
            # Real table click must still select and populate the editor.
            page.cue_table.show(); pump(.05)
            row = page.cue_model.row_for_cue_id('S1-03')
            index = page.cue_model.index(row, 3)
            page.cue_table.scrollTo(index); pump(.05)
            QTest.mouseClick(page.cue_table.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, page.cue_table.visualRect(index).center())
            pump(.12)
            checks['manual_click_edits'] = page.selected_cue_id=='S1-03' and page.cue_text.toPlainText()==page._cue_lookup['S1-03'].text
            result['passed'] = all(checks.values())
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            sys.setprofile(None)
            if timer: timer.stop()
            if recorder and recorder.poll() is None: recorder.communicate(b'q',timeout=8)
            if capture_log: capture_log.close()
            if page.video.controller: page.video.set_paused(True)
            page.undo_stack.setClean()
            (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            QTimer.singleShot(150, window.close)
    QTimer.singleShot(350, run)
