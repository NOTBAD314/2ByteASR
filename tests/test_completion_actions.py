"""Completion actions and stage ownership; real-sample audits are separate."""
from __future__ import annotations

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

from twobyteasr.app.completion_widgets import CompletionActionCard, CompletionActionGrid, CompletionSecondaryGroup, CompletionTaskSelector
from twobyteasr.design.ui_theme import blend_hex
from twobyteasr.app.main_ui_helpers import completion_stage_evidence, polishing_completion_details
from twobyteasr.recognition.service import MediaResult, QueueResult, RunOptions
from twobyteasr.app.ui import MainWindow, append_log_html_keep_left
from twobyteasr.design.ui_theme import theme_definition

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def completion_shell(monkeypatch):
    """Exercise production terminal handlers with actual completion widgets."""
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell._ui_language = 'zh'
    shell._active_stages = set()
    shell._progress_timer = QTimer(shell)
    shell.workflow = SimpleNamespace(set_active=lambda *args, **kwargs: None)
    shell.console_log = QTextEdit(shell)
    shell._console_lines = ['retained task log']
    shell._console_fragments = []
    monkeypatch.setattr(shell, '_release_run_state', lambda: None)
    monkeypatch.setattr(shell, '_refresh_progress_cards', lambda: None)
    monkeypatch.setattr(shell, '_switch_page', lambda *args: None)
    monkeypatch.setattr(shell, '_show_task_notification', lambda *args: None)
    page = shell._result_page()
    page.setParent(shell)
    yield shell
    shell.deleteLater()


def test_success_then_startup_failure_does_not_restore_previous_counts_or_directory(completion_shell, tmp_path):
    from twobyteasr.i18n import apply_ui_language
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    project_path = tmp_path/'previous.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='previous.mp4', duration_ms=2000), cues=[
        StudioCue('cue1', 0, 1000, '第一句'), StudioCue('cue2', 1000, 2000, '第二句')]), project_path)
    report_path = tmp_path/'previous-report.json'
    report_path.write_text(json.dumps({'result': {'cue_count': 2}, 'review_severity_counts': {'review': 1}}), 'utf8')
    srt_path = tmp_path/'previous.srt'
    srt_path.write_text('retained output', 'utf8')
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult('previous.mp4', 'success', project_path=str(project_path),
        report_json_path=str(report_path), srt_path=str(srt_path)),), 1.0))
    assert '2 条字幕' in shell.result_summary.text()
    assert shell.open_subtitle_result_button.isEnabled()

    shell._handle_unexpected_error('new worker failed to start')
    apply_ui_language(shell, 'en')
    apply_ui_language(shell, 'zh')
    assert shell.result_title.text() == '任务未能启动'
    assert shell.result_review_summary.text() == ''
    assert shell.result_task_summary.text() == ''
    assert shell._last_srt_dir == ''
    assert not shell.open_subtitle_result_button.isEnabled()
    assert not shell._last_studio_project
    assert not shell.export_result_button.isEnabled() and not shell.open_studio_result_button.isEnabled()
    assert shell.result_return_button.isEnabled()
    assert 'new worker failed to start' in shell.result_exception_summary.text()
    assert not shell.result_files_toggle.isChecked() and not shell.result_log_toggle.isChecked()


@pytest.mark.parametrize('exists', [True, False])
def test_unavailable_result_project_keeps_actionable_reason_outside_folded_details(completion_shell, tmp_path, exists):
    project_path = tmp_path/'unavailable.2byteproj'
    if exists:
        project_path.write_text('{ damaged copy', 'utf8')
    report_path = tmp_path/'retained-report.json'
    report_path.write_text(json.dumps({'result': {'cue_count': 2}}), 'utf8')
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult('actual.mp4', 'success', project_path=str(project_path),
        report_json_path=str(report_path)),), 1.0))
    assert '工程无法载入' in shell.result_task_summary.text()
    assert '恢复已有识别结果' in shell.result_task_summary.text()
    assert str(project_path) in shell.result_task_summary.toolTip()
    assert not shell.result_task_summary.isHidden()
    assert not shell._last_studio_project
    assert shell._last_recognition_report == str(report_path)
    assert not shell.export_result_button.isEnabled() and not shell.open_studio_result_button.isEnabled()
    assert shell.result_return_button.isEnabled()
    assert not shell.result_files_toggle.isChecked() and not shell.result_log_toggle.isChecked()


