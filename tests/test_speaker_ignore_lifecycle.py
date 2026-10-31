"""Role transactions must not serialize media/evidence inside native input."""
from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker
from twobyteasr.recognition.speaker_recovery import apply_candidate_role, load_candidate_snapshot, candidate_snapshot
from twobyteasr.studio.studio_speaker_manager import SpeakerManagerDialog
from twobyteasr.timeline.studio_commands import SetCandidateRoleCommand

APP = QApplication.instance() or QApplication([])


def _anonymous_project():
    cues = [StudioCue(str(i), i*2000, i*2000+1000, '保留字幕', speaker_id='API_S0'+str(i%3+1)) for i in range(6)]
    project = SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=13000), cues=cues,
        speakers=[StudioSpeaker('API_S0'+str(i), name='S'+str(i)) for i in range(1, 4)])
    project.generation_metadata['speaker_recovery'] = candidate_snapshot([
        dict(speaker=c.speaker_id, start=c.start_ms/1000, end=c.end_ms/1000, text=c.text) for c in cues], source='filetrans')
    project.generation_metadata['speaker_recovery']['allow_raw_recovery'] = False
    return project


def _page(project):
    page = QWidget()
    page.project = project
    page.undo_stack = QUndoStack(page)
    page._speaker_roles_pending = False
    page._populate_speakers = page._speaker_structure_changed = lambda: None
    page.selected_cue_ids = lambda: []
    page.video = SimpleNamespace(controller=None)
    page.speed_box = SimpleNamespace(currentData=lambda: 1.)
    page._seek = page._set_speed = lambda value: None
    page._open_recognition_sheet = lambda: None
    return page


def test_role_does_not_serialize_live_document_and_undo_preserves_other_evidence(monkeypatch):
    project = _anonymous_project()
    project.asr_evidence['unrelated'] = {'text': '保留证据'}
    project.generation_metadata['unrelated'] = {'manual': True}
    original = [(c.id, c.text, c.speaker_id) for c in project.cues]
    evidence = project.asr_evidence
    def forbidden():
        raise AssertionError('role operation serialized the entire document')
    monkeypatch.setattr(project, 'to_dict', forbidden)
    recovered = apply_candidate_role(project, load_candidate_snapshot(project), 'API_S03', 'ignore')
    assert [(c.id, c.text, c.speaker_id) for c in project.cues] == original
    assert recovered.asr_evidence is evidence
    page = _page(project)
    command = SetCandidateRoleCommand(project, recovered, page._speaker_structure_changed)
    page.undo_stack.push(command)
    assert not command.error and all(c.speaker_id != 'API_S03' for c in project.cues)
    project.generation_metadata['unrelated']['new'] = '后续变更'
    page.undo_stack.undo()
    assert [(c.id, c.text, c.speaker_id) for c in project.cues] == original
    assert project.asr_evidence['unrelated'] == {'text': '保留证据'}
    assert project.generation_metadata['unrelated']['new'] == '后续变更'
    page.undo_stack.redo()
    assert not command.error
    page.deleteLater()


def test_click_is_queued_and_close_commits_pending_role_once():
    page = _page(_anonymous_project())
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    QApplication.processEvents()
    index = page.undo_stack.index()
    dialog.cards['API_S03'].roles.buttons['ignore'].click()
    assert page.undo_stack.index() == index
    dialog.close()
    QApplication.processEvents()
    assert page.undo_stack.index() == index + 1
    assert page.project.generation_metadata['speaker_recovery']['roles']['API_S03'] == 'ignore'
    page.undo_stack.undo()
    assert len(page.project.cues) == 6
    page.deleteLater()


def test_pending_role_cannot_write_into_another_project():
    page = _page(_anonymous_project())
    dialog = SpeakerManagerDialog(page)
    dialog.show()
    QApplication.processEvents()
    dialog.cards['API_S03'].roles.buttons['ignore'].click()
    replacement = _anonymous_project()
    page.project = replacement
    QTest.qWait(30)
    assert replacement.generation_metadata['speaker_recovery']['roles']['API_S03'] == 'unconfirmed'
    assert page.undo_stack.index() == 0
    dialog.close()
    page.deleteLater()


def test_undoing_automatic_default_survives_refresh_and_can_be_redone():
    from twobyteasr.projects.low_share_speakers import apply_low_share_policy
    project = _anonymous_project()
    # This tests the automatic command's explicit opt-out independently from
    # the already tested threshold policy.
    recovered = apply_candidate_role(project, load_candidate_snapshot(project), 'API_S03', 'ignore', decision_source='low_share')
    recovered.generation_metadata.setdefault('speaker_organization', {})['low_share_policy'] = {
        'version': 'low-share-speakers-v1', 'ignored': {'API_S03': {'cues': 2}}}
    page = _page(project)
    page.undo_stack.push(SetCandidateRoleCommand(project, recovered, automatic=True, undo_stack=page.undo_stack))
    page.undo_stack.undo()
    QTest.qWait(10)
    assert len(project.cues) == 6 and not page.undo_stack.isClean()
    assert apply_low_share_policy(project) is None
    page.undo_stack.redo()
    assert len(project.cues) == 4
    page.deleteLater()
