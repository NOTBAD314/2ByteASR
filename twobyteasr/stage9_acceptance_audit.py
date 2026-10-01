"""Offline, no-GUI smoke test executed inside the shipped interpreter."""
from __future__ import annotations
import contextlib
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


def main(output_directory: str) -> int:
    output=Path(output_directory).resolve()
    if not output.is_relative_to(Path.cwd().resolve()/'tmp'):
        raise ValueError("ASR self-test output must be under cwd/tmp")
    output.mkdir(parents=True,exist_ok=True)
    result={"frozen":bool(getattr(sys,'frozen',False)),"real_provider_requests":0,"cli_processes":0}
    for key,folder in (('LOCALAPPDATA','local'),('APPDATA','roaming'),('TEMP','temp'),('TMP','temp')):
        directory=output/folder;directory.mkdir(exist_ok=True);os.environ[key]=str(directory)
    os.environ['2BYTEASR_USER_DATA_ROOT']=str(output/'local'/'2ByteASR')
    with (output/'runtime.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:
            from . import settings as settings_module, llm_config
            from .asr_provider_snapshot import resolve_provider_snapshot
            config=copy.deepcopy(settings_module.DEFAULT_SETTINGS)
            llm_config.activate_ai_service(config,'deepseek',unified=True)
            llm_config.update_active_profile(config,model='deepseek-v4-pro',protocol='openai_compatible_chat',unified=True)
            llm_config.read_scoped_api_key=lambda *a,**k:('offline-selftest-placeholder','fixture')
            settings_module.load_runtime_settings=lambda *a,**k:(copy.deepcopy(config),str(output/'memory-only.json'),[])
            snapshot=resolve_provider_snapshot(config)
            import subtitle_core as core
            import moss_firered_pipeline as pipeline
            from . import grouping, polishing, ai_providers
            from .runtime import RuntimeContext,activate_runtime_context
            from .provider_service import GLOBAL_PROVIDER_SERVICE
            import requests
            def forbidden(*args,**kwargs):
                raise RuntimeError('Network and CLI are forbidden in packaged ASR self-test')
            requests.sessions.Session.request=forbidden
            ai_providers.GrokCLIProvider=forbidden
            ai_providers.AntigravityCLIProvider=forbidden
            sent=[]
            def sender(messages,**kwargs):
                sent.append({'stage':kwargs['stage'],'provider':kwargs['provider'],'model':kwargs['model'],'url':kwargs['url']})
                data=json.loads(messages[-1]['content'])
                return json.dumps({'cues':[{'id':1,'edits':[]}]}) if kwargs['stage']=='polished' else json.dumps({'boundaries':[data['total_length']]})
            polishing.post_chat_completion=sender
            grouping.post_chat_completion=sender
            core.RUNTIME_SETTINGS={'models':{'ai_service':'grok_account','group_transport':'grok_cli'},'switches':{}}
            context=RuntimeContext(provider_snapshot=snapshot,event_log_path=str(output/'events.jsonl'))
            cache_dir=output/'cache';cache_dir.mkdir(exist_ok=True)
            cache={'cache_dir':str(cache_dir),'identity':{'fixture':'packaged-stage9'}}
            rows=[core.SpeechSegment(1,0,2,'测试字幕',.9,[],speaker='S01')]
            with activate_runtime_context(context,legacy=core):
                pipeline._preflight_cloud_stages(core)
                polishing.call_correction_api(rows,[],'','','fixture','fixture',[],[],[])
                first=core.group_subtitles(rows,cache_context=cache,max_workers=1)
                requests_before=len(sent)
                second=core.group_subtitles(rows,cache_context=cache,max_workers=1)
            result.update(snapshot=snapshot.public_identity(), sent=sent,
                          same_http_snapshot=all(x['provider']=='deepseek' and x['model']==snapshot.model for x in sent),
                          exact_text=''.join(x.text for x in first)==''.join(x.text for x in second)==rows[0].text,
                          cache_replay_requests=len(sent)-requests_before,
                          provider_idle=GLOBAL_PROVIDER_SERVICE.wait_for_idle(1))
            from .build_identity import load_build_identity
            result['build_identity']=asdict(load_build_identity())
            result['passed']=bool(result['same_http_snapshot'] and result['exact_text'] and len(sent)==2
                                  and result['cache_replay_requests']==0 and result['provider_idle'])
        except Exception as exc:
            import traceback
            traceback.print_exc()
            result.update(passed=False,error_type=type(exc).__name__)
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result.get('passed') else 1
