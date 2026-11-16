import pytest
from tests.test_ai_failure_escalation import context, observed
from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import grouping

def test_partly_rescued_batch_retains_fallback_badge(context,monkeypatch,observed):
    _,ctx,_=context
    monkeypatch.setattr(ctx,'task_language','zh')
    def fake(batch,**kw):
        high=kw['provider_snapshot'].enable_thinking=='high'
        success=high and batch[0].segment_id==1
        if not success:
            kw['batch_diagnostics']['fallback_reason']='parse_failure'
            grouping.add_review_item(batch[0].start,'断句回退','fixture',batch[0].text,priority=3,severity='warning')
        return GroupedBatchResult([grouping.individual_cue(x) for x in batch],
                                  origin='ai' if success else 'fallback',validated=success)
    monkeypatch.setattr(grouping,'call_grouping_api',fake)
    rows=[SpeechSegment(i,i*2.,i*2.+2,f'这一波第{i}次团战我们继续看看双方怎么处理',.9,[],speaker='S01') for i in range(1,5)]
    grouping.group_subtitles(rows,use_ai=True,provider_snapshot=ctx.provider_snapshot)
    done=[data for name,data in observed if name=='ai_escalation_round' and data.get('state')=='completed'][-1]
    assert done['resolved_batches']==[] and done['remaining_fallback_batches']==1
    assert any(item.get('category')=='断句回退' for item in ctx.review_items)
