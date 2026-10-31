"""B operation bar: applicable groups, complete category menus and existing jumps."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import pytest

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget
from types import SimpleNamespace

from twobyteasr.app.completion_todo import CATEGORY_LABELS, CompletionTodoSection, review_groups
from twobyteasr.app.completion_widgets import CompletionMoreButton
from twobyteasr.i18n import apply_ui_language
from twobyteasr.app.ui import MainWindow
from twobyteasr.recognition.service import MediaResult, QueueResult

APP = QApplication.instance() or QApplication([])
# The normal entry loads these before constructing MainWindow. Native font
# metrics are part of the design contract, so use that same font setup here.
from twobyteasr.app.ui import _register_bundled_fonts, _app_font
_register_bundled_fonts()
APP.setFont(_app_font())


def settle():
    for _ in range(4):
        APP.processEvents()


def test_review_groups_merge_plain_labels_largest_first_and_keep_first_row():
    rows = [dict(category='阅读较快', cue_ids=['a']), dict(category='多模型争议', cue_ids=['b']),
            dict(category='多模型文本冲突', cue_ids=['c']), dict(category='阅读较快', cue_ids=['d']),
            dict(category='阅读较快', cue_ids=['e']), dict(category='自定义类别', cue_ids=['f'])]
    groups = review_groups(rows)
    assert [(label, count) for label, count, _row in groups] == [
        (CATEGORY_LABELS['阅读较快'], 3), (CATEGORY_LABELS['多模型争议'], 2), ('自定义类别', 1)]
    assert groups[0][2]['cue_ids'] == ['a'] and groups[1][2]['cue_ids'] == ['b']


def test_section_shows_only_groups_that_apply_and_stacks_when_narrow():
    more = CompletionMoreButton(); more.setText('更多操作')
    section = CompletionTodoSection(more)
    section.resize(1284, 52); section.show(); settle()
    assert section.ai_card.isVisible() and not section.review_card.isVisible() and not section.retry_card.isVisible()
    rows = [dict(category='阅读较快', cue_ids=['a'])] * 2 + [dict(category='说话人需要确认', target='speakers')]
    section.set_review(rows)
    section.set_retry(visible=True, title='重试未完成 AI 校对', badge=4, body='AI 校对有一部分没完成，这些字幕保留了原文。只重试这一部分。')
    settle()
    assert section.columns == 3 and section.review_card.isVisible() and section.retry_card.isVisible()
    assert section.height() >= max(card.height() for card in section.cards if card.isVisible()) + 6
    assert section.review_card.badge.text() == '3' and section.retry_card.badge.text() == '4'
    assert section.retry_card.title.text() == '重试未完成 AI 校对'
    assert all(divider.isVisible() for divider in section.dividers)
    assert abs(section.ai_card.geometry().center().y() - section.retry_card.geometry().center().y()) <= 1
    chips = section.review_card.chip_texts()
    assert chips == ['字幕太快，来不及读 2', '说话人需要确认 1']
    assert section.review_card.action is None
    section.set_retry(visible=False); settle()
    assert section.columns == 3 and not section.retry_card.isVisible()
    assert section.dividers[0].isVisible() and not section.dividers[1].isVisible()
    section.resize(620, 600); settle()
    assert section.columns == 1
    assert section.ai_card.geometry().bottom() < section.review_card.geometry().top()
    section.set_review(()); settle()
    assert not section.review_card.isVisible()
    section.resize(1284, 52); settle()
    assert section.height() >= max(card.height() for card in section.cards if card.isVisible()) + 6 and not any(divider.isVisible() for divider in section.dividers)
    section.close()


def test_category_summary_has_no_removed_action_or_placeholder():
    section = CompletionTodoSection(CompletionMoreButton())
    section.resize(1284, 100); section.show()
    rows = [dict(category=f'类别 {index}', cue_ids=[str(index)]) for index in range(8)]
    section.set_review(rows); settle()
    assert section.review_card.action is None
    assert section.review_card.chip_texts()[-1] == '+5 类'
    assert not any('逐类查看' in b.text() for b in section.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton))
    section.close()


@pytest.mark.parametrize('target', ['icon','title','badge','blank','action','keyboard'])
def test_entire_ai_pill_activates_once(target):
    section = CompletionTodoSection(CompletionMoreButton())
    section.resize(1284, 100); section.set_ai(enabled=True); section.show(); settle()
    card = section.ai_card
    hits = []; card.action.clicked.connect(lambda: hits.append(1))
    if target == 'keyboard':
        card.setFocus(); QTest.keyClick(card, Qt.Key_Return)
    elif target == 'action':
        QTest.mouseClick(card.action, Qt.LeftButton)
    else:
        from PySide6.QtCore import QPoint
        pos = QPoint(card.width()//2, 2) if target == 'blank' else getattr(card,target).geometry().center()
        QTest.mouseClick(card, Qt.LeftButton, pos=pos)
    assert hits == [1]
    section.close()


@pytest.mark.parametrize('language', ['zh', 'en', 'ja'])
def test_busy_bar_keeps_buttons_and_copy_and_hides_only_whole_chips(language, monkeypatch):
    monkeypatch.setattr('twobyteasr.i18n._CURRENT_LANGUAGE_CACHE', language)
    more = CompletionMoreButton(); more.setText('更多操作')
    section = CompletionTodoSection(more)
    section.set_ai(enabled=True, unfinished=1)
    section.set_review([dict(category='阅读较快', cue_ids=['a'])] * 194
                       + [dict(category='说话人重叠', cue_ids=['b'])] * 13)
    from twobyteasr.i18n import tr
    section.set_retry(visible=True, title='重试', badge=1, note=tr('{count} 段没跑完', count=1))
    section.resize(1284, 52); section.show(); apply_ui_language(section, language); settle()
    assert section.height() >= max(card.height() for card in section.cards if card.isVisible()) + 6 and section.columns == 3, (section.width(),
        [(card.protected_width(), card.title.text(), card.note.text()) for card in section.cards], more.sizeHint().width())
    visible = [*section.cards, more]
    assert all(a.geometry().right() < b.geometry().left() for a, b in zip(visible, visible[1:]))
    for group in section.cards:
        button = group.action
        if button is not None:
            assert button.height() >= button.fontMetrics().height()
            assert button.fontMetrics().horizontalAdvance(button.text()) + 28 <= button.width()
        for label in (group.title, group.badge, group.note):
            if not label.isHidden():
                assert label.width() >= label.sizeHint().width()
    for chip in section.review_card.chips.labels:
        if chip.isVisible():
            assert chip.width() == chip.sizeHint().width()
            assert section.review_card.chips.rect().contains(chip.geometry())
    chips = section.review_card.chips
    assert chips.geometry().right() <= section.review_card.width()
    section.resize(720, section.height()); settle()
    assert section.columns == 1 and section.review_card.chips.isHidden()
    assert all(card.action.geometry().right() <= card.width() for card in section.cards if card.action is not None)
    section.close()


def completion_shell(monkeypatch):
    shell = MainWindow.__new__(MainWindow)
    QWidget.__init__(shell)
    shell._run_in_progress = False
    shell._ui_language = 'zh'
    shell._active_stages = set()
    shell._progress_timer = QTimer(shell)
    shell.workflow = SimpleNamespace(set_active=lambda *args, **kwargs: None)
    shell.console_log = QTextEdit(shell)
    shell._console_lines, shell._console_fragments = [], []
    for name in ('_release_run_state', '_refresh_progress_cards', '_switch_page', '_show_task_notification'):
        monkeypatch.setattr(shell, name, lambda *args: None)
    page = shell._result_page()
    page.setParent(shell)
    return shell


def test_real_result_fills_review_card_from_current_items_and_jumps_to_its_caption(monkeypatch, tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    project_path = tmp_path/'saved.2byteproj'
    cues = [StudioCue('c1', 0, 400, '好'), StudioCue('c2', 1000, 2000, '这是一句比较长的字幕需要很快读完的内容'),
            StudioCue('c3', 3000, 6000, '正常字幕')]
    save_project(SubtitleProject(media=StudioMedia(path='actual.mp4', duration_ms=6000), cues=cues), project_path)
    report_path = tmp_path/'report.json'
    report_path.write_text(json.dumps({'status': 'success', 'result': {'cue_count': 3},
        'polishing_summary': {'success_cues': 3, 'success_batches': 1}, 'terminology_summary': {'status': 'disabled'},
        'review_items': [{'category': '说话人重叠', 'cue_id': 'c3', 'text': '正常字幕', 'timestamp': 3.0, 'severity': 'review'}]}), 'utf8')
    shell = completion_shell(monkeypatch)
    shell._handle_result(QueueResult((MediaResult('actual.mp4', 'success', project_path=str(project_path),
        report_json_path=str(report_path)),), 1))
    todo = shell.result_todo
    labels = [label for label, _count, _row in review_groups(shell._completion_review_rows(
        shell._completion_task_evidence[shell._completion_task_key(shell._completion_tasks[0][0])]))]
    assert '多人同时说话' in labels and '字幕显示时间太短' in labels
    assert todo._shown[todo.review_card] and todo.review_card.badge.text().isdigit()
    assert not todo._shown[todo.retry_card]
    assert todo.ai_card.action.isEnabled()
    opened = []
    monkeypatch.setattr(shell, '_open_completion_project', lambda path, **kwargs: opened.append((path, kwargs)))
    row = next(row for label, _count, row in review_groups(shell._completion_review_rows(
        shell._completion_task_evidence[shell._completion_task_key(shell._completion_tasks[0][0])])) if label == '多人同时说话')
    shell._open_completion_review_row(row)
    assert opened and opened[0][0] == str(project_path) and opened[0][1]['mode'] == 'edit'
    studio = SimpleNamespace(project=SimpleNamespace(cues=cues), selected=[], seeks=[])
    studio.select_cue = studio.selected.append
    studio._seek = studio.seeks.append
    opened[0][1]['on_ready'](studio)
    assert studio.selected == ['c3'] and studio.seeks == [3.0]
    shell.deleteLater()


def test_retryable_ai_polish_moves_retry_into_its_card(monkeypatch, tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    project_path = tmp_path/'saved.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='actual.mp4', duration_ms=3000),
        cues=[StudioCue('c1', 0, 3000, '字幕')]), project_path)
    report_path = tmp_path/'report.json'
    report_path.write_text(json.dumps({'status': 'degraded_success', 'result': {'cue_count': 1},
        'polishing_summary': {'success_cues': 0, 'fallback_cues': 1, 'fallback_batches': 1},
        'terminology_summary': {'status': 'disabled'}}), 'utf8')
    shell = completion_shell(monkeypatch)
    shell._handle_result(QueueResult((MediaResult('actual.mp4', 'success', project_path=str(project_path),
        report_json_path=str(report_path)),), 1))
    todo = shell.result_todo
    assert todo._shown[todo.retry_card]
    assert shell.retry_failed_button is todo.retry_card.action
    # The summary card no longer carries a retry button of its own.
    assert shell.retry_failed_button.parentWidget() is not None
    assert not shell.result_summary_card.isAncestorOf(shell.retry_failed_button)
    shell.deleteLater()


def test_language_recovery_daily_entry_survives_operation_bar_merge(monkeypatch, tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    from twobyteasr.recognition.transcript_acceptance import KEY
    project_path = tmp_path / 'language-pending.2byteproj'
    pending = dict(id='range-1', start=0.0, end=3.0, start_sample=0, end_sample=48000,
                   status='pending', requested_language='en', transcript_language='it', attempts=[])
    save_project(SubtitleProject(media=StudioMedia(path='actual.mp4', duration_ms=3000),
        cues=[StudioCue('c1', 0, 3000, 'Parole italiane')],
        generation_metadata={KEY: dict(version=1, ranges=[pending])}), project_path)
    report_path = tmp_path / 'report.json'
    report_path.write_text(json.dumps(dict(status='success', result=dict(cue_count=1),
        polishing_summary=dict(success_cues=1, success_batches=1), terminology_summary=dict(status='disabled'))), 'utf-8')
    shell = completion_shell(monkeypatch)
    shell._handle_result(QueueResult((MediaResult('actual.mp4', 'success', project_path=str(project_path),
        report_json_path=str(report_path)),), 1))
    todo = shell.result_todo
    assert todo._shown[todo.retry_card] and todo.retry_card.badge.text() == '1'
    assert shell.retry_failed_button.text() == '仅恢复语言异常范围…'
    assert shell.retry_failed_button.isEnabled()
    assert '正常结果已保存' in shell.result_task_summary.text()
    assert shell.retry_failed_button is todo.retry_card.action
    opened = []
    monkeypatch.setattr(shell, '_open_completion_project', lambda path, **kwargs: opened.append((path, kwargs)))
    shell._retry_failed_items()
    assert opened[0][0] == str(project_path)
    assert opened[0][1]['source'] == 'completion-language-recovery'
    assert opened[0][1]['on_ready'].__name__ == 'open_recovery'
    shell.deleteLater()
