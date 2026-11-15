"""The 字幕任务进度与结果 window (2026-11-14 design A): chips, filters, details, retry."""

import json

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.design.task_panel_qss import build_task_panel_qss, status_tones
from twobyteasr.design.ui_theme import contrast_ratio, ordered_themes
from twobyteasr.studio.studio_task_panel import SubtitleTaskPanel
from twobyteasr.studio.studio_task_progress import SubtitleTask

FAIL = '操作或字符索引不合法，或产生不完整短片段'


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def make_task():
    task = SubtitleTask('AI 断句', ('a', 'b', 'c', 'd'))
    task.update(dict(range_id='a', cue_ids=['a'], source_rows=[1], status='applied', input_text='今天天气很好我们出发',
                     validated_texts=['今天天气很好', '我们出发'], final_texts=['今天天气很好', '我们出发'], attempts=1))
    task.update(dict(range_id='b', cue_ids=['b'], source_rows=[2], status='failed', error=FAIL,
                     input_text='等一下', final_texts=['等一下'], attempts=2))
    task.update(dict(range_id='c', cue_ids=['c'], source_rows=[3], status='running', phase='等待模型返回',
                     input_text='没事没事', attempts=1))
    return task


@pytest.fixture
def panel(app):
    panel = SubtitleTaskPanel()
    task = make_task()
    panel.add_task(task)
    panel.show()
    panel.refresh(force=True)
    yield panel, task
    panel.close()
    panel.deleteLater()


def chips(panel):
    QApplication.processEvents()
    return {button.text(): button for button in panel.findChildren(QPushButton, 'taskChip') if button.isVisible()}


def cause_button(panel):
    QApplication.processEvents()
    return next(b for b in panel.findChildren(QPushButton, 'taskCauseFilter') if b.isVisible())


def select(panel, key):
    panel.table.selectRow(panel._row_indexes[key])
    QApplication.processEvents()


def visible_keys(panel):
    return [key for key, index in panel._row_indexes.items() if not panel.table.isRowHidden(index)]


def test_zero_counts_are_left_out_and_running_work_has_its_own_chip(panel):
    panel, _task = panel
    texts = set(chips(panel))
    assert {'全部 4', '进行中 2', '已写回 1', '失败，保留原文 1', '只看要处理的 1'} <= texts
    assert not any(text.startswith(('无需调整', '需检查', '已取消', '建议待采用')) for text in texts)
    assert panel.fraction.text() == '2/4 条原字幕' and '等待模型返回' in panel.phase.text()


def test_chips_and_cause_card_filter_the_list(panel):
    panel, _task = panel
    chips(panel)['失败，保留原文 1'].click()
    assert visible_keys(panel) == ['b']
    chips(panel)['全部 4'].click()
    assert visible_keys(panel) == ['a', 'b', 'c']
    cause_button(panel).click()
    assert visible_keys(panel) == ['b'] and panel.filter == ('cause', FAIL)
    assert cause_button(panel).text() == '看全部'
    cause_button(panel).click()
    assert panel.filter is None and len(visible_keys(panel)) == 3


def test_retry_explains_why_it_waits_then_sends_only_the_failed_range(panel):
    panel, task = panel
    select(panel, 'b')
    assert not panel.retry_button.isEnabled() and panel.retry_why.text() == '任务结束后才能重试'
    sent = []
    panel.retry.connect(sent.append)
    task.finish()
    panel.refresh()
    assert panel.cancel_button.text() == '已结束' and panel.collapse_button.text() == '关闭'
    assert panel.retry_button.isEnabled() and panel.retry_why.text() == ''
    panel.retry_button.click()
    assert sent and sent[0]['record']['cue_ids'] == ['b']
    select(panel, 'a')
    assert not panel.retry_button.isEnabled() and panel.retry_why.text() == '这段已经好了，不用重试'


def test_details_show_original_model_and_written_lines_with_the_record_one_click_away(panel):
    panel, _task = panel
    assert panel.detail.currentIndex() == 0
    select(panel, 'a')
    assert panel.detail.currentIndex() == 1
    lines = lambda card: [w.text() for w in card.findChildren(type(panel.next_lead)) if w.objectName() == 'taskSegment']
    assert lines(panel.input_card) == ['今天天气很好我们出发']
    assert lines(panel.validated_card) == lines(panel.final_card) == ['今天天气很好', '我们出发']
    assert panel.next_lead.text() == '搞定'
    select(panel, 'b')
    assert panel.final_card.title.text() == '实际写回 · 保留原文' and FAIL in panel.next_text.text()
    panel.raw_toggle.click()
    assert panel.detail.currentIndex() == 2 and json.loads(panel.details.toPlainText())['error'] == FAIL


def test_task_pills_switch_between_tasks(panel):
    panel, task = panel
    earlier = SubtitleTask('单条重新识别', ('x',))
    earlier.update(dict(range_id='x', cue_ids=['x'], status='applied'))
    earlier.finish()
    panel.add_task(earlier)
    panel.refresh()
    QApplication.processEvents()
    pills = {b.text(): b for b in panel.findChildren(QPushButton, 'taskPill') if b.isVisible()}
    assert set(pills) == {'AI 断句', '单条重新识别'} and panel.current is earlier
    pills['AI 断句'].click()
    assert panel.current is task and panel.table.model().rowCount() == 3


@pytest.mark.parametrize('theme', ordered_themes(), ids=lambda theme: theme.key)
def test_every_theme_styles_the_window_with_readable_status_text(theme):
    sheet = build_task_panel_qss(theme)
    assert 'QDialog#subtitleTaskPanel' in sheet and 'taskChip' in sheet
    for status, (_solid, soft, ink) in status_tones(theme).items():
        assert contrast_ratio(ink, soft) >= 4.4, (theme.key, status)
