import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.test_stage9_provider_snapshot import config


@pytest.fixture
def context(monkeypatch, tmp_path):
    import subtitle_core as core
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("fixture", "test"))
    snap = resolve_provider_snapshot(config())
    ctx = RuntimeContext(provider_snapshot=snap, event_log_path=str(tmp_path / "events.jsonl"))
    with activate_runtime_context(ctx, legacy=core):
        yield core, ctx, {"cache_dir": str(tmp_path), "identity": {"hash": "fixture"}}


def test_verified_ai_cache_hit_legacy_miss_and_partial_recovery(context):
    from twobyteasr.recognition.cache import run_cached_api_batch
    from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
    core, ctx, cache = context
    calls = []
    segments = [SimpleNamespace(text="你好世界")]
    def runner():
        calls.append(1)
        return GroupedBatchResult([core.SubtitleCue(1, 0, 1, "你好世界")], validated=True)
    def execute(dep, producer=runner):
        return run_cached_api_batch("grouped", cache, dep, producer,
            encoder=core.serialize_cues, decoder=core.deserialize_cues,
            provider_snapshot=ctx.provider_snapshot,
            validator=lambda cues: "".join(c.text for c in cues) == "你好世界")
    first = execute({"speaker": "S1", "content": "你好世界", "boundaries": [4]})
    second = execute({"speaker": "S1", "content": "你好世界", "boundaries": [4]})
    assert len(calls) == 1 and second.cache_hit
    def fallback():
        calls.append(0)
        return GroupedBatchResult(first, origin="fallback")
    execute({"speaker": "S2"}, fallback)
    execute({"speaker": "S2"})
    assert calls == [1, 0, 1]
    ctx.provider_snapshot = replace(ctx.provider_snapshot, protocol="responses")
    execute({"speaker": "S2"})
    assert calls == [1, 0, 1, 1]
    payloads = [json.loads(p.read_text(encoding="utf-8")) for p in __import__('pathlib').Path(cache['cache_dir']).glob('api_batches/grouped/*.json')]
    assert all(p['producer'] == 'ai' and p['validation'] == 'source_contract_v1' for p in payloads)


def test_mutated_ai_cannot_be_cached(context):
    from twobyteasr.recognition.cache import run_cached_api_batch
    from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
    core, ctx, cache = context
    calls=[]
    def run():
        calls.append(1)
        return GroupedBatchResult([core.SubtitleCue(1, 0, 1, "改字")], validated=True)
    for _ in range(2):
        with pytest.raises(ValueError, match="未通过来源契约"):
            run_cached_api_batch('grouped', cache, {'text':'原文'}, run,
            encoder=core.serialize_cues, decoder=core.deserialize_cues,
            provider_snapshot=ctx.provider_snapshot, validator=lambda values: values[0].text == '原文')
    assert len(calls)==2


def test_queue_does_not_consume_request_budget(monkeypatch):
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot, TimeoutPolicy
    from twobyteasr.providers import llm_config
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture','test'))
    snap=resolve_provider_snapshot(config(), timeout_policy=TimeoutPolicy(.2,.5,.5,1))
    seen=[]
    def send(*args, **kwargs):
        seen.append(kwargs['timeout'])
        if len(seen)==1:time.sleep(.15)
        return '{}'
    service=ProviderService(workers=1)
    client=service.client_for_stage(snap.execution_settings(),'group',sender=send)
    one=client.submit([],timeout=.5,_timeout_policy=snap.timeout_policy,request_diagnostics={})
    diag={}
    two=client.submit([],timeout=.5,_timeout_policy=snap.timeout_policy,request_diagnostics=diag)
    assert one.result(2)=='{}' and two.result(2)=='{}'
    assert diag['queue_wait_ms'] >= 100
    assert isinstance(seen[1],tuple) and seen[1][1] > .4
    assert service.wait_for_idle(1)


def test_queue_timeout_has_its_own_diagnostic(context):
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
    from twobyteasr.providers.ai_providers import AIProviderError
    _,ctx,_=context
    service=ProviderService(workers=1)
    entered=threading.Event()
    def sender(*a,**k):
        entered.set();time.sleep(.15);return '{}'
    client=service.client_for_stage(ctx.provider_snapshot.execution_settings(),'group',sender=sender)
    first=client.submit([],timeout=.5,_timeout_policy=TimeoutPolicy(.1,.5,.5,1),request_diagnostics={})
    assert entered.wait(1)
    diag={}
    with pytest.raises(AIProviderError) as error:
        client.complete([],timeout=.5,_timeout_policy=TimeoutPolicy(.1,.5,.5,.03),request_diagnostics=diag)
    assert error.value.category=='queue_timeout' and diag['queue_wait_ms']>=25
    assert first.result(1)=='{}'
    assert service.wait_for_idle(1)


def test_whole_group_cache_preserves_legacy_file(context):
    from pathlib import Path
    from twobyteasr.recognition.cache import run_cached_stage
    from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
    core,ctx,cache=context
    old=Path(cache['cache_dir'])/'grouped.json';old.write_text('legacy evidence',encoding='utf-8')
    calls=[]
    def run():
        calls.append(1)
        return GroupedBatchResult([core.SubtitleCue(1,0,1,'你好',speaker='S01')],validated=True)
    for _ in range(2):
        result=run_cached_stage('grouped',cache,run,encoder=core.serialize_cues,decoder=core.deserialize_cues,
            extra_signature={'segments':[{'id':1,'text':'你好','speaker':'S01','start':0,'end':1}]})
        assert result[0].text=='你好'
    assert calls==[1] and old.read_text(encoding='utf-8')=='legacy evidence'
