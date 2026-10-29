"""Run the opt-in voiceprint UI audit against a fresh isolated project copy."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--model',required=True,type=Path)
    parser.add_argument('--runtime',required=True,type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--expect',default='',help='JSON case for the audit (see scoped_voiceprint_audit)')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to((ROOT/'tmp').resolve()):
        raise ValueError('Use a fresh output under this checkout tmp')
    if not args.project.is_file() or not args.runtime.is_file() or not (args.model/'embedding_model.ckpt').is_file():
        raise ValueError('Project, ECAPA model or main runtime missing')
    payload=json.loads(args.project.read_text('utf-8-sig'))
    media=Path(payload['media']['path'])
    if not media.is_file():
        raise ValueError('Project media missing')
    protected={str(args.project.resolve()):sha(args.project),str(media.resolve()):sha(media)}
    out.mkdir(parents=True)
    shutil.copy2(args.project,out/'project.2byteproj')
    shutil.copytree(args.model,out/'models'/'spkrec-ecapa-voxceleb')
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='scoped-voiceprint',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_MAIN_PYTHON=str(args.runtime.resolve()),TWOBYTEASR_DEVELOPER_RUNTIMES='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    if args.expect:
        env['TWOBYTEASR_VOICEPRINT_EXPECT']=args.expect
    for name in ('TWOBYTEASR_STARTUP_OPEN_STUDIO','TWOBYTEASR_STARTUP_RAISE'):
        env.pop(name,None)
    sys.path.insert(0,str(ROOT/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(command,cwd=ROOT,env=env,output=out/'process',timeout=args.timeout)
    path=out/'result.json'
    result=json.loads(path.read_text('utf8')) if path.exists() else {'passed':False,'error':'No audit receipt'}
    result['process_exit']=code
    result['originals_unchanged']=all(Path(path).is_file() and sha(path)==value for path,value in protected.items())
    result['passed']=bool(result.get('passed') and code==0 and result['originals_unchanged']
                          and (not args.exe or result.get('frozen')))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':result['passed'],'checks':len(result.get('checks',[])),
                      'exit':code,'originals_unchanged':result['originals_unchanged'],
                      'error':result.get('error','')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
