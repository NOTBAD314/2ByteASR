"""Scoped completion retry uses Qt workers and bound Studio proposals offline."""
from __future__ import annotations

import copy
import os
import threading
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QWidget

from twobyteasr.app import completion_retry, completion_retry_ui
from twobyteasr.app.completion_retry_ui import CompletionRetryThread
from twobyteasr.recognition.service import MediaResult, RunOptions
from twobyteasr.glossary.studio_glossary_service import GlossaryReviewPreview
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_text_tools import TextOccurrence
from twobyteasr.app.ui import MainWindow

APP = QApplication.instance() or QApplication([])


def sample_project():
    project = SubtitleProject(media=StudioMedia(path='isolated-source.mp4', duration_ms=1000),
        cues=[StudioCue('final-2', 0, 1000, '原处理文字', speaker_id='S01', evidence_refs=['segment:7'])],
        asr_evidence={'segment:7': {'text': '原处理文字', 'start_ms': 0, 'end_ms': 1000}},
        glossary_ids=['original-library'])
    # Production completion opens a loaded/validated project; establish the
    # same media graph before capturing the immutable preview fingerprint.
    project.validate()
    return project


def sample_preview(stage='polish'):
    return GlossaryReviewPreview((TextOccurrence('final-2', 0, '原处理文字', '重试建议文字',
        (0, len('原处理文字')), reason='未核验原音'),),
        {'job_id': 'retry-child', 'kind': 'failed_stage_retry', 'stage': stage,
         'scope_ids': [7], 'successful_ids': [7], 'failed_ids': [], 'pending_projection': [],
         'asr_run': False, 'audio_verified': False, 'user_project_or_glossary_saved': False})


@pytest.fixture
def page(monkeypatch):
    import subtitle_core
    from twobyteasr.projects import studio_project
    widget = QWidget()
    widget.session = SimpleNamespace(project=sample_project(), undo_stack=QUndoStack(widget))
    widget.selected_cue_ids = lambda: ['final-2']
    widget.select_cue = lambda cue_id: None
    widget._changed = lambda: None
    widget._show_studio_hint = lambda message: None
    monkeypatch.setattr(subtitle_core, 'glossary_catalog', lambda: [])
    monkeypatch.setattr(studio_project, 'save_project', lambda *a, **k: pytest.fail('retry review saved a project'))
    yield widget
    widget.deleteLater()
    APP.processEvents()


def drive_dialog(monkeypatch, inspect, *, begin=None):
    """Run production queued slots in the GUI loop, without an interactive modal."""
    from twobyteasr.studio.studio_find_replace import FindReplaceDialog
    observed = {}
    def exec_dialog(dialog):
        loop = QEventLoop()
        errors = []
        worker = dialog._glossary_review_worker
        observed['dialog'] = dialog
        observed['worker'] = worker
        def finish():
            observed['finished'] = True
            try:
                inspect(dialog)
                observed['finished'] = True
            except BaseException as exc:
                errors.append(exc)
            finally:
                loop.quit()
        # The wrapper's ready/finished slots are already connected. Delay one
        # event turn so their queued GUI work is complete before inspecting.
        worker.finished.connect(lambda: QTimer.singleShot(0, finish))
        timer = QTimer(dialog)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(3000)
        if begin:
            begin(dialog)
        loop.exec()
        timer.stop()
        if not observed.get('finished'):
            worker.token.cancel()
            assert worker.wait(2000), 'retry worker did not finish after cancellation'
            raise AssertionError('retry dialog did not deliver its terminal signal')
        if errors:
            raise errors[0]
        return 0
    monkeypatch.setattr(FindReplaceDialog, 'exec', exec_dialog)
    return observed


def test_real_qthread_copies_report_delivers_ready_off_gui_thread(monkeypatch):
    project, report = sample_project(), {'started_at': 'selected-report', 'scope': [7]}
    options = RunOptions(settings_snapshot_json='{"case":"original-snapshot"}')
    result, calls = sample_preview(), []
    def preview(p, r, o, **kwargs):
        calls.append((p, r, o, kwargs['stage'], QThread.currentThread() == APP.thread()))
        assert kwargs['cancel_token'] is worker.token
        return result
    monkeypatch.setattr(completion_retry, 'completion_retry_preview', preview)
    worker = CompletionRetryThread(project, report, options, 'polish')
    ready, failed = QSignalSpy(worker.ready), QSignalSpy(worker.failed)
    report['scope'].append(31)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    watchdog.start(3000)
    worker.start()
    loop.exec()
    watchdog.stop()
    assert worker.wait(2000)
    assert ready.count() == 1 and failed.count() == 0
    assert ready.at(0)[0] is result
    assert calls[0][1]['scope'] == [7] and calls[0][2] is options and calls[0][3:] == ('polish', False)
    worker.deleteLater()


