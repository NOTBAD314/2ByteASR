"""Exercise the normal Studio review and speaker board on an isolated project."""

import copy
import json
from dataclasses import replace
from time import perf_counter


def run(window, page, output, check, wait):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QTimer
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication
    from ..exports.studio_subtitle_export import _compile_format
    from ..projects.speaker_organization import CATEGORIES
    from ..projects.studio_project import StudioSpeaker, load_project, save_project
    from ..projects.studio_runtime_state import state_for
    from ..recognition.independent_review import firered_readings
    from ..studio.studio_speaker_board import SPEAKER_MIME
    from ..studio.studio_speaker_manager import SpeakerManagerDialog
    from ..subtitle_rules.current_issues import current_issue_view

    project = page.project
    wait(lambda: getattr(project, '_qc_result', None) is not None)
    view = current_issue_view(project)
    historical = [row for row in view.records if row.kind == 'segmentation_fallback']
    check('reported project opens with 710 captions', len(project.cues) == 710)
    check('all 44 fallback windows appear as separate issues',
          len(historical) == 44 and len({row.issue_id for row in historical}) == 44
          and {row.disposition for row in historical} == {'actionable'}
          and len({key for row in historical for key in row.cue_ids}) == 90)
    check('known adjacent errors point to both captions',
          all(any(row.kind == 'segmentation_semantic' and row.cue_ids == pair for row in view.records)
              for pair in [('16', '17'), ('20', '21'), ('30', '31')]))
    check('VAD and forced alignment do not impersonate independent recognition',
          firered_readings(project, project.cues[15])[0][1] == 'disabled')
    page.select_cue('16')
    page.grab().save(str(output/'review.png'))
    (output/'review-counts.json').write_text(json.dumps(dict(
        totals=view.totals(), counts=view.counts(), breakdown=view.statistics()), indent=2), 'utf-8')
    fixture = output/'speaker-work.2byteproj'
    editable = copy.deepcopy(project)
    editable.speakers = [StudioSpeaker(f'audit-{i}', f'说话人 {i+1}') for i in range(4)]
    editable.cues = [replace(cue, speaker_id=f'audit-{i%4}') for i, cue in enumerate(editable.cues)]
    save_project(editable, fixture)
    window.open_studio_project(str(fixture), source='subtitle_evidence_acceptance')
    wait(lambda: page.project is not project and page.project is not None and page._readiness.ready
         and not window._studio_loading_session.active)
    project = page.project
    wait(lambda: getattr(project, '_qc_result', None) is not None)
    board = SpeakerManagerDialog(page)
    board.show()
    wait(board.isVisible)
    app = QApplication.instance()
    state = state_for(project)
    metrics = {}
    hooks = {}
    counters = {}
    for owner, name in ((page, '_schedule_autosave'), (page, '_populate_speakers'), (page.cue_model, 'refresh')):
        original = getattr(owner, name)
        counters[name] = 0
        hooks[(owner, name)] = original

        def count(*args, key=name, callback=original, **kwargs):
            counters[key] += 1
            return callback(*args, **kwargs)

        setattr(owner, name, count)

    def drop(keys, kind, target=None):
        box = board.boxes[kind]
        if target:
            box._hover_tile = board.tiles[target]
        mime = QMimeData()
        mime.setData(SPEAKER_MIME, '\n'.join(keys).encode())
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        box.dropEvent(event)
        return event.isAccepted()

    def operation(name, function):
        before = dict(counters)
        revision = state.revision
        started = perf_counter()
        function()
        wait(lambda: state.revision != revision)
        metrics[name] = dict(ms=round((perf_counter()-started)*1000, 2), commits=state.revision-revision,
                             **{key: counters[key]-before[key] for key in counters})

    original = [(cue.id, cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in project.cues]
    evidence = project.asr_evidence
    history_source = copy.deepcopy(project.studio_state['ai_sentence_refine']['historical_windows'])
    try:
        operation('game', lambda: (drop(['audit-1', 'audit-2'], 'game'),
                                   drop(['audit-1', 'audit-2'], 'game')))
        check('quick repeated game drop commits once with original identities',
              metrics['game']['commits'] == 1 and metrics['game']['_schedule_autosave'] == 1
              and project.studio_state[CATEGORIES] == {'audit-1': 'game', 'audit-2': 'game'}
              and [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues] == original)
        board.grab().save(str(output/'speaker-board.png'))
        operation('game_out', lambda: drop(['audit-1', 'audit-2'], 'main'))
        check('drag out restores category and keeps speaker IDs', not project.studio_state[CATEGORIES]
              and [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues] == original)
        operation('merge', lambda: (drop(['audit-1', 'audit-2'], 'main', 'audit-0'),
                                    drop(['audit-1', 'audit-2'], 'main', 'audit-0')))
        check('speaker merge sends one commit and one save schedule', metrics['merge']['commits'] == 1
              and metrics['merge']['_schedule_autosave'] == 1 and metrics['merge']['_populate_speakers'] == 1)
        check('merge retains text, times, ASR evidence and historical windows',
              [(c.id, c.text, c.start_ms, c.end_ms) for c in project.cues] == [row[:4] for row in original]
              and project.asr_evidence is evidence
              and project.studio_state['ai_sentence_refine']['historical_windows'] == history_source)
        page.undo_stack.undo()
        check('one undo restores all speaker assignments',
              [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in project.cues] == original)
        page.undo_stack.redo()
        expected = [(c.id, c.speaker_id) for c in project.cues]
        index = page.undo_stack.index()
        drop(['audit-3'], 'game')
        board.close()
        app.processEvents()
        check('closing the speaker window discards a queued drop', page.undo_stack.index() == index)
        saved = []
        page.project_controller.save(on_finished=lambda path, error: saved.append((path, error)))
        wait(lambda: bool(saved))
        check('formal save finished', saved[0][1] is None)
        loaded = load_project(saved[0][0])
        check('saved project reopens with identical assignments and history',
              [(c.id, c.speaker_id) for c in loaded.cues] == expected
              and loaded.studio_state['ai_sentence_refine']['historical_windows'] == history_source
              and loaded.asr_evidence == evidence)
        (output/'reopened.srt').write_text(_compile_format(loaded, 'srt'), 'utf-8')
        timer = QTimer(page)
        timer.setSingleShot(True)
        timer.start(0)
        wait(lambda: not timer.isActive())
    finally:
        board.close()
        for (owner, name), original_callback in hooks.items():
            setattr(owner, name, original_callback)
        (output/'speaker-metrics.json').write_text(json.dumps(metrics, indent=2), 'utf-8')
