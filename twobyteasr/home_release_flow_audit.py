# SPDX-License-Identifier: GPL-3.0-only
"""Guarded installed-build check of actual Home ASR; no injected transcripts."""
import json
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path


def start(window, out):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from .build_identity import load_build_identity
    from .studio_project import load_project
    from .macos_desktop_evidence import (studio_snapshot, preserve_owned_project,
                                         preserve_studio_preview, image_colour_observation)
    config = json.loads((out/'home-flow.json').read_text('utf8'))
    result = dict(passed=False, identity=load_build_identity().to_dict(), checks={},
                  events=[], actual_model=True, injected_transcript=False, paid_calls=0)
    received, errors = [], []

    def save():
        (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value):
        result['checks'][name] = bool(value); save()
        if not value: raise AssertionError(name)

    def pump(seconds=.05):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            QApplication.processEvents(); time.sleep(.005)

    def wait(predicate, seconds, label):
        end = time.monotonic()+seconds
        while not predicate() and not errors and time.monotonic() < end: pump()
        check(label, predicate())
        if errors: raise RuntimeError(str(errors))

    def preview(page, label):
        if sys.platform != 'darwin':
            return
        controller = page.video.controller
        def visible_pixels():
            return (image_colour_observation(controller.surface.frame)['colour_fraction'] > .10
                    and image_colour_observation(page.video.grab().toImage())['colour_fraction'] > .10)
        deadline = time.monotonic()+3
        while not visible_pixels() and time.monotonic() < deadline:
            pump()
        record = preserve_studio_preview(page, out, label)
        result.setdefault('studio_preview', {})[label] = record
        check('actual Studio coloured decoded and composed video '+label, record['passed'])

    def run():
        guard = QTimer(window)
        def modal_guard():
            modal = QApplication.activeModalWidget()
            if isinstance(modal, QMessageBox):
                from .i18n import tr
                if modal.windowTitle() in {'本次识别会上传音频', tr('本次识别会上传音频')}:
                    # The pre-run upload confirmation (shown when the run is
                    # not under TWOBYTEASR_TEST_ROOT): record what it says and
                    # start, as a user who read it would (2026-10-14).
                    result.setdefault('run_disclosures', []).append(modal.informativeText())
                    start = next((b for b in modal.buttons()
                                  if modal.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole), None)
                    if start is not None:
                        start.click(); return
                errors.append(modal.text()+' '+modal.informativeText()); modal.reject()
        try:
            guard.timeout.connect(modal_guard); guard.start(200)
            # Use the ordinary return action: it refreshes newly prepared models.
            window._return_to_settings()
            # Select a supported combination through existing controls. The
            # default is local SenseVoice; a cloud config (2026-10-13) selects
            # the recognizer through the same provider controls a user uses.
            asr = dict(primary_asr_backend='sensevoice', firered_asr_backend='off', qwen_asr_backend='off')
            asr.update(config.get('asr') or {})
            api = config.get('api') or {}
            if config.get('loopback_mosi_reference'):
                from .mosi_loopback import start as start_loopback
                reference = json.loads(Path(config['loopback_mosi_reference']).read_text('utf8'))
                server, loopback = start_loopback(reference)
                result['loopback'] = loopback
                api = dict(provider='mosi_moss_pro', model='moss-transcribe-diarize-pro',
                           url=f'http://127.0.0.1:{server.server_port}/v1', key='sk-loopback-test', **api)
            if api:
                index = window.qwen_asr_api_provider.findData(api['provider'])
                check('available cloud provider '+api['provider'], index >= 0)
                window.qwen_asr_api_provider.setCurrentIndex(index)
                window.qwen_asr_api_model.setText(api['model']); window.qwen_asr_api_url.setText(api['url'])
                window.qwen_asr_api_key.setText(api.get('key', ''))
            for name, value in asr.items():
                combo = getattr(window, name); index = combo.findData(value)
                check('available '+name, index >= 0); combo.setCurrentIndex(index)
            window.ai_polish.setChecked(False)
            window.ai_grouping.setChecked(False); window.unified_glm.setChecked(False)
            window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] = []
            # One-voice fixtures use a single speaker; a MOSS run keeps MOSS's own speakers (2026-10-14).
            window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] = config.get('speaker_source', 'single')
            check('save local ASR configuration', window._save_asr_configuration(show_feedback=False))
            check('save local-only AI configuration', window._save_ai_configuration(show_feedback=False))
            source = str(Path(config['media']).resolve())
            window.import_media([source], replace=True)
            wait(lambda: window.media_paths == [source] and window.start_button.isEnabled(), 40, 'normal Home media intake')
            window.grab().save(str(out/'01-home-ready.png'))
            original = window._handle_event
            def observe(event):
                result['events'].append(asdict(event)); save(); original(event)
            window._handle_event = observe
            check('Home Start visible and enabled', window.start_button.isVisible() and window.start_button.isEnabled())
            QTest.mouseClick(window.start_button, Qt.LeftButton); pump(.1)
            check('normal Home Start launches actual worker', window.worker is not None)
            worker = window.worker
            result['task_options'] = asdict(worker.options)
            worker.result_ready.connect(received.append); worker.unexpected_error.connect(errors.append)
            wait(lambda: bool(received), int(config.get('timeout', 600)), 'real supported-model recognition completes')
            wait(lambda: not worker.isRunning(), 30, 'actual worker exits')
            result['recognition'] = asdict(received[0]); save()
            accepted = tuple(config.get('accept_status') or ('success',))
            result['task_status'] = received[0].successes[0].status if received[0].successes else ''
            check('task completes with an accepted status', bool(received[0].successes) and result['task_status'] in accepted)
            events_path = Path(worker.options.event_log_path) if getattr(worker.options, 'event_log_path', '') else None
            check('actual recognition delivers project', bool(received[0].successes and received[0].successes[0].project_path))
            target = Path(received[0].successes[0].project_path)
            for dialog in QApplication.topLevelWidgets():
                if isinstance(dialog, QDialog) and dialog.isVisible(): dialog.close()
            guard.stop()
            project = load_project(target)
            result['recognized_text'] = [cue.text for cue in project.cues]
            result['project_path'] = str(target)
            result['owned_project'] = preserve_owned_project(target, out.parent if config.get('recognition_only') else out,
                                                             'restart' if config.get('recognition_only') else 'recognized')
            check('actual ASR text is nonempty', bool(project.cues and any(c.text.strip() for c in project.cues)))
            # Which evidence the result really carries: speakers and cues with measured word times.
            from .cue_word_alignment import cue_words
            measured = 0
            for cue in project.cues:
                try:
                    measured += bool(cue_words(project, cue)[0])
                except Exception:
                    pass
            result['speakers'] = sorted({str(cue.speaker_id) for cue in project.cues})
            result['cues_with_measured_words'] = measured
            result['cue_count'] = len(project.cues)
            if config.get('require_measured_words'):
                check('local word timeline measured word times', measured > 0)
            if config.get('recognition_only'):
                result['restart_short_task']=True
                result['saved_project']=str(target)
                result['passed']=True
                return
            page = window.studio_page
            window.open_studio_project(target, mode='edit', source='home_release_validation')
            wait(lambda: page.project is not None and page.project.project_id == project.project_id and page._readiness.ready, 90, 'recognized result enters Studio')
            result['studio_ready_snapshot'] = studio_snapshot(page); save()
            preview(page, 'ready')
            cue = page.project.cues[0]; page.select_cue(cue.id)
            page._seek(cue.start_ms/1000+.1); pump(.3)
            page._begin_canvas_inline_edit(); pump(.2)
            editor = page.subtitle_edit_input
            check('normal Chinese editor visible', editor.isVisible())
            editor.setFocus(); QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
            event = QInputMethodEvent(); event.setCommitString('兔白字幕 0.5.0 实际识别后中文编辑')
            QApplication.sendEvent(editor, event); QTest.keyClick(editor, Qt.Key_Return); pump(.3)
            expected = page._cue_lookup[cue.id].text
            check('Chinese commit reaches actual cue', '实际识别后中文编辑' in expected)
            from .studio_edit_sequence import projected_cues, sequence_of
            import copy
            def signature():
                return [(c.text,c.start_ms,c.end_ms,c.speaker_id,c.style_id,c.appearance_override)
                        for c in projected_cues(page.project)]
            # New recognition projects keep V1 locked against accidental cuts;
            # unlock it the way a user does (track lock action) before cutting.
            from .studio_clip_edit import video_track_locked
            unlocked = []
            for track in list(page.project.video_tracks):
                if video_track_locked(page.project, track):
                    page._video_track_action(track.id, 'locked'); pump(.2); unlocked.append(track.id)
            result['unlocked_video_tracks'] = unlocked
            before = signature()
            before_raw = copy.deepcopy(page.project.to_dict())
            (out/'cut-before.json').write_text(json.dumps(before_raw,ensure_ascii=False,indent=2),'utf8')
            crossing = max(page.project.cues, key=lambda c:c.end_ms-c.start_ms)
            cut_ms = (crossing.start_ms+crossing.end_ms)//2
            page._seek(cut_ms/1000); pump(.5)
            page.timeline.selected_video_track_id = ''
            page.timeline.setFocus()
            QTest.keyClick(page.timeline,Qt.Key_K,Qt.ControlModifier); pump(.3)
            check('Ctrl+K without selected track preserves caption semantics', signature()==before and len(sequence_of(page.project).segments)==2)
            after_raw = page.project.to_dict()
            check('cut retains authored cues and word evidence', after_raw['cues']==before_raw['cues'] and after_raw['generation_metadata']==before_raw['generation_metadata'])
            (out/'cut-after.json').write_text(json.dumps(after_raw,ensure_ascii=False,indent=2),'utf8')
            page.undo_stack.undo();pump(.2)
            check('cut undo restores one segment and captions',len(sequence_of(page.project).segments)==1 and signature()==before)
            page.undo_stack.redo();pump(.2)
            check('cut redo restores two segments and captions',len(sequence_of(page.project).segments)==2 and signature()==before)
            second_ms = min(int(page.project.media.duration_ms)-100, cut_ms+1000)
            page._seek(second_ms/1000);pump(.4);page.timeline.setFocus()
            QTest.keyClick(page.timeline,Qt.Key_K,Qt.ControlModifier);pump(.2)
            check('second Ctrl+K preserves captions',len(sequence_of(page.project).segments)==3 and signature()==before)
            result['cut_ms']=cut_ms
            for offset in (-1,1):
                position=(cut_ms+offset*1000/30)/1000
                page._seek(position);pump(.4)
                window.grab().save(str(out/f'cut-frame-{offset}.png'))
                preview(page, 'cut-before' if offset < 0 else 'cut-after')
            QTest.mouseClick(page.save_button, Qt.LeftButton)
            wait(lambda: page.undo_stack.isClean(), 30, 'normal Save completes')
            page.show_project_hub(skip_dirty_guard=True)
            window.open_studio_project(target, mode='edit', source='home_release_reopen')
            wait(lambda: page.project is not None and cue.id in page._cue_lookup and page._readiness.ready, 90, 'normal reopen completes')
            check('Chinese edit survives save and reopen', page._cue_lookup[cue.id].text == expected)
            check('cut captions survive save and reopen', signature()==before and len(sequence_of(page.project).segments)==3)
            window.grab().save(str(out/'02-recognized-edited-reopened.png'))
            preview(page, 'reopened')
            QTest.mouseClick(page.studio_render_button,Qt.LeftButton)
            wait(lambda:page.export_workspace is not None and hasattr(page.export_workspace,'subtitle_format_checks'),30,'normal export workspace opens')
            ui=page.export_workspace
            export_root=out/'exports';export_root.mkdir(exist_ok=True)
            ui.subtitle_custom_directory.setText(str(export_root))
            ui.subtitle_destination_modes['custom'].setChecked(True)
            for control in ui.subtitle_format_checks.values(): control.setChecked(True)
            ui.subtitle_speaker_modes['combined'].setChecked(True)
            QTest.mouseClick(ui.subtitle_export_button,Qt.LeftButton);pump(.3)
            artifacts=ui._last_subtitle_artifacts
            result['subtitle_artifacts']=[str(a.path) for a in artifacts]
            check('actual GUI subtitle button exports four formats',len(artifacts)==4 and {a.path.suffix.lower() for a in artifacts}=={'.srt','.ass','.txt','.json'} and all(a.path.is_file() for a in artifacts))
            check('GUI subtitle output retains edited Chinese',all('实际识别后中文编辑' in a.path.read_text('utf-8-sig') for a in artifacts))
            from .studio_subtitle_export import verify_subtitle_artifact
            expected_project=copy.copy(page.project)
            expected_project.cues=projected_cues(page.project, domain='timeline')
            verification=[verify_subtitle_artifact(a,expected_project) for a in artifacts]
            result['subtitle_verification']=[asdict(row) for row in verification]
            check('GUI subtitle files parse with expected text and timing',all(row.valid for row in verification))
            ui.directory.setText(str(export_root));ui.resolution.setCurrentIndex(ui.resolution.findData((640,360)))
            ui.export_range.setCurrentIndex(ui.export_range.findData('full'))
            destination=ui.export_target().full_path
            QTest.mouseClick(ui.export_button,Qt.LeftButton)
            wait(lambda:not ui._running and (ui.pages.currentWidget() is ui.success_page or ui._last_failure),180,'cut Chinese project video export completes')
            result['video_error']=ui._last_failure
            check('cut Chinese video export succeeds',not ui._last_failure and destination.is_file())
            result['video_output']=str(destination)
            window.grab().save(str(out/'03-four-formats-and-video.png'))
            result['saved_project'] = str(target); result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            result['block_reason'] = getattr(window, '_run_block_reason', '')
            result['console'] = window.console.toPlainText() if hasattr(window, 'console') else ''
            result['studio_failure_snapshot'] = studio_snapshot(window.studio_page)
            window.grab().save(str(out/'failure.png'))
        finally:
            if result.get('project_path'):
                try:
                    result['final_owned_project'] = preserve_owned_project(Path(result['project_path']),
                        out.parent if config.get('recognition_only') else out,
                        'restart' if config.get('recognition_only') else 'final')
                except Exception as exc:
                    result['project_preservation_error'] = str(exc)
            guard.stop(); save()
            if getattr(window, 'worker', None) and window.worker.isRunning():
                window.token.cancel(); window.worker.wait(10000)
            window.studio_page.undo_stack.setClean()
            for dialog in QApplication.topLevelWidgets():
                if isinstance(dialog, QDialog) and dialog.isVisible(): dialog.reject()
            window.close()
            # A failed native task can leave an animated modal event loop alive.
            # The receipt above still fails; end this guarded audit process after
            # the real task is stopped, so subsequent independent checks can run.
            import sys
            if sys.platform == 'darwin':
                QTimer.singleShot(250, QApplication.instance().quit)
    QTimer.singleShot(500, run)
