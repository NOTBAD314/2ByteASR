"""Bounded Stage-9-only replay. Existing settings/cache are strictly read-only."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('inspect','longest','all','cache-only'),required=True)
    parser.add_argument('--polished',type=Path,required=True)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,choices=(1,2),default=1)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    sys.dont_write_bytecode=True
    output=args.output.resolve()
    if not output.is_relative_to(root/'tmp'):
        raise SystemExit('Replay output must be under workspace tmp')
    output.mkdir(parents=True,exist_ok=True)

    from twobyteasr import settings as settings_module
    from twobyteasr.asr_provider_snapshot import resolve_provider_snapshot
    settings_path=(args.settings or settings_module.project_settings_path()).resolve()
    settings_bytes=settings_path.read_bytes()
    raw_settings=json.loads(settings_bytes)
    settings,_=settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS,raw_settings)
    snapshot=resolve_provider_snapshot(settings)
    # Never alter the user's provider to make an experiment pass.
    identity=snapshot.public_identity()
    summary={'mode':args.mode,'snapshot':identity,'settings_path':str(settings_path),
             'settings_sha256':hashlib.sha256(settings_bytes).hexdigest(),
             'provider_requests':0,'workers':args.workers,'stage_1_to_8_runs':0}
    if snapshot.kind!='http' or snapshot.transport!='openai_compatible' or snapshot.provider!='deepseek':
        summary['blocked']='Current active profile is not DeepSeek HTTP; no requests made'
        (output/(args.mode+'-result.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False))
        return 2
    source_bytes=args.polished.read_bytes()
    payload=json.loads(source_bytes)
    summary['polished_sha256']=hashlib.sha256(source_bytes).hexdigest()
    summary['source_segments']=len(payload['data'])
    summary['key_present']=bool(snapshot.endpoint()['api_key'])
    if args.mode=='inspect':
        (output/'inspect-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False))
        return 0
    if not snapshot.endpoint()['api_key']:
        raise SystemExit('The selected DeepSeek profile has no credential; no requests made')

    # Credentials remain solely in the private in-memory snapshot. No user
    # settings/credential file is copied, saved, migrated, or modified.
    for key,folder in (('LOCALAPPDATA','local'),('APPDATA','roaming'),('TEMP','temp'),('TMP','temp')):
        p=output/folder;p.mkdir(exist_ok=True);os.environ[key]=str(p)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    settings_module.load_runtime_settings=lambda *a,**k:(copy.deepcopy(settings),str(output/'memory-only-settings.json'),[])
    import subtitle_core as core
    from twobyteasr import grouping, ai_providers
    from twobyteasr.service import CancellationToken
    from twobyteasr.runtime import RuntimeContext,activate_runtime_context
    from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
    import requests

    def forbidden_cli(**kwargs):
        raise RuntimeError('CLI is forbidden in this Stage9-only replay')
    ai_providers.GrokCLIProvider=forbidden_cli
    ai_providers.AntigravityCLIProvider=forbidden_cli
    original_request=requests.sessions.Session.request
    counter_lock=threading.Lock()
    def guarded_request(self,method,url,*a,**kw):
        if args.mode=='cache-only':
            raise RuntimeError('Provider request forbidden during cache-only verification')
        if urlsplit(url).hostname != urlsplit(snapshot.endpoint()['url']).hostname:
            raise RuntimeError('Unexpected endpoint in Stage9-only replay')
        with counter_lock:
            summary['provider_requests']+=1
        return original_request(self,method,url,*a,**kw)
    requests.sessions.Session.request=guarded_request
    rows=core.deserialize_segments(payload['data'])
    batches=[]
    speakers={}
    for row in sorted(rows,key=lambda x:(x.start,x.end,x.segment_id)):
        speakers.setdefault(row.speaker or 'S00',[]).append(row)
    for speaker,items in speakers.items():
        for batch in core.split_items_for_api(items,max_cues=core.GROUP_API_BATCH_MAX_CUES,max_chars=core.GROUP_API_BATCH_MAX_CHARS):
            batches.append((speaker,batch))
    summary['batch_input_characters']=[sum(len(x.text) for x in batch) for _,batch in batches]
    if args.mode=='longest':
        index=max(range(len(batches)),key=lambda i:sum(len(x.text) for x in batches[i][1]))
        rows=batches[index][1]
        summary['selected_original_batch']=index+1
    elif args.mode=='all' and len(batches)!=7:
        raise SystemExit('Expected exactly 7 cached-input batches; stopped before request')
    cache_dir=output/'cache';cache_dir.mkdir(exist_ok=True)
    cache_context={'cache_dir':str(cache_dir),'identity':payload['identity']}
    events=[]
    token=CancellationToken()
    context=RuntimeContext(provider_snapshot=snapshot,cancellation_token=token,event_log_path=str(output/(args.mode+'-events.jsonl')))
    timer=threading.Timer(90,token.cancel)
    grouping.GROUPING_API_RETRIES=1  # one observable attempt per diagnostic batch
    started=time.monotonic()
    timer.start()
    try:
        with activate_runtime_context(context,legacy=core),core.run_event_observer(lambda event,data:events.append({'event':event,**data})):
            cues=core.group_subtitles(rows,cache_context=cache_context,provider_snapshot=snapshot,max_workers=args.workers)
            expected={}
            actual={}
            for row in rows:expected.setdefault(row.speaker or 'S00',[]).append(row.text)
            for cue in cues:actual.setdefault(cue.speaker or 'S00',[]).append(cue.text)
            summary['text_exact']=({k:''.join(v) for k,v in expected.items()}=={k:''.join(v) for k,v in actual.items()})
            summary['result_origin']=getattr(cues,'origin',None)
            summary['validated']=getattr(cues,'validated',False)
            (output/(args.mode+'-cues.json')).write_text(json.dumps(core.serialize_cues(cues),ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as exc:
        from twobyteasr.asr_provider_snapshot import classify_request_error
        summary['error_category']=classify_request_error(exc)
        summary['error_type']=type(exc).__name__
    finally:
        timer.cancel()
        token.cancel()
        summary['provider_idle']=GLOBAL_PROVIDER_SERVICE.wait_for_idle(2)
        summary['elapsed_seconds']=round(time.monotonic()-started,3)
        summary['cache_hits']=sum(x['event']=='cache_hit' and x.get('stage')=='grouped_batch' for x in events)
        summary['cache_misses']=sum(x['event']=='CACHE_REJECTED' and x.get('stage')=='grouped_batch' for x in events)
        summary['fallback_batches']=sum(x['event']=='cloud_batch_completed' and x.get('result_origin')=='fallback' for x in events)
        summary['attempts']=[x for x in events if x['event']=='asr_provider_request']
        summary['settings_unchanged']=settings_path.read_bytes()==settings_bytes
        summary['polished_unchanged']=args.polished.read_bytes()==source_bytes
        (output/(args.mode+'-result.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k!='attempts'},ensure_ascii=False))
    return 0 if summary.get('text_exact') and summary.get('validated') and not summary.get('error_category') else 1


if __name__=='__main__':
    raise SystemExit(main())
