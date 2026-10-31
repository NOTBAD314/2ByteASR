"""Merged daily UI: normal entry, generated media, isolated data, no provider calls."""
import argparse,json,os,subprocess,sys
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('home','language'),required=True)
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):parser.error('fresh output under repository tmp required')
    out.mkdir(parents=True)
    from twobyteasr.acceptance.completion_todo_audit import build_tasks
    busy,_=build_tasks(out)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(busy[1]),TWOBYTEASR_INVOKER_CWD=str(root),TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_ACCEPTANCE_SCENARIO='completion-todo',TWOBYTEASR_UI_MERGE_AUDIT=args.mode,
        TWOBYTEASR_DIAGNOSTIC_NO_PLAYER='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(root/'quick_start.py')]
    code=run_on_desktop(command,cwd=root,env=env,output=out/'process',timeout=180)
    path=out/'result.json';result=json.loads(path.read_text('utf-8')) if path.exists() else {}
    result['process_exit']=code;path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    passed=code==0 and result.get('passed') and result.get('gui_shutdown')
    print(json.dumps(dict(passed=bool(passed),checks=len(result.get('checks',[])),error=result.get('error'),output=str(out)),ensure_ascii=False))
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
