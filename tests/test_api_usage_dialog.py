"""The API 用量与估算费用 window (2026-11-14 design 3, 日历糖果): totals, filters, task list, export."""

import csv
import json
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.design.ui_theme import contrast_ratio, ordered_themes
from twobyteasr.design.usage_dialog_qss import build_usage_dialog_qss, step_tones
from twobyteasr.providers import usage_ledger
from twobyteasr.studio import usage_dialog
from twobyteasr.studio.usage_dialog import UsageDialog, cost_text, money, row_money, status_mark

TODAY = date(2026, 11, 14)


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def ledger_rows():
    base = datetime(2026, 11, 14, 12, 0).astimezone()

    def row(i, task, project, stage, *, status='received', days=0, label='', cost=('0.001', '0.001')):
        at = (base - timedelta(days=days, minutes=i)).astimezone(timezone.utc).isoformat()
        value = dict(request_id=f'r{i}', at=at, model='deepseek-v4-flash', stage=stage, status=status,
                     task_id=task, project_id=project, media_fingerprint='')
        if label:
            value['task_label'] = label
        if status == 'received':
            value['usage'] = dict(input_tokens=1000, output_tokens=200, cached_input_tokens=100, uncached_input_tokens=900)
            value['cost'] = dict(known=True, currency='USD', low=cost[0], high=cost[1])
        else:
            value['usage'] = None
            value['cost'] = dict(known=False, reason='缺少用量')
        return value
    return [row(0, 't1', 'p1', 'translation', label='第1话.mp4'),
            row(1, 't1', 'p1', 'translation', status='usage_unknown'),
            row(2, 't1', 'p1', 'sentence_grouping', cost=('0.002', '0.004')),
            row(3, 't2', 'p1', 'proofread', days=3),
            row(4, 't3', 'p9', 'translation', days=10),
            row(5, '', '', 'connection_test', days=1, status='rate_limited')]


class Media:
    display_name = '工程片名.mp4'


class Project:
    project_id = 'p1'
    media = Media()
    generation_metadata = {}


@pytest.fixture
def dialog(app, monkeypatch):
    monkeypatch.setattr(usage_ledger, 'read_rows', lambda path=None: ledger_rows())
    monkeypatch.setattr(usage_ledger, 'flush', lambda timeout=2: None)
    monkeypatch.setattr(usage_ledger, 'write_error', lambda: '')
    monkeypatch.setattr(UsageDialog, '_today', lambda self: TODAY)
    window = UsageDialog(project=Project(), task_id='t1')
    end = time.time() + 5
    while not window._loaded_once and time.time() < end:
        app.processEvents()
        time.sleep(.01)
    assert window._loaded_once
    window.show()
    yield window
    window.close()


def test_money_and_status_helpers():
    assert money(Decimal('0.0212')) == '0.0212'
    assert money(Decimal('1.5')) == '1.50'
    assert money(Decimal('0.0000368')) == '0.000037'
    assert row_money(Decimal('0.00189')) == '0.00189'
    assert cost_text(Decimal('0.003'), Decimal('0.005')) == '0.0030–0.0050'
    assert [status_mark(s) for s in ('received', 'usage_unknown', 'cancelled', 'rate_limited')] == \
        ['applied', 'review', 'cancelled', 'failed']


def test_opens_on_this_task_and_never_counts_unknown_as_zero(dialog):
    assert dialog.scope == 'task'
    assert [row['request_id'] for row in dialog.visible_rows] == ['r0', 'r1', 'r2']
    assert '0.0030–0.0050' in dialog.money.text()
    assert '1 次用量未知' in dialog.badge.text
    assert dialog.todo.isVisibleTo(dialog) and dialog.todo.text() == '有问题 1'
    assert dialog.scope_label.text() == '本次任务' and dialog.range_label.text() == '全部时间'
    assert dialog.model.headerData(4, usage_dialog.Qt.Orientation.Horizontal) == '费用 USD'


def test_step_chips_and_problem_filter_stack(dialog):
    dialog._pick_step('翻译')
    assert [row['request_id'] for row in dialog.visible_rows] == ['r0', 'r1']
    dialog.todo.click()
    assert [row['request_id'] for row in dialog.visible_rows] == ['r1']
    dialog._pick_step('翻译')
    assert [row['request_id'] for row in dialog.visible_rows] == ['r1']
    dialog.todo.click()
    assert len(dialog.visible_rows) == 3


