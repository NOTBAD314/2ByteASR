from types import SimpleNamespace
from twobyteasr.recognition.run_context import RuntimeContext,sync_legacy_runtime


def test_resume_rebinds_reviews_and_retains_failed_polish_counts(monkeypatch):
    from twobyteasr.recognition import delivery_checkpoint,pipeline_runtime
    context=RuntimeContext()
    context.task_journal=SimpleNamespace(record={'task':{'remote_requests':{}}})
    legacy=SimpleNamespace(task_reporting=SimpleNamespace(_active_report={}),
        deserialize_cues=lambda rows:rows,deserialize_segments=lambda rows:rows,record_run_event=lambda *a,**k:None)
    sync_legacy_runtime(legacy,context)
    captured={}
    def finish(**kwargs):
        captured['reviews']=list(legacy.RUN_REVIEW_ITEMS)
        captured['report']=legacy.task_reporting._active_report
        return 'done'
    monkeypatch.setattr(pipeline_runtime,'complete_media_run',finish)
    review={'category':'校对回退','severity':'warning'}
    result=delivery_checkpoint.resume(context,legacy,{'arguments':{'cues':[],'segments':[]},
        'context':{'review_items':[review],'polishing_summary':{'success_batches':40,'fallback_batches':6,'fallback_cues':68}},
        'report':{'status':'interrupted'},'translation':{}})
    assert result=='done' and captured['reviews']==[review]
    assert captured['report']['polishing_summary']['fallback_batches']==6
