import json
from dataclasses import replace

import pytest
from tests.test_stage9_cache_and_budget import context


def segment(core, index=1, text="这里已经校对完成"):
    return core.SpeechSegment(index, 0, 2, text, .9, [], speaker="S01")


def test_stage8_stage9_preflight_share_snapshot_despite_stale_modules(context, monkeypatch):
    from twobyteasr.subtitle_rules import grouping, polishing
    from twobyteasr.providers import ai_providers
    import moss_firered_pipeline as pipeline
    core, ctx, cache = context
    calls=[]
    records=[]
    monkeypatch.setattr(core, "record_run_event", lambda event, **kw: records.append((event,kw)))
    for mod in (grouping,polishing):
        monkeypatch.setattr(mod, "record_run_event", lambda event, **kw: records.append((event,kw)))
    monkeypatch.setattr(grouping,"RUNTIME_SETTINGS",{"models":{"group_transport":"grok_cli"}})
    monkeypatch.setattr(core,"RUNTIME_SETTINGS",{"models":{"ai_service":"grok_account"},"switches":{}})
    monkeypatch.setattr(ai_providers,"GrokCLIProvider",lambda **k: pytest.fail("stale CLI constructed"))
    def sender(messages, **kwargs):
        calls.append(kwargs)
        data=json.loads(messages[-1]['content'])
        return json.dumps({'checked_ids':[cue['id'] for cue in data['cues']],'cues':[]}) if kwargs['stage']=='polished' else json.dumps({'boundaries':[data['total_length']]})
    monkeypatch.setattr(polishing,"post_chat_completion",sender)
    monkeypatch.setattr(grouping,"post_chat_completion",sender)
    # Production polish progress uses the SSE adapter boundary. Keep that
    # boundary isolated too; replacing only its non-streaming sender is stale.
    monkeypatch.setattr('twobyteasr.providers.llm_adapter.post_chat_completion_stream', sender)
    pipeline._preflight_cloud_stages(core)
    row=segment(core)
    polished=polishing.call_correction_api([row], [], "", "", "test", "", [], [], [])
    assert polished.succeeded == {row.segment_id} and not polished.failures
    result=grouping.call_grouping_api([row],provider_snapshot=ctx.provider_snapshot)
    assert result.validated and ''.join(c.text for c in result)==row.text
    assert len(calls)==2
    assert {x['model'] for x in calls}=={'deepseek-v4-pro'}
    assert {x['url'] for x in calls}=={'https://api.deepseek.com/v1/chat/completions'}
    requests=[x for event,x in records if event=='asr_provider_request']
    assert {x['provider_snapshot_fingerprint'] for x in requests}=={ctx.provider_snapshot.fingerprint}
    assert len([x for event,x in records if event=='asr_provider_snapshot'])==2


def test_production_group_second_run_has_zero_provider_requests(context, monkeypatch):
    from twobyteasr.subtitle_rules import grouping
    core,ctx,cache=context
    calls=[]
    def sender(messages, **kwargs):
        calls.append(1)
        return json.dumps({'boundaries':[json.loads(messages[-1]['content'])['total_length']]})
    monkeypatch.setattr(grouping,'post_chat_completion',sender)
    rows=[segment(core)]
    first=grouping.group_subtitles(rows,cache_context=cache,max_workers=1)
    assert first.validated and len(calls)==1
    second=grouping.group_subtitles(rows,cache_context=cache,max_workers=1)
    assert second.validated and len(calls)==1
    assert ''.join(c.text for c in second)==rows[0].text


def test_production_boundaries_preserve_spaces_and_punctuation(context, monkeypatch):
    from twobyteasr.subtitle_rules import grouping
    core,ctx,_=context
    monkeypatch.setattr(grouping,'GROUPING_API_RETRIES',1)
    monkeypatch.setattr(grouping,'post_chat_completion',lambda messages,**kwargs: json.dumps({'boundaries':[2,json.loads(messages[-1]['content'])['total_length']]}))
    rows=[segment(core,text='你好，  世界！')]
    result=grouping.call_grouping_api(rows,provider_snapshot=ctx.provider_snapshot)
    assert result.validated
    assert ''.join(c.text for c in result)==rows[0].text


@pytest.mark.parametrize('body,category',[('', 'empty_response'),('not JSON','parse_failure'),('{}','format_mismatch'),
    ('{"boundaries":[999]}','boundary_range'),('{"segmented_text":"改字","boundaries":[8]}','text_mutation_rejected')])
def test_invalid_outputs_are_explicit_fallback_never_ai(context,monkeypatch,body,category):
    from twobyteasr.subtitle_rules import grouping
    core,ctx,cache=context
    records=[]
    monkeypatch.setattr(grouping,'GROUPING_API_RETRIES',1)
    monkeypatch.setattr(grouping,'post_chat_completion',lambda *a,**k:body)
    monkeypatch.setattr(grouping,'record_run_event',lambda event,**kw:records.append((event,kw)))
    result=grouping.call_grouping_api([segment(core)],provider_snapshot=ctx.provider_snapshot)
    assert result.origin=='fallback' and not result.validated
    request=next(x for event,x in records if event=='asr_provider_request')
    assert request['fallback_reason']==category
    assert request['result_origin']=='failed_attempt'
