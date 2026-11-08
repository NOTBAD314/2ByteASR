"""Normal MainWindow speech-gap UI and range transaction, with offline rows."""
import copy
import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
    from ..projects.studio_project import load_project, save_project, StudioCue, StudioMedia, SubtitleProject
    from ..recognition.speech_coverage import KEY, pending
    from ..recognition.recognition_input import capture_recognition_snapshot, attach_timeline_result
    result = dict(passed=False, checks={}, pid=os.getpid(), gui_pid=os.getpid(), executable=sys.executable,
                  frozen=bool(getattr(sys, 'frozen', False)), model_calls=0)
    fixture = output/'fixture.2byteproj'
    def check(name, value):
        result['checks'][name] = bool(value)
        if not value:
            raise AssertionError(name)
    def write():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    def shutdown():
        result['gui_shutdown'] = True
        write()
    QApplication.instance().aboutToQuit.connect(shutdown)
    def flow():
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            page = getattr(window, '_studio_page_instance', None)
            if page is not None and page.project is not None and page.project.media.path.endswith('fixture.mp4'):
                break
            yield .1
        else:
            raise RuntimeError('Fixture project did not open through MainWindow')
        yield 1
        page._sync_recognition_zero_state()
        yield .2
        button = page.findChild(QPushButton, 'speechRecoveryButton')
        check('persistent_gap_button', button is not None and button.isVisible())
        window.grab().save(str(output/'01-partial-project.png'))
        button.click()
        yield .2
        dialog = page._speech_recovery_dialog
        check('gap_dialog_visible', dialog.isVisible())
        dialog.grab().save(str(output/'02-gap-dialog.png'))
        positions = []
        seek = page._seek
        def track_seek(seconds):
            positions.append(seconds)
            seek(seconds)
        page._seek = track_seek
        dialog.findChild(QPushButton, 'speechGapJump').click()
        yield .2
        check('gap_seek_uses_project_clock', positions == [10.0])
        page._seek = seek
        dialog.findChild(QPushButton, 'speechGapRetry').click()
        yield .4
        sheet = getattr(page, '_recognition_sheet', None)
        check('normal_range_sheet_visible', sheet is not None and sheet.isVisible())
        sheet.grab().save(str(output/'03-range-recognition-sheet.png'))
        sheet.close()
        yield .2
        original = copy.deepcopy(page.project.to_dict())
        snapshot = capture_recognition_snapshot(page.project, str(fixture), range_ms=(10000, 20000))
        recognized = SubtitleProject(media=StudioMedia(path=page.project.media.path, duration_ms=10000),
            cues=[StudioCue('recovered', 0, 3000, '离线恢复回执', 'NEW')],
            generation_metadata=dict(job_id='speech-gap-offline'))
        attached = attach_timeline_result(recognized, snapshot)
        target = save_project(attached, output/'partial-result.2byteproj')
        check('range_result_applied', page.apply_range_recognition_result(str(target), snapshot))
        gap, = pending(page.project.generation_metadata[KEY])
        check('partial_range_stays_pending', gap['status'] == 'partial' and gap['remaining_ranges'][0][0] > 13)
        check('outside_captions_unchanged', all(any(c.id == old['id'] and c.text == old['text']
            and c.start_ms == old['start_ms'] and c.end_ms == old['end_ms'] for c in page.project.cues)
            for old in original['cues']))
        after = copy.deepcopy(page.project.generation_metadata[KEY])
        page.undo_stack.undo()
        check('undo_restores_gap_ledger', page.project.generation_metadata[KEY] == original['generation_metadata'][KEY])
        page.undo_stack.redo()
        check('redo_restores_gap_ledger', page.project.generation_metadata[KEY] == after)
        saved = save_project(page.project, output/'saved.2byteproj')
        check('storage_reopen_retains_partial', load_project(saved).generation_metadata[KEY] == after)
        page._sync_recognition_zero_state()
        yield .2
        window.grab().save(str(output/'04-partial-recovery.png'))
        from ..diagnostics.build_identity import load_build_identity
        result['build'] = load_build_identity().to_dict()
        result['passed'] = True
        # Keep the audit profile and its project isolated from the real library.
        page.undo_stack.setClean()
        window.close()
    steps = flow()
    timer = QTimer(window)
    timer.setInterval(30)
    state = dict(until=0.0, busy=False)
    def tick():
        if state['busy'] or time.monotonic() < state['until']:
            return
        state['busy'] = True
        try:
            state['until'] = time.monotonic()+next(steps)
        except StopIteration:
            timer.stop()
            write()
            QApplication.instance().quit()
        except BaseException:
            result['error'] = traceback.format_exc()
            timer.stop()
            write()
            QApplication.instance().quit()
        finally:
            state['busy'] = False
    timer.timeout.connect(tick)
    timer.start()
