"""Opt-in headed acceptance on an isolated copy of the user's cut project."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, out):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .build_identity import load_build_identity
    from .studio_edit_sequence import source_cue_id_of, timeline_duration_ms
    from .studio_runtime_state import state_for
    out = Path(out)
    page = window.studio_page
    config = json.loads((out/'config.json').read_text('utf8'))
    report = dict(passed=False, checks={}, identity=load_build_identity().to_dict(),
                  pid=os.getpid(), executable=sys.executable, provider_calls=0)

    def pump(seconds=.1):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            QApplication.processEvents(); time.sleep(.003)

    def wait(predicate, seconds=90):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate(): return
            pump(.03)
        raise TimeoutError('Project36 GUI predicate timed out')

    def check(label, value):
        report['checks'][label] = bool(value)
        (out/'progress.json').write_text(json.dumps(report, ensure_ascii=False, default=str), 'utf8')
        if not value: raise AssertionError(label)

    def key(code, modifier=Qt.NoModifier):
        QTest.keyClick(window.windowHandle(), code, modifier); pump(.12)

    def activate():
        QApplication.setActiveWindow(window); window.activateWindow()
        page.timeline.setFocus(); pump(.1)

    def click(widget):
        QTest.mouseClick(window.windowHandle(), Qt.LeftButton, Qt.NoModifier,
                        widget.mapTo(window, widget.rect().center())); pump(.15)

    def shot(label):
        window.grab().save(str(out/(label+'.png')))
        if page.video.controller:
            page.video.controller.screenshot_to_file(out/(label+'-native.png'), mode='window')

    def seek(point):
        page._seek(point/1000)
        wait(lambda: not page.video._playback_clock.exact_seek_pending)
        pump(.3)
        check('seek '+str(point), abs(page.timeline.playhead_ms-point)<100)

    def edit(point, expected):
        seek(point); activate(); key(Qt.Key_E)
        wait(lambda: page._canvas_editor is not None)
        lock = page._review_edit_lock['cue_id']
        check('E target '+str(point), source_cue_id_of(lock)==expected)
        cue = next(c for c in page.project.cues if c.id==expected)
        check('E text '+str(point), page.subtitle_edit_input.toPlainText()==cue.text)
        check('E pauses '+str(point), page.video._paused)
        shot('edit-'+str(point)); key(Qt.Key_Escape)

    def run():
        try:
            wait(lambda: page.project is not None and page._readiness.ready)
            page.video.set_paused(True); page._set_volume(0)
            check('179 original subtitles loaded', len(page.project.cues)==179)
            check('deep source mapped playback', page._playback_mode=='mapped')
            before = {c.id:c.text for c in page.project.cues}
            edit(439400, '130')
            # A real clock tick while playing crosses 438436, then E pauses it.
            seek(438200); page.video.set_paused(False)
            wait(lambda: page.timeline.playhead_ms>=439000, 15)
            activate(); key(Qt.Key_E); wait(lambda: page._canvas_editor is not None)
            check('playing E crosses cue boundary', source_cue_id_of(page._review_edit_lock['cue_id'])=='130')
            check('playing E pauses', page.video._paused)
            key(Qt.Key_Escape)
            # Second retained clip carries a different source/timeline offset.
            point = 610800
            targets = state_for(page.project).cues_at(point)
            expected = source_cue_id_of(targets[0].id) if targets else source_cue_id_of(
                next(state_for(page.project).cues_before(point)).id)
            edit(point, expected)
            seek(439400); activate(); key(Qt.Key_E)
            page.subtitle_edit_input.selectAll()
            event=QInputMethodEvent(); event.setCommitString('工程36编辑验证')
            QApplication.sendEvent(page.subtitle_edit_input, event)
            seek(441800)
            check('open edit holds original cue', source_cue_id_of(page._review_edit_lock['cue_id'])=='130')
            page.subtitle_edit_input.setFocus(); key(Qt.Key_Return)
            check('commit updates only intended subtitle',
                  {c.id:c.text for c in page.project.cues}==dict(before, **{'130':'工程36编辑验证'}))
            activate(); key(Qt.Key_Z, Qt.ControlModifier)
            check('undo restores all original subtitle text', {c.id:c.text for c in page.project.cues}==before)
            if config.get('full_export'):
                click(page.studio_render_button); wait(lambda: page.export_workspace is not None)
                ui = page.export_workspace
                ui.directory.setText(str(out/'exports')); ui.filename.setText('工程36修复验收')
                ui.filename_prefix.setCurrentText(''); ui.filename_suffix.setCurrentText('')
                ui.resolution.setCurrentIndex(ui.resolution.findData((-1,-1)))
                ui.custom_resolution_width.setValue(640); ui.custom_resolution_height.setValue(360)
                ui.fps.setCurrentIndex(ui.fps.findData(30.0))
                ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
                ui.encoder_preset.setCurrentIndex(ui.encoder_preset.findData('fastest'))
                ui.export_range.setCurrentIndex(ui.export_range.findData('all'))
                expected_path = ui.export_target().full_path
                report['export_path']=str(expected_path)
                shot('export-settings'); click(ui.export_button)
                wait(lambda: not ui._running and (ui.pages.currentWidget() is ui.success_page or ui._last_failure),1200)
                report['export_error']=ui._last_failure
                check('full 179 subtitle export success', not ui._last_failure and expected_path.is_file())
                import av
                with av.open(str(expected_path)) as media:
                    check('AAC audio exists', bool(media.streams.audio))
                    frames=sum(1 for _ in media.decode(video=0))
                check('full film decoded frames', abs(frames-timeline_duration_ms(page.project)*30/1000)<=1)
                report['decoded_frames']=frames
                shot('export-success')
            report['passed']=True
        except BaseException:
            report['error']=traceback.format_exc(); shot('failure')
        finally:
            report['finished']=time.time()
            (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),'utf8')
            page.video.set_paused(True); page.undo_stack.setClean(); window.close()
    QTimer.singleShot(1800, run)
