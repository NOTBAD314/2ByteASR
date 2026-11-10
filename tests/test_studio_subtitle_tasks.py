"""Real Studio application paths with deterministic, offline task results."""

import copy
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
from twobyteasr.subtitle_rules.sentence_refine_ranges import input_version


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path, monkeypatch):
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    p = SubtitleProject(media=StudioMedia(path=str(tmp_path / 'fixture.mp4'), duration_ms=5000),
        cues=[StudioCue('a', 0, 4000, '今天天气很好我们继续出发', evidence_refs=['e'],
                        transform={'x': 4}, appearance_override={'font_size': 44})],
        asr_evidence={'e': {'words': [
            {'text': '今天天气很好', 'start_ms': 0, 'end_ms': 1800},
            {'text': '我们继续出发', 'start_ms': 2100, 'end_ms': 4000}]}})
    p.generation_metadata['language'] = {'code': 'zh'}
    path = tmp_path / 'fixture.2byteproj'
    save_project(p, path)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, 'load', lambda *args, **kwargs: None)
    monkeypatch.setattr(page, '_generate_waveform', lambda *args, **kwargs: None)
    page.open_project(path)
    monkeypatch.setattr(page, '_refine_configuration', lambda: {'model': 'fixture'})
    yield page
    worker = getattr(page, '_refine_worker', None)
    if worker and worker.isRunning():
        worker.requestInterruption()
        worker.wait(5000)
    page.close_page()


