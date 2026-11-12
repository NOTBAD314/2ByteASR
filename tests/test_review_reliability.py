"""Offline regressions for ownership, persistence and actual task state."""
import copy
from types import SimpleNamespace

import pytest
from pathlib import Path
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QHBoxLayout

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project, load_project
from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses
from twobyteasr.recognition import speech_coverage as coverage
from twobyteasr.recognition.speech_recovery_project import project_ranges
from twobyteasr.subtitle_rules.studio_qc import review_candidates
from twobyteasr.subtitle_rules.studio_review import store_review_risks
from twobyteasr.subtitle_rules.current_issues import current_issue_view
from twobyteasr.subtitle_rules.review_suggestions import model_suggestions
from twobyteasr.timeline.studio_commands import AdoptReviewCandidateCommand
from twobyteasr.timeline.speech_gap_commands import ConfirmNoSpeechCommand


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def overlapping(reading='散手了对吧', text='你毕竟你已经亮过三手了对吧'):
    a = StudioCue('long', 1000, 4300, text, 'A', evidence_refs=['a'])
    b = StudioCue('reply', 2600, 3300, '对对对', 'B', evidence_refs=['b'])
    p = SubtitleProject(media=StudioMedia('', duration_ms=6000),
        speakers=[StudioSpeaker('A'), StudioSpeaker('B')], cues=[a, b])
    p.asr_evidence = {
        'a': dict(start_ms=a.start_ms, end_ms=a.end_ms, speaker_id='A', moss_text=a.text),
        'b': dict(start_ms=b.start_ms, end_ms=b.end_ms, speaker_id='B', moss_text=b.text,
                  firered_text=reading, firered_start=2.6, firered_end=3.3)}
    return p, a, b


def test_half_sentence_moves_to_long_speaker_without_replacing_reply():
    p, a, b = overlapping()
    raw = copy.deepcopy(p.asr_evidence)
    assert not [r for r in cue_source_hypotheses(p, b) if r['model'] == 'firered' and not r.get('context_only')]
    candidate, = [r for r in cue_source_hypotheses(p, a) if r['model'] == 'firered']
    assert candidate['observed_text'] == '散手了对吧'
    assert candidate['text'] == '你毕竟你已经亮过散手了对吧'
    assert candidate['candidate_partial']
    store_review_risks(p)
    assert any(r.kind == 'local_model_correction' for r in current_issue_view(p).for_cue(a.id))
    assert not any(r.kind == 'model_disagreement' for r in current_issue_view(p).for_cue(b.id))
    assert p.asr_evidence == raw


def test_latest_actual_project_overlapping_receipts():
    p = load_project(Path(__file__).parent/'fixtures/latest_overlap_candidate.json')
    store_review_risks(p)
    a = next(c for c in p.cues if c.id == '2000035')
    b = next(c for c in p.cues if c.id == '2000036')
    candidates = review_candidates(p, a)
    assert any(c.text == '你毕竟你已经亮过散手了对吧' for c in candidates), (
        candidates, cue_source_hypotheses(p, a))
    assert not any(c.text == '散手了对吧' and not c.context_only for c in review_candidates(p, b))
    assert not any(r.kind in {'model_disagreement','local_model_correction','candidate_ownership'}
                   for r in current_issue_view(p).for_cue(b.id))


def test_confirmation_survives_same_evidence_and_reopens_for_new_evidence(tmp_path):
    from twobyteasr.subtitle_rules.current_issues import DECISIONS
    p, a, _ = overlapping()
    store_review_risks(p)
    issue = next(r for r in current_issue_view(p).for_cue(a.id) if r.kind == 'local_model_correction')
    p.studio_state[DECISIONS] = {issue.issue_id: dict(status='resolved', input_version=issue.input_version,
                                                    evidence_version=issue.evidence_version)}
    path=tmp_path/'confirmed.2byteproj'
    save_project(p,path)
    p=load_project(path)
    store_review_risks(p)
    assert not any(r.kind=='local_model_correction' for r in current_issue_view(p).for_cue(a.id))
    p.asr_evidence['b']['firered_text']='四手了对吧'
    store_review_risks(p)
    assert any(r.kind=='local_model_correction' for r in current_issue_view(p).for_cue(a.id))


