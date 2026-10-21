"""Private-desktop Studio check on a read-only copy of the requested project."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(out):
    from twobyteasr.acceptance.compact_overlap_audit import run
    return run(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--seek-cache',type=Path)
    args=parser.parse_args(); out=args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp'): raise ValueError('Repository tmp output required')
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup-trace.jsonl'),QT_QPA_PLATFORM='windows')
    if args.child: return child(out)
    if out.exists(): raise ValueError('Fresh output required')
    out.mkdir(parents=True)
    original=args.project.resolve(); data=original.read_bytes()
    (out/'original.2byteproj').write_bytes(data)
    (out/'repaired.2byteproj').write_bytes(data)
    if args.seek_cache:
        source_cache=args.seek_cache.resolve()
        if not source_cache.is_relative_to(ROOT/'tmp'):
            raise ValueError('Use an owned validation cache')
        cache=out/'seek-cache'
        for src in source_cache.rglob('*'):
            if not src.is_file(): continue
            dst=cache/src.relative_to(source_cache); dst.parent.mkdir(parents=True,exist_ok=True)
            if src.suffix in ('.mkv','.mp4'): os.link(src,dst)
            else: shutil.copy2(src,dst)
        os.environ['TWOBYTEASR_SEEK_CACHE_ROOT']=str(cache)
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop([sys.executable,'-X','utf8',str(Path(__file__).resolve()),
        '--child','--output',str(out)],cwd=ROOT,env=os.environ.copy(),output=out,timeout=300)
    result=json.loads((out/'result.json').read_text('utf8'))
    result['exit_code']=code
    result['original_sha256']=hashlib.sha256(data).hexdigest()
    result['original_unchanged']=original.read_bytes()==data
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','exit_code','original_unchanged','error')},ensure_ascii=False))
    return 0 if result['passed'] and result['original_unchanged'] and code==0 else 1


if __name__=='__main__': raise SystemExit(main())
