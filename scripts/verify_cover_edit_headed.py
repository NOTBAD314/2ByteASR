"""Normal entry in an isolated desktop; copies the project and links cached media read-only."""
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
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--seek-cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--scope',choices=('current','all'),default='current')
    args=parser.parse_args(); out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists(): raise ValueError('Fresh repository tmp output required')
    out.mkdir(parents=True); data=args.project.read_bytes(); (out/'project.2byteproj').write_bytes(data)
    for source in args.seek_cache.resolve().rglob('*'):
        if not source.is_file() or source.suffix=='.lock':continue
        target=out/'seek'/source.relative_to(args.seek_cache.resolve());target.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix.lower() in {'.mkv','.mp4'}:os.link(source,target)
        else:shutil.copy2(source,target)
    env=os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_STARTUP_PROJECT=str(out/'project.2byteproj'),
        TWOBYTEASR_SEEK_CACHE_ROOT=str(out/'seek'),TWOBYTEASR_ACCEPTANCE_SCENARIO='cover-edit-performance',
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_COVER_EDIT_BASELINE='1' if args.baseline else '0',
        TWOBYTEASR_COVER_EDIT_SCOPE=args.scope,
        QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    for key in ('QT_SCALE_FACTOR','QT_ENABLE_HIGHDPI_SCALING','QT_FONT_DPI'):env.pop(key,None)
    from isolated_windows_desktop import run_on_desktop
    cmd=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_on_desktop(cmd,cwd=ROOT,env=env,output=out/'process',timeout=330)
    p=out/'result.json';result=json.loads(p.read_text('utf8')) if p.is_file() else {}
    result.update(exit_code=code,original_unchanged=args.project.read_bytes()==data,
                  original_sha256=hashlib.sha256(data).hexdigest())
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','exit_code','original_unchanged','measurements','error')},ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and result.get('gui_shutdown') and result['original_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
