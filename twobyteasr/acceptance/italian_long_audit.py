"""Extra real-project phases; used only by the explicit isolated performance audit."""
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf8')).hexdigest()


def contents(project):
    return digest(([(c.id, c.text, c.original_text, c.start_ms, c.end_ms, c.speaker_id)
                    for c in project.cues], project.generation_metadata.get('translations', {})))


def presentation(project):
    # Undo deliberately advances the publication generation to reject old
    # frames. It is an ordering token, not authored presentation content.
    cues = [{k:v for k,v in asdict(c).items() if k != 'appearance_generation'} for c in project.cues]
    return digest((cues, [asdict(s) for s in project.styles],
                   project.style_recipes, project.effects))


def install(Audit, window, out):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from .blank_project_audit import _capture
    original_snapshot = Audit.snapshot
    def snapshot(self, label):
        row = original_snapshot(self, label)
        page = self.page
        cache = getattr(page, '_caption_playback_cache', None)
        row['widgets'] = len(window.findChildren(QWidget))
        row['undo_index_receivers'] = page.undo_stack.receivers('2indexChanged(int)')
        row['caption_queue'] = ({'frames': len(cache._frames),
            'pending': len(cache._pending[1]) if cache._pending else 0,
            'materialized': len(cache._materialized.project.cues) if cache._materialized else 0}
            if cache else {})
        return row
    Audit.snapshot = snapshot

    def event_filter(self, watched, event):
        if (getattr(self, '_italian_save_start', None) is not None and event.type()==QEvent.Paint
                and watched.objectName()=='studioManualSaveProgress'):
            self.result.setdefault('italian_save_feedback_ms', (time.perf_counter()-self._italian_save_start)*1000)
        if (getattr(self, '_italian_bulk_start', None) is not None and event.type()==QEvent.Paint
                and watched.objectName()=='studioBulkTransformProgress'):
            self.result.setdefault('italian_bulk_feedback_ms', (time.perf_counter()-self._italian_bulk_start)*1000)
        return False
    Audit.eventFilter = event_filter

    def identity(self):
        page = self.page
        p = page.project
        self._italian_contents = contents(p)
        QApplication.instance().installEventFilter(self)
        self.result['italian_identity'] = {
            'project_id': p.project_id, 'cues': len(p.cues),
            'translations': len(p.generation_metadata.get('translations', {})),
            'speaker_cues': dict(Counter(c.speaker_id for c in p.cues)),
            'speakers': [asdict(s) for s in p.speakers],
            'bilingual': p.studio_state.get('bilingual'),
            'timeline_bilingual': page.timeline.bilingual,
            'subtitle_rows': len(page.timeline._track_layout()[0]),
            'physical_subtitle_rows': len(page.timeline._display_rows()),
            'translation_rows': int(page.timeline._track_layout()[1] is not None),
            'video_rows': len(page.timeline._video_track_rects()),
            'audio_rows': len(page.timeline._audio_track_rects()),
            'contents_sha256': self._italian_contents,
            'readiness': page._readiness.profile,
            'open_phases': getattr(page, 'last_open_profile', {}),
            'video_controller': type(page.video.controller).__name__,
            'independent_captions': True,
        }
        cache = getattr(page, '_caption_playback_cache', None)
        self.result['italian_identity']['caption_cache'] = ({
            'prepared': cache.prepared_count, 'materialized': len(cache._materialized.project.cues)
            if cache._materialized else None, 'worker_builds': cache.worker_builds,
            'reasons': cache.full_rebuilds,
        } if cache else {})
        _capture(window, out / 'italian-first-screen.png')
        yield .1

    def navigation(self):
        page, tl = self.page, self.page.timeline
        initial_contents = contents(page.project)
        page.video.set_paused(True)
        rows = []
        for seconds in (15., 2400., 4800., 35., 2450., 4850.):
            t = time.perf_counter()
            yield from self.track('italian-seek', lambda s=seconds: page._seek(s))
            def ready(s=seconds):
                observed = page.video._last_mpv_time_pos_ms
                return (observed is not None and abs(observed - s*1000) < 150
                        and not page.video._playback_clock.snapshot().seeking)
            yield self.until(ready, 12, f'far-seek-{seconds}')
            rows.append({'target_s': seconds, 'completed_ms': (time.perf_counter()-t)*1000,
                         'acknowledged': ready()})
            page.video.controller.screenshot_to_file(out/f'italian-seek-{int(seconds)}.png', mode='video')
            yield .1
        self.result['italian_far_seek'] = rows
        self.result['checks']['italian_far_seeks'] = all(r['acknowledged'] for r in rows)
        tl.set_visible_window(2400000, 120000)
        yield .3
        yield from self.gesture('italian-scrub', QPointF(tl.TRACK_HEADER_WIDTH+80, 15), 420, steps=36)
        for span in (120000, 30000, 300000, 120000):
            for shift in (0, 15000, 30000, 45000):
                yield from self.track('italian-scroll-zoom',
                    lambda s=span, d=shift: tl.set_visible_window(2400000+d, s))
        expanded = bool(page.project.studio_state.get('speaker_roles', {}).get('expanded'))
        for value in (True, False, True, expanded):
            yield from self.track('italian-expand-tracks', lambda v=value: tl.set_group_expanded(v))
        bar = getattr(tl, '_vscroll', None)
        if bar is None:
            from PySide6.QtWidgets import QScrollBar
            bar = next((b for b in tl.findChildren(QScrollBar) if b.orientation()==Qt.Vertical), None)
        if bar:
            for value in (bar.maximum(), bar.minimum(), bar.maximum(), bar.minimum()):
                yield from self.track('italian-vertical-scroll', lambda v=value: bar.setValue(v))
        self.result['checks']['navigation_preserved_contents'] = contents(page.project)==initial_contents

    def controls(self):
        from ..timeline.selection_scope import SelectionScope
        from ..caption_style.style_resolution import resolve_cue_visual
        page = self.page
        self.clean_project()
        baseline = presentation(page.project)
        chosen = [c.id for c in page.project.cues[50:73]]
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(chosen, chosen[0]))
        yield .2
        yield from self.track('italian-ctrl-a', page._select_all_timeline_cues)
        self.result['checks']['italian_ctrl_a_full'] = len(page.selected_cue_ids()) == len(page.project.cues)
        layer = page.style_layer
        layer.setCurrentIndex(layer.findData('group'))
        for number in (62., 64.):
            count = page.undo_stack.index()
            def apply(value=number):
                page.style_font_size.setValue(value)
                page._commit_style_now()
            yield from self.track('italian-all-font', apply)
            self.result['checks'][f'all_font_{number}'] = all(
                resolve_cue_visual(page.project, c).style.font_size==number for c in page.project.cues)
            self.result['checks'][f'all_font_one_undo_{number}'] = page.undo_stack.index()==count+1
            changed = presentation(page.project)
            yield from self.track('italian-all-undo', page.undo_stack.undo)
            self.result['checks'][f'all_font_undo_restores_{number}'] = presentation(page.project)==baseline
            yield from self.track('italian-all-redo', page.undo_stack.redo)
            self.result['checks'][f'all_font_redo_restores_{number}'] = presentation(page.project)==changed
            page.undo_stack.undo()
            yield .2
        page.cue_controller.apply_selection_scope(SelectionScope.explicit(chosen, chosen[0]))
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        panel = page.caption_transform_panel
        yield from self.track('italian-show-transform', panel.refresh)
        count = page.undo_stack.index()
        before = {c.id: asdict(c) for c in page.project.cues}
        yield from self.track('italian-selected-position', lambda: panel.apply({'position_x': 1000.}))
        after = {c.id: asdict(c) for c in page.project.cues}
        touched = {key for key in before if before[key] != after[key]}
        self.result['checks']['selected_position_exact_scope'] = touched == set(chosen)
        self.result['checks']['position_one_undo'] = page.undo_stack.index()==count+1
        changed = presentation(page.project)
        yield from self.track('italian-position-undo', page.undo_stack.undo)
        self.result['checks']['position_undo_restores'] = presentation(page.project)==baseline
        yield from self.track('italian-position-redo', page.undo_stack.redo)
        self.result['checks']['position_redo_restores'] = presentation(page.project)==changed
        self.result['checks']['controls_preserved_contents'] = contents(page.project)==self._italian_contents
        _capture(window, out / 'italian-edited.png')
        self._italian_save_start = time.perf_counter()
        yield from self.track('italian-save', page.save)
        self._italian_save_start = None
        yield 1.
        path = str(page.session.project_path)
        expected = presentation(page.project)
        self.result['italian_saved_sha256'] = hashlib.sha256(__import__('pathlib').Path(path).read_bytes()).hexdigest()
        old = page.project
        t = time.perf_counter()
        page.show_project_hub(skip_dirty_guard=True)
        yield self.until(lambda: page.project is None, 30, 'italian-close')
        self.result['italian_close_ms'] = (time.perf_counter()-t)*1000
        yield .2
        t = time.perf_counter()
        window.open_studio_project(path, mode='edit', source='startup_audit')
        yield self.until(lambda: page.project is not None and page.project is not old and self.ready(),
                         90, 'italian-reopen')
        self.result['italian_reopen_ms'] = (time.perf_counter()-t)*1000
        self.result['checks']['italian_presentation_persisted'] = presentation(page.project)==expected
        self.result['checks']['italian_contents_persisted'] = contents(page.project)==self._italian_contents
        _capture(window, out / 'italian-reopened.png')
        yield .3

    def speakers(self):
        from ..studio.studio_speaker_manager import SpeakerManagerDialog
        page = self.page
        initial = contents(page.project)
        initial_speakers = [asdict(s) for s in page.project.speakers]
        dlg = SpeakerManagerDialog(page)
        dlg.show()
        self.result['speaker_manager'] = {'cards': list(dlg.cards), 'snapshot': dlg._snapshot_in_project}
        yield .3
        for key in list(dlg.cards)[-2:]:
            card = dlg.cards.get(key)
            if card is None or 'ignore' not in card.roles.buttons:
                continue
            index = page.undo_stack.index()
            yield from self.track('italian-ignore-speaker',
                lambda c=card: QTest.mouseClick(c.roles.buttons['ignore'], Qt.LeftButton))
            yield .2
            self.result['checks'][f'ignore_undo_added_{key}'] = page.undo_stack.index()==index+1
            yield from self.track('italian-restore-speaker', page.undo_stack.undo)
            yield .2
            self.result['checks'][f'ignore_restores_contents_{key}'] = contents(page.project)==initial
            self.result['checks'][f'ignore_restores_speakers_{key}'] = [asdict(s) for s in page.project.speakers]==initial_speakers
        dlg.close()
        dlg.deleteLater()
        yield .3

    def rates(self):
        page = self.page
        rows = []
        for rate in (1., 2., 4.):
            page.video.set_paused(True)
            page._seek(2400.)
            yield .4
            page._set_speed(rate)
            yield .2
            drops = lambda: {k: page.video.controller.get_property(k, None) for k in
                ('frame-drop-count', 'decoder-frame-drop-count', 'vo-delayed-frame-count')}
            before = drops()
            start = time.perf_counter()
            page.video.set_paused(False)
            samples = []
            while time.perf_counter()-start < 10.:
                samples.append({'t': time.perf_counter(), **self._av_sample()})
                yield .05
            page.video.set_paused(True)
            yield .1
            end = drops()
            rows.append({'rate': rate, 'wall_s': time.perf_counter()-start,
                         'samples': samples, 'drop_delta': {k: end[k]-before[k]
                             if isinstance(end[k], (int,float)) and isinstance(before[k],(int,float)) else None
                             for k in end}})
            page.video.controller.screenshot_to_file(out/f'italian-rate-{int(rate)}.png', mode='window')
            yield .2
        self.result['italian_rates'] = rows
        page._set_speed(1.)
        self.result['checks']['rates_preserved_contents'] = contents(page.project)==self._italian_contents

    def bulk_position(self):
        page = self.page
        page.video.set_paused(True)
        page._select_all_timeline_cues()
        page.style_layer.setCurrentIndex(page.style_layer.findData('group'))
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        panel = page.caption_transform_panel
        yield from self.track('bulk-position-inspector', panel.refresh)
        before = presentation(page.project)
        count = page.undo_stack.index()
        self._italian_bulk_start = time.perf_counter()
        yield from self.track('bulk-position-all', lambda: panel.apply({'position_x': 1000.}))
        self._italian_bulk_start = None
        self.result['checks']['bulk_position_all_one_undo'] = page.undo_stack.index()==count+1
        yield from self.track('bulk-position-all-undo', page.undo_stack.undo)
        self.result['checks']['bulk_position_all_undo_restores'] = presentation(page.project)==before
        yield .2

    def dense(self):
        page = self.page
        def scene_state():
            scene = getattr(page,'_caption_scene',None)
            trace = scene.trace() if scene is not None else {}
            return {k:trace.get(k) for k in ('expected_cue_ids','expected_display_cue_ids',
                                           'rendered_cue_ids','visible','owner')}
        page.video.set_paused(True)
        page._set_speed(1.)
        page._seek(2190.)  # Actual maximum: 15 cue starts / 30 s, three speakers.
        yield .5
        start = time.perf_counter()
        page.video.set_paused(False)
        samples = []
        while time.perf_counter()-start < 15.:
            samples.append({'at':time.perf_counter(),'media_ms':float(page._caption_sample_ms()),
                            'scene':scene_state()})
            yield .1
        page.video.set_paused(True)
        yield .1
        self.result['dense_playback'] = {'start_s':2190.,'wall_s':time.perf_counter()-start,'samples':samples}
        page._seek(2901.833333)
        yield .8
        expected = set(c.id for c in page.session.runtime.cues_at(page._caption_sample_ms()))
        trace = scene_state()
        self.result['overlap_frame'] = {'sample_ms':float(page._caption_sample_ms()), 'expected':sorted(expected),'scene':trace}
        self.result['checks']['overlap_all_originals_rendered'] = bool(expected) and expected <= set(trace.get('rendered_cue_ids',()))
        _capture(window,out/'italian-overlap.png')
        self.result['checks']['dense_preserved_contents'] = contents(page.project)==self._italian_contents
        yield .1

    def pixels(self):
        """Real visible pixels, separate from clocks, Qt paint and decoded FPS."""
        import subprocess
        import psutil
        import statistics
        import ctypes
        if os.environ.get('ITALIAN_VISIBLE') != '1':
            raise RuntimeError('Actual desktop pixels require --visible')
        page = self.page
        full_path = str(page.session.project_path)
        initial = contents(page.project)
        records = []
        for label, rate in (('full-1x',1.), ('full-2x',2.), ('full-4x',4.),
                            ('original-1x',1.), ('pure-video-1x',1.)):
            page.video.set_paused(True)
            if label == 'original-1x':
                page.bilingual_mode_actions['original'].trigger()
                yield 1.
            elif label == 'pure-video-1x':
                page.undo_stack.undo()  # Restore the complete bilingual state first.
                yield .2
                page.save()
                window.open_studio_project(str(out/'pure-video.2byteproj'), mode='edit', source='startup_audit')
                yield self.until(lambda: self.ready() and page.project.project_id=='italian-pure-video-control',
                                 90, 'pure-video-ready')
            page._seek(2400.)
            yield .7
            page._set_speed(rate)
            yield .2
            window.raise_()
            window.activateWindow()
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            if not user.SetWindowPos(int(window.winId()), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x53):
                raise ctypes.WinError(ctypes.get_last_error())
            rect = page.position_overlay._content_rect()
            origin = page.position_overlay.mapToGlobal(QPoint(round(rect.left()+rect.width()*.18),
                                                               round(rect.top()+rect.height()*.23)))
            dpr = window.devicePixelRatioF()
            sample_rect = [round(origin.x()*dpr), round(origin.y()*dpr),
                           round(min(384, rect.width()*.5)*dpr), round(24*dpr)]
            proc = psutil.Process()
            pids = [proc.pid] + [p.pid for p in proc.children(recursive=True)]
            folder = out/('pixels-'+label)
            folder.mkdir()
            (folder/'config.json').write_text(json.dumps({'rect': sample_rect, 'pids': pids}), encoding='utf8')
            root = Path(__file__).resolve().parents[2]
            # The explicitly selected measurement interpreter is separate from
            # a frozen app's sys.executable, which is the GUI itself.
            probe = subprocess.Popen([os.environ['ITALIAN_PYTHON'], '-B',
                str(Path(os.environ['ITALIAN_PROBE_SCRIPT'])), str(folder)],
                cwd=root, creationflags=0x08000000, stdout=subprocess.DEVNULL,
                stderr=(folder/'stderr.log').open('wb'))
            yield self.until(lambda: (folder/'ready').exists() or probe.poll() is not None, 10, label+'-probe')
            yield .5  # Paused control samples expose capture noise before playback.
            before_cpu = proc.cpu_times()
            start = time.perf_counter()
            start_ms = page.video.visual_position()*1000
            page.video.set_paused(False)
            deadline = start+8.
            yield lambda: time.perf_counter() >= deadline
            page.video.set_paused(True)
            end = time.perf_counter()
            end_ms = page.video.visual_position()*1000
            (folder/'stop').touch()
            yield self.until(lambda: probe.poll() is not None, 10, label+'-stop')
            payload = json.loads((folder/'pixels.json').read_text(encoding='utf8'))
            user.SetWindowPos(int(window.winId()), ctypes.c_void_p(-2), 0, 0, 0, 0, 0x13)
            paused = [r for r in payload['rows'] if start-.4 <= r['at'] <= start-.1 and r['owned']]
            samples = [r for r in payload['rows'] if start+.5 <= r['at'] <= end-.1]
            valid = [r for r in samples if r['owned']]
            changes = []
            for r in valid:
                if not changes or r['hash']!=changes[-1]['hash']:
                    changes.append(r)
            intervals = [(b['at']-a['at'])*1000 for a,b in zip(changes,changes[1:])]
            gaps = [(b['at']-a['at'])*1000 for a,b in zip(samples,samples[1:])]
            after_cpu = proc.cpu_times()
            percentile = lambda v,q: sorted(v)[min(len(v)-1, round((len(v)-1)*q))] if v else None
            records.append({'label':label, 'samples':len(samples), 'valid_samples':len(valid),
                'paused_samples':len(paused), 'paused_distinct_pixels':len({r['hash'] for r in paused}),
                'valid_fraction':len(valid)/max(1,len(samples)), 'pixel_changes':len(changes),
                'pixel_changes_per_s': len(changes)/max(.001,end-start-.6),
                'change_interval_p95_ms': percentile(intervals,.95),
                'longest_same_pixels_ms': max(intervals,default=None),
                'probe_gap_p95_ms': percentile(gaps,.95), 'probe_max_gap_ms':max(gaps,default=None),
                'probe_capture_p95_ms':percentile([r['capture_ms'] for r in valid],.95),
                'wall_s':end-start,'media_s':(end_ms-start_ms)/1000,
                'cpu_s':after_cpu.user+after_cpu.system-before_cpu.user-before_cpu.system,
                'rss_mb':proc.memory_info().rss/1e6,'error':payload['error']})
            self.result['italian_pixels'] = records
            self.save()
            _capture(window,out/(label+'.png'))
            yield .2
        window.open_studio_project(full_path, mode='edit', source='startup_audit')
        yield self.until(lambda: self.ready() and str(page.session.project_path)==full_path, 90, 'full-restored')
        self.result['checks']['pixel_diagnostics_restored_full_contents'] = contents(page.project)==initial
        self.result['checks']['desktop_pixel_samples_owned'] = all(r['valid_fraction']>.95 and not r['error']
                                                                    for r in records)

    Audit.phase_italian_identity = identity
    Audit.phase_italian_navigation = navigation
    Audit.phase_italian_controls = controls
    Audit.phase_italian_speakers = speakers
    Audit.phase_italian_rates = rates
    Audit.phase_italian_bulk_position = bulk_position
    Audit.phase_italian_dense = dense
    Audit.phase_italian_pixels = pixels
