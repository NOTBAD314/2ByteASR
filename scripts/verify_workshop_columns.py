"""Verify workshop column geometry and list edges on a private Windows desktop."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',type=Path);p.add_argument('--scale',default='1');args=p.parse_args()
    out=args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):raise ValueError('Use a fresh source/tmp directory')
    out.mkdir(parents=True);(out/'startup.2byteproj').write_text('{}','utf8')
    env=dict(os.environ,QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR=args.scale,QT_ENABLE_HIGHDPI_SCALING='0',QT_FONT_DPI='96',
        TWOBYTEASR_WORKSHOP_COLUMNS_ONLY='1',TWOBYTEASR_ACCEPTANCE_SCENARIO='vm2-model-settings',TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_STARTUP_PROJECT=str(out/'startup.2byteproj'),TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_TEST_ROOT=str(out/'profile'),LOCALAPPDATA=str(out/'profile/local'),APPDATA=str(out/'profile/roaming'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
    from audit_launch_bridge import run_audit_on_desktop
    command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
    code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=out,timeout=240,receipt=out/'result.json')
    result=json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    print(json.dumps(dict(exit_code=code,passed=result.get('passed'),checks=result.get('checks_passed'),output=str(out)),ensure_ascii=False))
    return 0 if code==0 and result.get('passed') else 1
if __name__=='__main__':raise SystemExit(main())