def test_local_adoption_undo_redo_and_save_reopen(tmp_path):
    p, a, b = overlapping()
    candidate = next(c for c in review_candidates(p, a) if 'FireRed' in c.sources)
    mark, = model_suggestions(a.text, [(candidate.text, candidate.sources)])
    assert mark.original == '三' and mark.options[0].text == '散'
    before = (a.start_ms, a.end_ms, a.speaker_id, b.text)
    stack = QUndoStack()
    stack.push(AdoptReviewCandidateCommand(p, a.id, mark.apply(a.text), 'fixture'))
    assert a.text == '你毕竟你已经亮过散手了对吧'
    assert before == (a.start_ms, a.end_ms, a.speaker_id, b.text)
    store_review_risks(p)
    assert not any(r.kind == 'local_model_correction' for r in current_issue_view(p).for_cue(a.id))
    stack.undo()
    assert a.text == '你毕竟你已经亮过三手了对吧'
    stack.redo()
    path = tmp_path/'owned.2byteproj'
    save_project(p, path)
    loaded = load_project(path)
    store_review_risks(loaded)
    assert not any(r.kind == 'local_model_correction' for r in current_issue_view(loaded).for_cue(a.id))


def test_ambiguous_candidate_retains_range_and_context_without_replacement():
    p, a, b = overlapping('回答完全不同')
    store_review_risks(p)
    for cue in (a, b):
        candidates = [r for r in cue_source_hypotheses(p, cue) if r.get('candidate_id')]
        assert candidates and all(r['context_only'] for r in candidates)
        assert candidates[0]['original_start_ms'] == 2600
        assert set(candidates[0]['related_references']) == {'a', 'b'}
        view = current_issue_view(p)
        assert not any(r.kind=='candidate_ownership' for r in view.for_cue(cue.id))
        assert any(r.kind=='candidate_ownership' and not r.suggestions
                   for r in view.diagnostics.get(cue.id,()))
        assert not any(r.kind == 'model_disagreement' for r in view.for_cue(cue.id))


@pytest.mark.parametrize('text,reading', [('前半句保持后面火龙出现了', '后面火笼出现了'),
                                         ('今天我们准备去山顶看看', '山底看看')])
def test_mapping_uses_generic_local_anchors(text, reading):
    p, a, _ = overlapping(reading, text)
    candidate = next(r for r in cue_source_hypotheses(p, a) if r.get('candidate_id'))
    assert candidate['candidate_partial'] and candidate['text'].startswith(text[:3])


def test_one_source_candidate_projects_to_multiple_final_cues():
    p, a, _ = overlapping('你毕竟你已经亮过散手了对吧')
    a.text = '你毕竟你已经亮过'
    tail = StudioCue('tail', 3000, 4300, '三手了对吧', 'A', evidence_refs=['a'])
    p.cues.append(tail)
    first = next(r for r in cue_source_hypotheses(p, a) if r.get('candidate_id'))
    second = next(r for r in cue_source_hypotheses(p, tail) if r.get('candidate_id'))
    assert first['text'] == a.text and second['text'] == '散手了对吧'


def test_spaced_language_partial_candidate_keeps_word_spacing():
    p, a, _ = overlapping('starting the gate now', 'we are starting the game now')
    candidate = next(r for r in cue_source_hypotheses(p, a) if r.get('candidate_id'))
    assert candidate['text'] == 'we are starting the gate now'


def gap_project():
    p = SubtitleProject(media=StudioMedia('fixture.wav', duration_ms=60000))
    p.generation_metadata[coverage.KEY] = coverage.make_state([
        dict(start=10, end=20, detector='firered_vad', confidence=.99),
        dict(start=30, end=35, detector='energy', confidence=.2)], [], duration=60, identity='audio')
    return p


