"""Read configured 2ByteASR providers; one bounded static spec per ready adapter."""
from __future__ import annotations
import argparse
import base64
import copy
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser();parser.add_argument('--settings',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--game',type=Path,required=True)
    parser.add_argument('--request',type=Path,required=True);parser.add_argument('--inspect-only',action='store_true')
    parser.add_argument('--provider',choices=('deepseek','antigravity','grok_account','codex_cli'))
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):raise ValueError('trial output must be in repository tmp')
    out.mkdir(parents=True,exist_ok=True)
    from twobyteasr.caption_design_trials import CaptionPreferences,TrialInput,SCHEMA,validate_spec,compile_static_candidate,local_specs
    from twobyteasr.llm_config import activate_ai_service,get_provider_profiles,endpoint_from_settings,resolved_service_values
    from twobyteasr.provider_registry import ProviderRegistry
    from twobyteasr.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.provider_diagnostics import redact_diagnostics
    from twobyteasr.web_theme_compiler import parse_object
    raw=args.settings.read_bytes();settings=json.loads(raw)
    preferences=CaptionPreferences(root/'docs/design/caption-preferences.json')
    if not preferences.path.is_file():preferences.write(preferences.read())
    request=args.request.read_text('utf8')
    request=request[request.index('## P1：'):request.index('## 时间限制')]
    shared=TrialInput.capture(request,'啊感觉他就是你看',args.game,preferences)
    (out/'shared-input.json').write_text(shared.json_text,encoding='utf8')
    names=sorted(set(get_provider_profiles(settings))|{'deepseek','antigravity','grok_account','codex_cli'})
    if args.provider:names=[args.provider]
    candidates=[]
    for name in names:
        frozen=copy.deepcopy(settings);activate_ai_service(frozen,name)
        endpoint=endpoint_from_settings(frozen,'polish');selection=ProviderRegistry().selection(frozen)
        capabilities=resolved_service_values(frozen,name)['capabilities']
        # Capture the credential into this request's in-memory settings before
        # redirecting application output paths. Never serialize this object.
        for prefix in ('polish','group'):frozen['models'][prefix+'_api_key']=endpoint.get('api_key','')
        candidates.append((frozen,dict(provider=name,model=selection.model or '(CLI default)',transport=selection.transport,
            configured=bool(get_provider_profiles(settings).get(name)),credential_ready=selection.credential_ready,
            declared_capabilities=capabilities,text=True,structured_output=True,image_generation=False,
            vision_verified=False,input_fingerprint=shared.fingerprint)))
    os.environ.update(LOCALAPPDATA=str(out/'local'),APPDATA=str(out/'roaming'),TMP=str(out/'temp'),TEMP=str(out/'temp'))
    (out/'temp').mkdir(exist_ok=True)
    result={'started':datetime.now(timezone.utc).isoformat(),'input_fingerprint':shared.fingerprint,'settings_path':str(args.settings),
        'settings_sha256':hashlib.sha256(raw).hexdigest(),'providers':[],'max_concurrency':2,'request_timeout_seconds':90,
        'image_gen':'无需调用','user_selected':None,'user_rating':None}
    lock=threading.Lock()
    def save():
        (out/'leaderboard.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    def trial(pair):
        frozen,row=pair
        row.update(status='checking',attempts=[],aesthetics=None)
        if row['provider'] not in {'deepseek','antigravity','grok_account','codex_cli'}:
            row['status']='inventory_only';return row
        if row['provider']=='deepseek':
            from urllib.parse import urlsplit
            if urlsplit(endpoint_from_settings(frozen,'polish')['base_url']).hostname!='api.deepseek.com':
                row['status']='destination_not_authorized';return row
        if row['transport']=='openai_compatible' and not row['credential_ready']:
            row['status']='unconfigured_credential';return row
        client=GLOBAL_PROVIDER_SERVICE.client_for_stage(frozen,'polish')
        started=time.monotonic()
        try:
            status=client.validate(timeout=12,use_cache=False)
            row['connection']={'available':status.available,'authenticated':status.authenticated,
                'message':redact_diagnostics(status.message),'seconds':round(time.monotonic()-started,3),'models':list(status.models)}
            if not status.available or not status.authenticated:
                row['status']='not_ready';return row
            row['status']='ready'
        except Exception as exc:
            row['status']='connection_failed';row['error']=redact_diagnostics(str(exc));return row
        if args.inspect_only:return row
        runtime_capabilities=client.capabilities()
        # Registry declarations are not proof of a particular HTTP model's
        # image input. Agy and validated Codex ACP/CLI are explicit image paths.
        image_capable=row['provider']=='antigravity' or (row['provider']=='codex_cli' and runtime_capabilities.vision)
        row['image_input']='pixels' if image_capable else 'shared frame reference and written description; pixels not inspected'
        row['vision_verified']=bool(image_capable)
        instruction='只返回符合schema的一份完整JSON DesignSpec。不可写HTML/JS/文件，不可改工程，不调用工具。纯文字/框体不需要位图。你的颜色、字体、主要结构和签名效果应有明确语义。可选择非冰蓝配色。保留渐变字芯→深色内描边→浅色外描边→低透明软阴影。不要添加场景文字或无意义编号。全部提供字段。'
        common={'type':'text','text':instruction+'\n'+shared.json_text}
        content=[common]
        if image_capable:
            encoded=base64.b64encode(args.game.read_bytes()).decode()
            content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+encoded}})
        # Every adapter gets the identical immutable common input. Unsupported
        # vision is an explicit capability difference, never invented seeing.
        if row['provider']=='antigravity':
            # This adapter exposes file-based visual input, not ACP image_url.
            # Its earlier payload failed locally before any design request.
            row['image_input']='explicit shared local image path; provider must report if unreadable'
            messages=[{'role':'user','content':common['text']+'\n仅为本次视觉理解允许读取这一张已授权图片：'+str(args.game.resolve())+'。不要读取其它文件；不要修改文件。如果无法看图，明确在concept说明。'}]
        else:messages=[{'role':'user','content':content if image_capable else common['text']}]
        for attempt in range(2):
            began=time.monotonic();deadline=began+89;first=[None]
            def stream(kind,value):
                if kind in ('delta','text','partial') and value and first[0] is None:first[0]=time.monotonic()-began
            receipt={'attempt':attempt+1,'success':False,'first_token_seconds':None,'json_valid':False,'schema_valid':False,
                'html_compile_success':False,'browser_render_success':None}
            try:
                raw_result=client.complete(messages,max_tokens=2600,temperature=.35,timeout=89,
                    cancel_check=lambda:time.monotonic()>=deadline,on_stream_event=stream)
                folder=out/row['provider'];folder.mkdir(exist_ok=True)
                (folder/f'response-{attempt+1}.txt').write_text(raw_result,encoding='utf8')
                receipt['first_token_seconds']=first[0]
                if len(raw_result)>24000:raise ValueError('response exceeded character budget')
                value=parse_object(raw_result);receipt['json_valid']=True
                spec=validate_spec(value);receipt['schema_valid']=True
                html=compile_static_candidate(spec,'啊感觉他就是你看',background_path=args.game)
                receipt.update(success=True,html_compile_success=True)
                folder=out/row['provider'];folder.mkdir(exist_ok=True)
                (folder/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf8')
                (folder/'candidate.html').write_text(html,encoding='utf8')
                (folder/'transparent.html').write_text(compile_static_candidate(spec,'啊感觉他就是你看'),encoding='utf8')
                row.update(status='spec_ready',spec_path=str(folder/'spec.json'),html_path=str(folder/'candidate.html'),name=spec['name'])
            except Exception as exc:
                category=getattr(exc,'category',type(exc).__name__)
                receipt.update(error=redact_diagnostics(str(exc)),category=category)
                row['status']='failed'
            receipt['total_seconds']=round(time.monotonic()-began,3);receipt['first_token_seconds']=first[0]
            row['attempts'].append(receipt)
            if receipt['success']:break
            if attempt or not any(word in str(receipt.get('category','')).lower() for word in ('timeout','cancel')):break
        row['stability']={'request_success_rate':sum(a['success'] for a in row['attempts'])/len(row['attempts']),
            'json_valid_rate':sum(a['json_valid'] for a in row['attempts'])/len(row['attempts']),
            'schema_valid_rate':sum(a['schema_valid'] for a in row['attempts'])/len(row['attempts']),
            'html_compile_rate':sum(a['html_compile_success'] for a in row['attempts'])/len(row['attempts']),
            'browser_render_success_rate':None,'sample_count':len(row['attempts'])}
        return row
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=[pool.submit(trial,pair) for pair in candidates]
        for future in as_completed(pending):
            row=future.result()
            with lock:result['providers'].append(row);save()
            print(json.dumps({k:row.get(k) for k in ('provider','model','status','name','stability')},ensure_ascii=False),flush=True)
    # Local candidates are always available, clearly identified as such.
    if not args.inspect_only:
        for index,spec in enumerate(local_specs(),1):
            folder=out/f'local-{index}';folder.mkdir(exist_ok=True)
            (folder/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf8')
            (folder/'candidate.html').write_text(compile_static_candidate(spec,'啊感觉他就是你看',background_path=args.game),encoding='utf8')
            (folder/'transparent.html').write_text(compile_static_candidate(spec,'啊感觉他就是你看'),encoding='utf8')
        result['local_fallbacks']=[str(out/f'local-{index}/spec.json') for index in (1,2,3)]
    result['settings_unchanged']=hashlib.sha256(args.settings.read_bytes()).hexdigest()==result['settings_sha256']
    result['finished']=datetime.now(timezone.utc).isoformat();save()
    GLOBAL_PROVIDER_SERVICE.shutdown(timeout=2)


if __name__=='__main__':main()
