"""Opt-in real-window checks for the 2026-10-11 six usage fixes.

Runs inside the normal desktop entry (source or frozen EXE) on an owned copy
of a project under ``tmp/``: real window-level mouse/keyboard events, window
captures, and measured timings. ``input.json`` selects one fixed phase
(``generate``, ``qw``, ``er``, ``xml``); nothing outside ``output`` is written.
"""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    spec = json.loads((output / 'input.json').read_text('utf-8'))
    result = dict(phase=spec['phase'], checks=[], records=[], identity=load_build_identity().to_dict(), passed=False)
    page = window.studio_page
    log = (output / 'operations.jsonl').open('w', encoding='utf-8')

    def event(kind, **values):
        log.write(json.dumps(dict(t=time.monotonic(), kind=kind, **values), ensure_ascii=False, default=str) + '\n')
        log.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        event('check', **result['checks'][-1])

    def record(name, **values):
        result['records'].append(dict(name=name, **values))
        event('record', name=name, **values)

    def capture(name):
        QApplication.processEvents()
        _capture(window, output / (name + '.png'))
        event('capture', name=name)

    def capture_widget(widget, name):
        QApplication.processEvents()
        widget.grab().save(str(output / (name + '.png')))
        event('capture', name=name)

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active

    def reveal(widget):
        """Scroll like a user would; report whether the control is on screen."""
        from PySide6.QtWidgets import QScrollArea
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget, 4, 4)
            parent = parent.parentWidget()
        QApplication.processEvents()
        return widget.isVisible() and not widget.visibleRegion().isEmpty()

    def click(widget, point=None, button=Qt.LeftButton, modifiers=Qt.NoModifier):
        """Platform-level press/release through the top-level window."""
        top = widget.window()
        point = widget.rect().center() if point is None else point
        handle, at = top.windowHandle(), widget.mapTo(top, point)
        QTest.mouseMove(handle, at)
        QTest.mousePress(handle, button, modifiers, at)
        QTest.mouseRelease(handle, button, modifiers, at)

    def key(key_code, modifiers=Qt.NoModifier):
        QTest.keyClick(window.windowHandle(), key_code, modifiers)

    def sequence_state():
        from .studio_edit_sequence import sequence_of, timeline_duration_ms
        project = page.project
        sequence = sequence_of(project)
        tracks = {t.id: [(c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms) for c in t.clips]
                  for t in (*project.video_tracks, *project.audio_tracks)}
        return dict(
            segments=[(s.source_in_ms, s.source_out_ms, s.timeline_in_ms, s.timeline_out_ms) for s in sequence.segments],
            timeline_duration_ms=timeline_duration_ms(project), tracks=tracks,
            playhead_ms=int(page.timeline.playhead_ms), visible_start_ms=int(page.timeline.visible_start_ms),
            visible_duration_ms=int(page.timeline.visible_duration_ms),
            undo_index=page.session.undo_stack.index(), undo_text=page.session.undo_stack.undoText(),
            save_state=page.save_state.text(),
            accepted=[(c.id, c.source_in_ms, c.source_out_ms) for c in sequence.clip_candidates if c.status == 'accepted'],
            player_path=str(getattr(page.video, '_media_path', '') or ''),
            playback_mode=str(getattr(page, '_playback_mode', '')))

    def player_source_ms():
        try:
            snapshot = page.video.playback_position_snapshot()
            return dict(presentation_media_ms=round(snapshot.presentation_media_ms),
                        paused=bool(snapshot.paused))
        except Exception as exc:
            return dict(error=str(exc))

    # ------------------------------------------------------------ generate
    def generate_steps():
        panel = page.highlight_panel
        page._open_clip_assistant()
        yield .8
        width = int(spec.get('panel_width', 0))
        if width:
            sizes = page.upper_splitter.sizes()
            total = sum(sizes)
            page.upper_splitter.setSizes([sizes[0], total - sizes[0] - width, width])
            yield .5
        capture('generate-01-before')
        capture_widget(page.context_panel, 'generate-01-panel')
        record('before', **sequence_state())
        if len(sequence_state()['segments']) > 1:
            record('restore_button', visible=reveal(panel.restore_button), enabled=panel.restore_button.isEnabled())
            click(panel.restore_button)
            yield 1.5
            record('after_restore', **sequence_state())
            capture('generate-02-restored')
        record('generate_button', visible=reveal(panel.generate_button), enabled=panel.generate_button.isEnabled())
        capture_widget(page.context_panel, 'generate-02-panel-scrolled')
        click(panel.generate_button)
        clicked = time.monotonic()
        yield 1.5
        state = sequence_state()
        record('after_generate', seconds=round(time.monotonic() - clicked, 3),
               result_text=panel.edit_result.text(), result_visible=panel.edit_result.isVisible(),
               paused=player_source_ms(), **state)
        capture('generate-03-after')
        capture_widget(page.context_panel, 'generate-03-panel')
        check('playhead at the start of the generated edit (within one frame)', 0 <= state['playhead_ms'] <= 40, state['playhead_ms'])
        check('whole generated timeline in view', state['visible_start_ms'] == 0
              and state['visible_duration_ms'] >= state['timeline_duration_ms'], state)
        check('panel states what was generated', panel.edit_result.isVisible() and '2' in panel.edit_result.text(),
              panel.edit_result.text())
        click(panel.generate_button)
        yield 1.0
        again = sequence_state()
        check('a second click adds no undo step', again['undo_index'] == state['undo_index'], again['undo_index'])
        record('after_second_click', result_text=panel.edit_result.text())
        expected = spec.get('expected_segments')
        if expected:
            check('generated segments follow the bin', [list(s) for s in state['segments']] == expected,
                  state['segments'])
            check('timeline duration is the kept total', state['timeline_duration_ms'] == spec['expected_duration_ms'],
                  state['timeline_duration_ms'])
        for probe, label in spec.get('seek_probes', ()):
            page._seek(probe / 1000.0)
            yield 1.2
            record('seek_probe', label=label, timeline_ms=probe, player=player_source_ms(),
                   playhead_ms=int(page.timeline.playhead_ms))
        capture('generate-04-seek')
        key(Qt.Key_Z, Qt.ControlModifier)
        yield 1.0
        record('after_undo', **sequence_state())
        key(Qt.Key_Y, Qt.ControlModifier)
        yield 1.0
        redone = sequence_state()
        record('after_redo', **redone)
        check('redo restores the generated edit', redone['segments'] == state['segments'], redone['segments'])
        # save, close, reopen: order, durations and linked audio survive
        key(Qt.Key_S, Qt.ControlModifier)
        yield 2.0
        from .studio_project import load_project
        saved = load_project(spec['project'])
        from .studio_edit_sequence import ensure_edit_sequence
        seq = ensure_edit_sequence(saved)
        reopened = [(s.source_in_ms, s.source_out_ms, s.timeline_in_ms, s.timeline_out_ms) for s in seq.segments]
        audio = [(c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms)
                 for t in saved.audio_tracks for c in t.clips]
        check('saved project keeps the generated order and durations', [list(x) for x in reopened] == [list(x) for x in state['segments']], reopened)
        check('linked audio follows the generated video', [list(x) for x in audio] == [list(x) for x in state['segments']], audio)
        # Panel views at the narrow width: bin expanded; then widened by the splitter.
        reveal(panel.bin_toggle)
        click(panel.bin_toggle)
        yield .6
        capture_widget(page.context_panel, 'generate-04b-bin-expanded')
        record('panel_layout', results_height=panel.results.height(), panel_height=panel.height(),
               bin_visible=panel.bin.isVisible(), settings_visible=panel.settings_area.isVisible(),
               max_width=page.context_panel.maximumWidth())
        check('candidate list is the main area of the panel', panel.results.height() >= 0.35 * panel.height(),
              dict(results=panel.results.height(), panel=panel.height()))
        sizes = page.upper_splitter.sizes()
        total = sum(sizes)
        page.upper_splitter.setSizes([sizes[0], total - sizes[0] - 740, 740])
        yield .8
        capture_widget(page.context_panel, 'generate-04c-wide-panel')
        record('wide_panel', width=page.context_panel.width())
        check('the tool panel can be widened beyond 520 px', page.context_panel.width() > 600, page.context_panel.width())
        page.upper_splitter.setSizes(sizes)
        yield .5
        # return to the full recording, then forward again by undo/redo
        reveal(panel.restore_button)
        click(panel.restore_button)
        yield 1.5
        full = sequence_state()
        record('after_restore_full', result_text=panel.edit_result.text(), **full)
        check('return to full recording shows the whole source', len(full['segments']) == 1
              and full['segments'][0][1] - full['segments'][0][0] == int(page.project.media.duration_ms), full['segments'])
        capture('generate-05-full')
        result['passed'] = all(x['passed'] for x in result['checks'])

    # ------------------------------------------------------------ Q / W
    def qw_steps():
        from .studio_edit_sequence import sequence_of
        t = page.timeline
        timings = dict(paint=[])
        cls = type(t)
        paint = cls.paintEvent

        def timed_paint(self, ev):
            started = time.perf_counter(); paint(self, ev)
            if self is t:
                timings['paint'].append((started, time.perf_counter()))
        cls.paintEvent = timed_paint
        try:
            page.video.set_paused(True); page._sync_play_button(True)
        except Exception as exc:
            record('pause_failed', error=str(exc))
        yield .8
        record('paused_at_start', playing_after_open=True)
        by_text = {c.text: c for c in page.project.cues}
        before_cue, after_cue = by_text[spec['before_text']], by_text[spec['after_text']]
        before_id, after_id = before_cue.id, after_cue.id

        def show_window():
            t.set_visible_window(max(0, before_cue.start_ms - 3000), spec.get('visible_ms', 12000))
        show_window()
        yield .6
        lane = t._track_layout()[0][after_cue.speaker_id]

        def lane_point(ms):
            return QPoint(round(t._time_to_x(ms)), round(lane.center().y()))

        def ruler_point(ms):
            return QPoint(round(t._time_to_x(ms)), max(2, t.RULER_HEIGHT // 2))

        def cues_now():
            return {c.id: (c.start_ms, c.end_ms, c.text) for c in page.project.cues}

        def state(tag):
            now = cues_now()
            row = dict(tag=tag, selected=page.selected_cue_id,
                       selected_text=now.get(page.selected_cue_id, ('', '', ''))[2],
                       highlighted=sorted(getattr(t, 'selected_ids', ()) or ()),
                       hold=bool(getattr(page, '_manual_selection_hold', False)),
                       playhead=int(t.playhead_ms), undo_index=page.session.undo_stack.index(),
                       undo_text=page.session.undo_stack.undoText(), save_state=page.save_state.text(),
                       before=now.get(before_id), after=now.get(after_id),
                       segments=[(s.source_in_ms, s.source_out_ms, s.timeline_in_ms, s.timeline_out_ms)
                                 for s in sequence_of(page.project).segments],
                       focus=type(QApplication.focusWidget()).__name__ if QApplication.focusWidget() else None)
            record('qw_state', **row)
            return row

        presses = []

        if spec.get('legacy_qw'):
            # Measurement only: the pre-2026-10-11 Q/W path (explicit caption
            # or video ripple; clock rule for the light selection).
            from .studio_cue_controller import StudioCueController as C
            from .studio_theme import MIN_CUE_DURATION_MS
            from .studio_edit_sequence import map_timing_to_source
            from .studio_commands import cue_by_id

            def legacy_trim(self, edge):
                project = self.session.project
                if not project:
                    return
                cue = self.explicit_edit_target()
                if cue is None:
                    self.page._ripple_video_to_playhead(edge)
                    return
                if len(self.selected_cue_ids()) != 1:
                    return
                if cue.speaker_id in self.page.timeline.locked_speakers:
                    return
                point = int(self.page.timeline.playhead_ms)
                start, end = (point, cue.end_ms) if edge == 'start' else (cue.start_ms, point)
                if start < 0 or end - start < MIN_CUE_DURATION_MS:
                    return
                if map_timing_to_source(project, cue_by_id(project, cue.id), start, end) is None:
                    return
                self.set_timing(cue.id, start, end)
            original_sync = C.sync_playhead_target
            C.trim_to_playhead = legacy_trim
            C.sync_playhead_target = lambda self, ms, *, force=False, rule='clock': original_sync(self, ms, force=force)
            record('legacy_qw', active=True)

        def press(code, tag):
            index = page.session.undo_stack.index()
            pushed = []
            stack = page.session.undo_stack
            handler = lambda *_: pushed.append(time.perf_counter())
            stack.indexChanged.connect(handler)
            prior = state(tag + ':before')
            profiler = None
            if spec.get('profile'):
                import cProfile
                profiler = cProfile.Profile()
                profiler.enable()
            sent = time.perf_counter()
            key(code)
            returned = time.perf_counter()
            if profiler is not None:
                profiler.disable()
                import io, pstats
                buffer = io.StringIO()
                pstats.Stats(profiler, stream=buffer).sort_stats('cumulative').print_stats(45)
                (output / f'profile-{tag}.txt').write_text(buffer.getvalue(), 'utf-8')
            yield .5
            stack.indexChanged.disconnect(handler)
            painted = [end for begin, end in timings['paint'] if pushed and begin >= pushed[0]]
            row = state(tag + ':after')
            row.update(command_ms=round((pushed[0] - sent) * 1000, 2) if pushed else None,
                       key_handler_ms=round((returned - sent) * 1000, 2),
                       paint_ms=round((painted[0] - sent) * 1000, 2) if painted else None,
                       applied=stack.index() != index, target_before=prior['selected_text'])
            presses.append(row)
            record('qw_press', **row)

        def undo_all(to_index):
            while page.session.undo_stack.index() > to_index:
                key(Qt.Key_Z, Qt.ControlModifier)
                yield .25
            yield .3

        base = page.session.undo_stack.index()
        gap_ms = int(spec['gap_ms'])
        # A) click empty caption lane in the gap, press Q once
        click(t, lane_point(gap_ms))
        yield .7
        state('A_gap_click')
        capture('qw-A1-gap-click')
        yield from press(Qt.Key_Q, 'A_q')
        capture('qw-A2-after-q')
        a = presses[-1]
        check('A: one Q after a gap click trims the nearest caption',
              a['applied'] and a['after'] and a['after'][0] == int(a['playhead']), a)
        yield from undo_all(base)
        # B) drag/click the playhead on the ruler into the gap, press Q once
        click(t, ruler_point(gap_ms - 40))
        yield .7
        state('B_ruler')
        yield from press(Qt.Key_Q, 'B_q')
        b = presses[-1]
        check('B: one Q after placing the playhead on the ruler trims the nearest caption',
              b['applied'] and b['after'] and b['after'][0] == int(b['playhead']), b)
        # C) direct W at a point inside the same caption (consecutive Q then W)
        inside = (cues_now()[after_id][0] + cues_now()[after_id][1]) // 2
        click(t, ruler_point(inside))
        yield .7
        yield from press(Qt.Key_W, 'C_w_inside')
        c = presses[-1]
        check('C: W inside the caption trims its end to the playhead (consecutive Q/W)',
              c['applied'] and c['after'] and c['after'][1] == int(c['playhead']), c)
        # D) explicit click on the earlier caption is respected
        old = cues_now()[before_id]
        click(t, lane_point((old[0] + old[1]) // 2))
        yield .6
        click(t, ruler_point(old[1] - 150))
        yield .7
        state('D_explicit_then_ruler')
        yield from press(Qt.Key_W, 'D_w')
        d = presses[-1]
        record('D_note', explicit_target_kept=d['after'] != old or d['before'] != old)
        # F) explicit click on a caption, then Q without moving the playhead
        cur = cues_now()[after_id]
        click(t, ruler_point(cur[0] + 300))
        yield .6
        click(t, lane_point(cur[0] + 600))
        yield .6
        state('F_explicit_click')
        yield from press(Qt.Key_Q, 'F_q_explicit')
        f = presses[-1]
        check('F: explicit caption click then Q trims that caption', f['applied'] and f['after'][0] == int(f['playhead']), f)
        # E) undo / redo of the whole sequence
        index_after = page.session.undo_stack.index()
        yield from undo_all(base)
        restored = cues_now()
        check('E: undo restores both captions exactly', restored.get(before_id) == (before_cue.start_ms, before_cue.end_ms, before_cue.text)
              and restored.get(after_id) == (after_cue.start_ms, after_cue.end_ms, after_cue.text),
              dict(before=restored.get(before_id), after=restored.get(after_id)))
        while page.session.undo_stack.index() < index_after:
            key(Qt.Key_Y, Qt.ControlModifier)
            yield .25
        yield .3
        state('E_redo')
        result['qw_presses'] = presses
        result['passed'] = all(x['passed'] for x in result['checks'])

    # ------------------------------------------------------------ E / R frames
    def grab_burst(name, seconds, action):
        """Capture the real window as fast as possible around one action."""
        import ctypes, threading
        from ctypes import wintypes as W
        from PIL import Image
        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        user.GetWindowDC.argtypes = [W.HWND]; user.GetWindowDC.restype = W.HDC
        user.ReleaseDC.argtypes = [W.HWND, W.HDC]
        user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
        gdi.CreateCompatibleDC.argtypes = [W.HDC]; gdi.CreateCompatibleDC.restype = W.HDC
        gdi.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]; gdi.CreateCompatibleBitmap.restype = W.HBITMAP
        gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]; gdi.SelectObject.restype = W.HANDLE
        gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT]
        gdi.DeleteObject.argtypes = [W.HANDLE]; gdi.DeleteDC.argtypes = [W.HDC]
        hwnd = int(window.winId())
        rect = W.RECT(); user.GetWindowRect(W.HWND(hwnd), ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        ratio = window.devicePixelRatioF()
        video = page.video
        origin = video.mapTo(window, QPoint(0, 0))
        crop = (int(origin.x() * ratio), int(origin.y() * ratio),
                int((origin.x() + video.width()) * ratio), int((origin.y() + video.height()) * ratio))
        frames, stop = [], threading.Event()

        class Info(ctypes.Structure):
            _fields_ = [('biSize', ctypes.c_uint32), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                        ('biPlanes', ctypes.c_ushort), ('biBitCount', ctypes.c_ushort), ('biCompression', ctypes.c_uint32),
                        ('biSizeImage', ctypes.c_uint32), ('a', ctypes.c_long), ('b', ctypes.c_long),
                        ('c', ctypes.c_uint32), ('d', ctypes.c_uint32), ('colors', ctypes.c_uint32 * 3)]

        def loop():
            source = user.GetWindowDC(W.HWND(hwnd))
            memory = gdi.CreateCompatibleDC(source)
            bitmap = gdi.CreateCompatibleBitmap(source, width, height)
            previous = gdi.SelectObject(memory, bitmap)
            buffer = ctypes.create_string_buffer(width * height * 4)
            info = Info(); info.biSize = 40; info.biWidth = width; info.biHeight = -height
            info.biPlanes = 1; info.biBitCount = 32
            try:
                while not stop.is_set():
                    started = time.perf_counter()
                    if user.PrintWindow(W.HWND(hwnd), memory, 2) and gdi.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(info), 0) == height:
                        image = Image.frombuffer('RGBA', (width, height), buffer, 'raw', 'BGRA', 0, 1).crop(crop)
                        frames.append((started, time.perf_counter(), image.convert('RGB').reduce(2)))
            finally:
                gdi.SelectObject(memory, previous); gdi.DeleteObject(bitmap); gdi.DeleteDC(memory)
                user.ReleaseDC(W.HWND(hwnd), source)
        worker = threading.Thread(target=loop, daemon=True)
        worker.start()
        yield .25
        marks = {'action': time.perf_counter()}
        action()
        marks['action_returned'] = time.perf_counter()
        yield float(seconds)
        stop.set(); worker.join(3)
        folder = output / ('frames-' + name); folder.mkdir()
        rows = []
        for index, (begin, end, image) in enumerate(frames):
            image.save(folder / f'{index:03d}.png')
            rows.append(dict(index=index, begin_ms=round((begin - marks['action']) * 1000, 1),
                             end_ms=round((end - marks['action']) * 1000, 1)))
        (folder / 'frames.json').write_text(json.dumps(dict(marks=marks, crop=crop, frames=rows), indent=1), 'utf-8')
        record('burst', burst=name, frames=len(rows), action_ms=round((marks['action_returned'] - marks['action']) * 1000, 1))

    def er_steps():
        t = page.timeline
        page.video.set_paused(True); page._sync_play_button(True)
        yield .8
        by_text = {c.text: c for c in page.project.cues}
        target = by_text[spec['cue_text']]
        other = by_text[spec['other_text']]
        t.set_visible_window(max(0, target.start_ms - 4000), 14000)
        yield .5

        def ruler(ms):
            return QPoint(round(t._time_to_x(ms)), max(2, t.RULER_HEIGHT // 2))
        click(t, ruler((target.start_ms + target.end_ms) // 2))
        yield 1.0
        from PySide6.QtWidgets import QWidget as _W

        def native_tree(widget):
            return [dict(cls=type(w).__name__, name=w.objectName(), hwnd=int(w.internalWinId() or 0))
                    for w in [widget, *widget.findChildren(_W)] if w.internalWinId()]
        record('native_windows', card=native_tree(page.subtitle_edit_card),
               video=int(page.video.internalWinId() or 0), host=int(page.video_overlay_host.internalWinId() or 0),
               strip=native_tree(page.review_summary_strip))
        capture('er-00-start')
        yield from grab_burst('E-paused', 1.2, lambda: key(Qt.Key_E))
        capture('er-01-editing')
        key(Qt.Key_Escape)
        yield .8
        yield from grab_burst('R-enter', 1.5, lambda: key(Qt.Key_R))
        capture('er-02-review')
        yield from grab_burst('R-down', 1.5, lambda: key(Qt.Key_Down))
        yield from grab_burst('R-E', 1.2, lambda: key(Qt.Key_E))
        key(Qt.Key_Escape)
        yield .6
        yield from grab_burst('R-exit', 1.2, lambda: key(Qt.Key_Escape))
        # quick consecutive: E, Esc, R, R within ~150 ms
        click(t, ruler((other.start_ms + other.end_ms) // 2))
        yield 1.0

        def rapid():
            key(Qt.Key_E); QApplication.processEvents(); key(Qt.Key_Escape); QApplication.processEvents()
            key(Qt.Key_R); QApplication.processEvents(); key(Qt.Key_R)
        yield from grab_burst('rapid-E-R', 1.5, rapid)
        # while playing
        key(Qt.Key_Space)
        yield 1.0
        yield from grab_burst('E-playing', 1.2, lambda: key(Qt.Key_E))
        key(Qt.Key_Escape)
        yield .5
        result['passed'] = True

    # ------------------------------------------------------------ XML
    def xml_steps():
        from pathlib import Path
        from PySide6.QtCore import QMimeData, QPointF, QUrl
        from PySide6.QtGui import QDropEvent
        from .danmaku_binding import binding_of, describe, effective_path
        from .studio_edit_sequence import sequence_of
        panel = page.highlight_panel
        page._open_clip_assistant()
        yield .5
        record('open_blank', panel_status=panel.status.text(), xml=panel.xml_status.text())
        media = spec['media']
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(media)])
        event = QDropEvent(QPointF(page.width() / 2, page.height() / 2), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        started = time.monotonic()
        page.dropEvent(event)   # the Studio's real drop handler
        yield lambda: str(page.project.media.path or '') and binding_of(page.project).get('status')
        bound = binding_of(page.project)
        record('after_drop', seconds=round(time.monotonic() - started, 2), binding=bound,
               xml=panel.xml_status.text(), panel_project=panel._project is page.project,
               effective=effective_path(page.project), media=page.project.media.path)
        capture_widget(page.context_panel, 'xml-01-after-drop')
        check('drop: same-name XML beside the original FLV is bound automatically',
              bound.get('status') == 'automatic' and Path(bound.get('path', '')).name == Path(spec['xml']).name, bound)
        check('drop: panel shows the match and the comment count', '已自动匹配' in panel.xml_status.text()
              and str(bound.get('count')) .isdigit() and bound.get('count', 0) > 0, panel.xml_status.text())
        check('drop: the clip assistant is bound to this project', panel._project is page.project
              and '尚未打开工程' not in panel.status.text(), panel.status.text())
        # Save, reopen: the binding is kept (or found again) for this source.
        key(Qt.Key_S, Qt.ControlModifier)
        yield 2.5
        window.open_studio_project(spec['project'], mode='edit', source='six_fixes_audit_reopen')
        yield ready
        yield lambda: binding_of(page.project).get('status') == 'automatic' and '已自动匹配' in panel.xml_status.text()
        record('after_reopen', binding=binding_of(page.project), xml=panel.xml_status.text())
        check('reopen: the binding survives saving and reopening', binding_of(page.project).get('path') == bound.get('path'),
              binding_of(page.project))
        # Analysis actually reads that XML.
        panel.config_toggle.setChecked(True)
        yield .3
        panel.mode.setCurrentIndex(max(0, panel.mode.findData('xml')))
        reveal(panel.analyze_button)
        click(panel.analyze_button)
        yield lambda: panel.analyze_button.isEnabled() and not getattr(panel, '_analyzing', False)
        yield 1.0
        info = dict(page.project.studio_state.get('highlight_analysis') or {})
        record('analysis', provenance=info, candidates=len(sequence_of(page.project).clip_candidates),
               source_line=panel.analysis_source.text(), status=panel.status.text())
        capture_widget(page.context_panel, 'xml-02-after-analysis')
        capture('xml-03-window')
        check('analysis used the bound XML', Path(info.get('danmaku_path', '')).name == Path(spec['xml']).name
              and int(info.get('danmaku_count') or 0) == int(bound.get('count') or -1), info)
        check('candidates exist and the settings folded', len(sequence_of(page.project).clip_candidates) > 0
              and panel.active_stage() == 'candidates', panel.active_stage())
        # Manual choice is never replaced by discovery.
        page._import_danmaku_xml(spec['manual_xml'])
        yield lambda: binding_of(page.project).get('origin') == 'manual'
        page._schedule_danmaku_discovery()
        yield 1.0
        check('a manual XML is not overwritten by discovery', binding_of(page.project).get('origin') == 'manual'
              and Path(binding_of(page.project).get('path', '')).name == Path(spec['manual_xml']).name,
              binding_of(page.project))
        record('after_manual', binding=binding_of(page.project), xml=panel.xml_status.text())
        # File dialog path: a new blank project, then the media the dialog returned.
        page.session.undo_stack.setClean()
        page.project_controller.create_blank_project()
        yield ready
        yield .5
        blank_id = page.project.project_id
        page.project_controller._attach_media_to_current(Path(media))
        yield lambda: page.project is not None and page.project.project_id == blank_id             and binding_of(page.project).get('status') == 'automatic'
        record('file_dialog_path', binding=binding_of(page.project), xml=panel.xml_status.text())
        check('file dialog: same-name XML bound for the imported FLV',
              Path(binding_of(page.project).get('path', '')).name == Path(spec['xml']).name
              and '已自动匹配' in panel.xml_status.text(), binding_of(page.project))
        result['passed'] = all(x['passed'] for x in result['checks'])

    phases = dict(generate=generate_steps, qw=qw_steps, er=er_steps, xml=xml_steps)

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'], mode='edit', source='six_fixes_audit')
        yield ready
        yield 1.5
        yield from phases[spec['phase']]()

    iterator = steps()
    state = dict(wait=None, deadline=0., until=0.)
    timer = QTimer(window)
    timer.setInterval(30)

    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop(); save(); log.close()
        page.session.undo_stack.setClean()
        window.close()
        QTimer.singleShot(500, QApplication.instance().quit)

    def tick():
        if state.get('ticking'):
            return
        state['ticking'] = True
        try:
            if state['wait'] is not None:
                if state['wait']():
                    state['wait'] = None
                elif time.monotonic() > state['deadline']:
                    raise TimeoutError('Real GUI condition did not settle')
                else:
                    return
            if time.monotonic() < state['until']:
                return
            value = next(iterator)
            if callable(value):
                state.update(wait=value, deadline=time.monotonic() + 120)
            else:
                state['until'] = time.monotonic() + float(value or 0)
        except StopIteration:
            finish()
        except BaseException:
            result['error'] = traceback.format_exc()
            try:
                capture('failure')
            except Exception:
                pass
            finish()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
