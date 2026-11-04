"""Real application, copied library, private Windows desktop, source or EXE."""
import argparse,json,os,shutil,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--cycles',type=int,default=3)
    parser.add_argument('--functional',action='store_true')
    parser.add_argument('--warm-index',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):parser.error('Fresh source/tmp output required')
    out.mkdir(parents=True)
    shutil.copytree(args.inputs/'Projects',out/'library')
    shutil.copy2(args.inputs/'stress-4484.2byteproj',out/'library/stress-4484.2byteproj')
    settings=out/'local/2ByteASR/SubtitleStudioPreview';settings.mkdir(parents=True)
    (settings/'settings.json').write_text(json.dumps(dict(project_root=str(out/'library'),auto_cover=False,
        studio_preferences={'recovery_policy':'official'},recent_projects=[])),encoding='utf-8')
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='library-performance' if args.exe else 'review-editor',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'library/stress-4484.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_STARTUP_SIZE='1600x950',TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',
        TWOBYTEASR_NAVIGATION_TRACE='1',PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',LIBRARY_PERF_CYCLES=str(args.cycles))
    env.pop('TWOBYTEASR_STARTUP_OPEN_STUDIO',None)
    if args.functional:env['LIBRARY_PERF_FUNCTIONAL']='1'
    if args.warm_index:
        data=json.loads(args.warm_index.read_text('utf-8'))
        parent=Path(next(iter(data['projects'])))
        while parent.name!='library' and parent.parent!=parent:parent=parent.parent
        if parent.name!='library':raise ValueError('Warm index must belong to an isolated library fixture')
        def remap(value):
            if isinstance(value,dict):return {remap(k):remap(v) for k,v in value.items()}
            if isinstance(value,list):return [remap(v) for v in value]
            if isinstance(value,str) and value.startswith(str(parent)):return str(out/'library')+value[len(str(parent)):]
            return value
        (settings/'library-index.json').write_text(json.dumps(remap(data),ensure_ascii=False),'utf-8')
    if args.baseline:env['LIBRARY_BASELINE_SOURCE']=str(args.baseline.resolve())
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'scripts/library_performance_entry.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=1800)
    result=json.loads((out/'result.json').read_text('utf-8')) if (out/'result.json').exists() else {}
    result['exit_code']=code
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:result.get(k) for k in ('passed','error','exit_code','operations')},ensure_ascii=False))
    return 0 if code==0 and result.get('passed') and result.get('gui_shutdown') else 1
if __name__=='__main__':raise SystemExit(main())
