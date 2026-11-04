"""Verify a copied real edited project through the normal source/frozen entry."""
import argparse,json,os,shutil,sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seek-cache',type=Path,required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp') or not args.seek_cache.resolve().is_relative_to(root/'tmp'):
        raise ValueError('Fresh owned tmp output and owned seek cache required')
    out.mkdir(parents=True);project=out/'copy.2byteproj';shutil.copy2(args.project,project)
    spec=dict(project=str(project),positions_ms=[300,1695,3100,3650,7800,12350,13000,17250,42658,112658,212658,312658,412658,464000,466000,470000,474000],
              play_from_ms=[2200,11500,464500])
    (out/'input.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),'utf-8')
    env=os.environ.copy();env.update(TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out),TWOBYTEASR_ACCEPTANCE_SCENARIO='timeline-sync',
        TWOBYTEASR_STARTUP_PROJECT=str(project),TWOBYTEASR_SEEK_CACHE_ROOT=str(args.seek_cache.resolve()),
        TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=300)
    result=json.loads((out/'result.json').read_text('utf-8')) if (out/'result.json').exists() else dict(passed=False)
    result['process_exit']=code;result['passed']=bool(result.get('passed') and result.get('gui_shutdown') and code==0)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(dict(output=str(out),passed=result['passed'],checks=len(result.get('checks',[])),error=result.get('error')),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
