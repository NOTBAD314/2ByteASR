import os
import copy

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia, StudioCue,
    StudioSpeaker, save_project, load_project)
from twobyteasr.projects.range_speakers import (register_range_speakers, orphan_range_speakers)
from twobyteasr.recognition.range_recognition import (RangePayload, splice_range, apply_plan, history_entry)
from twobyteasr.timeline.range_replace import ReplaceRangeCuesCommand
from twobyteasr.timeline.speaker_cleanup import CleanRangeSpeakersCommand

APP = QApplication.instance() or QApplication([])


def project():
    p = SubtitleProject(StudioMedia('', duration_ms=10000),
        speakers=[StudioSpeaker('HOST', '手动人物')], cues=[StudioCue('old', 1000, 3000, '人工正文', 'HOST')])
    p.validate()
    return p


def payload(task, *, start=1200, end=2500):
    return RangePayload(1000, 3000, cues=[StudioCue(task + '-cue', start, end, '新正文', 'S00')],
                        speakers=[StudioSpeaker('S00', 'S00')], speaker_scope=task)


def test_five_replacements_retire_previous_automatic_roster_and_undo_redo(tmp_path):
    p = project()
    stack = QUndoStack()
    for index in range(5):
        before = copy.deepcopy(p.speakers)
        plan = splice_range(p, (1000, 3000), payload('range-task' + str(index)), foreign_speakers=True)
        stack.push(ReplaceRangeCuesCommand(p, plan, history_entry(plan)))
        assert len(p.speakers) == 2
        assert orphan_range_speakers(p) == []
        stack.undo()
        assert p.speakers == before
        stack.redo()
        assert len(p.speakers) == 2
    path = save_project(p, tmp_path / 'clean.2byteproj')
    reopened = load_project(path)
    assert reopened.speakers == p.speakers
    assert [(c.id, c.text, c.speaker_id) for c in reopened.cues] == [(c.id, c.text, c.speaker_id) for c in p.cues]


def test_cropped_and_empty_payload_cannot_delete_old_cues_or_add_speakers():
    p = project()
    for incoming in (payload('outside', start=4000, end=5000), RangePayload(1000, 3000)):
        plan = splice_range(p, (1000, 3000), incoming, foreign_speakers=True)
        before = copy.deepcopy(p.cues)
        assert plan.inserted_ids == [] and plan.removed_ids == [] and plan.extra_speakers == []
        assert apply_plan(p, plan) is False
        assert p.cues == before and len(p.speakers) == 1


def test_speakers_are_allocated_only_for_accepted_cues():
    p = project()
    incoming = payload('task')
    incoming.cues.append(StudioCue('discard', 4000, 5000, '范围外', 'S01'))
    incoming.speakers.append(StudioSpeaker('S01'))
    plan = splice_range(p, (1000, 3000), incoming, foreign_speakers=True)
    assert len(plan.extra_speakers) == 1 and set(plan.speaker_map) == {'S00'}


def test_worker_delivery_is_idempotent_even_when_plan_is_rebuilt():
    p = project()
    incoming = payload('range-task')
    first = splice_range(p, (1000, 3000), incoming, foreign_speakers=True)
    apply_plan(p, first, history_entry(first))
    before = (copy.deepcopy(p.cues), copy.deepcopy(p.speakers))
    again = splice_range(p, (1000, 3000), incoming, foreign_speakers=True)
    assert again.result_key == first.result_key
    assert apply_plan(p, again, history_entry(again)) is False
    assert (p.cues, p.speakers) == before


def test_cleanup_preserves_live_hidden_and_manual_people_and_is_reversible(tmp_path):
    p = project()
    auto = StudioSpeaker('range-old-S00', '局部识别 · S00（待确认）')
    custom = StudioSpeaker('range-custom-S00', '局部识别 · S00（待确认）')
    hidden = StudioSpeaker('range-hidden-S00', '局部识别 · S00（待确认）')
    manual = StudioSpeaker('manual', '手动空人物')
    p.speakers.extend([auto, custom, hidden, manual])
    register_range_speakers(p, [auto, custom, hidden])
    custom.name, custom.color = '用户命名', '#123456'
    hidden.hidden = True
    p.cues.append(StudioCue('hidden', 4000, 5000, '隐藏轨有效字幕', hidden.id))
    p.studio_state['speaker_track_order'] = [s.id for s in p.speakers]
    p.studio_state['speaker_roles'] = {'auto': {auto.id: 'secondary'}, 'manual': {custom.id: 'own'}}
    before = copy.deepcopy(p.speakers)
    stack = QUndoStack()
    stack.push(CleanRangeSpeakersCommand(p))
    assert {s.id for s in p.speakers} == {'HOST', custom.id, hidden.id, manual.id}
    assert auto.id not in p.studio_state['speaker_track_order']
    stack.undo()
    assert p.speakers == before and auto.id in p.studio_state['speaker_track_order']
    stack.redo()
    assert auto.id not in {s.id for s in load_project(save_project(p, tmp_path / 'old.2byteproj')).speakers}


def test_legacy_cleanup_requires_history_and_unchanged_default_configuration():
    p = project()
    orphan = StudioSpeaker('range-abc-S00', '局部识别 · S00（待确认）')
    unproven = StudioSpeaker('range-abc-S01', '局部识别 · S01（待确认）')
    p.speakers.extend([orphan, unproven])
    p.generation_metadata['range_recognitions'] = [{'speaker_map': {'S00': orphan.id}}]
    assert orphan_range_speakers(p) == [orphan.id]
    orphan.color = '#123456'
    assert orphan_range_speakers(p) == []


