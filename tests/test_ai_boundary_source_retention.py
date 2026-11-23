from types import SimpleNamespace

import subtitle_core  # Initialize the legacy language facade.

from twobyteasr.subtitle_rules.ai_boundary_policy import (
    indivisible_spans, inspect, preserve_rejected_windows, select_model_boundary_domain,
)
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.grouping_quality_request import QualityRetryBudget, retry_quality_windows


def test_numeric_length_conflict_does_not_consume_a_retry():
    body = '856856831638568316385683163'
    quality = BoundaryQuality(body, max_chars=14)
    select_model_boundary_domain(quality)
    assert indivisible_spans(quality) == [(0, 27)]
    statuses = {}

    def unexpected_request(*args, **kwargs):
        raise AssertionError('An impossible window should not reach the model')

    result = retry_quality_windows(quality, [27], [27],
        provider=SimpleNamespace(complete=unexpected_request), snapshot=None, schema=None,
        budget=QualityRetryBudget(), record=lambda *args, **kwargs: None, statuses=statuses)
    assert result == [27]
    assert statuses == {(0, 27): 'indivisible_unit'}


def test_rejected_ai_slice_preserves_original_cuts_and_successful_neighbor():
    quality = BoundaryQuality('不用防御的感觉真美妙。今天先停，明天继续。', max_chars=14, required=[10])
    select_model_boundary_domain(quality)
    result, receipts = preserve_rejected_windows(quality, [4, 10, 14, quality.total],
                                                 [10, quality.total])
    assert result == [10, 14, quality.total]
    assert receipts[0]['origin'] == 'unresolved'
    assert receipts[0]['before'] == [4, 10]
    assert receipts[0]['after'] == [10]


def test_modal_predicate_cannot_be_left_without_its_complement():
    quality = BoundaryQuality('我知道这应该怎么排才能让这个加大功率减3费啊')
    issues = inspect(quality, [11, quality.total])
    assert any(issue['kind'] == 'incomplete_expression' and issue['start'] == 11 for issue in issues)
