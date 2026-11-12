"""Replay ace6's four original answers; optionally dispatch only bounded corrections."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(output, real=False, real_settings=None, fixture_path=None):
    output.mkdir(parents=True,exist_ok=False)
    os.environ['TWOBYTEASR_TEST_ROOT']=str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core as core
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.subtitle_rules.grouping_quality import quality_for_segments
    from twobyteasr.subtitle_rules.ai_boundary_policy import inspect,windows
    from twobyteasr.subtitle_rules.grouping_quality_request import QualityRetryBudget
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers.ai_providers import provider_for_stage
    from twobyteasr.recognition.pipeline_runtime import finalize_cues
    fixture=json.loads((Path(fixture_path) if fixture_path else ROOT/'tests/fixtures/grouping_contract/luoke_ace6.json').read_text('utf-8'))
    settings={'models':{'ai_service':'custom','provider_profiles':{'custom':{
        'base_url':'http://127.0.0.1:1/v1','model':'recorded-ace6'}}}}
    if real:
        settings=real_settings
    snapshot=resolve_provider_snapshot(settings)
    remote=provider_for_stage(snapshot.execution_settings(),'group') if real else None
    rows=core.deserialize_segments(fixture['segments']);original=copy.deepcopy(rows)
    tokens=fixture['acoustic_tokens'];events=[];requests=[]
    def record(event,**kw):events.append(dict(event=event,**kw))
    def complete(messages,**options):
        body=json.loads(messages[1]['content'])
        retry='failed_constraints' in body
        request=dict(batch=options.get('batch_index'),retry=retry,body=body,real_request=real and retry)
        requests.append(request)
        if retry:
            if real:
                try:
                    answer=remote.complete(messages,**options)
                except Exception as exc:
                    from twobyteasr.providers.provider_diagnostics import redact_diagnostics
                    request['error']=redact_diagnostics(str(exc))
                    request['exception_type']=type(exc).__name__
                    raise
            else:
                saved=next((r for r in fixture.get('recorded_corrections',[]) if
                    r['body']['source_text']==body['source_text']),None)
                answer=saved['response'] if saved else json.dumps({'boundaries':body['current_boundaries']})
            request['response']=answer
            return answer
        ids=[s['id'] for s in body['segments']]
        batch=next(b for b in fixture['batches'] if b['source_segment_ids']==ids)
        if body['source_text']!=batch['source_text']:
            raise ValueError('Fixed source mismatch')
        answer=json.dumps({'boundaries':batch['model_boundaries']},separators=(',',':'))
        request['response_sha256']=hashlib.sha256(answer.encode()).hexdigest()
        if request['response_sha256']!=batch['raw_response_sha256']:
            raise ValueError('Fixed answer mismatch')
        return answer
    context=RuntimeContext(task_language='zh',requested_language='zh',enable_domain_terms=False,provider_snapshot=snapshot)
    with language_scope('zh'),activate_runtime_context(context,legacy=core),patch.object(
            grouping,'provider_for_stage',return_value=SimpleNamespace(complete=complete)),patch.object(
            grouping,'record_run_event',side_effect=record),patch.object(core,'record_run_event',side_effect=record),patch.object(
            grouping,'_clear_short_utterance',return_value=False),patch.object(grouping,'GROUP_API_BATCH_MAX_CUES',32),patch.object(
            grouping,'QualityRetryBudget',side_effect=lambda:QualityRetryBudget(requests=2) if real else QualityRetryBudget()):
        cues=grouping.group_subtitles(rows,tokens,use_ai=True,provider_snapshot=snapshot,max_workers=1)
        texts=[c.text for c in cues]
        before=copy.deepcopy(cues)
        frozen=[]
        for batch in fixture['batches']:
            q=quality_for_segments([s for s in rows if s.segment_id in batch['source_segment_ids']],tokens,
                                   protected=batch['protected_source_offsets'])
            bad=windows(q,batch['model_boundaries'])
            for a,b in zip([0,*batch['model_boundaries']],batch['model_boundaries']):
                if not any(x<b and a<y for x,y in bad):
                    frozen.append(q.index.slice(a,b))
        final=finalize_cues(cues,rows,tokens,[],fixture['audio_seconds'],60,core)
        checks=dict(four_primary_answers=sum(not r['retry'] for r in requests)==4,
            accepted_regions_frozen=all(text in texts for text in frozen),
            qualified_guangdong_predecessor='哎其实广东工业大学这边' in texts,
            forbidden_borrow=not any('这边每次抓' in text for text in texts),
            no_downstream_text_change=[c.text for c in final]==[c.text for c in before],
            immutable_sources=rows==original,all_at_most_14=all(core.display_length(c.text)<=14 for c in cues),
            short_responses=all(text in texts for text in ('好','是的')))
        payload=dict(passed=all(checks.values()),checks=checks,job_id=fixture['job_id'],
            real_correction_requests=sum(r['real_request'] for r in requests),
            real_correction_responses=sum(r['real_request'] and bool(r.get('response')) for r in requests),
            simulated_correction_requests=sum(r['retry'] and not r['real_request'] for r in requests),
            requests=requests,events=events,origin=cues.origin,result_status=cues.result_status,
            cues=core.serialize_cues(cues),final_cues=core.serialize_cues(final),
            reviews=context.review_items,provider=dict(provider=snapshot.provider,model=snapshot.model))
        (output/'replay.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),'utf-8')
    print(json.dumps({k:v for k,v in payload.items() if k in {'passed','checks','real_correction_requests','simulated_correction_requests','origin','result_status','provider'}},ensure_ascii=False))
    return 0 if payload['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--real',action='store_true')
    args=parser.parse_args()
    if args.real:
        # Read the real configuration and encrypted vault before installing
        # isolation; keep credentials solely in memory throughout this probe.
        from twobyteasr.storage.settings import load_runtime_settings,stable_settings_root
        from twobyteasr.providers import llm_config
        actual_settings,_,_=load_runtime_settings(stable_settings_root())
        vault=llm_config._read_secrets(read_only_path=llm_config.secrets_path())
        with patch.object(llm_config,'_read_secrets',return_value=vault):
            code=run(args.output.resolve(),True,actual_settings)
        raise SystemExit(code)
    raise SystemExit(run(args.output.resolve()))
