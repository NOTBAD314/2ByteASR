from types import SimpleNamespace

from twobyteasr.recognition.model_execution import canonical_model_id, summarize_model_events


def test_model_aliases_combine_real_start_and_completion():
    events = [dict(event='MODEL_SELECTED', model_id='firered', role='timeline'),
        dict(event='MODEL_STARTED', model_id='FIRERED', pid=42),
        dict(event='MODEL_COMPLETED', model_id='firered', segment_count=2),
        dict(event='MODEL_SELECTED', model_id='qwen3-asr'),
        dict(event='MODEL_STARTED', model_id='QWEN3-ASR', pid=43),
        dict(event='MODEL_COMPLETED', model_id='qwen3-asr', segment_count=3)]
    summary = summarize_model_events(events)
    assert set(summary) == {'firered', 'qwen3-asr'}
    assert all(row['selected'] and row['started'] and row['completed'] for row in summary.values())
    assert summary['firered']['worker_pids'] == [42]
    assert summary['firered']['segment_count'] == 2


def test_completion_without_start_does_not_invent_process():
    summary = summarize_model_events([dict(event='MODEL_COMPLETED', model_id='moss', segment_count=50)])
    assert summary['moss']['completed'] and not summary['moss']['started']
    assert summary['moss']['worker_pids'] == []


def test_review_role_does_not_merge_distinct_models():
    events = [dict(event='MODEL_STARTED', model_id='QWEN3-ASR', backend='qwen3-asr', pid=1),
        dict(event='MODEL_COMPLETED', model_id='qwen3-asr', backend='whisper_turbo', segment_count=4)]
    assert set(summarize_model_events(events)) == {'qwen3-asr', 'whisper-turbo'}
    assert canonical_model_id('qwen-audio-3.1-asr-flash-filetrans') != canonical_model_id('QWEN3-ASR')
    assert canonical_model_id('BerLIN') == 'BerLIN'


def test_pipeline_summary_uses_the_same_reducer():
    from moss_firered_pipeline import _model_stage_summary
    events = [dict(event='MODEL_SELECTED', model_id='firered'),
        dict(event='asr_worker_started', model_id='FIRERED', pid=9),
        dict(event='MODEL_COMPLETED', model_id='firered', segment_count=1)]
    legacy = SimpleNamespace(task_reporting=SimpleNamespace(active_media_report=lambda: {'events': events}))
    assert _model_stage_summary(legacy) == summarize_model_events(events)