def test_empty_queue_clears_previous_subtitle_directory_action(completion_shell):
    shell = completion_shell
    shell._last_srt_dir = 'previous-output'
    shell.open_subtitle_result_button.setEnabled(True)
    shell._handle_result(QueueResult((), 0.0))
    assert shell._last_srt_dir == ''
    assert not shell.open_subtitle_result_button.isEnabled()


def test_web_failure_is_not_text_polishing_failure():
    report = {'result': {'cue_count': 32}, 'polishing_summary': {
        'success_batches': 2, 'success_cues': 31, 'fallback_cues': 0},
        'terminology_summary': {'status': 'failed', 'verified_count': 0,
        'unverified_count': 31, 'failure_categories': {'unsupported_search': 31}}}
    evidence = completion_stage_evidence(report)
    assert evidence['retry_stages'] == ()
    assert evidence['verification_incomplete']
    assert not evidence['polish_incomplete']
    assert evidence['search_unsupported']
    lines, retry = polishing_completion_details(report)
    assert not retry and '31' in '\n'.join(lines)
    assert any('处理记录 31' in line and '最终字幕 32' in line for line in lines)
    assert any('当前通道不支持' in line for line in lines)


@pytest.mark.parametrize('key', ['warm', 'grape', 'charcoal'])
def test_three_cards_share_theme_accent_and_reflow(key, monkeypatch):
    import twobyteasr.app.completion_widgets as controls
    monkeypatch.setattr(controls, 'theme_key', lambda: key)
    cards = [CompletionActionCard(title, '用途说明', 'fa5s.film', hue=hue)
             for title, hue in (('导出字幕', 'primary'), ('打开字幕工作台', 'brand'), ('完成并返回主菜单', 'finish'))]
    grid = CompletionActionGrid(cards)
    grid.resize(1100, controls.COMPLETION_MAIN_HEIGHT)
    grid.show()
    APP.processEvents()
    assert grid.columns == 3
    assert len({card.width() for card in cards}) <= 2
    assert {card.height() for card in cards} == {controls.COMPLETION_MAIN_HEIGHT}
    for card in cards:
        monkeypatch.setattr(card, 'underMouse', lambda: False)
        image = card.grab().toImage()
        # 2026-10-07: equal cards, each with its identity hue (wash + chip).
        theme = theme_definition(key)
        hue = card.hue_color()
        assert image.pixelColor(card.width()-25, card.height()-25) == QColor(blend_hex(theme.surface, hue, theme.role_wash[0]))
        chip = card.content_rects()[0]
        assert image.pixelColor(int(chip.left()) + 4, int(chip.center().y())) == QColor(hue)
    assert len({card.hue_color() for card in cards}) == 3
    grid.resize(700, 600)
    APP.processEvents()
    assert grid.columns == 1
    assert all(card.width() <= grid.width() for card in cards)
    assert cards[0].geometry().bottom() < cards[1].geometry().top()
    grid.close()


def test_full_card_keyboard_and_reentrant_activation_guard():
    card = CompletionActionCard('导出字幕', '保存字幕文件', 'fa5s.file-export')
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    calls = []
    def invoke():
        calls.append('export')
        shell._completion_action('export', invoke)
    card.clicked.connect(lambda: shell._completion_action('export', invoke))
    card.show()
    card.setFocus()
    APP.processEvents()
    QTest.keyClick(card, Qt.Key.Key_Space)
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    assert calls == ['export']
    shell._completion_action('studio', lambda: calls.append('studio'))
    assert calls == ['export', 'studio']
    card.close()
    shell.deleteLater()


