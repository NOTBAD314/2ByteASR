"""Saved-result delivery and recovery through the production completion handlers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget

from twobyteasr.recognition.recognition_history import parse_recognition_report
from twobyteasr.recognition.service import MediaResult, QueueResult
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.app.ui import MainWindow

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def completion_shell(monkeypatch):
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell._ui_language = 'zh'
    shell._active_stages = set()
    shell._progress_timer = QTimer(shell)
    shell.workflow = SimpleNamespace(set_active=lambda *args, **kwargs: None)
    shell.console_log = QTextEdit(shell)
    shell._console_lines = ['isolated retained log']
    shell._console_fragments = []
    shell._completion_dialog = None
    shell.switched_pages = []
    monkeypatch.setattr(shell, '_release_run_state', lambda: None)
    monkeypatch.setattr(shell, '_refresh_progress_cards', lambda: None)
    monkeypatch.setattr(shell, '_switch_page', lambda page: shell.switched_pages.append(page))
    monkeypatch.setattr(shell, '_show_task_notification', lambda *args: None)
    monkeypatch.setattr(shell, '_refresh_media_summary', lambda: None)
    monkeypatch.setattr(shell, '_resolve_glossary_binding', lambda: None)
    page = shell._result_page()
    page.setParent(shell)
    yield shell
    shell.deleteLater()


def write_report(tmp_path, *, status='degraded_success', project_path=None, srt_path=None):
    path = tmp_path / '本次_字幕任务报告.json'
    report = {
        'status': status,
        'started_at': '2026-10-04T23:33:59',
        'media': {'path': str(tmp_path / 'original.mp4')},
        'result': {'cue_count': 2, 'elapsed_seconds': 1.0, 'outputs': {
            'project': str(project_path or ''), 'srt': str(srt_path or '')}},
        'polishing_summary': {'success_cues': 2, 'fallback_cues': 0},
        'terminology_summary': {'status': 'failed', 'unverified_count': 2,
                                'failure_categories': {'unsupported_search': 2}},
    }
    if status == 'failed':
        report['result']['outputs']['project_error'] = 'original required save failed'
        report['result']['error'] = 'original required save failed'
    path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    return path, report


def saved_project(path):
    save_project(SubtitleProject(media=StudioMedia(path='original.mp4', duration_ms=2000), cues=[
        StudioCue('cue1', 0, 1000, '已有第一句'),
        StudioCue('cue2', 1000, 2000, '已有第二句'),
    ]), path)
    return path


def test_missing_artifact_does_not_rewrite_completed_task_as_save_failure(completion_shell, tmp_path):
    project_path = tmp_path / 'moved.2byteproj'
    report_path, report = write_report(tmp_path, project_path=project_path)
    before = report_path.read_bytes()
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult(report['media']['path'], 'degraded_success',
        project_path=str(project_path), report_json_path=str(report_path)),), 1.0))

    evidence = shell._completion_task_evidence[str(report_path)]
    assert evidence['outcome'].core_status == parse_recognition_report(report_path).status == 'completed'
    assert evidence['project_error'] and evidence['outcome'].core_errors == ()
    assert 'project_save_error' not in evidence['display_payload']['result']
    assert not shell.export_result_button.isEnabled() and not shell.open_studio_result_button.isEnabled()
    assert shell._last_studio_project == ''
    assert '工程无法载入' in shell.result_task_summary.text()
    assert report_path.read_bytes() == before


def test_verified_recovery_rebinds_saved_export_target_without_rewriting_history(completion_shell, tmp_path, monkeypatch):
    from twobyteasr.exports import completion_export
    from twobyteasr.recognition import recognition_recovery

    original = tmp_path / 'damaged.2byteproj'
    original.write_bytes(b'{ damaged original project')
    srt = tmp_path / 'retained.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n已有第一句\n\n'
                   '2\n00:00:01,000 --> 00:00:02,000\n已有第二句\n', encoding='utf-8')
    report_path, report = write_report(tmp_path, status='failed', project_path=original, srt_path=srt)
    protected = {path: path.read_bytes() for path in (original, srt, report_path)}
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult(report['media']['path'], 'failed',
        project_path=str(original), report_json_path=str(report_path), srt_path=str(srt)),), 1.0))
    recovery = recognition_recovery.recover_report
    monkeypatch.setattr(recognition_recovery, 'recover_report',
                        lambda path: recovery(path, recovery_root=tmp_path / 'recovered'))
    opened = []
    monkeypatch.setattr(shell, 'open_studio_project', lambda path, **kwargs: opened.append((Path(path), kwargs)))
    shell._recover_recognition_output()

    item, project = shell._completion_tasks[0]
    recovered_path = Path(item.project_path)
    evidence = shell._completion_task_evidence[str(report_path)]
    outcome = evidence['outcome']
    assert recovered_path.is_relative_to(tmp_path / 'recovered') and recovered_path != original
    assert shell._last_studio_project == str(recovered_path)
    assert outcome.result_usable and outcome.delivery_recovered and outcome.core_status == 'partial'
    assert outcome.raw_status == outcome.original_core_status == 'failed'
    assert evidence['delivery_witness'].project_sha256 == hashlib.sha256(recovered_path.read_bytes()).hexdigest()
    assert evidence['project_error'] == '' and project.cues[0].text == '已有第一句'
    assert shell.export_result_button.isEnabled() and shell.open_studio_result_button.isEnabled()
    assert opened == [(recovered_path, {'mode': 'edit', 'source': 'recognition_recovery'})]

    edited = load_project(recovered_path)
    edited.cues[0].text = '恢复后的工作台编辑'
    save_project(edited, recovered_path)
    exported = []
    class ExportDialog:
        def __init__(self, current, *args):
            exported.append(current)
        def exec(self):
            return False
    monkeypatch.setattr(completion_export, 'CompletionExportDialog', ExportDialog)
    shell._export_completion_result()
    assert exported[0].cues[0].text == '恢复后的工作台编辑'
    shell.switched_pages.clear()
    shell._return_to_main_menu()
    assert shell.switched_pages == [0]
    assert parse_recognition_report(report_path).status == 'failed'
    assert all(path.read_bytes() == raw for path, raw in protected.items())


def test_recovery_without_previous_report_lets_the_user_pick_one(completion_shell, tmp_path, monkeypatch):
    """更多操作 → 恢复已有识别结果… with no usable earlier report opens a report picker.

    Until 2026-10-15 `app/ui.py` used QFileDialog without importing it, so this
    path raised NameError inside the Qt slot and no picker appeared.
    """
    from PySide6 import QtWidgets
    from twobyteasr.app import ui
    from twobyteasr.recognition import recognition_recovery

    assert ui.QFileDialog is QtWidgets.QFileDialog
    picked, recovered, warnings = [], [], []
    answer = ['']

    class Picker:
        @staticmethod
        def getOpenFileName(parent, caption, folder, filters):
            picked.append((parent, str(caption), filters))
            return answer[0], filters

    def recover(path):
        recovered.append(path)
        raise RuntimeError('报告无法读取')
    monkeypatch.setattr(ui, 'QFileDialog', Picker)
    monkeypatch.setattr(recognition_recovery, 'recover_report', recover)
    monkeypatch.setattr(ui.QMessageBox, 'warning', lambda parent, title, text: warnings.append((str(title), str(text))))
    shell = completion_shell
    shell._last_recognition_report = str(tmp_path / 'moved_字幕任务报告.json')

    shell._recover_recognition_output()          # the earlier report is gone: ask; cancelling does nothing
    assert [(parent, caption) for parent, caption, _ in picked] == [(shell, '选择已有字幕任务报告')]
    assert recovered == [] and warnings == []

    answer[0] = str(tmp_path / 'chosen_字幕任务报告.json')
    shell._recover_recognition_output()          # the chosen report goes to recovery
    assert len(picked) == 2 and recovered == [answer[0]]
    assert warnings and warnings[0][0] == '恢复未完成' and '报告无法读取' in warnings[0][1]


def test_return_requires_recovered_autosave_even_when_undo_stack_is_clean(completion_shell, tmp_path):
    project_path = saved_project(tmp_path / 'saved.2byteproj')
    report_path, report = write_report(tmp_path, project_path=project_path)
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult(report['media']['path'], 'degraded_success',
        project_path=str(project_path), report_json_path=str(report_path)),), 1.0))
    attempts = []
    studio = SimpleNamespace(project_path=str(project_path), _recovered_autosave_pending=True,
        session=SimpleNamespace(undo_stack=SimpleNamespace(isClean=lambda: True)))
    studio.project_controller = SimpleNamespace(save=lambda: attempts.append('save'))
    shell.studio_page = studio
    shell.switched_pages.clear()

    shell._return_to_main_menu()
    assert attempts == ['save'] and shell.switched_pages == []
    assert '结果尚未安全保存' in shell.result_task_summary.text()
    assert not shell.result_task_summary.isHidden()

    def complete_save():
        attempts.append('save')
        studio._recovered_autosave_pending = False
    studio.project_controller.save = complete_save
    shell._return_to_main_menu()
    assert attempts == ['save', 'save'] and shell.switched_pages == [0]
