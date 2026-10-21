"""Normal app entry on a private desktop with an owned project and profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--seek-cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path)
    p.add_argument('--scenario',choices=['window-proofread','compact-overlap'],default='window-proofread')
    args=p.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Fresh repository tmp required')
    if not (args.seek_cache/'v2').is_dir():raise ValueError('Pass seek cache root containing v2')
    out.mkdir(parents=True);data=args.project.read_bytes();(out/'project.2byteproj').write_bytes(data)
    for source in args.seek_cache.resolve().rglob('*'):
        if not source.is_file() or source.suffix=='.lock':continue
        target=out/'seek'/source.relative_to(args.seek_cache.resolve());target.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix.lower() in {'.mkv','.mp4'}:os.link(source,target)
        else:shutil.copy2(source,target)
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO=args.scenario,
        TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),TWOBYTEASR_SEEK_CACHE_ROOT=str(out/'seek'),
        TWOBYTEASR_INVOKER_CWD=str(ROOT),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    if args.exe and args.exe.resolve()==ROOT/'2ByteASR.exe':
        cmd=[sys.executable,str(ROOT/'scripts/verify_desktop_entry_bridge.py'),str(out),json.dumps(cmd)]
    code=run_on_desktop(cmd,cwd=ROOT,env=env,output=out/'process',timeout=480)
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    result.update(exit_code=code,original_unchanged=args.project.read_bytes()==data,
        original_sha256=hashlib.sha256(data).hexdigest())
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(dict(passed=result.get('passed'),checks=len(result.get('checks',[])),
        failed=[x for x in result.get('checks',[]) if not x['passed']],error=result.get('error'),exit=code),ensure_ascii=False))
    return 0 if result.get('passed') and result.get('gui_shutdown') and code==0 and result['original_unchanged'] else 1

if __name__=='__main__':raise SystemExit(main())
