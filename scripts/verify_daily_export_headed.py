"""Run exact frozen export code with an isolated normal application profile."""
import argparse,json,os,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=Path(__file__).resolve().parents[1];out=a.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):p.error('Choose a new source/tmp directory')
    out.mkdir(parents=True)
    env=dict(os.environ,TWOBYTEASR_TEST_ROOT=str(out),TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='daily-export',TWOBYTEASR_INVOKER_CWD=str(root),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',QT_QPA_PLATFORM='windows',PYTHONUTF8='1',HF_HUB_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    code=run_on_desktop([str(a.exe.resolve())],cwd=root,env=env,output=out/'process',timeout=300)
    r=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    r['process_exit']=code;r['passed']=bool(r.get('passed') and r.get('gui_shutdown') and code==0)
    (out/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(r,ensure_ascii=False));return 0 if r['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
