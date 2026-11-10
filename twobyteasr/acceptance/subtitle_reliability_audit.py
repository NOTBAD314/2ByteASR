"""Normal Windows workbench audit of subtitle export and roster repair."""
import copy
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt, QCoreApplication, QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import psutil
    from ..exports.studio_export_ui import SubtitleExportDialog
    from ..projects.studio_project import save_project, load_project, StudioSpeaker
    from ..projects.range_speakers import register_range_speakers
    from ..studio.studio_speaker_manager import SpeakerManagerDialog
    from ..diagnostics.build_identity import launch_identity_payload

    app = QApplication.instance()
    output = Path(output)
    result = dict(passed=False, checks={}, exports=[], build=launch_identity_payload(),
                  scope='normal MainWindow, synthetic 4485/8468 captions, synthetic 16s media')
    process = psutil.Process()

    def receipt():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    def check(name, value):
        result['checks'][name] = bool(value)
        receipt()
        if not value:
            raise AssertionError(name)

    def wait(predicate, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            app.processEvents()
            time.sleep(.003)
        raise TimeoutError('subtitle audit wait')

    def dialog_for(page, folder, stem='captions'):
        dialog = SubtitleExportDialog(page.project, page.project_path, page,
                                      export_on_accept=True, base_name=stem)
        dialog.custom_directory.setText(str(folder))
        dialog.destination_choice.set_value('custom')
        dialog.speaker_modes['combined'].setChecked(True)
        for name, control in dialog.format_checks.items():
            control.setChecked(name == 'srt')
        for name, control in dialog.language_checks.items():
            control.setChecked(name == 'bilingual')
        dialog.show()
        return dialog

    def run():
        page = window.studio_page
        try:
            window._switch_page(page)
            cycles = int(os.environ.get("SUBTITLE_AUDIT_CYCLES", "20"))
            for count in (4485, 8468):
                fixture = output / f'fixture-{count}.2byteproj'
                folder = output / str(count)
                folder.mkdir(exist_ok=True)
                for cycle in range(cycles):
                    if cycle in (0, 10):
                        page.project_controller.open_project_entry(str(fixture), single_shot_fn=QTimer.singleShot,
                                                                  skip_dirty_guard=True)
                        wait(lambda: page.project is not None and len(page.project.cues) == count and page._readiness.ready)
                        wait(lambda: not page._readiness.overlay.isVisible())
                        page.video.set_paused(True)
                        wait(lambda: not getattr(page, '_qc_full_scan_pending', False))
                    if count == 4485 and cycle == 0:
                        from ..studio.studio_punctuation import apply_style
                        manuscript = page.project.cues[0].text
                        for mode in ('add', 'original', 'none', 'original'):
                            apply_style(page, mode)
                            wait(lambda: page._prepared_caption('cue-0') is not None
                                 and ('?' in page._prepared_caption('cue-0').snapshot.text) == (mode == 'add'))
                            row = page.cue_model.row_for_cue_id('cue-0')
                            shown = page.cue_model.data(page.cue_model.index(row, 3))
                            check('normal list policy ' + mode, ('?' in shown) == (mode == 'add'))
                        check('punctuation toggles preserve authored text', page.project.cues[0].text == manuscript)
                        wait(lambda: not getattr(page, '_qc_full_scan_pending', False))
                        page._seek(.3)
                        wait(lambda: page._prepared_caption('cue-0') is not None)
                        prepared = page._prepared_caption('cue-0')
                        check('prepared preview removes sentence question marks', '?' not in prepared.snapshot.text
                              and '！' not in prepared.snapshot.text)
                        frame = output / 'native-preview.png'
                        page.video.controller.screenshot_to_file(str(frame), mode='window', fast=True)
                        wait(frame.is_file, 15)
                        page.grab().save(str(output / 'workspace.png'))
                    dialog = dialog_for(page, folder)
                    intervals, samples = [], []
                    previous = [time.perf_counter()]
                    def heartbeat():
                        now = time.perf_counter()
                        intervals.append(now - previous[0])
                        previous[0] = now
                        samples.append(process.memory_info().rss)
                    timer = QTimer()
                    timer.setInterval(10)
                    timer.timeout.connect(heartbeat)
                    timer.start()
                    began = time.perf_counter()
                    QTest.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
                    returned = time.perf_counter() - began
                    task = dialog._subtitle_task
                    check(f'{count}/{cycle} worker started', task is not None)
                    dialog._run_export()
                    check(f'{count}/{cycle} repeated click same task', dialog._subtitle_task is task)
                    wait(lambda: dialog._subtitle_task is None)
                    heartbeat()
                    timer.stop()
                    check(f'{count}/{cycle} verified one bilingual file', len(dialog.artifacts) == 1
                          and dialog.artifacts[0].cue_count == count)
                    check(f'{count}/{cycle} released snapshot and stage', task.snapshot is None
                          and not list(folder.glob('.subtitle-*')))
                    result['exports'].append(dict(count=count, cycle=cycle,
                        seconds=time.perf_counter() - began, main_return_ms=returned * 1000,
                        max_heartbeat_ms=max(intervals) * 1000, rss=process.memory_info().rss,
                        peak_sampled_rss=max(samples), handles=process.num_handles(),
                        worker_peak_bytes=task.work.peak_bytes, worker_exit=getattr(task, "worker_exit", None),
                        snapshot_bytes=task.snapshot_bytes, validation_cache=task.validation_cache,
                        timings_ms={key: value * 1000 for key, value in task.work.timings.items()}))
                    if cycle == 0:
                        dialog.grab().save(str(output / f'export-{count}.png'))
                    dialog.close()
                    dialog.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    receipt()
                # Cancel from the visible window and retry the same project.
                dialog = dialog_for(page, folder, 'cancelled')
                dialog._run_export()
                cancelled = dialog._subtitle_task
                dialog.reject()
                wait(cancelled.done.is_set)
                check(f'{count} close cancels without stale UI', cancelled.snapshot is None
                      and cancelled.exception_type == 'SubtitleExportCancelled')
                retry = dialog_for(page, folder, 'retry')
                retry._run_export()
                wait(lambda: retry._subtitle_task is None)
                check(f'{count} cancelled export retries', len(retry.artifacts) == 1)
                retry.close()
                retry.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

            # The old-project repair is reached through its visible button.
            original = copy.deepcopy(page.project.speakers)
            orphan = StudioSpeaker('range-audit-S00', '局部识别 · S00（待确认）')
            page.project.speakers.append(orphan)
            register_range_speakers(page.project, [orphan])
            page._speaker_structure_changed()
            manager = SpeakerManagerDialog(page)
            manager.show()
            QTest.mouseClick(manager.more_toggle, Qt.MouseButton.LeftButton)
            check('repair button is actually visible', manager.cleanup_range_button.isVisible())
            QTest.mouseClick(manager.cleanup_range_button, Qt.MouseButton.LeftButton)
            check('visible repair removes automatic empty person', orphan.id not in {s.id for s in page.project.speakers})
            manager.grab().save(str(output / 'speaker-cleanup.png'))
            page.undo_stack.undo()
            check('visible repair undo restores person', orphan.id in {s.id for s in page.project.speakers})
            page.undo_stack.redo()
            check('visible repair redo retains original roster', page.project.speakers == original)
            target = save_project(page.project, output / 'repaired.2byteproj')
            check('repair persists across reopen', load_project(target).speakers == page.project.speakers)
            manager.close()
            manager.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

            check('all requested export loops completed', len(result['exports']) == 2 * cycles)
            result['passed'] = all(result['checks'].values())
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            try:
                page.undo_stack.setClean()
                page._recovered_autosave_pending = False
                page.close_page()
                window.close()
                result['gui_shutdown'] = True
            except Exception:
                result['shutdown_error'] = traceback.format_exc()
            receipt()
            QTimer.singleShot(100, app.quit)
    QTimer.singleShot(600, run)
