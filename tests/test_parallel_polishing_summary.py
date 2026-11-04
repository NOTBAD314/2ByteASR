from types import SimpleNamespace
from twobyteasr.recognition.streaming_recognition import aggregate_polishing


def test_last_successful_shard_cannot_erase_previous_failures():
    rows=[SimpleNamespace(index=0,reviews=[{'category':'校对回退'}],polishing_summary={
        'success_batches':14,'fallback_batches':1,'success_cues':281,'fallback_cues':1,
        'fallback_ids':[12],'failure_records':{'12':'schema_error'}}),
        SimpleNamespace(index=1,reviews=[],polishing_summary={'success_batches':15,'fallback_batches':0,
        'success_cues':330,'fallback_cues':0})]
    total=aggregate_polishing(rows)
    assert total['status']=='partial' and total['fallback_cues']==1
    assert total['success_cues']==611 and total['fallback_ids']==[1000012]
    assert total['failure_records']=={'1000012':'schema_error'}


def test_verified_complete_cached_shard_has_no_fabricated_batch_count():
    total=aggregate_polishing([SimpleNamespace(index=0,reviews=[],polishing_summary={})])
    assert total['status']=='completed' and total['cached_complete_shards']==1
    assert total['success_batches']==0