def test_real_qthread_cancel_suppresses_late_ready(monkeypatch):
    entered = threading.Event()
    def preview(*args, cancel_token, **kwargs):
        entered.set()
        assert cancel_token._event.wait(2), 'test did not cancel the in-flight retry'
        return sample_preview()
    monkeypatch.setattr(completion_retry, 'completion_retry_preview', preview)
    worker = CompletionRetryThread(sample_project(), {}, RunOptions(), 'polish')
    ready, failed = QSignalSpy(worker.ready), QSignalSpy(worker.failed)
    worker.start()
    assert entered.wait(2)
    worker.token.cancel()
    assert failed.wait(3000) or failed.count() == 1
    assert worker.wait(2000) and ready.count() == 0 and failed.count() == 1
    assert '取消' in failed.at(0)[0]
    worker.deleteLater()


def test_dialog_binds_copied_project_applies_receipt_once_and_undoes(page, monkeypatch):
    project = page.session.project
    before = copy.deepcopy((project.asr_evidence, project.cues[0].__dict__))
    result = sample_preview()
    seen = []
    def preview(p, report, options, **kwargs):
        seen.append((p, report, options, kwargs['stage']))
        return result
    monkeypatch.setattr(completion_retry, 'completion_retry_preview', preview)
    def inspect(dialog):
        assert QThread.currentThread() == APP.thread()
        assert dialog._preview_binding.matches(project)
        assert dialog._glossary_review_receipt == result.receipt
        assert dialog.preview.count() == 1 and dialog.all_button.isEnabled()
        assert project.cues[0].text == '原处理文字'
        # A scoped retry cannot change into a manual learning or unrelated AI
        # tool while delivering/applying these suggestions.
        assert dialog.tabs.currentIndex() == 3
        assert not dialog.tabs.tabBar().isEnabled() or all(not dialog.tabs.isTabEnabled(i) for i in (0, 1, 2))
        assert not dialog.ai_run_button.isEnabled()
        dialog._do_apply_preview()
        assert project.cues[0].text == '重试建议文字'
        assert project.generation_metadata['glossary_review_jobs'][0]['job_id'] == 'retry-child'
        assert project.generation_metadata['glossary_review_jobs'][0]['applied_cue_ids'] == ['final-2']
        assert project.asr_evidence == before[0] and project.glossary_ids == ['original-library']
        assert page.session.undo_stack.count() == 1
        page.session.undo_stack.undo()
        assert project.cues[0].__dict__ == before[1] and not project.generation_metadata.get('glossary_review_jobs')
    observed = drive_dialog(monkeypatch, inspect)
    options = RunOptions(settings_snapshot_json='{"case":"original"}')
    receipt = completion_retry_ui.open_completion_retry_review(page, {'started_at': 'selected'}, options)
    assert receipt == result.receipt
    assert seen[0][0] is not project and seen[0][0].project_id == project.project_id
    assert seen[0][1]['started_at'] == 'selected' and seen[0][2] is options and seen[0][3] == 'polish'
    observed['dialog'].deleteLater()


