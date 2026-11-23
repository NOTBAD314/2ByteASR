"""2026-11-22 (user, 1 h 洛克王国 stream): retries packed clauses into 14-character lines.

The before/after pairs are the reported job's own grouping_quality_retry
receipts, each logged "improved". The replay fixture keeps that job's
requests, first answers and retry answers (no media, network or account).
"""
import json
from pathlib import Path

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.grouping_quality_request import candidate_answer, correction_regression

FIXTURE = Path(__file__).parent / 'fixtures' / 'grouping_contract' / 'rocom_1h_20261122_replay.json'


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh', enable_domain_terms=False),
                                                        legacy=core):
        yield


def cuts(parts):
    out, total = [], 0
    for part in parts:
        total += len(part)
        out.append(total)
    return out


@pytest.mark.parametrize('before,after', [
    (['你们别着急', '我跟你说你们别着急', '这时候罗隐开完古镜之后', '我们要推了还搁那笑呢', '马上你就笑不出来了', '我只能说'],
     ['你们别着急我跟你说', '你们别着急这时候罗隐开完古镜', '之后我们要推了还搁那笑呢', '马上你就笑不出来了我只能说']),
    (['朋友们啊就我我插句嘴啊', '就是直播间里面有', '那种就是不太尊重别人的啊', '就是人家打了一半还搁',
      '那速速下一个就这种啊', '我我我可能', '我迟早都会给你封掉的', '你说话注意点啊', '你说话注意点'],
     ['朋友们啊就我', '我插句嘴啊就是直播间里面有', '那种就是不太尊重', '别人的啊就是人家打了一半还搁',
      '那速速下一个就这种啊我', '我我可能我迟早都会给你封掉的', '你说话注意点啊你说话注意点']),
])
def test_joining_complete_lines_into_long_ones_is_a_regression(before, after):
    q = BoundaryQuality(''.join(before))
    assert correction_regression(q, cuts(before), cuts(after), 0, q.total) == 'merged_complete_lines'


def test_a_short_fragment_may_still_join_its_neighbour():
    before = ['江陵一日还', '没死吗']
    q = BoundaryQuality(''.join(before))
    assert correction_regression(q, cuts(before), [q.total], 0, q.total) == ''


def test_a_measured_pause_is_never_joined_over():
    before = ['好的', '我们走']
    q = BoundaryQuality(''.join(before), pauses={2: .4})
    assert correction_regression(q, cuts(before), [q.total], 0, q.total) == 'merged_complete_lines'


def test_reference_keeps_passed_cuts_and_splits_the_long_line_evenly():
    from twobyteasr.subtitle_rules.ai_boundary_policy import break_candidates
    parts = ['你们别着急', '这时候罗隐开完古镜之后我们要推了还搁那笑呢']
    q = BoundaryQuality(''.join(parts))
    result = cuts(parts)
    answer = candidate_answer(q, result, 0, q.total, break_candidates(q))
    assert answer is not None and 5 in answer
    lengths = [b - a for a, b in zip([0, *answer], answer)]
    assert max(lengths) <= q.max_chars and lengths[0] == 5


def test_a_number_with_no_legal_cut_is_a_note_not_an_unfinished_range():
    from twobyteasr.subtitle_rules.ai_boundary_policy import (inspect, unsplittable_lengths,
                                                              select_model_boundary_domain)
    q = BoundaryQuality('872498724987249')
    select_model_boundary_domain(q)
    issues = [x for x in inspect(q, [q.total]) if x['kind'] == 'length']
    assert issues and unsplittable_lengths(q, issues) == issues


def test_replay_of_the_reported_job_keeps_the_first_answer():
    from twobyteasr.acceptance.grouping_report_replay import replay
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    data = dict(data, batches=[b for b in data['batches'] if b['batch_id'] in {3, 6}])
    total = replay(data)['total']
    # Job: 2 batches merged 27% of the first answer's cuts away and one batch
    # was left as 断句待重试; now the first answer stands where it was within limits.
    assert total['blocking'] == 0
    assert total['kept_first_ratio'] >= .9
    assert total['near_limit_ratio'] <= .2
