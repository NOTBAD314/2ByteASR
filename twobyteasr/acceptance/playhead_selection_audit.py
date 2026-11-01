"""Pixel and clock evidence for interrupted scrubs and explicit deselection."""
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
    from PySide6.QtGui import QImage, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from twobyteasr.acceptance.blank_project_audit import _capture
    app = QApplication.instance()
    page = window.built_page('studio')
    loading = getattr(window, '_studio_loading_session', None)
    if (page is None or page.project is None or getattr(page, '_project_load_in_progress', False)
            or getattr(getattr(page, '_readiness', None), 'active', False)
            or loading is not None and (loading.active or not loading.deliveries)):
        QTimer.singleShot(250, lambda: start(window, output))
        return
    result = dict(passed=False, checks=[], failures=[], samples=[], gui_shutdown=False,
        dpr=window.devicePixelRatioF(), pixel_source='mpv composed PNG and Windows PrintWindow on private desktop; Qt-injected input')
    def write():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    def check(name, passed, detail=None):
        result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
        if not passed:
            result['failures'].append(name)
        write()
    def wait(predicate, seconds=15):
        end = time.monotonic() + seconds
        while not predicate() and time.monotonic() < end:
            QTest.qWait(25)
        if not predicate():
            raise RuntimeError('Timed out waiting for media or GUI')
    def capture(name):
        page.video.controller.screenshot_to_file(output/(name+'-mpv.png'), mode='window')
        wait(lambda: (output/(name+'-mpv.png')).exists())
        _capture(window, output/(name+'-window.png'))
        page.timeline.grab().save(str(output/(name+'-timeline.png')))
        return QImage(str(output/(name+'-mpv.png')))
    def pink_pixels(image):
        count = 0
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                if c.red() > 100 and c.red() > c.green()+25 and c.blue() > c.green()+15:
                    count += 1
        return count
    def sample(label):
        clock = page.video.playback_position_snapshot()
        value = dict(label=label, clock_ms=clock.presentation_media_ms, timeline_ms=page.timeline.playhead_ms,
            timecode=page.timecode_input.text(), scrub=page.timeline._scrub_drag,
            router_active=page._timeline_scrub.active, router_pending=page._timeline_scrub.pending,
            paused=page.video._paused)
        result['samples'].append(value)
        return value
    def begin_drag(playing):
        page.video.set_paused(True)
        page._seek(2)
        wait(lambda: not page.video.playback_position_snapshot().exact_seek_pending)
        page.video.set_paused(not playing)
        QTest.qWait(200)
        timeline = page.timeline
        timeline.set_visible_window(0, 24000)
        first = QPoint(round(timeline._time_to_x(3000)), 12)
        last = QPoint(round(timeline._time_to_x(6000)), 12)
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, first)
        global_point = timeline.mapToGlobal(last)
        QApplication.sendEvent(timeline, QMouseEvent(QEvent.MouseMove, QPointF(last), QPointF(global_point),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.qWait(50)
        return last
    def perform():
        try:
            wait(lambda: page.video.controller is not None and page.video.controller.running)
            wait(lambda: page.video._startup_state == 'READY')
            check('normal entry has live mpv and project', page.video.controller.running and page.project is not None)
            for playing in (False, True):
                for ending in ('release', 'deactivate', 'ungrab', 'escape', 'focus_peer'):
                    name = str(playing)+'-'+ending
                    last = begin_drag(playing)
                    check(name+' begins a drag', page.timeline._scrub_drag and page._timeline_scrub.active)
                    peer = None
                    if ending == 'release':
                        QTest.mouseRelease(page.timeline, Qt.LeftButton, Qt.NoModifier, last)
                    elif ending == 'escape':
                        QTest.keyClick(page.timeline, Qt.Key_Escape)
                    elif ending == 'focus_peer':
                        window.activateWindow(); QTest.qWait(50)
                        peer = QWidget(); peer.setWindowTitle('Owned focus probe'); peer.resize(250, 90)
                        peer.show(); peer.activateWindow(); QTest.qWait(150)
                        check(name+' peer receives native focus', peer.isActiveWindow())
                    else:
                        QApplication.sendEvent(page.timeline, QEvent(QEvent.WindowDeactivate if ending == 'deactivate' else QEvent.UngrabMouse))
                    QTest.qWait(250)
                    value = sample(name)
                    check(name+' releases gesture and scheduler', not value['scrub'] and not value['router_active']
                        and not page._timeline_scrub.timer.isActive() and value['router_pending'] is None, value)
                    check(name+' preserves pause intent', page.video._paused == (not playing), value)
                    # Exercise playback even if the old release-loss bug kept
                    # it paused, to separate moving video from a pinned cursor.
                    page.video.set_paused(False)
                    QTest.qWait(200)
                    before = sample(name+'-playing-before')
                    before_image = capture(name+'-before')
                    QTest.qWait(450)
                    after = sample(name+'-playing-after')
                    after_image = capture(name+'-after')
                    check(name+' actual video frames change', before_image != after_image)
                    check(name+' cursor and timecode follow clock', after['timeline_ms'] > before['timeline_ms']+150
                        and abs(after['clock_ms']-after['timeline_ms']) < 180 and before['timecode'] != after['timecode'],
                        dict(before=before, after=after))
                    QTest.mouseRelease(page.timeline, Qt.LeftButton, Qt.NoModifier, last)
                    if peer is not None:
                        peer.close(); window.activateWindow(); QTest.qWait(50)
            page.video.set_paused(True); page._seek(4)
            wait(lambda: not page.video.playback_position_snapshot().exact_seek_pending)
            page.select_cue('a')
            page.position_edit_button.setChecked(True)
            page.ensure_active_subtitle_renderer(reason='deselect_audit')
            wait(lambda: page.position_overlay.isVisible())
            QTest.qWait(350)
            selected = capture('selected')
            selected_pixels = pink_pixels(selected)
            check('selected native video contains transform handles', selected_pixels > 20, selected_pixels)
            original = page.project.to_dict()
            page.timeline.setFocus()
            QTest.keyClick(page.timeline, Qt.Key_Escape)
            # Capture before another playback tick can reconcile the renderer.
            check('Escape immediately clears selected cue and Qt overlay', not page.selected_cue_id and not page.position_overlay.isVisible())
            QTest.qWait(250)
            deselected = capture('deselected')
            pixels = pink_pixels(deselected)
            check('deselected native video removes transform handles', pixels == 0, pixels)
            check('cancel does not change subtitle or dirty state', page.project.to_dict() == original)
            page.cue_controller.sync_playhead_target(page.timeline.playhead_ms)
            check('same clock target cannot undo cancellation', not page.selected_cue_id)
            last = begin_drag(True)
            page.workspace_host.hide(); QTest.qWait(100)
            check('hidden workspace discards gesture without resuming', not page.timeline._scrub_drag
                and not page._timeline_scrub.active and page.video._paused)
            page.workspace_host.show()
            result['passed'] = not result['failures']
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            write()
            page.video.set_paused(True)
            page.undo_stack.setClean()
            window.result_exit_code = 0 if result['passed'] else 1
            window.close()
    def closed():
        result['gui_shutdown'] = True
        write()
    app.aboutToQuit.connect(closed)
    QTimer.singleShot(500, perform)
