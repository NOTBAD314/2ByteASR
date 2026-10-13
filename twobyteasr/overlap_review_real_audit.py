"""Opt-in real saved-caption review, seek pixels and production SRT audit.

The external plan is data only. No cue is invented, inference rerun, response
replayed or product renderer changed. Native mpv screenshots include its video,
subtitles and bitmap overlays; HWND PrintWindow independently captures the UI.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _data_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf8')).hexdigest()


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .caption_scene import active_cues
    from .studio_acceptance_audit import audit_tmp_root
    from .studio_commands import MutationOrigin, SetCueFieldsCommand
    from .studio_edit_sequence import projected_cues, sequence_of, timeline_duration_ms
    from .studio_project import load_project
    from .studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts, verify_subtitle_artifact

    output = Path(output).resolve()

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = {'passed': False, 'checks': [], 'screenshots': [], 'timepoints': [],
                'exports': [], 'pid': os.getpid(), 'executable': sys.executable,
                'identity': load_build_identity().to_dict(),
                'scope': '32 existing saved cues; source media; no new ASR/model or missing utterance recovery',
                'pixel_methods': ['mpv screenshot-to-file mode window (video/subtitles/bitmap)', 'HWND PrintWindow'],
                'page_bindings': [], 'gui_shutdown': False}
            self.events = []
            self.phase = 'initialization'
            self.waiting = 0
            self.deadline = time.monotonic() + 120
            self.busy = False
            self.steps = self.run()
            self.observed_page = None
            self.original_trace = None
            self.bind_page()
            self.timer = QTimer(self)
            self.timer.setInterval(50)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def check(self, name, passed, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(passed), 'detail': detail})
            if not passed:
                raise AssertionError(f'{name}: {detail}')

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                now = time.monotonic()
                if now > self.deadline:
                    raise TimeoutError(f'Overlap review audit phase timeout: {self.phase}')
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else now + float(step)
                self.deadline = time.monotonic() + 120
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.result['failure_visibility'] = self.page.subtitle_visibility_trace(reason='overlap_review_failure')
                    self.shot('overlap-review-failure')
                    controller = self.page.video.controller
                    if controller is not None and controller.running:
                        controller.screenshot_to_file(output/'overlap-review-failure-mpv.png')
                except Exception as exc:
                    self.result['failure_capture_error'] = repr(exc)
                self.finish()
            finally:
                self.busy = False

        def bind_page(self):
            actual = window.studio_page
            if actual is self.observed_page:
                return
            if self.observed_page is not None:
                self.observed_page._studio_trace = self.original_trace
            self.page = self.observed_page = actual
            forward = self.original_trace = actual._studio_trace
            def observed_trace(event, **values):
                self.events.append({'at': time.perf_counter(), 'phase': self.phase,
                                    'page_object_id': id(actual), 'event': event, **values})
                return forward(event, **values)
            actual._studio_trace = observed_trace
            self.result['page_bindings'].append({'phase': self.phase, 'page_object_id': id(actual)})

        def ready(self):
            self.bind_page()
            controller = self.page.video.controller
            return (self.page.project is not None and self.page._readiness.ready
                and not self.page._readiness.active and controller is not None and controller.running)

        def shot(self, name):
            target = output/(name+'.png')
            _capture(window, target)
            image = QImage(str(target))
            self.check('HWND image decoded '+name, not image.isNull() and image.width() > 0 and image.height() > 0)
            self.result['screenshots'].append({'path': str(target), 'method': 'HWND PrintWindow',
                'sha256': _sha(target), 'size': [image.width(), image.height()]})

        def seek_ui(self, milliseconds):
            control = self.page.timecode_input
            control.setFocus()
            QTest.keyClick(control, Qt.Key_A, Qt.ControlModifier)
            seconds, remainder = divmod(int(milliseconds), 1000)
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            QTest.keyClicks(control, f'{hours:02d}:{minutes:02d}:{seconds:02d}.{remainder:03d}')
            QTest.keyClick(control, Qt.Key_Return)

        def visible_ready(self, point):
            milliseconds = point['timeline_ms']
            expected = set(point['expected_active_cue_ids'])
            if abs(int(self.page.timeline.playhead_ms)-milliseconds) > 1:
                return False
            controller = self.page.video.controller
            if controller.observed_property('pause', None) is not True:
                return False
            actual = controller.observed_property('time-pos', None)
            if actual is None or abs(float(actual)*1000-point['source_ms']) > 40:
                return False
            trace = self.page.subtitle_visibility_trace(reason='overlap_review_seek_wait')
            if trace.get('owner') == 'caption_scene':
                return (set(trace.get('expected_cue_ids', ())) == expected
                    and set(trace.get('rendered_cue_ids', ())) == expected
                    and trace.get('visible') is True)
            return (len(expected) == 1 and trace.get('cue_id') in expected
                and trace.get('visible') is True and trace.get('foreground_owner_count') == 1)

        def validate_project(self, project, label):
            self.check(label+' project identity', project.project_id == self.plan['project_id'], project.project_id)
            self.check(label+' complete32 cue rows', project.to_dict()['cues'] == self.plan['expected_cues'])
            self.check(label+' original31 ASR unchanged', _data_sha(project.asr_evidence) == self.plan['expected_asr_evidence_sha256'])
            self.check(label+' USER_EDIT protected texts', project.studio_state.get('manual_caption_text', {}) == self.plan['manual_caption_text'])
            self.check(label+' raw schema unchanged', project.schema_version == self.plan['schema_version'])
            self.check(label+' source media same', Path(project.media.path).resolve() == Path(self.plan['media_path']).resolve())

        def run(self):
            self.plan = json.loads((output/'review-plan.json').read_text('utf8'))
            self.startup = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT']).resolve()
            source = Path(self.plan['project_path']).resolve()
            self.check('external data plan kind', self.plan['kind'] == 'overlap_review_actual_caption_copy')
            self.check('exact four requested real timepoints',
                [x['timeline_ms'] for x in self.plan['timepoints']] == [10000,12000,12450,13700])
            self.check('plan original and startup paths isolated',
                source.is_relative_to(audit_tmp_root()) and self.startup.is_relative_to(output))
            self.check('original task copy SHA', _sha(source) == self.plan['project_sha256'])
            self.check('startup task copy SHA', _sha(self.startup) == self.plan['project_sha256'])
            self.check('original media bytes match', _sha(self.plan['media_path']) == self.plan['media_sha256'])
            self.check('plan carries full32 cues and31 ASR count', len(self.plan['expected_cues']) == 32
                and self.plan['asr_segment_count'] == 31)
            self.result.update(plan_sha256=_sha(output/'review-plan.json'), project_id=self.plan['project_id'],
                source_project_id=self.plan['source_project_id'], media_path=self.plan['media_path'],
                media_sha256=self.plan['media_sha256'], project_before_sha256=self.plan['project_sha256'],
                layer_provenance=self.plan.get('layer_provenance'), pending_reviews=self.plan.get('pending_reviews'))
            self.source = source
            # The startup and prepared task copy remain immutable. Only this
            # additional private working copy receives the real UI save.
            working = output/'runtime-reviewed.2byteproj'
            working.write_bytes(self.startup.read_bytes())
            self.phase = 'open-real-copy'
            window.open_studio_project(working, mode='edit', source='overlap-review-real')
            yield lambda: self.ready() and Path(self.page.project_path).resolve() == working
            yield .3
            self.validate_project(self.page.project, 'loaded')
            self.check('source sequence identity', sequence_of(self.page.project).is_identity())
            self.check('source full media timeline', timeline_duration_ms(self.page.project) == self.page.project.media.duration_ms)
            window.showNormal()
            window.resize(1200,820)
            window.raise_()
            window.activateWindow()
            self.page.volume_slider.setValue(0)
            self.page.video.set_paused(True)
            self.page._set_review_mode(False)
            self.page.select_cue(None)
            self.page.position_edit_button.setChecked(False)
            yield lambda: self.page.video.controller.observed_property('pause', None) is True
            yield .5
            self.shot('overlap-review-opened')
            for point in self.plan['timepoints']:
                milliseconds = point['timeline_ms']
                self.phase = 'seek-'+str(milliseconds)
                self.seek_ui(milliseconds)
                yield lambda point=point: self.visible_ready(point)
                yield .3
                self.check('exact active runtime IDs '+str(milliseconds),
                    {c.id for c in self.page.session.runtime.cues_at(milliseconds)} == set(point['expected_active_cue_ids']))
                visible = active_cues(self.page, milliseconds)
                self.check('exact production scene input IDs '+str(milliseconds),
                    {c.id for c in visible} == set(point['expected_active_cue_ids']))
                self.check('actual active texts '+str(milliseconds), {c.id:c.text for c in visible} == point['expected_texts'])
                trace = self.page.subtitle_visibility_trace(reason='overlap_review_measured_seek')
                self.check('settled renderer still exact '+str(milliseconds), self.visible_ready(point), trace)
                if len(point['expected_active_cue_ids']) > 1:
                    self.check('all overlapping cue pixels rendered '+str(milliseconds),
                        set(trace.get('rendered_cue_ids', ())) == set(point['expected_active_cue_ids'])
                        and trace.get('visible') is True, trace)
                controller = self.page.video.controller
                diagnostics = controller.subtitle_diagnostics()
                for name in ('time-pos','video-pts','pause','sub-visibility','vo'):
                    try:
                        diagnostics[name] = controller.get_property(name)
                    except RuntimeError as exc:
                        diagnostics[name] = {'unavailable': type(exc).__name__, 'detail': str(exc)}
                mpv = output/(f'seek-{milliseconds}-mpv.png')
                controller.screenshot_to_file(mpv, mode='window')
                yield lambda mpv=mpv: mpv.is_file() and mpv.stat().st_size > 0
                yield .1
                image = QImage(str(mpv))
                self.check('actual mpv composed image decoded '+str(milliseconds), not image.isNull())
                self.result['screenshots'].append({'path':str(mpv),'method':'mpv window video/subtitle/bitmap',
                    'sha256':_sha(mpv),'size':[image.width(),image.height()]})
                self.shot(f'seek-{milliseconds}-hwnd')
                self.result['timepoints'].append({'requested':point,'measured_timeline_ms':self.page.timeline.playhead_ms,
                    'caption_sample_ms':self.page._caption_sample_ms(), 'visibility':trace,
                    'mpv':diagnostics,'mpv_image':str(mpv)})
                ass = Path(diagnostics.get('studio_subtitle_path') or '')
                if ass.is_file():
                    (output/f'seek-{milliseconds}-production.ass').write_bytes(ass.read_bytes())

            self.phase = 'manual-protection'
            protected_id = self.plan['human_cue_ids'][0]
            cue = next(c for c in self.page.project.cues if c.id == protected_id)
            self.check('human guarded source differs from final', bool(cue.original_text) and cue.original_text != cue.text)
            protected_text = cue.text
            for origin in (MutationOrigin.LLM, MutationOrigin.ASR):
                command = SetCueFieldsCommand(self.page.project, cue.id, {'text':cue.original_text},
                    'Existing raw text protection probe', changed=self.page._changed, origin=origin)
                command.redo()
                self.check(origin.value+' cannot overwrite existing USER_EDIT', cue.text == protected_text)
            self.validate_project(self.page.project, 'after-protection')
            self.phase = 'save-reopen'
            save_before_mtime_ns = working.stat().st_mtime_ns
            QTest.mouseClick(self.page.save_button, Qt.LeftButton)
            yield .3
            self.check('actual UI save wrote private working file', working.stat().st_mtime_ns > save_before_mtime_ns)
            reopened = load_project(working)
            self.validate_project(reopened, 'saved-file')
            self.result['saved_project'] = str(working)
            self.result['saved_project_sha256'] = _sha(working)
            window.open_studio_project(working, mode='edit', source='overlap-review-reopen')
            yield lambda: self.ready() and Path(self.page.project_path).resolve() == working
            yield .3
            self.check('reopened current Studio page ownership', self.page is window.studio_page)
            self.validate_project(self.page.project, 'fresh-Studio-reopen')
            self.phase = 'reopen-pause'
            self.page.volume_slider.setValue(0)
            self.page.video.set_paused(True)
            self.page._set_review_mode(False)
            self.page.select_cue(None)
            self.page.position_edit_button.setChecked(False)
            yield lambda: self.page.video.controller.observed_property('pause', None) is True
            yield .2
            self.phase = 'reopen-seek-12450'
            self.seek_ui(12450)
            yield lambda: self.visible_ready(self.plan['timepoints'][2])
            yield .2
            self.shot('overlap-review-saved-reopened')
            self.phase = 'production-five-SRT'
            artifacts = export_subtitle_artifacts(reopened, output/'exports', self.plan['export_base_name'],
                SubtitleExportOptions(frozenset({'srt'}), 'both'))
            self.check('exact combined and4 speaker SRT', len(artifacts) == 5)
            projected = projected_cues(reopened, domain='timeline')
            for artifact in artifacts:
                ordered = sorted([c for c in projected if not artifact.speaker_id or c.speaker_id == artifact.speaker_id],
                    key=lambda c:(c.start_ms,c.end_ms,c.id))
                expected = copy.copy(reopened)
                expected.cues = ordered
                verification = verify_subtitle_artifact(artifact, expected)
                self.check('parser-backed production SRT '+artifact.path.name, verification.valid)
                blocks = [b for b in artifact.path.read_text('utf8').strip().split('\n\n') if b]
                texts = ['\n'.join(b.splitlines()[2:]) for b in blocks]
                self.check('exact saved text projection '+artifact.path.name, texts == [c.text for c in ordered])
                self.check('artifact cue count '+artifact.path.name, artifact.cue_count == len(ordered))
                if artifact.speaker_id:
                    suffix = artifact.path.stem.rsplit('_', 1)[-1]
                    self.check('per-file speaker count '+artifact.path.name,
                        artifact.cue_count == self.plan['expected_export_counts'].get(suffix))
                self.result['exports'].append({'path':str(artifact.path),'sha256':_sha(artifact.path),
                    'speaker_id':artifact.speaker_id,'cue_count':artifact.cue_count})
            self.check('combined count32', sum(x['cue_count'] for x in self.result['exports'] if not x['speaker_id']) == 32)
            self.check('speaker partition count32', sum(x['cue_count'] for x in self.result['exports'] if x['speaker_id']) == 32)
            self.check('per-speaker cardinality matches plan',
                sorted(x['cue_count'] for x in self.result['exports'] if x['speaker_id'])
                == sorted(v for k,v in self.plan['expected_export_counts'].items() if k != 'combined'))
            self.check('immutable startup copy preserved', _sha(self.startup) == self.plan['project_sha256'])
            self.check('immutable prepared copy preserved', _sha(self.source) == self.plan['project_sha256'])
            from . import blank_project_audit
            self.result['provider_calls_attempted'] = blank_project_audit._provider_calls
            self.result['external_connections_blocked'] = list(blank_project_audit._blocked_external_connections)
            self.check('no model requests attempted', self.result['provider_calls_attempted'] == 0)
            self.check('no external connections attempted', not self.result['external_connections_blocked'])

        def finish(self):
            self.timer.stop()
            self.bind_page()
            self.page._studio_trace = self.original_trace
            self.result['last_phase'] = self.phase
            (output/'production-visibility-events.json').write_text(json.dumps(self.events, ensure_ascii=False,
                indent=2, default=str), encoding='utf8')
            target = output/'overlap-review-result.json'
            def write():
                target.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            write()
            def stopped():
                self.result['gui_shutdown'] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.page.undo_stack.setClean()
            window.close()

    window._overlap_review_real_audit = Audit()