def test_high_vad_probability_alone_requires_listening():
    p = gap_project()
    assert all(r['status'] == 'needs_confirmation' for r in project_ranges(p))
    assert coverage.counts(p.generation_metadata[coverage.KEY]) == dict(
        speech_gap_count=0, speech_failure_count=0, speech_confirmation_count=2)


def test_batch_no_speech_decisions_persist_and_undo(tmp_path):
    p = gap_project()
    raw = copy.deepcopy(p.generation_metadata[coverage.KEY]['gaps'])
    stack = QUndoStack()
    stack.push(ConfirmNoSpeechCommand(p, [r['id'] for r in project_ranges(p)]))
    assert not project_ranges(p)
    assert p.generation_metadata[coverage.KEY]['gaps'] == raw
    path = tmp_path/'silent.2byteproj'
    save_project(p, path)
    assert not project_ranges(load_project(path))
    p.generation_metadata[coverage.KEY]['execution_identity'] = {'model': 'another-model'}
    assert not project_ranges(p)
    stack.undo()
    assert len(project_ranges(p)) == 2
    stack.redo()
    assert not project_ranges(p)
    p.generation_metadata[coverage.KEY]['identity'] = 'changed-audio'
    assert len(project_ranges(p)) == 2


def test_failure_without_vad_remains_failure_and_empty_success_stops_retry():
    failed = coverage.make_state([], [], duration=30, windows=[
        dict(start=0, end=30, error='decoder failed', complete=False)])
    gap, = failed['gaps']
    assert gap['classification'] == 'processing_failure'
    assert 'decoder failed' in str(gap['processing_errors'])
    reliable = coverage.make_state([dict(start=0, end=30, speech_verified=True)], [], duration=30)
    calls = []
    for _ in range(2):
        coverage.recover(reliable, [], lambda *args: calls.append(args) or [], source='test')
    assert len(calls) == 1 and reliable['gaps'][0]['status'] == 'needs_confirmation'


def test_successful_empty_range_retry_does_not_become_a_processing_failure():
    from twobyteasr.recognition.speech_recovery_project import failed_range_attempt
    p = gap_project()
    assert failed_range_attempt(p, (10_000,20_000), 'no_usable_captions')
    assert all(r['classification'] == 'uncertain_speech' for r in project_ranges(p))
    assert not coverage.counts(p.generation_metadata[coverage.KEY])['speech_failure_count']


def test_gap_listening_remains_in_menu_without_creating_status_widgets():
    from PySide6.QtWidgets import QMenu
    from twobyteasr.studio.speech_recovery_ui import add_actions
    page=SimpleNamespace(project=gap_project())
    before=copy.deepcopy(page.project.generation_metadata)
    menu=QMenu()
    add_actions(page,menu)
    assert [a.objectName() for a in menu.actions()]==['speechRecoveryAction']
    assert len(project_ranges(page.project))==2
    assert page.project.generation_metadata==before
    assert not menu.findChildren(QLabel)
    menu.close()


def test_cancellation_marks_only_the_current_recognition_task():
    from twobyteasr.studio.studio_media_flow import StudioMediaFlowMixin
    project = gap_project()
    task = SimpleNamespace(project=project, cancelled=False)
    page = SimpleNamespace(project=project, _recognition_subtitle_task=task,
                           _recognition_show_status=lambda *args: None)
    StudioMediaFlowMixin.set_recognition_cancelling(page)
    assert task.cancelled and page._recognition_cancelling
    task.cancelled = False
    page.project = gap_project()
    StudioMediaFlowMixin.set_recognition_cancelling(page)
    assert not task.cancelled


@pytest.mark.parametrize('key', ['_cancelled_job_ids', '_committed_job_ids'])
def test_late_events_are_rejected_before_touching_page(key):
    from twobyteasr.app.ui import MainWindow
    owner = SimpleNamespace(_active_job_id='job', **{key: {'job'}})
    MainWindow._handle_event(owner, SimpleNamespace(job_id='job', kind='cue_delta'))