def test_earlier_log_position_survives_new_output():
    edit = QTextEdit()
    edit.resize(400, 140)
    edit.show()
    for i in range(200):
        append_log_html_keep_left(edit, f'旧日志 {i}')
    APP.processEvents()
    bar = edit.verticalScrollBar()
    bar.setValue(bar.maximum() // 3)
    previous = bar.value()
    append_log_html_keep_left(edit, '新的完整日志')
    APP.processEvents()
    assert bar.value() == previous
    assert '新的完整日志' in edit.toPlainText()
    edit.close()


def test_retry_uses_frozen_options_without_reading_home_settings(monkeypatch):
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell.media_paths = ['actual-media.mp4']
    class Button:
        def setEnabled(self, value): pass
    shell.start_button = Button()
    frozen = RunOptions(glossary_snapshot_json='{"case":"BerLIN"}',
                        settings_snapshot_json='{"model":"saved"}')
    shell._retry_run_options = frozen
    seen = []
    monkeypatch.setattr(shell, '_launch_pipeline_worker', seen.append)
    shell._start_run()
    assert seen == [frozen]
    assert shell._retry_run_options is None
    shell.deleteLater()


def test_export_dialog_preserves_dotted_media_stem():
    from twobyteasr.exports.completion_export import CompletionExportDialog
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    project = SubtitleProject(media=StudioMedia(path='', duration_ms=0))
    dialog = CompletionExportDialog(project, '比赛.42250669220.456-467')
    assert dialog.name.text() == '比赛.42250669220.456-467'
    dialog.deleteLater()


def test_task_selector_paints_middle_ellipsis_without_changing_selection():
    selector = CompletionTaskSelector()
    complete = '【无畏契约上海全球冠军赛】9月27日_JDG_vs_FUT.图一_亚海悬城.42250669220.456-467.mp4'
    selector.addItem(complete)
    selector.setItemData(0, complete, Qt.ItemDataRole.ToolTipRole)
    selector.setToolTip(complete)
    selector.resize(280, 40)
    selector.show()
    APP.processEvents()
    painted = selector._elided_style_option().currentText
    assert '…' in painted and painted != complete
    assert painted.endswith('.mp4')
    assert selector.currentText() == complete
    assert selector.itemData(0, Qt.ItemDataRole.ToolTipRole) == complete
    assert selector.toolTip() == complete
    selector.close()


def test_secondary_actions_are_one_readable_group_and_wrap_when_narrow():
    page = QWidget()
    layout = QVBoxLayout(page)
    buttons = [QPushButton(title) for title in ('开始优先审核', '按当前词库重新校对…', '更多操作')]
    bar = CompletionSecondaryGroup(buttons)
    layout.addWidget(bar)
    page.resize(1000, 220)
    page.show()
    APP.processEvents()
    assert all(button.height() >= 40 for button in buttons)
    assert len({button.y() for button in buttons}) == 1
    page.resize(240, 300)
    APP.processEvents()
    assert buttons[0].y() < buttons[1].y() < buttons[2].y()
    page.close()


def test_return_requires_saved_project_but_never_requires_srt(completion_shell, monkeypatch, tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    from PySide6.QtWidgets import QMessageBox
    project_path = tmp_path/'saved.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='actual.mp4', duration_ms=1000),
        cues=[StudioCue('cue', 0, 1000, '已保存')]), project_path)
    report_path = tmp_path/'report.json'
    report_path.write_text(json.dumps({'status': 'success', 'result': {'cue_count': 1}}), 'utf8')
    shell = completion_shell
    shell._handle_result(QueueResult((MediaResult('actual.mp4', 'success', project_path=str(project_path),
        report_json_path=str(report_path)),), 1))
    pages = []
    monkeypatch.setattr(shell, '_switch_page', pages.append)
    monkeypatch.setattr(shell, '_refresh_media_summary', lambda: None)
    monkeypatch.setattr(shell, '_resolve_glossary_binding', lambda: None)
    shell._return_to_main_menu()
    assert pages == [0]
    project_path.write_text('{ broken after completion', 'utf8')
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args))
    shell._return_to_main_menu()
    assert pages == [0] and warnings
    assert '尚未安全保存' in shell.result_task_summary.text()
    assert not shell.result_task_summary.isHidden()


def test_completion_report_path_identity_keeps_same_media_tasks_separate(completion_shell, tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    tasks = []
    for index, text in enumerate(('第一份', '第二份')):
        path = tmp_path/f'{index}.2byteproj'
        save_project(SubtitleProject(media=StudioMedia(path='same.mp4', duration_ms=1000),
            cues=[StudioCue(str(index), 0, 1000, text)]), path)
        report = tmp_path/f'{index}.json'
        report.write_text(json.dumps({'status':'success','result':{'cue_count':1},
            'polishing_summary':{'success_cues':index+1,'success_batches':1},
            'terminology_summary':{'status':'disabled'}}), 'utf8')
        tasks.append(MediaResult('same.mp4','success',project_path=str(path),report_json_path=str(report)))
    shell = completion_shell
    shell._handle_result(QueueResult(tuple(tasks), 2))
    assert len(shell._completion_task_evidence) == 2
    shell.result_task_selector.setCurrentIndex(1)
    assert shell._last_studio_project == tasks[1].project_path
    assert shell._last_recognition_report == tasks[1].report_json_path
    assert tasks[1].project_path in shell.result_files.toPlainText()
    assert tasks[0].project_path not in shell.result_files.toPlainText()
    assert shell.result_return_button is shell.result_action_grid.cards[2]
    assert not hasattr(shell, 'burn_subtitle_result_button')
    assert all('压制' not in action.text() for action in shell.result_more_menu.actions())
