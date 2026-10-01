"""Inspect or replay explicitly authorized historical authored-source failures.

Credentials are resolved in memory from the existing store. No credential or
settings file is copied; all outputs belong to a fresh repository tmp folder.
"""
import argparse,copy,hashlib,json,os,sys,time
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--request-id',choices=['cfd03cec2bc546fe9dd13dd5acd1589a','fbbc674ba397498e8d0d0c91ba017d81'],required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):raise ValueError('Fresh repository tmp output required')
    out.mkdir(parents=True)
    original_local=Path(os.environ['LOCALAPPDATA'])
    source=original_local/'2ByteASR/SubtitleStudioPreview/logs/theme-drafts'/args.request_id
    original=(source/'creative/provider-original.txt').read_bytes();original_hash=hashlib.sha256(original).hexdigest()
    from twobyteasr.caption_creative_pipeline import ThemeLedger,accept_authored_set
    from twobyteasr.web_theme_compiler import parse_object
    from twobyteasr.authored_repair import collect_issues,provider_callbacks
    metadata=json.loads((source/'request.json').read_text('utf8'))
    old_ledger=json.loads((source/'creative/ledger.json').read_text('utf8'))
    payload=parse_object(original.decode('utf-8-sig'))
    from twobyteasr.theme_metadata import normalize_theme_input
    for index,row in enumerate(payload['candidates']):
        row['generated_source']=normalize_theme_input(row['generated_source'],path=f'candidates[{index}].generated_source')
    safe_prompt=old_ledger.get('theme','Balatro')+' 游戏字幕；保持指定历史候选的设计意图，仅修复技术错误。'
    ledger=ThemeLedger(out/'creative',safe_prompt)
    ledger.value['historical_source']=dict(parent_request_id=args.request_id,source_sha256=original_hash,
        original_path=str(source/'creative/provider-original.txt'),replay_mode='authorized safe derivative',original_unchanged=True)
    issues=collect_issues(payload,ledger);ledger.value['aggregate_technical_errors']=issues;ledger.save()
    result=dict(request_id=args.request_id,provider=metadata['provider'],model=metadata['model'],
        source_sha256=original_hash,mode='real bounded repair' if args.execute else 'offline aggregate inspection',
        initial_issues=[{k:i.get(k) for k in ('candidate_index','path','category','repair')} for i in issues],
        model_calls=0,passed=False)
    if args.execute:
        assert metadata['provider']=='deepseek'
        from twobyteasr import settings as settings_module
        from twobyteasr.llm_config import activate_ai_service,update_active_profile,endpoint_from_settings
        from twobyteasr.ai_providers import OpenAICompatibleProvider
        settings_path=original_local/'2ByteASR'/settings_module.SETTINGS_FILENAME
        settings_bytes=settings_path.read_bytes()
        settings,_=settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS,json.loads(settings_bytes))
        settings=copy.deepcopy(settings);activate_ai_service(settings,'deepseek');update_active_profile(settings,model=metadata['model'])
        client=OpenAICompatibleProvider(endpoint_from_settings(settings,'polish'))
        assert client.endpoint['model']==metadata['model']
        for name in ('local','roaming','temp'):(out/name).mkdir()
        os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TEMP=str(out/'temp'),TMP=str(out/'temp'))
        import tempfile
        tempfile.tempdir=str(out/'temp')
        calls=[];complete=client.complete
        def counted(messages,**kwargs):
            started=time.monotonic();row=dict(operation=kwargs.get('operation_kind'),started=started,status='started')
            calls.append(row)
            try:
                value=complete(messages,**kwargs);row['status']='returned';return value
            except Exception as exc:row.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:500]);raise
            finally:
                row.update(elapsed_seconds=time.monotonic()-started,budget=getattr(client,'last_timings',{}).get('request_budget'))
                (out/'calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),'utf8')
        client.complete=counted
        patch,regenerate=provider_callbacks(client,args.request_id)
        try:
            suggestion=accept_authored_set(payload,ledger,metadata['provider'],metadata['model'],
                technical_repair=patch,candidate_regenerate=regenerate,request_id=args.request_id)
            result.update(passed=len(suggestion.concepts)==3,source_after=[c['authored_theme'] for c in suggestion.concepts])
        except Exception as exc:result['error']=str(exc)[:1500]
        result.update(calls=calls,model_calls=sum(row['status']=='returned' for row in calls),
                      settings_unchanged=settings_path.read_bytes()==settings_bytes)
    result['original_unchanged']=(source/'creative/provider-original.txt').read_bytes()==original
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_after','calls')},ensure_ascii=False))
    return 0 if result['passed'] or not args.execute else 1


if __name__=='__main__':raise SystemExit(main())