def outcome_for(page, monkeypatch):
    def complete(messages, **kwargs):
        request = json.loads(messages[-1]['content'])
        return json.dumps({'results': [{'cue_id': request['cues'][0]['cue_id'], 'action': 'split',
                                      'split_after_chars': [5]}]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
        lambda *args, **kwargs: SimpleNamespace(complete=complete))
    cues = copy.deepcopy(page.project.cues)
    outcome = refine_cues_with_llm(cues, project=copy.deepcopy(page.project),
                                  runtime_settings={'models': {'group_model': 'fixture'}}, boundary_only=True)
    task = page._new_subtitle_task('AI 断句', cues)
    page._refine_task = task
    return cues, outcome, task


def test_real_commit_is_one_undo_keeps_metadata_and_saves(page, monkeypatch, tmp_path):
    before = copy.deepcopy(page.project.cues)
    cues, outcome, task = outcome_for(page, monkeypatch)
    assert outcome.llm_status == 'completed'
    old_count = page.undo_stack.count()
    page._apply_sentence_refine(outcome, cues, task=task)
    assert [cue.text for cue in page.project.cues] == ['今天天气很好', '我们继续出发']
    assert page.project.cues[0].end_ms == 1800 and page.project.cues[1].start_ms == 2100
    assert all(cue.transform == before[0].transform for cue in page.project.cues)
    assert all(cue.appearance_override == before[0].appearance_override for cue in page.project.cues)
    assert task.counts()['applied'] == 1 and task.counts()['total'] == 1
    assert page.undo_stack.count() == old_count + 1
    page.undo_stack.undo()
    assert page.project.cues == before
    page.undo_stack.redo()
    saved = tmp_path / 'after.2byteproj'
    save_project(page.project, saved)
    assert load_project(saved).cues == page.project.cues


@pytest.mark.parametrize('change', ['edit', 'style', 'switch', 'cancel', 'new_task', 'configuration', 'language'])
def test_late_results_cannot_overwrite_current_content(page, monkeypatch, change):
    cues, outcome, task = outcome_for(page, monkeypatch)
    if change == 'edit':
        page.project.cues[0].text = '用户新文本'
    elif change == 'style':
        page.project.cues[0].transform['x'] = 50
    elif change == 'switch':
        page.project = SubtitleProject(media=StudioMedia(path='other'), cues=[StudioCue('other', 0, 1000, '另一工程')])
    elif change == 'cancel':
        page._cancel_subtitle_task(task.task_id)
    elif change == 'configuration':
        task.configuration = page._refine_configuration()
        monkeypatch.setattr(page, '_refine_configuration', lambda: {'model': 'new-model'})
    elif change == 'language':
        page.project.generation_metadata['language'] = {'code': 'ja'}
    else:
        page._refine_task = page._new_subtitle_task('AI 断句', page.project.cues)
    expected = copy.deepcopy(page.project.cues)
    page._apply_sentence_refine(outcome, cues, task=task)
    assert page.project.cues == expected
    assert task.counts()['applied'] == 0


def test_panel_collapse_reopen_and_progress_never_moves_selection(page, monkeypatch):
    cues, outcome, task = outcome_for(page, monkeypatch)
    before = page.selected_cue_id
    page.show_subtitle_tasks()
    panel = page._subtitle_task_panel()
    task.update(dict(range_id='a', cue_ids=['a'], phase='等待模型返回', status='running', start_ms=0, end_ms=4000))
    panel.refresh()
    assert panel.table.model().rowCount() == 1 and panel.isVisible()
    assert page.selected_cue_id == before
    playhead = page.timeline.playhead_ms
    panel.hide()
    page._apply_sentence_refine(outcome, cues, task=task)
    page.show_subtitle_tasks()
    panel.refresh()
    assert task.counts()['applied'] == 1 and '1/1' in panel.summary.text()
    assert page.timeline.playhead_ms == playhead
    assert page.selected_cue_id in {cue.id for cue in page.project.cues}


def test_processed_cache_invalidates_after_edit_model_or_undo(page, monkeypatch):
    cues, outcome, task = outcome_for(page, monkeypatch)
    page._apply_sentence_refine(outcome, cues, task=task)
    assert page._collect_refine_scope(True) == []
    page.project.cues[0].text += '新'
    assert len(page._collect_refine_scope(True)) == 1
    monkeypatch.setattr(page, '_refine_configuration', lambda: {'model': 'changed'})
    assert len(page._collect_refine_scope(True)) == 2
    page.undo_stack.undo()
    assert page._collect_refine_scope(True)


def test_local_reasr_late_suggestion_is_guarded(page):
    from twobyteasr.studio.studio_reasr import LocalReASRResult
    cue = page.project.cues[0]
    task = page._new_subtitle_task('单条重新识别', [cue])
    task.cue_id = cue.id
    task.input_version = input_version([cue], page.project)
    page._reasr_task = task
    task.update(dict(range_id=cue.id, cue_ids=[cue.id], status='running'))
    result = LocalReASRResult(cue.id, cue.text, '', '新建议', (), '新建议', 'fixture', task.task_id)
    cue.text = '已编辑'
    page._reasr_ready(result)
    assert task.counts()['failed'] == 1 and cue.text == '已编辑'


def test_duplicate_start_uses_one_background_job(page, monkeypatch):
    calls = []
    def complete(messages, **kwargs):
        calls.append(1)
        time.sleep(.1)
        request = json.loads(messages[-1]['content'])
        return json.dumps({'results': [{'cue_id': row['cue_id'], 'action': 'keep'} for row in request['cues']]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
        lambda *args, **kwargs: SimpleNamespace(complete=complete))
    monkeypatch.setattr('twobyteasr.providers.llm_config.text_ai_key_missing', lambda *args: False)
    page.run_sentence_refine(whole_project=True)
    first = page._refine_task
    page.run_sentence_refine(whole_project=True)
    assert first is page._refine_task
    deadline = time.monotonic() + 5
    while first.ended is None and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    assert first.ended is not None and len(calls) == 1 and first.counts()['unchanged'] == 1


def test_split_translation_keeps_estimates_provenance_and_undo_retains_it(page, monkeypatch):
    from twobyteasr.subtitle_rules.subtitle_translation import set_manual, records_of, split_merge_candidates
    set_manual(page.project, 'a', '天气很好，我们继续出发。')
    records = copy.deepcopy(records_of(page.project))
    cues, outcome, task = outcome_for(page, monkeypatch)
    page._apply_sentence_refine(outcome, cues, task=task)
    split_records = records_of(page.project)
    assert all(split_records[cue.id]['split_estimate'] for cue in page.project.cues)
    assert all(split_records[cue.id]['split_from']['cue_id'] == 'a' for cue in page.project.cues)
    page.undo_stack.undo()
    assert page.project.cues[0].id == 'a' and records_of(page.project) == records


def test_saved_result_reopens_in_task_panel(page, monkeypatch):
    cues, outcome, task = outcome_for(page, monkeypatch)
    page._apply_sentence_refine(outcome, cues, task=task)
    page._subtitle_tasks = {}
    page._subtitle_tasks_dialog = None
    page.show_subtitle_tasks()
    restored = page._subtitle_task_panel().current
    assert restored.ended is not None and restored.counts()['applied'] == 1


def test_whole_recognition_uses_actual_phases_and_cancelled_progress(page):
    page._recognition_running = True
    page._recognition_subtitle_task = None
    page.set_recognition_runtime_stage('准备当前时间轴音频', '真实阶段')
    task = page._recognition_subtitle_task
    assert task.phase == '准备当前时间轴音频' and task.counts()['processed'] == 0
    page._cancel_subtitle_task(task.task_id)
    page.finish_recognition_runtime(1.)
    assert task.counts()['cancelled'] == 1 and task.counts()['processed'] == 0


def test_whole_recognition_local_fallback_remains_reviewable(page):
    page._recognition_running = True
    page._recognition_subtitle_task = None
    page.set_recognition_runtime_stage('模型返回后校验', '')
    task = page._recognition_subtitle_task
    page._record_recognition_task_event('grouping_api_fallback', {'reason': '断点校验失败，采用保留范围'})
    page.finish_recognition_runtime(1.)
    assert task.counts()['review'] == 1 and task.counts()['suggestion'] == 0
    assert task.rows['source']['error'] and task.unit_label == '个输入范围'


def test_grouping_progress_and_unchanged_retry_do_not_claim_improvement(page):
    page._recognition_running=True
    page._recognition_subtitle_task=None
    page.set_recognition_runtime_stage('断句：模型处理','')
    task=page._recognition_subtitle_task
    for label in ('断句：本地断点检查','断句：局部重试未变化','断句：最终字幕验证'):
        page._record_recognition_task_event('pipeline_work_progress',dict(label=label,state='completed'))
        assert task.phase==label
    page._record_recognition_task_event('grouping_quality_retry',dict(outcome='unchanged',improved=False))
    assert task.rows['source']['activity']['grouping_quality_retry']['improved'] is False
    page._finish_recognition_subtitle_task('suggestion','结果已交付')
    page._recognition_running=False


def test_untrusted_alignment_is_visible_as_review_without_losing_successful_work(page):
    page._recognition_running=True
    page._recognition_subtitle_task=None
    page.set_recognition_runtime_stage('FireRed 时间证据','')
    task=page._recognition_subtitle_task
    page._record_recognition_task_event('FIRERED_ALIGNMENT_STATUS',dict(status='degraded',counts={'aligned':9,'failed_or_unavailable':1}))
    page._finish_recognition_subtitle_task('suggestion','结果已交付')
    assert task.counts()['review']==1
    assert task.rows['source']['issues'][-1]['counts']['aligned']==9
    page._recognition_running=False


def test_writeback_failure_has_no_success_count(page, monkeypatch):
    cues, outcome, task = outcome_for(page, monkeypatch)
    before = copy.deepcopy(page.project.cues)
    def fail(*args, **kwargs):
        raise ValueError('模拟写回校验失败')
    monkeypatch.setattr('twobyteasr.timeline.sentence_refine_command.RefineCuesCommand', fail)
    page._apply_sentence_refine(outcome, cues, task=task)
    assert page.project.cues == before and task.counts()['failed'] == 1 and task.counts()['applied'] == 0
