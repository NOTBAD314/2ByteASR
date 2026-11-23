"""兔白处理 on the completion page (2026-11-21, design 乙1): routing, fixes on a
copy, byte-exact backup/restore, single-change undo and cancellation."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from twobyteasr.app import completion_ai_repair as repair
from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                                load_project, save_project)
from twobyteasr.recognition import speech_coverage as coverage
from twobyteasr.recognition.current_review import current_review
from twobyteasr.recognition.speech_recovery_project import project_ranges


def _project():
    p = SubtitleProject(StudioMedia('fixture.wav', duration_ms=60000), speakers=[StudioSpeaker('s')])
    p.cues = [
        StudioCue('short', 1000, 1200, '好的', speaker_id='s'),                       # 0.2 s, room after
        StudioCue('boxed-prev', 2000, 2960, '前面那条字幕', speaker_id='s'),
        StudioCue('boxed', 3000, 3300, '对对', speaker_id='s'),                        # boxed in
        StudioCue('boxed-next', 3340, 5000, '后面那条字幕', speaker_id='s'),
        StudioCue('fast', 8000, 9000, '这一条字幕的字非常非常多读不完', speaker_id='s'),  # room after
        StudioCue('text', 14000, 16000, '我们去打末影龙', speaker_id='s'),
        StudioCue('tail', 30000, 32000, '最后一条字幕', speaker_id='s'),
    ]
    p.generation_metadata['language'] = {'code': 'zh'}
    p.generation_metadata['speaker_recovery'] = {'roles': {'s': 'unconfirmed'}}
    state = coverage.make_state([dict(start=20, end=22), dict(start=24, end=26), dict(start=40, end=42)],
                                [], duration=60)
    p.generation_metadata[coverage.KEY] = state
    report = dict(job_id='job', status='success', review_items=[
        dict(category='多模型争议', severity='review', cue_id='text', text='我们去打末影龙', timestamp=14.0),
        dict(category='说话人需要确认', severity='review', cue_id='tail', text='最后一条字幕', timestamp=30.0)])
    return p, report


@pytest.fixture
def saved(tmp_path, monkeypatch):
    p, report = _project()
    path = save_project(p, tmp_path / 'task.2byteproj')
    monkeypatch.setattr(repair, 'text_ai_ready', lambda settings, stage='polish': True)
    monkeypatch.setattr(repair, 'speech_backend', lambda settings: ('local', '本机测试模型'))
    monkeypatch.setattr(repair, 'backup_root', lambda: tmp_path / 'backups')
    from twobyteasr.subtitle_rules import studio_qc
    monkeypatch.setattr(studio_qc, 'review_candidates', lambda project, cue: (
        studio_qc.QCCandidate(cue.text, ('current',)), studio_qc.QCCandidate('我们去打末影龙', ('moss',)),
        studio_qc.QCCandidate('我们去打末地龙', ('firered',))) if cue.id == 'text' else ())
    return path, report


def _ask(answers):
    calls = []

    def ask(system, payload, *, stage, max_tokens, cancelled):
        calls.append(payload)
        items = payload['items']
        if 'candidates' in items[0]:
            return json.dumps({'results': [dict(id=row['id'], choice=answers.get('text', -1)) for row in items]})
        return json.dumps({'results': [dict(id=row['id'], **answers['speech'](row)) for row in items]})
    ask.calls = calls
    return ask


def _plan(path, report):
    return repair.plan_repair(load_project(path), report, path, settings={'models': {}})


def test_plan_routes_each_item_kind_and_estimates_without_requests_for_local_fixes(saved):
    path, report = saved
    plan = _plan(path, report)
    counts = {item.key: item.count for item in plan.categories}
    assert counts['short'] == 2 and counts['fast'] == 1 and counts['text'] == 1
    assert counts['speech'] == 3 and counts['speaker'] == 1
    assert not plan.category('speaker').automatic
    local = plan.estimate({'short', 'fast'})
    assert local.requests == 0 and local.cost_text() == '不花钱'
    assert plan.estimate().requests >= 2


def test_local_timing_extends_into_free_space_and_explains_boxed_captions(saved):
    path, report = saved
    plan = _plan(path, report)
    result = repair.run_repair(plan, {'short', 'fast'})
    cues = {cue.id: cue for cue in result.project.cues}
    assert cues['short'].end_ms - cues['short'].start_ms >= 600
    assert cues['fast'].end_ms > 9000 and cues['fast'].end_ms <= cues['text'].start_ms - repair.GAP_MS
    short = result.categories['short']
    assert short.fixed == 1 and short.left == 1 and '没有空档' in short.reasons[0][1]
    assert result.requests == 0
    # The copy changed; the file did not.
    assert load_project(path).cues[0].end_ms == 1200


def test_text_choice_writes_only_a_listed_reading_and_kept_items_leave_the_list(saved):
    path, report = saved
    plan = _plan(path, report)
    result = repair.run_repair(plan, {'text'}, ask=_ask({'text': 0}))
    assert next(c for c in result.project.cues if c.id == 'text').text == '我们去打末地龙'
    record = repair.commit_repair(plan, result, approved_text_ids=repair.text_change_ids(result))
    reopened = load_project(path)
    assert not [row for row in current_review(reopened, report)['items'] if row['category'] == '多模型争议']
    assert record['categories']['text']['fixed'] == 1


def test_text_answer_outside_the_candidates_is_left_for_a_person(saved):
    path, report = saved
    result = repair.run_repair(_plan(path, report), {'text'}, ask=_ask({'text': 7}))
    assert next(c for c in result.project.cues if c.id == 'text').text == '我们去打末影龙'
    assert result.categories['text'].left == 1


def test_speech_heard_again_inserts_real_lines_and_records_non_speech(saved):
    path, report = saved
    plan = _plan(path, report)
    heard = {20: '这里有一句真台词', 24: '', 40: '谢谢观看'}

    def transcribe(clip, regions, backend):
        assert backend == 'local'
        return [dict(text=heard[round(region['start'] + start)]) for region in regions
                for start in [transcribe.window_start]]

    def clip(runner, project, start_ms, end_ms, path):
        transcribe.window_start = start_ms / 1000
        path.write_bytes(b'RIFF' + b'\0' * 60)
    repair_clip = repair._clip
    repair._clip = clip
    try:
        ask = _ask({'speech': lambda row: dict(verdict='speech', text=row['heard'])})
        result = repair.run_repair(plan, {'speech'}, ask=ask, transcribe=transcribe)
    finally:
        repair._clip = repair_clip
    speech = result.categories['speech']
    assert speech.fixed == 3 and speech.left == 0
    inserted = [c for c in result.project.cues if c.id.startswith('ai-')]
    assert [c.text for c in inserted] == ['这里有一句真台词']
    assert 20000 <= inserted[0].start_ms < inserted[0].end_ms <= 22000
    # Only the real line went to the text AI; empty and 谢谢观看 were decided locally.
    assert len(ask.calls) == 1 and len(ask.calls[0]['items']) == 1
    before = path.read_bytes()
    with pytest.raises(ValueError, match='採用'):
        repair.commit_repair(plan, result)
    assert path.read_bytes() == before
    repair.commit_repair(plan, result, approved_text_ids=repair.text_change_ids(result))
    assert not project_ranges(load_project(path))


def test_backup_restores_the_exact_original_bytes(saved):
    path, report = saved
    original = path.read_bytes()
    plan = _plan(path, report)
    record = repair.commit_repair(plan, repair.run_repair(plan, {'short', 'fast'}))
    assert path.read_bytes() != original
    loaded = repair.read_record(path)
    assert loaded and not repair.edited_since(loaded)
    repair.restore_before_repair(loaded)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()
    assert record['backup_sha256'] == hashlib.sha256(original).hexdigest()


def test_failed_undo_record_write_does_not_replace_project(saved, monkeypatch):
    path, report = saved
    before = path.read_bytes()
    plan = _plan(path, report)
    result = repair.run_repair(plan, {'short'})

    def fail_record(*args):
        raise OSError('storage unavailable')

    monkeypatch.setattr(repair, '_write_record', fail_record)
    with pytest.raises(OSError, match='storage unavailable'):
        repair.commit_repair(plan, result)
    assert path.read_bytes() == before


def test_empty_or_unmapped_transcription_keeps_review_ranges(saved, monkeypatch):
    path, report = saved
    monkeypatch.setattr(repair, '_clip', lambda runner, project, a, b, clip: None)
    result = repair.run_repair(_plan(path, report), {'speech'}, ask=_ask({}),
                               transcribe=lambda clip, regions, backend: (
                                   [dict(text='unmapped')] if len(regions) > 1 else []))
    assert result.categories['speech'].fixed == 0
    assert result.categories['speech'].left == 3
    assert len({row['id'] for row in project_ranges(result.project)}) == 3


def test_partial_undo_keeps_full_restore_warning_after_an_unrelated_edit(saved):
    path, report = saved
    plan = _plan(path, report)
    repair.commit_repair(plan, repair.run_repair(plan, {'short'}))
    project = load_project(path)
    project.cues[-1].text = '后来手动改的字幕'
    save_project(project, path)
    record = repair.read_record(path)
    assert repair.set_change_undone(record, record['changes'][0]['change_id'], True)
    assert load_project(path).cues[-1].text == '后来手动改的字幕'
    assert repair.edited_since(repair.read_record(path))


def test_completion_repair_does_not_write_behind_open_editor(saved):
    from types import SimpleNamespace
    from PySide6.QtCore import QObject
    from twobyteasr.app.completion_ai_repair_ui import RepairController

    path, report = saved

    class Window(QObject):
        def built_page(self, name):
            return SimpleNamespace(project_path=path)

    window = Window()
    controller = RepairController(window)
    controller.plan = _plan(path, report)
    assert controller.blocked_reason()


def test_single_change_undo_and_redo_respect_later_edits(saved):
    path, report = saved
    plan = _plan(path, report)
    repair.commit_repair(plan, repair.run_repair(plan, {'short'}))
    record = repair.read_record(path)
    change = next(row for row in record['changes'] if row['category'] == 'short')
    assert repair.set_change_undone(record, change['change_id'], True)
    assert load_project(path).cues[0].end_ms == 1200
    assert repair.set_change_undone(record, change['change_id'], False)
    assert load_project(path).cues[0].end_ms > 1200
    # A caption edited after 兔白 is never overwritten by an undo.
    project = load_project(path)
    project.cues[0].text = '人工改过'
    save_project(project, path)
    assert not repair.set_change_undone(repair.read_record(path), change['change_id'], True)
    assert load_project(path).cues[0].text == '人工改过'


def test_speech_decision_undo_brings_the_range_back(saved):
    path, report = saved
    plan = _plan(path, report)
    repair_clip = repair._clip
    repair._clip = lambda runner, project, a, b, clip: clip.write_bytes(b'RIFF' + b'\0' * 60)
    try:
        result = repair.run_repair(plan, {'speech'}, ask=_ask({}),
                                   transcribe=lambda clip, regions, backend: [dict(text='') for _ in regions])
    finally:
        repair._clip = repair_clip
    repair.commit_repair(plan, result)
    assert not project_ranges(load_project(path))
    record = repair.read_record(path)
    first = record['changes'][0]
    assert repair.set_change_undone(record, first['change_id'], True)
    assert len({row['id'] for row in project_ranges(load_project(path))}) == 1


def test_cancel_writes_nothing_and_a_changed_file_is_not_overwritten(saved):
    path, report = saved
    original = path.read_bytes()
    plan = _plan(path, report)
    with pytest.raises(repair.RepairCancelled):
        repair.run_repair(plan, {'short', 'fast'}, cancelled=lambda: True)
    assert path.read_bytes() == original
    result = repair.run_repair(plan, {'short'})
    project = load_project(path)
    project.cues[-1].text = '处理期间在工作台改的'
    save_project(project, path)
    with pytest.raises(ValueError):
        repair.commit_repair(plan, result)
    assert load_project(path).cues[-1].text == '处理期间在工作台改的'


def test_stage_proposals_are_written_directly(saved, monkeypatch):
    path, report = saved
    project = load_project(path)
    unit = dict(key='job:polish:1', job_id='job', project_id=str(project.project_id), stage='polish',
                status='failed', retryable=True, cue_ids=['tail'], original_ids=['1'],
                input=dict(parts=[]))
    plan = repair.plan_repair(project, report, path, settings={'models': {}})
    from twobyteasr.app.completion_ai_repair import Category
    plan.categories.insert(0, Category('stage', rows=[unit]))

    def execute(project, report, unit, cancelled):
        return dict(unit, status='proposals_pending', proposals=[dict(
            cue_id='tail', start_ms=30000, original='最后一条字幕', replacement='最后一条字幕！', span=(0, 6))],
            pending_projection=[])
    result = repair.run_repair(plan, {'stage'}, stage_execute=execute)
    assert next(c for c in result.project.cues if c.id == 'tail').text == '最后一条字幕！'
    assert result.categories['stage'].fixed == 1
    ledger = result.project.generation_metadata['processing_recovery']['units']['job:polish:1']
    assert ledger['status'] == 'applied'


def _rejected_fixture(tmp_path, monkeypatch):
    """Two refused AI edits on one caption; only one has a second source."""
    p, report = _project()
    p.cues.append(StudioCue('seg', 44000, 47000, '接破命运的少雨天', speaker_id='s', evidence_refs=['segment:9']))
    p.asr_evidence['segment:9'] = dict(start_ms=44000, end_ms=47000, text='接破命运的少雨天',
        caption_arbitration={'processing_identity': {'polish_record_id': 77}})
    report['events'] = [dict(event='terminology_polish_final', cue_id=77, details=dict(rejected_edits=[
        dict(**{'from': '接破命运', 'to': '揭破秘密'}, start=0, end=4, rule_id='whole_sentence_safety'),
        dict(**{'from': '少雨', 'to': '少有'}, start=5, end=7, rule_id='local_difference_without_two_sources'),
        dict(**{'from': '不存在', 'to': '别的'}, start=0, end=3, rule_id='source_quote_not_found')]))]
    path = save_project(p, tmp_path / 'rejected.2byteproj')
    from twobyteasr.subtitle_rules import studio_qc
    monkeypatch.setattr(studio_qc, 'review_candidates', lambda project, cue: (
        studio_qc.QCCandidate('揭破秘密的少雨天', ('firered',)),) if cue.id == 'seg' else ())
    return path, report


def test_rejected_suggestions_apply_only_with_a_second_source(saved, tmp_path, monkeypatch):
    path, report = _rejected_fixture(tmp_path, monkeypatch)
    plan = _plan(path, report)
    rows = plan.category('rejected').rows
    assert [(row['source'], row['target']) for row in rows] == [('接破命运', '揭破秘密'), ('少雨', '少有')]

    def ask(system, payload, *, stage, max_tokens, cancelled):
        assert all('reason' in row and 'target' in row for row in payload['items'])
        return json.dumps({'results': [dict(id=row['id'], decision='apply') for row in payload['items']]})
    result = repair.run_repair(plan, {'rejected'}, ask=ask)
    seg = next(c for c in result.project.cues if c.id == 'seg')
    # 揭破秘密 has FireRed's reading behind it; 少有 has only the AI.
    assert seg.text == '揭破秘密的少雨天'
    done = result.categories['rejected']
    assert done.fixed == 1 and done.left == 1 and '只有 AI' in done.reasons[0][1]
    before = path.read_bytes()
    with pytest.raises(ValueError, match='採用'):
        repair.commit_repair(plan, result)
    assert path.read_bytes() == before
    repair.commit_repair(plan, result, approved_text_ids=repair.text_change_ids(result))
    again = repair.plan_repair(load_project(path), report, path, settings={'models': {}})
    assert [row['target'] for row in again.category('rejected').rows] == ['少有']
    record = repair.read_record(path)
    change = next(row for row in record['changes'] if row['category'] == 'rejected')
    assert repair.set_change_undone(record, change['change_id'], True)
    reopened = load_project(path)
    assert next(c for c in reopened.cues if c.id == 'seg').text == '接破命运的少雨天'
    assert len(repair.rejected_rows(reopened, report)) == 2


def test_rejected_keep_is_remembered_without_touching_text(saved, tmp_path, monkeypatch):
    path, report = _rejected_fixture(tmp_path, monkeypatch)
    plan = _plan(path, report)
    ask = lambda system, payload, **_: json.dumps({'results': [dict(id=row['id'], decision='keep')
                                                               for row in payload['items']]})
    result = repair.run_repair(plan, {'rejected'}, ask=ask)
    assert next(c for c in result.project.cues if c.id == 'seg').text == '接破命运的少雨天'
    assert result.categories['rejected'].fixed == 2
    repair.commit_repair(plan, result)
    reopened = load_project(path)
    assert not repair.rejected_rows(reopened, report)
    assert repair.handled_rejected_count(reopened, report) == 2
    assert repair.handled_rejected_count(reopened, {'events': []}) == 0


def test_rejected_current_text_and_partial_glossary_match_do_not_count(saved, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.subtitle_rules import studio_qc

    path, report = _rejected_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(studio_qc, 'review_candidates', lambda project, cue: (
        studio_qc.QCCandidate('接破命运的少雨天（少有）', ('Current',)),
        studio_qc.QCCandidate('少有', ('FireRed',), context_only=True),
    ))
    monkeypatch.setattr(studio_qc, 'terminology_from_project', lambda project: (
        SimpleNamespace(canonical='少有的日子'),
    ))

    def ask(system, payload, **kwargs):
        return json.dumps({'results': [dict(id=row['id'], decision='apply') for row in payload['items']]})

    result = repair.run_repair(_plan(path, report), {'rejected'}, ask=ask)
    assert result.categories['rejected'].fixed == 0
    assert result.categories['rejected'].left == 2
    assert next(c.text for c in result.project.cues if c.id == 'seg') == '接破命运的少雨天'
