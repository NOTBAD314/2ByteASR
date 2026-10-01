"""Authorized real provider trial, isolated from application settings and projects."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--settings',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--service',default='deepseek');p.add_argument('--prompt',default='balatro小丑牌风格')
    p.add_argument('--text',default='收看嗯');p.add_argument('--seconds',type=int,default=1800)
    p.add_argument('--game-frame',type=Path)
    p.add_argument('--review-with-agy',action='store_true',help='Explicit separate image reviewer before full animation')
    p.add_argument('--call-budget',type=int,default=16)
    p.add_argument('--prepare-only',action='store_true',help='Save the exact first request without any network call')
    args=p.parse_args();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():raise ValueError('Use a fresh repository tmp directory')
    out.mkdir(parents=True)
    from twobyteasr.settings import DEFAULT_SETTINGS,_merge_known_settings
    from twobyteasr.llm_config import activate_ai_service,endpoint_from_settings
    from twobyteasr.provider_registry import GLOBAL_PROVIDER_REGISTRY
    raw=args.settings.read_bytes();settings,_=_merge_known_settings(DEFAULT_SETTINGS,json.loads(raw))
    activate_ai_service(settings,args.service)
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    endpoint=endpoint_from_settings(settings,'polish')
    # Resolve DPAPI only in memory before isolating all writable runtime paths.
    for key in ('polish_api_key','group_api_key'):settings['models'][key]=endpoint.get('api_key','')
    for key,value in [('LOCALAPPDATA','local'),('APPDATA','roaming'),('TMP','temp'),('TEMP','temp')]:
        (out/value).mkdir(exist_ok=True);os.environ[key]=str(out/value)
    settings['models']['ai_design_wait_mode']='configured'
    settings['models']['ai_design_cli_timeout_seconds']=args.seconds
    from twobyteasr.caption_creative_pipeline import request_creative_options
    if args.prepare_only:
        from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
        class PreparedOnly(Exception):pass
        class PreviewClient:
            def capabilities(self):return SimpleNamespace(vision=False)
            def invocation_trace(self):return {'external_calls':0}
            def complete(self,messages,**kwargs):
                payload={'destination':endpoint.get('base_url'),'provider':selection.provider,'model':selection.model,
                    'messages':messages,'schema':kwargs.get('json_schema'),'max_tokens':kwargs.get('max_tokens')}
                (out/'external-request-preview.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),'utf8')
                raise PreparedOnly('Request prepared; no network or provider process invoked')
        GLOBAL_PROVIDER_SERVICE.client_for_stage=lambda *a,**k:PreviewClient()
    cue=SimpleNamespace(id='trial-cue',text=args.text,start_ms=0,end_ms=6000)
    project=SimpleNamespace(cues=[cue],media=SimpleNamespace(width=1920,height=1080),render_settings={'fps':60})
    record=dict(provider=selection.provider,model=selection.model,service=args.service,prompt=args.prompt,text=args.text,
        settings_path=str(args.settings),settings_sha256=hashlib.sha256(raw).hexdigest(),total_budget_seconds=args.seconds,
        started_at=time.time(),status='running',first_usable_preview_seconds=None,actual_cost_usd=None)
    started=time.monotonic()
    def save(): (out/'trial.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf8')
    def event(e):
        with (out/'events.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(e,ensure_ascii=False)+'\n')
        if e['name']=='candidate_complete':
            if record['first_usable_preview_seconds'] is None and any(c.get('motion_preview') for c in e.get('partial_concepts',[])):
                record['first_usable_preview_seconds']=time.monotonic()-started
            record['candidate_states']=e['candidate_states'];save()
            print(json.dumps({'stage':e['name'],'candidate':e['candidate_id'],'elapsed':round(time.monotonic()-started,2)},ensure_ascii=False),flush=True)
    save()
    if not args.prepare_only:
        from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
        factory=GLOBAL_PROVIDER_SERVICE.client_for_stage
        record.update(call_budget=args.call_budget,external_calls=0)
        def bounded_client(*a,**kw):
            client=factory(*a,**kw);complete=client.complete
            def bounded_complete(messages,**options):
                if record['external_calls']>=args.call_budget:raise ValueError('本轮真实请求预算已用尽，保留现有证据')
                record['external_calls']+=1;save()
                return complete(messages,**options)
            client.complete=bounded_complete
            return client
        GLOBAL_PROVIDER_SERVICE.client_for_stage=bounded_client
    reviewer=None
    if args.review_with_agy:
        from review_theme_keyframes import agy_review
        def reviewer(proof):
            return agy_review(proof,Path(proof['frames'][0]['path']).parent/'agy-review')
    try:
        result=request_creative_options(project,cue.id,args.prompt,settings,ledger_root=out/'creative',
            request_id=out.name,stage_event_callback=event,deadline_seconds=args.seconds,
            reference_frames=[str(args.game_frame.resolve())] if args.game_frame else (),keyframe_review=reviewer)
        (out/'concepts.json').write_text(json.dumps(result.concepts,ensure_ascii=False,indent=2),'utf8')
        record.update(status='complete',usable=sum(bool(c.get('motion_preview')) and c.get('technical_status')!='failed' for c in result.concepts),
            candidates=[dict(id=c['id'],name=c['name'],technical=c.get('technical_status','passed'),
                errors=c.get('technical_errors',[]),ledger=c['ledger_path']) for c in result.concepts])
    except Exception as exc:record.update(status='prepared' if args.prepare_only else 'failed',category=getattr(exc,'category','generation_error'),error=str(exc)[:1500])
    finally:
        record.update(total_seconds=time.monotonic()-started,settings_unchanged=args.settings.read_bytes()==raw);save()
    print(json.dumps(record,ensure_ascii=False,indent=2))
    return 0 if record['status'] in {'complete','prepared'} else 1

if __name__=='__main__':sys.exit(main())
