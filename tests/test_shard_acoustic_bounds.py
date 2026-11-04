from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
from twobyteasr.recognition.alignment_audio import bounded_jobs


def test_padded_model_jobs_do_not_claim_an_unrelated_native_request():
    context=RuntimeContext(shard_bounds=(100.,120.))
    original=[dict(id='left',text='はい',window_start_ms=99700,window_end_ms=105000),
              dict(id='right',text='ありがとう',window_start_ms=117000,window_end_ms=120300)]
    with activate_runtime_context(context):
        jobs=bounded_jobs(original)
    assert jobs[0]['window_start_ms']==100000
    assert jobs[1]['window_end_ms']==120000
    assert original[0]['window_start_ms']==99700
