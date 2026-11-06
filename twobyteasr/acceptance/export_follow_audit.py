"""Real-window checks for three user reports (2026-10-27).

User (10-27): dropdown lists showed black corners; with 跟随播放头 on the
timeline did not follow playback; after an export the tray said 压制完成 but
the app stayed stuck on the progress page.

Opens the copied sample project in Studio and, driven by the real event loop
(steps are QTimer callbacks, nothing waits inside processEvents while a
measurement runs):

1. follow: zooms the timeline to a 4-second window, plays 6 s and records
   where the view starts — as opened, then with a number field focused, then
   after a click on the timeline ruler;
2. dropdowns: opens a Studio dropdown and reads its native window style
   (a see-through list must be a layered window, or its corners are black);
3. export: exports the whole sample to the isolated folder, then for 8 s
   records the longest event-loop gap (20 ms heartbeat), when the result page
   first painted, and every mpv command slower than 100 ms.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=export-follow`` (isolated data,
``scripts/verify_export_follow_headed.py``; source or frozen). Offline; no AI.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def _layered(widget) -> bool | None:
    if sys.platform != 'win32':
        return None
    import ctypes
    user32 = ctypes.WinDLL('user32')
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return bool(user32.GetWindowLongPtrW(int(widget.winId()), -20) & 0x80000)   # WS_EX_LAYERED


def start(window, output: Path):
    from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], metrics={}, errors=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(sys.executable))

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    page = window.studio_page
    timeline = page.timeline
    options = set(filter(None, os.environ.get('TWOBYTEASR_EXPORT_FOLLOW_OPTIONS', '').split(',')))
    result['options'] = sorted(options)

    def follow_run(label, prepare=None):
        """Play 6 s from 0 in a 4 s window; the view should move with the playhead."""
        if not page.video._paused:
            page._toggle_playback()
        page._seek(0.0)
        yield 'seek', lambda: not page.video._playback_clock.exact_seek_pending, 10
        yield 400
        timeline.set_visible_window(0, 4000)
        if prepare is not None:
            prepare()
        yield 300
        state = dict(toggle=page.follow_playhead_toggle.isChecked(),
                     editing=page._editing_has_focus(),
                     focus=type(QApplication.focusWidget()).__name__ if QApplication.focusWidget() else None,
                     suspended=max(0.0, getattr(timeline, '_follow_suspended_until', 0) - time.perf_counter()),
                     start=timeline.visible_start_ms, window=timeline.visible_duration_ms)
        samples = []
        sampler = QTimer()
        sampler.setInterval(100)
        sampler.timeout.connect(lambda: samples.append((timeline.playhead_ms, timeline.visible_start_ms)))
        page._toggle_playback()
        sampler.start()
        yield 6000
        sampler.stop()
        if not page.video._paused:
            page._toggle_playback()
        grab(page, f'follow-{label}')
        playheads = [p for p, _s in samples]
        starts = [s for _p, s in samples]
        late = [(p, s) for p, s in samples if p > 4500]
        outside = [(p, s) for p, s in late if not (s <= p <= s + state['window'])]
        state.update(played_to=max(playheads, default=0), view_moved_to=max(starts, default=0),
                     outside=len(outside), samples=len(samples))
        result['metrics'][f'follow_{label}'] = state
        check(f'follow {label}: the view moves with the playhead',
              state['played_to'] > 4500 and state['view_moved_to'] > 0 and not outside, state)

    def steps():
        project = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
        window.showNormal()
        window.resize(1600, 900)
        window.open_studio_project(str(project), mode='edit', source='export_follow_audit')
        yield 'project', lambda: page.project is not None and page._readiness.ready, 90
        yield 1500
        if not page.video._paused:   # opening a project starts playback
            page._toggle_playback()
        page._set_volume(0)
        yield 500

        # 1. Follow playhead.
        if 'skip-follow' not in options:
            yield from follow_run('as_opened')
            spin = next((s for s in page.findChildren(QAbstractSpinBox) if s.isVisible() and s.isEnabled()), None)
            if spin is not None:
                yield from follow_run('number_field_focused', lambda: spin.setFocus(Qt.FocusReason.MouseFocusReason))
            else:
                result['metrics']['follow_number_field_focused'] = 'no visible number field'

            def click_ruler():
                QTest.mouseClick(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 QPoint(timeline.TRACK_HEADER_WIDTH + 40, max(4, timeline.RULER_HEIGHT // 2)))
            yield from follow_run('after_ruler_click', click_ruler)

        # 2. Export, with a dropdown check on the export page first. The
        # encoder scan runs once in the background at startup; 自动 needs it.
        yield 'preview', lambda: page._preview_path is not None, 60
        from ..exports.studio_render import cached_encoder_choices
        from ..system.platform_media import ffmpeg_tool
        yield 'encoder scan', lambda: cached_encoder_choices(ffmpeg_tool(), 'h264') is not None, 120
        page._open_render_dialog()
        yield 'export page', lambda: page.export_workspace is not None and page.export_workspace.isVisible(), 30
        workspace = page.export_workspace
        yield 1200
        combo = next((c for c in (workspace.codec, workspace.resolution, workspace.fps)
                      if isinstance(c, QComboBox) and c.isVisible()), None)
        if combo is not None:
            combo.showPopup()
            yield 400
            container = combo.view().window()
            facts = dict(visible=container.isVisible(), layered=_layered(container),
                         frameless=bool(container.windowFlags() & Qt.WindowType.FramelessWindowHint),
                         translucent=container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
            result['metrics']['dropdown'] = facts
            check('dropdown: the rounded list is a layered see-through window',
                  facts['visible'] and facts['translucent'] and facts['layered'] is not False, facts)
            combo.hidePopup()
            yield 300
        exports = output / 'exports'
        exports.mkdir(exist_ok=True)
        forced = next((o.split('=', 1)[1] for o in options if o.startswith('encoder=')), '')
        if forced:
            workspace.encoder.setCurrentIndex(workspace.encoder.findData(forced))
        segments=next((int(o.split('=',1)[1]) for o in options if o.startswith('segments=')),None)
        if segments is not None:
            workspace.parallel_segments.setCurrentIndex(workspace.parallel_segments.findData(segments))
            check('acceleration is selected in the normal GUI',workspace.parallel_segments.currentData()==segments)
        result['metrics']['encoder_choice'] = dict(selected=workspace.encoder.currentData(),
                                                   resolved=workspace._resolved_encoder(),
                                                   hint=workspace.actual_encoder_hint.text())
        workspace.directory.setText(str(exports))
        workspace.filename.setText('export-follow')
        yield 300
        grab(window,'export-settings-window')
        grab(workspace.settings_scroll.widget(),'export-settings-full-column')

        timing = dict(show_success=None, success_done=None, success_paint=None, notified=None)
        gaps, slow_mpv = [], []
        last = [time.perf_counter()]

        def beat():
            now = time.perf_counter()
            gaps.append((now, now - last[0]))
            last[0] = now
        heartbeat = QTimer()
        heartbeat.setInterval(20)
        heartbeat.timeout.connect(beat)

        class PaintWatch(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Paint and timing['success_paint'] is None and timing['show_success']:
                    timing['success_paint'] = time.perf_counter()
                return False
        watch = PaintWatch(workspace)
        workspace.success_page.installEventFilter(watch)
        original_show = workspace._show_success

        def show_success(path):
            timing['show_success'] = time.perf_counter()
            try:
                return original_show(path)
            finally:
                timing['success_done'] = time.perf_counter()
        workspace.render_succeeded.disconnect(workspace._show_success)
        workspace._show_success = show_success
        workspace.render_succeeded.connect(show_success)
        from ..exports import export_notification
        original_notify = export_notification.notify_export_completed

        def notify(parent, path):
            timing['notified'] = time.perf_counter()
            if 'quiet' in options:
                import winsound
                winsound.MessageBeep = lambda *a, **k: None
            began = time.perf_counter()
            try:
                return original_notify(parent, path)
            finally:
                timing['notify_ms'] = round(1000 * (time.perf_counter() - began), 1)
        export_notification.notify_export_completed = notify
        controller = page.video.controller
        original_send = controller._send if controller is not None else None
        if original_send is not None:
            def send(command, *args, **kwargs):
                began = time.perf_counter()
                try:
                    return original_send(command, *args, **kwargs)
                finally:
                    spent = time.perf_counter() - began
                    if spent > 0.1:
                        slow_mpv.append(dict(at=began, seconds=round(spent, 3), command=list(command)[:2]))
            controller._send = send
        window_paints = []

        class WindowPaintWatch(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Paint:
                    window_paints.append(time.perf_counter())
                return False
        window_watch = WindowPaintWatch(workspace)
        workspace.pages.installEventFilter(window_watch)
        heartbeat.start()
        clicked = time.perf_counter()
        QTest.mouseClick(workspace.export_button, Qt.MouseButton.LeftButton)
        yield 'export started', lambda: workspace._last_job is not None and workspace._running, 30
        if 'details' in options and not workspace.running_details_button.isChecked():
            workspace.running_details_button.click()
        if 'minimize' in options:
            yield 1500
            window.showMinimized()
        yield 'export finished', lambda: not workspace._running, 1800
        finished = time.perf_counter()
        restored = None
        if 'minimize' in options:
            yield 2000
            window.showNormal()
            restored = time.perf_counter()
        yield 8000
        heartbeat.stop()
        during = sorted(((round(gap * 1000, 1), round(at - (timing['show_success'] or finished), 2))
                         for at, gap in gaps if at < (timing['show_success'] or finished)), reverse=True)[:6]
        result['metrics']['export_timeline'] = dict(
            export_seconds=round(finished - clicked, 1), longest_gaps_before_success=during,
            pages_paints_after_success=len([t for t in window_paints if t >= (timing['show_success'] or finished)]),
            first_paint_after_restore_ms=round(1000 * (min((t for t in window_paints if t >= restored), default=0) - restored), 1)
            if restored else None)
        export_notification.notify_export_completed = original_notify
        if original_send is not None:
            controller._send = original_send
        grab(window, 'export-finished-window')
        after = [gap for at, gap in gaps if at >= (timing['show_success'] or finished)]
        export = dict(
            page=type(workspace.pages.currentWidget()).__name__,
            on_success_page=workspace.pages.currentWidget() is workspace.success_page,
            output=Path(workspace._last_job.output_path).is_file(),
            show_success_ms=round(1000 * ((timing['success_done'] or 0) - (timing['show_success'] or 0)), 1),
            paint_after_success_ms=round(1000 * (timing['success_paint'] - timing['show_success']), 1)
            if timing['success_paint'] and timing['show_success'] else None,
            notified=timing['notified'] is not None, notify_ms=timing.get('notify_ms'),
            max_gap_after_success_ms=round(1000 * max(after, default=0), 1),
            beats_after_success=len(after),
            slow_mpv=[dict(item, at=round(item['at'] - (timing['show_success'] or finished), 3)) for item in slow_mpv],
            failure=workspace._last_failure or None,
            job_encoder=workspace._last_job.settings.encoder, job_quality=workspace._last_job.settings.quality,
            job_mode=workspace._last_job.settings.quality_mode,
            output_mb=round(Path(workspace._last_job.output_path).stat().st_size / 1e6, 1)
            if Path(workspace._last_job.output_path).is_file() else None,
            receipt=dict(workspace._last_job.completion_metadata or {}),
            parallel_decision=dict(workspace._last_job.export_context.get('parallel_decision') or {}))
        result['metrics']['export'] = export
        check('export: finished on the result page', export['on_success_page'] and export['output'], export)
        check('export: result page painted within 1 s', export['paint_after_success_ms'] is not None
              and export['paint_after_success_ms'] < 1000, export)
        check('export: the app keeps responding after the finish (no gap over 500 ms)',
              export['max_gap_after_success_ms'] < 500, export)
        import psutil,gc
        owner=psutil.Process()
        def memory_after():
            gc.collect()
            children=[]
            for child in owner.children(recursive=True):
                try:
                    if child.name().lower() in {'node.exe','chrome.exe','chrome-headless-shell.exe','ffmpeg.exe'}:
                        children.append(dict(pid=child.pid,name=child.name(),rss=child.memory_info().rss,command=child.cmdline()))
                except psutil.Error:pass
            export_folder=str(Path(workspace._last_job.output_path).parent).lower()
            export_children=[child for child in children if export_folder in '\n'.join(child['command']).lower()]
            return dict(rss=owner.memory_info().rss,export_children=export_children,
                background_children=[child for child in children if child not in export_children])
        result['repetitions']=[dict(iteration=1,receipt=export['receipt'],memory_after=memory_after())]
        repetitions=next((int(o.split('=',1)[1]) for o in options if o.startswith('repeat=')),1)
        for iteration in range(2,max(1,min(6,repetitions))+1):
            QTest.mouseClick(workspace.success_page.again,Qt.MouseButton.LeftButton)
            yield 400
            edit=None
            if 'edit-repeat' in options and iteration in (3,4):
                wanted='g' if iteration==3 else 'animated'
                target=next(c for c in page.project.cues if c.style_id==wanted)
                before=target.text;after=before+'改'
                accepted=page.cue_controller.set_text(target.id,after)
                check(f'repeat {iteration}: one cue edit uses the normal undoable controller',
                    accepted and target.text==after,dict(cue_id=target.id,kind='static' if iteration==3 else 'moving'))
                edit=dict(cue_id=target.id,before=before,after=after,kind='static' if iteration==3 else 'moving')
                yield 500
            workspace.filename.setText(f'export-follow-{iteration}')
            QTest.mouseClick(workspace.export_button,Qt.MouseButton.LeftButton)
            yield 'repeat export started',lambda:workspace._running,30
            yield 'repeat export finished',lambda:not workspace._running,1800
            yield 800
            check(f'repeat {iteration}: validated output and result page',
                workspace.pages.currentWidget() is workspace.success_page and Path(workspace._last_job.output_path).is_file())
            result['repetitions'].append(dict(iteration=iteration,receipt=dict(workspace._last_job.completion_metadata),
                memory_after=memory_after(),edit=edit))
            if edit:
                assets=workspace._last_job.completion_metadata.get('caption_assets') or {}
                if iteration==3:
                    check('one static cue edit retains the moving asset',assets.get('dynamic_rendered')==0,assets)
                check(f'repeat {iteration}: unaffected static assets are reused',
                    assets.get('static',{}).get('hits',0)>=assets.get('static',{}).get('total',0)-2,assets)
            grab(window,f'export-repeat-{iteration}-finished')
        page._close_export_workspace()
        yield 800
        page.save()
        yield 500

    run = steps()

    def advance():
        try:
            step = next(run)
        except StopIteration:
            finish()
            return
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
            finish()
            return
        if isinstance(step, int):
            QTimer.singleShot(step, advance)
            return
        label, predicate, seconds = step
        deadline = time.monotonic() + seconds

        def poll():
            try:
                ready = predicate()
            except Exception:  # noqa: BLE001
                ready = False
            if ready:
                advance()
            elif time.monotonic() > deadline:
                result['errors'].append(f'timed out waiting for {label}')
                finish()
            else:
                QTimer.singleShot(50, poll)
        poll()

    def finish():
        result['passed'] = not result['errors'] and all(c['passed'] for c in result['checks'])
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def stopped():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
    app.aboutToQuit.connect(stopped)
    QTimer.singleShot(2500, advance)