def test_filtered_total_and_all_unknown_cost_are_honest(dialog):
    dialog._pick_step('翻译')
    assert '0.0010' in dialog.money.text() and '0.0050' not in dialog.money.text()
    dialog.todo.click()
    assert '未知' in dialog.money.text() and '1 次' in dialog.facts.text()
    assert '1 次用量未知' in dialog.badge.text
    dialog.scope = 'task:loose'
    dialog.step = ''
    dialog.render()
    assert '未知' in dialog.money.text()
    cards = [dialog.tasks.item(i).data(usage_dialog.TaskDelegate.Role) for i in range(dialog.tasks.count())]
    assert next(card for card in cards if card.get('scope') == 'task:loose')['cost'] == '未知'


def test_task_list_names_old_and_new_rows(dialog):
    names = {key: dialog.titles[key] for key in ('t1', 't2', 't3', 'loose')}
    assert names['t1'] == '第1话.mp4'                 # recorded task_label
    assert names['t2'] == '工程片名.mp4'               # older row of the open project
    assert names['t3'].startswith('任务 ')            # older row of another project
    assert names['loose'] == '其他请求'
    scopes = [dialog.tasks.item(i).data(usage_dialog.Qt.ItemDataRole.UserRole) for i in range(dialog.tasks.count())]
    assert scopes[:3] == ['all', 'project', 'task'] or scopes[:3] == ['task', 'project', 'all']
    target = next(i for i, scope in enumerate(scopes) if scope == 'task:t3')
    dialog.tasks.setCurrentRow(target)
    assert dialog.scope == 'task:t3'
    assert [row['request_id'] for row in dialog.visible_rows] == ['r4']


def test_time_range_buttons_and_dragged_days(dialog):
    dialog.scope = 'all'
    dialog.render()
    assert len(dialog.visible_rows) == 6
    dialog.range_buttons['today'].click()
    assert {row['request_id'] for row in dialog.visible_rows} == {'r0', 'r1', 'r2'}
    dialog._pick_days(3, 1)
    assert dialog.range_mode == 'custom' and dialog.range_label.text() == '11/11–11/13'
    assert {row['request_id'] for row in dialog.visible_rows} == {'r3', 'r5'}
    assert not any(button.isChecked() for button in dialog.range_buttons.values())
    parts, requests, unknown = dialog.calendar.days[-1]
    assert (requests, unknown) == (3, 1) and set(parts) == {'翻译', '断句'}


def test_detail_line_copy_and_csv(dialog, tmp_path, app):
    assert dialog.strip_lead.text() == '说明' and not dialog.copy_button.isEnabled()
    dialog.table.selectRow(1)
    assert dialog.strip_lead.text() == '先看看' and '不算作零' in dialog.strip_text.text()
    dialog.table.selectRow(0)
    assert dialog.strip_lead.text() == '这一行' and '第1话.mp4' in dialog.strip_text.text()
    dialog.copy_row()
    assert json.loads(app.clipboard().text())['request_id'] == 'r0'
    path = dialog.export_csv(str(tmp_path / 'usage.csv'))
    with open(path, encoding='utf-8-sig', newline='') as stream:
        lines = list(csv.reader(stream))
    assert lines[0][0] == '本机时间' and len(lines) == 4
    assert lines[2][7] == '' and lines[2][11] == '用量未知'


@pytest.mark.parametrize('theme', ordered_themes(), ids=lambda theme: theme.key)
def test_step_colours_read_in_every_theme(theme):
    for step, (_solid, soft, ink) in step_tones(theme).items():
        assert contrast_ratio(ink, soft) >= 4.4, (theme.key, step)
    assert 'QDialog#apiUsageDialog' in build_usage_dialog_qss(theme)


def test_usage_scope_records_a_task_label():
    with usage_ledger.usage_scope(project_id='p', task_id='t', task_label='第2话.mkv'):
        assert usage_ledger.context()['task_label'] == '第2话.mkv'
        attempt = usage_ledger.Attempt(endpoint='https://api.deepseek.com/v1/chat/completions', model='deepseek-v4-flash')
    assert attempt.row['task_label'] == '第2话.mkv' and attempt.row['task_id'] == 't'