def test_dialog_discards_results_after_manual_edit(page, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(completion_retry, 'completion_retry_preview',
        lambda *a, **k: sample_preview() if release.wait(2) else pytest.fail('test did not release retry'))
    def begin(dialog):
        page.session.project.cues[0].text = '人工已确认'
        release.set()
    def inspect(dialog):
        assert dialog._completion_retry_receipt is None and dialog.preview.count() == 0
        assert '已改变' in dialog.status_label.text()
        assert page.session.project.cues[0].text == '人工已确认' and page.session.undo_stack.count() == 0
    observed = drive_dialog(monkeypatch, inspect, begin=begin)
    assert completion_retry_ui.open_completion_retry_review(page, {}, RunOptions()) is None
    observed['dialog'].deleteLater()


def test_dialog_reject_cancels_running_worker_without_applying_late_result(page, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(completion_retry, 'completion_retry_preview',
        lambda *a, **k: sample_preview() if release.wait(2) else pytest.fail('test did not release retry'))
    def begin(dialog):
        dialog.reject()
        assert dialog._review_close_pending and dialog._glossary_review_worker.token.is_cancelled
        release.set()
    def inspect(dialog):
        assert dialog._glossary_review_worker is None
        assert dialog._completion_retry_receipt is None and dialog.preview.count() == 0
        assert page.session.project.cues[0].text == '原处理文字' and page.session.undo_stack.count() == 0
    observed = drive_dialog(monkeypatch, inspect, begin=begin)
    assert completion_retry_ui.open_completion_retry_review(page, {}, RunOptions()) is None
    observed['dialog'].deleteLater()


@pytest.mark.parametrize('stage', ['polish', 'terminology'])
def test_completion_button_dispatches_selected_task_snapshot_without_start_run(stage, monkeypatch):
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell._completion_retry_in_progress = False
    shell.result_task_selector = QComboBox(shell)
    shell.result_task_selector.addItems(['same.mp4 first task', 'same.mp4 second task'])
    shell.result_task_selector.setCurrentIndex(1)
    tasks = [MediaResult('same.mp4', 'success', project_path=str(i) + '.2byteproj',
        report_json_path=str(i) + '.json') for i in (1, 2)]
    shell._completion_tasks = [(row, sample_project()) for row in tasks]
    payloads = [{'started_at': str(i), 'scope': [i]} for i in (1, 2)]
    outcome = SimpleNamespace(result_usable=True, polish_retryable=stage == 'polish',
        search_retryable=stage == 'terminology')
    shell._completion_task_evidence = {shell._completion_task_key(row): {
        'outcome': outcome, 'display_payload': payload} for row, payload in zip(tasks, payloads)}
    frozen = RunOptions(settings_snapshot_json='{"selected":"original-task"}')
    shell._last_run_options = frozen
    monkeypatch.setattr(shell, '_start_run', lambda: pytest.fail('scoped retry entered queue'))
    opened, called = [], []
    studio = SimpleNamespace()
    def open_project(path, *, mode, source, on_ready):
        opened.append((path, mode, source))
        on_ready(studio)
    monkeypatch.setattr(shell, '_open_completion_project', open_project)
    def review(page, report, options, *, stage):
        assert shell._completion_retry_in_progress
        called.append((page, copy.deepcopy(report), options, stage))
        report['scope'].append(99)
        return {'job_id': 'selected-retry'}
    monkeypatch.setattr(completion_retry_ui, 'open_completion_retry_review', review)
    shell._retry_failed_items()
    assert opened == [('2.2byteproj', 'edit', 'completion_failed_stage_retry')]
    assert called == [(studio, {'started_at': '2', 'scope': [2]}, frozen, stage)]
    assert payloads[1]['scope'] == [2]
    assert shell._completion_task_evidence[shell._completion_task_key(tasks[1])]['retry_receipts'] == [{'job_id': 'selected-retry'}]
    assert not shell._completion_retry_in_progress
    shell.deleteLater()


def test_unsupported_search_dispatch_does_not_open_retry_or_queue(monkeypatch):
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell.result_task_selector = QComboBox(shell)
    shell.result_task_selector.addItem('same.mp4')
    item = MediaResult('same.mp4', 'success', project_path='saved.2byteproj', report_json_path='report.json')
    shell._completion_tasks = [(item, sample_project())]
    shell._completion_task_evidence = {shell._completion_task_key(item): {'outcome':
        SimpleNamespace(result_usable=True, polish_retryable=False, search_retryable=False)}}
    shell._last_failed_items = []
    monkeypatch.setattr(shell, '_open_completion_project', lambda *a, **k: pytest.fail('unsupported search opened retry'))
    monkeypatch.setattr(shell, '_start_run', lambda: pytest.fail('unsupported search entered queue'))
    shell._retry_completion_stage('terminology')
    shell._retry_failed_items()
    shell.deleteLater()



def test_active_completion_retry_blocks_start_before_config_or_worker_changes(monkeypatch):
    from twobyteasr.app import ui
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell._completion_retry_in_progress = True
    shell.media_paths = ['selected-existing-media.mp4']
    shell.start_button = QPushButton(shell)
    shell.start_button.setEnabled(True)
    shell.result_task_selector = QComboBox(shell)
    shell.result_task_selector.addItems(['first', 'selected second'])
    shell.result_task_selector.setCurrentIndex(1)
    selected = sample_project()
    shell._completion_tasks = [('first-report', sample_project()), ('selected-report', selected)]
    shell._completion_task_evidence = {'selected-report': {'display_payload': {'scope_ids': [7]}}}
    previous = copy.deepcopy(shell._completion_task_evidence)
    existing_worker, token = object(), object()
    shell.worker, shell.token = existing_worker, token
    frozen = RunOptions(settings_snapshot_json='{"case":"original-task"}')
    shell._last_run_options = frozen
    shell._retry_run_options = frozen
    def forbidden(*args, **kwargs):
        pytest.fail('start_run crossed the active completion retry guard')
    monkeypatch.setattr(shell, '_save_asr_configuration', forbidden)
    monkeypatch.setattr(shell, '_save_ai_configuration', forbidden)
    monkeypatch.setattr(shell, '_launch_pipeline_worker', forbidden)
    monkeypatch.setattr(ui, 'save_runtime_settings', forbidden)
    monkeypatch.setattr(ui, 'PipelineWorker', forbidden)
    shell._start_run()
    assert shell.worker is existing_worker and shell.token is token
    assert shell._last_run_options is frozen and shell._retry_run_options is frozen
    assert not shell._run_in_progress and shell._completion_retry_in_progress
    assert shell.start_button.isEnabled() and shell.result_task_selector.currentIndex() == 1
    assert shell._completion_tasks[1][1] is selected and shell._completion_task_evidence == previous
    assert '预览' in shell._run_block_reason
    shell.deleteLater()
