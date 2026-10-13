"""Explicit real-network acceptance; ordinary pytest remains offline.

Every item calls the production repository adapter, sequentially. No global
model/cache is borrowed. This verifies weights, not runtime installation or ASR.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import hashlib
from datetime import datetime,timezone


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--models',default='')
    p.add_argument('--allow-full-download',action='store_true')
    p.add_argument('--resume',action='store_true',help='明确恢复已有验收；不记为从零下载')
    p.add_argument('--mode',default='AUTO',choices=['AUTO','MODELSCOPE','HF_OFFICIAL','HF_MIRROR'])
    args=p.parse_args()
    if not args.allow_full_download:p.error('需要显式 --allow-full-download；完整清单约 73 GiB')
    root=Path(__file__).resolve().parents[1]
    out=args.output.resolve()
    if not out.is_relative_to(root/'tmp'):p.error('验收目录必须在本仓库 tmp 内')
    if any(x.is_symlink() or (x.exists() and getattr(x.lstat(),'st_file_attributes',0)&1024) for x in (out,*out.parents)):
        p.error('验收目录不能经过链接或 junction')
    if (out/'models').exists() and any((out/'models').rglob('*')) and not args.resume:
        p.error('模型/暂存目录非空。请选新目录，或显式 --resume；恢复记录不冒充从零下载')
    for key in list(os.environ):
        if key.upper().startswith(('HF_','HUGGING_FACE_','MODELSCOPE_','TORCH_','XET_','TWOBYTEASR_','2BYTEASR_')) or key.upper().endswith(('_TOKEN','_API_KEY')):
            os.environ.pop(key,None)
    out.mkdir(parents=True,exist_ok=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out),QT_QPA_PLATFORM='offscreen',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      TWOBYTEASR_DOWNLOAD_PYTHON=sys.executable)
    sys.path.insert(0,str(root))
    from twobyteasr.test_isolation import install,require_isolated_paths
    install()
    for key,part in {'HF_HUB_CACHE':'hf-cache/hub','HUGGINGFACE_HUB_CACHE':'hf-cache/hub','HF_XET_CACHE':'hf-cache/xet',
                     'TRANSFORMERS_CACHE':'hf-cache/transformers','XDG_CACHE_HOME':'xdg','HOME':'profile','NETRC':'empty-netrc'}.items():
        os.environ[key]=str(out/part)
    require_isolated_paths('full-model-download')
    from twobyteasr.repository_download import download_model,planned_sources,validate_files
    from twobyteasr.model_download_diagnostic import network_facts
    from twobyteasr.download_diagnostics import redact
    lock=json.loads((root/'dependencies.lock.json').read_text('utf-8-sig'))
    keys=args.models.split(',') if args.models else list(lock['models'])
    if any(k not in lock['models'] for k in keys):p.error('未知模型')
    files=['dependencies.lock.json','twobyteasr/repository_download.py','scripts/download_file_fast.py']
    results=dict(network=network_facts(),started=time.time(),models=[],weight_only=True,resume=args.resume,mode=args.mode,
        inputs={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},cache_policy='new isolated directory; retries separately marked')
    report=out/('acceptance-recovery-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.json' if args.resume else 'acceptance.json')
    for key in keys:
        spec=lock['models'][key];destination=out/'models'/Path(spec['path']).name
        initial=[f for f in spec['required_files'] if (destination/f).exists()]
        row=dict(model=key,repository=spec['repository'],revision=spec['revision'],initial_files=initial,
                 first_install=not args.resume and not initial,started=time.time(),complete_download='RUNNING',load='NOT VERIFIED',inference='NOT VERIFIED')
        results['models'].append(row)
        report.write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
        required=spec.get('download_bytes',0)*2+10*1024**3
        try:
            if shutil.disk_usage(out).free<required:raise OSError('磁盘空间不足：保留当前模型双份空间和 10 GiB 余量')
            from contextlib import redirect_stdout,redirect_stderr
            with (out/(key+'.log')).open('w',encoding='utf8') as log,redirect_stdout(log),redirect_stderr(log):
                selected=download_model(model_key=key,spec=spec,destination=destination,mode=args.mode,staging_root=out/'models/.downloads')
                manifest=next(x for x in planned_sources(spec,args.mode) if x.mode==selected)
                ok,reason=validate_files(destination,manifest)
                if not ok:raise RuntimeError(reason)
            receipt=json.loads((destination/'.2byteasr-source.json').read_text('utf8'))
            row.update(complete_download='PASS',integrity='PASS',source=selected,source_revision=manifest.revision,source_repository=manifest.repository,files=receipt.get('files',[]),
                       actual_network_payload_bytes=sum(x.get('transfer',{}).get('network_payload_bytes',0) for x in receipt.get('files',[])),
                       installed_bytes=sum((destination/f).stat().st_size for f in manifest.files))
        except Exception as exc:row.update(complete_download='FAIL',error=redact(str(exc)))
        row['elapsed_s']=round(time.time()-row['started'],3)
        report.write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps({k:v for k,v in row.items() if k!='files'},ensure_ascii=False),flush=True)
    results['finished']=time.time()
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
    return 0 if all(x['complete_download']=='PASS' for x in results['models']) else 1


if __name__=='__main__':raise SystemExit(main())
