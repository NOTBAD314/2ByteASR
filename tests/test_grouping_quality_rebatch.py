import json
from types import SimpleNamespace
import pytest
import subtitle_core as core
from twobyteasr.subtitle_rules import grouping
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context


@pytest.mark.parametrize('always_bad',[False,True])
def test_only_rejected_large_batch_gets_one_smaller_attempt(monkeypatch,always_bad):
    calls=[]
    def complete(messages,**kwargs):
        data=json.loads(messages[-1]['content']);count=len(data['segments']);calls.append(count)
        if count>16 or always_bad:return json.dumps(dict(boundaries=[data['total_length']],segmented_text='改写'))
        return json.dumps(dict(boundaries=data['source_segment_offsets']+[data['total_length']]))
    monkeypatch.setattr(grouping,'GROUPING_API_RETRIES',1)
    monkeypatch.setattr(grouping,'SECOND_PASS_GROUP_VALIDATION',False)
    monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    snapshot=resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'fixture'}}}})
    rows=[core.SpeechSegment(i+1,i*2.,i*2.+1.5,'今日は海を見ます',.9,[],speaker='S01') for i in range(32)]
    with activate_runtime_context(RuntimeContext(task_language='ja',requested_language='ja'),legacy=core):
        result=grouping.call_grouping_api(rows,provider_snapshot=snapshot,_packed=True,batch_index=1)
    assert calls==[32,16,16]
    assert ''.join(c.text for c in result)==''.join(row.text for row in rows)
    assert result.validated is (not always_bad)
    assert result.origin==('fallback' if always_bad else 'ai')