def test_user_confirmed_role_and_voiceprint_target_remain_even_when_empty():
    p = project()
    main = StudioSpeaker('range-main-S00', '局部识别 · S00（待确认）')
    voice = StudioSpeaker('range-voice-S00', '局部识别 · S00（待确认）')
    p.speakers.extend([main, voice])
    register_range_speakers(p, [main, voice])
    p.generation_metadata['speaker_organization'] = {'decisions': {main.id: 'main'}}
    p.generation_metadata['speaker_recovery'] = {
        'voiceprint_review': {'reviewed_by': 'user', 'members': {voice.id: [voice.id]}}}
    assert orphan_range_speakers(p) == []


def test_gui_duplicate_and_out_of_order_deliveries_do_not_replace_twice(tmp_path, monkeypatch):
    from tests.test_studio_range_recognition import _page, _plan_from_result
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _plan = _plan_from_result(page.project, tmp_path)
    _, older, _ = _plan_from_result(page.project, tmp_path)
    path = save_project(result, tmp_path / 'new.2byteproj')
    older_path = save_project(older, tmp_path / 'older.2byteproj')
    try:
        assert page.apply_range_recognition_result(str(path), snapshot)
        before = copy.deepcopy(page.project.cues)
        roster = copy.deepcopy(page.project.speakers)
        assert not page.apply_range_recognition_result(str(path), snapshot)
        assert not page.apply_range_recognition_result(str(older_path), snapshot)
        assert page.project.cues == before and page.project.speakers == roster
        assert page.undo_stack.count() == 1
    finally:
        page.close_page()


def test_gui_final_zero_selected_captions_and_wrong_window_preserve_project(tmp_path, monkeypatch):
    from tests.test_studio_range_recognition import _page, _plan_from_result
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _plan = _plan_from_result(page.project, tmp_path)
    before = copy.deepcopy(page.project.cues)
    try:
        info = result.generation_metadata['timeline_recognition']['range']
        info['cue_ids'] = []
        path = save_project(result, tmp_path / 'empty-selection.2byteproj')
        assert not page.apply_range_recognition_result(str(path), snapshot)
        info['window_ms'] = [0, 1000]
        path = save_project(result, tmp_path / 'wrong-window.2byteproj')
        assert not page.apply_range_recognition_result(str(path), snapshot)
        assert page.project.cues == before and page.undo_stack.count() == 0
    finally:
        page.close_page()


def test_confirmation_replans_from_latest_outside_edits(tmp_path, monkeypatch):
    from tests.test_studio_range_recognition import _page, _plan_from_result
    from twobyteasr.studio import studio_range_recognition
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _ = _plan_from_result(page.project, tmp_path)
    page.project.cues[1].text = '识别期间手动修改'
    def confirm(_page):
        page.project.cues[0].text = '确认期间区间外的新编辑'
        page.project.generation_metadata['translations'] = {'a': 'new outside translation'}
        return True
    monkeypatch.setattr(studio_range_recognition, 'ask_replace_edited', confirm)
    try:
        path = save_project(result, tmp_path / 'confirm.2byteproj')
        assert page.apply_range_recognition_result(str(path), snapshot)
        assert page.project.cues[0].text == '确认期间区间外的新编辑'
        assert page.project.generation_metadata['translations']['a'] == 'new outside translation'
    finally:
        page.close_page()


def test_failed_transaction_restores_all_data_and_does_not_enter_undo_history(monkeypatch):
    from twobyteasr.recognition import speech_recovery_project
    p = project()
    before = copy.deepcopy(p.to_dict())
    plan = splice_range(p, (1000, 3000), payload('range-failed'), foreign_speakers=True)
    def fail(project, _plan):
        project.generation_metadata['partial_failure'] = True
        raise ValueError('injected range commit failure')
    monkeypatch.setattr(speech_recovery_project, 'merge_project_range', fail)
    command = ReplaceRangeCuesCommand(p, plan, history_entry(plan))
    outcome = command.outcome
    stack = QUndoStack()
    stack.push(command)
    assert not outcome['applied'] and 'injected' in outcome['error']
    assert stack.count() == 0 and p.to_dict() == before


def test_translation_completed_during_recognition_is_confirmed_before_replacement(tmp_path, monkeypatch):
    from tests.test_studio_range_recognition import _page, _plan_from_result
    from twobyteasr.studio import studio_range_recognition
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _ = _plan_from_result(page.project, tmp_path)
    page.project.generation_metadata['translations'] = {'b': '新手动译文'}
    asked = []
    monkeypatch.setattr(studio_range_recognition, 'ask_replace_edited', lambda _page: asked.append(True) or False)
    try:
        path = save_project(result, tmp_path / 'translated.2byteproj')
        assert not page.apply_range_recognition_result(str(path), snapshot)
        assert asked == [True] and page.project.generation_metadata['translations']['b'] == '新手动译文'
        assert page.undo_stack.count() == 0
    finally:
        page.close_page()


def test_open_split_draft_cannot_be_spliced_under_the_editor(tmp_path, monkeypatch):
    from tests.test_studio_range_recognition import _page, _plan_from_result
    page = _page(tmp_path, monkeypatch)
    snapshot, result, _ = _plan_from_result(page.project, tmp_path)
    page.project._caption_preview_active = True
    before = copy.deepcopy(page.project.cues)
    try:
        path = save_project(result, tmp_path / 'draft.2byteproj')
        assert not page.apply_range_recognition_result(str(path), snapshot)
        assert page.project.cues == before and page.undo_stack.count() == 0
    finally:
        page.project._caption_preview_active = False
        page.close_page()
