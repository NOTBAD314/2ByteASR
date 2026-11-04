from twobyteasr.app.main_ui_helpers import polishing_completion_details


def test_schema_failure_is_shown_as_output_problem_not_network_failure():
    report = {'result': {'cue_count': 1, 'segment_count': 1}, 'polishing_summary': {
        'fallback_batches': 1, 'fallback_cues': 1,
        'failure_categories': {'structured_schema_error': 1}}}
    lines, retry = polishing_completion_details(report)
    assert retry
    assert any('输出字段不符合约定' in line for line in lines)
    assert not any('请求失败' in line for line in lines)
