"""Opt-in normal source/frozen UI replay; all mutable data is under tmp.

The actual saved 48-cue project and 50 processing records are replayed. This
does not claim end-to-end inference, acoustic verification or a cloud speedup.
"""
from __future__ import annotations

import copy
from dataclasses import fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .display_handoff_ui import open_handoff_preview
    from .models import SpeechSegment, SubtitleCue, WordUnit
    from .recognition_result import media_identity_for_task, verify_result_reference
    from .runtime import RuntimeContext
    from .service import MediaResult, QueueResult
    from .studio_project import create_studio_outputs, load_project
    from .studio_revisions import thaw_json
    from .style_resolution import resolve_cue_visual
    from .visual_snapshot import _anchor
    from .terminology import apply_to_segments, snapshot_glossaries, TermResolver
    from .output import render_srt, render_txt

    output = Path(output).resolve()
    inputs = json.loads((output/'input.json').read_text('utf8'))
    fixture = Path(inputs['fixture']).resolve()
    require_paths = [fixture, Path(inputs['media']), Path(os.environ['APPDATA']), Path(os.environ['LOCALAPPDATA'])]
    if any(not path.resolve().is_relative_to(output) for path in require_paths):
        raise ValueError('Recognition correctness audit must use only its isolated copies')

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.started = time.monotonic()
            self.result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(),
                executable=sys.executable, identity=load_build_identity().to_dict(),
                entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main',
                scope=inputs['scope'], provider_calls=0, inference_run=False,
                screenshots_method='Actual HWND PrintWindow on a private desktop; desktop never switched')
            self.steps, self.waiting, self.busy = self.run(), 0., False
            self.deadline = time.monotonic()+60
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            self.write()
            if not value:
                raise AssertionError(name+': '+str(detail))

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                self.page = window.studio_page
                now = time.monotonic()
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    error = modal.text()+' '+modal.informativeText()
                    modal.reject()
                    raise RuntimeError(error)
                if now > self.deadline:
                    raise TimeoutError('Normal UI replay phase timed out')
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else time.monotonic()+float(step)
                self.deadline = time.monotonic()+65
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failure')
                except Exception:
                    self.result['capture_error'] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def ready(self):
            p = self.page
            self.result['last_readiness'] = dict(project_path=str(p.project_path),
                project_state=str(p._project_view_state), ready=p._readiness.ready,
                active=p._readiness.active, profile=dict(p._readiness.profile),
                controller_running=bool(p.video.controller and p.video.controller.running))
            self.write()
            return bool(p.project is not None and p._readiness.ready and not p._readiness.active
                and p._project_view_state == 'open' and p.video.controller and p.video.controller.running)

        def shot(self, name, surface=None):
            _capture(surface or window, output/(name+'.png'))
            self.result['screenshots'].append(name+'.png')

        def click(self, button):
            self.check('visible enabled action '+button.text(), button.isVisible() and button.isEnabled())
            if isinstance(button, QCheckBox):
                checked = button.isChecked()
                QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, QPoint(10, button.height()//2))
                self.check('checkbox indicator actually toggles '+button.text(), button.isChecked()!=checked)
            else:
                QTest.mouseClick(button, Qt.LeftButton)

        def state(self, project=None):
            return {cue.id: dict(text=cue.text, start=cue.start_ms, end=cue.end_ms,
                speaker=cue.speaker_id, transform=thaw_json(cue.transform))
                for cue in (project or self.page.project).cues}

        def anchors(self):
            p = self.page.project
            width, height = p.render_settings.get('play_res_x', 1920), p.render_settings.get('play_res_y', 1080)
            return {c.id: list(_anchor(resolve_cue_visual(p, c).style, width, height)[:2]) for c in p.cues}

        def transport(self):
            p = self.page
            clock = p.video.playback_position_snapshot()
            controller = p.video.controller
            observed = controller.observed_property('time-pos', None)
            return dict(paused=clock.paused, decoder_paused=controller.observed_property('pause', None),
                observed_ms=float(observed)*1000 if isinstance(observed, (float, int)) else None,
                presented_ms=clock.presentation_media_ms, timeline_ms=p.timeline.playhead_ms,
                seeking=clock.seeking, exact_seek_pending=clock.exact_seek_pending,
                buffered_play_pending=bool(getattr(p.video, '_buffered_play_pending', False)),
                startup_state=getattr(p.video, '_startup_state', ''))

        def settled_pause(self):
            sample = self.transport()
            self.result['last_transport'] = sample
            return bool(sample['paused'] and sample['decoder_paused'] is True
                and not sample['seeking'] and not sample['exact_seek_pending']
                and not sample['buffered_play_pending'] and sample['startup_state']=='READY')

        def seek(self, milliseconds):
            box = self.page.timecode_input
            box.setFocus()
            QTest.keyClick(box, Qt.Key_A, Qt.ControlModifier)
            seconds, millis = divmod(milliseconds, 1000)
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            QTest.keyClicks(box, f'{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}')
            QTest.keyClick(box, Qt.Key_Return)
            QTest.keyClick(box, Qt.Key_Tab)
            self.check('committed timecode leaves editing focus', not box.hasFocus())
            trace = dict(getattr(self.page.video, '_active_seek_trace', None) or {})
            self.seek_expectation = dict(requested_project_ms=milliseconds, trace=trace,
                decoder_target_ms=1000*trace.get('decoder_target_seconds', trace.get('target_seconds', -1)),
                canvas_target_ms=1000*trace.get('target_seconds', -1))

        def seek_complete(self):
            value = self.transport()
            expected = self.seek_expectation
            return bool(self.settled_pause() and value['observed_ms'] is not None
                and abs(value['timeline_ms']-expected['requested_project_ms'])<=40
                and abs(value['observed_ms']-expected['decoder_target_ms'])<=40
                and abs(value['presented_ms']-expected['canvas_target_ms'])<=40
                and self.rendered())

        def rendered(self):
            trace = self.page.subtitle_visibility_trace(reason='recognition_correctness_audit')
            self.result['last_visibility'] = trace
            return bool(trace.get('owner')=='caption_scene' and trace.get('visible')
                and set(trace.get('expected_cue_ids', ())) == set(trace.get('rendered_cue_ids', ()))
                and all(row.get('status')=='rendered' and row.get('alpha_nonzero', 0)>0
                        for row in trace.get('cue_pixels', ())))

        def glossary(self):
            window._manage_terms()
            QApplication.processEvents()
            page = window.term_library_page._ensure_library()
            # Work on the copied existing library, preserving its CHICHOO entry.
            item = next((page.game_list.item(index) for index in range(page.game_list.count())
                if page.game_list.item(index).data(Qt.UserRole)=='瓦罗兰特'), None)
            self.check('copied library present in normal list', item is not None)
            page.game_list.setCurrentItem(item)
            QApplication.processEvents()
            self.check('copied library selected', page._library_key()=='瓦罗兰特', page._library_key())
            for canonical, alias in [('CHIOCHOO', '球球'), ('autumn', '奥特曼'),
                                     ('MyCAT', '小猫'), ('S0pp', 'sop'), ('BerLIN', 'Borlin')]:
                page.term_editor.setText(canonical)
                page.term_alias_editor.setText(alias)
                self.click(page.add_term_button)
                QApplication.processEvents()
            self.click(page.use_game)
            QApplication.processEvents()
            ids = window._enabled_glossary_ids()
            snapshot = snapshot_glossaries(window.legacy, ids)
            self.check('normal UI enabled copied library', '瓦罗兰特' in ids, ids)
            self.check('new aliases and saved original spelling stay distinct',
                TermResolver(snapshot).resolve('球球 奥特曼 CHICHOO').text=='CHIOCHOO autumn CHICHOO')
            self.check('case and zero are saved exactly',
                TermResolver(snapshot).resolve('borlin sop sopp').text=='BerLIN S0pp sopp')
            path = output/'ui-added-library.json'
            page._export_library_to(path)
            self.check('ordinary library export persists confirmed pairs',
                {('球球', 'CHIOCHOO'), ('奥特曼', 'autumn')} <= {
                    (row['from'], row['to']) for row in json.loads(path.read_text('utf8'))['mappings']})
            self.shot('06-normal-glossary-add-and-enable')
            self.result['ui_added_snapshot'] = snapshot.summary()
            (output/'ui-added-snapshot.json').write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), 'utf8')
            return snapshot, ids

        def records(self):
            rows = json.loads((output/'source-polished.json').read_text('utf8'))['data']
            allowed = {field.name for field in fields(SpeechSegment)}
            result = []
            for row in rows:
                args = {key: copy.deepcopy(value) for key, value in row.items() if key in allowed}
                args['words'] = [WordUnit(**word) for word in args.get('words', ())]
                result.append(SpeechSegment(**args))
            return result

        def deliver(self, segments, ids, snapshot, job):
            media = inputs['media']
            cues = [SubtitleCue(s.segment_id, s.start, s.end, s.text, speaker=s.speaker) for s in segments]
            identity = media_identity_for_task(media, RuntimeContext())
            outputs = create_studio_outputs(media, cues, txt_path='', segments=segments, glossary_ids=ids,
                generation_metadata={'job_id': job, 'media_identity': identity,
                    'terminology_snapshot': snapshot.to_dict(), 'audit_origin': 'offline saved-record UI replay'})
            ref = json.loads(outputs['result_ref_json'])
            txt, srt = output/(job+'.txt'), output/(job+'.srt')
            txt.write_text(render_txt(cues), 'utf8')
            srt.write_text(render_srt(cues), 'utf8')
            report = json.loads((output/'input-report.txt').read_text('utf8'))
            report.update(job_id=job, status='success', audit_origin='offline saved-record UI replay; no new inference')
            report['media']['path'] = media
            report['result'].update(cue_count=len(cues), outputs={**outputs, 'txt': str(txt), 'srt': str(srt)},
                elapsed_seconds=0., recognition_result=ref)
            report_path = output/(job+'-report.json')
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf8')
            item = MediaResult(media, 'success', txt_path=str(txt), srt_path=str(srt),
                report_json_path=str(report_path), project_path=outputs['project'], job_id=job,
                project_id=ref['project_id'], result_revision=ref['result_revision'],
                media_fingerprint=ref['media_fingerprint'], result_ref_json=outputs['result_ref_json'])
            window._active_job_id = job
            window._handle_result(QueueResult((item,), 0., job_id=job))
            notification = getattr(window, '_completion_dialog', None)
            if notification and notification.isVisible():
                self.click(notification.confirm_button)
            self.result.setdefault('delivery_refs', []).append(ref)
            return ref

        def run(self):
            window.showNormal()
            window.resize(1460, 920)
            yield .3
            self.check('QSettings isolated', Path(QSettings('2ByteASR', 'recognition-correctness').fileName()).resolve().is_relative_to(output))
            before = self.state(load_project(fixture))
            window.open_studio_project(fixture, mode='edit', source='recognition_correctness_retained_copy')
            yield self.ready
            self.check('normal open retains all 48 cue ends and transforms', self.state()==before, len(before))
            self.result['retained_continuous_review'] = self.page.continuous_review_toggle.isChecked()
            if self.page.continuous_review_toggle.isChecked():
                self.click(self.page.continuous_review_toggle)
                yield .1
            if not self.transport()['paused']:
                self.click(self.page.play_button)
            yield self.settled_pause
            anchors = self.anchors()
            self.shot('01-original-copy-open')
            dialog = open_handoff_preview(self.page)
            yield .2
            self.check('preview alone does not change project', self.state()==before)
            self.check('preview lists actual proposed changes', dialog.table.rowCount()==len(dialog.ends) and bool(dialog.ends), dialog.audit)
            self.result['handoff_preview'] = dict(ends=dialog.ends, audit=dialog.audit, before=dialog.before)
            self.shot('02-handoff-preview', dialog)
            index = self.page.undo_stack.index()
            self.click(dialog.apply_button)
            yield .15
            after = self.state()
            expected = copy.deepcopy(before)
            for key, end in dialog.ends.items():
                expected[key]['end'] = end
            self.check('explicit apply changes only listed cue end times', after==expected)
            self.check('handoff is exactly one undo command', self.page.undo_stack.index()==index+1)
            self.page.undo_stack.undo()
            yield .1
            self.check('single undo restores ends and transforms', self.state()==before)
            self.page.undo_stack.redo()
            yield .1
            self.check('single redo restores exact reviewed changes', self.state()==after)
            self.click(self.page.save_button)
            yield .15
            self.check('normal save persists reviewed result', self.state(load_project(fixture))==after)
            for milliseconds in (18400, 25200):
                self.seek(milliseconds)
                yield self.seek_complete
                self.check('source anchors stable after seek '+str(milliseconds), self.anchors()==anchors)
                self.result.setdefault('seek_receipts', []).append(dict(requested_ms=milliseconds, expectation=self.seek_expectation,
                    observation=self.transport(), visibility=self.result['last_visibility']))
                self.shot('03-seek-'+str(milliseconds))
            before_play = self.transport()
            self.click(self.page.play_button)
            yield lambda:not self.transport()['paused'] and self.transport()['decoder_paused'] is False
            yield .45
            self.click(self.page.play_button)
            yield self.settled_pause
            current = self.transport()
            self.check('normal play advances actual decoder', current['observed_ms'] is not None
                and current['observed_ms'] > before_play['observed_ms']+100, current)
            self.check('anchors stable after play pause', self.anchors()==anchors)
            window.resize(1280, 900)
            yield .3
            self.check('resize preserves persisted transforms and anchors', self.state()==after and self.anchors()==anchors)
            self.shot('04-after-play-pause-resize')
            snapshot, ids = self.glossary()
            yield .2
            segments = self.records()
            original = copy.deepcopy(segments)
            events = []
            from types import SimpleNamespace
            apply_to_segments(segments, snapshot, SimpleNamespace(record_run_event=lambda name, **kw: events.append(dict(event=name, **kw))))
            self.result['local_application'] = events
            self.check('UI-saved aliases apply to actual six occurrences', events[0]['replacement_count']==6, events[0]['replacement_count'])
            self.check('all original source boundaries and speakers retained',
                [(s.start, s.end, s.speaker) for s in segments]==[(s.start, s.end, s.speaker) for s in original])
            self.check('all words agree with final body and canonical case', all(
                ''.join(w.text for w in s.words).replace(' ', '')==s.text.replace(' ', '') for s in segments if s.words))
            self.check('bounded-search provenance survives local normalization', all(
                old.caption_arbitration.get('timing_evidence')==new.caption_arbitration.get('timing_evidence')
                for old, new in zip(original, segments)))
            refs = []
            for number in (1, 2):
                job = f'offline-ui-record-replay-{number}'
                ref = self.deliver(copy.deepcopy(segments), ids, snapshot, job)
                refs.append(ref)
                yield .2
                self.shot('07-result-'+str(number))
                self.click(window.open_studio_result_button)
                yield self.ready
                current = verify_result_reference(ref, project=self.page.project, project_path=self.page.project_path)
                self.result.setdefault('loaded_result_identity', []).append(dict(
                    expected=ref, actual=current.generation_metadata.get('recognition_result'),
                    project_id=current.project_id, project_path=str(self.page.project_path),
                    readiness=dict(self.result['last_readiness']),
                    completion_callback_pending=bool(getattr(window, '_completion_project_opening', False))))
                self.check('real result button opens exact job '+str(number),
                    current.project_id==ref['project_id'] and len(current.cues)==50)
                # The ready callback precedes the asynchronous restored review
                # transport. Let the normal media event arrive before deciding
                # whether the real Pause action is needed.
                yield .4
                if self.page.continuous_review_toggle.isChecked():
                    self.click(self.page.continuous_review_toggle)
                    yield .1
                if not self.transport()['paused']:
                    self.click(self.page.play_button)
                yield self.settled_pause
                self.check('new result final body is saved in each project', [c.text for c in current.cues]==[s.text for s in segments])
                self.shot('08-studio-delivered-'+str(number))
            self.check('two same-name jobs retain independent projects', len({r['path'] for r in refs})==2
                and len({r['project_id'] for r in refs})==2 and len({r['result_revision'] for r in refs})==2)
            if inputs.get('live_result'):
                yield from self.live_result()
            yield from self.layout_fixture()
            from .blank_project_audit import _provider_calls, _blocked_external_connections
            self.result.update(provider_calls=_provider_calls, blocked_external_connections=_blocked_external_connections)
            self.check('no provider calls', _provider_calls==0)

        def live_result(self):
            """Deliver the already completed service object, never restamp it."""
            from .recognition_result import cue_identity, digest_payload, input_graph_identity
            from .studio_project import save_project
            live_path = Path(os.environ.get('TWOBYTEASR_ACCEPTANCE_LIVE_RESULT', '')).resolve()
            self.check('live receipt environment names the isolated manifest',
                live_path == Path(inputs['live_result']).resolve() and live_path.is_relative_to(output))
            live = json.loads(live_path.read_text('utf8'))
            queue, reference = live['queue'], live['reference']
            allowed = {field.name for field in fields(MediaResult)}
            items = tuple(MediaResult(**{key: value for key, value in row.items() if key in allowed})
                for row in queue['results'])
            self.check('live queue retains exact reference string',
                len(items)==1 and json.loads(items[0].result_ref_json)==reference)
            before = verify_result_reference(reference)
            self.result['live_upstream'] = {key: live.get(key) for key in
                ('source_receipt', 'upstream_passed', 'partial_home_delivery_only', 'upstream_outcome', 'upstream_error')}
            expected_state = self.state(before)
            expected_cues = cue_identity(before)
            expected_graph = input_graph_identity(before)
            window._active_job_id = queue['job_id']
            window._handle_result(QueueResult(items, queue['elapsed_seconds'],
                log_path=queue.get('log_path', ''), job_id=queue['job_id']))
            notice = getattr(window, '_completion_dialog', None)
            if notice and notice.isVisible():
                self.click(notice.confirm_button)
            yield .2
            self.shot('11-real-live-result')
            self.click(window.open_studio_result_button)
            yield self.ready
            actual_graph = input_graph_identity(self.page.project)
            audit_sections = ('media', 'media_pool', 'video_tracks', 'audio_tracks', 'av_track_groups',
                'edit_sequence', 'studio_state', 'edit_history', 'render_settings', 'project_id', 'cues')
            saved_data, opened_data = before.to_dict(), self.page.project.to_dict()
            (output/'live-project-open-comparison.json').write_text(json.dumps(dict(
                saved={key:saved_data.get(key) for key in audit_sections},
                opened={key:opened_data.get(key) for key in audit_sections}), ensure_ascii=False, indent=2), 'utf8')
            self.result['live_open_identity'] = dict(expected_reference=reference,
                actual_reference=self.page.project.generation_metadata.get('recognition_result'),
                actual_project_id=self.page.project.project_id,
                actual_path=str(self.page.project_path), expected_graph=expected_graph,
                actual_graph=actual_graph, actual_graph_digest=digest_payload(actual_graph),
                readiness=copy.deepcopy(self.result.get('last_readiness')),
                completion_callback_pending=bool(getattr(window, '_completion_project_opening', False)))
            self.write()
            current = verify_result_reference(reference, project=self.page.project,
                project_path=self.page.project_path)
            self.check('actual result button loads every committed live cue',
                current.project_id==reference['project_id'] and len(current.cues)==len(before.cues)
                and current.generation_metadata['recognition_result']==reference
                and self.state()==expected_state, reference)
            graph = input_graph_identity(current)
            self.check('live cue and input graph digests match the saved service reference',
                digest_payload(cue_identity(current))==reference['cue_digest']
                and digest_payload(graph)==reference['input_graph_digest'] and graph==expected_graph)
            clips = [clip for kind in ('video_tracks', 'audio_tracks')
                for track in graph[kind] for clip in track['clips'] if clip.get('enabled', True)]
            self.check('fresh live AV graph has zero origin and 67653ms effective duration',
                current.media.duration_ms==67653 and len(clips)==2 and all(
                    (clip['source_in_ms'], clip['timeline_in_ms'], clip['source_out_ms'], clip['timeline_out_ms'])
                    ==(0, 0, 67653, 67653) for clip in clips), graph)
            self.check('live media source and fingerprint match the committed input',
                Path(current.media.path).resolve()==Path(live['media']).resolve()
                and current.generation_metadata['media_identity']['fingerprint']==reference['media_fingerprint'])
            yield .4
            if self.page.continuous_review_toggle.isChecked():
                self.click(self.page.continuous_review_toggle)
                yield .1
            if not self.transport()['paused']:
                self.click(self.page.play_button)
            yield self.settled_pause
            anchors = self.anchors()
            name_rows = [dict(id=key, text=row['text'], words=row.get('words', []))
                for key, row in current.asr_evidence.items()
                if any(name in row.get('text', '') for name in ('CHIOCHOO', 'autumn'))]
            compact = lambda text: re.sub(r'\s+', '', str(text))
            self.check('saved live nickname words and bodies keep exact CHIOCHOO/autumn spelling',
                len(name_rows)==6 and all(compact(row['text'])==compact(''.join(
                    word['text'] for word in row['words'])) for row in name_rows)
                and not any(name in cue.text for cue in current.cues for name in ('球球', '奥特曼')),
                name_rows)
            self.result['live_delivery'] = dict(reference=reference, loaded_project_id=current.project_id,
                project_path=str(self.page.project_path), upstream_inference_run=True,
                gui_inference_run=False, name_evidence=name_rows, initial_anchors=anchors)
            self.shot('12-real-live-studio')
            for milliseconds in (18400, 25110, 21600, 26100):
                self.seek(milliseconds)
                yield self.seek_complete
                self.check('live cue content and anchors survive seek '+str(milliseconds),
                    self.state()==expected_state and self.anchors()==anchors)
                self.result['live_delivery'].setdefault('seek_receipts', []).append(dict(
                    requested_ms=milliseconds, expectation=self.seek_expectation,
                    observation=self.transport(), visibility=self.result['last_visibility']))
                self.shot('13-live-seek-'+str(milliseconds))
            previous = self.transport()
            self.click(self.page.play_button)
            yield lambda: not self.transport()['paused'] and self.transport()['decoder_paused'] is False
            yield .45
            self.click(self.page.play_button)
            yield self.settled_pause
            self.check('live decoder actually advances during normal play',
                self.transport()['observed_ms']>previous['observed_ms']+100, self.transport())
            window.resize(1460, 920)
            yield .2
            self.check('live playback pause resize retain every cue and anchor',
                self.state()==expected_state and self.anchors()==anchors)
            self.result['live_delivery']['graph_after_playback'] = input_graph_identity(current)
            self.check('asynchronous decoder and waveform work preserve committed live input graph',
                input_graph_identity(current)==expected_graph,
                dict(expected_duration=expected_graph['media']['duration_ms'],
                    actual_duration=current.media.duration_ms))
            self.shot('14-live-after-play-pause-resize')
            # Export range controls edit a separate tmp fixture. The original
            # committed live project and its reference remain unchanged.
            export_path = output/'live-export-fixture.2byteproj'
            save_project(copy.deepcopy(current), export_path)
            reopened = load_project(export_path)
            self.check('saved live export copy preserves cues input graph and anchors',
                cue_identity(reopened)==expected_cues and input_graph_identity(reopened)==expected_graph
                and self.state(reopened)==expected_state, dict(cues_equal=cue_identity(reopened)==expected_cues,
                    graph_equal=input_graph_identity(reopened)==expected_graph,
                    state_equal=self.state(reopened)==expected_state))
            self.result['live_delivery']['saved_copy'] = dict(path=str(export_path),
                sha256_before_export=hashlib.sha256(export_path.read_bytes()).hexdigest(),
                copied_reference=copy.deepcopy(reopened.generation_metadata['recognition_result']))
            self.check_ass(reopened, output/'live-full.ass', 'all saved live cues')
            self.live_subtitles(reopened)
            window.open_studio_project(export_path, mode='edit', source='recognition_correctness_live_export_copy')
            yield self.ready
            yield .4
            if self.page.continuous_review_toggle.isChecked():
                self.click(self.page.continuous_review_toggle)
                yield .1
            if not self.transport()['paused']:
                self.click(self.page.play_button)
            yield self.settled_pause
            yield from self.export_live_video()
            self.check('live export copy retains all original cue text time speaker and transforms',
                self.state()==expected_state)
            self.click(self.page.save_button)
            yield .2
            saved = load_project(export_path)
            self.check('normal save of the export copy retains exact cue and input graph digests',
                cue_identity(saved)==expected_cues and digest_payload(input_graph_identity(saved))==reference['input_graph_digest'])
            self.result['live_delivery']['saved_copy']['sha256_after_export'] = hashlib.sha256(export_path.read_bytes()).hexdigest()

        def live_subtitles(self, project):
            from .studio_subtitle_export import (SubtitleExportOptions,
                export_subtitle_artifacts, verify_subtitle_artifact)
            from .export_timeline import export_project_snapshot
            frozen = export_project_snapshot(project)
            artifacts = export_subtitle_artifacts(project, output/'live-subtitles', 'live-r3-57-cues',
                SubtitleExportOptions(frozenset({'srt', 'ass', 'txt', 'json'})))
            receipts = []
            for artifact in artifacts:
                verification = verify_subtitle_artifact(artifact, frozen)
                text = artifact.path.read_text('utf8')
                self.check('saved live '+artifact.format+' preserves canonical body and timestamps',
                    verification.valid and 'CHIOCHOO' in text and 'autumn' in text
                    and 'chiochoo' not in text and 'Autumn' not in text,
                    dict(path=str(artifact.path), cue_count=verification.cue_count,
                        unicode_valid=verification.unicode_valid, timestamps_valid=verification.timestamps_valid))
                receipts.append(dict(path=str(artifact.path), format=artifact.format,
                    sha256=hashlib.sha256(artifact.path.read_bytes()).hexdigest(),
                    cue_count=verification.cue_count, valid=verification.valid))
            self.result['live_subtitle_artifacts'] = receipts

        def check_ass(self, project, path, label, *, existing=False):
            from .export_timeline import export_project_snapshot
            from .ass_compiler import compile_ass
            frozen = export_project_snapshot(project)
            content = path.read_text('utf-8-sig') if existing else compile_ass(frozen)
            if not existing:
                path.write_text(content, 'utf8')
            payloads = [line.split(',', 9)[9] for line in content.splitlines() if line.startswith('Dialogue:')]
            plain = [re.sub(r'\{[^}]*\}', '', text).replace(r'\N', '').replace(r'\n', '').replace(r'\h', ' ')
                for text in payloads]
            compact = lambda text: re.sub(r'\s+', '', str(text))
            self.check('ASS payload preserves exact visible text '+label,
                len(payloads)>=len(frozen.cues) and all(compact(cue.text) in {compact(text) for text in plain}
                    for cue in frozen.cues), dict(path=str(path), events=len(payloads), cues=len(frozen.cues)))
            self.check('ASS nickname case matches saved bodies '+label,
                any('CHIOCHOO' in text for text in plain) and any('autumn' in text for text in plain)
                and not any('chiochoo' in text or 'Autumn' in text for text in plain))
            self.result.setdefault('ass_text_receipts', []).append(dict(path=str(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), cue_count=len(frozen.cues),
                nickname_payloads=[text for text in plain if 'CHIOCHOO' in text or 'autumn' in text]))

        def export_live_video(self):
            """Real export buttons, frozen production job, encoded MP4 frames."""
            p = self.page
            self.click(p.studio_render_button)
            yield lambda: p.export_workspace is not None
            ui = p.export_workspace
            yield .3
            ui.filename.setText('live-r3-15-28')
            ui.filename_prefix.clear()
            ui.filename_suffix.clear()
            ui.directory.setText(str(output/'video'))
            for box, value in ((ui.preset, 'custom'), (ui.quality, 'custom'),
                    (ui.extension, 'mp4'), (ui.codec, 'h264'), (ui.rate_control, 'crf'),
                    (ui.encoder_preset, 'balanced'), (ui.audio, 'aac')):
                index = box.findData(value)
                self.check('production export choice available '+value, index>=0)
                box.setCurrentIndex(index)
            if ui.encoder.findData('libx264')<0:
                ui.encoder.addItem('Software x264', 'libx264')
            ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
            ui.quality_value.setValue(20)
            for field, value in zip(ui.project_range_bar.fields, ('00:00:15.000', '00:00:28.000')):
                field.setFocus()
                QTest.keyClick(field, Qt.Key_A, Qt.ControlModifier)
                QTest.keyClicks(field, value)
                QTest.keyClick(field, Qt.Key_Return)
                QTest.keyClick(field, Qt.Key_Tab)
            ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
            self.check('normal export range fields freeze 15 to 28 seconds',
                ui._range_seconds()==(15., 13., 13.), ui._range_seconds())
            self.click(ui.export_button)
            yield lambda: ui._last_job is not None
            job = ui._last_job
            self.check('production job freezes AV graph and exact range',
                job.start_seconds==15. and job.duration_seconds==13. and bool(job.video_graph)
                and bool(job.export_project_data) and job.settings.audio_codec=='aac')
            self.check_ass(p.project, Path(job.ass_path), 'frozen production export', existing=True)
            yield lambda: not ui._running
            self.check('normal production MP4 export completes successfully', ui.pages.currentWidget()==ui.success_page,
                dict(failure=ui._last_failure, output=job.output_path, receipt=job.completion_metadata))
            rendered = Path(job.output_path)
            self.check('real encoded MP4 published within tmp', rendered.is_file() and rendered.resolve().is_relative_to(output))
            self.result['live_video_export'] = dict(path=str(rendered), ass=job.ass_path,
                start_seconds=15., duration_seconds=13., job_context=job.export_context,
                receipt=copy.deepcopy(job.completion_metadata), inference_run=False,
                limitations='Encoded frame inspection validates displayed spelling/placement; no new human acoustic listening. SRT has no placement contract.')
            self.shot('16-live-export-complete')
            self.video_frames(job)
            ui._back()
            yield .2

        def video_frames(self, job):
            from .platform_media import ffmpeg_tool
            from .processes import run_hidden_subprocess
            ffmpeg = ffmpeg_tool()
            ffprobe = ffmpeg.with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')
            probe = run_hidden_subprocess([str(ffprobe), '-v', 'error', '-show_entries',
                'format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate', '-of', 'json', job.output_path],
                purpose='recognition correctness exported clip probe', capture_output=True, text=True,
                encoding='utf8', timeout=15, check=True)
            media = json.loads(probe.stdout)
            self.check('encoded clip is 13 seconds and retains video and audio streams',
                abs(float(media['format']['duration'])-13.)<.1
                and {row['codec_type'] for row in media['streams']} >= {'video', 'audio'}, media)
            frames = []
            for source_seconds, canonical in ((21.6, 'CHIOCHOO'), (26.1, 'autumn')):
                target = output/f'burned-{canonical}.png'
                run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-ss', str(source_seconds-15), '-i',
                    job.output_path, '-frames:v', '1', '-y', str(target)],
                    purpose='recognition correctness actual encoded frame', capture_output=True,
                    text=True, encoding='utf8', timeout=15, check=True)
                self.check('decoded burned video frame exists '+canonical, target.is_file() and target.stat().st_size>1000)
                frames.append(dict(canonical=canonical, source_seconds=source_seconds,
                    encoded_seconds=source_seconds-15, path=str(target),
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
            self.result['live_video_export'].update(probe=media, decoded_frames=frames,
                visual_review_pending=True)

        def layout_fixture(self):
            from .subtitle_stacking import initialize_project_layout
            from .subtitle_layout_ui import open_layout_preview
            from .studio_project import save_project
            cues = [SubtitleCue(i+1, i*.3, i*.3+.45, '测试字幕', speaker='S01' if i%2 else 'S02') for i in range(100)]
            identity = media_identity_for_task(inputs['media'], RuntimeContext())
            generated = create_studio_outputs(inputs['media'], cues, txt_path='',
                generation_metadata={'job_id':'offline-ui-layout-chain', 'media_identity':identity,
                    'audit_origin':'synthetic two-concurrent 100-cue layout fixture; no inference'})
            project = load_project(generated['project'])
            offsets = {thaw_json(c.transform).get('initial_layout', {}).get('offset_y', 0) for c in project.cues}
            self.check('100-cue two-concurrent chain reuses exactly two saved bands', len(offsets)==2 and 0 in offsets, sorted(offsets))
            manual = project.cues[1]
            manual.transform = {**thaw_json(manual.transform), 'position_x':777, 'position_y':888,
                'position_locked':True, 'keyframes':{'position_y': [{'time_ms':0, 'value':888}, {'time_ms':100, 'value':800}]}}
            original = copy.deepcopy(manual.transform)
            initialize_project_layout(project)
            self.check('manual position and keyframes retained', manual.transform==original)
            # Labelled authored fixture: deliberately displace one automatic
            # saved base position, then exercise the real review/apply command.
            auto = project.cues[3]
            auto.transform['initial_layout']['position_y'] -= 150
            save_project(project, generated['project'])
            self.result['synthetic_layout_fixture'] = dict(project=generated['project'], offsets=sorted(offsets),
                maximum_concurrency=2, cue_count=100, inference_run=False, manual_transform=original)
            window.open_studio_project(generated['project'], mode='edit', source='recognition_correctness_layout_fixture')
            yield self.ready
            yield .4
            if self.page.continuous_review_toggle.isChecked():
                self.click(self.page.continuous_review_toggle)
                yield .1
            if not self.transport()['paused']:
                self.click(self.page.play_button)
            yield self.settled_pause
            before = self.state()
            self.check('normal open preserves manual positions and keyframes',
                self.page.project.cues[1].transform==original)
            dialog = open_layout_preview(self.page, [c.id for c in self.page.project.cues])
            yield .15
            self.check('layout preview leaves original project untouched', self.state()==before)
            self.check('layout review protects the authored cue', manual.id in dialog.protected_ids
                and not dialog.reset_manual.isChecked(), list(dialog.protected_ids))
            self.check('layout preview lists all selected captions and a real change',
                dialog.table.rowCount()==100 and dialog.command is not None)
            self.shot('09-layout-preview-manual-keyframes', dialog)
            index = self.page.undo_stack.index()
            self.click(dialog.apply_button)
            yield .15
            after = self.state()
            self.check('layout apply preserves every text time and speaker',
                [{k:v for k,v in row.items() if k!='transform'} for row in before.values()]==
                [{k:v for k,v in row.items() if k!='transform'} for row in after.values()])
            self.check('layout apply preserves manual transform and keyframes',
                self.page.project.cues[1].transform==original)
            self.check('layout review applies one undoable edit', after!=before and self.page.undo_stack.index()==index+1)
            self.page.undo_stack.undo()
            yield .1
            self.check('one layout undo restores every transform', self.state()==before)
            self.page.undo_stack.redo()
            yield .1
            self.check('one layout redo restores exact reviewed transform', self.state()==after)
            self.click(self.page.save_button)
            yield .1
            self.shot('10-layout-applied')

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), 'utf8')

        def finish(self):
            self.timer.stop()
            self.result['elapsed_seconds'] = round(time.monotonic()-self.started, 3)
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()
            def stopped():
                self.result['gui_shutdown'] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            modal = QApplication.activeModalWidget()
            if modal is not None:
                modal.reject()
            window.close()

    window._recognition_correctness_audit = Audit()
