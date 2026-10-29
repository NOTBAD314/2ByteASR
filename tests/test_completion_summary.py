"""Current task facts and adaptive summaries; headed evidence is separate."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.app.completion_summary import completion_summary
from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome
from twobyteasr.app.ui import MainWindow

APP = QApplication.instance() or QApplication([])


def report():
    return {'status': 'degraded_success', 'media': {'name': '材料.mp4'},
        'result': {'cue_count': 8, 'audio_seconds': 12.375},
        'settings': {'content_profile': {'game': '', 'terminology_snapshot': {
            'libraries': [{'id': 'chosen', 'name': '自定义领域', 'revision': '9', 'found': True}], 'effective_terms': 17}}},
        'stages': [{'label': 'MOSS 全局转写', 'status': 'completed', 'elapsed_seconds': 13.2},
            {'label': '筛选 MOSS 低置信度', 'status': 'completed', 'elapsed_seconds': .05},
            {'label': '云端模型受限校对', 'status': 'completed', 'elapsed_seconds': 4.7}],
        'events': [{'event': 'terminology_applied', 'replacement_count': 2, 'scanned_segment_count': 8},
            {'event': 'terminology_applied', 'replacement_count': 0, 'scanned_segment_count': 8},
            {'event': 'terminology_polish_final', 'cue_id': 4, 'details': {'returned_edits': [{'from': 'name', 'to': 'NAME'}],
                'accepted_edits': [], 'rejected_edits': [{'from': 'name', 'to': 'NAME', 'rule_id': 'unsupported'}]}}],
        'polishing_summary': {'success_batches': 1, 'success_cues': 8, 'term_context': {
            'accepted_edits': 0, 'rejected_edits': 1, 'unresolved_recall_gaps': 3, 'recall_gap_cues': 2}},
        'terminology_summary': {'status': 'disabled', 'requested': False}, 'review_severity_counts': {'review': 5}}


def test_summary_preserves_distinct_execution_quality_and_name_counters():
    payload = report()
    summary = completion_summary(payload, normalize_recognition_outcome(payload),
        project_path='/copy/saved.2byteproj', project_loaded=True)
    assert len(summary.task_lines) == 4 and len(summary.log_lines) <= 6
    assert '12.375' in summary.task_lines[0]
    assert '场景未记录' in summary.task_lines[2] and 'r9' in summary.task_lines[2]
    assert '疑似术语未召回' in summary.log_lines[0]
    assert 'name → NAME' in summary.log_lines[1]
    assert any('MOSS 13.200s' in row for row in summary.log_lines)
    assert any('AI校对 4.700s' in row for row in summary.log_lines)
    assert (summary.local_replacements, summary.ai_proposed, summary.ai_accepted, summary.ai_rejected) == (2, 1, 0, 1)
    assert '联网核验未启用' in summary.log_lines[-1]
    assert '识别错误' not in '\n'.join(summary.log_lines)


def test_unknown_counters_are_not_invented_and_new_scene_source_is_visible():
    payload = {'status': 'success', 'result': {'cue_count': 1}, 'settings': {'content_profile': {
        'resolved_context': {'domain': '游戏甲', 'source': 'enabled_glossary_metadata'}}}}
    summary = completion_summary(payload, normalize_recognition_outcome(payload))
    assert summary.local_replacements is None and summary.ai_proposed is None
    assert '未记录' in '\n'.join(summary.log_lines)
    assert '游戏甲' in summary.task_lines[2] and '启用词库元数据' in summary.task_lines[2]
    assert '质量检查通过' not in '\n'.join(summary.log_lines)
    payload['events'] = [{'event': 'terminology_applied'}, {'event': 'terminology_polish_final', 'cue_id': 1}]
    summary = completion_summary(payload, normalize_recognition_outcome(payload))
    assert summary.local_replacements is None and summary.ai_proposed is None
    assert summary.ai_accepted is None and summary.ai_rejected is None


def shell_page():
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._completion_log_generation = 0
    page = shell._result_page()
    shell.result_task_selector.hide(); shell.result_icon.hide(); shell.result_review_status.hide()
    shell.result_summary.setText('请求已完成；仍有待审核项')
    shell.open_priority_review_button.show()
    data = report()
    summary = completion_summary(data, normalize_recognition_outcome(data), project_path='/saved.2byteproj', project_loaded=True)
    shell.result_files_panel.set_summary_lines(summary.task_lines)
    shell.result_log_panel.set_summary_lines(summary.log_lines)
    return shell, page


def settle():
    for _ in range(5):
        APP.processEvents()


def test_default_real_rows_use_viewport_height_and_manual_collapse_survives_resize():
    shell, page = shell_page()
    page.resize(1440, 1040); page.show(); settle()
    viewport = page.viewport()
    panels = (shell.result_files_panel, shell.result_log_panel)
    # 2026-10-07: both folds start collapsed; one header click opens the summary.
    assert all(panel.mode == 'collapsed' and panel.summary.isHidden() and panel.detail.isHidden() for panel in panels)
    for panel in panels:
        QTest.mouseClick(panel.header, Qt.MouseButton.LeftButton)
    settle()
    assert all(panel.mode == 'summary' and panel.summary.isVisible() and panel.detail.isHidden() for panel in panels)
    assert len(panels[0].visible_summary_rows()) == 4
    assert len(panels[1].visible_summary_rows()) == 6
    bottom = shell.result_action_grid.mapTo(viewport, QPoint()).y() + shell.result_action_grid.height()
    assert 24 <= viewport.height() - bottom <= 40, (viewport.height(), bottom)
    assert all(card.height() <= 220 for card in shell.result_action_grid.cards)
    QTest.mouseClick(panels[0].collapse_button, Qt.MouseButton.LeftButton); settle()
    assert panels[0].mode == 'collapsed'
    page.resize(1260, 800); settle()
    assert panels[0].mode == 'collapsed' and panels[0].summary.isHidden()
    QTest.mouseClick(panels[0].header, Qt.MouseButton.LeftButton); settle()
    assert panels[0].mode == 'summary'
    QTest.mouseClick(panels[0].header, Qt.MouseButton.LeftButton); settle()
    assert panels[0].mode == 'full' and panels[0].detail.isVisible() and panels[0].summary.isHidden()
    QTest.mouseClick(panels[0].header, Qt.MouseButton.LeftButton); settle()
    assert panels[0].mode == 'summary'
    page.close(); page.deleteLater(); shell.deleteLater(); settle()


def test_short_window_reduces_real_rows_then_scrolls_accessible_actions():
    shell, page = shell_page()
    page.resize(580, 440); page.show(); settle()
    assert shell.result_action_grid.columns == 1
    assert len(shell.result_files_panel.visible_summary_rows()) == 2
    assert len(shell.result_log_panel.visible_summary_rows()) == 4
    assert page.verticalScrollBar().maximum() > 0 and page.horizontalScrollBar().maximum() == 0
    page.ensureWidgetVisible(shell.result_more_button); settle()
    assert shell.result_more_button.mapTo(page.viewport(), QPoint()).y() < page.viewport().height()
    page.close(); page.deleteLater(); shell.deleteLater(); settle()


def test_extreme_logical_desktop_does_not_stretch_real_lines_into_blank_gaps():
    shell, page = shell_page()
    page.resize(3840, 2090); page.show(); settle()
    for panel in (shell.result_files_panel, shell.result_log_panel):
        assert panel._extra_height <= panel.max_extra_height()
        assert all(row.height() <= row.fontMetrics().height()+4+round(row.fontMetrics().height()*1.5)
                   for row in panel.visible_summary_rows())
    assert shell.result_action_grid.cards[0].height() <= 220
    page.close(); page.deleteLater(); shell.deleteLater(); settle()


def test_open_glossary_editor_is_prepared_before_current_task_snapshot():
    shell = MainWindow.__new__(MainWindow); QWidget.__init__(shell)
    assert shell._prepare_glossary_for_task()
    calls = []
    shell._term_library_dialog = SimpleNamespace(prepare_for_task=lambda: calls.append('commit') or False)
    assert not shell._prepare_glossary_for_task() and calls == ['commit']
    shell.deleteLater(); settle()
